"""v0.3 验证：渲染一遍 sales_prompt，确认 v10.1/10.2 阶段铁律 section 注入。"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents import (
    _build_product_fact_card_block,
    _format_avoid_repeating,
    _format_hits_for_prompt,
    _format_history_for_prompt,
    _format_judge_instruction,
    _format_session_memory,
    _infer_sales_context,
    _phase_pack,
    _stage_pack,
    _tool_status_summary,
    lang_instruction,
    load_prompt,
    render_prompt,
)
from src.schema import DialogueState, JudgeFeedback, SessionMemory

from scripts.smoke_judge_prompt_render import _persona


def main() -> int:
    state = DialogueState(
        session_id="render-test",
        topic="华为零售店：客户咨询 Pura 70 的拍照效果",
        product_text="",
        persona_profile=_persona(),
        round_idx=12,
        max_rounds=20,
        current_stage="方案匹配与价值锚定",
        current_stage_id="S3",
        outcome="",
        session_memory=SessionMemory.empty(),
        judge_feedback=JudgeFeedback.empty(),
        who_speaks_first="sales",
        opening_line="",
        max_rounds_floor=1,
        product_kb_id=None,
        enterprise_kb_id=None,
        language="zh",
    )
    sp = _stage_pack(state)
    phase = _phase_pack(state, "sales")
    template = load_prompt("sales_prompt")

    variables = {
        "topic": state.topic,
        "sales_context": _infer_sales_context(state.topic),
        "tool_status": _tool_status_summary(tools_enabled=None),
        "stage": "方案匹配与价值锚定",
        "round_idx": 12,
        "max_rounds": 20,
        "rounds_left": 8,
        "product_hits": _format_hits_for_prompt([], empty_text="(test empty)"),
        "enterprise_hits": _format_hits_for_prompt([], empty_text="(test empty)"),
        "session_memory": _format_session_memory(state),
        "sales_instruction": _format_judge_instruction(state, "sales"),
        "avoid_repeating": _format_avoid_repeating(state),
        "recent_history": _format_history_for_prompt(state.recent_history),
        "language_directive": lang_instruction(state.language, role="sales"),
        "product_fact_card_block": _build_product_fact_card_block(state),
        **phase,
        **sp,
    }
    rendered = render_prompt(template, variables)

    out = Path("logs/v03_sales_prompt_rendered.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")

    must = [
        "🎯 当前阶段铁律",
        "Required Trigger",
        "ideal 轮次窗口",
        "Gate Condition",
        "你的执行逻辑",
        "你的行为约束",
        "S3 · 方案匹配与价值锚定",
    ]
    missing = [k for k in must if k not in rendered]
    print(f"sales_prompt 渲染长度: {len(rendered)} chars → 写入 {out}")
    print(f"缺失关键字: {missing if missing else '无（全部命中 ✅）'}")

    idx = rendered.find("🎯 当前阶段铁律")
    if idx >= 0:
        print("\n----- v10.1/10.2 阶段铁律 section -----")
        print(rendered[idx : idx + 1100])
        print("----- 片段结束 -----\n")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
