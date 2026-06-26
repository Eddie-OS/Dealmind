"""A4 · 报告聚合器（V2 详尽版）

输入：单个 analysis_job 的所有 turn_classifications + 关联 session 信息
输出：分两块
  1. summary —— 写回 analysis_jobs.summary_json
     原 V1 字段保留：
       handbook_id / handbook_name / session_ids / session_count
       total_classifications / categories_total / categories_covered
       coverage_pct / category_coverage / uncovered_categories
       weak_categories / strong_categories / dim_avg / outcome_join
     新增 V2 字段（学 v3.1 PDF）：
       coverage_by_group        按 6 个 group 的覆盖小总分
       excellent_turns          高分销冠话 Top 15（含上下文 + why-good）
       problematic_turns        低分销冠话 Top 15（含上下文 + why-bad + 应改成）
       revision_proposals       Handbook 修订建议（学 v3.1：原问题/证据/建议）
       customer_voice           按 persona 抽样客户原话调研
       key_numbers              "销冠必须背得出"的数字便签
       generated_at             生成时间
       version                  报告 schema 版本

  2. persona_insights —— 落到 analysis_persona_insights 表（不变）
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from src.analyzers.excellence_scorer import build_excellent_by_group
from src.analyzers.handbook_classifier import (
    PLAYBOOK_GROUP_ORDER,
    _iter_categories,
)
from src.analyzers.handbook_revisor import build_handbook_revisions
from src.analyzers.methodology import build_methodology
from src.storage import db as sdb

_OLD_GROUP_ORDER = ["intro", "sell", "comp", "param", "faq", "demo"]


def _group_order_for(struct: dict) -> list[str]:
    return (
        PLAYBOOK_GROUP_ORDER
        if (struct or {}).get("doc_type") == "playbook_v1"
        else _OLD_GROUP_ORDER
    )


logger = logging.getLogger(__name__)

REPORT_SCHEMA_VERSION = "2.0"


def _is_customer_role(role: str | None) -> bool:
    """turns 表客户侧 role 为 persona（与 schema.Turn.speaker 一致）。"""
    return (role or "").strip().lower() in ("persona", "customer")


from src.analyzers.handbook_scorer import DIM_LABEL as _NEW_DIM_LABEL

# 新版三层 6 维标签；同时保留旧维度键，使历史报告（未重算）仍能正确显示标签。
_DIM_LABEL: dict[str, str] = {
    **{
        "accuracy": "口径对齐",
        "specificity": "具体度",
        "delivery": "表达力",
        "customer_fit": "客户契合",
        "closing_push": "推进力",
        "risk_compliance": "底线合规",
    },
    **_NEW_DIM_LABEL,
}

# 抓取销冠必须随时背出的数字 token —— 数字 + 常见单位
_NUMBER_PATTERN = re.compile(
    r"\d+[\.,]?\d*\s*"
    r"(?:%|％|g|kg|nits?|hz|mah|w|ms|英寸|寸|cm|mm|h|小时|分钟|min|"
    r"gb|tb|mb|mp|英镑|美金|rmb|元|rub|x|倍|核|代)",
    re.IGNORECASE,
)


# ============================================================
# 公共入口
# ============================================================

def aggregate_report(
    *,
    job_id: int,
    session_ids: list[str],
    handbook: dict[str, Any],
    classifications: list[dict[str, Any]],
) -> dict[str, Any]:
    """聚合产出 {summary, persona_insights}。"""
    struct = handbook.get("structure_json") or {}
    label_map = _build_label_map(struct)

    # 1) 覆盖率 + 短板/强项 + 6 维全局
    cat_groups: dict[str, list[dict]] = defaultdict(list)
    for c in classifications:
        cat_groups[c["category_id"]].append(c)

    cat_coverage: dict[str, dict[str, Any]] = {}
    dim_sum: dict[str, list[int]] = defaultdict(list)

    for cid, items in cat_groups.items():
        sessions_covered = len({c["session_id"] for c in items})
        qualities = [_avg_quality(c.get("scores") or {}) for c in items]
        avg_q = round(sum(qualities) / max(1, len(qualities)), 2)
        cat_coverage[cid] = {
            "label": label_map.get(cid, cid),
            "hits": len(items),
            "sessions_covered": sessions_covered,
            "avg_quality": avg_q,
        }
        for it in items:
            for k, v in (it.get("scores") or {}).items():
                try:
                    dim_sum[k].append(int(v))
                except (TypeError, ValueError):
                    continue

    all_cats = list(label_map.keys())
    uncovered = sorted(c for c in all_cats if c not in cat_coverage)

    # 短板/强项：先按 ≥ 2 次命中筛（高置信），若不足 4 条则 fallback 到所有
    # 已命中条目（小样本兜底）——避免单 session 测试时报告全空。
    high_conf = [(cid, d) for cid, d in cat_coverage.items() if d["hits"] >= 2]
    all_ranked = list(cat_coverage.items())
    ranked = high_conf if len(high_conf) >= 4 else all_ranked
    weak_sorted = sorted(ranked, key=lambda x: x[1]["avg_quality"])[:8]
    strong_sorted = sorted(ranked, key=lambda x: -x[1]["avg_quality"])[:8]

    weak_categories = [
        {
            "category_id": cid, "label": d["label"], "hits": d["hits"],
            "avg_quality": d["avg_quality"],
            "reason": _weak_reason(cat_groups[cid]),
            "issue_top": _top_issues(cat_groups[cid], k=5),
            "suggestion_samples": _suggestion_samples(cat_groups[cid], k=3),
        }
        for cid, d in weak_sorted
    ]
    strong_categories = [
        {
            "category_id": cid, "label": d["label"],
            "hits": d["hits"], "avg_quality": d["avg_quality"],
            "highlight_reason": _strength_reason(cat_groups[cid]),
        }
        for cid, d in strong_sorted
    ]

    dim_avg = {
        k: round(sum(v) / max(1, len(v)), 2)
        for k, v in dim_sum.items()
    }

    # 2) outcome 拼接（轻量 SQL）+ session→persona 索引
    outcome_join: Counter = Counter()
    persona_rows: dict[Any, dict[str, Any]] = {}
    sess_to_persona: dict[str, Any] = {}
    sess_outcome: dict[str, str] = {}

    if session_ids:
        with sdb.connection_scope() as conn:
            qmarks = ",".join("?" * len(session_ids))
            rows = list(conn.execute(
                f"SELECT id, persona_id, "
                f"json_extract(summary_json, '$.outcome') AS outcome "
                f"FROM sessions WHERE id IN ({qmarks})",
                session_ids,
            ).fetchall())
            for r in rows:
                outcome_join[r["outcome"] or "unknown"] += 1
                sess_to_persona[r["id"]] = r["persona_id"]
                sess_outcome[r["id"]] = r["outcome"] or "unknown"
            # 拉 persona 元信息（name/format_type）
            pids = sorted({p for p in sess_to_persona.values() if p is not None})
            if pids:
                pmarks = ",".join("?" * len(pids))
                prows = list(conn.execute(
                    f"SELECT id, name, format_type FROM personas WHERE id IN ({pmarks})",
                    pids,
                ).fetchall())
                for p in prows:
                    persona_rows[p["id"]] = dict(p)

    # 3) 加载 turn 索引（含原文 + 前一条客户提问 + 无损全量轮）
    turn_index, prev_customer, turns_by_session = _load_turn_index(session_ids)

    # 3.5) 销售 turn 健康度指标（提及率 / 兜底率 / 重复率 / 平均字数）
    engagement = _calc_engagement_metrics(
        turn_index=turn_index,
        handbook_struct=struct,
        session_ids=session_ids,
    )

    # 4) 销冠话亮点 / 失误（V2 新增）
    excellent_turns, problematic_turns = _build_turn_highlights(
        classifications=classifications,
        label_map=label_map,
        turn_index=turn_index,
        prev_customer=prev_customer,
        sess_to_persona=sess_to_persona,
        persona_rows=persona_rows,
    )

    # 4.5) 优秀话术（改动⑥）：解耦手册一致性，行为信号 ⊕ LLM 优秀度，按 135910 + 手册外分组
    excellent_by_group = build_excellent_by_group(
        classifications=classifications,
        label_map=label_map,
        turns_by_session=turns_by_session,
        prev_customer=prev_customer,
        sess_to_persona=sess_to_persona,
        persona_rows=persona_rows,
    )

    # 5) Handbook 修订建议（V2 新增 · 学 v3.1）
    coverage_by_group = _coverage_by_group(cat_coverage, all_cats, struct)
    doc_type = struct.get("doc_type") or "handbook_135910"
    playbook_persona_breakdown = (
        _build_playbook_persona_breakdown(struct, cat_coverage)
        if doc_type == "playbook_v1" else []
    )

    # 缺口②：运行时按每场对话 LLM 判定客户类型 A/B/C/D（仅 playbook），
    # 聚合成对话侧人设分布 + 各类型专属话术覆盖。落库缓存，失败退化为空。
    conversation_persona_breakdown: dict[str, Any] = {}
    if doc_type == "playbook_v1":
        try:
            from src.analyzers.runtime_persona import (
                build_conversation_persona_breakdown,
                classify_sessions,
            )
            session_personas = classify_sessions(
                struct=struct,
                turns_by_session=turns_by_session,
                handbook_id=handbook.get("id"),
            )
            conversation_persona_breakdown = build_conversation_persona_breakdown(
                struct=struct,
                classifications=classifications,
                session_personas=session_personas,
                outcome_by_session=sess_outcome,
            )
        except Exception as e:  # noqa: BLE001 —— 运行时人设判定不应阻断报告
            logger.warning("[aggregate] 对话人设判定失败，跳过：%s", e)
    revision_proposals = _build_revision_proposals(
        struct=struct,
        label_map=label_map,
        uncovered=uncovered,
        weak_categories=weak_categories,
        dim_avg=dim_avg,
        session_count=len(session_ids),
        total_classifications=len(classifications),
    )

    # 5.5) 手册迭代建议（改动⑤）：按 31 条逐条 LLM + 每条 TOP3 原声
    handbook_revisions = build_handbook_revisions(
        struct=struct,
        label_map=label_map,
        classifications=classifications,
        turn_index=turn_index,
        prev_customer=prev_customer,
        sess_to_persona=sess_to_persona,
        persona_rows=persona_rows,
    )

    # 6) 客户原声调研（V2 新增）
    customer_voice = _build_customer_voice(
        turn_index=turn_index,
        sess_to_persona=sess_to_persona,
        persona_rows=persona_rows,
    )

    # 7) 关键数字便签（V2 新增）
    key_numbers = _build_key_numbers(struct)

    # 8) persona insights（原有）
    insights = _build_persona_insights(
        classifications=classifications,
        sess_to_persona=sess_to_persona,
        persona_rows=persona_rows,
        outcomes=outcome_join,
        label_map=label_map,
        session_ids=session_ids,
        turn_index=turn_index,
    )

    summary = {
        "version": REPORT_SCHEMA_VERSION,
        "doc_type": doc_type,
        "playbook_persona_breakdown": playbook_persona_breakdown,
        "conversation_persona_breakdown": conversation_persona_breakdown,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "handbook_id": handbook.get("id"),
        "handbook_name": handbook.get("name"),
        "session_ids": session_ids,
        "session_count": len(session_ids),
        "total_classifications": len(classifications),
        "categories_total": len(all_cats),
        "categories_covered": len(cat_coverage),
        "coverage_pct": round(
            100.0 * len(cat_coverage) / max(1, len(all_cats)), 1
        ),
        "category_coverage": cat_coverage,
        "coverage_by_group": coverage_by_group,
        "uncovered_categories": uncovered,
        "weak_categories": weak_categories,
        "strong_categories": strong_categories,
        "dim_avg": dim_avg,
        "outcome_join": dict(outcome_join),
        # V2 新增
        "excellent_turns": excellent_turns,
        "excellent_by_group": excellent_by_group,
        "problematic_turns": problematic_turns,
        "revision_proposals": revision_proposals,
        "handbook_revisions": handbook_revisions,
        "customer_voice": customer_voice,
        "key_numbers": key_numbers,
        "engagement": engagement,
        # V2-① 报告可解释性：分析方法说明（单一事实源，前端弹窗 + 导出 HTML 同源）
        "methodology": build_methodology(),
    }
    return {"summary": summary, "persona_insights": insights}


# ============================================================
# 内部 helper —— label / score 基础
# ============================================================

def _build_label_map(struct: dict) -> dict[str, str]:
    """统一经 _iter_categories 派生（新旧结构通用）。"""
    return {c["id"]: (c.get("label") or c["id"]) for c in _iter_categories(struct)}


def _avg_quality(scores: dict[str, Any]) -> float:
    if not isinstance(scores, dict) or not scores:
        return 0.0
    vals: list[float] = []
    for v in scores.values():
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue
    return round(sum(vals) / max(1, len(vals)), 2)


def _weak_reason(items: list[dict]) -> str:
    """汇总 issues 取 Top-3 高频，转成一句原因。"""
    counter: Counter = Counter()
    for it in items:
        for iss in (it.get("issues") or []):
            counter[str(iss)[:50]] += 1
    if not counter:
        return "缺少明确的 issue 反馈，建议人工抽检最低分样本"
    top = counter.most_common(3)
    return " / ".join(f"{txt}({n})" for txt, n in top)


def _top_issues(items: list[dict], k: int = 5) -> list[dict]:
    counter: Counter = Counter()
    for it in items:
        for iss in (it.get("issues") or []):
            counter[str(iss)[:80]] += 1
    return [{"text": t, "count": n} for t, n in counter.most_common(k)]


def _suggestion_samples(items: list[dict], k: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        sug = (it.get("suggestion") or "").strip()
        if sug and sug not in seen:
            seen.add(sug)
            out.append(sug[:200])
            if len(out) >= k:
                break
    return out


def _strength_reason(items: list[dict]) -> str:
    """从 reference_text + suggestion 反推强项亮点。"""
    refs = [it.get("reference_text") or "" for it in items if it.get("reference_text")]
    if refs:
        return f"销冠在该条目上多次复述官方口径：{refs[0][:80]}…"
    return "销冠在该条目上表现稳定，建议沉淀为标准范本"


def _lookup_handbook_text(cid: str, struct: dict) -> str:
    """从 struct 中找到 cid 对应的 text + label，用于"原 Handbook 内容"展示（新旧通用）。"""
    for c in _iter_categories(struct):
        if c.get("id") == cid:
            label = (c.get("label") or "").strip()
            text = (c.get("text") or "").strip()
            if label and text:
                return f"{label}：{text}"
            return text or label
    return ""


def _coverage_by_group(
    cat_coverage: dict, all_cats: list[str], struct: dict
) -> dict[str, dict]:
    """按 group 汇总覆盖率（doc_type 感知）。"""
    group_of = {c["id"]: c["group"] for c in _iter_categories(struct)}
    out: dict[str, dict] = {}
    for g in _group_order_for(struct):
        all_g = [c for c in all_cats if group_of.get(c) == g]
        cov_g = [c for c in cat_coverage if group_of.get(c) == g]
        if not all_g:
            continue
        # 该 group 内 hits / avg_quality
        items = [cat_coverage[c] for c in cov_g]
        hits = sum(it["hits"] for it in items)
        if items:
            avg_q = round(
                sum(it["avg_quality"] * it["hits"] for it in items)
                / max(1, hits), 2,
            )
        else:
            avg_q = 0.0
        out[g] = {
            "covered": len(cov_g),
            "total": len(all_g),
            "coverage_pct": round(100.0 * len(cov_g) / max(1, len(all_g)), 1),
            "hits": hits,
            "weighted_avg_quality": avg_q,
        }
    return out


def _build_playbook_persona_breakdown(
    struct: dict, cat_coverage: dict
) -> list[dict[str, Any]]:
    """doc 侧人设视角：把带 persona（A/B/C/D）的条目（开场/卖点）按人设汇总
    覆盖与质量，回答“面向某类客户的话术被销冠演绎得怎样”。无需额外 LLM。"""
    slots: dict[str, dict[str, Any]] = {}
    for c in _iter_categories(struct):
        p = (c.get("persona") or "").strip()
        if not p:
            continue
        slot = slots.setdefault(p, {
            "persona": p,
            "persona_label": c.get("persona_label") or "",
            "total": 0, "covered": 0, "hits": 0, "_qsum": 0.0,
        })
        if c.get("persona_label") and not slot["persona_label"]:
            slot["persona_label"] = c["persona_label"]
        slot["total"] += 1
        cov = cat_coverage.get(c["id"])
        if cov:
            slot["covered"] += 1
            slot["hits"] += int(cov.get("hits", 0))
            slot["_qsum"] += float(cov.get("avg_quality", 0)) * int(cov.get("hits", 0))
    out: list[dict[str, Any]] = []
    for p in sorted(slots):
        s = slots[p]
        avg = round(s["_qsum"] / s["hits"], 2) if s["hits"] else 0.0
        out.append({
            "persona": s["persona"],
            "persona_label": s["persona_label"],
            "total": s["total"],
            "covered": s["covered"],
            "coverage_pct": round(100.0 * s["covered"] / max(1, s["total"]), 1),
            "hits": s["hits"],
            "avg_quality": avg,
        })
    return out


# ============================================================
# 内部 helper —— turn 索引 / 高分低分话提取
# ============================================================

def _load_turn_index(
    session_ids: list[str],
) -> tuple[dict[tuple[str, int], dict], dict[tuple[str, int], str], dict[str, list[dict]]]:
    """一次性把所有 session 的 turns load 进内存。

    返回：
      turn_index        {(session_id, idx): {role, content, metadata}}
                        注意：persona 与 sales 同轮共享 idx，dict 会发生键碰撞（sales 覆盖
                        persona）。仅适用于"按 sales turn 取内容"的旧逻辑。需要 persona
                        信号（purchase_signal 等）时请用 turns_by_session（无损全量）。
      prev_customer     {(session_id, sales_idx): 同轮 customer.content}
      turns_by_session  {session_id: [按 idx,插入序 排好的全部 turn rec]}（无损，含 persona）
    """
    if not session_ids:
        return {}, {}, {}

    with sdb.connection_scope() as conn:
        qmarks = ",".join("?" * len(session_ids))
        rows = list(conn.execute(
            f"SELECT session_id, idx, role, content, metadata_json FROM turns "
            f"WHERE session_id IN ({qmarks}) "
            f"ORDER BY session_id ASC, idx ASC",
            session_ids,
        ).fetchall())

    turn_index: dict[tuple[str, int], dict] = {}
    by_sess: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        try:
            meta = json.loads(r["metadata_json"] or "{}")
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
        rec = {
            "role": r["role"],
            "content": r["content"] or "",
            "idx": int(r["idx"]),
            "session_id": r["session_id"],
            "metadata": meta,
        }
        turn_index[(r["session_id"], int(r["idx"]))] = rec
        by_sess[r["session_id"]].append(rec)

    prev_customer: dict[tuple[str, int], str] = {}
    for sid, lst in by_sess.items():
        cur_q = ""
        for t in lst:
            if _is_customer_role(t["role"]):
                cur_q = t["content"]
            elif t["role"] == "sales":
                prev_customer[(sid, t["idx"])] = cur_q
    return turn_index, prev_customer, dict(by_sess)


def _build_turn_highlights(
    *,
    classifications: list[dict],
    label_map: dict[str, str],
    turn_index: dict[tuple[str, int], dict],
    prev_customer: dict[tuple[str, int], str],
    sess_to_persona: dict[str, Any],
    persona_rows: dict[Any, dict],
) -> tuple[list[dict], list[dict]]:
    """合并同一 turn 的多 label，按 avg_quality 排序，取高分/低分 Top N。"""
    grouped: dict[tuple[str, int], dict] = {}
    for c in classifications:
        key = (c["session_id"], int(c["turn_idx"]))
        rec = grouped.setdefault(key, {
            "labels": [],
            "scores_acc": defaultdict(list),
            "issues": [],
            "suggestions": [],
            "references": [],
            "best_conf": -1.0,
            "primary_label": None,
        })
        cid = c["category_id"]
        conf = float(c.get("confidence") or 0.0)
        rec["labels"].append({
            "category_id": cid,
            "label": label_map.get(cid, cid),
            "confidence": round(conf, 3),
        })
        for k, v in (c.get("scores") or {}).items():
            try:
                rec["scores_acc"][k].append(float(v))
            except (TypeError, ValueError):
                pass
        for iss in (c.get("issues") or []):
            txt = str(iss).strip()
            if txt and txt not in rec["issues"]:
                rec["issues"].append(txt)
        sug = (c.get("suggestion") or "").strip()
        if sug and sug not in rec["suggestions"]:
            rec["suggestions"].append(sug)
        ref = (c.get("reference_text") or "").strip()
        if ref and ref not in rec["references"]:
            rec["references"].append(ref)
        if conf > rec["best_conf"]:
            rec["best_conf"] = conf
            rec["primary_label"] = {
                "category_id": cid,
                "label": label_map.get(cid, cid),
            }

    records: list[dict] = []
    for (sid, idx), rec in grouped.items():
        scores_avg = {
            k: round(sum(v) / len(v), 2)
            for k, v in rec["scores_acc"].items() if v
        }
        avg_q = (
            round(sum(scores_avg.values()) / max(1, len(scores_avg)), 2)
            if scores_avg else 0.0
        )
        meta = turn_index.get((sid, idx)) or {}
        sales_content = (meta.get("content") or "").strip()
        if not sales_content:
            continue
        pid = sess_to_persona.get(sid)
        persona_meta = persona_rows.get(pid) or {} if pid is not None else {}
        records.append({
            "session_id": sid,
            "turn_idx": idx,
            "sales_content": sales_content,
            "customer_question": (prev_customer.get((sid, idx), "") or "").strip(),
            "persona_id": pid,
            "persona_name": persona_meta.get("name") or (
                f"#{pid}" if pid is not None else "—"
            ),
            "persona_cluster": persona_meta.get("format_type"),
            "primary_label": rec["primary_label"],
            "labels": rec["labels"],
            "scores": scores_avg,
            "avg_quality": avg_q,
            "issues": rec["issues"][:5],
            "suggestion": " / ".join(rec["suggestions"][:3]),
            "reference_text": rec["references"][0] if rec["references"] else "",
        })

    if not records:
        return [], []

    # 高分：avg_q ≥ 6.5 视为亮点，不够补到 Top 8（哪怕分不高，也要展示"本批最好"）
    # 低分：avg_q < 6.5 视为短板，不够补到 Bottom 8（哪怕分不低，也要展示"本批最差"）
    # 这样小样本不会出现完全空的板块。
    by_high = sorted(records, key=lambda r: -r["avg_quality"])
    excellent = [r for r in by_high if r["avg_quality"] >= 6.5][:15]
    if len(excellent) < 5:
        excellent = by_high[: min(8, len(by_high))]
    by_low = sorted([r for r in records if r["avg_quality"] > 0],
                    key=lambda r: r["avg_quality"])
    problematic = [r for r in by_low if r["avg_quality"] < 6.5][:15]
    if len(problematic) < 5:
        problematic = by_low[: min(8, len(by_low))]
    # 给高分加 why_good，给低分加 why_bad（基于 scores 中最高/最低维度）
    for r in excellent:
        r["why_good"] = _why_good(r)
    for r in problematic:
        r["why_bad"] = _why_bad(r)
    return excellent, problematic


def _why_good(r: dict) -> list[str]:
    """从 6 维分中选 Top-3 高维做"为什么好"，加上 reference_text。"""
    scores = r.get("scores") or {}
    top = sorted(scores.items(), key=lambda x: -x[1])[:3]
    out: list[str] = []
    for dim, sc in top:
        if sc >= 7:
            out.append(
                f"{_DIM_LABEL.get(dim, dim)} {sc}/10 — 显著高于该批次均值"
            )
    if r.get("reference_text"):
        out.append(f"与 Handbook 原文一致：「{r['reference_text'][:60]}…」")
    if r.get("primary_label", {}).get("label"):
        out.append(f"准确切入「{r['primary_label']['label']}」")
    return out[:4]


def _why_bad(r: dict) -> list[str]:
    """从 6 维分中选 Bottom-3 低维做"为什么差"，叠加 issues。"""
    scores = r.get("scores") or {}
    low = sorted(scores.items(), key=lambda x: x[1])[:3]
    out: list[str] = []
    for dim, sc in low:
        if sc < 6:
            out.append(
                f"{_DIM_LABEL.get(dim, dim)} 仅 {sc}/10"
            )
    for iss in (r.get("issues") or [])[:3]:
        out.append(f"问题：{iss}")
    return out[:5]


# ============================================================
# 内部 helper —— 修订建议 / 客户原声 / 关键数字
# ============================================================

def _build_revision_proposals(
    *,
    struct: dict,
    label_map: dict[str, str],
    uncovered: list[str],
    weak_categories: list[dict],
    dim_avg: dict[str, float],
    session_count: int,
    total_classifications: int,
) -> list[dict]:
    """学 v3.1 PDF "调整说明" 段：每条都给：
      kind / severity / 原 Handbook 内容 / 现状证据 / 修订建议
    """
    out: list[dict] = []

    # ① 未覆盖项 → 补充话术
    for cid in uncovered[:10]:
        original = _lookup_handbook_text(cid, struct)
        out.append({
            "kind": "add_missing",
            "category_id": cid,
            "category_label": label_map.get(cid, cid),
            "severity": "high",
            "original": original or "（Handbook 中此条目缺正文或仅有标题）",
            "evidence": (
                f"本批共 {session_count} 场会话 / {total_classifications} 条销冠分类中，"
                f"该条目 0 次被销冠引用，等同于死条目"
            ),
            "suggestion": _suggest_for_uncovered(cid, label_map),
        })

    # ② 短板 → 改进话术
    for w in weak_categories:
        cid = w["category_id"]
        original = _lookup_handbook_text(cid, struct)
        sev = "high" if w["avg_quality"] < 4 else "medium"
        out.append({
            "kind": "improve_existing",
            "category_id": cid,
            "category_label": w["label"],
            "severity": sev,
            "original": original or "（Handbook 中此条目缺正文或仅有标题）",
            "evidence": (
                f"命中 {w['hits']} 次 · 6 维均分 {w['avg_quality']}/10 · "
                f"常见问题：{w['reason']}"
            ),
            "issue_top": w.get("issue_top") or [],
            "suggestion_samples": w.get("suggestion_samples") or [],
            "suggestion": _suggest_for_weak(cid, label_map),
        })

    # ③ 全局 6 维短板 → 整本手册级建议
    for dim, score in (dim_avg or {}).items():
        if score < 5.5:
            out.append({
                "kind": "global_dim",
                "dimension": dim,
                "dimension_label": _DIM_LABEL.get(dim, dim),
                "severity": "high" if score < 4 else "medium",
                "original": "（涉及全本 Handbook 通用规则段）",
                "evidence": (
                    f"全 {total_classifications} 条分类中，"
                    f"{_DIM_LABEL.get(dim, dim)} 维度平均仅 {score}/10"
                ),
                "suggestion": _global_dim_suggestion(dim),
            })

    return out


def _suggest_for_uncovered(cid: str, label_map: dict[str, str]) -> str:
    label = label_map.get(cid, cid)
    grp = cid.split("_")[0] if "_" in cid else cid
    if grp == "sell":
        return (
            f"在 Handbook 中为「{label}」补：① 30 字以内的销冠黄金一句话；"
            f"② 1 个客户痛点引入场景；③ 与之关联的 1 条演示动作 ID；"
            f"④ 1 句 closing-push（试用/价格/邀约）"
        )
    if grp == "comp":
        return (
            f"在 Handbook 中为「{label}」补：① 本机优势的可验证数字对比（如 Ozon 商品页价差%）；"
            f"② 销冠合规话术（不诋毁竞品）；③ 当客户提到竞品时的 3 句快速回应模板"
        )
    if grp == "param":
        return (
            f"在 Handbook 中为「{label}」补：① 参数原值 + 来源（官方海报/PPT 页码）；"
            f"② 一句生活化类比（如「相当于多少..」）；③ 销冠口播范本"
        )
    if grp == "faq":
        return (
            f"在 Handbook 中为「{label}」补：① 客户原问题 3 个常见变体；② 标准答；"
            f"③ 1 句反问对方需求的引导；④ 1 句 closing-push"
        )
    if grp == "demo":
        return (
            f"在 Handbook 中为「{label}」补：① 演示动作的完整 step；② 销冠口播；"
            f"③ 触发时机（什么客户/什么话术后触发）；④ 演示后 1 句过渡至成交"
        )
    return (
        f"在 Handbook 中为「{label}」补：① 销冠黄金句；② 客户场景；"
        f"③ 推进动作；④ 反面禁止说示例"
    )


def _suggest_for_weak(cid: str, label_map: dict[str, str]) -> str:
    label = label_map.get(cid, cid)
    return (
        f"对「{label}」做 v 下一版修订：① 补可验证的具体数字（替换泛词）；"
        f"② 给销冠口播 3 个变体（破冰版 / 紧迫版 / 异议版）；"
        f"③ 列「禁忌说法」清单；④ 配 1 个客户场景演绎案例"
    )


def _global_dim_suggestion(dim: str) -> str:
    sug = {
        "spec_veracity": (
            "在 Handbook 顶部增加「参数真实性红线」段：列出销冠必须复述的"
            "官方数字与原文，禁止自由发挥；并示范 3 句典型的「错位」反面案例"
        ),
        "consumer_language": (
            "为每条卖点/参数增加「可验证渠道 + 具体数字 + 生活化类比」，"
            "把专业参数翻译成大众听得懂的价值；"
            "销冠句式范本：「在 X 场景下，本机 Z 优势相当于…」"
        ),
        "delivery_appeal": (
            "为每条卖点增加：① 3 秒钩子开场；② 1 个生活化类比；"
            "③ 2 个销冠话术变体（破冰版 / 紧迫版），强化节奏与共情"
        ),
        "need_alignment": (
            "按 persona 类型新增「人设触发器」表：列出每种 persona 触发何种话术；"
            "强化「你说的是…」复述客户原问题、贴合实际场景的训练"
        ),
        "conversion_push": (
            "在每个 FAQ / 演示动作末尾追加「下一步推进句」"
            "（试用 → 价格 → 询单 → 邀约下单）；"
            "销冠话术结尾必须有自然、低门槛的动作号召"
        ),
        "behavior_compliance": (
            "重写 Handbook「禁止说」段：明确不能夸大、不能贬竞品、"
            "不能承诺不存在功能；并示范如何用「合规口径」替代风险话术"
        ),
    }
    return sug.get(dim, "建议在 Handbook 顶部增加该维度的训练段")


def _build_customer_voice(
    *,
    turn_index: dict[tuple[str, int], dict],
    sess_to_persona: dict[str, Any],
    persona_rows: dict[Any, dict],
) -> list[dict]:
    """按 persona 聚合：每个 persona 选 6 条最有信息量的客户问句。"""
    by_persona: dict[Any, list[dict]] = defaultdict(list)
    by_sess: dict[str, list[dict]] = defaultdict(list)
    for (sid, idx), rec in turn_index.items():
        by_sess[sid].append({"idx": idx, **rec})
    for sid, lst in by_sess.items():
        pid = sess_to_persona.get(sid)
        lst.sort(key=lambda x: x["idx"])
        for t in lst:
            if not _is_customer_role(t["role"]):
                continue
            content = (t["content"] or "").strip()
            # 过滤过短"你好" / "嗯"
            if len(content) < 8:
                continue
            by_persona[pid].append({
                "session_id": sid,
                "turn_idx": t["idx"],
                "content": content[:240],
                "length": len(content),
            })

    out: list[dict] = []
    for pid, items in by_persona.items():
        meta = persona_rows.get(pid) or {}
        # 按长度倒排选有信息量的；同一 session 内去重保留前 2 条
        seen_sess: Counter = Counter()
        items.sort(key=lambda x: -x["length"])
        picked: list[dict] = []
        for it in items:
            if seen_sess[it["session_id"]] >= 2:
                continue
            seen_sess[it["session_id"]] += 1
            picked.append({
                "session_id": it["session_id"],
                "turn_idx": it["turn_idx"],
                "content": it["content"],
            })
            if len(picked) >= 6:
                break
        out.append({
            "persona_id": pid,
            "persona_name": (meta.get("name")
                             or (f"#{pid}" if pid is not None else "未分组")),
            "persona_cluster": meta.get("format_type") or "未分类",
            "samples": picked,
            "sample_count": len(picked),
        })
    out.sort(key=lambda x: -x["sample_count"])
    return out


_PUNT_KEYWORDS = (
    "官网", "官方网站", "在线查", "稍后回复", "需要查询", "我会查", "可以查询",
    "请查看", "建议您查", "官方渠道", "请咨询", "稍后告诉", "等我确认",
    "需要确认", "我去问", "我帮您查询", "我帮您确认",
)


def _extract_handbook_tokens(struct: dict) -> list[str]:
    """从 handbook 中抽出销售应当口播的关键词 / 短语 / 数字。

    用于计算"销售引用率"：销售 turn 中含至少一个此 token 即记一次命中。
    """
    out: set[str] = set()

    def add(text: str) -> None:
        if not text:
            return
        text = text.strip()
        if 2 <= len(text) <= 20:
            out.add(text)
        # 把短句切分加入（按 / 、 / ， / 。）
        for seg in (
            text.replace("、", "/")
            .replace("，", "/")
            .replace("。", "/")
            .replace("；", "/")
            .split("/")
        ):
            seg = seg.strip()
            if 2 <= len(seg) <= 14:
                out.add(seg)
        # 把数字 token（含单位）单独抽出
        for m in _NUMBER_PATTERN.findall(text):
            m = m.strip()
            if m:
                out.add(m)

    intro = struct.get("intro_1") or {}
    if isinstance(intro, dict):
        add(intro.get("text") or "")
        add(intro.get("label") or "")
    for key in ("selling_points", "competitor_points", "core_params",
                "faq", "demo_actions"):
        for it in struct.get(key) or []:
            for fld in ("label", "text", "q", "a", "vs"):
                if isinstance(it.get(fld), str):
                    add(it[fld])

    # 过滤过于泛的词
    blacklist = {
        "卖点", "竞品", "FAQ", "演示", "参数", "客户", "问题", "回答",
        "建议", "可选", "默认", "标准", "高端", "便宜", "推荐",
    }
    return sorted([t for t in out if t not in blacklist])


def _calc_engagement_metrics(
    *,
    turn_index: dict[tuple[str, int], dict],
    handbook_struct: dict,
    session_ids: list[str] | None = None,
) -> dict[str, Any]:
    """计算销售 turn 健康度指标。

    覆盖：
    - handbook_mention_rate: 销售自报 used_handbook=true OR 含至少 1 个 Handbook 关键词
    - handbook_mention_self_reported_rate: 销售自报 used_handbook=true 的比例
    - handbook_mention_keyword_rate: 关键词匹配命中的比例
    - punt_rate: 销售 turn 含"查官网 / 我帮您查询"等兜底词的比例
    - parse_fail_rate: 销售 turn 是"系统提示：本轮 sales 响应解析失败"的比例
    - repetition_rate: 同一场内 sales 句完全重复的比例（重复 turn 数 / 全部 sales）
    - avg_length: 销售 turn 平均字符数
    """
    tokens = _extract_handbook_tokens(handbook_struct or {})
    tokens = sorted(tokens, key=lambda t: -len(t))

    # 从 DB 拉销售 turn 的 metadata —— 看销售自报的 used_handbook
    self_reported_used_hb: dict[tuple[str, int], bool] = {}
    if session_ids:
        try:
            import json as _json
            with sdb.connection_scope() as conn:
                qmarks = ",".join("?" * len(session_ids))
                rows = list(conn.execute(
                    f"SELECT session_id, idx, metadata_json FROM turns "
                    f"WHERE session_id IN ({qmarks}) AND role = 'sales'",
                    session_ids,
                ).fetchall())
                for r in rows:
                    try:
                        meta = _json.loads(r["metadata_json"] or "{}")
                        self_reported_used_hb[(r["session_id"], int(r["idx"]))] = bool(
                            meta.get("used_handbook")
                        )
                    except Exception:
                        continue
        except Exception:
            pass

    by_sess: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for (sid, idx), rec in turn_index.items():
        if rec.get("role") == "sales":
            content = (rec.get("content") or "").strip()
            if content:
                by_sess[sid].append((idx, content))

    total = sum(len(v) for v in by_sess.values())
    if total == 0:
        return {
            "total_sales_turns": 0,
            "handbook_mention_rate": 0.0,
            "handbook_mention_self_reported_rate": 0.0,
            "handbook_mention_keyword_rate": 0.0,
            "punt_rate": 0.0,
            "parse_fail_rate": 0.0,
            "repetition_rate": 0.0,
            "avg_length": 0.0,
            "top_hit_tokens": [],
            "punt_examples": [],
            "duplicate_examples": [],
            "token_count": len(tokens),
        }

    hit_turns = 0
    self_report_hits = 0
    keyword_hits = 0
    punt_turns = 0
    parse_fail_turns = 0
    length_sum = 0
    token_counter: Counter = Counter()
    punt_examples: list[str] = []
    dup_count = 0
    duplicate_examples: list[str] = []

    for sid, lines in by_sess.items():
        seen_lines: Counter = Counter()
        for idx, line in lines:
            length_sum += len(line)
            if "系统提示" in line and "解析失败" in line:
                parse_fail_turns += 1
                continue
            # 销售自报
            self_reported = self_reported_used_hb.get((sid, idx), False)
            if self_reported:
                self_report_hits += 1
            # handbook 关键词命中
            matched_tokens: list[str] = []
            for tk in tokens:
                if tk in line:
                    matched_tokens.append(tk)
                    if len(matched_tokens) >= 3:
                        break
            if matched_tokens:
                keyword_hits += 1
                for tk in matched_tokens:
                    token_counter[tk] += 1
            # mention：自报 OR 关键词命中（两者之一为真）
            if self_reported or matched_tokens:
                hit_turns += 1
            # 兜底词
            punts = [p for p in _PUNT_KEYWORDS if p in line]
            if punts:
                punt_turns += 1
                if len(punt_examples) < 5:
                    punt_examples.append(f"[{punts[0]}] {line[:100]}")
            # 重复
            key = line[:60]
            seen_lines[key] += 1
        for k, n in seen_lines.items():
            if n >= 2:
                dup_count += (n - 1)
                if len(duplicate_examples) < 5:
                    duplicate_examples.append(f"x{n} {k[:80]}")

    top_hits = [{"token": t, "count": n} for t, n in token_counter.most_common(15)]
    return {
        "total_sales_turns": total,
        "handbook_mention_rate": round(hit_turns / total, 3),
        "handbook_mention_count": hit_turns,
        "handbook_mention_self_reported_rate": round(self_report_hits / total, 3),
        "handbook_mention_keyword_rate": round(keyword_hits / total, 3),
        "punt_rate": round(punt_turns / total, 3),
        "punt_count": punt_turns,
        "parse_fail_rate": round(parse_fail_turns / total, 3),
        "parse_fail_count": parse_fail_turns,
        "repetition_rate": round(dup_count / total, 3),
        "repetition_count": dup_count,
        "avg_length": round(length_sum / total, 1),
        "token_count": len(tokens),
        "top_hit_tokens": top_hits,
        "punt_examples": punt_examples,
        "duplicate_examples": duplicate_examples,
    }


def _build_key_numbers(struct: dict) -> list[dict]:
    """从 core_params / selling_points / faq 中提取所有"销冠应背"的数字。

    每条：{ value, context, source_text, source_group }
    """
    out: list[dict] = []
    seen: set[str] = set()

    def harvest(item: dict, source_label: str) -> None:
        text = (item.get("text") or "").strip()
        label = (item.get("label") or "").strip()
        if not text:
            return
        for m in _NUMBER_PATTERN.findall(text):
            key = (m.strip().lower(), label.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "value": m.strip(),
                "context": label or source_label,
                "source_group": source_label,
                "source_text": text[:140],
            })

    for it in struct.get("core_params") or []:
        harvest(it, "核心参数")
    for it in struct.get("selling_points") or []:
        harvest(it, "卖点")
    for it in struct.get("faq") or []:
        harvest(it, "FAQ")
    for it in struct.get("competitor_points") or []:
        harvest(it, "竞品对比")
    return out[:40]


# ============================================================
# Persona Insights（在 turn_index 基础上轻量优化）
# ============================================================

def _build_persona_insights(
    *,
    classifications: list[dict],
    sess_to_persona: dict[str, Any],
    persona_rows: dict[Any, dict[str, Any]],
    outcomes: Counter,
    label_map: dict[str, str],
    session_ids: list[str],
    turn_index: dict[tuple[str, int], dict] | None = None,
) -> list[dict[str, Any]]:
    """按 persona_id 聚合，包含客户原话样本。"""
    by_persona: dict[Any, list[dict]] = defaultdict(list)
    for c in classifications:
        pid = sess_to_persona.get(c["session_id"])
        by_persona[pid].append(c)

    sess_by_persona: dict[Any, set] = defaultdict(set)
    for sid, pid in sess_to_persona.items():
        sess_by_persona[pid].add(sid)

    # 提客户问句样本（每 persona 取 8 条）
    sample_objections_by_persona: dict[Any, list[str]] = defaultdict(list)
    if turn_index:
        per_sess_objs: dict[str, list[str]] = defaultdict(list)
        for (sid, idx), rec in turn_index.items():
            if _is_customer_role(rec["role"]):
                content = (rec["content"] or "").strip()
                if len(content) >= 8:
                    per_sess_objs[sid].append(content[:80])
        for sid, lst in per_sess_objs.items():
            pid = sess_to_persona.get(sid)
            sample_objections_by_persona[pid].extend(lst[:5])

    sess_quality: dict[str, list[float]] = defaultdict(list)
    for c in classifications:
        sess_quality[c["session_id"]].append(_avg_quality(c.get("scores") or {}))

    sess_outcome_map: dict[str, str] = {}
    if session_ids:
        with sdb.connection_scope() as conn:
            qmarks = ",".join("?" * len(session_ids))
            rows = list(conn.execute(
                f"SELECT id, json_extract(summary_json, '$.outcome') AS outcome "
                f"FROM sessions WHERE id IN ({qmarks})",
                session_ids,
            ).fetchall())
            for r in rows:
                sess_outcome_map[r["id"]] = r["outcome"] or "unknown"

    out: list[dict[str, Any]] = []
    for pid, items in by_persona.items():
        cnt: Counter = Counter()
        for it in items:
            cnt[it["category_id"]] += 1
        top = [
            {"category_id": cid, "label": label_map.get(cid, cid), "count": n}
            for cid, n in cnt.most_common(5)
        ]

        persona_meta = persona_rows.get(pid) if pid is not None else None
        cluster = (persona_meta or {}).get("format_type") or "未分类"

        pid_sess = sess_by_persona.get(pid) or set()
        if pid_sess:
            deals = sum(
                1 for sid in pid_sess if sess_outcome_map.get(sid) == "deal"
            )
            deal_rate = round(deals / len(pid_sess), 3)
        else:
            deal_rate = None

        all_q: list[float] = []
        for sid in pid_sess:
            all_q.extend(sess_quality.get(sid, []))
        avg_quality = round(sum(all_q) / max(1, len(all_q)), 2) if all_q else None

        out.append({
            "persona_id": pid,
            "persona_cluster": cluster,
            "top_concerns": top,
            "sample_objections": sample_objections_by_persona.get(pid, [])[:8],
            "deal_rate": deal_rate,
            "avg_quality": avg_quality,
        })
    out.sort(key=lambda x: (x["deal_rate"] is None, -(x["deal_rate"] or 0)))
    return out
