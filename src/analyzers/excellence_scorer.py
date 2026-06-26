"""⑥ 优秀话术评分 —— 与「手册一致性」解耦。

核心理念（用户拍板的 6c「两者结合」）：
  一句话是不是"优秀销售话术"，看的是**有效性与说服力**（能否推进成交 / 化解顾虑 /
  建立信任 / 制造心动），**不是**它有没有照搬产品手册。手册里没提到、但很有效的金句
  同样算优秀，并且要单独拎出来喂给"手册迭代建议"（改动⑤）。

判定 = 行为信号（免费，覆盖全部 sales turn）⊕ LLM 优秀度评分（解耦 accuracy）：
  - 行为信号：销冠第 i 轮之后，**下一条客户轮**的 purchase_signal 相对上一条的涨幅、
    attitude 是否转正、是否触发 WALK_AWAY / COMPLAINT。这些字段已落库（persona turn
    metadata），无需任何 LLM。
  - LLM 优秀度：对"行为信号 + 现有维度"预排序出的候选池（封顶 ~50 条）跑一次批量 LLM，
    只判 0-10 优秀度 + why_good，**不以是否命中手册为门槛**。

分组（135910 + 手册外）：
  - 命中手册的 turn → 按其主标签的 135910 类别归组（intro/sell/comp/param/faq/demo）。
  - 未命中手册的 turn → 归入 "off_handbook"（手册外精彩话术）。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from src.analyzers.handbook_scorer import EXCELLENCE_EXCLUDE_DIM
from src.llm import (
    LLMCallError,
    LLMJsonParseError,
    call_llm_json,
    with_llm_override,
)
from src.perf_config import aux_llm_override

logger = logging.getLogger(__name__)

# 135910 + 手册外，前端 / HTML 按此顺序渲染
GROUP_ORDER = ["intro", "sell", "comp", "param", "faq", "demo", "off_handbook"]
GROUP_LABEL = {
    "intro": "一句话定位",
    "sell": "核心卖点",
    "comp": "竞品对比",
    "param": "核心参数",
    "faq": "FAQ 应答",
    "demo": "现场演示",
    "off_handbook": "手册外精彩话术",
}

# 每组最多保留多少条（前端折叠展开，去掉旧版 15 条全局硬上限）
_PER_GROUP_CAP = 20
# 候选池封顶（控制 LLM 成本，满足 SLA）
_CLASSIFIED_POOL = 36
_OFFHB_POOL = 16
# 进入"手册外"候选的最低行为信号分
_OFFHB_MIN_BEHAVIORAL = 6.0
# LLM 批量分片大小
_LLM_CHUNK = 10

# attitude → 正向度（0..1）。未知态度给中性 0.4。
_ATTITUDE_POS = {
    "excited": 1.0, "convinced": 1.0, "interested": 0.95, "positive": 0.9,
    "enthusiastic": 1.0, "delighted": 1.0, "trusting": 0.9, "engaged": 0.75,
    "curious": 0.6, "open": 0.6, "considering": 0.6, "neutral": 0.4,
    "cautious": 0.32, "hesitant": 0.28, "skeptical": 0.22, "doubtful": 0.22,
    "reluctant": 0.2, "annoyed": 0.08, "frustrated": 0.08, "negative": 0.05,
    "hostile": 0.0, "angry": 0.0,
}

# 解析失败占位句（不应进优秀池）
_PARSE_FAIL_MARK = "响应解析失败"


def _attitude_pos(attitude: str | None) -> float:
    return _ATTITUDE_POS.get((attitude or "").strip().lower(), 0.4)


def _group_of_cid(cid: str | None) -> str | None:
    if not cid:
        return None
    head = cid.split("_", 1)[0]
    return head if head in GROUP_LABEL else None


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ============================================================
# 1) 行为信号
# ============================================================

def _neighbor_persona_signals(
    sess_turns: list[dict],
    sales_pos: int,
) -> tuple[float, float, str, str]:
    """给定一条 sales turn 在 session 有序列表中的下标，返回：
        ps_before  —— 该 sales 之前最近一条客户轮的 purchase_signal
        ps_after   —— 该 sales 之后最近一条客户轮的 purchase_signal（= 这句话的即时效果）
        attitude_after —— 之后那条客户轮的 attitude
        status_after   —— 之后那条客户轮的 status（WALK_AWAY / COMPLAINT 等）
    缺失时给中性默认。
    """
    ps_before = 0.0
    found_before = False
    for j in range(sales_pos - 1, -1, -1):
        t = sess_turns[j]
        if _is_persona(t):
            ps_before = _to_float((t.get("metadata") or {}).get("purchase_signal"), 0.0)
            found_before = True
            break

    ps_after = ps_before if found_before else 0.0
    attitude_after = ""
    status_after = ""
    for j in range(sales_pos + 1, len(sess_turns)):
        t = sess_turns[j]
        if _is_persona(t):
            meta = t.get("metadata") or {}
            ps_after = _to_float(meta.get("purchase_signal"), ps_after)
            attitude_after = str(meta.get("attitude") or "")
            status_after = str(meta.get("status") or "")
            break
    return ps_before, ps_after, attitude_after, status_after


def _is_persona(turn: dict) -> bool:
    return (turn.get("role") or "").strip().lower() in ("persona", "customer")


def _behavioral_score(
    ps_before: float,
    ps_after: float,
    attitude_after: str,
    status_after: str,
) -> float:
    """0..10。客户在这句话之后达到的购买信号水平 + 涨幅 + 态度，叠加流失惩罚。"""
    ps_after = max(0.0, min(1.0, ps_after))
    delta = ps_after - ps_before
    # delta ∈ [-0.3, +0.3] 归一化到 [0,1]
    delta_norm = max(0.0, min(1.0, (delta + 0.3) / 0.6))
    base01 = 0.45 * ps_after + 0.30 * delta_norm + 0.25 * _attitude_pos(attitude_after)
    st = (status_after or "").strip().upper()
    if st == "WALK_AWAY":
        base01 *= 0.30
    elif st == "COMPLAINT":
        base01 *= 0.15
    return round(base01 * 10.0, 2)


# ============================================================
# 2) LLM 优秀度评分（解耦手册一致性）
# ============================================================

_LLM_SYSTEM = (
    "你是顶级线下销售话术教练。判断每一条销冠发言是不是『优秀销售话术』——"
    "评判标准是**有效性与说服力**：能否推进成交、化解顾虑、建立信任、制造心动、"
    "把话题引向价值。**绝不**以「是否照搬产品手册」为标准——手册没提到但很有效的金句"
    "同样优秀。只输出 JSON。"
)


def _build_llm_prompt(chunk: list[dict[str, Any]]) -> str:
    lines = []
    for it in chunk:
        cq = (it.get("customer_question") or "").strip()[:200]
        sc = (it.get("sales_content") or "").strip()[:500]
        lines.append(
            f"- id={it['_pid']}\n  客户上一句：{cq or '（无）'}\n  销冠这句：{sc}"
        )
    body = "\n".join(lines)
    return (
        "## 待评销冠发言\n"
        f"{body}\n\n"
        "## 输出格式（**只输出 JSON 对象**，不要 markdown）\n"
        "{\n"
        '  "items": [\n'
        '    {"id": 0, "excellence": 0-10 整数, "why": ["≤25字亮点1", "≤25字亮点2"]}\n'
        "  ]\n"
        "}\n\n"
        "规则：excellence 越高越优秀；why 给 1~2 条「为什么这句好」（聚焦说服技巧/"
        "情绪价值/异议化解，不要复述内容）；每条都要返回；严禁遗漏 id。"
    )


def _llm_excellence(pool: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """对候选池跑批量 LLM，返回 {_pid: {excellence, why}}。失败的分片静默跳过。"""
    out: dict[int, dict[str, Any]] = {}
    for start in range(0, len(pool), _LLM_CHUNK):
        chunk = pool[start:start + _LLM_CHUNK]
        try:
            with with_llm_override(aux_llm_override(thinking_mode="disabled")):
                raw = call_llm_json(
                    _LLM_SYSTEM,
                    _build_llm_prompt(chunk),
                    temperature=0.3,
                )
        except (LLMCallError, LLMJsonParseError) as exc:
            logger.warning("[excellence] LLM 分片失败：%s", exc)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("[excellence] LLM 未知异常：%s", exc)
            continue
        items = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                pid = int(it.get("id"))
            except (TypeError, ValueError):
                continue
            exc_v = max(0.0, min(10.0, _to_float(it.get("excellence"), 0.0)))
            why = [str(w).strip() for w in (it.get("why") or []) if str(w).strip()][:3]
            out[pid] = {"excellence": exc_v, "why": why}
    return out


# ============================================================
# 3) 编排入口
# ============================================================

def build_excellent_by_group(
    *,
    classifications: list[dict[str, Any]],
    label_map: dict[str, str],
    turns_by_session: dict[str, list[dict]],
    prev_customer: dict[tuple[str, int], str],
    sess_to_persona: dict[str, Any],
    persona_rows: dict[Any, dict],
    use_llm: bool = True,
) -> dict[str, Any]:
    """产出 {groups: [...], total: n}，按 135910 + 手册外分组。

    turns_by_session 必须是**无损全量**有序列表（含 persona 轮，带 metadata），
    因为行为信号要读 persona 轮的 purchase_signal/attitude（详见 _load_turn_index 注释）。
    """
    # 3.1 每个 sales turn 在 session 列表中的下标（用于邻居查找）
    sales_pos_index: dict[tuple[str, int], tuple[str, int]] = {}
    for sid, lst in turns_by_session.items():
        for pos, t in enumerate(lst):
            if (t.get("role") or "").strip().lower() == "sales":
                sales_pos_index[(sid, int(t["idx"]))] = (sid, pos)

    # 3.2 命中手册的 turn：主标签 + 非 accuracy 维度均分
    classified: dict[tuple[str, int], dict] = {}
    grouped_clf: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for c in classifications:
        grouped_clf[(c["session_id"], int(c["turn_idx"]))].append(c)
    for key, items in grouped_clf.items():
        best = max(items, key=lambda c: _to_float(c.get("confidence"), 0.0))
        cid = best.get("category_id")
        # 剔除「参数真实性」维度的均分（解耦手册一致性：优秀≠照搬手册）
        eff_vals: list[float] = []
        for c in items:
            for k, v in (c.get("scores") or {}).items():
                if k == EXCELLENCE_EXCLUDE_DIM:
                    continue
                eff_vals.append(_to_float(v, 0.0))
        dim_eff = round(sum(eff_vals) / len(eff_vals), 2) if eff_vals else None
        refs = [c.get("reference_text") for c in items if c.get("reference_text")]
        classified[key] = {
            "cid": cid,
            "group": _group_of_cid(cid) or "off_handbook",
            "label": label_map.get(cid, cid) if cid else "",
            "dim_eff": dim_eff,
            "reference_text": refs[0] if refs else "",
        }

    # 3.3 对所有 sales turn 算行为信号 + 预排序分
    records: list[dict[str, Any]] = []
    for sid, lst in turns_by_session.items():
        for rec in lst:
            if (rec.get("role") or "").strip().lower() != "sales":
                continue
            idx = int(rec["idx"])
            content = (rec.get("content") or "").strip()
            if len(content) < 8 or _PARSE_FAIL_MARK in content:
                continue
            pos_key = sales_pos_index.get((sid, idx))
            if pos_key is None:
                continue
            _sid, pos = pos_key
            ps_before, ps_after, attitude_after, status_after = _neighbor_persona_signals(
                lst, pos
            )
            behavioral = _behavioral_score(ps_before, ps_after, attitude_after, status_after)

            clf = classified.get((sid, idx))
            is_off = clf is None
            if clf and clf["dim_eff"] is not None:
                effectiveness_pre = round(0.5 * behavioral + 0.5 * clf["dim_eff"], 2)
            else:
                effectiveness_pre = behavioral

            pid = sess_to_persona.get(sid)
            persona_meta = persona_rows.get(pid) or {} if pid is not None else {}
            records.append({
                "session_id": sid,
                "turn_idx": idx,
                "sales_content": content,
                "customer_question": (prev_customer.get((sid, idx), "") or "").strip(),
                "persona_id": pid,
                "persona_name": persona_meta.get("name") or (f"#{pid}" if pid is not None else "—"),
                "group": clf["group"] if clf else "off_handbook",
                "handbook_label": clf["label"] if clf else "",
                "is_off_handbook": is_off,
                "behavioral_score": behavioral,
                "purchase_signal_before": round(ps_before, 2),
                "purchase_signal_after": round(ps_after, 2),
                "attitude_after": attitude_after,
                "status_after": status_after,
                "reference_text": clf["reference_text"] if clf else "",
                "_eff_pre": effectiveness_pre,
            })

    if not records:
        return {"groups": [], "total": 0}

    # 3.4 候选池：命中手册 top + 手册外高行为信号 top
    clf_records = [r for r in records if not r["is_off_handbook"]]
    off_records = [r for r in records if r["is_off_handbook"]]
    clf_pool = sorted(clf_records, key=lambda r: -r["_eff_pre"])[:_CLASSIFIED_POOL]
    off_pool = sorted(
        [r for r in off_records if r["behavioral_score"] >= _OFFHB_MIN_BEHAVIORAL],
        key=lambda r: -r["behavioral_score"],
    )[:_OFFHB_POOL]
    pool = clf_pool + off_pool
    for i, r in enumerate(pool):
        r["_pid"] = i

    # 3.5 LLM 优秀度
    llm_out: dict[int, dict[str, Any]] = {}
    if use_llm and pool:
        llm_out = _llm_excellence(pool)

    # 3.6 终评分 + why_good
    for r in pool:
        pid = r["_pid"]
        if pid in llm_out:
            r["excellence_score"] = round(0.5 * r["behavioral_score"] + 0.5 * llm_out[pid]["excellence"], 1)
            r["why_good"] = llm_out[pid]["why"] or _fallback_why(r)
        else:
            r["excellence_score"] = round(r["_eff_pre"], 1)
            r["why_good"] = _fallback_why(r)

    # 3.7 分组 + 排序 + 截断
    groups_map: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        r.pop("_pid", None)
        r.pop("_eff_pre", None)
        groups_map[r["group"]].append(r)

    groups_out: list[dict[str, Any]] = []
    total = 0
    for key in GROUP_ORDER:
        items = sorted(groups_map.get(key, []), key=lambda r: -r["excellence_score"])
        items = items[:_PER_GROUP_CAP]
        if not items:
            continue
        total += len(items)
        groups_out.append({
            "key": key,
            "label": GROUP_LABEL[key],
            "count": len(items),
            "items": items,
        })
    return {"groups": groups_out, "total": total}


def _fallback_why(r: dict[str, Any]) -> list[str]:
    """LLM 缺位时用行为信号合成 why_good。"""
    out: list[str] = []
    delta = r["purchase_signal_after"] - r["purchase_signal_before"]
    if delta >= 0.1:
        out.append(
            f"客户购买信号 {r['purchase_signal_before']:.1f}→{r['purchase_signal_after']:.1f} 明显上升"
        )
    elif r["purchase_signal_after"] >= 0.7:
        out.append(f"客户购买信号维持高位 {r['purchase_signal_after']:.1f}")
    att = (r.get("attitude_after") or "").strip().lower()
    if att and _ATTITUDE_POS.get(att, 0.4) >= 0.6:
        out.append(f"客户态度转为「{r['attitude_after']}」")
    if r.get("reference_text"):
        out.append(f"精准切入「{r['handbook_label']}」")
    if not out:
        out.append("有效推进了对话")
    return out[:3]
