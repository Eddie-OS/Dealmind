"""Stage 14：销冠技能配置接口。

  GET    /api/agent-skills/tools      所有可用工具列表（含 schema、category、enabled 标志）
  GET    /api/agent-skills/config     当前配置
  PATCH  /api/agent-skills/config     更新配置（部分字段）
  POST   /api/agent-skills/test_tool  独立测试一个工具的调用结果
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.storage.db import (
    get_agent_skills_config,
    get_connection,
    update_agent_skills_config,
)
from src.tools.registry import (
    ToolContext,
    get_all_tools,
    run_tool_safe,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-skills", tags=["agent-skills"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ToolInfo(BaseModel):
    name: str
    description: str
    category: str
    parameters: dict[str, Any]
    enabled: bool


class ToolsListResp(BaseModel):
    tools: list[ToolInfo]
    total: int


class SkillsConfig(BaseModel):
    enabled_tools: list[str] = Field(default_factory=list)
    max_tool_loops: int = 3
    tool_top_k_default: int = 3
    web_search_provider: str = "tavily"
    web_search_api_key: str = ""
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    extra_config: dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[str] = None


class SkillsConfigUpdate(BaseModel):
    enabled_tools: Optional[list[str]] = None
    max_tool_loops: Optional[int] = None
    tool_top_k_default: Optional[int] = None
    web_search_provider: Optional[str] = None
    web_search_api_key: Optional[str] = None
    mcp_servers: Optional[list[dict[str, Any]]] = None
    extra_config: Optional[dict[str, Any]] = None


class TestToolReq(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    product_kb_id: Optional[int] = None
    enterprise_kb_id: Optional[int] = None


class TestToolResp(BaseModel):
    ok: bool
    name: str
    arguments: dict[str, Any]
    result: Any
    error: Optional[str] = None


class TestWebSearchReq(BaseModel):
    query: str = Field("华为 MatePad 12X 价格", description="测试查询")
    top_k: int = Field(3, ge=1, le=5)
    provider: Optional[str] = Field(
        None,
        description="不传则使用 agent_skills_config 当前配置；用于UI上『暂存未保存的key』时临时测试",
    )
    api_key: Optional[str] = Field(
        None,
        description="不传则使用 DB 中保存的 key",
    )


class TestWebSearchResp(BaseModel):
    ok: bool
    provider: str
    query: str
    error: Optional[str] = None
    result: Any = None


# ---------- MCP ----------


class McpServerCfg(BaseModel):
    name: str = Field(..., description="MCP server 别名，必须唯一")
    command: str = Field(..., description="可执行命令（绝对路径或在 PATH 中），如 `npx`、`python`")
    args: list[str] = Field(default_factory=list, description="命令行参数列表")
    env: dict[str, str] = Field(default_factory=dict, description="额外环境变量（合并到当前 env）")
    enabled: bool = True


class McpProbeResp(BaseModel):
    ok: bool
    name: str
    server_info: dict[str, Any] = Field(default_factory=dict)
    protocol_version: Optional[str] = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_count: int = 0
    error: Optional[str] = None


class McpCallToolReq(BaseModel):
    server_name: Optional[str] = Field(
        None,
        description="DB 中已保存 MCP server 的别名（与 server_cfg 二选一）",
    )
    server_cfg: Optional[McpServerCfg] = Field(
        None,
        description="临时 server 配置（用于未保存时测试）",
    )
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpCallToolResp(BaseModel):
    ok: bool
    is_error: bool = False
    content: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_cfg_dict() -> dict[str, Any]:
    conn = get_connection()
    try:
        return get_agent_skills_config(conn)
    finally:
        conn.close()


def _cfg_to_resp(cfg: dict[str, Any]) -> SkillsConfig:
    return SkillsConfig(
        enabled_tools=list(cfg.get("enabled_tools") or []),
        max_tool_loops=int(cfg.get("max_tool_loops") or 3),
        tool_top_k_default=int(cfg.get("tool_top_k_default") or 3),
        web_search_provider=str(cfg.get("web_search_provider") or "tavily"),
        web_search_api_key=str(cfg.get("web_search_api_key") or ""),
        mcp_servers=list(cfg.get("mcp_servers") or []),
        extra_config=dict(cfg.get("extra_config") or {}),
        updated_at=cfg.get("updated_at"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/tools", response_model=ToolsListResp)
def list_tools() -> ToolsListResp:
    """所有已注册工具 + 当前 enabled 状态。"""
    cfg = _load_cfg_dict()
    enabled = set(cfg.get("enabled_tools") or [])
    out: list[ToolInfo] = []
    for entry in get_all_tools():
        schema = entry.input_schema.model_json_schema()
        params = {
            "type": "object",
            "properties": schema.get("properties", {}),
        }
        if "required" in schema:
            params["required"] = schema["required"]
        out.append(ToolInfo(
            name=entry.name,
            description=entry.description,
            category=entry.category,
            parameters=params,
            enabled=entry.name in enabled,
        ))
    return ToolsListResp(tools=out, total=len(out))


@router.get("/config", response_model=SkillsConfig)
def get_config() -> SkillsConfig:
    return _cfg_to_resp(_load_cfg_dict())


@router.patch("/config", response_model=SkillsConfig)
def patch_config(payload: SkillsConfigUpdate) -> SkillsConfig:
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        return _cfg_to_resp(_load_cfg_dict())

    # 校验 enabled_tools 中 name 是否真存在（不存在也不拒，只是给警告）
    if "enabled_tools" in fields:
        all_names = {e.name for e in get_all_tools()}
        unknown = [n for n in fields["enabled_tools"] if n not in all_names]
        if unknown:
            logger.warning("配置启用了未知工具：%s（将持久化但运行时被忽略）", unknown)

    conn = get_connection()
    try:
        new_cfg = update_agent_skills_config(conn, **fields)
    finally:
        conn.close()
    return _cfg_to_resp(new_cfg)


@router.post("/test_web_search", response_model=TestWebSearchResp)
def test_web_search(req: TestWebSearchReq) -> TestWebSearchResp:
    """专门给 UI「测试联通」按钮用。

    与 ``/test_tool`` 区别：允许在请求里临时覆盖 provider / api_key，
    方便用户在保存之前先验证一下新填的 key 是否能用。
    """
    from src.tools.web_search import run_web_search

    cfg = _load_cfg_dict()
    provider = req.provider or cfg.get("web_search_provider") or "tavily"
    result = run_web_search(
        req.query,
        top_k=req.top_k,
        provider=req.provider,
        api_key=req.api_key,
    )
    if isinstance(result, dict) and result.get("error"):
        return TestWebSearchResp(
            ok=False,
            provider=str(provider),
            query=req.query,
            error=str(result.get("error")),
            result=None,
        )
    return TestWebSearchResp(
        ok=True,
        provider=str(result.get("provider") or provider),
        query=req.query,
        error=None,
        result=result,
    )


@router.post("/test_tool", response_model=TestToolResp)
def test_tool(req: TestToolReq) -> TestToolResp:
    """独立测试一个工具调用，UI 配置页"试一下"按钮。"""
    all_names = {e.name for e in get_all_tools()}
    if req.name not in all_names:
        raise HTTPException(status_code=404, detail=f"未注册的工具：{req.name}")

    ctx = ToolContext(
        product_kb_id=req.product_kb_id,
        enterprise_kb_id=req.enterprise_kb_id,
        session_id=None,
        persona_id=None,
        extra={"mode": "test"},
    )
    result = run_tool_safe(req.name, req.arguments, ctx)
    ok = bool(result.get("ok")) if isinstance(result, dict) else True
    return TestToolResp(
        ok=ok,
        name=req.name,
        arguments=req.arguments,
        result=result.get("data") if (ok and isinstance(result, dict)) else result,
        error=None if ok else (result.get("error") if isinstance(result, dict) else None),
    )


# ===========================================================================
# MCP（Phase C）
# ===========================================================================


def _find_mcp_server_cfg(name: str) -> Optional[dict[str, Any]]:
    """从 agent_skills_config.mcp_servers_json 里按 name 查 server 配置。"""
    cfg = _load_cfg_dict()
    for s in (cfg.get("mcp_servers") or []):
        if isinstance(s, dict) and s.get("name") == name:
            return s
    return None


@router.post("/mcp/probe", response_model=McpProbeResp)
def mcp_probe(cfg: McpServerCfg) -> McpProbeResp:
    """启动 MCP server 子进程，握手并列出工具。

    用于：
    1. 用户在 UI 配 server 但还没保存，点「探活并列工具」立即测；
    2. 也用于服务端校验配置是否能用。
    """
    from src.tools.mcp_client import probe_mcp_server

    res = probe_mcp_server({
        "command": cfg.command,
        "args": cfg.args,
        "env": cfg.env,
    })
    if not res.get("ok"):
        return McpProbeResp(
            ok=False,
            name=cfg.name,
            error=str(res.get("error") or "未知错误"),
        )
    return McpProbeResp(
        ok=True,
        name=cfg.name,
        server_info=res.get("server_info") or {},
        protocol_version=res.get("protocol_version"),
        tools=res.get("tools") or [],
        tool_count=int(res.get("tool_count") or 0),
    )


@router.post("/mcp/call_tool", response_model=McpCallToolResp)
def mcp_call_tool(req: McpCallToolReq) -> McpCallToolResp:
    """调用某个 MCP server 的一个 tool。

    server 来源（二选一）：
      1. 传 ``server_name`` → 从 DB 已保存配置里找
      2. 传 ``server_cfg``  → 用临时配置（未保存测试）
    """
    from src.tools.mcp_client import call_mcp_tool_sync

    if req.server_cfg is not None:
        cfg_dict = {
            "command": req.server_cfg.command,
            "args": req.server_cfg.args,
            "env": req.server_cfg.env,
        }
    elif req.server_name:
        saved = _find_mcp_server_cfg(req.server_name)
        if not saved:
            raise HTTPException(status_code=404, detail=f"未找到 MCP server：{req.server_name}")
        cfg_dict = {
            "command": saved.get("command"),
            "args": saved.get("args") or [],
            "env": saved.get("env") or {},
        }
    else:
        raise HTTPException(status_code=400, detail="必须传 server_name 或 server_cfg 之一")

    res = call_mcp_tool_sync(cfg_dict, req.tool_name, req.arguments)
    if not res.get("ok") and "error" in res:
        return McpCallToolResp(
            ok=False,
            is_error=True,
            content=[],
            error=str(res.get("error")),
        )
    return McpCallToolResp(
        ok=bool(res.get("ok", True)),
        is_error=bool(res.get("is_error", False)),
        content=res.get("content") or [],
        error=None,
    )
