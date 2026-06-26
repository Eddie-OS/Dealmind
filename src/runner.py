"""命令行入口。

阶段 1：参数解析 + 配置加载。
阶段 2：加载 product.md / persona.yaml 并打印输入摘要。
阶段 3：--test-llm 调用模型联通验证。
后续阶段在此基础上接入多轮主循环、Judge、Coach、输出。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from rich.console import Console
from rich.table import Table

from src.agents import generate_persona_turn, generate_sales_turn
from src.config import PROJECT_ROOT, Settings, load_settings
from src.judge import judge_dialogue
from src.llm import LLMCallError, LLMJsonParseError, call_llm_json
from src.loaders import (
    InputValidationError,
    load_persona_yaml,
    load_text_file,
    validate_product_text,
)
from src.memory import update_session_memory
from src.persona.loader import persona_from_db_row
from src.schema import DialogueState, JudgeFeedback, PersonaProfile, PressureProfile, SessionMemory
from src.session import OPENING_TEMPLATES, run_session
from src.storage import db as storage_db
from src.utils import now_timestamp, safe_json_dumps


console = Console()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.runner",
        description="多人设销冠压力测试引擎 MVP - 单场会话运行器",
    )
    parser.add_argument(
        "--product",
        type=str,
        default="data/product.md",
        help="产品资料 Markdown 路径（默认 data/product.md）",
    )
    parser.add_argument(
        "--persona",
        type=str,
        default="personas/price_sensitive_student.yaml",
        help=(
            "用户人设：可传 (a) YAML 文件路径，或 (b) DB 中 persona 的数字 id，"
            "或 (c) 形如 'db:<id>' 的显式 DB 引用。"
            "示例：--persona 1 / --persona db:5 / --persona personas/xxx.yaml"
        ),
    )
    parser.add_argument(
        "--topic",
        type=str,
        default="学习平板销售模拟",
        help="本场会话主题",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=20,
        help="最大对话轮数（默认 20）",
    )
    parser.add_argument(
        "--judge-interval",
        type=int,
        default=3,
        help="Judge Agent 调用间隔，单位：轮（默认 3）",
    )
    parser.add_argument(
        "--memory-interval",
        type=int,
        default=3,
        help="Session Memory 更新间隔，单位：轮（默认 3）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs",
        help="输出根目录（默认 outputs）",
    )
    # Stage 5.5：渐进式对话引擎参数
    parser.add_argument(
        "--first-speaker",
        type=str,
        choices=("sales", "persona"),
        default="sales",
        help="谁先开口（默认 sales 销冠先开场）",
    )
    parser.add_argument(
        "--opening-line",
        type=str,
        default="",
        help="销售开场白文本（仅 --first-speaker=sales 时生效；为空则用模板）",
    )
    parser.add_argument(
        "--opening-template",
        type=int,
        default=None,
        help="销售开场白模板编号 0~4（与 --opening-line 互斥；都不给则用 0 号）",
    )
    parser.add_argument(
        "--floor",
        type=int,
        default=None,
        help="最小护栏轮数（之前禁止一切提前结束）；默认 max(3, round(max_rounds*0.15))",
    )
    parser.add_argument(
        "--test-llm",
        action="store_true",
        help="仅做 LLM 联通测试：调用模型返回 {\"ok\": true, \"message\": \"LLM connected\"} 后退出",
    )
    parser.add_argument(
        "--one-turn-test",
        action="store_true",
        help="单轮测试：Persona 发言一次 + Sales 回应一次后退出",
    )
    return parser


def _resolve_persona(spec: str) -> PersonaProfile:
    """根据 --persona 入参解析为 PersonaProfile。

    解析顺序：
    1. 'db:<id>' 显式前缀 → 必须 DB 中找到，否则报错
    2. 纯数字 → 先按 DB id 查，找到就用；找不到再 fallback 文件路径
    3. 其他 → 直接当文件路径走 YAML 加载
    """
    if spec.startswith("db:"):
        try:
            pid = int(spec[3:])
        except ValueError as exc:
            raise InputValidationError(f"--persona db:<id> 中 id 必须为整数：{spec}") from exc
        with storage_db.connection_scope() as conn:
            row = storage_db.get_persona_by_id(conn, pid)
        if not row:
            raise InputValidationError(f"DB 中未找到 persona id={pid}")
        return persona_from_db_row(row)

    if spec.isdigit():
        pid = int(spec)
        with storage_db.connection_scope() as conn:
            row = storage_db.get_persona_by_id(conn, pid)
        if row:
            return persona_from_db_row(row)
        # 数字但 DB 没找到 → fall through 当文件路径

    return load_persona_yaml(spec)


def _print_run_config(args: argparse.Namespace, settings: Settings) -> None:
    """以表格形式打印本次运行的关键参数与配置。"""
    table = Table(title="MVP Runner 启动配置", show_header=True, header_style="bold cyan")
    table.add_column("项目", style="dim")
    table.add_column("值")

    table.add_row("Project root", str(PROJECT_ROOT))
    table.add_row("Product path", args.product)
    table.add_row("Persona path", args.persona)
    table.add_row("Topic", args.topic)
    table.add_row("Max rounds", str(args.max_rounds))
    table.add_row("Judge interval", str(args.judge_interval))
    table.add_row("Memory interval", str(args.memory_interval))
    table.add_row("Output dir", args.output_dir)
    table.add_row("First speaker", args.first_speaker)
    if args.first_speaker == "sales":
        if args.opening_line:
            table.add_row("Opening line (custom)", args.opening_line[:60])
        elif args.opening_template is not None:
            table.add_row("Opening template", f"#{args.opening_template}")
        else:
            table.add_row("Opening template", "#0 (default)")
    table.add_row("Floor (min rounds)", str(args.floor) if args.floor is not None else "auto")

    for key, value in settings.redacted().items():
        table.add_row(f"settings.{key}", str(value))

    console.print(table)


def _print_inputs_summary(product_text: str, persona: PersonaProfile) -> None:
    """打印产品与人设输入摘要。"""
    console.print(f"[green]Product loaded:[/green] 约 {len(product_text)} characters")
    console.print(
        f"[green]Persona loaded:[/green] {persona.name} "
        f"(id={persona.id}, format={getattr(persona, 'format_type', 'structured')})"
    )
    console.print(f"[dim]Pressure profile:[/dim] {persona.pressure_profile.summary()}")

    table = Table(title=f"人设详情：{persona.name}", show_header=True, header_style="bold magenta")
    table.add_column("字段", style="dim")
    table.add_column("值")
    table.add_row("Format", getattr(persona, "format_type", "structured"))
    table.add_row("Tags", ", ".join(persona.tags) if persona.tags else "-")
    table.add_row("年龄", str(persona.age) if persona.age is not None else "-")
    table.add_row("职业", persona.occupation or "-")
    table.add_row("预算", str(persona.budget) if persona.budget is not None else "-")
    table.add_row("性格", persona.personality or "-")
    table.add_row(
        "痛点",
        "\n".join(f"- {p}" for p in persona.pain_points) if persona.pain_points else "-",
    )
    table.add_row("异议风格", persona.objection_style or "-")
    table.add_row("购买目标", persona.purchase_goal or "-")
    if persona.format_type == "prompt_based" and persona.prompt_text:
        snippet = persona.prompt_text[:120] + ("..." if len(persona.prompt_text) > 120 else "")
        table.add_row("Prompt 摘要", snippet)
    console.print(table)


def _run_llm_smoke_test() -> int:
    """阶段 3 联通验证：调一次模型，要求返回固定 JSON。"""
    console.print("[bold]LLM 联通测试开始[/bold]")
    system_prompt = (
        "你是 LLM 联通测试机器人。无论用户说什么，你都只回复一个合法 JSON 对象，"
        "格式严格为 {\"ok\": true, \"message\": \"LLM connected\"}。"
        "不要输出任何额外文字、markdown 或解释。"
    )
    user_prompt = "请按规定输出联通验证 JSON。"
    try:
        result = call_llm_json(system_prompt, user_prompt, temperature=0.0)
    except LLMJsonParseError as exc:
        console.print(f"[red]LLM 输出无法解析为 JSON:[/red] {exc}")
        console.print(f"[dim]原始片段:[/dim] {exc.raw_output!r}")
        return 3
    except LLMCallError as exc:
        console.print(f"[red]LLM 调用失败:[/red] {exc}")
        return 4

    console.print("[green]LLM 返回 JSON 如下:[/green]")
    console.print(safe_json_dumps(result))

    if isinstance(result, dict) and result.get("ok") is True:
        console.print("[bold green]LLM 联通测试通过[/bold green]")
        return 0
    console.print(
        "[yellow]LLM 已联通但返回内容与预期不完全一致，"
        "可能是模型自由发挥导致；调用链路本身正常。[/yellow]"
    )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        settings = load_settings()
    except RuntimeError as exc:
        console.print(f"[red]配置加载失败:[/red] {exc}")
        return 1

    console.print("[green]Settings loaded successfully[/green]")
    _print_run_config(args, settings)

    if args.test_llm:
        return _run_llm_smoke_test()

    try:
        product_text = load_text_file(args.product)
        validate_product_text(product_text)
        persona = _resolve_persona(args.persona)
    except InputValidationError as exc:
        console.print(f"[red]输入加载失败:[/red] {exc}")
        return 2

    _print_inputs_summary(product_text, persona)

    if args.one_turn_test:
        return _run_one_turn_test(product_text, persona, args)

    # Stage 5.5：解析开场白
    opening_line = ""
    if args.first_speaker == "sales":
        if args.opening_line and args.opening_template is not None:
            console.print("[red]--opening-line 和 --opening-template 不能同时指定[/red]")
            return 2
        if args.opening_line:
            opening_line = args.opening_line
        elif args.opening_template is not None:
            if not 0 <= args.opening_template < len(OPENING_TEMPLATES):
                console.print(
                    f"[red]--opening-template 必须在 0~{len(OPENING_TEMPLATES)-1} 之间[/red]"
                )
                return 2
            opening_line = OPENING_TEMPLATES[args.opening_template]
        else:
            opening_line = OPENING_TEMPLATES[0]

    # floor 默认：max(3, round(max_rounds*0.15))
    floor = args.floor if args.floor is not None else max(3, round(args.max_rounds * 0.15))

    # 阶段 6+：注入 Judge 和 Session Memory；Stage 5.5 注入渐进式参数
    state = run_session(
        product_text=product_text,
        persona=persona,
        topic=args.topic,
        max_rounds=args.max_rounds,
        judge_interval=args.judge_interval,
        memory_interval=args.memory_interval,
        output_dir=args.output_dir,
        judge_fn=judge_dialogue,
        memory_fn=update_session_memory,
        who_speaks_first=args.first_speaker,
        opening_line=opening_line,
        max_rounds_floor=floor,
    )

    console.print(
        f"\n[bold]会话摘要[/bold]  outcome=[cyan]{state.outcome}[/cyan]  "
        f"turns={len(state.full_history)}  session_id={state.session_id}"
    )
    console.print(
        "[yellow]当前进度：阶段 6 完成（Judge + Session Memory 已接入）。"
        "继续推进阶段 7（Coach 复盘 + 输出文件）。[/yellow]"
    )
    return 0


def _run_one_turn_test(product_text: str, persona: "PersonaProfile", args: argparse.Namespace) -> int:
    """单轮测试：Persona 发言 → Sales 回应，打印两段对话。"""
    from src.schema import DialogueState, JudgeFeedback, SessionMemory

    console.rule("[bold cyan]单轮测试开始[/bold cyan]")

    state = DialogueState(
        session_id=f"test_{now_timestamp()}",
        topic=args.topic,
        product_text=product_text,
        persona_profile=persona,
        round_idx=1,
        max_rounds=args.max_rounds,
        current_stage="开场与需求暴露",
        session_memory=SessionMemory.empty(),
        judge_feedback=JudgeFeedback.empty(),
    )

    console.print(f"\n[bold magenta]Round 1[/bold magenta] · 阶段：{state.current_stage}\n")

    console.print("[dim]Persona Agent 思考中...[/dim]")
    persona_turn = generate_persona_turn(state)
    console.print(f"[bold blue]【用户 · {persona.name}】[/bold blue]")
    console.print(f"  {persona_turn.content}")
    console.print(f"  [dim]→ intent={persona_turn.metadata.get('intent')}  "
                  f"attitude={persona_turn.metadata.get('attitude')}  "
                  f"purchase_signal={persona_turn.metadata.get('purchase_signal')}  "
                  f"status={persona_turn.metadata.get('status')}[/dim]\n")

    state.recent_history.append(persona_turn)
    state.full_history.append(persona_turn)

    console.print("[dim]Sales Agent 思考中...[/dim]")
    sales_turn = generate_sales_turn(state)
    console.print("[bold green]【销冠】[/bold green]")
    console.print(f"  {sales_turn.content}")
    console.print(f"  [dim]→ intent={sales_turn.metadata.get('intent')}  "
                  f"next_action={sales_turn.metadata.get('next_action')}[/dim]\n")

    console.rule("[bold cyan]单轮测试完成[/bold cyan]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
