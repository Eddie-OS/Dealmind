"""10 · 话术质量分析 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402
from shared.runctx import RunContext  # noqa: E402
from shared.session_reader import SessionRecord, load_sessions  # noqa: E402
from shared.trace import Tracer  # noqa: E402

AGENT_KEY = "10_quality_analyst"

_DIM_CN = {
    "responsiveness": "响应度",
    "specificity": "具体性",
    "evidence_usage": "证据使用",
    "objection_handling": "异议处理",
    "closing_progress": "推进度",
}


def _session_metrics(rec: SessionRecord) -> dict[str, Any]:
    signals = rec.signal_series()
    return {
        "persona_id": rec.persona_id,
        "persona_name": rec.persona_name,
        "outcome": rec.outcome,
        "rounds": rec.total_rounds,
        "final_stage": rec.final_stage,
        "judged": rec.judged,
        "quality_score": rec.quality_score,
        "difficulty": rec.difficulty,
        "sales_score": rec.sales_score,
        "handbook_citation_rate": rec.handbook_citation_rate,
        "guard_rewrites": rec.guard_rewrites,
        "fabrication_rate": round(rec.guard_rewrites / len(rec.sales_turns), 3)
        if rec.sales_turns
        else 0.0,
        "signal_start": signals[0] if signals else None,
        "signal_end": signals[-1] if signals else None,
        "signal_net": round(signals[-1] - signals[0], 3) if len(signals) >= 2 else None,
        "unresolved_objections": list(rec.memory.get("main_objections") or []),
        "failed_strategies": [
            str(f.get("strategy") or "").strip()
            for f in (rec.coach.get("what_failed") or [])
            if str(f.get("strategy") or "").strip()
        ],
    }


def _deep_analyze(rec: SessionRecord, handbook_struct: dict, max_turns: int, tracer: Tracer) -> list[dict[str, Any]]:
    from src.analyzers.handbook_turn_analyzer import analyze_turn_once

    rows: list[dict[str, Any]] = []
    for turn in rec.sales_turns[:max_turns]:
        content = (turn.get("content") or "").strip()
        if len(content) < 6:
            continue
        try:
            results = analyze_turn_once(content=content, handbook_struct=handbook_struct)
        except Exception as exc:  # noqa: BLE001
            tracer.log(f"{rec.persona_name} 第 {turn.get('idx')} 轮 deep 分析异常：{exc}", level="warn")
            continue
        for r in results:
            r["turn_idx"] = turn.get("idx")
            r["persona_id"] = rec.persona_id
            rows.append(r)
    return rows


def _render_md(
    metrics: list[dict[str, Any]],
    deep_rows: list[dict[str, Any]],
    mode: str,
    dry_run: bool,
) -> str:
    if not metrics:
        return "# 话术质量分析报告\n\n本次 run 没有任何已完成的会话。\n"

    # 裁判没来得及介入就结束的场次不参与打分统计，否则会被当成 0 分拉低均值
    scored = [m for m in metrics if m.get("judged")]
    unscored = [m for m in metrics if not m.get("judged")]
    basis = scored or metrics

    dim_means = {
        k: round(mean([m["sales_score"].get(k, 0.0) for m in basis]), 2) for k in _DIM_CN
    }
    weakest = min(dim_means, key=lambda k: dim_means[k]) if dim_means else None
    outcomes = Counter(m["outcome"] for m in metrics)
    failed = Counter(s for m in metrics for s in m["failed_strategies"])
    objections = Counter(o for m in metrics for o in m["unresolved_objections"])

    lines = [
        "# 话术质量分析报告",
        "",
        f"- 分析模式：**{mode}**" + ("　⚠️ **dry-run 数据，结论无效**" if dry_run else ""),
        f"- 会话数：**{len(metrics)}**"
        + (f"（其中 {len(unscored)} 场在裁判介入前就结束，不计入打分统计）" if unscored else ""),
        f"- 平均质量分：**{round(mean([m['quality_score'] for m in basis]), 2)}**",
        f"- 平均手册引用率：{round(mean([m['handbook_citation_rate'] for m in metrics]), 3)}"
        "（销冠自报，非客观校验）",
        f"- 平均编造率：{round(mean([m['fabrication_rate'] for m in metrics]), 3)}"
        "（被事实护栏改写的轮次占比）",
        "",
        "## 五维画像",
        "",
        f"基于 {len(basis)} 场被裁判打过分的会话。",
        "",
        "| 维度 | 均分 | 最低 | 最高 |",
        "|------|------|------|------|",
    ]
    for k, cn in _DIM_CN.items():
        vals = [m["sales_score"].get(k, 0.0) for m in basis]
        lines.append(f"| {cn} | **{dim_means[k]}** | {min(vals)} | {max(vals)} |")
    lines.append("")

    if unscored:
        lines += [
            "### 未被打分的场次",
            "",
            "这些会话在第一次裁判介入之前就结束了（客户提前离场、开局异常等），",
            "没有任何裁判数据，因此不参与上面的均值计算。",
            "",
            "| 人设 | 结果 | 轮数 |",
            "|------|------|------|",
        ]
        lines += [f"| {m['persona_name']} | {m['outcome']} | {m['rounds']} |" for m in unscored]
        lines.append("")
    if weakest:
        lines += [
            f"**最弱维度：{_DIM_CN[weakest]}（{dim_means[weakest]}）**",
            "",
            "这是下一轮训练最该补的地方。",
            "",
        ]

    lines += ["## 结果分布", "", "| 结果 | 场次 | 占比 |", "|------|------|------|"]
    for outcome, n in outcomes.most_common():
        lines.append(f"| {outcome} | {n} | {round(n / len(metrics) * 100, 1)}% |")
    lines.append("")

    if failed:
        lines += ["## 高频失效策略", "", "| 策略 | 出现场次 |", "|------|----------|"]
        lines += [f"| {s} | {n} |" for s, n in failed.most_common(10)]
        lines.append("")

    if objections:
        lines += ["## 收尾时仍未解决的异议", "", "| 异议 | 出现场次 |", "|------|----------|"]
        lines += [f"| {o} | {n} |" for o, n in objections.most_common(10)]
        lines.append("")

    lines += [
        "## 每场明细",
        "",
        "| 人设 | 结果 | 轮数 | 终局阶段 | 质量分 | 难度 | 手册引用率 | 编造轮数 | 信号净变化 |",
        "|------|------|------|----------|--------|------|------------|----------|------------|",
    ]
    for m in sorted(metrics, key=lambda x: -x["quality_score"]):
        lines.append(
            f"| {m['persona_name']} | {m['outcome']} | {m['rounds']} | {m['final_stage']} | "
            f"{m['quality_score']} | {m['difficulty']}/10 | {m['handbook_citation_rate']} | "
            f"{m['guard_rewrites']} | {m['signal_net'] if m['signal_net'] is not None else '-'} |"
        )
    lines.append("")

    if deep_rows:
        by_dim: dict[str, list[float]] = {}
        for r in deep_rows:
            for k, v in (r.get("scores") or {}).items():
                if isinstance(v, (int, float)):
                    by_dim.setdefault(k, []).append(float(v))
        lines += [
            "## deep 模式 · 六维逐条打分",
            "",
            f"共分析 {len(deep_rows)} 条销冠发言与手册条目的匹配。",
            "",
            "| 维度 | 均分 | 样本数 |",
            "|------|------|--------|",
        ]
        for k, vals in sorted(by_dim.items()):
            lines.append(f"| {k} | {round(mean(vals), 2)} | {len(vals)} |")
        lines.append("")

        issues = Counter(i for r in deep_rows for i in (r.get("issues") or []))
        if issues:
            lines += ["### 高频问题", "", "| 问题 | 次数 |", "|------|------|"]
            lines += [f"| {i} | {n} |" for i, n in issues.most_common(15)]
            lines.append("")

    return "\n".join(lines)


def analyze(ctx: RunContext, cfg: dict[str, Any], mode_override: str | None = None) -> dict[str, Any]:
    tracer = Tracer(ctx, AGENT_KEY)
    qcfg = cfg.get("quality") or {}
    mode = (mode_override or qcfg.get("mode") or "fast").lower()
    max_turns = int(qcfg.get("deep_max_turns_per_session") or 20)

    sessions = load_sessions(ctx)
    tracer.log(f"读取 {len(sessions)} 场会话，模式 ={mode}")

    handbook_struct: dict = {}
    hb_path = ctx.handbook_dir / "handbook.json"
    if mode == "deep" and hb_path.is_file():
        handbook_struct = (
            json.loads(hb_path.read_text(encoding="utf-8")).get("structure_json") or {}
        )
    if mode == "deep" and not handbook_struct:
        tracer.log("deep 模式需要产品手册，但本次 run 没有绑定；降级到 fast", level="warn")
        mode = "fast"

    metrics: list[dict[str, Any]] = []
    deep_rows: list[dict[str, Any]] = []

    for rec in sessions:
        m = _session_metrics(rec)
        metrics.append(m)

        rows: list[dict[str, Any]] = []
        if mode == "deep":
            rows = _deep_analyze(rec, handbook_struct, max_turns, tracer)
            deep_rows.extend(rows)

        tracer.step(
            f"analyze_{rec.persona_id}",
            title=f"质量分析 · {rec.persona_name}",
            summary={
                "结果": m["outcome"],
                "质量分": m["quality_score"],
                "手册引用率": m["handbook_citation_rate"],
                "编造轮数": m["guard_rewrites"],
                "信号净变化": m["signal_net"],
                "deep 打分条数": len(rows),
            },
            output_json={"metrics": m, "deep": rows[:20]} if rows else {"metrics": m},
        )

    md = _render_md(metrics, deep_rows, mode, ctx.dry_run)
    (ctx.reports_dir / "quality_report.md").write_text(md, encoding="utf-8")
    (ctx.reports_dir / "quality_scores.json").write_text(
        json.dumps(
            {"mode": mode, "dry_run": ctx.dry_run, "sessions": metrics, "deep": deep_rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    ctx.set_stage(AGENT_KEY, "done", mode=mode, sessions=len(metrics), deep_rows=len(deep_rows))
    tracer.log(f"质量报告完成（{mode}）→ `reports/quality_report.md`", level="ok")
    return {"mode": mode, "metrics": metrics, "deep": deep_rows}


def main() -> int:
    ap = argparse.ArgumentParser(description="分析已完成会话的话术质量")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--mode", choices=["fast", "deep"], default=None)
    args = ap.parse_args()

    bootstrap.init()
    import yaml

    cfg = yaml.safe_load((bootstrap.AGENT_ROOT / "config" / "pipeline.yaml").read_text("utf-8"))
    rid = args.run_id or RunContext.latest_run_id()
    if not rid:
        print("没有找到任何 run，先跑一次 run_all.py")
        return 2
    ctx = RunContext.load(rid)
    res = analyze(ctx, cfg, args.mode)
    print(f"[{AGENT_KEY}] run={rid} mode={res['mode']} 会话 {len(res['metrics'])} 场")
    print(f"  → {ctx.reports_dir / 'quality_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
