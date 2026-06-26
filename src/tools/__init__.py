"""Stage 14: 销冠 Agent 的可插拔工具系统（function-calling 风格）。

模块组织：
- ``registry``：``@tool`` 装饰器、工具注册表、OpenAI tools schema 导出、
  统一调度入口 ``run_tool()`` / ``run_tool_safe()``。
- ``rag_search``：3 个内置 RAG 工具（产品库 / 企业库 / 销售案例）。
- ``web_search``、``mcp_client``：留给下一轮（Phase B / C）。

设计原则：
1. 工具实现纯函数 + Pydantic schema，远端 LLM 通过 OpenAI tools 协议调用；
2. 任何工具运行异常都被 ``run_tool_safe`` 捕获，转成 ``{"error": str}`` 返回，
   绝不让一个工具挂掉打断整段 Sales Agent 对话；
3. 工具只从 ``RegistryEntry.metadata`` 读所需的轻量上下文（kb_id 等），
   不直接访问 DialogueState，便于在配置页"测试工具"按钮里独立调用。
"""

from src.tools.registry import (  # noqa: F401
    RegistryEntry,
    ToolContext,
    get_all_tools,
    get_enabled_tools,
    get_tool_schemas,
    list_all_tool_names,
    run_tool,
    run_tool_safe,
    tool,
)

# 触发副作用：装饰器在 import 时把工具注册进 registry
from src.tools import rag_search  # noqa: F401,E402
from src.tools import web_search  # noqa: F401,E402
from src.tools import sales_ops  # noqa: F401,E402  # 成交执行工具（报价/库存/优惠/对比）
