"""Stage 10：批量报告 · 6 个接口（5 聚合 + 1 Training Guide 导出）。

数据源（read-only，纯聚合）：
    sessions.summary_json            → outcome / total_rounds / latest_memory
    evaluations(role='judge')        → dialogue_quality_score + sales_score 五维
    evaluations(role='coach')        → what_worked / what_failed / suggested_rebuttals 等
    turns.metadata_json (sales role) → used_product_kb / used_enterprise_kb / rag_hits

接口前缀：/api/batch/{batch_id}/report/...

设计原则：
    - 报告只读：不写任何表
    - 空批量 / 空 session 都返回安全空值（前端 ElEmpty 占位）
    - 异议聚合按"完全相同字符串"折叠；不做模糊归并（留到后续 Stage）
"""

from __future__ import annotations

import io
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from src.storage import db as storage_db


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/batch", tags=["batch-report"])


# ============================================================
# 共用 loader：一次拉完整 batch + 子 sessions + judge + coach + turns
# 把数据库 IO 都集中起来，避免 5 个接口各自串多次 DB
# ============================================================


def _load_bundle(batch_id: int) -> dict[str, Any]:
    """读 batch + 全部子 session 的 detail，组装成内存数据包供各聚合函数复用。"""
    with storage_db.connection_scope() as conn:
        batch = storage_db.get_batch_job(conn, batch_id)
        if not batch:
            raise HTTPException(404, f"batch {batch_id} 不存在")

        sids: list[str] = batch.get("session_ids") or []
        sessions: list[dict[str, Any]] = []
        judges_by_sid: dict[str, list[dict[str, Any]]] = {}
        coach_by_sid: dict[str, dict[str, Any]] = {}
        turns_by_sid: dict[str, list[dict[str, Any]]] = {}
        personas_by_id: dict[int, dict[str, Any]] = {}

        for sid in sids:
            srow = storage_db.get_session_by_id(conn, sid)
            if not srow:
                continue
            sessions.append(srow)
            pid = srow.get("persona_id")
            if pid and pid not in personas_by_id:
                p = storage_db.get_persona_by_id(conn, pid)
                if p:
                    personas_by_id[pid] = p
            judges_by_sid[sid] = storage_db.list_evaluations(
                conn, sid, evaluator_role="judge",
            )
            coach = storage_db.get_latest_evaluation(conn, sid, "coach")
            if coach:
                coach_by_sid[sid] = coach
            turns_by_sid[sid] = storage_db.list_turns(conn, sid)

    return {
        "batch": batch,
        "sessions": sessions,
        "judges_by_sid": judges_by_sid,
        "coach_by_sid": coach_by_sid,
        "turns_by_sid": turns_by_sid,
        "personas_by_id": personas_by_id,
    }


def _outcome_of(s: dict[str, Any]) -> str:
    summary = s.get("summary") or {}
    return summary.get("outcome") or s.get("status") or "UNKNOWN"


def _memory_of(s: dict[str, Any]) -> dict[str, Any]:
    summary = s.get("summary") or {}
    return summary.get("latest_memory") or {}


def _final_judge(judges: list[dict[str, Any]]) -> dict[str, Any]:
    """取该 session 最后一次 judge 评分的 feedback。"""
    if not judges:
        return {}
    last = max(judges, key=lambda j: j.get("id", 0))
    return last.get("feedback") or {}


def _quality_score(fb: dict[str, Any]) -> float | None:
    v = fb.get("dialogue_quality_score") if fb else None
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ============================================================
# 1. overview
# ============================================================


