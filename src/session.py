"""多轮对话主循环。

run_session() 是核心函数：
- 初始化 DialogueState
- 循环调用 Persona Agent → Sales Agent
- 按 judge_interval / memory_interval 触发 Judge 和 Session Memory
- 维护 recent_history（滑窗 10）和 full_history（全量）
- 支持 6 阶段销售路径
- 提前结束（Persona status / Judge end_status）+ 超时兜底
- 会话结束后调用 Coach 复盘 + 写出 4 个输出文件（阶段 7）
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from rich.panel import Panel
from rich.text import Text

from src.agents import (
    _infer_stage_id,
    generate_opening_line,
    generate_persona_turn,
    generate_sales_turn,
)
from src.business_stages import (
    is_valid_transition,
    short_circuit_statuses,
    stage_cn_name,
)
from src.coach import run_coach
from src.output_writer import write_session_outputs
from src.safe_console import SafeConsole
from src.schema import DialogueState, JudgeFeedback, PersonaProfile, SessionMemory, Turn
from src.utils import now_timestamp


console = SafeConsole()

_RECENT_HISTORY_LIMIT = 10

STAGES = [
    "开场与需求暴露",
    "核心异议出现",
    "销冠挖掘动机",
    "方案匹配与价值锚定",
    "强压测试",
    "成交推进或失败退出",
]

# Stage 5.5：5 个销售开场白模板（销售先开口时随机/指定）
OPENING_TEMPLATES = [
    "您好，欢迎光临，请问今天想看点什么？",
    "Hi，需要我帮您介绍一下吗？",
    "您好，随便看看也没关系，有需要随时叫我～",
    "欢迎光临！这边有刚到的新品，要不要看一下？",
    "您好，这边有什么我可以帮您的吗？",
]


# Stage 5.5：COMPLAINT 也算终结（用户投诉/服务态度差 → 立即停止）
_TERMINAL_STATUSES = {"DEAL_DONE", "WALK_AWAY", "FOLLOW_UP", "COMPLAINT"}

# business_stages v0.2 Q5：客户出 DEAL_DONE 时不立即 break，让销冠跑完本轮 S5 峰终；
# WALK_AWAY / COMPLAINT 才是真正的短路终止（不再生成销冠回复）。
# 实际短路集合走 YAML 配置（默认 WALK_AWAY + COMPLAINT），方便后续调整。
def _hard_short_circuit_statuses() -> set[str]:
    try:
        return set(short_circuit_statuses())
    except Exception:
        return {"WALK_AWAY", "COMPLAINT"}


# Stage 6a：事件类型（与前端 ws 事件名对齐）
EVENT_SESSION_START = "session_start"
EVENT_STAGE_CHANGE = "stage_change"
EVENT_PERSONA_TURN = "persona_turn"
EVENT_SALES_TURN = "sales_turn"
EVENT_MEMORY_UPDATE = "memory_update"
EVENT_JUDGE_FEEDBACK = "judge_feedback"
EVENT_COACH_REVIEW = "coach_review"
EVENT_SESSION_END = "session_end"
EVENT_LOG = "log"  # 通用提示，前端可选展示
EVENT_SESSION_STATUS = "session_status"  # 运行态变化（如暂停/恢复）


def _safe_emit(
    on_event: Optional[Callable[[dict], None]],
    event_type: str,
    data: dict,
) -> None:
    """事件上抛包装：吞掉异常，确保推流故障永远不影响主循环。"""
    if on_event is None:
        return
    try:
        on_event({"type": event_type, "data": data})
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]on_event({event_type}) 失败（忽略）: {exc}[/yellow]")


def get_stage_by_round(round_idx: int, max_rounds: int) -> str:
    """按轮次比例返回当前销售阶段（Judge 可覆盖）。

    Stage 5.5 比例重排（保留 6 STAGES 命名）：
        0~15%   STAGES[0] 开场与需求暴露
        15~33%  STAGES[1] 核心异议出现       ┐ 合占 35%（核心需求挖掘期）
        33~50%  STAGES[2] 销冠挖掘动机       ┘
        50~70%  STAGES[3] 方案匹配与价值锚定
        70~85%  STAGES[4] 强压测试
        85~100% STAGES[5] 成交推进或失败退出
    """
    if max_rounds <= 0:
        return STAGES[0]
    progress = (round_idx - 1) / max_rounds
    if progress < 0.15:
        return STAGES[0]
    elif progress < 0.33:
        return STAGES[1]
    elif progress < 0.50:
        return STAGES[2]
    elif progress < 0.70:
        return STAGES[3]
    elif progress < 0.85:
        return STAGES[4]
    else:
        return STAGES[5]


def get_phase(round_idx: int, max_rounds: int) -> str:
    """对外暴露的"阶段大类"（mining / matching / pressure / closing），
    供 agents.py 注入阶段约束时使用。比 STAGES 名更稳定。
    """
    if max_rounds <= 0:
        return "mining"
    progress = (round_idx - 1) / max_rounds
    if progress < 0.50:
        return "mining"      # 开场 + 需求挖掘
    elif progress < 0.70:
        return "matching"    # 方案匹配
    elif progress < 0.85:
        return "pressure"    # 强压测试
    else:
        return "closing"     # 成交推进 / 失败退出


def _append_turn(state: DialogueState, turn: Turn) -> None:
    """把新 Turn 追加到 full_history，并维护 recent_history 滑窗。注入当前 stage。"""
    turn.metadata["stage"] = state.current_stage
    state.full_history.append(turn)
    state.recent_history.append(turn)
    if len(state.recent_history) > _RECENT_HISTORY_LIMIT:
        state.recent_history = state.recent_history[-_RECENT_HISTORY_LIMIT:]


def _print_turn(turn: Turn, persona_name: str) -> None:
    """把一轮发言用 rich Panel 打印到控制台。"""
    if turn.speaker == "persona":
        label = f"[bold blue]用户 · {persona_name}[/bold blue]"
        border = "blue"
        meta_parts = [
            f"intent={turn.metadata.get('intent', '-')}",
            f"attitude={turn.metadata.get('attitude', '-')}",
            f"purchase_signal={turn.metadata.get('purchase_signal', '-')}",
            f"status={turn.metadata.get('status', '-')}",
        ]
    else:
        label = "[bold green]销冠[/bold green]"
        border = "green"
        meta_parts = [
            f"intent={turn.metadata.get('intent', '-')}",
            f"next_action={turn.metadata.get('next_action', '-')}",
        ]

    body = Text(turn.content)
    body.append(f"\n[dim]{'  ·  '.join(meta_parts)}[/dim]", style="dim")
    console.print(Panel(body, title=label, border_style=border, expand=False))


def _should_stop_early(state: DialogueState) -> tuple[bool, str]:
    """检查是否在客户 turn 之后立刻硬短路（不再让销冠跑本轮）。

    business_stages v0.2 Q5：
      - **硬短路**（立即 break，不跑销冠）：WALK_AWAY / COMPLAINT —— 客户已经走人，
        销冠再说任何话都是对空气说，且语义上也违反"客户已离场不应再发言"。
      - **软终止**（让销冠跑完本轮峰终再 break）：DEAL_DONE / FOLLOW_UP —— 销冠
        仍有 S5 收尾、加微信、留祝福等动作要做。由主循环在销冠 turn 之后再判一次。
      - max_rounds_floor 护栏继续生效：早于 floor 的任何 terminal 信号都被忽略。

    返回 (是否硬短路, 原因)。
    """
    hard_set = _hard_short_circuit_statuses()
    floor = state.max_rounds_floor or 0

    if state.outcome in _TERMINAL_STATUSES:
        if state.round_idx < floor:
            # 早结束被护栏挡住，清掉 outcome 让循环继续
            state.outcome = ""
        elif state.outcome in hard_set:
            return True, f"Persona 状态: {state.outcome}（硬短路 / 不再生成销冠回复）"

    latest_persona = next(
        (t for t in reversed(state.full_history) if t.speaker == "persona"), None
    )
    if latest_persona and latest_persona.metadata.get("status") in _TERMINAL_STATUSES:
        if state.round_idx < floor:
            return False, ""
        status = latest_persona.metadata["status"]
        reason = latest_persona.metadata.get("walk_away_reason") or ""
        state.outcome = status
        tail = f" · 原因：{reason}" if reason else ""
        if status in hard_set:
            return True, f"Persona status={status}{tail}（硬短路 / 不再生成销冠回复）"
        # 软终止：标记 outcome 但本轮销冠还要跑完
        return False, ""
    return False, ""


def _should_stop_after_sales(state: DialogueState) -> tuple[bool, str]:
    """销冠 turn 跑完后再判一次：DEAL_DONE / FOLLOW_UP 已经在 state.outcome 里
    （由 _should_stop_early 在销冠之前打的标），现在让销冠的 S5 峰终发完就 break。
    """
    floor = state.max_rounds_floor or 0
    if state.round_idx < floor:
        return False, ""
    if state.outcome in _TERMINAL_STATUSES and state.outcome not in _hard_short_circuit_statuses():
        return True, f"销冠 S5 峰终已完成，按 Persona 状态 {state.outcome} 结束"
    return False, ""


def run_session(
    product_text: str,
    persona: PersonaProfile,
    topic: str,
    max_rounds: int = 20,
    judge_interval: int = 3,
    # business_stages v0.2 Q1：默认 2 轮刷新一次（原 3），让 Judge 的 gate
    # 在客户暴露信号后能更快查到 session_memory.current_need 等字段。
    memory_interval: int = 2,
    output_dir: str = "outputs",
    judge_fn=None,
    memory_fn=None,
    *,
    who_speaks_first: str = "sales",
    opening_line: str = "",
    max_rounds_floor: int = 0,
    on_event: Optional[Callable[[dict], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
    pause_flag: Optional[threading.Event] = None,
    session_id: Optional[str] = None,
    product_kb_id: Optional[int] = None,
    enterprise_kb_id: Optional[int] = None,
    handbook_id: Optional[int] = None,
    language: str = "zh-CN",
) -> DialogueState:
    """运行一场完整的多轮销售博弈会话。

    Args:
        product_text: 产品资料全文。
        persona: 用户人设。
        topic: 会话主题。
        max_rounds: 最大对话轮数。
        judge_interval: 每隔几轮调用 Judge Agent。
        memory_interval: 每隔几轮更新 Session Memory。
        output_dir: 输出根目录（阶段 7 使用）。
        judge_fn: Judge Agent 函数（阶段 6 注入）。
        memory_fn: Session Memory 更新函数（阶段 6 注入）。
        who_speaks_first: Stage 5.5——"sales" 销售先开口，"persona" 客户先开口。
        opening_line: who_speaks_first="sales" 时使用的开场白；为空则取 OPENING_TEMPLATES[0]。
        max_rounds_floor: 在该轮之前忽略一切提前结束信号（防过早成交/早撤）。
            建议设为 max(3, int(max_rounds * 0.15))。

    Returns:
        最终 DialogueState，供后续输出模块使用。
    """
    if who_speaks_first not in ("sales", "persona"):
        raise ValueError(f"who_speaks_first 必须是 'sales' 或 'persona'，当前 {who_speaks_first!r}")
    # 注：销售先开口且未显式指定开场白时，不再写死中文模板默认值，
    # 留空交由下方 generate_opening_line 按会话语言现场生成。

    # Stage 6a：session_id 允许外部传入（让 Web 创建的 session 与 outputs 目录、DB 主键对齐）
    if not session_id:
        session_id = f"session_{now_timestamp()}_{persona.id}"
    state = DialogueState(
        session_id=session_id,
        topic=topic,
        product_text=product_text,
        persona_profile=persona,
        round_idx=0,
        max_rounds=max_rounds,
        current_stage=STAGES[0],
        current_stage_id="S1",  # business_stages v0.2：从 S1 起步
        outcome="",
        session_memory=SessionMemory.empty(),
        judge_feedback=JudgeFeedback.empty(),
        who_speaks_first=who_speaks_first,
        opening_line=opening_line if who_speaks_first == "sales" else "",
        max_rounds_floor=max_rounds_floor,
        product_kb_id=product_kb_id,
        enterprise_kb_id=enterprise_kb_id,
        handbook_id=handbook_id,
        language=language,
    )

    # 销售先开口且未指定开场白 → 用 LLM 按会话语言现场生成（英语会话出英文招呼）。
    # 放在 preflight / SESSION_START 之前，保证后续事件与第 0 轮 turn 拿到的是真实文本。
    if state.who_speaks_first == "sales" and not state.opening_line:
        state.opening_line = generate_opening_line(state)
        opening_line = state.opening_line

    # v0.2.2 真实性补丁：会话启动前预检产品事实卡（永不抛）
    try:
        from src.preflight import build_product_fact_card
        state.product_fact_card = build_product_fact_card(
            topic=topic,
            persona=persona,
            product_kb_id=product_kb_id,
        )
        console.print(
            f"[dim]事实卡:[/dim] {state.product_fact_card.product_name} "
            f"[{state.product_fact_card.confidence}]"
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]preflight 失败（不影响会话）：{exc}[/yellow]")
        state.product_fact_card = None

    # ② 深度研究节点：对话前为「产品 × persona 市场」预研一份市场事实表（缓存优先，永不抛）
    try:
        from src.research.market_research import get_or_research

        _cc = (getattr(persona, "country_code", None) or "").strip().upper()
        if _cc and _cc != "GLOBAL":
            _mf = get_or_research(handbook_id=handbook_id, country_code=_cc)
            if _mf:
                _own = (_mf.get("facts") or {}).get("own_product") or {}
                console.print(
                    f"[dim]市场事实表:[/dim] {_cc} 本品价={_own.get('price') or '—'} "
                    f"[{(_mf.get('facts') or {}).get('evidence_quality', '?')}]"
                )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]市场预研失败（不影响会话）：{exc}[/yellow]")

    console.rule(f"[bold]会话开始[/bold]  {session_id}")
    console.print(
        f"[dim]人设:[/dim] {persona.name}  "
        f"[dim]话题:[/dim] {topic}  "
        f"[dim]最大轮数:[/dim] {max_rounds}  "
        f"[dim]先开口:[/dim] {who_speaks_first}  "
        f"[dim]floor:[/dim] {max_rounds_floor}"
    )

    _safe_emit(on_event, EVENT_SESSION_START, {
        "session_id": session_id,
        "topic": topic,
        "persona": {
            "id": getattr(persona, "id", None),
            "name": persona.name,
            "format_type": getattr(persona, "format_type", "structured"),
            "tags": list(getattr(persona, "tags", []) or []),
        },
        "max_rounds": max_rounds,
        "max_rounds_floor": max_rounds_floor,
        "judge_interval": judge_interval,
        "memory_interval": memory_interval,
        "who_speaks_first": who_speaks_first,
        "opening_line": opening_line if who_speaks_first == "sales" else "",
        "current_stage": state.current_stage,
    })

    # Stage 5.5：销售先开口——把开场白作为 idx=0 turn 直接 append，不调 LLM
    if state.who_speaks_first == "sales":
        opening_turn = Turn(
            idx=0,
            speaker="sales",
            content=state.opening_line,
            metadata={
                "intent": "opening_greeting",
                "is_opening": True,
                "used_product_context": False,
                "next_action": "wait_for_customer_response",
            },
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        _append_turn(state, opening_turn)
        _print_turn(opening_turn, persona.name)
        _safe_emit(on_event, EVENT_SALES_TURN, {
            "turn": opening_turn.model_dump(),
            "round_idx": 0,
            "stage": state.current_stage,
        })

    for round_idx in range(1, max_rounds + 1):
        # Stage 6a：每轮开头检查中断标志（响应 ≤ 1 轮）
        if cancel_flag is not None and cancel_flag.is_set():
            state.outcome = "CANCELLED"
            console.print("[yellow]收到中断信号，会话停止。[/yellow]")
            _safe_emit(on_event, EVENT_LOG, {
                "level": "info",
                "message": f"会话在 Round {round_idx} 前被中断",
            })
            break

        # 暂停：在轮与轮之间挂起（响应 ≤ 1 轮），期间仍可被中断
        if pause_flag is not None and pause_flag.is_set():
            _safe_emit(on_event, EVENT_LOG, {
                "level": "info",
                "message": f"会话在 Round {round_idx} 前暂停",
            })
            while pause_flag.is_set():
                if cancel_flag is not None and cancel_flag.is_set():
                    break
                time.sleep(0.3)
            if not (cancel_flag is not None and cancel_flag.is_set()):
                _safe_emit(on_event, EVENT_LOG, {
                    "level": "info",
                    "message": f"会话在 Round {round_idx} 前恢复",
                })

        state.round_idx = round_idx

        # business_stages v0.2：current_stage / current_stage_id 完全由 Judge 决定。
        # round_idx==1 用默认 S1（已在 DialogueState 初始化时设置），后续不再按轮次比例自动推进。
        # 旧的 STAGES 6 阶段中文名 + get_stage_by_round 仅保留用于历史对话回放兼容。
        prev_stage = state.current_stage
        if not state.current_stage:
            state.current_stage = STAGES[0]
        if state.current_stage != prev_stage:
            _safe_emit(on_event, EVENT_STAGE_CHANGE, {
                "round_idx": round_idx,
                "from_stage": prev_stage,
                "to_stage": state.current_stage,
                "from_stage_id": state.current_stage_id,
                "to_stage_id": state.current_stage_id,
                "direction": "stay",
                "trigger": "init",
            })

        console.print(
            f"\n[bold]Round {round_idx}/{max_rounds}[/bold] "
            f"[dim]· 阶段：{state.current_stage} ({state.current_stage_id})[/dim]"
        )

        # ── Persona 发言 ──────────────────────────────────────────
        console.print("[dim]  Persona 思考中...[/dim]")
        persona_turn = generate_persona_turn(state)
        _append_turn(state, persona_turn)
        _print_turn(persona_turn, persona.name)
        _safe_emit(on_event, EVENT_PERSONA_TURN, {
            "turn": persona_turn.model_dump(),
            "round_idx": round_idx,
            "stage": state.current_stage,
        })

        # 检查 Persona 是否触发结束
        stop, reason = _should_stop_early(state)
        if stop:
            console.print(f"[yellow]对话提前结束：{reason}[/yellow]")
            _safe_emit(on_event, EVENT_LOG, {
                "level": "info",
                "message": f"提前结束：{reason}",
            })
            break

        # ── Sales 发言 ────────────────────────────────────────────
        console.print("[dim]  Sales 思考中...[/dim]")
        sales_turn = generate_sales_turn(state)
        _append_turn(state, sales_turn)
        _print_turn(sales_turn, persona.name)
        _safe_emit(on_event, EVENT_SALES_TURN, {
            "turn": sales_turn.model_dump(),
            "round_idx": round_idx,
            "stage": state.current_stage,
            "stage_id": state.current_stage_id,
        })

        # business_stages v0.2 Q5：销冠跑完后再判一次软终止（DEAL_DONE / FOLLOW_UP）
        stop, reason = _should_stop_after_sales(state)
        if stop:
            console.print(f"[yellow]对话结束（销冠 S5 后）：{reason}[/yellow]")
            _safe_emit(on_event, EVENT_LOG, {
                "level": "info",
                "message": f"销冠 S5 后结束：{reason}",
            })
            break

        # ── Session Memory 更新（阶段 6 补充；占位先跳过）──────────
        if memory_fn and round_idx % memory_interval == 0:
            console.print(f"[dim]  [Round {round_idx}] 更新会话画像...[/dim]")
            try:
                state.session_memory = memory_fn(state)
                console.print(
                    f"  [dim]do_not_repeat: {state.session_memory.do_not_repeat}[/dim]"
                )
                _safe_emit(on_event, EVENT_MEMORY_UPDATE, {
                    "round_idx": round_idx,
                    "session_memory": state.session_memory.model_dump(),
                })
            except Exception as exc:
                console.print(f"[yellow]  Session Memory 更新失败（跳过）: {exc}[/yellow]")

        # ── Judge 检查 + business_stages v0.2 阶段推进（含倒退）────
        if judge_fn and round_idx % judge_interval == 0:
            console.print(f"[dim]  [Round {round_idx}] Judge 检查中...[/dim]")
            try:
                state.judge_feedback = judge_fn(state)
                console.print(
                    f"  Judge → stage={state.judge_feedback.next_stage}  "
                    f"end_status={state.judge_feedback.end_status}  "
                    f"reason={state.judge_feedback.reason[:60]}"
                )

                # business_stages v0.2：用 stage_transition 推进 current_stage_id；
                # 同时把中文名同步到 current_stage 供前端 / 老逻辑兼容。
                st = state.judge_feedback.stage_transition
                prev_stage_id = state.current_stage_id
                prev_stage_cn = state.current_stage
                if st and st.to_stage:
                    new_sid = st.to_stage
                    # 服务端再次防御性校验（Judge 内部已校验过一次）
                    if is_valid_transition(prev_stage_id, new_sid):
                        state.current_stage_id = new_sid
                        state.current_stage = stage_cn_name(new_sid)
                    else:
                        console.print(
                            f"[yellow]Judge stage_transition 非法 "
                            f"{prev_stage_id}→{new_sid}，已忽略[/yellow]"
                        )
                if state.current_stage_id != prev_stage_id:
                    _safe_emit(on_event, EVENT_STAGE_CHANGE, {
                        "round_idx": round_idx,
                        "from_stage": prev_stage_cn,
                        "to_stage": state.current_stage,
                        "from_stage_id": prev_stage_id,
                        "to_stage_id": state.current_stage_id,
                        "direction": st.direction if st else "stay",
                        "trigger": "judge",
                        "reason": (st.triggered_fail_signal if st else "") or state.judge_feedback.reason,
                    })

                _safe_emit(on_event, EVENT_JUDGE_FEEDBACK, {
                    "round_idx": round_idx,
                    "judge_feedback": state.judge_feedback.model_dump(),
                })

                # Judge 可以终止会话（floor 护栏内强制忽略；硬短路 statuses 立刻生效）
                if state.judge_feedback.end_status not in ("CONTINUE", ""):
                    if state.round_idx < state.max_rounds_floor:
                        console.print(
                            f"[yellow]Judge 想终止({state.judge_feedback.end_status})，"
                            f"但当前轮 {state.round_idx} < floor {state.max_rounds_floor}，"
                            f"护栏拦截，继续。[/yellow]"
                        )
                    else:
                        state.outcome = state.judge_feedback.end_status
                        console.print(
                            f"[yellow]Judge 终止会话：end_status={state.outcome}[/yellow]"
                        )
                        break
            except Exception as exc:
                console.print(f"[yellow]  Judge 检查失败（跳过）: {exc}[/yellow]")

    else:
        # 跑满 max_rounds 没有提前结束。
        # Stage 15d：根据最近一轮 persona 的 purchase_signal 判定更合适的 outcome：
        #   · purchase_signal ≥ 0.6 → FOLLOW_UP（明显感兴趣但没成交，约后续）
        #   · 0.3 ≤ signal < 0.6   → FOLLOW_UP（中度兴趣）
        #   · signal < 0.3         → TIMEOUT（聊到上限但客户冷淡）
        # 这样避免"50 轮快成交了结果对话停止 = TIMEOUT"的错误归类。
        if not state.outcome:
            try:
                last_p = next(
                    (t for t in reversed(state.full_history) if t.speaker == "persona"),
                    None,
                )
                sig = 0.0
                if last_p:
                    sig = float((last_p.metadata or {}).get("purchase_signal") or 0)
            except Exception:
                sig = 0.0
            if sig >= 0.3:
                state.outcome = "FOLLOW_UP"
                console.print(
                    f"[yellow]已达最大轮数 {max_rounds}，但客户购买信号={sig:.2f}，"
                    f"会话结束为 FOLLOW_UP（约后续跟进）[/yellow]"
                )
            else:
                state.outcome = "TIMEOUT"
                console.print(
                    f"[yellow]已达最大轮数 {max_rounds}，客户购买信号={sig:.2f}，"
                    f"会话结束：TIMEOUT[/yellow]"
                )

    console.rule(
        f"[bold]会话结束[/bold]  outcome=[cyan]{state.outcome}[/cyan]  "
        f"共 {len([t for t in state.full_history if t.speaker == 'persona'])} 轮"
    )

    # ── 阶段 7：Coach 复盘 ────────────────────────────────────────────
    console.print("\n[bold]Coach 复盘中...[/bold]")
    try:
        state.coach_review = run_coach(state)
        if state.coach_review is not None:
            _safe_emit(on_event, EVENT_COACH_REVIEW, {
                "coach_review": state.coach_review.model_dump(),
            })
    except Exception as exc:
        console.print(f"[yellow]Coach 复盘失败（跳过）: {exc}[/yellow]")

    # ── Stage 11：销售案例三轨入库（judge_auto + coach_auto） ─────────
    # 完全静默：任何失败都不影响主流程。
    try:
        from src.cases import auto_extract_cases
        from src.storage.db import connection_scope, get_session_by_id
        with connection_scope() as _case_conn:
            _sess_row = get_session_by_id(_case_conn, session_id) or {}
            _pid = _sess_row.get("persona_id")
            _res = auto_extract_cases(_case_conn, state, persona_id=_pid)
        if any(_res.values()):
            console.print(
                f"[green]销售案例入库：judge_auto={_res['judge_auto']} "
                f"coach_auto={_res['coach_auto']}[/green]"
            )
    except Exception as exc:
        console.print(f"[yellow]销售案例入库失败（跳过）: {exc}[/yellow]")

    # ── 阶段 7：写出 4 个输出文件 ─────────────────────────────────────
    console.print("\n[bold]写出会话文件...[/bold]")
    output_path: str = ""
    try:
        session_dir = write_session_outputs(state, output_dir)
        output_path = str(session_dir)
        console.print(f"[green]文件输出完成：{session_dir}[/green]")
    except Exception as exc:
        console.print(f"[yellow]文件输出失败（跳过）: {exc}[/yellow]")

    # Stage 6a：最终 session_end 事件（永远是 stream 的最后一条）
    _safe_emit(on_event, EVENT_SESSION_END, {
        "session_id": session_id,
        "outcome": state.outcome,
        "total_rounds": state.round_idx,
        "persona_turns": len([t for t in state.full_history if t.speaker == "persona"]),
        "sales_turns": len([t for t in state.full_history if t.speaker == "sales"]),
        "output_dir": output_path,
    })

    return state
