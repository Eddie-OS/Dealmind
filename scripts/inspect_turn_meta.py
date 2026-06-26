"""快速查 sales turn 的 metadata - 看 handbook_inject、rag_hits 实际值。"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.storage import db as sdb  # noqa: E402

TARGET = "session_20260528_105505_p15"

with sdb.connection_scope() as conn:
    rows = list(conn.execute(
        "SELECT idx, role, content, metadata_json FROM turns "
        "WHERE session_id=? AND role='sales' ORDER BY idx ASC LIMIT 5",
        (TARGET,),
    ).fetchall())

for r in rows:
    meta = json.loads(r["metadata_json"] or "{}")
    print(f"=== sales turn #{r['idx']} ===")
    txt = (r["content"] or "")
    print("content_first_120:", txt[:120])
    hb = meta.get("handbook_inject") or {}
    print(f"hb_inject: id={hb.get('handbook_id')} "
          f"resolved={hb.get('handbook_resolved_from')} "
          f"len={hb.get('handbook_block_len')}")
    rag = meta.get("rag_hits") or {}
    print(f"rag.query: {(rag.get('query') or '')[:120]}")
    print(f"rag.product hits: {len(rag.get('product') or [])}")
    for h in (rag.get("product") or [])[:2]:
        print(f"   - score={h.get('score'):.3f} text={(h.get('text') or '')[:80]}")
    print(f"rag.enterprise hits: {len(rag.get('enterprise') or [])}")
    print(f"used_product_context: {meta.get('used_product_context')}")
    print(f"content_guard: {meta.get('content_guard')}")
    print()
