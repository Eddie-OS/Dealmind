"""Coach Agent：会后复盘模块。

会话结束后调用一次，对完整对话进行深度分析，
返回结构化的 CoachReview 对象。
"""

from __future__ import annotations

from collections import Counter

from src.agents import _format_history_for_prompt, load_prompt, render_prompt
from src.business_stages import load_stages, playbook_cn
from src.lang import lang_instruction
from src.llm import (
    LLMCallError,
    LLMJsonParseError,
    LLMOverride,
    call_llm_json,
    with_llm_override,
)
from src.safe_console import SafeConsole
from src.schema import CoachReview, DialogueState, SalesScore
from src.utils import safe_json_dumps


console = SafeConsole()


def _compute_playbook_stats(state: DialogueState) -> dict:
    """统计销冠在本场全程使用的 playbook_action（命中数 + 各阶段覆盖率）。

    返回结构（注入 coach_prompt）：
      {
        "total_sales_turns": 12,
        "actions_count": {"spin_problem": 3, "anchor_3a": 2, ...},
        "stage_coverage": {                  # 每个阶段：销冠用了哪些 actions / 漏了哪些
          "S1": {"used": ["warmup_greeting"], "missed": ["soft_hook", "space_giving"]},
          ...
        },
      }
    """
    sales_turns = [t for t in state.full_history if t.speaker == "sales"]
    counter: Counter[str] = Counter()
    by_stage: dict[str, set[str]] = {}
    for t in sales_turns:
        pa = (t.metadata or {}).get("playbook_action")
        sid = (t.metadata or {}).get("stage_id") or ""
        if pa:
            counter[pa] += 1
            by_stage.setdefault(sid, set()).add(pa)

    cfg = load_stages()
    stage_coverage: dict[str, dict] = {}
    for sid in cfg.all_stage_ids():
        allowed = set(cfg.get_allowed_actions(sid))
        used = by_stage.get(sid, set()) & allowed
        missed = allowed - used
        stage_coverage[sid] = {
            "used": sorted(used),
            "missed": sorted(missed),
        }

    return {
        "total_sales_turns": len(sales_turns),
        "actions_count": dict(counter),
        "stage_coverage": stage_coverage,
    }


def _format_playbook_stats(stats: dict) -> str:
    """playbook_stats → 可读 markdown 注入 coach_prompt。"""
    lines = [f"总销冠发言轮数：{stats['total_sales_turns']}"]
    if stats["actions_count"]:
        lines.append("\n各 playbook_action 命中次数：")
        for k, v in sorted(stats["actions_count"].items(), key=lambda x: -x[1]):
            lines.append(f"  · {k} ({playbook_cn(k)}) × {v}")
    else:
        lines.append("\n（销冠全程未输出任何 playbook_action — 严重违规）")

    lines.append("\n各阶段剧本覆盖率：")
    for sid, cov in stats["stage_coverage"].items():
        used_str = ", ".join(cov["used"]) or "（无）"
        missed_str = ", ".join(cov["missed"]) or "（无）"
        lines.append(f"  · {sid}  已用 [{used_str}]  漏掉 [{missed_str}]")
    return "\n".join(lines)


def _compute_stage_weight_balance(state: DialogueState) -> dict:
    """统计销冠在各 stage 的实际发言占比 vs YAML 期望权重的偏离。

    返回：
      {
        "S1": {"actual": 0.20, "expected": 0.15, "delta": +0.05, "outside_tolerance": False},
        ...
      }
    """
    cfg = load_stages()
    tol = cfg.weight_tolerance
    sales_turns = [t for t in state.full_history if t.speaker == "sales"]
    total = max(1, len(sales_turns))
    counts: dict[str, int] = {sid: 0 for sid in cfg.all_stage_ids()}
    for t in sales_turns:
        sid = (t.metadata or {}).get("stage_id")
        if sid in counts:
            counts[sid] += 1
    out: dict[str, dict] = {}
    for sid, cnt in counts.items():
        actual = cnt / total
        expected = cfg.stages[sid].weight if sid in cfg.stages else 0.0
        delta = actual - expected
        out[sid] = {
            "actual": round(actual, 3),
            "expected": expected,
            "delta": round(delta, 3),
            "outside_tolerance": abs(delta) > tol,
        }
    return out


def _format_weight_balance(balance: dict) -> str:
    lines = []
    for sid, d in balance.items():
        flag = "⚠️" if d["outside_tolerance"] else "✓"
        lines.append(
            f"  {flag} {sid}  实际 {d['actual']:.0%}  期望 {d['expected']:.0%}  "
            f"偏差 {d['delta']:+.0%}"
        )
    return "\n".join(lines) if lines else "（无销冠 stage 数据可统计）"


