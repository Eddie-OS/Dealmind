"""重建向量索引脚本。

切换嵌入模型（如 bge-small-zh → paraphrase-multilingual-MiniLM-L12-v2）后
必须执行本脚本：旧模型生成的向量维度/语义空间与新模型不同，必须全部清空重建。

使用方法：
    cd f:\\Langraph
    python scripts/rebuild_vector_index.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 必须在所有 src.* 导入之前加载 .env，确保 DM_EMBED_MODEL / HF_ENDPOINT 生效
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rebuild")


def main() -> None:
    logger.info("=== 开始重建向量索引 ===")

    # 1. 清空 Chroma collections
    logger.info("Step 1: 清空 Chroma collections...")
    from src.rag.kb_store import reset_collection
    for kb_type in ("product", "enterprise"):
        reset_collection(kb_type)
        logger.info("  已清空: %s_knowledge", kb_type)

    # 2. 验证新 embedding 模型可加载
    logger.info("Step 2: 加载嵌入模型...")
    from src.rag.embedder import get_embedder
    emb = get_embedder()
    emb.ensure_loaded()
    logger.info("  模型后端: %s  维度: %s", emb.backend, emb.dim)

    # 3. 把所有 indexed 文件重置为 pending，触发重新索引
    logger.info("Step 3: 重置文件状态为 pending...")
    from src.storage import db as storage_db
    with storage_db.connection_scope() as conn:
        kbs = conn.execute("SELECT id FROM knowledge_bases").fetchall()
        all_files = []
        for kb in kbs:
            kb_files = storage_db.list_kb_files(conn, kb["id"])
            all_files.extend(kb_files)
        for f in all_files:
            storage_db.update_kb_file_status(conn, f["id"], status="pending", error_msg="")
            logger.info("  pending: %s", f.get("filename", f["id"]))

    # 4. 启动索引线程
    logger.info("Step 4: 启动后台索引线程...")
    from src.rag.seed import start_indexer_thread
    started = start_indexer_thread()
    logger.info("  索引线程 %s", "已启动" if started else "已在运行")

    # 5. 等待索引完成
    import time
    logger.info("Step 5: 等待索引完成（可能需要 1-5 分钟）...")
    for attempt in range(120):
        time.sleep(5)
        with storage_db.connection_scope() as conn:
            pending = storage_db.list_pending_files(conn)
        if not pending:
            break
        logger.info("  剩余 pending 文件: %d", len(pending))

    # 6. 检查结果
    logger.info("Step 6: 检查索引结果...")
    from src.storage import db as storage_db
    with storage_db.connection_scope() as conn:
        kbs = conn.execute("SELECT id FROM knowledge_bases").fetchall()
        all_files = []
        for kb in kbs:
            all_files.extend(storage_db.list_kb_files(conn, kb["id"]))
    for f in all_files:
        status = f.get("status")
        chunks = f.get("chunk_count", 0)
        err = f.get("error_msg", "")
        logger.info(
            "  [%s] %s  chunks=%s%s",
            status,
            f.get("filename", "?")[:50],
            chunks,
            f"  ERROR: {err[:80]}" if err else "",
        )

    logger.info("=== 重建完成 ===")


if __name__ == "__main__":
    main()
