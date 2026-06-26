"""知识库 7 接口（蓝图 §Stage 4）。

- GET    /api/kbs?kb_type=                     KB 列表（可按 product/enterprise 过滤）
- POST   /api/kbs                              新建 KB
- DELETE /api/kbs/{kb_id}                      删除 KB（连带 files + 向量 chunks）
- GET    /api/kbs/{kb_id}/files                列出该 KB 全部文件 + 状态
- POST   /api/kbs/{kb_id}/files                上传一个或多个文件 → 入库 pending + 触发后台索引
- DELETE /api/kbs/{kb_id}/files/{file_id}      删除单文件（含向量库 chunks）
- POST   /api/kbs/{kb_id}/query                检索测试：text + top_k → top hits

设计：
- 上传走 async endpoint + 自管 connection（避开 Depends(get_db) 跨线程问题，
  Stage 3 已遇到过；这里复用同样模式）。
- 索引一律走 src.rag.seed.start_indexer_thread() 的后台 daemon。
- 删除 KB / 删除文件时主动调 KBStore 清理向量库 chunks 后再 SQL DELETE。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from src.config import PROJECT_ROOT
from src.rag.embedder import get_embedder
from src.rag.kb_store import KBStore
from src.rag.parsers import SUPPORTED_SUFFIXES
from src.rag.seed import start_indexer_thread
from src.storage import db as storage_db


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kbs", tags=["knowledge_bases"])


_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"


def _ensure_upload_dir() -> Path:
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return _UPLOAD_DIR


def get_db():
    conn = storage_db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ===== Pydantic schemas =====


class KBCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=128)
    kb_type: Literal["product", "enterprise", "experience"] = "product"
    description: Optional[str] = Field(None, max_length=512)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(3, ge=1, le=20)
    scope_kb_only: bool = True


# ===== helpers =====


def _serialize_kb(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "kb_type": row["kb_type"],
        "description": row.get("description"),
        "file_count": row.get("file_count", 0),
        "chunk_count": row.get("chunk_count", 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _serialize_file(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kb_id": row["kb_id"],
        "filename": row["filename"],
        "file_type": row.get("file_type"),
        "file_size": row.get("file_size"),
        "chunk_count": row.get("chunk_count", 0),
        "status": row.get("status", "pending"),
        "error_msg": row.get("error_msg"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _ensure_kb(conn, kb_id: int) -> dict[str, Any]:
    kb = storage_db.get_kb_by_id(conn, kb_id)
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
    return kb


# ===== endpoints =====


@router.get("")
def list_kbs(
    kb_type: Optional[str] = None,
    conn=Depends(get_db),
) -> dict[str, Any]:
    rows = storage_db.list_kbs(conn, kb_type=kb_type)
    return {"items": [_serialize_kb(r) for r in rows], "total": len(rows)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_kb_endpoint(body: KBCreate, conn=Depends(get_db)) -> dict[str, Any]:
    if storage_db.get_kb_by_name(conn, body.name):
        raise HTTPException(409, f"KB 名称已存在: {body.name}")
    kb_id = storage_db.create_kb(
        conn,
        name=body.name,
        kb_type=body.kb_type,
        description=body.description,
    )
    return _serialize_kb(storage_db.get_kb_by_id(conn, kb_id))


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kb_endpoint(kb_id: int, conn=Depends(get_db)) -> None:
    kb = _ensure_kb(conn, kb_id)
    # 先清向量库
    try:
        KBStore(kb_id=kb_id, kb_type=kb["kb_type"]).delete_by_kb()
    except Exception as exc:
        logger.warning("delete chroma chunks failed kb=%s: %s", kb_id, exc)
    storage_db.delete_kb(conn, kb_id)


@router.get("/{kb_id}/files")
def list_files(kb_id: int, conn=Depends(get_db)) -> dict[str, Any]:
    _ensure_kb(conn, kb_id)
    rows = storage_db.list_kb_files(conn, kb_id)
    return {"items": [_serialize_file(r) for r in rows], "total": len(rows)}


@router.post("/{kb_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_files(
    kb_id: int,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """支持一次多文件上传。落盘到 data/uploads/，登记 pending，触发后台索引。"""
    if not files:
        raise HTTPException(422, "至少上传一个文件")

    # 校验 + 读 bytes（async 段）
    payloads: list[tuple[str, bytes, str]] = []  # (filename, data, suffix)
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                422,
                f"不支持的格式 {suffix}（{f.filename}）。"
                f"支持: {', '.join(SUPPORTED_SUFFIXES)}",
            )
        data = await f.read()
        if not data:
            raise HTTPException(422, f"文件为空: {f.filename}")
        payloads.append((f.filename or f"upload{suffix}", data, suffix))

    upload_dir = _ensure_upload_dir()
    created_files: list[dict[str, Any]] = []

    # 同步段：自管 conn 避开跨线程
    with storage_db.connection_scope() as conn:
        _ensure_kb(conn, kb_id)
        kb = storage_db.get_kb_by_id(conn, kb_id)
        for filename, data, suffix in payloads:
            safe_name = f"{uuid.uuid4().hex}{suffix}"
            dest = upload_dir / safe_name
            dest.write_bytes(data)
            file_id = storage_db.create_kb_file(
                conn,
                kb_id=kb_id,
                filename=filename,
                file_path=str(dest.resolve()),
                file_type=suffix.lstrip("."),
                file_size=len(data),
                status="pending",
            )
            created_files.append(_serialize_file(storage_db.get_kb_file(conn, file_id)))

    # 触发后台索引
    start_indexer_thread()

    return {"imported": len(created_files), "items": created_files}


@router.delete(
    "/{kb_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_file_endpoint(kb_id: int, file_id: int, conn=Depends(get_db)) -> None:
    kb = _ensure_kb(conn, kb_id)
    row = storage_db.get_kb_file(conn, file_id)
    if not row or row["kb_id"] != kb_id:
        raise HTTPException(404, "文件不存在或不属于该 KB")
    try:
        KBStore(kb_id=kb_id, kb_type=kb["kb_type"]).delete_by_file(file_id)
    except Exception as exc:
        logger.warning("chroma delete_by_file failed: %s", exc)
    storage_db.delete_kb_file(conn, file_id)
    storage_db.recompute_kb_stats(conn, kb_id)
    # 物理文件留作审计；如需删除可下面 unlink
    try:
        Path(row["file_path"]).unlink(missing_ok=True)  # type: ignore[arg-type]
    except OSError:
        pass


@router.post("/{kb_id}/query")
def query_endpoint(
    kb_id: int,
    body: QueryRequest,
    conn=Depends(get_db),
) -> dict[str, Any]:
    kb = _ensure_kb(conn, kb_id)
    store = KBStore(kb_id=kb_id, kb_type=kb["kb_type"])
    hits = store.query(body.text, top_k=body.top_k, scope_kb_only=body.scope_kb_only)
    return {
        "kb_id": kb_id,
        "kb_name": kb["name"],
        "kb_type": kb["kb_type"],
        "query": body.text,
        "top_k": body.top_k,
        "hits": hits,
        "embedder": get_embedder().info(),
    }


@router.get("/meta/embedder", tags=["knowledge_bases"])
def embedder_info() -> dict[str, Any]:
    """返回当前嵌入模型信息（前端可显示在头部）。"""
    return get_embedder().info()
