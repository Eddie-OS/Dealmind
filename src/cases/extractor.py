"""Stage 11：三轨入库提取器（judge_auto / coach_auto / manual）。

设计要点：
- 与 session.py 解耦：本模块只读 DialogueState + 操作 DB，不发事件。
- 每条 case 写入失败仅 log，不抛出，避免破坏 session 主流程。
- session_id 是 sessions.id (TEXT)；persona_id 可空（人设可能未入库）。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from src.schema import DialogueState, Turn
from src.storage import db as dbm

logger = logging.getLogger(__name__)

# 与 PRD 一致：>= 8.0 视为高分会话
HIGH_SCORE_THRESHOLD: float = 8.0

# coach_auto 提取每条 what_worked 时，围绕命中 round 前后扩展几条上下文
COACH_CONTEXT_RADIUS: int = 1


# ---------------------------------------------------------------
# 对话片段序列化
# ---------------------------------------------------------------

def _serialize_turn(t: Turn) -> dict[str, Any]:
    """把 Turn 转成案例库 dialogue_excerpt_json 的一行。"""
    return {
        "idx": t.idx,
        "speaker": t.speaker,
        "content": t.content,
        "stage": (t.metadata or {}).get("stage", ""),
    }


def _serialize_dialogue(turns: list[Turn]) -> list[dict[str, Any]]:
    return [_serialize_turn(t) for t in turns]


def _persona_tags_from_state(state: DialogueState) -> list[str]:
    """从 persona_profile 抽 4-6 个轻量标签：性别 / 年龄段 / 角色 / 核心痛点。"""
    p = state.persona_profile
    tags: list[str] = []
    if getattr(p, "gender", None):
        tags.append(str(p.gender))
    age = getattr(p, "age", None)
    if isinstance(age, int) and age > 0:
        if age < 25:
            tags.append("青年")
        elif age < 40:
            tags.append("青壮")
        elif age < 55:
            tags.append("中年")
        else:
            tags.append("中老年")
    if getattr(p, "role", None):
        tags.append(str(p.role))
    # 痛点 / 关键需求字段在 PersonaProfile 可能叫法不一，extra='allow' 后兜底
    for key in ("pain_points", "needs", "interests"):
        v = getattr(p, key, None)
        if isinstance(v, list) and v:
            tags.append(str(v[0]))
            break
    return [t for t in tags if t]


def _short_outcome_label(outcome: str) -> str:
    return {
        "SUCCESS": "成单",
        "DEAL": "成单",
        "FAILED": "未成单",
        "FAIL": "未成单",
        "TIMEOUT": "超时未决",
        "WALK_AWAY": "客户离场",
    }.get(outcome or "", outcome or "未知")


# ---------------------------------------------------------------
# 轨 A：judge_auto（高分整场归档）
# ---------------------------------------------------------------

def extract_judge_auto_case(
    conn: sqlite3.Connection,
    state: DialogueState,
    *,
    persona_id: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """若 dialogue_quality_score >= 阈值，则归档整场对话。

    返回新建的 case dict，或 None（不达阈值 / 异常）。
    """
    try:
        score = float(getattr(state.judge_feedback, "dialogue_quality_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if score < HIGH_SCORE_THRESHOLD:
        return None

    excerpt = _serialize_dialogue(state.full_history)
    outcome_zh = _short_outcome_label(state.outcome)
    persona_name = getattr(state.persona_profile, "name", "") or "未命名人设"
    topic = state.topic or "未命名场景"

    title = f"[{score:.1f}/10·{outcome_zh}] {persona_name} × {topic}"

    why = (
        f"Judge 评定整场对话质量 {score:.1f}/10（>= {HIGH_SCORE_THRESHOLD}），"
        f"结局 {outcome_zh}，共 {state.round_idx} 轮，"
        f"销冠在响应度 / 证据 / 异议处理上均达到合格线，整段适合作为正面范例。"
    )

    try:
        return dbm.create_sales_case(
            conn,
            source="judge_auto",
            title=title,
            session_id=state.session_id,
            scene=topic,
            persona_id=persona_id,
            persona_tags=_persona_tags_from_state(state),
            dialogue_excerpt=excerpt,
            raw_content=None,
            why_excellent=why,
            tags=["judge", outcome_zh, f"score:{score:.1f}"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("judge_auto case 写入失败 session=%s: %s",
                       state.session_id, exc)
        return None


# ---------------------------------------------------------------
# 轨 B：coach_auto（what_worked 单条策略）
# ---------------------------------------------------------------

def _slice_around(turns: list[Turn], target_round: int) -> list[Turn]:
    """以 target_round 为中心，取 ±COACH_CONTEXT_RADIUS 轮的销冠/人设上下文。

    round 在 metadata.round 上；若无，则退化到 idx 顺序匹配。
    """
    if not turns:
        return []
    lo = target_round - COACH_CONTEXT_RADIUS
    hi = target_round + COACH_CONTEXT_RADIUS

    matched: list[Turn] = []
    for t in turns:
        r = (t.metadata or {}).get("round")
        if isinstance(r, int) and lo <= r <= hi:
            matched.append(t)
    if matched:
        return matched

    # 没有 round 元数据：用 idx 近邻（每轮约 2 条 turn）
    center_idx = max(0, (target_round - 1) * 2)
    half = COACH_CONTEXT_RADIUS * 2 + 1
    return turns[max(0, center_idx - half): center_idx + half + 1]


def extract_coach_auto_cases(
    conn: sqlite3.Connection,
    state: DialogueState,
    *,
    persona_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """遍历 coach_review.what_worked，每条生成 1 个 case。"""
    review = state.coach_review
    if review is None:
        return []
    items = list(review.what_worked or [])
    if not items:
        return []

    persona_name = getattr(state.persona_profile, "name", "") or "未命名人设"
    topic = state.topic or "未命名场景"
    tags_persona = _persona_tags_from_state(state)
    created: list[dict[str, Any]] = []

    for it in items:
        if not isinstance(it, dict):
            continue
        round_no = it.get("round")
        try:
            round_no_i = int(round_no) if round_no is not None else 0
        except (TypeError, ValueError):
            round_no_i = 0
        strategy = str(it.get("strategy") or "").strip() or "未命名策略"
        why_effective = str(it.get("why_effective") or it.get("why") or "").strip()
        evidence = str(it.get("evidence") or "").strip()

        excerpt_turns = _slice_around(state.full_history, round_no_i) if round_no_i else []
        excerpt = _serialize_dialogue(excerpt_turns)
        title = f"[策略] {strategy} · R{round_no_i or '?'} · {persona_name}"

        why = why_effective or "Coach 标记为有效策略，但未给出具体原因。"
        if evidence:
            why = f"{why}\n\n关键证据：{evidence}"

        try:
            case = dbm.create_sales_case(
                conn,
                source="coach_auto",
                title=title,
                session_id=state.session_id,
                scene=topic,
                persona_id=persona_id,
                persona_tags=tags_persona,
                dialogue_excerpt=excerpt,
                raw_content=None,
                why_excellent=why,
                tags=["coach", strategy[:20]],
            )
            created.append(case)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "coach_auto case 写入失败 session=%s round=%s: %s",
                state.session_id, round_no_i, exc,
            )

    return created


# ---------------------------------------------------------------
# 统一入口：在 session.py 内 coach 复盘完成后调用
# ---------------------------------------------------------------

def auto_extract_cases(
    conn: sqlite3.Connection,
    state: DialogueState,
    *,
    persona_id: Optional[int] = None,
) -> dict[str, int]:
    """两轨同时跑；返回 {judge_auto: n, coach_auto: m}（已 commit）。"""
    result = {"judge_auto": 0, "coach_auto": 0}
    try:
        case = extract_judge_auto_case(conn, state, persona_id=persona_id)
        if case:
            result["judge_auto"] = 1
        coach_cases = extract_coach_auto_cases(conn, state, persona_id=persona_id)
        result["coach_auto"] = len(coach_cases)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_extract_cases 整体异常 session=%s: %s",
                       state.session_id, exc)
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
    return result


# ---------------------------------------------------------------
# 轨 C：manual（会话详情页点「收藏为案例」）
# ---------------------------------------------------------------

def save_manual_case_from_turn(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_idx: int,
    title: str,
    why_excellent: Optional[str] = None,
    tags: Optional[list[str]] = None,
    context_radius: int = 2,
) -> dict[str, Any]:
    """从指定 session + 指定 turn 出发，抽 ±context_radius 条上下文存为案例。

    上层 routes_sessions.py 包装为 POST /api/sessions/{id}/cases。
    """
    turns_rows = dbm.list_turns(conn, session_id=session_id)
    if not turns_rows:
        raise ValueError("session 无对话记录")

    session_row = dbm.get_session_by_id(conn, session_id)
    if not session_row:
        raise ValueError(f"session {session_id} 不存在")

    persona_id = session_row.get("persona_id")
    scene = session_row.get("topic") or ""

    # 命中目标 turn
    target_pos: Optional[int] = None
    for i, t in enumerate(turns_rows):
        if int(t.get("idx", -1)) == int(turn_idx):
            target_pos = i
            break
    if target_pos is None:
        raise ValueError(f"turn_idx={turn_idx} 不在 session 内")

    lo = max(0, target_pos - context_radius)
    hi = min(len(turns_rows), target_pos + context_radius + 1)
    excerpt = [
        {
            "idx": int(r.get("idx", 0)),
            # DB 列名是 role，输出统一为 speaker 与 Turn schema 对齐
            "speaker": r.get("role") or r.get("speaker"),
            "content": r.get("content") or "",
            "stage": r.get("stage") or (r.get("metadata") or {}).get("stage", ""),
        }
        for r in turns_rows[lo:hi]
    ]

    return dbm.create_sales_case(
        conn,
        source="manual",
        title=title or f"[手动收藏] {scene} · turn {turn_idx}",
        session_id=session_id,
        scene=scene,
        persona_id=persona_id,
        persona_tags=[],
        dialogue_excerpt=excerpt,
        raw_content=None,
        why_excellent=why_excellent or "",
        tags=tags or ["manual"],
    )
