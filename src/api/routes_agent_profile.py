"""Stage 15a：销冠 Agent 配置中心接口。

  GET    /api/agent-profile/sales             获取当前配置（含 system_prompt 等所有字段）
  PATCH  /api/agent-profile/sales             更新配置（自动建版本快照）
  GET    /api/agent-profile/sales/versions    版本列表（含 snapshot，便于侧栏展示）
  POST   /api/agent-profile/sales/restore     一键回滚到某个历史版本
  POST   /api/agent-profile/sales/try         极简一次性调销冠 Agent，返回回复 + tool_calls

只为 sales 一种 profile 服务。后续扩到 persona/judge/coach 时把 name 路径参数化即可。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-profile", tags=["agent-profile"])

_PROFILE_NAME = "sales"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentProfile(BaseModel):
    id: int
    name: str
    role_description: str = ""
    system_prompt: str = ""
    opening_lines: list[str] = Field(default_factory=list)
    default_session_params: dict[str, Any] = Field(default_factory=dict)
    model_override: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentProfileUpdate(BaseModel):
    role_description: Optional[str] = None
    system_prompt: Optional[str] = None
    opening_lines: Optional[list[str]] = None
    default_session_params: Optional[dict[str, Any]] = None
    model_override: Optional[dict[str, Any]] = None
    version_comment: Optional[str] = Field(
        None,
        description="本次保存的备注（会写入 agent_profile_versions.comment）",
    )


class VersionItem(BaseModel):
    id: int
    version_no: int
    comment: Optional[str] = None
    created_at: str
    snapshot: dict[str, Any] = Field(default_factory=dict)


class VersionsResp(BaseModel):
    name: str
    versions: list[VersionItem]
    total: int


class RestoreReq(BaseModel):
    version_no: int = Field(..., description="要恢复的版本号")


class TryReq(BaseModel):
    customer_opening: str = Field(..., description="客户开场白 / 当前一轮发言内容")
    topic: str = Field("华为 MatePad 12X 学习平板推荐", description="话题（写入 DialogueState.topic）")
    product_kb_id: Optional[int] = None
    enterprise_kb_id: Optional[int] = None
    persona_name: str = Field("试一试·客户", description="客户人设名")
    persona_age: Optional[int] = 30
    round_idx: int = Field(1, ge=1, le=20)
    max_rounds: int = Field(8, ge=2, le=50)
    stage: str = Field("开场与需求暴露")


class TryRespToolCall(BaseModel):
    loop: int = 0
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_preview: str = ""
    ok: bool = True


class TryResp(BaseModel):
    ok: bool
    content: str = ""
    strategy: dict[str, Any] = Field(default_factory=dict)
    tool_mode: Optional[str] = None
    tool_calls: list[TryRespToolCall] = Field(default_factory=list)
    used_product_kb: list[str] = Field(default_factory=list)
    used_enterprise_kb: list[str] = Field(default_factory=list)
    error: Optional[str] = None


# ---------- 多轮试一试（Phase B 新增）----------


class TryTurnHistoryItem(BaseModel):
    speaker: str = Field(..., description="'persona' / 'sales'")
    content: str = ""


class TryNextReq(BaseModel):
    history: list[TryTurnHistoryItem] = Field(default_factory=list, description="此前对话历史（按时序）")
    customer_next: str = Field(..., description="客户最新一轮发言，将作为最后一条 persona turn")
    topic: str = "华为 MatePad 12X 学习平板推荐"
    product_kb_id: Optional[int] = None
    enterprise_kb_id: Optional[int] = None
    persona_name: str = "试一试·客户"
    persona_age: Optional[int] = 30
    max_rounds: int = Field(12, ge=2, le=50)
    stage: str = Field("中段·需求挖掘")


# ---------- 记忆与学习 ----------


class KbCard(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    kb_type: str
    file_count: int = 0
    chunk_count: int = 0
    last_uploaded_at: Optional[str] = None
    is_default_bound: bool = False


class RecentUpload(BaseModel):
    kb_id: int
    kb_name: Optional[str] = None
    kb_type: str
    filename: str
    status: str
    chunk_count: int = 0
    created_at: str


class MemoryResp(BaseModel):
    product_kb: KbCard
    enterprise_kb: KbCard
    sales_cases: dict[str, Any]  # {total, by_source}
    recent_uploads: list[RecentUpload]
    bound_defaults: dict[str, Any]  # default_session_params 中的 KB id 等


# ---------- 生效配置预览（Tab 2 用）----------


class ProviderSnapshot(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    is_default: bool = False
    source: str  # 'db_default' / 'env' / 'override'


class EffectiveConfigResp(BaseModel):
    """销冠当前真实生效的 LLM 配置（全局默认 + 销冠覆盖叠加后）。"""
    global_default: ProviderSnapshot
    override_provider: Optional[ProviderSnapshot] = None
    effective_model: str
    effective_temperature: float
    effective_max_tokens: Optional[int] = None
    has_any_override: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_profile_resp(p: dict[str, Any]) -> AgentProfile:
    return AgentProfile(
        id=int(p.get("id") or 0),
        name=str(p.get("name") or ""),
        role_description=p.get("role_description") or "",
        system_prompt=p.get("system_prompt") or "",
        opening_lines=list(p.get("opening_lines") or []),
        default_session_params=dict(p.get("default_session_params") or {}),
        model_override=dict(p.get("model_override") or {}),
        extra=dict(p.get("extra") or {}),
        created_at=p.get("created_at"),
        updated_at=p.get("updated_at"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/sales", response_model=AgentProfile)
def get_sales_profile() -> AgentProfile:
    from src.storage.db import get_agent_profile, get_connection
    conn = get_connection()
    try:
        p = get_agent_profile(conn, _PROFILE_NAME)
    finally:
        conn.close()
    if p is None:
        raise HTTPException(status_code=500, detail="无法初始化 sales agent_profile")
    return _to_profile_resp(p)


@router.patch("/sales", response_model=AgentProfile)
def patch_sales_profile(payload: AgentProfileUpdate) -> AgentProfile:
    from src.storage.db import get_connection, update_agent_profile

    fields = {
        k: v for k, v in payload.model_dump().items()
        if v is not None and k != "version_comment"
    }
    conn = get_connection()
    try:
        new_p = update_agent_profile(
            conn,
            _PROFILE_NAME,
            bump_version=True,
            version_comment=payload.version_comment,
            **fields,
        )
    finally:
        conn.close()
    return _to_profile_resp(new_p)


@router.get("/sales/versions", response_model=VersionsResp)
def list_sales_versions(limit: int = 50) -> VersionsResp:
    from src.storage.db import get_connection, list_agent_profile_versions
    conn = get_connection()
    try:
        rows = list_agent_profile_versions(conn, _PROFILE_NAME, limit=limit)
    finally:
        conn.close()
    items = [
        VersionItem(
            id=int(r["id"]),
            version_no=int(r["version_no"]),
            comment=r.get("comment"),
            created_at=r["created_at"],
            snapshot=r.get("snapshot") or {},
        )
        for r in rows
    ]
    return VersionsResp(name=_PROFILE_NAME, versions=items, total=len(items))


@router.post("/sales/restore", response_model=AgentProfile)
def restore_sales_version(req: RestoreReq) -> AgentProfile:
    from src.storage.db import get_connection, restore_agent_profile_version
    conn = get_connection()
    try:
        new_p = restore_agent_profile_version(conn, _PROFILE_NAME, req.version_no)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()
    return _to_profile_resp(new_p)


@router.post("/sales/try", response_model=TryResp)
def try_sales_turn(req: TryReq) -> TryResp:
    """极简一次性调销冠 Agent，方便在 UI「试一试」 tab 即时验证 prompt 改动。

    构造一个最小可用 DialogueState（包含客户开场白 + 可选 KB 绑定），
    调 ``generate_sales_turn``，把 turn.metadata 中的 tool_calls / strategy 返回前端。
    """
    from src.agents import generate_sales_turn
    from src.schema import DialogueState, PersonaProfile, SessionMemory, Turn

    try:
        persona = PersonaProfile(
            id="try_persona",
            name=req.persona_name,
            age=req.persona_age,
        )
        customer_turn = Turn(
            idx=0,
            speaker="persona",
            content=req.customer_opening,
            metadata={},
            created_at="",
        )
        state = DialogueState(
            session_id="agent_profile_try",
            topic=req.topic,
            product_text="",
            persona_profile=persona,
            round_idx=req.round_idx,
            max_rounds=req.max_rounds,
            current_stage=req.stage,
            recent_history=[customer_turn],
            session_memory=SessionMemory.empty(),
            product_kb_id=req.product_kb_id,
            enterprise_kb_id=req.enterprise_kb_id,
        )
        turn = generate_sales_turn(state)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent-profile/try 调用失败")
        return TryResp(ok=False, content="", error=f"{type(exc).__name__}: {exc}")

    meta = turn.metadata or {}
    # strategy 字段在 metadata 中是平铺的（SalesStrategy.model_dump），抽出已知 strategy keys
    strategy_keys = {
        "intent", "tone", "next_action", "evidence_focus",
        "confidence", "risk", "end_status", "summary_for_persona",
    }
    strategy = {k: v for k, v in meta.items() if k in strategy_keys}

    raw_calls = meta.get("tool_calls") or []
    calls = []
    for c in raw_calls:
        if not isinstance(c, dict):
            continue
        calls.append(TryRespToolCall(
            loop=int(c.get("loop", 0)),
            name=str(c.get("name", "?")),
            arguments=dict(c.get("arguments") or {}),
            result_preview=str(c.get("result_preview") or "")[:800],
            ok=bool(c.get("ok", True)),
        ))

    return TryResp(
        ok=True,
        content=turn.content or "",
        strategy=strategy,
        tool_mode=meta.get("tool_mode"),
        tool_calls=calls,
        used_product_kb=list(meta.get("used_product_kb") or []),
        used_enterprise_kb=list(meta.get("used_enterprise_kb") or []),
    )


@router.post("/sales/try_next", response_model=TryResp)
def try_sales_next_turn(req: TryNextReq) -> TryResp:
    """多轮调试：传入完整对话历史 + 客户最新发言，调销冠 Agent 给出下一轮。

    与 ``/sales/try`` 区别：本接口接收 ``history`` 数组（每项 speaker/content），
    构造 ``DialogueState.recent_history``，让销冠看到上下文做出更合理回复。
    """
    from src.agents import generate_sales_turn
    from src.schema import DialogueState, PersonaProfile, SessionMemory, Turn

    try:
        # 构造历史 + 客户新发言
        history_turns: list[Turn] = []
        sales_turn_count = 0
        for i, h in enumerate(req.history or []):
            speaker = "sales" if h.speaker == "sales" else "persona"
            if speaker == "sales":
                sales_turn_count += 1
            history_turns.append(Turn(
                idx=i,
                speaker=speaker,
                content=h.content or "",
                metadata={},
                created_at="",
            ))
        history_turns.append(Turn(
            idx=len(history_turns),
            speaker="persona",
            content=req.customer_next,
            metadata={},
            created_at="",
        ))
        # 只取最近 10 条进入 recent_history，避免上下文爆炸
        recent = history_turns[-10:]

        persona = PersonaProfile(
            id="try_persona",
            name=req.persona_name,
            age=req.persona_age,
        )
        # 销冠这轮编号 = 已发生的 sales turn 数 + 1
        round_idx = sales_turn_count + 1
        state = DialogueState(
            session_id="agent_profile_try_multi",
            topic=req.topic,
            product_text="",
            persona_profile=persona,
            round_idx=round_idx,
            max_rounds=req.max_rounds,
            current_stage=req.stage,
            recent_history=recent,
            full_history=history_turns,
            session_memory=SessionMemory.empty(),
            product_kb_id=req.product_kb_id,
            enterprise_kb_id=req.enterprise_kb_id,
        )
        turn = generate_sales_turn(state)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent-profile/try_next 调用失败")
        return TryResp(ok=False, content="", error=f"{type(exc).__name__}: {exc}")

    meta = turn.metadata or {}
    strategy_keys = {
        "intent", "tone", "next_action", "evidence_focus",
        "confidence", "risk", "end_status", "summary_for_persona",
    }
    strategy = {k: v for k, v in meta.items() if k in strategy_keys}

    raw_calls = meta.get("tool_calls") or []
    calls = []
    for c in raw_calls:
        if not isinstance(c, dict):
            continue
        calls.append(TryRespToolCall(
            loop=int(c.get("loop", 0)),
            name=str(c.get("name", "?")),
            arguments=dict(c.get("arguments") or {}),
            result_preview=str(c.get("result_preview") or "")[:800],
            ok=bool(c.get("ok", True)),
        ))

    return TryResp(
        ok=True,
        content=turn.content or "",
        strategy=strategy,
        tool_mode=meta.get("tool_mode"),
        tool_calls=calls,
        used_product_kb=list(meta.get("used_product_kb") or []),
        used_enterprise_kb=list(meta.get("used_enterprise_kb") or []),
    )


# ---------------------------------------------------------------------------
# 记忆与学习（Tab 4）
# ---------------------------------------------------------------------------


@router.get("/sales/memory", response_model=MemoryResp)
def get_sales_memory() -> MemoryResp:
    """聚合销冠"已学到的资产"：产品库 / 企业库 / 案例集 / 最近上传。"""
    from src.storage.db import (
        get_agent_profile,
        get_connection,
    )

    conn = get_connection()
    try:
        profile = get_agent_profile(conn, _PROFILE_NAME) or {}
        dsp = profile.get("default_session_params") or {}
        bound_product_id = dsp.get("product_kb_id")
        bound_enterprise_id = dsp.get("enterprise_kb_id")

        # 产品库：取首选（若 default_session_params 指定就用指定，否则取 kb_type='product' 中 file_count 最大者）
        product = _pick_kb(conn, bound_product_id, "product")
        enterprise = _pick_kb(conn, bound_enterprise_id, "enterprise")

        # 案例集统计
        rows = conn.execute(
            "SELECT source, COUNT(*) AS n FROM sales_cases GROUP BY source"
        ).fetchall()
        by_source = {r["source"]: int(r["n"]) for r in rows}
        total_cases = sum(by_source.values())

        # 最近 10 条上传
        recent_rows = conn.execute(
            """
            SELECT f.id, f.kb_id, f.filename, f.status, f.chunk_count, f.created_at,
                   k.name AS kb_name, k.kb_type AS kb_type
            FROM knowledge_files f
            LEFT JOIN knowledge_bases k ON k.id = f.kb_id
            ORDER BY f.created_at DESC
            LIMIT 10
            """
        ).fetchall()
        recent = [
            RecentUpload(
                kb_id=int(r["kb_id"]),
                kb_name=r["kb_name"],
                kb_type=r["kb_type"] or "?",
                filename=r["filename"] or "",
                status=r["status"] or "?",
                chunk_count=int(r["chunk_count"] or 0),
                created_at=r["created_at"],
            )
            for r in recent_rows
        ]
    finally:
        conn.close()

    return MemoryResp(
        product_kb=product,
        enterprise_kb=enterprise,
        sales_cases={"total": total_cases, "by_source": by_source},
        recent_uploads=recent,
        bound_defaults={
            "product_kb_id": bound_product_id,
            "enterprise_kb_id": bound_enterprise_id,
        },
    )


def _pick_kb(conn: Any, bound_id: Optional[int], kb_type: str) -> KbCard:
    """优先按 bound_id 取；没有则取该类型下 file_count 最大者；都没有就返回空卡片。"""
    row = None
    if bound_id:
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE id = ?", (int(bound_id),)
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE kb_type = ? "
            "ORDER BY file_count DESC, id ASC LIMIT 1",
            (kb_type,),
        ).fetchone()
    if row is None:
        return KbCard(kb_type=kb_type, is_default_bound=False)

    last_uploaded = conn.execute(
        """
        SELECT MAX(created_at) AS last_ts FROM knowledge_files WHERE kb_id = ?
        """,
        (row["id"],),
    ).fetchone()
    is_bound = bool(bound_id) and int(row["id"]) == int(bound_id)

    return KbCard(
        id=int(row["id"]),
        name=row["name"],
        kb_type=row["kb_type"],
        file_count=int(row["file_count"] or 0),
        chunk_count=int(row["chunk_count"] or 0),
        last_uploaded_at=(last_uploaded["last_ts"] if last_uploaded else None),
        is_default_bound=is_bound,
    )


# ---------------------------------------------------------------------------
# Tab 2 模型与采样：生效配置预览
# ---------------------------------------------------------------------------


@router.get("/sales/effective_config", response_model=EffectiveConfigResp)
def get_sales_effective_config() -> EffectiveConfigResp:
    """返回销冠当前真实生效的 LLM 配置（全局默认 ⊕ 销冠 model_override）。

    用于 Tab 2 顶部"当前生效"卡片，让用户一眼看清覆盖关系。
    """
    from src.config import load_settings
    from src.storage.db import (
        get_agent_profile,
        get_connection,
        get_default_provider,
        get_provider_by_id,
    )

    conn = get_connection()
    try:
        profile = get_agent_profile(conn, _PROFILE_NAME) or {}
        mo = profile.get("model_override") or {}

        # 1) global default
        default_row = get_default_provider(conn)
        if default_row:
            global_default = ProviderSnapshot(
                id=int(default_row["id"]),
                name=default_row.get("name"),
                provider_type=default_row.get("provider_type"),
                base_url=default_row.get("base_url"),
                model_name=default_row.get("model_name"),
                temperature=float(default_row.get("temperature", 0.7)),
                is_default=True,
                source="db_default",
            )
        else:
            env_s = load_settings()
            global_default = ProviderSnapshot(
                base_url=env_s.base_url,
                model_name=env_s.model_name,
                temperature=env_s.temperature,
                is_default=False,
                source="env",
            )

        # 2) override provider（如指定）
        override_provider: Optional[ProviderSnapshot] = None
        ov_pid = mo.get("provider_id")
        if ov_pid:
            try:
                row = get_provider_by_id(conn, int(ov_pid))
            except Exception:
                row = None
            if row:
                override_provider = ProviderSnapshot(
                    id=int(row["id"]),
                    name=row.get("name"),
                    provider_type=row.get("provider_type"),
                    base_url=row.get("base_url"),
                    model_name=row.get("model_name"),
                    temperature=float(row.get("temperature", 0.7)),
                    is_default=bool(row.get("is_default")),
                    source="override",
                )
    finally:
        conn.close()

    # 3) 叠加生效值
    base = override_provider or global_default
    eff_model = (mo.get("model") or base.model_name or "?")
    if mo.get("temperature") not in (None, ""):
        eff_temp = float(mo["temperature"])
    else:
        eff_temp = float(base.temperature or 0.7)
    eff_max_tokens = int(mo["max_tokens"]) if mo.get("max_tokens") else None

    has_any = bool(
        mo.get("provider_id")
        or mo.get("model")
        or mo.get("temperature") not in (None, "")
        or mo.get("max_tokens")
    )

    return EffectiveConfigResp(
        global_default=global_default,
        override_provider=override_provider,
        effective_model=eff_model,
        effective_temperature=eff_temp,
        effective_max_tokens=eff_max_tokens,
        has_any_override=has_any,
    )
