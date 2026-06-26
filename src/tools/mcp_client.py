"""MCP（Model Context Protocol）stdio 客户端封装（Stage 14 Phase C）。

设计目标：
1. 给 ``routes_agent_skills`` 暴露两个 sync 函数：
   - ``probe_mcp_server(cfg)`` → 启动子进程、握手、list_tools、关闭，返回 server 元信息和工具列表。
   - ``call_mcp_tool_sync(cfg, tool_name, arguments)`` → 一次性子进程调用某个 MCP tool。
2. 不做长连接、不做异步事件循环复用——每次调用都新启子进程。
   优点：实现简单 / 进程隔离 / 不污染主进程的 asyncio 状态；
   代价：每次调用 + ~1s 启动开销，但 MCP 在销售场景里调用频次很低，可接受。
3. 整体 12s 超时（包括子进程启动 + 握手 + 工具调用），杜绝挂死。
4. 任何异常都被吞噬为 ``{"ok": False, "error": "..."}``，绝不向上抛。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_SEC = 12.0


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------


def _build_server_params(cfg: dict[str, Any]) -> StdioServerParameters:
    command = (cfg.get("command") or "").strip()
    if not command:
        raise ValueError("MCP server 必填 command")
    args = cfg.get("args") or []
    if isinstance(args, str):
        # 容错：UI 上可能传一整行命令字符串
        args = [a for a in args.split() if a]
    if not isinstance(args, list):
        raise ValueError("MCP args 必须是字符串列表")
    env_in = cfg.get("env") or {}
    if env_in and not isinstance(env_in, dict):
        raise ValueError("MCP env 必须是 dict")
    # 合并系统环境（很多 MCP server 依赖 PATH / TEMP 等），用户传的优先
    merged_env = dict(os.environ)
    for k, v in (env_in or {}).items():
        merged_env[str(k)] = str(v)

    return StdioServerParameters(
        command=command,
        args=[str(a) for a in args],
        env=merged_env,
    )


# ---------------------------------------------------------------------------
# 工具元信息序列化
# ---------------------------------------------------------------------------


def _tool_to_dict(t: Any) -> dict[str, Any]:
    """MCP Tool 对象 → 普通 dict（供前端展示 / 后续注册 registry 用）。"""
    schema = getattr(t, "inputSchema", None) or {}
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump()
    return {
        "name": getattr(t, "name", None),
        "description": (getattr(t, "description", None) or "").strip(),
        "input_schema": schema if isinstance(schema, dict) else {},
    }


def _content_to_dict(c: Any) -> dict[str, Any]:
    """MCP tool 返回 content 项 → dict。"""
    if hasattr(c, "model_dump"):
        d = c.model_dump()
        # 统一加 type 字段
        if "type" not in d:
            d["type"] = type(c).__name__.lower().replace("content", "")
        return d
    return {"type": "raw", "value": str(c)[:2000]}


# ---------------------------------------------------------------------------
# 内部 async 实现
# ---------------------------------------------------------------------------


async def _async_probe(cfg: dict[str, Any], timeout: float) -> dict[str, Any]:
    params = _build_server_params(cfg)

    async def _do() -> dict[str, Any]:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init_resp = await session.initialize()
                tools_resp = await session.list_tools()
                tools = [_tool_to_dict(t) for t in (tools_resp.tools or [])]

                server_info = {}
                si = getattr(init_resp, "serverInfo", None) or getattr(init_resp, "server_info", None)
                if si is not None:
                    if hasattr(si, "model_dump"):
                        server_info = si.model_dump()
                    elif isinstance(si, dict):
                        server_info = si
                proto = getattr(init_resp, "protocolVersion", None) or getattr(init_resp, "protocol_version", None)
                return {
                    "ok": True,
                    "server_info": server_info,
                    "protocol_version": str(proto) if proto else None,
                    "tools": tools,
                    "tool_count": len(tools),
                }

    return await asyncio.wait_for(_do(), timeout=timeout)


async def _async_call_tool(
    cfg: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    params = _build_server_params(cfg)

    async def _do() -> dict[str, Any]:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                contents = [_content_to_dict(c) for c in (result.content or [])]
                is_error = bool(getattr(result, "isError", False))
                return {
                    "ok": not is_error,
                    "is_error": is_error,
                    "content": contents,
                }

    return await asyncio.wait_for(_do(), timeout=timeout)


# ---------------------------------------------------------------------------
# sync 包装：在专用 daemon 线程里跑 asyncio.run，避免污染调用方 loop
# ---------------------------------------------------------------------------


def _run_in_thread(coro_factory, timeout: float) -> dict[str, Any]:
    """把 async 任务放到独立线程的 asyncio.run 里跑，主线程 join 等待。

    Windows + Python 3.11 上 stdio_client 内部用 subprocess，
    在主线程混用 asyncio 容易撞到 'Selector...' 异常，所以隔离到线程更稳。
    """
    result_box: dict[str, Any] = {}

    def runner() -> None:
        try:
            result_box["data"] = asyncio.run(coro_factory())
        except asyncio.TimeoutError:
            result_box["err"] = f"MCP 调用超时（{timeout}s）"
        except Exception as exc:  # noqa: BLE001
            logger.exception("MCP 子线程异常")
            result_box["err"] = f"{type(exc).__name__}: {exc}"

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=timeout + 4.0)  # 给线程多一点缓冲

    if t.is_alive():
        return {"ok": False, "error": f"MCP 子进程长时间无响应（>{timeout + 4}s）"}
    if "err" in result_box:
        return {"ok": False, "error": result_box["err"]}
    return result_box.get("data") or {"ok": False, "error": "MCP 无返回"}


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def probe_mcp_server(
    cfg: dict[str, Any],
    timeout: Optional[float] = None,
) -> dict[str, Any]:
    """启动 MCP server 子进程 → initialize → list_tools → 关闭。

    Returns:
        ``{ok, server_info, protocol_version, tools, tool_count}`` 或
        ``{ok: False, error: "..."}``。
    """
    to = float(timeout or _DEFAULT_TIMEOUT_SEC)
    try:
        return _run_in_thread(lambda: _async_probe(cfg, to), to)
    except Exception as exc:  # noqa: BLE001
        logger.exception("probe_mcp_server 顶层异常")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def call_mcp_tool_sync(
    cfg: dict[str, Any],
    tool_name: str,
    arguments: Optional[dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> dict[str, Any]:
    """启动 MCP server 子进程 → initialize → call_tool → 关闭。"""
    if not tool_name:
        return {"ok": False, "error": "tool_name 不能为空"}
    to = float(timeout or _DEFAULT_TIMEOUT_SEC)
    args = arguments or {}
    try:
        return _run_in_thread(
            lambda: _async_call_tool(cfg, tool_name, args, to),
            to,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("call_mcp_tool_sync 顶层异常")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
