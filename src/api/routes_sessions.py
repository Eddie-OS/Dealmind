"""Stage 6a：sessions REST 端点。

4 个接口：
    POST   /api/sessions             创建（参数完整含 opening_line / who_speaks_first）
    POST   /api/sessions/{id}/start  触发 SessionRunner 实际跑
    POST   /api/sessions/{id}/cancel set cancel_flag
    GET    /api/sessions/{id}        基本信息（DB 行 + 运行时 status）

注意：实际事件流走 WebSocket `/ws/session/{id}/live`，REST 这边只做控制面。
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.api.session_runner_async import (
    SessionRunner,
    get_runner,
    register_runner,
    release_session_slot,
    remove_runner,
    session_slot_stats,
    try_acquire_session_slot,
)
from src.config import PROJECT_ROOT
from src.loaders import load_text_file
from src.persona.loader import persona_from_db_row
from src.session import OPENING_TEMPLATES
from src.storage import db as storage_db
from src.utils import now_timestamp


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ============================================================
# Request / Response Models
# ============================================================


SUPPORTED_LANGUAGES = ("zh-CN", "en-US", "es-ES", "ar-SA", "id-ID")


class CreateSessionRequest(BaseModel):
    persona_id: int = Field(..., description="必填，personas 表主键")
    topic: str = Field("学习平板销售模拟", max_length=200)
    product_kb_id: Optional[int] = None
    enterprise_kb_id: Optional[int] = None
    handbook_id: Optional[int] = Field(
        None,
        description="可选，绑定的产品手册 id（Handbook Analysis）。"
        "若不传且全库只有一份 ready Handbook，运行时会自动套用。",
    )
    max_rounds: int = Field(50, ge=8, le=80)
    judge_interval: int = Field(3, ge=1, le=10)
    # business_stages v0.2 Q1：默认 2（原 3），与 prompts/business_stages.yaml
    # global_rules.memory_refresh_interval_default 保持一致。
    memory_interval: int = Field(2, ge=1, le=10)
    who_speaks_first: str = Field("sales", pattern="^(sales|persona)$")
    opening_line: Optional[str] = Field(None, max_length=400)
    opening_template_idx: Optional[int] = Field(None, ge=0, le=10)
    max_rounds_floor: Optional[int] = Field(
        None, ge=0,
        description="护栏轮数；None 时默认 max(3, round(max_rounds*0.15))",
    )
    language: str = Field(
        "zh-CN",
        description="对话语言：zh-CN | en-US | es-ES | ar-SA | id-ID",
    )


class SessionInfo(BaseModel):
    id: str
    persona_id: Optional[int]
    product_kb_id: Optional[int]
    enterprise_kb_id: Optional[int]
    handbook_id: Optional[int] = None
    topic: str
    opening_line: str
    max_rounds: int
    status: str
    config: dict
    summary: dict
    runtime_status: Optional[str] = None
    started_at: Optional[str]
    ended_at: Optional[str]
    created_at: str
    updated_at: str


# ============================================================
# Helpers
# ============================================================


def _resolve_opening_line(req: CreateSessionRequest) -> str:
    """根据请求决定开场白文本（仅 who_speaks_first='sales' 用）。

    优先级：opening_line（自定义）> opening_template_idx > **留空交给 LLM 现场生成**。
    返回空字符串时，run_session 会用 generate_opening_line 按会话语言现场生成开场招呼。
    """
    if req.who_speaks_first != "sales":
        return ""
    if req.opening_line and req.opening_line.strip():
        return req.opening_line.strip()
    if req.opening_template_idx is not None:
        idx = req.opening_template_idx
        if 0 <= idx < len(OPENING_TEMPLATES):
            return OPENING_TEMPLATES[idx]
        raise HTTPException(
            status_code=400,
            detail=f"opening_template_idx 必须在 0~{len(OPENING_TEMPLATES) - 1}",
        )
    return ""


def _serialize_session(row: dict, *, runtime_status: Optional[str] = None) -> dict:
    """把 db row 转 API 返回 dict，运行时 status 单独字段。"""
    return {
        "id": row["id"],
        "persona_id": row.get("persona_id"),
        "product_kb_id": row.get("product_kb_id"),
        "enterprise_kb_id": row.get("enterprise_kb_id"),
        "handbook_id": row.get("handbook_id"),
        "provider_id": row.get("provider_id"),
        "topic": row.get("topic") or "",
        "opening_line": row.get("opening_line") or "",
        "max_rounds": row.get("max_rounds") or 0,
        "status": row.get("status") or "pending",
        "config": row.get("config") or {},
        "summary": row.get("summary") or {},
        "runtime_status": runtime_status,
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ============================================================
# Endpoints
# ============================================================


@router.get("", summary="筛选 + 分页列出 sessions")
def list_sessions(
    persona_id: Optional[int] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    outcome: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> dict:
    """会话历史列表。

    - 支持 persona_id / status / outcome 过滤
    - 分页：page 从 1 开始，size 每页条数
    - 返回 {items, total, page, size}，items 与 GET /{id} 字段一致
    """
    offset = (page - 1) * size
    with storage_db.connection_scope() as conn:
        rows, total = storage_db.list_sessions(
            conn,
            persona_id=persona_id,
            status=status_,
            outcome=outcome,
            limit=size,
            offset=offset,
        )
    items = [_serialize_session(r) for r in rows]
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session(req: CreateSessionRequest) -> dict:
    """创建一条 session 记录（状态 pending），不立即开跑。

    前端拿到 session_id 后跳转到对话现场页，再调 POST /start 启动。
    """
    with storage_db.connection_scope() as conn:
        persona_row = storage_db.get_persona_by_id(conn, req.persona_id)
    if not persona_row:
        raise HTTPException(404, f"persona id={req.persona_id} 不存在")

    if req.product_kb_id is not None:
        with storage_db.connection_scope() as conn:
            if not storage_db.get_kb_by_id(conn, req.product_kb_id):
                raise HTTPException(404, f"product_kb_id={req.product_kb_id} 不存在")
    if req.handbook_id is not None:
        with storage_db.connection_scope() as conn:
            if not storage_db.get_handbook(conn, req.handbook_id):
                raise HTTPException(404, f"handbook_id={req.handbook_id} 不存在")
    if req.enterprise_kb_id is not None:
        with storage_db.connection_scope() as conn:
            if not storage_db.get_kb_by_id(conn, req.enterprise_kb_id):
                raise HTTPException(404, f"enterprise_kb_id={req.enterprise_kb_id} 不存在")

    opening_line = _resolve_opening_line(req)
    session_id = f"session_{now_timestamp()}_p{req.persona_id}"

    # Stage 15d：把 floor 从"前 15% 轮强制 CONTINUE"降低为"最多前 3 轮"，
    # 避免 max_rounds=50 时前 8 轮把客户的提前成交/离场信号一律压住。
    floor = (
        req.max_rounds_floor
        if req.max_rounds_floor is not None
        else min(3, max(1, req.max_rounds // 10))
    )

    language = req.language if req.language in SUPPORTED_LANGUAGES else "zh-CN"
    config = {
        "who_speaks_first": req.who_speaks_first,
        "judge_interval": req.judge_interval,
        "memory_interval": req.memory_interval,
        "max_rounds_floor": floor,
        "opening_template_idx": req.opening_template_idx,
        "language": language,
    }

    with storage_db.connection_scope() as conn:
        row = storage_db.create_session(
            conn,
            session_id=session_id,
            persona_id=req.persona_id,
            product_kb_id=req.product_kb_id,
            enterprise_kb_id=req.enterprise_kb_id,
            handbook_id=req.handbook_id,
            provider_id=None,
            topic=req.topic,
            opening_line=opening_line,
            max_rounds=req.max_rounds,
            config=config,
        )

    logger.info("session created: %s persona=%s rounds=%d floor=%d",
                session_id, persona_row["name"], req.max_rounds, floor)
    return _serialize_session(row, runtime_status="pending")


@router.post("/{session_id}/start", status_code=status.HTTP_202_ACCEPTED)
async def start_session(session_id: str) -> dict:
    """触发引擎在线程池开跑。幂等：同一 session 多次 start 返回当前 runner 状态。"""
    with storage_db.connection_scope() as conn:
        row = storage_db.get_session_by_id(conn, session_id)
    if not row:
        raise HTTPException(404, f"session {session_id!r} 不存在")
    if row.get("status") not in ("pending", "running"):
        raise HTTPException(
            409,
            f"session 当前状态为 {row.get('status')!r}，不可重复 start",
        )

    existing = get_runner(session_id)
    if existing is not None:
        return {"session_id": session_id, "runtime_status": existing.status,
                "message": "session 已在跑，可直接连 WebSocket 拉取事件"}

    # 取 persona
    with storage_db.connection_scope() as conn:
        persona_row = storage_db.get_persona_by_id(conn, row["persona_id"])
    if not persona_row:
        raise HTTPException(500, f"session 引用的 persona id={row['persona_id']} 已被删除")
    persona = persona_from_db_row(persona_row)

    # 产品资料：Stage 6a 直接读 data/product.md（Stage 6b 会切到 RAG）
    product_path = PROJECT_ROOT / "data" / "product.md"
    try:
        product_text = load_text_file(str(product_path))
    except Exception:
        product_text = (
            "（产品资料未找到。当前为 Stage 6a 默认占位，Stage 6b 将接入选定的产品 KB 做 RAG 检索。）"
        )

    # 并发闸门：小内存机器同时跑太多实时会话会 OOM 卡死整机。
    # 名额满时直接 429 让前端稍候再试，而不是硬扛。
    if not try_acquire_session_slot():
        stats = session_slot_stats()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"当前同时进行的会话已满（{stats['active']}/{stats['max']}），"
            f"请稍候几分钟再试。",
        )

    cfg = row.get("config") or {}
    runner = SessionRunner(session_id=session_id, holds_slot=True)
    register_runner(runner)

    try:
        runner.start_in_executor(
            product_text=product_text,
            persona=persona,
            topic=row.get("topic") or "学习平板销售模拟",
            max_rounds=int(row.get("max_rounds") or 50),
            judge_interval=int(cfg.get("judge_interval") or 3),
            memory_interval=int(cfg.get("memory_interval") or 3),
            who_speaks_first=cfg.get("who_speaks_first") or "sales",
            opening_line=row.get("opening_line") or "",
            max_rounds_floor=int(cfg.get("max_rounds_floor") or 0),
            output_dir="outputs",
            product_kb_id=row.get("product_kb_id"),
            enterprise_kb_id=row.get("enterprise_kb_id"),
            handbook_id=row.get("handbook_id"),
            language=(cfg.get("language") or "zh-CN"),
        )
    except Exception:
        # 启动失败（未真正进入 _run_blocking）：立即归还名额并摘掉 runner，
        # 否则名额会永久泄漏、闸门被逐步锁死。
        runner.holds_slot = False
        release_session_slot()
        remove_runner(session_id)
        raise

    logger.info("session %s started in executor", session_id)
    return {
        "session_id": session_id,
        "runtime_status": runner.status,
        "ws_url": f"/ws/session/{session_id}/live",
    }


@router.post("/{session_id}/cancel")
def cancel_session(session_id: str) -> dict:
    """请求中断。下一轮循环检查 cancel_flag 后实际停止。"""
    runner = get_runner(session_id)
    if runner is None:
        raise HTTPException(404, f"session {session_id!r} 不在活跃 runner 中（可能已结束）")
    runner.request_cancel()
    return {
        "session_id": session_id,
        "runtime_status": runner.status,
        "cancelled": True,
    }


@router.get("/{session_id}")
def get_session(session_id: str) -> dict:
    """读 session 行 + 当前运行时 status（如有 runner）。"""
    with storage_db.connection_scope() as conn:
        row = storage_db.get_session_by_id(conn, session_id)
    if not row:
        raise HTTPException(404, f"session {session_id!r} 不存在")

    runner = get_runner(session_id)
    runtime_status = runner.status if runner else row.get("status")
    return _serialize_session(row, runtime_status=runtime_status)


# ============================================================
# Stage 7：复盘 + 导出 + 删除
# ============================================================


def _load_full_detail(session_id: str) -> dict[str, Any]:
    """聚合一场 session 的全部回放数据（DB-only，不读 outputs/）。"""
    with storage_db.connection_scope() as conn:
        row = storage_db.get_session_by_id(conn, session_id)
        if not row:
            raise HTTPException(404, f"session {session_id!r} 不存在")
        turns = storage_db.list_turns(conn, session_id)
        judge_evals = storage_db.list_evaluations(
            conn, session_id, evaluator_role="judge",
        )
        coach_eval = storage_db.get_latest_evaluation(
            conn, session_id, "coach",
        )
        persona_row = (
            storage_db.get_persona_by_id(conn, row["persona_id"])
            if row.get("persona_id") else None
        )

    summary = row.get("summary") or {}
    return {
        "session": _serialize_session(row),
        "persona": persona_row,  # 已是 dict 或 None
        "turns": turns,
        "judge_evaluations": judge_evals,
        "coach_review": (coach_eval.get("feedback") if coach_eval else None),
        "session_memory": summary.get("latest_memory") or {},
        "session_memory_round": summary.get("latest_memory_round"),
        "outcome": summary.get("outcome"),
        "metrics": {
            "total_rounds": summary.get("total_rounds") or 0,
            "persona_turns": summary.get("persona_turns") or 0,
            "sales_turns": summary.get("sales_turns") or 0,
            "judge_count": len(judge_evals),
        },
    }


@router.get("/{session_id}/detail")
def get_session_detail(session_id: str) -> dict:
    """详情页用：会话 + persona + turns + judge 历次 + coach + 终态画像。"""
    return _load_full_detail(session_id)


@router.get("/{session_id}/prompt_inspect")
def get_session_prompt_inspect(session_id: str) -> dict[str, Any]:
    """C1 · 销冠 prompt 透视

    用本场 session 实际绑定的 handbook（若未绑则走 resolve_default_handbook_id 兜底）
    渲染出销冠 prompt 顶部的 [产品手册] 强约束块原文，方便人工眼检
    "销冠看到了什么"。

    后续 Sprint 2 可在此基础上扩展返回完整 sales prompt 渲染结果。
    """
    with storage_db.connection_scope() as conn:
        row = storage_db.get_session_by_id(conn, session_id)
    if not row:
        raise HTTPException(404, f"session_id={session_id} 不存在")

    # 复用 agents._build_handbook_block_with_meta，构造最小 DialogueState
    # 只需 handbook_id 字段；其它字段（persona 等）此 helper 不读
    from src.agents import _build_handbook_block_with_meta
    from src.schema import (
        DialogueState,
        JudgeFeedback,
        PersonaProfile,
        PressureProfile,
        SessionMemory,
    )

    _stub_persona = PersonaProfile(
        id="_inspect",
        name="—",
        personality="—",
        pain_points=[],
        objection_style="—",
        purchase_goal="—",
        pressure_profile=PressureProfile(
            price_sensitivity=0.5, trust_threshold=0.5, patience=0.5,
            competitor_awareness=0.5, decision_power=0.5,
            emotion_volatility=0.5, need_urgency=0.5,
            skepticism=0.5, bargaining_aggressiveness=0.5,
        ),
    )
    state = DialogueState(
        session_id=session_id,
        topic=row.get("topic") or "",
        product_text="",
        persona_profile=_stub_persona,
        round_idx=0,
        max_rounds=int(row.get("max_rounds") or 10),
        session_memory=SessionMemory.empty(),
        judge_feedback=JudgeFeedback.empty(),
        handbook_id=row.get("handbook_id"),
    )
    block_text, meta = _build_handbook_block_with_meta(state)
    return {
        "session_id": session_id,
        "handbook_block": block_text,
        "handbook_meta": meta,
        "session_handbook_id_raw": row.get("handbook_id"),
    }


# ────────────── export helpers ──────────────


def _format_score(v: Any) -> str:
    return f"{float(v):.2f}" if isinstance(v, (int, float)) else "-"


def _render_markdown(detail: dict[str, Any]) -> str:
    """把详情数据拼成人类可读的 Markdown 复盘报告。"""
    s = detail["session"]
    persona = detail.get("persona") or {}
    metrics = detail["metrics"]
    coach = detail.get("coach_review") or {}
    memory = detail.get("session_memory") or {}
    judge_history = detail.get("judge_evaluations") or []
    final_judge = judge_history[-1] if judge_history else None

    lines: list[str] = []
    push = lines.append

    push(f"# 销售对话复盘 · {s['id']}")
    push("")
    push("## 基本信息")
    push(f"- **客户画像**: {persona.get('name') or '-'} "
         f"({persona.get('format_type') or '-'})")
    push(f"- **会话主题**: {s.get('topic') or '-'}")
    push(f"- **开场白**: {s.get('opening_line') or '-'}")
    push(f"- **结果**: {detail.get('outcome') or '-'}")
    push(f"- **轮数**: {metrics['total_rounds']}/{s.get('max_rounds') or '-'}")
    push(f"- **开始时间**: {s.get('started_at') or '-'}")
    push(f"- **结束时间**: {s.get('ended_at') or '-'}")
    push("")

    # ── 对话流 ──
    push("## 对话流")
    push("")
    for t in detail.get("turns") or []:
        role = "销冠" if t["role"] == "sales" else "客户"
        idx = t["idx"]
        stage = t.get("stage") or ""
        push(f"### Round {idx} · {role}" + (f" · _{stage}_" if stage else ""))
        push("")
        content = (t.get("content") or "").strip()
        for ln in content.splitlines() or [content]:
            push(f"> {ln}" if ln else ">")
        meta = t.get("metadata") or {}
        meta_tags: list[str] = []
        for k in ("intent", "attitude", "purchase_signal", "status",
                  "walk_away_reason"):
            v = meta.get(k)
            if v not in (None, "", []):
                meta_tags.append(f"`{k}={v}`")
        if meta_tags:
            push("")
            push(" ".join(meta_tags))
        push("")

    # ── Judge ──
    if final_judge:
        push("## Judge 最终评估")
        fb = final_judge.get("feedback") or {}
        score = (fb.get("sales_score") or {})
        push(f"- **end_status**: `{fb.get('end_status') or 'CONTINUE'}`")
        push(f"- **综合质量**: {_format_score(fb.get('dialogue_quality_score'))}")
        push("- **销冠五维评分**:")
        for k in ("responsiveness", "specificity", "evidence_usage",
                  "objection_handling", "closing_progress"):
            push(f"  - {k}: {_format_score(score.get(k))}")
        if fb.get("reason"):
            push(f"- **judge 说明**: {fb['reason']}")
        if fb.get("sales_instruction"):
            push(f"- **销冠下一步指令**: {fb['sales_instruction']}")
        if fb.get("persona_instruction"):
            push(f"- **人设下一步指令**: {fb['persona_instruction']}")
        push("")

    # ── Coach ──
    if coach:
        push("## Coach 复盘")
        if coach.get("outcome_analysis"):
            push("### 总体分析")
            push(coach["outcome_analysis"])
            push("")
        if coach.get("what_worked"):
            push(f"### 有效策略 ({len(coach['what_worked'])})")
            for it in coach["what_worked"]:
                push(f"- **R{it.get('round', '-')}** · {it.get('strategy', '')}")
                if it.get("evidence"):
                    push(f"  > {it['evidence']}")
                if it.get("why_effective"):
                    push(f"  - 为何有效：{it['why_effective']}")
            push("")
        if coach.get("what_failed"):
            push(f"### 失效操作 ({len(coach['what_failed'])})")
            for it in coach["what_failed"]:
                push(f"- **R{it.get('round', '-')}** · {it.get('strategy', '')}")
                if it.get("evidence"):
                    push(f"  > {it['evidence']}")
                if it.get("why_failed"):
                    push(f"  - 为何失败：{it['why_failed']}")
            push("")
        if coach.get("persona_insight"):
            push("### 对客户的新认识")
            push(coach["persona_insight"])
            push("")
        if coach.get("key_lessons"):
            push("### 核心经验")
            for ls in coach["key_lessons"]:
                push(f"- {ls}")
            push("")
        if coach.get("suggested_rebuttals"):
            push("### 推荐话术")
            for it in coach["suggested_rebuttals"]:
                push(f"- **遇到**: {it.get('objection', '')}")
                push(f"  - **回应**: {it.get('rebuttal_template', '')}")
            push("")
        if coach.get("reusable_tactics"):
            push("### 可复用打法")
            for t in coach["reusable_tactics"]:
                push(f"- {t}" if isinstance(t, str) else f"- {json.dumps(t, ensure_ascii=False)}")
            push("")

    # ── 终态画像 ──
    if memory:
        push("## 终态客户画像")
        for k, label in [
            ("current_need", "当前需求"),
            ("budget_boundary", "预算边界"),
            ("emotional_state", "情绪状态"),
            ("next_best_action", "下一步建议"),
        ]:
            v = memory.get(k)
            if v:
                push(f"- **{label}**: {v}")
        for k, label in [
            ("main_objections", "核心异议"),
            ("mentioned_competitors", "提及竞品"),
            ("decision_constraints", "决策约束"),
            ("do_not_repeat", "避免重复"),
        ]:
            arr = memory.get(k) or []
            if arr:
                push(f"- **{label}**:")
                for it in arr:
                    push(f"  - {it}")
        push("")

    return "\n".join(lines)


def _render_jsonl(detail: dict[str, Any]) -> str:
    """每行一条结构化记录，便于二次分析 / 训练集采样。"""
    lines: list[str] = []
    s = detail["session"]
    lines.append(json.dumps({"kind": "session", **s}, ensure_ascii=False))
    if detail.get("persona"):
        lines.append(json.dumps(
            {"kind": "persona", **detail["persona"]}, ensure_ascii=False,
        ))
    for t in detail.get("turns") or []:
        lines.append(json.dumps({"kind": "turn", **t}, ensure_ascii=False))
    for ev in detail.get("judge_evaluations") or []:
        lines.append(json.dumps({"kind": "judge", **ev}, ensure_ascii=False))
    if detail.get("coach_review"):
        lines.append(json.dumps(
            {"kind": "coach", "feedback": detail["coach_review"]},
            ensure_ascii=False,
        ))
    if detail.get("session_memory"):
        lines.append(json.dumps(
            {"kind": "session_memory", **detail["session_memory"]},
            ensure_ascii=False,
        ))
    return "\n".join(lines) + "\n"


_EXPORT_MEDIA = {
    "json": ("application/json; charset=utf-8", "json"),
    "md":   ("text/markdown; charset=utf-8",     "md"),
    "jsonl": ("application/jsonl; charset=utf-8", "jsonl"),
}


class BulkExportPayload(BaseModel):
    """POST /api/sessions/bulk_export 入参。"""
    session_ids: list[str] = Field(..., min_length=1, max_length=200)
    format: str = Field(
        "md",
        description="会话格式：md / json / jsonl",
    )
    include_analysis: bool = Field(
        True,
        description="是否同时打包每个会话最新已完成的分析报告（md + json）",
    )


@router.post(
    "/bulk_export",
    summary="批量打包导出（zip：会话 + 可选分析报告）",
)
def bulk_export_sessions(payload: BulkExportPayload) -> Response:
    """前端 SessionHistory 多选后的批量导出入口。

    - 每个 session 都进 `sessions/{id}.{fmt}`
    - 若 include_analysis=True，且该 session 有 status=completed 的分析任务，
      就追加 `analysis/{id}.md` + `analysis/{id}.json`
    - 缺失的 session 写一行 manifest 标记，不阻断
    - 全部用 stdlib zipfile，零新增依赖
    """
    fmt = payload.format.lower()
    if fmt not in _EXPORT_MEDIA:
        raise HTTPException(
            400, f"format 必须是 json|md|jsonl，收到 {payload.format!r}",
        )

    # 延迟导入避免顶层环
    from src.api.routes_analysis import (
        find_latest_completed_job_for_session,
        render_analysis_markdown,
    )

    manifest_lines: list[str] = [
        "# 批量导出清单",
        f"- 会话数: {len(payload.session_ids)}",
        f"- 会话格式: .{fmt}",
        f"- 含分析报告: {'是' if payload.include_analysis else '否'}",
        "",
        "| session_id | 会话 | 分析报告 |",
        "| --- | --- | --- |",
    ]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sid in payload.session_ids:
            sess_ok = False
            an_ok = False
            try:
                detail = _load_full_detail(sid)
                if fmt == "json":
                    body = json.dumps(detail, ensure_ascii=False, indent=2)
                elif fmt == "md":
                    body = _render_markdown(detail)
                else:
                    body = _render_jsonl(detail)
                zf.writestr(f"sessions/{sid}.{fmt}", body)
                sess_ok = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("bulk_export session %s 失败: %s", sid, exc)
                zf.writestr(
                    f"sessions/{sid}.error.txt",
                    f"导出失败：{exc}",
                )

            if payload.include_analysis:
                try:
                    job = find_latest_completed_job_for_session(sid)
                    if job:
                        zf.writestr(
                            f"analysis/{sid}.md",
                            render_analysis_markdown(job),
                        )
                        zf.writestr(
                            f"analysis/{sid}.json",
                            json.dumps(job, ensure_ascii=False, indent=2),
                        )
                        an_ok = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "bulk_export analysis for %s 失败: %s", sid, exc,
                    )

            manifest_lines.append(
                f"| `{sid}` | {'OK' if sess_ok else 'FAIL'} "
                f"| {'OK' if an_ok else ('—' if not payload.include_analysis else 'NONE')} |",
            )

        zf.writestr("manifest.md", "\n".join(manifest_lines))

    buf.seek(0)
    data = buf.getvalue()
    filename = f"sessions-bulk-{len(payload.session_ids)}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/{session_id}/export", summary="导出会话（json/md/jsonl）")
def export_session(session_id: str, format: str = Query("json")) -> Response:
    """流式下载会话回放。

    json  → 完整 detail dump
    md    → 人类可读 Markdown 复盘报告
    jsonl → 每行一条 (session/persona/turn/judge/coach/memory)
    """
    fmt = format.lower()
    if fmt not in _EXPORT_MEDIA:
        raise HTTPException(
            400, f"format 必须是 json|md|jsonl，收到 {format!r}",
        )

    detail = _load_full_detail(session_id)

    if fmt == "json":
        body = json.dumps(detail, ensure_ascii=False, indent=2)
    elif fmt == "md":
        body = _render_markdown(detail)
    else:  # jsonl
        body = _render_jsonl(detail)

    media_type, ext = _EXPORT_MEDIA[fmt]
    filename = f"{session_id}.{ext}"
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body.encode("utf-8"))),
        },
    )


@router.delete("/{session_id}", status_code=status.HTTP_200_OK,
               summary="删除 session 及关联输出")
def delete_session(session_id: str) -> dict:
    """删 DB（turns/evaluations 级联）+ 清 outputs/{session_id}/ 目录。

    若 session 仍在运行，先 cancel；DB 行不存在则 404。
    """
    runner = get_runner(session_id)
    if runner is not None and runner.status == "running":
        runner.request_cancel()

    with storage_db.connection_scope() as conn:
        ok = storage_db.delete_session(conn, session_id)
    if not ok:
        raise HTTPException(404, f"session {session_id!r} 不存在")

    # 清 outputs/{session_id}/ 目录（如果存在）
    out_dir = PROJECT_ROOT / "outputs" / session_id
    if out_dir.exists() and out_dir.is_dir():
        try:
            shutil.rmtree(out_dir)
            removed_outputs = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("rmtree outputs %s failed: %s", out_dir, exc)
            removed_outputs = False
    else:
        removed_outputs = False

    return {
        "session_id": session_id,
        "deleted": True,
        "removed_outputs": removed_outputs,
    }


# ============================================================
# Stage 11：手动收藏单条 turn 为销售案例（manual 入库轨）
# ============================================================

from pydantic import BaseModel as _CaseBaseModel, Field as _CaseField  # noqa: E402


class CollectAsCasePayload(_CaseBaseModel):
    """POST /api/sessions/{id}/cases 入参。"""

    turn_idx: int = _CaseField(..., description="目标 turn 的 idx（来自 detail.turns[].idx）")
    title: Optional[str] = _CaseField(None, description="案例标题；缺省自动生成")
    why_excellent: Optional[str] = _CaseField(None, description="为什么值得收藏")
    tags: Optional[list[str]] = _CaseField(default=None)
    context_radius: int = _CaseField(
        2, ge=0, le=10, description="向上下文各扩展几条 turn",
    )


@router.post(
    "/{session_id}/cases",
    status_code=status.HTTP_201_CREATED,
    summary="将该 session 中某条 turn 收藏为销售案例（manual）",
)
def collect_session_turn_as_case(
    session_id: str, payload: CollectAsCasePayload,
) -> dict:
    """三轨 C：人工收藏。

    - 校验 session 存在 + turn_idx 命中
    - 调用 src.cases.extractor.save_manual_case_from_turn
    - 失败返回 4xx；成功返回新建的 case dict
    """
    try:
        from src.cases.extractor import save_manual_case_from_turn
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"cases 模块加载失败: {exc}") from exc

    with storage_db.connection_scope() as conn:
        sess = storage_db.get_session_by_id(conn, session_id)
        if not sess:
            raise HTTPException(404, f"session {session_id!r} 不存在")
        try:
            case = save_manual_case_from_turn(
                conn,
                session_id=session_id,
                turn_idx=payload.turn_idx,
                title=payload.title or "",
                why_excellent=payload.why_excellent,
                tags=payload.tags,
                context_radius=payload.context_radius,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("collect_session_turn_as_case failed")
            raise HTTPException(500, f"收藏失败: {exc}") from exc

    return {"ok": True, "case": case}
