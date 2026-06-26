"""Session Memory 更新器。

每隔 memory_interval 轮调用一次，从最近对话提取用户画像，
把 do_not_repeat / main_objections / budget_boundary 等关键信息
注入 state，供下一轮 Persona / Sales Agent 读取。
"""

from __future__ import annotations

from src.agents import _format_history_for_prompt, load_prompt, render_prompt
from src.lang import lang_instruction
from src.llm import LLMCallError, LLMJsonParseError, call_llm_json, with_llm_override
from src.perf_config import aux_llm_override
from src.safe_console import SafeConsole
from src.schema import DialogueState, SessionMemory
from src.utils import safe_json_dumps


console = SafeConsole()


def update_session_memory(state: DialogueState) -> SessionMemory:
    """调用模型更新当前会话画像记忆。

    解析失败时返回旧画像（不丢历史），而不是崩溃。
    """
    template = load_prompt("session_memory_prompt")

    old_mem = state.session_memory
    old_mem_text = (
        safe_json_dumps(old_mem.model_dump())
        if any([old_mem.current_need, old_mem.main_objections, old_mem.budget_boundary])
        else "（暂无旧画像，这是首次更新）"
    )

    variables = {
        "old_session_memory": old_mem_text,
        "recent_history": _format_history_for_prompt(state.recent_history),
    }

    system_prompt = (
        "你是销售对话的会话画像提取专家。"
        "严格按照给定格式输出 JSON，不要任何多余文字。"
        + lang_instruction(state.language, role="memory")
    )
    user_prompt = render_prompt(template, variables)

    try:
        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(system_prompt, user_prompt, temperature=0.2)
    except (LLMCallError, LLMJsonParseError) as exc:
        console.print(f"[yellow]Session Memory 更新失败，保留旧画像: {exc}[/yellow]")
        return old_mem

    try:
        new_mem = SessionMemory.model_validate(raw)
    except Exception as exc:
        console.print(f"[yellow]Session Memory 解析失败，保留旧画像: {exc}[/yellow]")
        return old_mem

    console.print(
        f"  [dim]画像更新 → 主要异议: {new_mem.main_objections}[/dim]\n"
        f"  [dim]do_not_repeat: {new_mem.do_not_repeat}[/dim]"
    )
    return new_mem
