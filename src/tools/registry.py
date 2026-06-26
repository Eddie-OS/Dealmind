"""工具注册表 + ``@tool`` 装饰器 + OpenAI tools schema 导出。

每个工具一个文件、一个函数、一个 Pydantic input schema。注册时记录：
- name、description、category（"rag" / "web" / "mcp" / "custom"）
- input schema（Pydantic 模型 → JSON schema）
- runner（实际执行函数，签名为 ``runner(args_dict, ctx) -> Any``）

LLM 拿到的 OpenAI tools 是按 schema 自动生成的（不需要手写一遍 JSON）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """工具运行期上下文。

    Sales Agent 真实调用时由 ``agents.py`` 构造；"测试工具"按钮里允许全空。
    """

    product_kb_id: Optional[int] = None
    enterprise_kb_id: Optional[int] = None
    session_id: Optional[str] = None
    persona_id: Optional[int] = None

    # v0.2.1 真实性补丁：persona 的地区市场上下文。
    # web_search 工具会强制 include_domains=persona_market_domains，
    # search_*_kb 也可以按地区过滤（后续按需扩展）。
    # 任一为空表示该字段未设，工具自行决定 fallback（通常走全球兜底）。
    persona_country_code: Optional[str] = None        # "MY" / "PH" / ...
    persona_country_name: Optional[str] = None
    persona_currency: Optional[str] = None            # "MYR" / "PHP" / ...
    persona_market_domains: list[str] = field(default_factory=list)

    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RegistryEntry:
    name: str
    description: str
    category: str
    input_schema: type[BaseModel]
    runner: Callable[..., Any]

    def to_openai_tool(self) -> dict[str, Any]:
        """OpenAI Chat Completions tools 协议格式。"""
        schema = self.input_schema.model_json_schema()
        # Pydantic v2 schema 顶部已经是 {type:object, properties, required}
        # 但要清掉 $defs/title 等 OpenAI 不喜欢的冗余
        cleaned = {
            "type": "object",
            "properties": schema.get("properties", {}),
        }
        if "required" in schema:
            cleaned["required"] = schema["required"]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": cleaned,
            },
        }


# ---------------------------------------------------------------------------
# 全局注册表
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, RegistryEntry] = {}


def tool(
    *,
    name: str,
    description: str,
    schema: type[BaseModel],
    category: str = "custom",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰器：把一个函数注册成可被 Sales Agent 调用的工具。

    被装饰函数签名建议为 ``fn(args: SchemaModel, ctx: ToolContext) -> Any``。
    返回值会被 ``json.dumps`` 后塞给 LLM 作为 tool 消息内容，
    所以请返回 JSON-serializable 对象（dict / list / 基本类型）。
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _REGISTRY:
            logger.warning("tool '%s' 已注册，将被覆盖（来源：%s）", name, fn)
        _REGISTRY[name] = RegistryEntry(
            name=name,
            description=description,
            category=category,
            input_schema=schema,
            runner=fn,
        )
        return fn

    return deco


# ---------------------------------------------------------------------------
# 查询 / 调度
# ---------------------------------------------------------------------------


def list_all_tool_names() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_all_tools() -> list[RegistryEntry]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY.keys())]


def get_enabled_tools(enabled_names: list[str]) -> list[RegistryEntry]:
    """按启用列表过滤；未识别的 name 静默忽略。"""
    out: list[RegistryEntry] = []
    for n in enabled_names:
        if n in _REGISTRY:
            out.append(_REGISTRY[n])
        else:
            logger.warning("enabled_tools 引用了未知工具 '%s'，已忽略", n)
    return out


def get_tool_schemas(enabled_names: list[str]) -> list[dict[str, Any]]:
    """直接喂给 ``client.chat.completions.create(tools=...)`` 的列表。"""
    return [e.to_openai_tool() for e in get_enabled_tools(enabled_names)]


def run_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> Any:
    """执行工具，出错抛异常。给"测试工具"按钮用，方便看完整堆栈。"""
    if name not in _REGISTRY:
        raise KeyError(f"未注册的工具：{name}")
    entry = _REGISTRY[name]
    parsed = entry.input_schema.model_validate(args or {})
    return entry.runner(parsed, ctx)


def run_tool_safe(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """执行工具，永远不抛；出错返回 ``{"error": "..."}``。

    Sales Agent tool-use 循环里走这个版本，避免一个工具异常炸掉整轮对话。
    """
    try:
        result = run_tool(name, args or {}, ctx)
        # 强制 JSON 化前的"可序列化"探测
        try:
            json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            result = {"warning": "result not directly JSON-serializable", "repr": repr(result)[:500]}
        return {"ok": True, "data": result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool '%s' 执行失败", name)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
