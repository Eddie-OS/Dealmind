"""00 · 统筹编排 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402
from shared.runctx import RunContext  # noqa: E402
from shared.trace import Tracer, md_kv_table, write_run_log_header  # noqa: E402

AGENT_KEY = "00_orchestrator"

# 会话内 agent：事件到来时问它们要不要渲染这一步
IN_LOOP_AGENTS = [
    "03_sales_agent",
    "04_customer_agent",
    "05_judge_agent",
    "06_memory_agent",
    "07_coach_agent",
    "08_content_guard",
]


def _load_agent(folder: str):
    """按目录名加载 agent 模块。目录以数字开头，不能用普通 import。"""
    path = bootstrap.AGENT_ROOT / folder / "run.py"
    spec = importlib.util.spec_from_file_location(f"agent_{folder}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_config() -> dict[str, Any]:
    import yaml

    path = bootstrap.AGENT_ROOT / "config" / "pipeline.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


# ── 成本估算 ──────────────────────────────────────────────────────────


def estimate_calls(n_personas: int, rounds: int, judge_interval: int, memory_interval: int) -> dict[str, int]:
    per_session = (
        rounds * 2                      # 每轮客户 + 销冠各一次
        + rounds // max(judge_interval, 1)
        + rounds // max(memory_interval, 1)
        + 1                             # 会后复盘
        + 1                             # 开场白 / 产品事实卡抽取
    )
    return {
        "每场估算调用": per_session,
        "人设数": n_personas,
        "合计估算调用": per_session * n_personas,
    }


def check_budget(cfg: dict[str, Any], n_personas: int, rounds: int, est: dict[str, int]) -> Optional[str]:
    b = cfg.get("budget") or {}
    if n_personas > int(b.get("max_personas") or 10**9):
        return f"人设数 {n_personas} 超过 budget.max_personas={b.get('max_personas')}"
    if rounds > int(b.get("max_rounds_per_session") or 10**9):
        return f"轮数 {rounds} 超过 budget.max_rounds_per_session={b.get('max_rounds_per_session')}"
    if est["合计估算调用"] > int(b.get("max_llm_calls") or 10**9):
        return (
            f"估算调用 {est['合计估算调用']} 次超过 budget.max_llm_calls="
            f"{b.get('max_llm_calls')}"
        )
    return None


# ── 单场对练 ──────────────────────────────────────────────────────────


def _make_event_router(
    ctx: RunContext, session_dir: Path, agents: dict[str, Any]
) -> Callable[[dict], None]:
    """把 run_session 抛出的事件分发给会话内各 agent 的 MD 追踪器。"""
    tracers = {
        key: Tracer(ctx, key, scope_dir=session_dir) for key in agents
    }

    def on_event(event: dict) -> None:
        # run_session 抛的是 {"type": ..., "data": {...}}，agent 只关心 data
        etype = event.get("type")
        payload = event.get("data") or {}
        for key, mod in agents.items():
            if etype not in getattr(mod, "EVENT_TYPES", ()):
                continue
            try:
                rendered = mod.render(payload)
            except Exception:  # noqa: BLE001
                continue
            if not rendered:
                continue
            tracers[key].step(
                rendered["name"],
                title=rendered.get("title", ""),
                summary=rendered.get("summary"),
                output_md=rendered.get("output_md", ""),
                output_json=rendered.get("output_json"),
            )

    return on_event


def _write_dialogue_md(state: Any, path: Path, persona_name: str) -> None:
    """人类可读的对话全文。write_session_outputs 不产出这个，这里补上。"""
    lines = [
        f"# 对话全文 · {persona_name} vs 销冠",
        "",
        md_kv_table(
            {
                "session_id": state.session_id,
                "话题": state.topic,
                "结果": state.outcome,
                "总轮数": state.round_idx,
                "终局阶段": state.current_stage,
                "人设": f"{state.persona_profile.name}（{state.persona_profile.occupation or '-'}，"
                f"预算 {state.persona_profile.budget or '-'}）",
            }
        ),
        "",
        "---",
        "",
    ]
    for t in state.full_history:
        # SalesStrategy / HiddenState 的字段被上游铺平写在 metadata 顶层
        meta = t.metadata or {}
        if t.speaker == "sales":
            guard = meta.get("content_guard") or {}
            # 开场白在阶段机启动之前生成，没有 stage_id
            tag = f"阶段 {meta.get('stage_id')}" if meta.get("stage_id") else "开场"
            if meta.get("playbook_action"):
                tag += f" · {meta['playbook_action']}"
            if meta.get("used_handbook"):
                tag += " · 引用手册"
            if guard.get("rewritten"):
                tag += f" · ⚠️ 护栏改写 {len(guard.get('warnings') or [])} 处"
            lines += [f"**销冠**　<sub>{tag}</sub>", "", t.content, ""]
        else:
            tag = f"信号 {meta.get('purchase_signal', 0)} · {meta.get('status', 'CONTINUE')}"
            if meta.get("walk_away_reason"):
                tag += f" · {meta['walk_away_reason']}"
            lines += [f"**{persona_name}**　<sub>{tag}</sub>", "", t.content, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_one_session(
    ctx: RunContext,
    persona: Any,
    cfg: dict[str, Any],
    product_text: str,
    topic: str,
    agents: dict[str, Any],
    handbook_bound: bool,
) -> dict[str, Any]:
    """跑一个人设。任何异常都在这里被捕获，不让它掀翻全量。"""
    from src.judge import judge_dialogue
    from src.memory import update_session_memory
    from src.session import run_session

    rcfg = cfg.get("run") or {}
    rounds = int(rcfg.get("max_rounds") or 20)
    session_dir = ctx.session_dir(persona.id, persona.name)
    orch = Tracer(ctx, AGENT_KEY)

    if bootstrap.is_dry_run():
        from shared import fake_llm

        fake_llm.reset_thread()

    started = time.time()
    orch.log(f"开始对练 · **{persona.name}**（`{persona.id}`）")

    try:
        state = run_session(
            product_text=product_text,
            persona=persona,
            topic=topic,
            max_rounds=rounds,
            # 引擎会自己在 output_dir 下按 session_id 建目录，所以这里给父目录 +
            # 会话目录名，让引擎产物和本层写的 dialogue.md / steps 落在同一个目录里。
            output_dir=str(session_dir.parent),
            session_id=session_dir.name,
            judge_fn=judge_dialogue,
            memory_fn=update_session_memory,
            who_speaks_first=str(rcfg.get("who_speaks_first") or "sales"),
            max_rounds_floor=max(3, int(rounds * 0.15)),
            on_event=_make_event_router(ctx, session_dir, agents),
            handbook_id=1 if handbook_bound else None,
            language=str(rcfg.get("language") or "zh-CN"),
        )
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        (session_dir / "ERROR.md").write_text(
            f"# 对练失败 · {persona.name}\n\n```\n{traceback.format_exc()}\n```\n",
            encoding="utf-8",
        )
        ctx.mark_persona(persona.id, "failed", error=err)
        orch.log(f"**{persona.name}** 对练失败：{err}", level="error")
        return {"persona_id": persona.id, "status": "failed", "error": err}

    _write_dialogue_md(state, session_dir / "dialogue.md", persona.name)

    elapsed = round(time.time() - started, 1)
    ctx.mark_persona(
        persona.id,
        "done",
        outcome=state.outcome,
        rounds=state.round_idx,
        elapsed_s=elapsed,
        dir=str(session_dir.relative_to(ctx.root)).replace("\\", "/"),
    )
    orch.log(
        f"**{persona.name}** 完成 · 结果 `{state.outcome}` · {state.round_idx} 轮 · {elapsed}s",
        level="ok",
    )
    return {"persona_id": persona.id, "status": "done", "outcome": state.outcome}


# ── 全量编排 ──────────────────────────────────────────────────────────


def orchestrate(
    *,
    dry_run: bool = False,
    resume: Optional[str] = None,
    limit: Optional[int] = None,
    assume_yes: bool = False,
    quality_mode: Optional[str] = None,
) -> int:
    # 续跑必须先偷看 manifest 决定模式：对一个 dry-run 产生的 run 目录发起
    # 真实调用，会把假数据和真数据混在同一棵目录树里，之后没法分辨。
    if resume and not dry_run:
        man_path = bootstrap.AGENT_ROOT / "runs" / resume / "manifest.json"
        if man_path.is_file():
            dry_run = bool(json.loads(man_path.read_text(encoding="utf-8")).get("dry_run"))

    env = bootstrap.init(dry_run=dry_run or None)
    dry_run = bool(env["dry_run"])
    cfg = _load_config()
    rcfg = cfg.get("run") or {}
    if limit is not None:
        cfg.setdefault("personas", {})["limit"] = limit

    ctx = (
        RunContext.load(resume)
        if resume
        else RunContext.create(dry_run=dry_run, topic=str(rcfg.get("topic") or ""))
    )
    orch = Tracer(ctx, AGENT_KEY)
    write_run_log_header(
        ctx,
        env,
        {
            "run_id": ctx.run_id,
            "模式": "dry-run（假模型）" if dry_run else "真实执行",
            "最大轮数": rcfg.get("max_rounds"),
            "并发": rcfg.get("session_concurrency"),
            "人设上限": (cfg.get("personas") or {}).get("limit") or "全量",
            "质量分析模式": quality_mode or (cfg.get("quality") or {}).get("mode"),
        },
    )

    # ── 01 手册 ──
    handbook = _load_agent("01_handbook_ingest").ingest(ctx, cfg)
    handbook_bound = bool(handbook)
    ctx.manifest["source_handbook"] = handbook.get("name") or ""
    ctx.save_manifest()

    product_text = ""
    hb_md = ctx.handbook_dir / "handbook.md"
    if hb_md.is_file():
        product_text = hb_md.read_text(encoding="utf-8")
    if not product_text.strip():
        product_text = "（本次未绑定产品手册，销冠按通用销售经验作答。）"

    topic = str(rcfg.get("topic") or "").strip() or (
        f"{handbook.get('name')} 销售模拟" if handbook_bound else "通用销售模拟"
    )

    # ── 02 人设 ──
    personas = _load_agent("02_persona_curator").curate(ctx, cfg)
    if not personas:
        orch.log("没有可用人设，终止", level="error")
        print("personas/ 里没有可用人设。先跑 tools/export_personas_from_db.py 导一份快照。")
        return 2

    pending_ids = set(ctx.pending_personas([p.id for p in personas]))
    todo = [p for p in personas if p.id in pending_ids]
    skipped = len(personas) - len(todo)
    if skipped:
        orch.log(f"续跑：跳过已完成的 {skipped} 场，本次补 {len(todo)} 场")
    if not todo:
        orch.log("所有场次都已完成，跳过对练，直接重跑分析与报告阶段")

    # ── 成本闸 ──
    rounds = int(rcfg.get("max_rounds") or 20)
    est = estimate_calls(len(todo), rounds, 3, 2)
    violation = check_budget(cfg, len(todo), rounds, est)
    if violation:
        orch.log(f"预算闸拦截：{violation}", level="error")
        print(f"\n预算闸拦截：{violation}\n改 config/pipeline.yaml → budget 后重试。")
        return 3

    if todo and not dry_run and (cfg.get("budget") or {}).get("confirm_before_real_run", True) and not assume_yes:
        print("\n" + "=" * 60)
        print(f"即将真实执行：{len(todo)} 个人设 × 最多 {rounds} 轮")
        for k, v in est.items():
            print(f"  {k}: {v}")
        print("=" * 60)
        if input("确认开始？(y/N) ").strip().lower() not in {"y", "yes"}:
            orch.log("用户取消执行", level="warn")
            print("已取消。建议先跑 --dry-run 验证链路。")
            return 0

    orch.log(
        f"进入全量对练：{len(todo)} 场，估算模型调用 {est['合计估算调用']} 次"
        + ("（dry-run，实际不调用）" if dry_run else "")
    )

    # ── 03-08 全量对练 ──
    agents = {key: _load_agent(key) for key in IN_LOOP_AGENTS}
    concurrency = max(1, int(rcfg.get("session_concurrency") or 1))
    results: list[dict[str, Any]] = []

    if concurrency == 1:
        for persona in todo:
            results.append(
                run_one_session(ctx, persona, cfg, product_text, topic, agents, handbook_bound)
            )
    else:
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="session") as pool:
            futures = {
                pool.submit(
                    run_one_session, ctx, p, cfg, product_text, topic, agents, handbook_bound
                ): p
                for p in todo
            }
            for fut in as_completed(futures):
                results.append(fut.result())

    done = sum(1 for r in results if r["status"] == "done")
    failed = len(results) - done
    orch.log(f"对练结束：成功 {done} 场，失败 {failed} 场", level="ok" if not failed else "warn")

    # ── 09 / 10 / 11 ──
    _load_agent("09_phrase_miner").mine(ctx, cfg)
    _load_agent("10_quality_analyst").analyze(ctx, cfg, quality_mode)
    _load_agent("11_report_composer").compose(ctx, cfg)

    ctx.set_stage(AGENT_KEY, "done", sessions_done=done, sessions_failed=failed)
    orch.log(f"全部完成。入口：`EXEC_SUMMARY.md`", level="ok")

    print("\n" + "=" * 60)
    print(f"run_id = {ctx.run_id}" + ("（dry-run）" if dry_run else ""))
    print(f"完成 {done} 场，失败 {failed} 场")
    print(f"\n先看这个：{ctx.root / 'EXEC_SUMMARY.md'}")
    print(f"过程日志：  {ctx.run_log_path}")
    print(f"全部产物：  {ctx.root}")
    if failed:
        print(f"\n补跑失败场次：python run_all.py --resume {ctx.run_id}")
    print("=" * 60)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="全量模拟对抗总控")
    ap.add_argument("--dry-run", action="store_true", help="用假模型跑通全链路，不花钱")
    ap.add_argument("--resume", default=None, metavar="RUN_ID", help="续跑未完成的场次")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个人设")
    ap.add_argument("--yes", action="store_true", help="跳过真实执行前的确认")
    ap.add_argument("--quality-mode", choices=["fast", "deep"], default=None)
    a = ap.parse_args()
    return orchestrate(
        dry_run=a.dry_run,
        resume=a.resume,
        limit=a.limit,
        assume_yes=a.yes,
        quality_mode=a.quality_mode,
    )


if __name__ == "__main__":
    sys.exit(main())