@router.get("/{batch_id}/report/overview", summary="批量任务概览指标")
def get_overview(batch_id: int) -> dict[str, Any]:
    """4 大数字 + outcome 分布 + 平均轮数 + 平均质量。"""
    b = _load_bundle(batch_id)
    batch = b["batch"]
    sessions = b["sessions"]

    outcomes = Counter(_outcome_of(s) for s in sessions)
    rounds = [
        (s.get("summary") or {}).get("total_rounds") or 0
        for s in sessions
    ]
    rounds_valid = [r for r in rounds if r > 0]
    quality_scores: list[float] = []
    for s in sessions:
        q = _quality_score(_final_judge(b["judges_by_sid"].get(s["id"], [])))
        if q is not None:
            quality_scores.append(q)

    finished = sum(
        1 for s in sessions
        if (s.get("status") or "").lower() not in ("pending", "running")
    )
    deal_count = outcomes.get("DEAL_DONE", 0)

    return {
        "batch_id": batch_id,
        "batch_name": batch.get("name"),
        "status": batch.get("status"),
        "total_count": batch.get("total_count") or 0,
        "completed_count": batch.get("completed_count") or 0,
        "failed_count": batch.get("failed_count") or 0,
        "cancelled_count": batch.get("cancelled_count") or 0,
        "duration_sec": (batch.get("summary") or {}).get("duration_sec") or 0,
        "deal_count": deal_count,
        "deal_rate": round(deal_count / finished, 3) if finished > 0 else 0.0,
        "avg_rounds": round(sum(rounds_valid) / len(rounds_valid), 1)
                      if rounds_valid else 0.0,
        "avg_quality": round(sum(quality_scores) / len(quality_scores), 2)
                       if quality_scores else 0.0,
        "outcome_dist": [
            {"outcome": k, "count": v}
            for k, v in outcomes.most_common()
        ],
        "max_rounds": batch.get("max_rounds"),
        "started_at": batch.get("started_at"),
        "ended_at": batch.get("ended_at"),
    }


# ============================================================
# 2. objections Top-N
# ============================================================


@router.get("/{batch_id}/report/objections", summary="高频异议 Top-N")
def get_objections(
    batch_id: int,
    top: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """从所有 session 的 latest_memory.main_objections 聚合：
        - 完全相同字符串折叠 + 计数
        - 每条记录关联出现的 persona 名（去重）
        - 关联 session_ids 便于点进
    """
    b = _load_bundle(batch_id)
    sessions = b["sessions"]
    personas = b["personas_by_id"]

    bucket: dict[str, dict[str, Any]] = {}
    for s in sessions:
        mem = _memory_of(s)
        items = mem.get("main_objections") or []
        if not isinstance(items, list):
            continue
        pid = s.get("persona_id")
        p_name = (personas.get(pid) or {}).get("name") if pid else None
        outcome = _outcome_of(s)
        for raw in items:
            if not isinstance(raw, str):
                continue
            key = raw.strip()
            if not key:
                continue
            slot = bucket.setdefault(key, {
                "text": key,
                "count": 0,
                "personas": set(),
                "outcomes": Counter(),
                "session_ids": [],
            })
            slot["count"] += 1
            if p_name:
                slot["personas"].add(p_name)
            slot["outcomes"][outcome] += 1
            slot["session_ids"].append(s["id"])

    ranked = sorted(bucket.values(), key=lambda r: r["count"], reverse=True)[:top]
    items = [{
        "text": r["text"],
        "count": r["count"],
        "personas": sorted(r["personas"]),
        "outcomes": [{"outcome": k, "count": v}
                     for k, v in r["outcomes"].most_common()],
        "session_ids": r["session_ids"][:5],   # 最多 5 个 demo
    } for r in ranked]

    return {
        "batch_id": batch_id,
        "items": items,
        "total_unique": len(bucket),
        "total_records": sum(s["count"] for s in items),
    }


# ============================================================
# 3. persona_comparison
# ============================================================


@router.get("/{batch_id}/report/persona_comparison", summary="各 persona 在本 batch 内的表现")
def get_persona_comparison(batch_id: int) -> dict[str, Any]:
    """每个 persona：sessions / outcome 分布 / avg_quality / avg_rounds / deal_rate。"""
    b = _load_bundle(batch_id)
    sessions = b["sessions"]
    personas = b["personas_by_id"]

    grp: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "outcomes": Counter(),
        "rounds": [],
        "quality": [],
        "session_ids": [],
    })

    for s in sessions:
        pid = s.get("persona_id")
        if pid is None:
            continue
        outcome = _outcome_of(s)
        grp[pid]["outcomes"][outcome] += 1
        r = (s.get("summary") or {}).get("total_rounds") or 0
        if r > 0:
            grp[pid]["rounds"].append(r)
        q = _quality_score(_final_judge(b["judges_by_sid"].get(s["id"], [])))
        if q is not None:
            grp[pid]["quality"].append(q)
        grp[pid]["session_ids"].append(s["id"])

    items: list[dict[str, Any]] = []
    for pid, g in grp.items():
        sess = sum(g["outcomes"].values())
        deal = g["outcomes"].get("DEAL_DONE", 0)
        items.append({
            "persona_id": pid,
            "persona_name": (personas.get(pid) or {}).get("name") or f"#{pid}",
            "persona_avatar_key": (personas.get(pid) or {}).get("avatar_key"),
            "tags": (personas.get(pid) or {}).get("tags") or [],
            "sessions": sess,
            "deal_count": deal,
            "deal_rate": round(deal / sess, 3) if sess else 0.0,
            "avg_quality": round(sum(g["quality"]) / len(g["quality"]), 2)
                           if g["quality"] else None,
            "avg_rounds": round(sum(g["rounds"]) / len(g["rounds"]), 1)
                          if g["rounds"] else 0.0,
            "outcomes": [{"outcome": k, "count": v}
                         for k, v in g["outcomes"].most_common()],
            "session_ids": g["session_ids"],
        })
    # 按 deal_rate DESC, avg_quality DESC 排
    items.sort(key=lambda x: (-x["deal_rate"], -(x["avg_quality"] or 0)))

    return {"batch_id": batch_id, "items": items}


