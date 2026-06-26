"""Handbook Analysis 模块 · Handbook 管理 API。

Sprint 1 范围（本文件）：
- GET    /api/handbooks                     列表
- POST   /api/handbooks                     新建（仅 name + product_kb_id + description）
- GET    /api/handbooks/{id}                详情（含 structure_json）
- PUT    /api/handbooks/{id}                修改 name / description / structure_json
- DELETE /api/handbooks/{id}                删除（级联 files / jobs / classifications）
- GET    /api/handbooks/{id}/files          文件列表 + 解析状态
- POST   /api/handbooks/{id}/files          上传一个或多个文件 → 同步解析为 parsed_text
- DELETE /api/handbooks/{id}/files/{fid}    删除单文件
- POST   /api/handbooks/{id}/extract        触发 LLM 抽取 1/3/3/5/9/10（Sprint 2 完成）
- GET    /api/handbooks/{id}/extract_status 查询抽取状态

设计要点：
- 复用 src/rag/parsers.py 的 parse_file()，所有格式开箱即用
- 上传文件 UUID 重命名落盘到 data/handbook_uploads/
- parsed_text 同步存表，便于后续 extract / 校对时直接读
- 一个文件上传一次性完成 解析+入库，不走后台索引线程（数量小、要立即可见）
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from src.config import PROJECT_ROOT
from src.rag.parsers import SUPPORTED_SUFFIXES, parse_file
from src.storage import db as storage_db


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/handbooks", tags=["handbooks"])


_UPLOAD_DIR = PROJECT_ROOT / "data" / "handbook_uploads"
_MAX_PARSED_TEXT_BYTES = 500 * 1024
_MAX_FILE_BYTES = 50 * 1024 * 1024


def _ensure_upload_dir() -> Path:
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return _UPLOAD_DIR


def get_db():
    conn = storage_db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ============================================================
# Pydantic schemas
# ============================================================

class HandbookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=128)
    product_kb_id: Optional[int] = None
    description: Optional[str] = Field(None, max_length=512)


class HandbookUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    product_kb_id: Optional[int] = None
    description: Optional[str] = Field(None, max_length=512)
    structure: Optional[dict[str, Any]] = None
    bump_version: bool = False


# ============================================================
# Serializers
# ============================================================

def _serialize_handbook(row: dict[str, Any], *, include_structure: bool = False) -> dict[str, Any]:
    out = {
        "id": row["id"],
        "name": row["name"],
        "product_kb_id": row.get("product_kb_id"),
        "description": row.get("description"),
        "status": row.get("status", "draft"),
        "version_no": row.get("version_no", 1),
        "extraction_log": row.get("extraction_log"),
        "source_files_json": row.get("source_files_json") or [],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if include_structure:
        out["structure"] = row.get("structure_json") or {}
        struct = out["structure"] if isinstance(out["structure"], dict) else {}
        out["structure_stats"] = {
            "intro_1": 1 if struct.get("intro_1") else 0,
            "selling_points": len(struct.get("selling_points") or []),
            "competitor_points": len(struct.get("competitor_points") or []),
            "core_params": len(struct.get("core_params") or []),
            "faq": len(struct.get("faq") or []),
            "demo_actions": len(struct.get("demo_actions") or []),
        }
    return out


def _serialize_file(row: dict[str, Any], *, include_text: bool = False) -> dict[str, Any]:
    parsed_text = row.get("parsed_text") or ""
    out = {
        "id": row["id"],
        "handbook_id": row["handbook_id"],
        "filename": row["filename"],
        "file_type": row.get("file_type"),
        "file_size": row.get("file_size"),
        "status": row.get("status", "pending"),
        "error_msg": row.get("error_msg"),
        "parsed_text_length": len(parsed_text),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if include_text:
        out["parsed_text"] = parsed_text
    return out


def _ensure_handbook(conn, handbook_id: int) -> dict[str, Any]:
    hb = storage_db.get_handbook(conn, handbook_id)
    if not hb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Handbook 不存在")
    return hb


def _parse_to_text(path: Path) -> str:
    """复用 KB 同款 parser，把 chunks 拼成全文（带 Slide/Section 标记）。"""
    chunks = parse_file(path)
    parts: list[str] = []
    for c in chunks:
        section = c.get("section") or ""
        text = (c.get("text") or "").strip()
        if not text:
            continue
        if section:
            parts.append(f"[{section}]\n{text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


# ============================================================
# Handbook CRUD
# ============================================================

@router.get("")
def list_handbooks_endpoint(conn=Depends(get_db)) -> dict[str, Any]:
    rows = storage_db.list_handbooks(conn)
    return {
        "items": [_serialize_handbook(r) for r in rows],
        "total": len(rows),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_handbook_endpoint(
    body: HandbookCreate,
    conn=Depends(get_db),
) -> dict[str, Any]:
    if storage_db.get_handbook_by_name(conn, body.name):
        raise HTTPException(409, f"Handbook 名称已存在: {body.name}")
    hb_id = storage_db.create_handbook(
        conn,
        name=body.name,
        product_kb_id=body.product_kb_id,
        description=body.description,
    )
    return _serialize_handbook(
        storage_db.get_handbook(conn, hb_id), include_structure=True,
    )


@router.get("/{handbook_id}")
def get_handbook_endpoint(
    handbook_id: int,
    conn=Depends(get_db),
) -> dict[str, Any]:
    hb = _ensure_handbook(conn, handbook_id)
    return _serialize_handbook(hb, include_structure=True)


@router.put("/{handbook_id}")
def update_handbook_endpoint(
    handbook_id: int,
    body: HandbookUpdate,
    conn=Depends(get_db),
) -> dict[str, Any]:
    _ensure_handbook(conn, handbook_id)

    if body.name is not None and body.name.strip():
        exists = storage_db.get_handbook_by_name(conn, body.name.strip())
        if exists and int(exists["id"]) != handbook_id:
            raise HTTPException(409, f"Handbook 名称已被占用: {body.name}")

    new_status = "ready" if body.structure is not None else None
    updated = storage_db.update_handbook(
        conn,
        handbook_id,
        name=body.name,
        product_kb_id=body.product_kb_id,
        description=body.description,
        structure=body.structure,
        status=new_status,
        bump_version=body.bump_version,
    )
    return _serialize_handbook(updated, include_structure=True)


@router.delete("/{handbook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_handbook_endpoint(handbook_id: int, conn=Depends(get_db)) -> None:
    _ensure_handbook(conn, handbook_id)
    # 同时清掉物理上传文件（保留审计可改 False）
    files = storage_db.list_handbook_files(conn, handbook_id)
    storage_db.delete_handbook(conn, handbook_id)
    for f in files:
        try:
            Path(f["file_path"]).unlink(missing_ok=True)
        except OSError:
            pass


# ============================================================
# Handbook Files
# ============================================================

@router.get("/{handbook_id}/files")
def list_handbook_files_endpoint(
    handbook_id: int,
    conn=Depends(get_db),
) -> dict[str, Any]:
    _ensure_handbook(conn, handbook_id)
    rows = storage_db.list_handbook_files(conn, handbook_id)
    return {
        "items": [_serialize_file(r) for r in rows],
        "total": len(rows),
    }


@router.get("/{handbook_id}/files/{file_id}")
def get_handbook_file_endpoint(
    handbook_id: int,
    file_id: int,
    include_text: bool = False,
    conn=Depends(get_db),
) -> dict[str, Any]:
    _ensure_handbook(conn, handbook_id)
    row = storage_db.get_handbook_file(conn, file_id)
    if not row or int(row["handbook_id"]) != handbook_id:
        raise HTTPException(404, "文件不存在或不属于该 Handbook")
    return _serialize_file(row, include_text=include_text)


@router.post("/{handbook_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_handbook_files(
    handbook_id: int,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """同步上传 + 解析为 parsed_text。

    与 KB 上传的差异：
    - 不走后台索引线程，解析必须在请求内完成（供后续 LLM 抽取读取）
    - parsed_text 直接存表，便于校对编辑器读
    """
    if not files:
        raise HTTPException(422, "至少上传一个文件")

    payloads: list[tuple[str, bytes, str]] = []
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
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(
                413,
                f"文件过大 {len(data)/1024/1024:.1f}MB > 50MB（{f.filename}）",
            )
        payloads.append((f.filename or f"upload{suffix}", data, suffix))

    upload_dir = _ensure_upload_dir()
    created_files: list[dict[str, Any]] = []

    with storage_db.connection_scope() as conn:
        _ensure_handbook(conn, handbook_id)

        for filename, data, suffix in payloads:
            safe_name = f"{uuid.uuid4().hex}{suffix}"
            dest = upload_dir / safe_name
            dest.write_bytes(data)

            file_id = storage_db.create_handbook_file(
                conn,
                handbook_id=handbook_id,
                filename=filename,
                file_path=str(dest.resolve()),
                file_type=suffix.lstrip("."),
                file_size=len(data),
                status="parsing",
            )

            try:
                parsed = _parse_to_text(dest)
                if not parsed.strip():
                    raise RuntimeError("解析后内容为空")
                truncated = parsed.encode("utf-8")[:_MAX_PARSED_TEXT_BYTES].decode(
                    "utf-8", errors="ignore",
                )
                storage_db.update_handbook_file(
                    conn,
                    file_id,
                    parsed_text=truncated,
                    status="parsed",
                )
            except Exception as exc:
                logger.warning(
                    "parse handbook file failed handbook=%s file=%s: %s",
                    handbook_id, filename, exc,
                )
                storage_db.update_handbook_file(
                    conn,
                    file_id,
                    status="failed",
                    error_msg=str(exc)[:500],
                )

            created_files.append(
                _serialize_file(storage_db.get_handbook_file(conn, file_id))
            )

    return {"imported": len(created_files), "items": created_files}


@router.delete(
    "/{handbook_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_handbook_file_endpoint(
    handbook_id: int,
    file_id: int,
    conn=Depends(get_db),
) -> None:
    _ensure_handbook(conn, handbook_id)
    row = storage_db.get_handbook_file(conn, file_id)
    if not row or int(row["handbook_id"]) != handbook_id:
        raise HTTPException(404, "文件不存在或不属于该 Handbook")
    storage_db.delete_handbook_file(conn, file_id)
    try:
        Path(row["file_path"]).unlink(missing_ok=True)
    except OSError:
        pass


# ============================================================
# Extract（Sprint 2 完整实现；Sprint 1 仅占位）
# ============================================================

@router.post("/{handbook_id}/extract", status_code=status.HTTP_202_ACCEPTED)
def trigger_extract_endpoint(
    handbook_id: int,
    doc_type: str = Query(
        default="handbook_135910",
        description="结构类型：handbook_135910（默认，旧 1/3/3/5/9/10）| playbook_v1（按人设+4章流程）",
    ),
    conn=Depends(get_db),
) -> dict[str, Any]:
    """触发 LLM 从已解析文件抽取结构。

    doc_type：
      - handbook_135910（默认）：旧 1/3/3/5/9/10 结构；
      - playbook_v1：新「按人设 + 4 章流程」结构（变长）。

    状态机：
      draft / ready / failed → extracting → ready / failed
      已在 extracting 中 → 409，避免重复触发

    异步：后台线程跑，立即返回 202。
    抽取完成后会自动 bump_version 并 set status=ready；structure_json 落库。
    """
    hb = _ensure_handbook(conn, handbook_id)
    files = storage_db.list_handbook_files(conn, handbook_id)
    parsed_files = [
        f for f in files
        if (f.get("parsed_text") or "").strip()
        and f.get("status") == "parsed"
    ]
    if not parsed_files:
        raise HTTPException(
            422,
            "请先上传至少一份可解析的来源文件（status=parsed）",
        )
    if hb.get("status") == "extracting":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "已有抽取任务正在进行，请稍候",
        )

    # 标记为 extracting + 清空旧 log
    storage_db.update_handbook(
        conn, handbook_id,
        status="extracting",
        extraction_log="started",
    )

    # 后台线程
    import threading
    from src.analyzers.handbook_extractor_runner import run_extract_in_background
    threading.Thread(
        target=run_extract_in_background,
        args=(handbook_id, doc_type),
        daemon=True,
        name=f"hb-extract-{handbook_id}",
    ).start()

    return {
        "handbook_id": handbook_id,
        "status": "extracting",
        "doc_type": doc_type,
        "ready_files": len(parsed_files),
        "message": "已开始抽取，可通过 GET /api/handbooks/{id}/extract_status 轮询",
    }


@router.get("/{handbook_id}/extract_status")
def get_extract_status_endpoint(
    handbook_id: int,
    conn=Depends(get_db),
) -> dict[str, Any]:
    hb = _ensure_handbook(conn, handbook_id)
    return {
        "handbook_id": handbook_id,
        "status": hb.get("status"),
        "version_no": hb.get("version_no", 1),
        "extraction_log": hb.get("extraction_log"),
    }
