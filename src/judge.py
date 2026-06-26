"""Judge Agent：会中裁判与对话导演。

每隔 judge_interval 轮调用一次，评估对话质量、控制阶段推进、
防止假成交/重复/跑题，并向 Persona 和 Sales 下达下一轮行为指令。

business_stages v0.2：
- Judge 拿到 5 阶段全图（render_all_stages_for_judge）
- 输出的 next_stage 直接使用 S1-S5 id；session 主循环按 is_valid_transition 校验
- 允许 S3→S2 / S4→S3 两条倒退边
"""

from __future__ import annotations

from src.agents import (
    _format_history_for_prompt,
    _format_session_memory,
    _infer_stage_id,
    load_prompt,
    render_prompt,
)
from src.safe_console import SafeConsole
from src.business_stages import (
    is_valid_transition,
    render_all_stages_for_judge,
    stage_cn_name,
)
from src.lang import lang_instruction
from src.llm import (
    LLMCallError,
    LLMJsonParseError,
    LLMOverride,
    call_llm_json,
    with_llm_override,
)
from src.schema import DialogueState, JudgeFeedback, SalesScore, StageTransition
from src.utils import safe_json_dumps


console = SafeConsole()


# 销冠 strategy.playbook_action 命中频次摘要：给 Judge 看"销冠最近 5 轮用了哪些剧本动作"
def _recent_playbook_usage(state: DialogueState, lookback: int = 5) -> str:
    sales_turns = [t for t in state.full_history if t.speaker == "sales"][-lookback:]
    if not sales_turns:
        return "（暂无销冠发言）"
    lines = []
    for t in sales_turns:
        pa = (t.metadata or {}).get("playbook_action") or "-"
        sid = (t.metadata or {}).get("stage_id") or "-"
        upc = (t.metadata or {}).get("used_product_context")
        upc_str = "✓" if upc else "✗"
        lines.append(f"  · round {t.idx} [stage={sid}] playbook={pa} used_product={upc_str}")
    return "\n".join(lines)


def _format_fact_card_for_judge(state: DialogueState) -> str:
    """把 state.product_fact_card 渲染给 Judge 看。无卡 → 提示 Judge 按严格模式审。"""
    card = getattr(state, "product_fact_card", None)
    if card is None:
        return (
            "**产品事实卡：未生成**   _可信度：UNCERTAIN_\n"
            "⚠️ 本场无可信产品事实基准；所有销冠提到的具体数字 / 参数你应当默认 = 未证实。"
        )
    return getattr(card, "render_block", "") or f"**产品事实卡：{card.product_name}**"


def _format_recent_tool_hits(state: DialogueState, lookback: int = 3) -> str:
    """把销冠最近 lookback 轮调过的工具命中摘要给 Judge，用于事实可信度对照。"""
    sales_turns = [t for t in state.full_history if t.speaker == "sales"][-lookback:]
    if not sales_turns:
        return "（暂无销冠工具调用记录）"
    lines: list[str] = []
    for t in sales_turns:
        meta = t.metadata or {}
        tool_calls = meta.get("tool_calls") or []
        rag = meta.get("rag_hits") or {}
        prod_hits = rag.get("product") or []
        ent_hits = rag.get("enterprise") or []
        guard = meta.get("content_guard") or {}
        parts = [
            f"round {t.idx}：",
            f"产品KB命中={len(prod_hits)}",
            f"企业KB命中={len(ent_hits)}",
            f"工具调用={len(tool_calls)}",
        ]
        if guard.get("rewritten"):
            parts.append(f"content_guard改写={len(guard.get('warnings', []))}处")
        lines.append("  · " + " ".join(parts))
    return "\n".join(lines)


def _format_persona_for_judge(state: DialogueState) -> str:
    p = state.persona_profile
    return (
        f"姓名: {p.name}, 职业: {p.occupation}, 预算: {p.budget}\n"
        f"性格: {p.personality}\n"
        f"痛点: {', '.join(p.pain_points)}\n"
        f"异议风格: {p.objection_style}\n"
        f"压力参数: {p.pressure_profile.summary()}"
    )