# ============================================================
# 4. sales_radar
# ============================================================


_RADAR_DIMS = (
    "responsiveness",
    "specificity",
    "evidence_usage",
    "objection_handling",
    "closing_progress",
)

_RADAR_LABELS = {
    "responsiveness": "响应度",
    "specificity": "针对性",
    "evidence_usage": "证据使用",
    "objection_handling": "异议处理",
    "closing_progress": "推进力",
}


@router.get("/{batch_id}/report/sales_radar", summary="销冠五维评分均值")
def get_sales_radar(batch_id: int) -> dict[str, Any]:
    """聚合所有 session 的最终 judge 评分五维均值；同时返回 per-session 列表
    供前端绘制 boxplot 或 small multiples。"""
    b = _load_bundle(batch_id)
    judges_by_sid = b["judges_by_sid"]
    sessions = b["sessions"]

    per_session: list[dict[str, Any]] = []
    dim_sum: dict[str, float] = {d: 0.0 for d in _RADAR_DIMS}
    dim_n: dict[str, int] = {d: 0 for d in _RADAR_DIMS}

    for s in sessions:
        fb = _final_judge(judges_by_sid.get(s["id"], []))
        score = (fb or {}).get("sales_score") or {}
        row: dict[str, Any] = {
            "session_id": s["id"],
            "persona_id": s.get("persona_id"),
            "outcome": _outcome_of(s),
            "quality": _quality_score(fb),
        }
        any_dim = False
        for d in _RADAR_DIMS:
            v = score.get(d)
            try:
                vf = float(v) if v is not None else None
            except (TypeError, ValueError):
                vf = None
            row[d] = vf
            if vf is not None:
                dim_sum[d] += vf
                dim_n[d] += 1
                any_dim = True
        if any_dim:
            per_session.append(row)

    avg: dict[str, float] = {
        d: round(dim_sum[d] / dim_n[d], 2) if dim_n[d] > 0 else 0.0
        for d in _RADAR_DIMS
    }

    return {
        "batch_id": batch_id,
        "dimensions": [
            {"key": d, "label": _RADAR_LABELS[d], "avg": avg[d], "samples": dim_n[d]}
            for d in _RADAR_DIMS
        ],
        "per_session": per_session,
    }


# ============================================================
# 5. rag_stats
# ============================================================


