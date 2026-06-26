#!/usr/bin/env python3
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from src.storage import db as sdb
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with sdb.connection_scope() as conn:
    j = conn.execute("SELECT summary_json FROM analysis_jobs WHERE id=15").fetchone()
    s = json.loads(j["summary_json"])
    cov = s.get("category_coverage") or {}
    print("=== 135910 各条目命中次数 ===")
    for cid, v in sorted(cov.items(), key=lambda x: -x[1].get("hits", 0)):
        lab = (v.get("label") or "")[:22]
        print(f"  {cid:12s} {lab:22s} hits={v['hits']} avgQ={v.get('avg_quality', 0)}")
    uncov = s.get("uncovered_categories") or []
    print(f"\n未覆盖 {len(uncov)} 条:", uncov)
    prob = s.get("problematic_turns") or []
    print("\n=== 问题话术 Top5 ===")
    for t in prob[:5]:
        print(f"R{t.get('turn_idx')} {t.get('persona_name', '')[:18]}")
        print(f"  销: {(t.get('sales_content') or '')[:100]}")
        for w in (t.get("why_bad") or [])[:2]:
            print(f"  - {w}")
