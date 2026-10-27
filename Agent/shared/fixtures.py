"""给会话内 agent 做单步自检用的最小可用状态。

只服务于 `python 0X_xxx/run.py --selftest`：想单独验证"销冠这一轮到底
会说什么"时，不需要起一整场对练，构造一个两轮上下文的 DialogueState 就够。
不参与全量执行链路。
"""
from __future__ import annotations

from typing import Any


def demo_persona() -> Any:
    from src.schema import PersonaProfile, PressureProfile

    return PersonaProfile(
        id="selftest_customer",
        name="自检客户",
        age=26,
        occupation="产品经理",
        budget=4000,
        personality="谨慎、爱比价、说话直接",
        pain_points=["预算有限", "担心买了用不上", "在意售后"],
        objection_style="反复拿竞品价格施压",
        purchase_goal="花最少的钱买到够用的设备",
        pressure_profile=PressureProfile(
            price_sensitivity=0.8,
            trust_threshold=0.6,
            patience=0.5,
            competitor_awareness=0.7,
            decision_power=0.8,
            emotion_volatility=0.4,
            need_urgency=0.6,
            skepticism=0.7,
            bargaining_aggressiveness=0.8,
        ),
    )


def demo_state(*, round_idx: int = 2, topic: str = "平板销售模拟") -> Any:
    from src.schema import DialogueState, Turn

    history = [
        Turn(idx=0, speaker="sales", content="您好，看平板是吧？我先了解下您主要拿来做什么。"),
        Turn(idx=1, speaker="persona", content="主要是办公和看剧，但我看别家同配置便宜六百。"),
    ]
    state = DialogueState(
        session_id="selftest",
        topic=topic,
        product_text="（自检用占位产品资料）",
        persona_profile=demo_persona(),
        round_idx=round_idx,
        max_rounds=6,
        current_stage_id="S2",
        recent_history=history,
        full_history=list(history),
    )
    return state
