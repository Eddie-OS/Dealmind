"""最小可用 MCP server（stdio），仅用于 Stage 14 Phase C 联调冒烟。

提供两个 tool：
- ``echo(text: str)`` 原样返回
- ``add(a: int, b: int)`` 返回 a+b 的字符串
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


app = Server("demo-smoke-server")


@app.list_tools()
async def _list_tools() -> list[Tool]:
    return [
        Tool(
            name="echo",
            description="原样返回 text。",
            inputSchema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        Tool(
            name="add",
            description="返回 a + b 的整数。",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
        ),
    ]


@app.call_tool()
async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "echo":
        return [TextContent(type="text", text=str(arguments.get("text", "")))]
    if name == "add":
        a = int(arguments.get("a", 0))
        b = int(arguments.get("b", 0))
        return [TextContent(type="text", text=str(a + b))]
    return [TextContent(type="text", text=f"unknown tool: {name}")]


async def _main() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
