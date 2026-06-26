"""② 离线预研 CLI：为「手册(产品) × 目标市场」批量研究并缓存市场事实表。

用法：
  # 预研所有 persona 实际出现过的市场（推荐：批量跑对话前先跑一遍）
  python scripts/research_markets.py

  # 指定手册 + 指定市场
  python scripts/research_markets.py --handbook 1 --countries MY,RU,TH

  # 强制刷新（忽略缓存新鲜度）
  python scripts/research_markets.py --countries MY --force
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.research.market_research import get_or_research
from src.storage import db

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _distinct_persona_countries(conn) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT country_code FROM personas "
        "WHERE country_code IS NOT NULL AND country_code != ''"
    ).fetchall()
    return sorted({(r["country_code"] or "").upper() for r in rows if r["country_code"]})


def main() -> None:
    ap = argparse.ArgumentParser(description="批量预研市场事实表")
    ap.add_argument("--handbook", type=int, default=None, help="handbook id（默认解析全库默认手册）")
    ap.add_argument("--countries", type=str, default=None, help="逗号分隔的国家码，如 MY,RU,TH")
    ap.add_argument("--force", action="store_true", help="忽略缓存新鲜度强制重研究")
    ap.add_argument("--max-age-days", type=int, default=30, help="缓存新鲜度窗口（天）")
    args = ap.parse_args()

    with db.connection_scope() as conn:
        handbook_id = args.handbook or db.resolve_default_handbook_id(conn)
        hb = db.get_handbook(conn, handbook_id) if handbook_id else None
        print(f"手册：id={handbook_id} name={hb.get('name') if hb else '（未绑定）'}")

        if args.countries:
            countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
        else:
            countries = _distinct_persona_countries(conn)
        print(f"目标市场（{len(countries)}）：{', '.join(countries) or '（无）'}\n")

        for cc in countries:
            row = get_or_research(
                handbook_id=handbook_id,
                country_code=cc,
                max_age_days=args.max_age_days,
                force=args.force,
                conn=conn,
            )
            if not row:
                print(f"[{cc}] 跳过（GLOBAL / 空）")
                continue
            f = row.get("facts") or {}
            op = f.get("own_product") or {}
            comps = f.get("competitors") or []
            print(
                f"[{cc}] 本品价={op.get('price') or '—'} | "
                f"竞品 {len(comps)} 条 | 促销 {len(f.get('promotions') or [])} | "
                f"政策 {len(f.get('policies') or [])} | 卖点 {len(f.get('local_selling_points') or [])} | "
                f"证据强度={f.get('evidence_quality', '?')} | 来源 {len(row.get('sources') or [])}"
            )
        conn.commit()
    print("\n完成。")


if __name__ == "__main__":
    main()
