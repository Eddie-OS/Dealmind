"""v0.3 验证：直接复用 judge_dialogue 的 variables 构造逻辑，
渲染一遍 judge_prompt，确认 v10.1/10.2 的几大 section 都成功注入。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents import (
    _format_history_for_prompt,
    _format_session_memory,
    _infer_stage_id,
    load_prompt,
    render_prompt,
)
from src.business_stages import get_stage, render_all_stages_for_judge, stage_cn_name
from src.judge import (
    _format_fact_card_for_judge,
    _format_persona_for_judge,
    _format_recent_tool_hits,
    _recent_playbook_usage,
)
from src.locales import render_client_market_block
from src.schema import (
    DialogueState,
    JudgeFeedback,
    PersonaProfile,
    PressureProfile,
    SessionMemory,
)
from src.stage_quota import current_stage_phase, render_quota_table


def _persona() -> PersonaProfile:
    pp = {
        f: 0.5 for f in (
            "price_sensitivity", "trust_threshold", "patience",
            "competitor_awareness", "decision_power", "emotion_volatility",
            "need_urgency", "skepticism", "bargaining_aggressiveness",
        )
    }
    return PersonaProfile(
        id="render-test",
        name="测试客户",
        occupation="自由职业",
        budget="3000-5000 MYR",
        personality="务实",
        pain_points=["拍照", "续航"],
        objection_style="直来直去",
        pressure_profile=PressureProfile(**pp),
        country_code="MY",
        country_name="Malaysia",
        currency="MYR",
        market_domains=["consumer.huawei.com/my"],
    )


def main() -> int:
    state = DialogueState(
        session_id="render-test",
        topic="华为零售店：客户咨询 Pura 70 的拍照效果",
        product_text="",
        persona_profile=_persona(),
        round_idx=12,            # 故意放在 S3 窗口中段
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

    # 复刻 src/judge.py 里 variables 的构造（剪掉 LLM 调用）
    current_sid = _infer_stage_id(state)
    persona = state.persona_profile
    cmb = render_client_market_block(
        country_code=persona.country_code,
        country_name=persona.country_name,
        currency=persona.currency,
        market_domains=list(persona.market_domains),
    )

    stage_quota_table = render_quota_table(
        max_rounds=state.max_rounds,
        current_stage_id=current_sid,
        round_idx=state.round_idx,
    )
    phase_info = current_stage_phase(
        round_idx=state.round_idx,
        current_stage_id=current_sid,
        max_rounds=state.max_rounds,
    )
    cur_spec = get_stage(current_sid)
    current_required_trigger = (cur_spec.required_trigger if cur_spec else "") or "（未定义）"
    current_gate_condition = (cur_spec.gate_condition if cur_spec else "") or "（未定义）"
    over_budget = int(phase_info.get("over_budget_rounds", 0) or 0)
    ideal_window_str = phase_info.get("ideal_window_str", "—")
    stage_budget_status = (
        f"✅ 在 ideal 窗口内（剩余 {phase_info.get('rounds_left_in_stage', 0)} 轮）"
        if phase_info.get("in_window")
        else f"⚠️ 已超 ideal 窗口 **{over_budget}** 轮"
    )

    variables = {
        "topic": state.topic,
        "stage": state.current_stage,
        "current_stage_id": current_sid,
        "current_stage_cn": stage_cn_name(current_sid),
        "round_idx": str(state.round_idx),
        "max_rounds": str(state.max_rounds),
        "persona_profile": _format_persona_for_judge(state),
        "session_memory": _format_session_memory(state),
        "recent_history": _format_history_for_prompt(state.recent_history),
        "all_stages_overview": render_all_stages_for_judge(),
        "recent_playbook_usage": _recent_playbook_usage(state, lookback=5),
        "client_market_block": cmb,
        "product_fact_card_block": _format_fact_card_for_judge(state),
        "recent_tool_hits_summary": _format_recent_tool_hits(state, lookback=3),
        "stage_quota_table": stage_quota_table,
        "current_required_trigger": current_required_trigger,
        "current_gate_condition": current_gate_condition,
        "stage_budget_status": stage_budget_status,
        "current_stage_over_budget_rounds": str(over_budget),
        "current_stage_ideal_window": ideal_window_str,
    }
    template = load_prompt("judge_prompt")
    rendered = render_prompt(template, variables)

    out = Path("logs/v03_judge_prompt_rendered.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(f"已渲染 → {out}  ({len(rendered)} chars)")

    must_have = [
        "⚖️ v10.1 阶段推进硬规则",
        "阶段轮次配额表",
        "S3 | 方案匹配与价值锚定",
        "理想轮次窗口",
        "导购员核心驱动动作（Required Trigger）",
        "消费者阶段流转大闸（Gate Condition）",
        "动作大闸强制覆盖",
        "ideal 窗口内（剩余",  # round=12 在 S3 窗口 10-17 里
        "🔬 销冠事实可信度审查",
        "📍 客户所在市场",
    ]
    missing = [k for k in must_have if k not in rendered]
    if missing:
        print(f"❌ 缺以下 section / 关键字: {missing}")
        return 1

    # 看一眼 quota 表那一段
    idx_a = rendered.find("⚖️ v10.1 阶段推进硬规则")
    idx_b = rendered.find("📍 客户所在市场")
    if idx_a > 0 and idx_b > idx_a:
        print("\n----- v10.1 section 片段（前 1500 字符）-----")
        print(rendered[idx_a : idx_a + 1500])
        print("----- 片段结束 -----\n")

    print("✅ Judge prompt 包含所有 v10.1/10.2/v0.2.x 必备 section")
    return 0


if __name__ == "__main__":
    sys.exit(main())