@router.get("/{batch_id}/report/rag_stats", summary="RAG 命中率")
def get_rag_stats(batch_id: int) -> dict[str, Any]:
    """统计销冠 turns 中：
        - 总数 / 用了产品 KB 的数 / 用了企业 KB 的数 / 同时用了两者的数
        - hit_rate = (产品 ∪ 企业) / 总数
        - 平均每条 sales turn 的 chunk 数（按 product+enterprise 之和）

    关键数据形状（与 src/agents.py 一致）：
        turn.metadata.used_product_kb    = list[str]  非空即视为"用了产品 KB"
        turn.metadata.used_enterprise_kb = list[str]  非空即视为"用了企业 KB"
        turn.metadata.rag_hits = {
            "query": str,
            "product":    list[compact_hit],
            "enterprise": list[compact_hit],
            "product_fallback": bool,
        }
    """
    b = _load_bundle(batch_id)
    sessions = b["sessions"]
    turns_by_sid = b["turns_by_sid"]

    sales_total = 0
    prod_used = 0
    ent_used = 0
    both_used = 0
    prod_chunks = 0
    ent_chunks = 0
    fallback_count = 0
    sessions_with_rag = 0

    for s in sessions:
        s_turns = turns_by_sid.get(s["id"], [])
        sales_turns = [t for t in s_turns if t.get("role") == "sales"]
        sales_total += len(sales_turns)
        session_has_rag = False
        for t in sales_turns:
            meta = t.get("metadata") or {}
            p_ids = meta.get("used_product_kb") or []
            e_ids = meta.get("used_enterprise_kb") or []
            p = bool(p_ids)
            e = bool(e_ids)
            if p:
                prod_used += 1
            if e:
                ent_used += 1
            if p and e:
                both_used += 1
            if p or e:
                session_has_rag = True
            rag_hits = meta.get("rag_hits") or {}
            if isinstance(rag_hits, dict):
                prod_chunks += len(rag_hits.get("product") or [])
                ent_chunks += len(rag_hits.get("enterprise") or [])
                if rag_hits.get("product_fallback"):
                    fallback_count += 1
        if session_has_rag:
            sessions_with_rag += 1

    any_used = prod_used + ent_used - both_used  # 容斥
    chunks_total = prod_chunks + ent_chunks
    hit_rate = round(any_used / sales_total, 3) if sales_total > 0 else 0.0

    return {
        "batch_id": batch_id,
        "sales_turns_total": sales_total,
        "used_product_kb": prod_used,
        "used_enterprise_kb": ent_used,
        "used_both_kb": both_used,
        "used_any_kb": any_used,
        "hit_rate": hit_rate,
        "product_chunks": prod_chunks,
        "enterprise_chunks": ent_chunks,
        "chunks_total": chunks_total,
        "avg_chunks_per_turn": round(chunks_total / sales_total, 2)
                               if sales_total > 0 else 0.0,
        "fallback_turns": fallback_count,
        "sessions_with_rag": sessions_with_rag,
        "sessions_total": len(sessions),
    }


# ============================================================
# 7. business_stages v0.2 — playbook 覆盖率 + 各阶段配比
# ============================================================


@router.get("/{batch_id}/report/playbook_stats", summary="销冠剧本动作覆盖率")
def get_playbook_stats(batch_id: int) -> dict[str, Any]:
    """统计本批次销冠全部 sales turns 的 playbook_action 使用情况：

    返回结构（直接喂给前端 ECharts）：
        {
          "batch_id": int,
          "total_sales_turns": int,
          "with_playbook": int,             # 真的输出了 playbook_action 的 turn 数
          "without_playbook": int,
          "stage_distribution": [           # 各 stage 销冠发言占比 vs 期望权重
            {"stage_id": "S1", "actual_count": 12, "actual_ratio": 0.18,
             "expected_ratio": 0.15, "delta": 0.03, "outside_tolerance": False}
          ],
          "action_usage": [                 # 各 action 出现次数（按命中量倒序）
            {"action_id": "spin_problem", "stage_id": "S2",
             "cn": "SPIN-痛点提问", "count": 23}
          ],
          "stage_coverage": [               # 每个 stage 的"用了哪些 / 漏了哪些"
            {"stage_id": "S1", "used": [...], "missed": [...]}
          ]
        }
    """
    # 延迟 import，避免单元测试不需要 yaml 时也强加载
    from src.business_stages import load_stages, playbook_cn

    b = _load_bundle(batch_id)
    sessions = b["sessions"]
    turns_by_sid = b["turns_by_sid"]

    cfg = load_stages()
    stage_ids = cfg.all_stage_ids()

    sales_total = 0
    with_pa = 0
    stage_counter: Counter[str] = Counter()
    action_counter: Counter[str] = Counter()
    stage_used: dict[str, set[str]] = {sid: set() for sid in stage_ids}

    for s in sessions:
        for t in turns_by_sid.get(s["id"], []):
            if t.get("role") != "sales":
                continue
            sales_total += 1
            meta = t.get("metadata") or {}
            sid = meta.get("stage_id") or ""
            pa = meta.get("playbook_action")
            if sid in stage_counter or sid in stage_ids:
                stage_counter[sid] += 1
            if pa:
                with_pa += 1
                action_counter[pa] += 1
                if sid in stage_used:
                    stage_used[sid].add(pa)

    tol = cfg.weight_tolerance
    stage_distribution: list[dict[str, Any]] = []
    for sid in stage_ids:
        cnt = stage_counter.get(sid, 0)
        actual = (cnt / sales_total) if sales_total > 0 else 0.0
        expected = cfg.stages[sid].weight
        delta = actual - expected
        stage_distribution.append({
            "stage_id": sid,
            "stage_cn": cfg.stages[sid].cn_name,
            "actual_count": cnt,
            "actual_ratio": round(actual, 3),
            "expected_ratio": expected,
            "delta": round(delta, 3),
            "outside_tolerance": abs(delta) > tol,
        })

    action_usage = [
        {
            "action_id": aid,
            "stage_id": (cfg.playbook_index.get(aid) or {}).get("stage_id", ""),
            "cn": playbook_cn(aid),
            "count": cnt,
        }
        for aid, cnt in action_counter.most_common()
    ]

    stage_coverage: list[dict[str, Any]] = []
    for sid in stage_ids:
        allowed = set(cfg.get_allowed_actions(sid))
        used = stage_used.get(sid, set()) & allowed
        missed = allowed - used
        stage_coverage.append({
            "stage_id": sid,
            "stage_cn": cfg.stages[sid].cn_name,
            "used": sorted(used),
            "missed": sorted(missed),
            "coverage_rate": round(len(used) / len(allowed), 3) if allowed else 0.0,
        })

    return {
        "batch_id": batch_id,
        "total_sales_turns": sales_total,
        "with_playbook": with_pa,
        "without_playbook": sales_total - with_pa,
        "stage_distribution": stage_distribution,
        "action_usage": action_usage,
        "stage_coverage": stage_coverage,
    }


