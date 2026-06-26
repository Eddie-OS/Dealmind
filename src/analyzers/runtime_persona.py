"""运行时按对话判定客户类型 A/B/C/D（仅 playbook_v1）。

输入一场对话的客户原话 + playbook 预设的人设清单，由 LLM 判定该场对话的客户
最接近哪一类人设；结果落 SQLite 缓存（session_runtime_persona），同一对话 + 同一
人设清单不重复调 LLM。

设计取舍：
- 仅 playbook_v1 生效（旧 135910 无 A/B/C/D 人设轴，直接返回空）。
- 候选人设从结构里动态抽取（open.persona_openers / say[].persona），数量不固定。
- 缓存键 = session_id；同时存人设清单指纹 struct_fp，手册结构变化后自动失效重判。
- LLM 不可达 / 解析失败时退化为 "?"（不阻断报告生成）。
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from src.llm import LLMCallError, LLMJsonParseError, call_llm_json
from src.storage import db as sdb

logger = logging.getLogger(__name__)

_TABLE = "session_runtime_persona"

_SYS_PROMPT = (
    "你是一名销售培训分析师。根据一段真实客户在对话中的发言，"
    "判断该客户最接近产品手册里预设的哪一类人设。"
    "只能从给定候选里选一个代号，必须返回 JSON。"
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_table(conn) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
            session_id    TEXT PRIMARY KEY,
            handbook_id   INTEGER,
            persona       TEXT,
            persona_label TEXT,
            reason        TEXT,
            struct_fp     TEXT,
            source        TEXT,
            updated_at    TEXT
        )"""
    )


def _persona_catalog(struct: dict) -> list[dict[str, str]]:
    """从 playbook 结构抽出可选人设类型 [{persona, persona_label, hint}]（变长）。"""
    seen: dict[str, dict[str, Any]] = {}

    open_blk = struct.get("open") or {}
    for po in open_blk.get("persona_openers") or []:
        if not isinstance(po, dict):
            continue
        p = (po.get("persona") or "").strip()
        if not p:
            continue
        d = seen.setdefault(p, {"persona_label": "", "hints": []})
        if po.get("persona_label") and not d["persona_label"]:
            d["persona_label"] = str(po["persona_label"]).strip()
        if po.get("text"):
            d["hints"].append(str(po["text"]).strip())

    for blk in struct.get("say") or []:
        if not isinstance(blk, dict):
            continue
        p = (blk.get("persona") or "").strip()
        if not p:
            continue
        d = seen.setdefault(p, {"persona_label": "", "hints": []})
        if blk.get("persona_label") and not d["persona_label"]:
            d["persona_label"] = str(blk["persona_label"]).strip()
        for pt in blk.get("points") or []:
            if isinstance(pt, dict) and pt.get("label"):
                d["hints"].append(str(pt["label"]).strip())

    out: list[dict[str, str]] = []
    for k in sorted(seen):
        v = seen[k]
        out.append({
            "persona": k,
            "persona_label": v["persona_label"],
            "hint": " / ".join([h for h in v["hints"] if h][:4]),
        })
    return out


