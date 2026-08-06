"""C3 · Handbook 注入效果 baseline 分析

对所有 sessions 中销冠 turns 做轻量统计：
  1) 多少 turn 带 handbook_inject metadata（注入生效率）
  2) 销冠话里实际命中 Handbook 卖点 / 参数 / FAQ 关键词的频率（引用率）
  3) 按 session 分组，按 persona 分组，看是否所有人都被 Handbook "绑住"

不调用任何 LLM，只读数据库，几秒出报告。

用法：
    cd f:\\Dealmind
    python scripts/c3_handbook_baseline_report.py [--limit 50]
    python scripts/c3_handbook_baseline_report.py --hb-id 1 --since 2026-05-27
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.storage import db as sdb


# ============================================================
# 关键词抽取
# ============================================================

# 用于"销冠是否引用 Handbook XX 项"的关键词抓取——按 label/text 双向收集
# 然后从销冠话里抓任意子串命中
def collect_keywords(struct: dict) -> dict[str, list[str]]:
    """从 handbook structure 抽取分组关键词。

    Returns:
        { category_id: [keyword1, keyword2, ...] }
        category_id 形如 sell_1 / comp_2 / param_3 / faq_4 / demo_5 / intro_1
    """
    kw_map: dict[str, list[str]] = {}

    def _push(cid: str, *texts: str) -> None:
        seen: set[str] = set()
        bucket: list[str] = []
        for t in texts:
            if not t:
                continue
            # 中文/英文分词：取 2-12 字符的连续片段，跳过纯标点
            for frag in re.split(r"[，。；：、,;:!\?！？\(\)（）\[\]\n\r\t·•—\-—\|]+", t):
                frag = frag.strip()
                if 3 <= len(frag) <= 16 and frag not in seen:
                    seen.add(frag)
                    bucket.append(frag)
        if bucket:
            kw_map[cid] = bucket

    intro = struct.get("intro_1") or {}
    if isinstance(intro, dict):
        _push("intro_1", intro.get("label", ""), intro.get("text", ""))

    for grp_key, prefix in [
        ("selling_points", "sell"),
        ("competitor_points", "comp"),
        ("core_params", "param"),
        ("faq", "faq"),
        ("demo_actions", "demo"),
    ]:
        for i, it in enumerate(struct.get(grp_key) or [], 1):
            cid = it.get("id") or f"{prefix}_{i}"
            if grp_key == "faq":
                _push(cid, it.get("label", ""), it.get("q", ""), it.get("a", ""))
            elif grp_key == "competitor_points":
                _push(cid, it.get("label", ""), it.get("vs", ""), it.get("text", ""))
            else:
                _push(cid, it.get("label", ""), it.get("text", ""))
    return kw_map


def hit_categories(content: str, kw_map: dict[str, list[str]]) -> list[str]:
    """返回命中的 category_id 列表（去重）。"""
    if not content:
        return []
    hits: list[str] = []
    for cid, words in kw_map.items():
        for w in words:
            if w and w in content:
                hits.append(cid)
                break  # 命中一次即可
    return hits


# ============================================================
# 主流程
# ============================================================

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hb-id", type=int, default=None,
                    help="Handbook id（默认取库里第一份 ready）")
    ap.add_argument("--limit", type=int, default=50,
                    help="最近 N 场 session（按 created_at 倒序）")
    ap.add_argument("--since", type=str, default=None,
                    help="只看 created_at >= 此 ISO 时间的 session")
    args = ap.parse_args()

    with sdb.connection_scope() as conn:
        # 1) 取目标 Handbook
        if args.hb_id:
            hb = sdb.get_handbook(conn, args.hb_id)
        else:
            ready = sdb.list_handbooks(conn, status="ready")
            hb = ready[0] if ready else None
        if not hb:
            print("ERROR: 没有 ready Handbook")
            sys.exit(1)
        hb_id = int(hb["id"])
        print(f"Target Handbook: #{hb_id} {hb['name']}")
        struct = hb.get("structure_json") or {}
        kw_map = collect_keywords(struct)
        print(f"  - 抽取分组关键词: {len(kw_map)} 个 category")
        for cid, ws in list(kw_map.items())[:3]:
            print(f"    * {cid}: {ws[:3]}{' ...' if len(ws) > 3 else ''}")
        print()

        # 2) 取 sessions（按时间倒序）
        sql = "SELECT id, persona_id, handbook_id, topic, created_at, summary_json FROM sessions"
        params: list = []
        where_parts: list[str] = []
        if args.since:
            where_parts.append("created_at >= ?")
            params.append(args.since)
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(args.limit))
        sessions = list(conn.execute(sql, params).fetchall())
        print(f"Scanning {len(sessions)} sessions...")

        # 3) 取每场销冠 turns + metadata
        per_session: list[dict] = []
        per_persona_hits: dict[int, Counter] = defaultdict(Counter)
        per_persona_total: dict[int, int] = defaultdict(int)
        total_sales_turns = 0
        total_with_inject = 0
        total_hits_any = 0

        for sess in sessions:
            sid = sess["id"]
            rows = list(conn.execute(
                "SELECT idx, role, content, metadata_json FROM turns "
                "WHERE session_id = ? AND role = 'sales' ORDER BY idx ASC",
                (sid,),
            ).fetchall())
            if not rows:
                continue
            session_total = len(rows)
            session_with_inject = 0
            session_hit_count = 0
            session_hit_categories: Counter = Counter()
            for t in rows:
                meta = {}
                try:
                    meta = json.loads(t["metadata_json"] or "{}")
                except Exception:
                    pass
                inj = meta.get("handbook_inject") or {}
                if inj.get("handbook_id"):
                    session_with_inject += 1
                hits = hit_categories(t["content"] or "", kw_map)
                if hits:
                    session_hit_count += 1
                    for cid in hits:
                        session_hit_categories[cid] += 1
                        per_persona_hits[sess["persona_id"]][cid] += 1
                per_persona_total[sess["persona_id"]] += 1

            total_sales_turns += session_total
            total_with_inject += session_with_inject
            total_hits_any += session_hit_count

            per_session.append({
                "session_id": sid,
                "persona_id": sess["persona_id"],
                "handbook_id": sess["handbook_id"],
                "topic": sess["topic"],
                "sales_turns": session_total,
                "with_handbook_inject": session_with_inject,
                "hit_any_turns": session_hit_count,
                "hit_rate": round(session_hit_count / session_total, 3) if session_total else 0,
                "top_categories": session_hit_categories.most_common(5),
            })

        if total_sales_turns == 0:
            print("没有任何销冠 turn，无法分析")
            sys.exit(0)

        # 4) 输出 baseline 报告
        print("=" * 72)
        print("BASELINE REPORT")
        print("=" * 72)
        print(f"销冠 turn 总数（所有场次）  : {total_sales_turns}")
        print(f"携带 handbook_inject 签名   : {total_with_inject} "
              f"({total_with_inject/total_sales_turns*100:.1f}%)")
        print(f"销冠话命中任意 Handbook 项 : {total_hits_any} "
              f"({total_hits_any/total_sales_turns*100:.1f}%)")
        print()
        print("Top 10 最常被引用的 Handbook 项：")
        global_cat: Counter = Counter()
        for s in per_session:
            for cid, n in s["top_categories"]:
                global_cat[cid] += n
        for cid, n in global_cat.most_common(10):
            label = _label_for(struct, cid)
            print(f"  {cid:12s} · {n:4d} 次 · {label}")
        print()

        # 5) 输出 5 场样本（最新 5 个）
        print("最近 5 场样本：")
        print(f"{'session_id':38s} {'persona':>4s} {'sales':>5s} "
              f"{'inj%':>5s} {'hit%':>5s}  top categories")
        for s in per_session[:5]:
            inj_pct = (s["with_handbook_inject"] / s["sales_turns"] * 100) if s["sales_turns"] else 0
            hit_pct = s["hit_rate"] * 100
            cats = ",".join(c for c, _ in s["top_categories"][:3]) or "—"
            print(
                f"  {s['session_id'][:36]:38s} {s['persona_id'] or '-':>4} "
                f"{s['sales_turns']:>5d} {inj_pct:>4.0f}% {hit_pct:>4.0f}%  {cats}"
            )

        # 6) 写入 JSON 报告
        out = ROOT / "data" / "analysis_reports" / "c3_baseline.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "handbook_id": hb_id,
                    "handbook_name": hb["name"],
                    "sessions_scanned": len(per_session),
                    "total_sales_turns": total_sales_turns,
                    "total_with_handbook_inject": total_with_inject,
                    "total_hits_any": total_hits_any,
                    "top_categories": dict(global_cat.most_common(20)),
                    "per_session": per_session,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n报告已写入: {out}")


def _label_for(struct: dict, cid: str) -> str:
    """根据 category_id 返回原 label，找不到返回空。"""
    if cid == "intro_1":
        return (struct.get("intro_1") or {}).get("label", "") or "一句话定位"
    prefix = cid.split("_")[0]
    grp_map = {
        "sell": "selling_points",
        "comp": "competitor_points",
        "param": "core_params",
        "faq": "faq",
        "demo": "demo_actions",
    }
    grp = grp_map.get(prefix)
    if not grp:
        return ""
    for it in struct.get(grp) or []:
        if it.get("id") == cid:
            return it.get("label", "")
    return ""


if __name__ == "__main__":
    main()
