"""向量库管理 4 接口（蓝图 §Stage 5）。

- GET    /api/vector/collections           列出所有 Chroma collection（含统计 + 关联 KB）
- POST   /api/vector/collections/{name}/rebuild   reset + 复位文件 pending + 启动 indexer
- POST   /api/vector/collections/{name}/clear     reset + 复位文件 pending（不启动 indexer）
- GET    /api/vector/embedder              当前嵌入模型信息卡

设计：
- 复用 Stage 4 的 KBStore / _get_client / reset_collection / start_indexer_thread
- rebuild / clear 走同样的"清向量 + 文件状态回退"原子操作，差别仅在是否触发 indexer
- 占用空间估算：collection chunk_count * dim * 4 bytes（float32）+ data/chroma 目录实际占用
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.config import PROJECT_ROOT
from src.rag.embedder import get_embedder
from src.rag.kb_store import (
    CHROMA_DIR,
    COLLECTION_MAP,
    _get_client,
    reset_collection,
)
from src.rag.seed import start_indexer_thread
from src.storage import db as storage_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vector", tags=["vector_admin"])


# 反向映射：collection_name → kb_type
_COLLECTION_TO_TYPE = {v: k for k, v in COLLECTION_MAP.items()}


def get_db():
    conn = storage_db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _resolve_kb_type(collection_name: str) -> str:
    kb_type = _COLLECTION_TO_TYPE.get(collection_name)
    if not kb_type:
        raise HTTPException(404, f"未知 collection: {collection_name}")
    return kb_type


def _dir_total_bytes(p: Path) -> int:
    """目录递归字节数。"""
    if not p.exists():
        return 0
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _collection_stats(conn, collection_name: str) -> dict[str, Any]:
    """单 collection 的统计：document/chunk 数 + 占用估算 + 关联 KB 列表。"""
    kb_type = _COLLECTION_TO_TYPE.get(collection_name)
    chroma_count = 0
    try:
        client = _get_client()
        col = client.get_collection(collection_name)
        chroma_count = int(col.count())
    except Exception as exc:
        logger.warning("get_collection(%s) failed: %s", collection_name, exc)

    kbs: list[dict[str, Any]] = []
    db_chunk_total = 0
    db_file_total = 0
    if kb_type:
        kb_rows = storage_db.list_kbs(conn, kb_type=kb_type)
        for kb in kb_rows:
            kbs.append(
                {
                    "id": kb["id"],
                    "name": kb["name"],
                    "file_count": int(kb.get("file_count", 0)),
                    "chunk_count": int(kb.get("chunk_count", 0)),
                }
            )
            db_chunk_total += int(kb.get("chunk_count", 0))
            db_file_total += int(kb.get("file_count", 0))

    emb_dim = get_embedder().dim or 0
    estimated_vector_bytes = int(chroma_count * emb_dim * 4)  # float32

    return {
        "name": collection_name,
        "kb_type": kb_type,
        "exists": chroma_count > 0 or bool(kbs),
        "chunk_count": chroma_count,
        "db_chunk_count": db_chunk_total,
        "kb_file_count": db_file_total,
        "kb_count": len(kbs),
        "kbs": kbs,
        "estimated_vector_bytes": estimated_vector_bytes,
    }


# ===== endpoints =====


@router.get("/collections")
def list_collections(conn=Depends(get_db)) -> dict[str, Any]:
    """列出所有 collection（包括尚未实际创建但已规划的）。

    首次调用会触发 embedder 加载（用于计算向量占用估算）；
    若加载失败也不影响列表本身，仅使 estimated_vector_bytes=0。
    """
    try:
        get_embedder().ensure_loaded()
    except Exception as exc:
        logger.warning("embedder lazy-load failed: %s", exc)

    items = [_collection_stats(conn, name) for name in COLLECTION_MAP.values()]
    total_chroma_bytes = _dir_total_bytes(CHROMA_DIR)
    return {
        "items": items,
        "total": len(items),
        "chroma_dir": str(CHROMA_DIR),
        "chroma_dir_bytes": total_chroma_bytes,
        "embedder": get_embedder().info(),
    }


def _reset_files_to_pending(kb_type: str) -> dict[str, int]:
    """该 collection 涉及的所有文件状态回退 pending（chunk_count 清零）。"""
    affected_files = 0
    affected_kbs = 0
    with storage_db.connection_scope() as conn:
        kbs = storage_db.list_kbs(conn, kb_type=kb_type)
        for kb in kbs:
            files = storage_db.list_kb_files(conn, kb["id"])
            for f in files:
                storage_db.update_kb_file_status(
                    conn,
                    f["id"],
                    status="pending",
                    chunk_count=0,
                    error_msg="",
                )
                affected_files += 1
            storage_db.update_kb_stats(
                conn, kb["id"], file_count=0, chunk_count=0
            )
            affected_kbs += 1
    return {"affected_kbs": affected_kbs, "affected_files": affected_files}


@router.post(
    "/collections/{collection_name}/rebuild",
    status_code=status.HTTP_202_ACCEPTED,
)
def rebuild_collection(collection_name: str) -> dict[str, Any]:
    """清空 collection 后复位文件为 pending，并启动后台 indexer 重新索引。"""
    kb_type = _resolve_kb_type(collection_name)
    reset_collection(kb_type)
    counters = _reset_files_to_pending(kb_type)
    started = start_indexer_thread()
    logger.info(
        "rebuild collection %s: kbs=%d files=%d indexer_started=%s",
        collection_name,
        counters["affected_kbs"],
        counters["affected_files"],
        started,
    )
    return {
        "collection": collection_name,
        "kb_type": kb_type,
        **counters,
        "indexer_started": started,
        "message": "已清空向量库 + 复位文件状态，后台索引已启动",
    }


@router.post(
    "/collections/{collection_name}/clear",
    status_code=status.HTTP_200_OK,
)
def clear_collection(collection_name: str) -> dict[str, Any]:
    """仅清空 collection + 复位文件状态，不自动重索引。"""
    kb_type = _resolve_kb_type(collection_name)
    reset_collection(kb_type)
    counters = _reset_files_to_pending(kb_type)
    logger.info(
        "clear collection %s: kbs=%d files=%d",
        collection_name,
        counters["affected_kbs"],
        counters["affected_files"],
    )
    return {
        "collection": collection_name,
        "kb_type": kb_type,
        **counters,
        "message": "已清空向量库 + 复位文件状态（未触发重索引）",
    }


@router.get("/embedder")
def embedder_info() -> dict[str, Any]:
    """嵌入模型信息（与 /api/kbs/meta/embedder 同源，单独暴露便于设置页直接调）。"""
    return get_embedder().info()