def judge_dialogue(state: DialogueState) -> JudgeFeedback:
    """调用 Judge Agent 评估当前对话并输出结构化反馈。

    business_stages v0.2：
      - 把 5 阶段全图（render_all_stages_for_judge）注入 prompt
      - 把销冠最近 5 轮的 playbook_action 摘要注入 prompt
      - LLM 输出 ``current_stage_id`` / ``next_stage_id`` （S1-S5），裁判可以倒退
      - 服务端再用 ``is_valid_transition`` 兜底校验非法切换 → 自动回落到原地停留

    解析失败时返回"继续且不切换阶段"的安全默认，不中断会话。
    """
    template = load_prompt("judge_prompt")

    current_sid = _infer_stage_id(state)

    # v0.2.1 真实性补丁：把 persona 的 country/currency/market_domains 块注入 Judge prompt
    from src.locales import render_client_market_block as _render_market

    persona = state.persona_profile
    client_market_block = _render_market(
        country_code=getattr(persona, "country_code", None),
        country_name=getattr(persona, "country_name", None),
        currency=getattr(persona, "currency", None),
        market_domains=list(getattr(persona, "market_domains", []) or []),
    )

    # v0.2.2：把 product_fact_card 和本轮销冠工具命中摘要给 Judge
    product_fact_card_block = _format_fact_card_for_judge(state)
    recent_tool_hits_summary = _format_recent_tool_hits(state, lookback=3)

    # v0.3 (v10.1)：阶段配额表 + 当前阶段的 required_trigger / gate_condition
    from src.business_stages import get_stage  # noqa: PLC0415
    from src.stage_quota import current_stage_phase, render_quota_table  # noqa: PLC0415

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
        else f"⚠️ 已超 ideal 窗口 **{over_budget}** 轮（窗口 {ideal_window_str}）"
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
        "client_market_block": client_market_block,
        "product_fact_card_block": product_fact_card_block,
        "recent_tool_hits_summary": recent_tool_hits_summary,
        # v0.3 (v10.1)
        "stage_quota_table": stage_quota_table,
        "current_required_trigger": current_required_trigger,
        "current_gate_condition": current_gate_condition,
        "stage_budget_status": stage_budget_status,
        "current_stage_over_budget_rounds": str(over_budget),
        "current_stage_ideal_window": ideal_window_str,
    }

    system_prompt = (
        "你是销售模拟系统的会中裁判。"
        "严格按照给定格式输出 JSON，不要任何多余文字。"
        + lang_instruction(state.language, role="judge")
    )
    user_prompt = render_prompt(template, variables)

    old_feedback = state.judge_feedback

    try:
        from src.perf_config import aux_llm_override

        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(system_prompt, user_prompt, temperature=0.2)
    except (LLMCallError, LLMJsonParseError) as exc:
        console.print(f"[yellow]Judge 调用失败，保留旧反馈: {exc}[/yellow]")
        return old_feedback

    try:
        sales_score_raw = raw.get("sales_score", {})
        try:
            sales_score = SalesScore.model_validate(sales_score_raw)
        except Exception:
            sales_score = SalesScore()

        # business_stages v0.2：优先取 LLM 输出的 _id 字段；老 LLM 可能只给中文名 → fallback
        raw_current_sid = (raw.get("current_stage_id") or "").strip() or current_sid
        raw_next_sid = (raw.get("next_stage_id") or "").strip() or raw_current_sid

        # 服务端兜底：非法切换 → 强制原地停留
        machine_pass = bool(raw.get("machine_check_pass", True))
        llm_pass = bool(raw.get("llm_check_pass", True))
        fail_reasons = list(raw.get("gate_fail_reasons") or [])
        triggered_fail = raw.get("triggered_fail_signal") or None

        if not is_valid_transition(raw_current_sid, raw_next_sid):
            console.print(
                f"[yellow]Judge 输出非法切换 {raw_current_sid}→{raw_next_sid}，"
                f"已回落为原地停留[/yellow]"
            )
            raw_next_sid = raw_current_sid
            fail_reasons.append(f"非法切换 {raw_current_sid}→{raw_next_sid} 被服务端拦截")

        direction = (
            "advance" if _stage_order(raw_next_sid) > _stage_order(raw_current_sid)
            else "regress" if _stage_order(raw_next_sid) < _stage_order(raw_current_sid)
            else "stay"
        )
        stage_transition = StageTransition(
            from_stage=raw_current_sid,
            to_stage=raw_next_sid,
            direction=direction,
            machine_check_pass=machine_pass,
            llm_check_pass=llm_pass,
            fail_reasons=fail_reasons,
            triggered_fail_signal=triggered_fail,
        )

        feedback = JudgeFeedback(
            should_continue=raw.get("should_continue", True),
            # current_stage / next_stage 仍用中文名以保兼容；id 走 stage_transition
            current_stage=stage_cn_name(raw_current_sid),
            next_stage=stage_cn_name(raw_next_sid),
            dialogue_quality_score=float(raw.get("dialogue_quality_score", 0)),
            sales_score=sales_score,
            persona_instruction=raw.get("persona_instruction", ""),
            sales_instruction=raw.get("sales_instruction", ""),
            avoid_repeating=raw.get("avoid_repeating", []),
            end_status=raw.get("end_status", "CONTINUE"),
            reason=raw.get("reason", ""),
            stage_transition=stage_transition,
        )
    except Exception as exc:
        console.print(f"[yellow]Judge 输出结构解析失败，保留旧反馈: {exc}[/yellow]")
        return old_feedback

    arrow = "→" if feedback.stage_transition and feedback.stage_transition.direction == "advance" \
            else "↩" if feedback.stage_transition and feedback.stage_transition.direction == "regress" \
            else "·"
    console.print(
        f"  [bold]Judge[/bold] → "
        f"质量分=[cyan]{feedback.dialogue_quality_score}[/cyan]  "
        f"end_status=[cyan]{feedback.end_status}[/cyan]  "
        f"stage=[cyan]{feedback.stage_transition.from_stage if feedback.stage_transition else '-'}"
        f" {arrow} {feedback.stage_transition.to_stage if feedback.stage_transition else '-'}[/cyan]"
    )
    if feedback.reason:
        console.print(f"  [dim]理由: {feedback.reason}[/dim]")
    if feedback.avoid_repeating:
        console.print(f"  [dim]避免重复: {feedback.avoid_repeating}[/dim]")
    if feedback.stage_transition and feedback.stage_transition.fail_reasons:
        console.print(f"  [dim]gate fail: {feedback.stage_transition.fail_reasons}[/dim]")

    return feedback


def _stage_order(sid: str) -> int:
    """S1/S2/.../S5 → 1-5；未识别返回 -1。供方向判断使用。"""
    if not sid or len(sid) < 2 or sid[0] != "S":
        return -1
    try:
        return int(sid[1:])
    except ValueError:
        return -1