def _format_judge_score(state: DialogueState) -> str:
    fb = state.judge_feedback
    if not fb or not fb.sales_score:
        return "（暂无评分）"
    sc = fb.sales_score
    lines = [
        f"综合质量分: {fb.dialogue_quality_score}",
        f"  回应具体度: {sc.responsiveness}/10",
        f"  表达具体度: {sc.specificity}/10",
        f"  产品依据: {sc.evidence_usage}/10",
        f"  异议处理: {sc.objection_handling}/10",
        f"  成交推进: {sc.closing_progress}/10",
    ]
    if fb.reason:
        lines.append(f"Judge理由: {fb.reason}")
    return "\n".join(lines)


def _format_persona_summary(state: DialogueState) -> str:
    p = state.persona_profile
    return (
        f"姓名: {p.name}, 年龄: {p.age}, 职业: {p.occupation}, 预算: {p.budget}\n"
        f"性格: {p.personality}\n"
        f"痛点: {', '.join(p.pain_points)}\n"
        f"异议风格: {p.objection_style}\n"
        f"压力参数: {p.pressure_profile.summary()}"
    )


def run_coach(state: DialogueState) -> CoachReview:
    """会后调用一次，生成完整 CoachReview。

    解析失败时返回带部分字段的默认对象，不中断主流程。
    """
    template = load_prompt("coach_prompt")

    playbook_stats = _compute_playbook_stats(state)
    weight_balance = _compute_stage_weight_balance(state)

    # v0.2.1 真实性补丁：客户所在市场块注入
    from src.locales import render_client_market_block as _render_market
    persona = state.persona_profile
    client_market_block = _render_market(
        country_code=getattr(persona, "country_code", None),
        country_name=getattr(persona, "country_name", None),
        currency=getattr(persona, "currency", None),
        market_domains=list(getattr(persona, "market_domains", []) or []),
    )

    variables = {
        "topic": state.topic,
        "outcome": state.outcome,
        "total_rounds": str(state.round_idx),
        "final_stage": state.current_stage,
        "final_stage_id": state.current_stage_id,
        "persona_name": state.persona_profile.name,
        "persona_summary": _format_persona_summary(state),
        "judge_score": _format_judge_score(state),
        "full_history": _format_history_for_prompt(state.full_history),
        # business_stages v0.2 新增维度
        "playbook_stats": _format_playbook_stats(playbook_stats),
        "weight_balance": _format_weight_balance(weight_balance),
        # v0.2.1 真实性 / 一致性维度
        "client_market_block": client_market_block,
    }

    system_prompt = (
        "你是专业销售培训教练，擅长从对话记录中提炼可执行的销售经验。"
        "严格按照给定格式输出 JSON，不要任何多余文字。"
        + lang_instruction(state.language, role="coach")
    )
    user_prompt = render_prompt(template, variables)

    try:
        from src.perf_config import aux_llm_override

        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(system_prompt, user_prompt, temperature=0.3)
    except (LLMCallError, LLMJsonParseError) as exc:
        console.print(f"[yellow]Coach 调用失败，返回空复盘: {exc}[/yellow]")
        return _default_coach_review(state)

    try:
        review = CoachReview.model_validate(raw)
    except Exception as exc:
        console.print(f"[yellow]Coach 输出解析失败，返回空复盘: {exc}[/yellow]")
        return _default_coach_review(state)

    # 把统计数据回填到 review.extra 字段，方便前端可视化（CoachReview extra='allow'）
    try:
        review.__pydantic_extra__["playbook_stats"] = playbook_stats  # type: ignore[attr-defined]
        review.__pydantic_extra__["stage_weight_balance"] = weight_balance  # type: ignore[attr-defined]
    except Exception:
        pass

    console.print(
        f"  [bold]Coach 复盘完成[/bold]  "
        f"难度={review.difficulty_rating}/10  "
        f"经验条数={len(review.key_lessons)}  "
        f"话术模板={len(review.suggested_rebuttals)}"
    )
    return review


def _default_coach_review(state: DialogueState) -> CoachReview:
    return CoachReview(
        outcome_analysis=f"本次会话结果: {state.outcome}（解析失败，无详细分析）",
        what_worked=[],
        what_failed=[],
        persona_insight="",
        key_lessons=[],
        suggested_rebuttals=[],
        difficulty_rating=0,
        difficulty_reason="",
        reusable_tactics=[],
    )
