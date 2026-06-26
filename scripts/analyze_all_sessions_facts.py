#!/usr/bin/env python3
"""全量历史会话事实分析（只读，不改代码库逻辑）。"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.storage import db as sdb

# Handbook 135910 关键词桶（MatePad 12X 手册常见 token）
HB_GROUPS = {
    "intro": ("一句话", "定位", "旗舰", "MatePad", "12X", "12 X"),
    "sell": ("纸感", "屏幕", "扬声器", "轻薄", "续航", "卖点", "OLED", "144", "1000"),
    "comp": ("iPad", "三星", "Samsung", "竞品", "对比", "苹果"),
    "param": ("nits", "Hz", "mAh", "66W", "555", "5.9", "HarmonyOS", "参数", "英寸"),
    "faq": ("保修", "以旧换新", "分期", "学生", "办公", "FAQ", "售后"),
    "demo": ("演示", "试用", "摸", "看", "体验", "背板", "珠光"),
}

PUNT_PHRASES = (
    "官网", "官方网站", "在线查", "稍后", "帮您查", "我帮您确认",
    "需要查询", "我去问", "等我确认", "具体价格我", "打开官网",
)

OUTCOME_WALK = {"WALK_AWAY", "COMPLAINT", "TIMEOUT"}


def hb_group_hits(text: str) -> set[str]:
    t = (text or "").lower()
    hit = set()
    for g, kws in HB_GROUPS.items():
        for kw in kws:
            if kw.lower() in t:
                hit.add(g)
                break
    return hit


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with sdb.connection_scope() as conn:
        sessions = list(conn.execute("""
            SELECT s.id, s.persona_id, s.handbook_id, s.topic, s.status,
                   s.started_at, s.ended_at, s.summary_json, s.max_rounds,
                   p.name AS persona_name
            FROM sessions s
            LEFT JOIN personas p ON p.id = s.persona_id
            WHERE s.status IN ('done', 'cancelled', 'failed')
            ORDER BY s.created_at DESC
        """).fetchall())

        # analysis job 15 summary if exists
        job15 = conn.execute(
            "SELECT summary_json FROM analysis_jobs WHERE id=15"
        ).fetchone()
        analysis_summary = {}
        if job15 and job15["summary_json"]:
            try:
                analysis_summary = json.loads(job15["summary_json"])
            except Exception:
                pass

    print("=" * 60)
    print(f"历史会话总数（done/cancelled/failed）: {len(sessions)}")
    print("=" * 60)

    # 1) Outcome 分布
    outcomes = Counter()
    outcome_by_persona: dict[str, Counter] = defaultdict(Counter)
    walk_sessions: list[dict] = []

    for s in sessions:
        summ = {}
        if s["summary_json"]:
            try:
                summ = json.loads(s["summary_json"])
            except Exception:
                pass
        oc = summ.get("outcome") or "UNKNOWN"
        outcomes[oc] += 1
        pname = s["persona_name"] or f"p#{s['persona_id']}"
        outcome_by_persona[pname][oc] += 1
        if oc in OUTCOME_WALK:
            walk_sessions.append({
                "id": s["id"],
                "persona": pname,
                "outcome": oc,
                "rounds": summ.get("total_rounds", 0),
                "handbook_id": s["handbook_id"],
            })

    print("\n【1】结果 Outcome 分布")
    for oc, n in outcomes.most_common():
        pct = n / len(sessions) * 100
        print(f"  {oc:15s} {n:4d} ({pct:.1f}%)")

    # 2) 加载所有 turns 统计
    sales_turns = 0
    persona_turns = 0
    sales_with_punt = 0
    sales_with_hb_any = 0
    sales_hb_groups: Counter = Counter()
    persona_hb_groups: Counter = Counter()
    last_persona_before_walk: list[str] = []

    session_sales_hb_rate: list[tuple[str, float]] = []
    session_chatter_score: list[tuple[str, float]] = []  # 非135910话题占比粗估

    CHATTER_KW = (
        "天气", "吃饭", "你好", "谢谢", "再见", "哈哈", "嗯嗯",
        "了解一下", "随便看看", "再看看", "考虑一下",
    )

    with sdb.connection_scope() as conn:
        for s in sessions:
            sid = s["id"]
            turns = list(conn.execute(
                "SELECT idx, role, content, metadata_json FROM turns "
                "WHERE session_id=? ORDER BY idx",
                (sid,),
            ).fetchall())
            summ = json.loads(s["summary_json"] or "{}") if s["summary_json"] else {}
            oc = summ.get("outcome") or "UNKNOWN"

            s_sales = 0
            s_hb = 0
            s_chatter = 0
            last_persona_line = ""

            for t in turns:
                role = t["role"]
                content = t["content"] or ""
                if role == "sales":
                    sales_turns += 1
                    s_sales += 1
                    if any(p in content for p in PUNT_PHRASES):
                        sales_with_punt += 1
                    gh = hb_group_hits(content)
                    if gh:
                        sales_with_hb_any += 1
                        s_hb += 1
                        for g in gh:
                            sales_hb_groups[g] += 1
                    if any(c in content for c in CHATTER_KW) and not gh:
                        s_chatter += 1
                elif role == "persona":
                    persona_turns += 1
                    last_persona_line = content.strip()
                    gh = hb_group_hits(content)
                    for g in gh:
                        persona_hb_groups[g] += 1

            if s_sales:
                session_sales_hb_rate.append((sid, s_hb / s_sales))
                session_chatter_score.append((sid, s_chatter / s_sales))

            if oc in OUTCOME_WALK and last_persona_line:
                last_persona_before_walk.append(last_persona_line[:120])

    print(f"\n【2】Turn 量级: 销冠 {sales_turns} / 客户 {persona_turns}")
    if sales_turns:
        print(f"  销冠「查官网/推诿」率: {sales_with_punt/sales_turns*100:.1f}%")
        print(f"  销冠至少命中1个135910桶: {sales_with_hb_any/sales_turns*100:.1f}%")
    print("  销冠话术按135910桶命中次数:")
    for g in ("intro", "sell", "comp", "param", "faq", "demo"):
        print(f"    {g:6s}: {sales_hb_groups[g]}")
    print("  客户发言按135910桶命中次数:")
    for g in ("intro", "sell", "comp", "param", "faq", "demo"):
        print(f"    {g:6s}: {persona_hb_groups[g]}")

    avg_hb = sum(r for _, r in session_sales_hb_rate) / max(1, len(session_sales_hb_rate))
    print(f"\n  场均销冠 Handbook 桶命中率: {avg_hb*100:.1f}%")

    # 3) 离开原因：从最后客户句 + metadata 抽样
    print(f"\n【3】客户离开类会话 {len(walk_sessions)} 场")
    print("  最后一条客户话（Walk/Complaint/Timeout 前，抽样15条）:")
    for line in last_persona_before_walk[:15]:
        print(f"    · {line}")

    # metadata walk_away
    walk_reasons = Counter()
    with sdb.connection_scope() as conn:
        for s in walk_sessions[:200]:
            rows = conn.execute(
                "SELECT metadata_json FROM turns WHERE session_id=? AND role='persona' "
                "ORDER BY idx DESC LIMIT 3",
                (s["id"],),
            ).fetchall()
            for r in rows:
                try:
                    meta = json.loads(r["metadata_json"] or "{}")
                except Exception:
                    meta = {}
                for k in ("walk_away_reason", "status", "attitude", "intent"):
                    v = meta.get(k)
                    if v:
                        walk_reasons[f"{k}={v}"] += 1

    if walk_reasons:
        print("\n  Persona turn metadata 中的离开/态度信号 Top:")
        for k, n in walk_reasons.most_common(12):
            print(f"    {k}: {n}")

    # 4) Analysis job 15 覆盖率（若存在）
    if analysis_summary:
        print("\n【4】Batch#13 分析报告 (Job#15) 135910 覆盖事实")
        cov = analysis_summary.get("category_coverage") or {}
        uncov = analysis_summary.get("uncovered_categories") or []
        eng = analysis_summary.get("engagement") or {}
        print(f"  Handbook 条目覆盖率: {analysis_summary.get('coverage_pct', 0):.1f}%")
        print(f"  未覆盖条目数: {len(uncov)}")
        if uncov[:8]:
            print(f"  未覆盖样例: {uncov[:8]}")
        cbg = analysis_summary.get("coverage_by_group") or {}
        for g, st in cbg.items():
            print(f"    group {g}: {st.get('coverage_pct',0):.0f}%覆盖, "
                  f"质量{st.get('weighted_avg_quality',0):.1f}")
        print(f"  销冠 Handbook 提及率(分析器): {eng.get('handbook_mention_rate',0)*100:.1f}%")
        print(f"  推诿率: {eng.get('punt_rate',0)*100:.1f}%")
        weak = analysis_summary.get("weak_categories") or []
        print("  弱项 Top3:")
        for w in weak[:3]:
            print(f"    - {w.get('label')}: 均分{w.get('avg_quality')}, {w.get('reason','')[:60]}")

    # 5) 抽样：高轮次但低 handbook 的会话 vs 成交会话
    print("\n【5】典型对比（销冠低Handbook命中 vs 相对高命中）")
    low = sorted(session_sales_hb_rate, key=lambda x: x[1])[:3]
    high = sorted(session_sales_hb_rate, key=lambda x: -x[1])[:3]

    def sample_session(sid: str, label: str) -> None:
        with sdb.connection_scope() as conn:
            turns = conn.execute(
                "SELECT idx, role, content FROM turns WHERE session_id=? "
                "ORDER BY idx LIMIT 8",
                (sid,),
            ).fetchall()
            summ = conn.execute(
                "SELECT summary_json FROM sessions WHERE id=?", (sid,)
            ).fetchone()
        oc = "?"
        if summ and summ["summary_json"]:
            try:
                oc = json.loads(summ["summary_json"]).get("outcome", "?")
            except Exception:
                pass
        print(f"\n  [{label}] {sid} outcome={oc}")
        for t in turns:
            role = "客" if t["role"] == "persona" else "销"
            c = (t["content"] or "")[:100].replace("\n", " ")
            print(f"    R{t['idx']} {role}: {c}")

    for sid, rate in low:
        sample_session(sid, f"低HB命中 {rate*100:.0f}%")
    for sid, rate in high:
        sample_session(sid, f"高HB命中 {rate*100:.0f}%")

    # 6) Persona 维度离开率
    print("\n【6】离开率最高的人设 Top8（Walk+Complaint+Timeout / 总场次）")
    persona_stats = []
    for pname, oc_counter in outcome_by_persona.items():
        total = sum(oc_counter.values())
        walk = sum(oc_counter.get(x, 0) for x in OUTCOME_WALK)
        if total >= 2:
            persona_stats.append((walk / total, walk, total, pname))
    for rate, walk, total, pname in sorted(persona_stats, reverse=True)[:8]:
        print(f"  {pname[:20]:20s} 离开 {walk}/{total} ({rate*100:.0f}%)")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
