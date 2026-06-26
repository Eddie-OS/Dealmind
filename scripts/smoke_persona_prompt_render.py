"""v0.3 验证：渲染一遍 persona_prompt，确认 v10.2 阶段铁律 section 注入。"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents import (
    _build_structured_persona_text,
    _format_history_for_prompt,
    _format_judge_instruction,
    _format_session_memory,
    _phase_pack,
    _stage_pack,
    lang_instruction,
    load_prompt,
    render_prompt,
)
from src.schema import DialogueState, JudgeFeedback, SessionMemory

from scripts.smoke_judge_prompt_render import _persona


def main() -> int:
    persona = _persona()
    state = DialogueState(
        session_id="render-test",
        topic="华为零售店：客户咨询 Pura 70 的拍照效果",
        product_text="",
        persona_profile=persona,
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
    phase = _phase_pack(state, "persona")
    template = load_prompt("persona_prompt")
    variables = {
        "pressure_profile": persona.pressure_profile.summary(),
        "topic": state.topic,
        "stage": state.current_stage,
        "round_idx": state.round_idx,
        "max_rounds": state.max_rounds,
        "persona_instruction": _format_judge_instruction(state, "persona"),
        "session_memory": _format_session_memory(state),
        "recent_history": _format_history_for_prompt(state.recent_history),
        "language_directive": lang_instruction(state.language, role="persona"),
        "persona_profile": _build_structured_persona_text(persona),
        **phase,
        **sp,
    }
    rendered = render_prompt(template, variables)

    out = Path("logs/v03_persona_prompt_rendered.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")

    must = [
        "🎯 当前阶段的行为铁律",
        "ideal 轮次窗口",
        "你（消费者）的执行逻辑",
        "你（消费者）的行为约束",
        "S3 · 方案匹配与价值锚定",
        "严禁自发跳跃阶段",
        "Defense Level 实时回升",
    ]
    missing = [k for k in must if k not in rendered]
    sys.stderr.write(f"persona_prompt 长度: {len(rendered)} → {out}\n")
    sys.stderr.write(f"缺失: {missing if missing else '无 ✅'}\n")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