# ============================================================
# 6. Training Guide 导出 · 9 章节 Markdown
#
# 模板来自蓝图第 20 章 9 节：
#   1. 用户类型      2. 典型心智     3. 高频异议
#   4. 推荐策略      5. 标准话术     6. FAQ
#   7. 错误示范      8. 教练点评     9. 禁用表达清单
# ============================================================


def _section_users(b: dict[str, Any]) -> str:
    """1. 用户类型：本批跑过哪些 persona、tags、各跑了几场。"""
    sessions = b["sessions"]
    personas = b["personas_by_id"]
    grp: Counter = Counter()
    for s in sessions:
        pid = s.get("persona_id")
        if pid is not None:
            grp[pid] += 1
    if not grp:
        return "_本批次未关联任何 persona。_\n"
    lines = ["| 客户人设 | 场次 | 标签 |", "| --- | --- | --- |"]
    for pid, n in grp.most_common():
        p = personas.get(pid) or {}
        tags = " · ".join((p.get("tags") or [])[:5]) or "—"
        name = p.get("name") or f"#{pid}"
        lines.append(f"| {name} | {n} | {tags} |")
    return "\n".join(lines) + "\n"


def _section_mindsets(b: dict[str, Any]) -> str:
    """2. 典型心智：聚合所有 coach.persona_insight。"""
    coach_by_sid = b["coach_by_sid"]
    sessions = b["sessions"]
    personas = b["personas_by_id"]
    by_persona: dict[int, list[str]] = defaultdict(list)
    for s in sessions:
        c = coach_by_sid.get(s["id"])
        if not c:
            continue
        fb = c.get("feedback") or {}
        insight = fb.get("persona_insight")
        if isinstance(insight, str) and insight.strip():
            by_persona[s.get("persona_id")].append(insight.strip())

    if not by_persona:
        return "_本批次还没产出 Coach 心智洞察（需要至少一场跑完 Coach 复盘）。_\n"
    blocks = []
    for pid, arr in by_persona.items():
        name = (personas.get(pid) or {}).get("name") or f"#{pid}"
        blocks.append(f"### {name}\n")
        for ins in arr[:3]:  # 每 persona 最多 3 条
            blocks.append(f"- {ins}")
        blocks.append("")
    return "\n".join(blocks)


def _section_objections(b: dict[str, Any], top: int = 15) -> str:
    """3. 高频异议（含出现频次）。"""
    bucket: Counter = Counter()
    for s in b["sessions"]:
        mem = _memory_of(s)
        for raw in (mem.get("main_objections") or []):
            if isinstance(raw, str) and raw.strip():
                bucket[raw.strip()] += 1
    if not bucket:
        return "_本批次未沉淀异议（可能 session 跑得太短）。_\n"
    lines = ["| 排名 | 异议 | 出现 |", "| --- | --- | --- |"]
    for i, (text, n) in enumerate(bucket.most_common(top), 1):
        lines.append(f"| {i} | {text} | {n} |")
    return "\n".join(lines) + "\n"


