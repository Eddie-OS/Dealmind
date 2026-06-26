"""Persona 人设库 7 接口（蓝图 §Stage 3）。

- GET    /api/personas                       列表 + 筛选
- GET    /api/personas/{id}                  详情
- POST   /api/personas                       手动创建（structured 或 prompt_based）
- POST   /api/personas/upload                上传 .json/.yaml/.md/.txt（支持 panel JSON 批量）
- POST   /api/personas/{id}/extract_pressure 对 prompt_based 抽 9 维量化参数
- PATCH  /api/personas/{id}                  部分更新（含调参 / 改 prompt）
- DELETE /api/personas/{id}                  删除

说明：
- 蓝图列出的 POST /api/personas/generate（LLM 文本生成）在本阶段先不做，
  优先保证 44 预填 + 上传 + 调参三大核心闭环。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from src.persona.generator import clarify_persona_idea, generate_persona_draft
from src.persona.parser import PersonaParseError, parse_persona_file, parse_persona_payload
from src.persona.pressure_extractor import DEFAULT_PRESSURE, DIMENSIONS, extract_pressure_profile
from src.storage import db as storage_db


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/personas", tags=["personas"])


def get_db():
    conn = storage_db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ===== Pydantic schemas =====


class PressureProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    trust_threshold: float = Field(0.5, ge=0.0, le=1.0)
    patience: float = Field(0.5, ge=0.0, le=1.0)
    competitor_awareness: float = Field(0.5, ge=0.0, le=1.0)
    decision_power: float = Field(0.5, ge=0.0, le=1.0)
    emotion_volatility: float = Field(0.5, ge=0.0, le=1.0)
    need_urgency: float = Field(0.5, ge=0.0, le=1.0)
    skepticism: float = Field(0.5, ge=0.0, le=1.0)
    bargaining_aggressiveness: float = Field(0.5, ge=0.0, le=1.0)


class PersonaCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    format_type: Literal["structured", "prompt_based"] = "prompt_based"
    prompt_text: Optional[str] = None
    profile: Optional[dict[str, Any]] = None   # structured 字段集合（age/occupation/...）
    pressure: Optional[PressureProfileBody] = None
    source: Optional[str] = Field(None, max_length=128)
    tags: list[str] = Field(default_factory=list)
    locale: str = Field("zh-CN", max_length=16)
    avatar_key: Optional[str] = Field(None, pattern=r"^p\d{2}$", description="notion 头像 key，留空自动分配")


class PersonaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=128)
    format_type: Optional[Literal["structured", "prompt_based"]] = None
    prompt_text: Optional[str] = None
    profile: Optional[dict[str, Any]] = None
    pressure: Optional[PressureProfileBody] = None
    source: Optional[str] = None
    tags: Optional[list[str]] = None
    locale: Optional[str] = None
    pressure_extracted: Optional[bool] = None
    avatar_key: Optional[str] = Field(None, pattern=r"^p\d{2}$")
    # v0.2.1 真实性 / 地区一致性补丁
    country_code: Optional[str] = Field(None, max_length=8, description="ISO-3166-1 alpha-2，如 MY/PH/CN")
    country_name: Optional[str] = Field(None, max_length=64)
    currency: Optional[str] = Field(None, max_length=8, description="ISO-4217，如 MYR/PHP/CNY")
    market_domains: Optional[list[str]] = Field(None, description="该市场可信信源域名清单，web_search 锁此列表")


# ===== helpers =====


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """DB row dict → 对外 JSON。空 profile 用 {} 填充避免前端判空麻烦。"""
    return {
        "id": row["id"],
        "name": row["name"],
        "format_type": row["format_type"],
        "prompt_text": row.get("prompt_text"),
        "profile": row.get("profile") or {},
        "pressure": row.get("pressure") or {},
        "source": row.get("source"),
        "tags": row.get("tags") or [],
        "locale": row.get("locale") or "zh-CN",
        "pressure_extracted": bool(row.get("pressure_extracted")),
        "avatar_key": row.get("avatar_key"),
        # v0.2.1 真实性 / 地区一致性
        "country_code": row.get("country_code"),
        "country_name": row.get("country_name"),
        "currency": row.get("currency"),
        "market_domains": row.get("market_domains") or [],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ===== endpoints =====


@router.get("")
def list_personas(
    format_type: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
    conn=Depends(get_db),
) -> dict[str, Any]:
    rows = storage_db.list_personas(
        conn,
        format_type=format_type,
        tag=tag,
        search=search,
        limit=limit,
    )
    return {"items": [_serialize(r) for r in rows], "total": len(rows)}


@router.get("/{persona_id}")
def get_persona(persona_id: int, conn=Depends(get_db)) -> dict[str, Any]:
    row = storage_db.get_persona_by_id(conn, persona_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona 不存在")
    return _serialize(row)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_persona(body: PersonaCreate, conn=Depends(get_db)) -> dict[str, Any]:
    # prompt_based 必须有 prompt_text；structured 必须有 personality 或 pain_points
    if body.format_type == "prompt_based" and not (body.prompt_text and body.prompt_text.strip()):
        raise HTTPException(422, "prompt_based 模式必须填写 prompt_text")
    if body.format_type == "structured":
        profile = body.profile or {}
        if not profile.get("personality") and not profile.get("pain_points"):
            raise HTTPException(422, "structured 模式 profile 至少包含 personality 或 pain_points")

    pressure = body.pressure.model_dump() if body.pressure else DEFAULT_PRESSURE.copy()
    new_id = storage_db.create_persona(
        conn,
        name=body.name,
        format_type=body.format_type,
        prompt_text=body.prompt_text,
        profile=body.profile,
        pressure=pressure,
        source=body.source or "manual",
        tags=body.tags,
        locale=body.locale,
        pressure_extracted=body.pressure is not None,
        avatar_key=body.avatar_key,
    )
    row = storage_db.get_persona_by_id(conn, new_id)
    return _serialize(row)


class PersonaGenerateAnswer(BaseModel):
    question: str
    answer: Any  # str | list[str]


class PersonaGenerate(BaseModel):
    idea: str = Field("", max_length=4000, description="用户对客户的粗略想法")
    answers: Optional[list[PersonaGenerateAnswer]] = None
    skip_clarify: bool = Field(False, description="True 时跳过澄清直接生成")


@router.post("/generate")
def generate_persona(body: PersonaGenerate) -> dict[str, Any]:
    """AI 辅助生成人设（草稿不落库，前端预览/编辑后再走 POST /api/personas 创建）。

    smart 流程：
      - 首次（无 answers 且未 skip_clarify）→ 判断 idea 是否够完整：
          不够 → 返回 {status:"need_clarification", questions:[...]}；
          够   → 直接生成 {status:"ok", draft:{...}}。
      - 带 answers / skip_clarify → 直接生成草稿。
    """
    idea = (body.idea or "").strip()
    answers = [a.model_dump() for a in body.answers] if body.answers else None

    if not answers and not body.skip_clarify:
        clarify = clarify_persona_idea(idea)
        if clarify.get("need_clarification"):
            return {"status": "need_clarification", "questions": clarify.get("questions", [])}

    if not idea and not answers:
        raise HTTPException(422, "请先描述你的大致想法")

    try:
        draft = generate_persona_draft(idea, answers)
    except Exception as exc:  # noqa: BLE001
        logger.warning("generate_persona 失败：%s", exc)
        raise HTTPException(502, f"AI 生成失败，请重试：{exc}") from exc
    return {"status": "ok", "draft": draft}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_persona(file: UploadFile = File(...)) -> dict[str, Any]:
    """支持单条或 panel 批量。文件落到临时目录后用 parser 解析。

    备注：因为本端点是 async（要 await file.read），不再用 Depends(get_db)
    获取 sync 连接（会跨 thread）；改为在 await 后的同步段内自管 connection。
    """
    suffix = Path(file.filename or "upload").suffix.lower() or ".json"
    if suffix not in {".json", ".yaml", ".yml", ".md", ".txt"}:
        raise HTTPException(422, f"不支持的文件格式: {suffix}")

    data = await file.read()
    if not data:
        raise HTTPException(422, "上传文件为空")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        items = parse_persona_file(tmp_path)
    except PersonaParseError as exc:
        raise HTTPException(422, f"文件解析失败: {exc}") from exc
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    if not items:
        raise HTTPException(422, "文件解析后无可用 persona")

    with storage_db.connection_scope() as conn:
        ids = storage_db.bulk_create_personas(conn, items)
        serialized = [_serialize(storage_db.get_persona_by_id(conn, i)) for i in ids]

    return {"imported": len(ids), "ids": ids, "items": serialized}


@router.post("/{persona_id}/extract_pressure")
def extract_pressure(persona_id: int, conn=Depends(get_db)) -> dict[str, Any]:
    """调 LLM 抽取该 persona 的 9 维量化参数并覆盖保存。

    仅 prompt_based persona 有意义；structured 直接 422。
    LLM 失败时 pressure_extractor 已 fallback 全 0.5，这里仍标记 extracted=True
    以便前端流程不卡住——但日志会有 warning。
    """
    row = storage_db.get_persona_by_id(conn, persona_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona 不存在")
    if row["format_type"] != "prompt_based":
        raise HTTPException(422, "仅 prompt_based persona 支持参数抽取")
    prompt = row.get("prompt_text") or ""
    if not prompt.strip():
        raise HTTPException(422, "该 persona 缺少 prompt_text")

    pressure = extract_pressure_profile(prompt)
    storage_db.update_persona(
        conn,
        persona_id,
        pressure=pressure,
        pressure_extracted=True,
    )
    updated = storage_db.get_persona_by_id(conn, persona_id)
    return _serialize(updated)


@router.patch("/{persona_id}")
def update_persona(
    persona_id: int,
    body: PersonaUpdate,
    conn=Depends(get_db),
) -> dict[str, Any]:
    existing = storage_db.get_persona_by_id(conn, persona_id)
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona 不存在")

    update_kwargs: dict[str, Any] = {}
    if body.name is not None:
        update_kwargs["name"] = body.name
    if body.format_type is not None:
        update_kwargs["format_type"] = body.format_type
    if body.prompt_text is not None:
        update_kwargs["prompt_text"] = body.prompt_text
    if body.profile is not None:
        update_kwargs["profile"] = body.profile
    if body.pressure is not None:
        update_kwargs["pressure"] = body.pressure.model_dump()
        # 手动改了参数视为已抽取
        if body.pressure_extracted is None:
            update_kwargs["pressure_extracted"] = True
    if body.source is not None:
        update_kwargs["source"] = body.source
    if body.tags is not None:
        update_kwargs["tags"] = body.tags
    if body.locale is not None:
        update_kwargs["locale"] = body.locale
    if body.pressure_extracted is not None:
        update_kwargs["pressure_extracted"] = body.pressure_extracted
    if body.avatar_key is not None:
        update_kwargs["avatar_key"] = body.avatar_key
    # v0.2.1 真实性 / 一致性 4 个新字段
    if body.country_code is not None:
        update_kwargs["country_code"] = body.country_code or None
    if body.country_name is not None:
        update_kwargs["country_name"] = body.country_name or None
    if body.currency is not None:
        update_kwargs["currency"] = body.currency or None
    if body.market_domains is not None:
        update_kwargs["market_domains"] = body.market_domains

    if not update_kwargs:
        raise HTTPException(422, "未提供任何可更新字段")

    storage_db.update_persona(conn, persona_id, **update_kwargs)
    updated = storage_db.get_persona_by_id(conn, persona_id)
    return _serialize(updated)


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona(persona_id: int, conn=Depends(get_db)) -> None:
    if not storage_db.get_persona_by_id(conn, persona_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona 不存在")
    storage_db.delete_persona(conn, persona_id)


@router.get("/meta/dimensions", tags=["personas"])
def list_dimensions() -> dict[str, list[str]]:
    """前端调参时拉取 9 维定义名（与 extractor 严格一致）。"""
    return {"dimensions": list(DIMENSIONS)}


@router.get("/meta/countries", tags=["personas"])
def list_countries() -> dict[str, Any]:
    """v0.2.1：前端 persona 编辑弹窗的「国家」下拉用。

    返回：[{code: "MY", label: "马来西亚 (MY)", currency: "MYR", domains: [...]}]
    """
    from src.locales import COUNTRY_REGISTRY

    items = [
        {
            "code": m.code,
            "label": f"{m.name_cn} ({m.code})",
            "name_cn": m.name_cn,
            "name_en": m.name_en,
            "currency": m.currency,
            "currency_symbol": m.currency_symbol,
            "default_market_domains": list(m.market_domains),
        }
        for m in COUNTRY_REGISTRY.values()
    ]
    return {"countries": items}