def _fingerprint(catalog: list[dict[str, str]]) -> str:
    raw = json.dumps(catalog, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _customer_excerpt(turns: list[dict], max_turns: int = 8, max_chars: int = 900) -> str:
    out: list[str] = []
    for t in turns or []:
        role = (t.get("role") or "").strip().lower()
        if role not in ("persona", "customer"):
            continue
        c = (t.get("content") or "").strip()
        if c:
            out.append(c)
        if len(out) >= max_turns:
            break
    txt = "\n".join(f"- {c}" for c in out)
    return txt[:max_chars]


def _build_user_prompt(catalog: list[dict[str, str]], excerpt: str) -> str:
    lines = ["候选人设类型："]
    for c in catalog:
        hint = f"，典型关注点：{c['hint']}" if c["hint"] else ""
        lines.append(f"- {c['persona']}（{c['persona_label']}）{hint}")
    lines.append("")
    lines.append("客户发言节选：")
    lines.append(excerpt or "（无有效客户发言）")
    lines.append("")
    lines.append(
        '请只返回 JSON：{"persona":"<候选代号，如 A>","reason":"<不超过30字的依据>"}。'
        '若实在无法判断，persona 用 "?"。'
    )
    return "\n".join(lines)


def classify_sessions(
    *,
    struct: dict,
    turns_by_session: dict[str, list[dict]],
    handbook_id: int | None = None,
    use_cache: bool = True,
) -> dict[str, dict[str, str]]:
    """对每场对话判定客户类型。

    Returns:
        {session_id: {"persona": "A"|"?", "persona_label": str, "source": "cache"|"llm"|"fallback"}}
        非 playbook 或无人设清单时返回空 dict。
    """
    if (struct or {}).get("doc_type") != "playbook_v1":
        return {}
    catalog = _persona_catalog(struct or {})
    if not catalog:
        return {}

    fp = _fingerprint(catalog)
    label_of = {c["persona"]: c["persona_label"] for c in catalog}
    valid = set(label_of.keys())
    result: dict[str, dict[str, str]] = {}
    sids = list((turns_by_session or {}).keys())
    if not sids:
        return {}

    with sdb.connection_scope() as conn:
        _ensure_table(conn)

        cached: dict[str, dict[str, str]] = {}
        if use_cache:
            qm = ",".join("?" * len(sids))
            for r in conn.execute(
                f"SELECT session_id, persona, persona_label, struct_fp "
                f"FROM {_TABLE} WHERE session_id IN ({qm})",
                sids,
            ).fetchall():
                if r["struct_fp"] == fp:
                    cached[r["session_id"]] = {
                        "persona": r["persona"] or "?",
                        "persona_label": r["persona_label"] or "",
                        "source": "cache",
                    }

        for sid in sids:
            if sid in cached:
                result[sid] = cached[sid]
                continue

            excerpt = _customer_excerpt(turns_by_session.get(sid) or [])
            persona, reason = "?", ""
            try:
                data = call_llm_json(
                    _SYS_PROMPT,
                    _build_user_prompt(catalog, excerpt),
                    temperature=0.0,
                )
                if isinstance(data, dict):
                    p = str(data.get("persona") or "").strip()
                    if p in valid:
                        persona = p
                        reason = str(data.get("reason") or "").strip()[:60]
            except (LLMCallError, LLMJsonParseError) as e:
                logger.warning("[runtime_persona] session=%s 判定失败：%s", sid, e)

            rec = {
                "persona": persona,
                "persona_label": label_of.get(persona, ""),
                "source": "llm" if persona != "?" else "fallback",
            }
            result[sid] = rec
            conn.execute(
                f"INSERT OR REPLACE INTO {_TABLE} "
                f"(session_id, handbook_id, persona, persona_label, reason, "
                f" struct_fp, source, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (sid, handbook_id, persona, rec["persona_label"], reason,
                 fp, rec["source"], _now_iso()),
            )
        conn.commit()

    return result


def build_conversation_persona_breakdown(
    *,
    struct: dict,
    classifications: list[dict],
    session_personas: dict[str, dict[str, str]],
    outcome_by_session: dict[str, str] | None = None,
) -> dict[str, Any]:
    """对话侧人设分布 + 各类型话术覆盖。

    - distribution：每类客户出现在多少场对话里（含 outcome 拆分）。
    - per_type_coverage：某类客户的对话里，该类专属话术（open_X/say_X_*）被覆盖多少。
    """
    from src.analyzers.handbook_classifier import _iter_categories

    if not session_personas:
        return {}

    cats = _iter_categories(struct or {})
    # persona → 该类专属话术 category id 集
    persona_cats: dict[str, set[str]] = {}
    for c in cats:
        p = (c.get("persona") or "").strip()
        if p:
            persona_cats.setdefault(p, set()).add(c["id"])

    # session → 命中的 category 集
    sess_hit_cats: dict[str, set[str]] = {}
    for c in classifications:
        sid = c.get("session_id")
        cid = c.get("category_id")
        if sid and cid:
            sess_hit_cats.setdefault(sid, set()).add(cid)

    outcome_by_session = outcome_by_session or {}

    # 汇总
    slots: dict[str, dict[str, Any]] = {}
    for sid, info in session_personas.items():
        p = info.get("persona") or "?"
        slot = slots.setdefault(p, {
            "persona": p,
            "persona_label": info.get("persona_label") or "",
            "sessions": 0,
            "outcomes": {},
            "_covered_cats": set(),
        })
        if info.get("persona_label") and not slot["persona_label"]:
            slot["persona_label"] = info["persona_label"]
        slot["sessions"] += 1
        oc = outcome_by_session.get(sid) or "unknown"
        slot["outcomes"][oc] = slot["outcomes"].get(oc, 0) + 1
        own = persona_cats.get(p) or set()
        slot["_covered_cats"] |= (sess_hit_cats.get(sid, set()) & own)

    distribution: list[dict[str, Any]] = []
    for p in sorted(slots):
        s = slots[p]
        own_total = len(persona_cats.get(p) or set())
        covered = len(s["_covered_cats"])
        distribution.append({
            "persona": s["persona"],
            "persona_label": s["persona_label"],
            "sessions": s["sessions"],
            "outcomes": s["outcomes"],
            "own_cats_total": own_total,
            "own_cats_covered": covered,
            "own_coverage_pct": round(100.0 * covered / own_total, 1) if own_total else 0.0,
        })

    classified = sum(1 for v in session_personas.values() if (v.get("persona") or "?") != "?")
    return {
        "distribution": distribution,
        "session_total": len(session_personas),
        "classified": classified,
    }
