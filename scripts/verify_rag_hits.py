"""验证 RAG 查询能否真正命中（修完 embedder 维度问题后的回归测试）。

跑几个典型俄罗斯销售/华为 MatePad 的查询，看 product / enterprise 两个
collection 是否各自能返回非空 top_k。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.rag.embedder import get_embedder  # noqa: E402
from src.rag.kb_store import KBStore  # noqa: E402
from src.storage import db as sdb  # noqa: E402


PRODUCT_QUERIES = [
    "MatePad 12X 价格多少？",
    "Цена планшета HUAWEI MatePad 12X",  # 俄语：价格
    "屏幕亮度 多少 nits",
    "护眼模式 蓝光",
    "Сколько весит планшет",  # 俄语：重量
    "充电速度 SuperCharge",
]

ENTERPRISE_QUERIES = [
    "客户嫌贵 怎么处理",
    "异议处理 技巧",
    "Как закрыть сделку",  # 俄语：如何促单
    "建立信任",
]


def _run(kb_id: int, kb_type: str, queries: list[str]) -> None:
    store = KBStore(kb_id=kb_id, kb_type=kb_type)
    print(f"\n=== KB id={kb_id} type={kb_type} ===")
    total_hits = 0
    for q in queries:
        hits = store.query(q, top_k=3, scope_kb_only=True)
        n = len(hits)
        total_hits += n
        if n == 0:
            print(f"  [MISS] {q}")
            continue
        top = hits[0]
        score = top.get("score")
        preview = (top.get("text") or "")[:80].replace("\n", " ")
        print(f"  [HIT x{n}] {q}")
        print(f"    top score={score:.3f}  preview={preview}...")
    print(f"  → 总命中数: {total_hits} / {len(queries) * 3} 可能")


def main() -> None:
    emb = get_embedder()
    emb.ensure_loaded()
    print(f"Embedder: backend={emb.backend} model={emb.model_name} dim={emb.dim}")

    with sdb.connection_scope() as conn:
        product_kbs = sdb.list_kbs(conn, kb_type="product")
        enterprise_kbs = sdb.list_kbs(conn, kb_type="enterprise")

    if not product_kbs:
        print("\n[skip] 没有 product KB")
    else:
        _run(product_kbs[0]["id"], "product", PRODUCT_QUERIES)

    if not enterprise_kbs:
        print("\n[skip] 没有 enterprise KB")
    else:
        _run(enterprise_kbs[0]["id"], "enterprise", ENTERPRISE_QUERIES)


if __name__ == "__main__":
    main()