def _section_strategies(b: dict[str, Any], top: int = 10) -> str:
    """4. 推荐策略：聚合 coach.what_worked。"""
    items: list[str] = []
    for s in b["sessions"]:
        c = b["coach_by_sid"].get(s["id"])
        if not c:
            continue
        for w in (c.get("feedback") or {}).get("what_worked", []) or []:
            if isinstance(w, dict):
                strat = w.get("strategy") or w.get("title")
                why = w.get("why_effective") or ""
                if strat:
                    items.append(
                        f"**{strat.strip()}**" +
                        (f" — {why.strip()}" if why else "")
                    )
            elif isinstance(w, str) and w.strip():
                items.append(w.strip())
    if not items:
        return "_本批次还没产出 Coach 标记的有效策略。_\n"
    seen: set[str] = set()
    uniq: list[str] = []
    for x in items:
        key = x[:60].lower()
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return "\n".join(f"- {x}" for x in uniq[:top]) + "\n"


def _section_scripts(b: dict[str, Any], top: int = 15) -> str:
    """5. 标准话术：来自 coach.suggested_rebuttals。"""
    items: list[tuple[str, str]] = []
    for s in b["sessions"]:
        c = b["coach_by_sid"].get(s["id"])
        if not c:
            continue
        for sr in (c.get("feedback") or {}).get("suggested_rebuttals", []) or []:
            if not isinstance(sr, dict):
                continue
            obj = (sr.get("objection") or "").strip()
            tmpl = (sr.get("rebuttal_template") or sr.get("rebuttal") or "").strip()
            if obj and tmpl:
                items.append((obj, tmpl))
    if not items:
        return "_本批次还没沉淀标准话术（来源：Coach.suggested_rebuttals）。_\n"
    blocks: list[str] = []
    seen: set[str] = set()
    for obj, tmpl in items:
        k = obj[:50].lower()
        if k in seen:
            continue
        seen.add(k)
        blocks.append(f"- **遇到**：{obj}\n  **回应**：{tmpl}")
        if len(blocks) >= top:
            break
    return "\n".join(blocks) + "\n"


def _section_faq(b: dict[str, Any], top: int = 10) -> str:
    """6. FAQ：把高频异议改写为问答形式。"""
    bucket: Counter = Counter()
    for s in b["sessions"]:
        for raw in (_memory_of(s).get("main_objections") or []):
            if isinstance(raw, str) and raw.strip():
                bucket[raw.strip()] += 1
    if not bucket:
        return "_暂无可生成的 FAQ。_\n"
    out = []
    for i, (text, _n) in enumerate(bucket.most_common(top), 1):
        out.append(f"**Q{i}.** {text}")
        out.append(f"**A{i}.** _（请基于「推荐策略 / 标准话术」段落给出具体应对，"
                   "本字段后续 Stage 可由 LLM 自动生成回答）_")
        out.append("")
    return "\n".join(out)


def _section_failures(b: dict[str, Any], top: int = 10) -> str:
    """7. 错误示范：来自 coach.what_failed。"""
    items: list[str] = []
    for s in b["sessions"]:
        c = b["coach_by_sid"].get(s["id"])
        if not c:
            continue
        for w in (c.get("feedback") or {}).get("what_failed", []) or []:
            if isinstance(w, dict):
                strat = w.get("strategy") or w.get("title")
                why = w.get("why_failed") or ""
                if strat:
                    items.append(
                        f"**{strat.strip()}**" +
                        (f" — {why.strip()}" if why else "")
                    )
            elif isinstance(w, str) and w.strip():
                items.append(w.strip())
    if not items:
        return "_本批次未识别明显失效操作。_\n"
    seen: set[str] = set()
    uniq: list[str] = []
    for x in items:
        k = x[:60].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return "\n".join(f"- {x}" for x in uniq[:top]) + "\n"


