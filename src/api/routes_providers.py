"""LLM Providers 管理 6 接口（蓝图 §Stage 2）。

- GET    /api/providers                列表
- POST   /api/providers                新增
- PATCH  /api/providers/{id}           更新
- DELETE /api/providers/{id}           删除（拒绝删唯一 default）
- POST   /api/providers/{id}/default   设为默认（热生效）
- POST   /api/providers/test           连通测试（支持已存 provider_id 或临时配置）
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from src import llm
from src.storage import db as storage_db


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/providers", tags=["providers"])


def get_db():
    conn = storage_db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ===== Pydantic schemas =====


class ProviderBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    provider_type: str = Field(..., min_length=1, max_length=32)
    base_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(..., min_length=1, max_length=512)
    model_name: str = Field(..., min_length=1, max_length=128)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_retries: int = Field(2, ge=0, le=10)
    is_active: bool = True
    is_default: bool = False
    extra_config: dict[str, Any] = Field(default_factory=dict)


class ProviderCreate(ProviderBase):
    pass


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    provider_type: Optional[str] = Field(None, min_length=1, max_length=32)
    base_url: Optional[str] = Field(None, min_length=1, max_length=512)
    api_key: Optional[str] = Field(None, min_length=1, max_length=512)
    model_name: Optional[str] = Field(None, min_length=1, max_length=128)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    is_active: Optional[bool] = None
    extra_config: Optional[dict[str, Any]] = None


class ProviderOut(ProviderBase):
    id: int
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class ProviderTestRequest(BaseModel):
    """支持两种用法：传 provider_id 用已存，或传完整配置临时测试。"""
    provider_id: Optional[int] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None


class ProviderTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    reply: str = ""
    error: Optional[str] = None


# ===== 接口 =====


@router.get("", response_model=list[ProviderOut])
def list_all(conn=Depends(get_db)):
    return storage_db.list_providers(conn)


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
def create(payload: ProviderCreate, conn=Depends(get_db)):
    existing = conn.execute(
        "SELECT id FROM llm_providers WHERE name = ?", (payload.name,)
    ).fetchone()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"名称已存在：{payload.name}")

    new_id = storage_db.create_provider(
        conn,
        name=payload.name,
        provider_type=payload.provider_type,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model_name=payload.model_name,
        temperature=payload.temperature,
        max_retries=payload.max_retries,
        is_active=payload.is_active,
        is_default=payload.is_default,
        extra_config=payload.extra_config or None,
    )
    if payload.is_default:
        llm.reset_client_for_test()
        logger.info("新增并设为默认 provider id=%d，已重置 LLM 客户端缓存", new_id)

    row = storage_db.get_provider_by_id(conn, new_id)
    if not row:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "创建后无法读取")
    return row


@router.patch("/{provider_id}", response_model=ProviderOut)
def update(provider_id: int, payload: ProviderUpdate, conn=Depends(get_db)):
    existing = storage_db.get_provider_by_id(conn, provider_id)
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"provider {provider_id} 不存在")

    if payload.name and payload.name != existing["name"]:
        conflict = conn.execute(
            "SELECT id FROM llm_providers WHERE name = ? AND id != ?",
            (payload.name, provider_id),
        ).fetchone()
        if conflict:
            raise HTTPException(status.HTTP_409_CONFLICT, f"名称已存在：{payload.name}")

    fields = payload.model_dump(exclude_none=True)
    if not fields:
        return existing
    storage_db.update_provider(conn, provider_id, **fields)

    if existing["is_default"]:
        llm.reset_client_for_test()
        logger.info("更新了 default provider id=%d，已重置 LLM 客户端缓存", provider_id)

    return storage_db.get_provider_by_id(conn, provider_id)


@router.delete("/{provider_id}")
def remove(provider_id: int, conn=Depends(get_db)):
    existing = storage_db.get_provider_by_id(conn, provider_id)
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"provider {provider_id} 不存在")

    total = conn.execute("SELECT COUNT(*) AS n FROM llm_providers").fetchone()["n"]
    if existing["is_default"] and total > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "不能删除默认 provider，请先把另一条设为默认。",
        )
    if total == 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "不能删除最后一条 provider，至少保留一条。",
        )

    storage_db.delete_provider(conn, provider_id)
    return {"ok": True}


@router.post("/{provider_id}/default", response_model=ProviderOut)
def set_default(provider_id: int, conn=Depends(get_db)):
    ok = storage_db.set_default_provider(conn, provider_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"provider {provider_id} 不存在")

    llm.reset_client_for_test()
    logger.info("set_default → provider id=%d，已重置 LLM 客户端缓存（下次调用生效）", provider_id)

    row = storage_db.get_provider_by_id(conn, provider_id)
    return row


@router.post("/test", response_model=ProviderTestResponse)
def test_connection(payload: ProviderTestRequest, conn=Depends(get_db)):
    """临时构造一次性 OpenAI 客户端发 ping，不污染全局 llm 模块。

    所有异常吃掉返回 {ok:false, error:str}，让前端拿到清晰反馈。
    """
    if payload.provider_id is not None:
        row = storage_db.get_provider_by_id(conn, payload.provider_id)
        if not row:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"provider {payload.provider_id} 不存在",
            )
        base_url = row["base_url"]
        api_key = row["api_key"]
        model_name = row["model_name"]
    else:
        if not (payload.base_url and payload.api_key and payload.model_name):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "未指定 provider_id 时必须同时传 base_url / api_key / model_name",
            )
        base_url = payload.base_url
        api_key = payload.api_key
        model_name = payload.model_name

    t0 = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=20.0)
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=10,
            temperature=0.0,
        )
        latency = int((time.time() - t0) * 1000)
        reply = (resp.choices[0].message.content or "").strip()
        return ProviderTestResponse(
            ok=True, latency_ms=latency, reply=reply, error=None
        )
    except Exception as exc:  # noqa: BLE001
        latency = int((time.time() - t0) * 1000)
        err = f"{type(exc).__name__}: {exc}"
        logger.warning("provider 测试失败 base_url=%s model=%s err=%s", base_url, model_name, err)
        return ProviderTestResponse(
            ok=False, latency_ms=latency, reply="", error=err
        )