def _section_coach_review(b: dict[str, Any]) -> str:
    """8. 教练点评：每场 outcome_analysis 摘要 + 平均难度。"""
    sessions = b["sessions"]
    personas = b["personas_by_id"]
    blocks: list[str] = []
    difficulty_scores: list[float] = []
    for s in sessions:
        c = b["coach_by_sid"].get(s["id"])
        if not c:
            continue
        fb = c.get("feedback") or {}
        analysis = (fb.get("outcome_analysis") or "").strip()
        if not analysis:
            continue
        pid = s.get("persona_id")
        name = (personas.get(pid) or {}).get("name") or f"#{pid}"
        rating = fb.get("difficulty_rating")
        try:
            difficulty_scores.append(float(rating)) if rating is not None else None
        except (TypeError, ValueError):
            pass
        blocks.append(
            f"### {name}（{_outcome_of(s)}"
            + (f", 难度 {rating}" if rating is not None else "")
            + ")\n"
            f"{analysis}\n"
        )
    head = ""
    if difficulty_scores:
        head = (f"平均客户难度评分: **{sum(difficulty_scores)/len(difficulty_scores):.2f}** / 10"
                f" (样本 {len(difficulty_scores)})\n\n")
    return head + ("\n".join(blocks) if blocks else "_本批次未产出 Coach 总体分析。_\n")


def _section_banned(b: dict[str, Any], top: int = 15) -> str:
    """9. 禁用表达：来自 judge.avoid_repeating + coach.what_failed 中的具体话术。"""
    bucket: Counter = Counter()
    for s in b["sessions"]:
        # judge.avoid_repeating
        for jev in b["judges_by_sid"].get(s["id"], []) or []:
            for x in (jev.get("feedback") or {}).get("avoid_repeating", []) or []:
                if isinstance(x, str) and x.strip():
                    bucket[x.strip()] += 1
        # coach.what_failed 中明显是话术的（含"问"/"说"）
        c = b["coach_by_sid"].get(s["id"])
        if c:
            for w in (c.get("feedback") or {}).get("what_failed", []) or []:
                if isinstance(w, dict):
                    strat = (w.get("strategy") or "").strip()
                    if strat and len(strat) < 80:
                        bucket[strat] += 1
    if not bucket:
        return "_本批次未识别禁用表达。_\n"
    return "\n".join(
        f"- {text}  _×{n}_" for text, n in bucket.most_common(top)
    ) + "\n"


@router.get(
    "/{batch_id}/report/export",
    summary="导出 Training Guide（9 章节 Markdown）",
)
def export_training_guide(batch_id: int) -> Response:
    """蓝图第 20 章 9 节结构。前端 a[download] 直接下载。"""
    b = _load_bundle(batch_id)
    batch = b["batch"]

    # overview 行内 mini 表
    n_total = batch.get("total_count") or 0
    n_done = batch.get("completed_count") or 0
    n_fail = batch.get("failed_count") or 0
    n_cancel = batch.get("cancelled_count") or 0
    ov_summary = batch.get("summary") or {}
    outcome_dist = ov_summary.get("outcome_dist") or {}

    buf = io.StringIO()
    write = buf.write

    write(f"# 销冠训练手册 · {batch.get('name') or '未命名批次'}\n\n")
    write(f"> Batch ID: `{batch_id}`  ·  "
          f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    # 概览块
    write("## 概览\n\n")
    write(f"- 总场次 / 完成 / 失败 / 中断: **{n_total} / {n_done} / {n_fail} / {n_cancel}**\n")
    if outcome_dist:
        oc = " · ".join(f"{k}:{v}" for k, v in outcome_dist.items())
        write(f"- 结果分布: {oc}\n")
    write(f"- 主题: {batch.get('topic') or '—'}\n")
    write(f"- 开始 / 结束: {batch.get('started_at') or '—'} → {batch.get('ended_at') or '—'}\n\n")
    write("---\n\n")

    # 9 sections
    sections = [
        ("1. 用户类型", _section_users(b)),
        ("2. 典型心智", _section_mindsets(b)),
        ("3. 高频异议", _section_objections(b)),
        ("4. 推荐策略", _section_strategies(b)),
        ("5. 标准话术", _section_scripts(b)),
        ("6. FAQ",      _section_faq(b)),
        ("7. 错误示范", _section_failures(b)),
        ("8. 教练点评", _section_coach_review(b)),
        ("9. 禁用表达清单", _section_banned(b)),
    ]
    for title, body in sections:
        write(f"## {title}\n\n{body}\n")

    body = buf.getvalue()
    filename = f"training_guide_batch_{batch_id}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body.encode("utf-8"))),
        },
    )
