"""11 · 报告汇总 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402
from shared.runctx import RunContext  # noqa: E402
from shared.session_reader import load_sessions  # noqa: E402
from shared.trace import Tracer  # noqa: E402

AGENT_KEY = "11_report_composer"


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _cross_persona_md(metrics: list[dict[str, Any]], dry_run: bool) -> str:
    if not metrics:
        return "# 跨人设横向对比\n\n本次 run 没有已完成的会话。\n"

    lines = [
        "# 跨人设横向对比",
        "",
        ("> ⚠️ dry-run 数据，下列结论无效，仅用于验证报告格式。\n" if dry_run else ""),
        f"共 **{len(metrics)}** 个人设完成对练。",
        "",
        "## 总表（按质量分降序）",
        "",
        "| 人设 | 结果 | 质量分 | 人设难度 | 轮数 | 终局阶段 | 编造轮数 | 信号净变化 |",
        "|------|------|--------|----------|------|----------|----------|------------|",
    ]
    for m in sorted(metrics, key=lambda x: -x["quality_score"]):
        q = f"**{m['quality_score']}**" if m.get("judged") else "_未打分_"
        lines.append(
            f"| {m['persona_name']} | {m['outcome']} | {q} | "
            f"{m['difficulty']}/10 | {m['rounds']} | {m['final_stage']} | "
            f"{m['guard_rewrites']} | {m['signal_net'] if m['signal_net'] is not None else '-'} |"
        )
    lines.append("")

    scored_only = [m for m in metrics if m.get("judged")] or metrics
    hardest = sorted(scored_only, key=lambda x: (x["quality_score"], -x["difficulty"]))[:5]
    lines += ["## 销冠表现最差的五个对手", "", "| 人设 | 质量分 | 难度 | 未解决异议 |", "|------|--------|------|------------|"]
    for m in hardest:
        objs = "；".join(m["unresolved_objections"][:3]) or "-"
        lines.append(f"| {m['persona_name']} | {m['quality_score']} | {m['difficulty']}/10 | {objs} |")
    lines.append("")

    # 难度与表现的关系：难度高但分也高 = 销冠真强；难度低但分低 = 该补课
    lines += [
        "## 难度 vs 表现",
        "",
        "| 象限 | 含义 | 人设 |",
        "|------|------|------|",
    ]
    q_mid = mean([m["quality_score"] for m in scored_only])
    d_mid = mean([m["difficulty"] for m in scored_only]) or 5
    buckets: dict[str, list[str]] = defaultdict(list)
    for m in scored_only:
        hi_q = m["quality_score"] >= q_mid
        hi_d = m["difficulty"] >= d_mid
        key = (
            "硬仗打赢" if hi_q and hi_d else
            "轻松拿下" if hi_q else
            "难缠翻车" if hi_d else
            "简单也没接住"
        )
        buckets[key].append(m["persona_name"])
    for key, meaning in [
        ("硬仗打赢", "对手难 + 表现好，这里的打法值得沉淀"),
        ("轻松拿下", "对手不难 + 表现好，参考价值有限"),
        ("难缠翻车", "对手难 + 表现差，属于正常，看复盘找方法"),
        ("简单也没接住", "对手不难 + 表现差，**这是最该优先补的**"),
    ]:
        names = "、".join(buckets.get(key, [])) or "-"
        lines.append(f"| {key} | {meaning} | {names} |")
    lines.append("")
    return "\n".join(lines)


def _training_guide_md(
    handbook: dict[str, Any],
    phrases: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    guard_examples: list[str],
    dry_run: bool,
) -> str:
    struct = handbook.get("structure_json") or {}
    verified = [p for p in phrases if p.get("source") == "验证"]

    lines = [
        f"# 销售培训手册 · {handbook.get('name') or '（未绑定产品手册）'}",
        "",
        ("> ⚠️ dry-run 数据，内容为占位，不可用于培训。\n" if dry_run else ""),
        "本手册由一次全量模拟对抗自动生成。所有话术都标注了来源场次，",
        "有疑问可以回到对应会话看完整上下文。",
        "",
        "## 一、这个产品最该讲的几件事",
        "",
    ]
    intro = (struct.get("intro_1") or {}).get("text", "")
    if intro:
        lines += [f"**一句话定位**：{intro}", ""]
    sells = struct.get("selling_points") or []
    if sells:
        for i, s in enumerate(sells, 1):
            lines.append(f"{i}. **{s.get('label','')}** — {s.get('text','')}")
        lines.append("")
    else:
        lines += ["_（本次未绑定产品手册，跳过）_", ""]

    lines += ["## 二、按异议类型的应对话术", ""]
    if verified:
        by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for p in verified:
            by_theme[p.get("theme") or "其他"].append(p)
        for theme in sorted(by_theme, key=lambda t: -len(by_theme[t])):
            lines += [f"### {theme}", ""]
            for p in by_theme[theme][:6]:
                lines += [
                    f"**客户**：{p.get('objection') or '（开场）'}",
                    "",
                    f"**这样答**：",
                    "",
                    f"> {p.get('phrase','')}",
                    "",
                    f"<sub>实战验证：客户购买信号 +{p.get('signal_lift')}（`{p.get('persona_name')}` 第 {p.get('turn_idx')} 轮）</sub>",
                    "",
                ]
    else:
        lines += ["_（本次没有话术通过验证门槛，详见 `excellent_phrases.md` 的筛选漏斗）_", ""]

    lines += ["## 三、踩过的坑", ""]
    failed = Counter(s for m in metrics for s in m.get("failed_strategies") or [])
    if failed:
        for s, n in failed.most_common(12):
            lines.append(f"- **{s}** —— 在 {n} 场里被判定为失效")
    else:
        lines.append("_（复盘未产出失效策略记录）_")
    lines.append("")

    lines += ["## 四、明令禁止", "", "以下内容在模拟中被事实护栏拦下过，一线不许说：", ""]
    if guard_examples:
        for g in guard_examples[:15]:
            lines.append(f"- {g}")
    else:
        lines.append("_（本次没有触发护栏改写）_")
    lines += [
        "",
        "> 判断标准很简单：**产品手册里没写的具体数字，一个都不许说。**",
        "> 需要给客户确切数字时，当场打开官网查给他看。",
        "",
    ]
    return "\n".join(lines)


def _exec_summary_md(
    ctx: RunContext,
    metrics: list[dict[str, Any]],
    phrases: list[dict[str, Any]],
    quality_mode: str,
) -> str:
    man = ctx.manifest
    done = ctx.done_personas()
    failed = ctx.failed_personas()
    verified = [p for p in phrases if p.get("source") == "验证"]
    outcomes = Counter(m["outcome"] for m in metrics)

    lines = [
        f"# 执行摘要 · {ctx.run_id}",
        "",
        ("> ⚠️ **本次是 dry-run**：没有调用真实模型，所有内容为占位数据，"
         "仅用于验证产出链路。不要据此下任何结论。\n" if ctx.dry_run else ""),
        "## 跑了什么",
        "",
        "| 项 | 值 |",
        "|----|-----|",
        f"| 产品手册 | {man.get('source_handbook') or '（未绑定）'} |",
        f"| 话题 | {man.get('topic') or '（未指定）'} |",
        f"| 开始时间 | {man.get('created_at', '-')} |",
        f"| 续跑次数 | {man.get('resume_count', 0)} |",
        f"| 完成会话 | **{len(done)}** |",
        f"| 失败会话 | {len(failed)} |",
        f"| 质量分析模式 | {quality_mode} |",
        "",
    ]

    if metrics:
        scored = [m for m in metrics if m.get("judged")] or metrics
        avg_q = round(mean([m["quality_score"] for m in scored]), 2)
        avg_fab = round(mean([m["fabrication_rate"] for m in metrics]), 3)
        unscored_n = len(metrics) - len([m for m in metrics if m.get("judged")])
        lines += [
            "## 三个关键结论",
            "",
            f"1. **平均质量分 {avg_q}**"
            + (f"（{len(scored)} 场被裁判打过分，另 {unscored_n} 场提前结束未计入）" if unscored_n else "")
            + "，结果分布 "
            + "、".join(f"{k} {v} 场" for k, v in outcomes.most_common())
            + "。",
        ]
        dims = {
            k: round(mean([m["sales_score"].get(k, 0.0) for m in scored]), 2)
            for k in ("responsiveness", "specificity", "evidence_usage", "objection_handling", "closing_progress")
        }
        weakest = min(dims, key=lambda k: dims[k])
        cn = {
            "responsiveness": "响应度",
            "specificity": "具体性",
            "evidence_usage": "证据使用",
            "objection_handling": "异议处理",
            "closing_progress": "推进度",
        }[weakest]
        lines.append(f"2. **最弱维度是「{cn}」（{dims[weakest]}）**，下一轮训练优先补这里。")
        if avg_fab > 0:
            lines.append(
                f"3. **编造率 {avg_fab}** —— 平均每 {round(1 / avg_fab)} 轮就有一轮说出"
                "手册里没有依据的具体数字，被事实护栏改写。"
            )
        else:
            lines.append("3. **编造率 0** —— 本次没有任何一轮被事实护栏改写。")
        lines.append("")

    lines += [
        "## 产物索引",
        "",
        "| 文件 | 说明 |",
        "|------|------|",
        "| [`RUN_LOG.md`](RUN_LOG.md) | 完整执行时间线 |",
        "| [`reports/excellent_phrases.md`](reports/excellent_phrases.md) "
        f"| 优秀话术库（实战验证 {len(verified)} 条） |",
        "| [`reports/quality_report.md`](reports/quality_report.md) | 话术质量分析报告 |",
        "| [`reports/cross_persona_comparison.md`](reports/cross_persona_comparison.md) | 跨人设横向对比 |",
        "| [`reports/training_guide.md`](reports/training_guide.md) | 可直接下发的培训手册 |",
    ]
    if (ctx.handbook_dir / "handbook.md").is_file():
        lines.append("| [`01_handbook/handbook.md`](01_handbook/handbook.md) | 产品手册解析结果 |")
    lines += [
        "| [`02_personas/personas.md`](02_personas/personas.md) | 参战人设花名册 |",
        "| `sessions/<人设>/dialogue.md` | 每个人设与销冠的完整对话 |",
        "| `sessions/<人设>/steps/` | 该场每个 agent 每一步的输入输出 |",
        "",
    ]

    if failed:
        lines += ["## 失败场次", "", "| 人设 | 错误 |", "|------|------|"]
        lines += [f"| `{pid}` | {err[:120]} |" for pid, err in failed]
        lines += [
            "",
            f"重跑补齐：`python run_all.py --resume {ctx.run_id}`",
            "",
        ]
    return "\n".join(lines)


def compose(ctx: RunContext, cfg: dict[str, Any]) -> None:
    tracer = Tracer(ctx, AGENT_KEY)

    quality = _read_json(ctx.reports_dir / "quality_scores.json", {})
    metrics = quality.get("sessions") or []
    quality_mode = quality.get("mode") or "(未运行)"
    if not metrics:
        # 10 号没跑或跑失败时，退回自己从会话现算，保证报告不空白
        tracer.log("没读到 quality_scores.json，改为直接从会话计算", level="warn")
        from importlib import import_module

        sys.path.insert(0, str(bootstrap.AGENT_ROOT / "10_quality_analyst"))
        mod = import_module("run")
        metrics = [mod._session_metrics(rec) for rec in load_sessions(ctx)]

    phrases = _read_jsonl(ctx.reports_dir / "excellent_phrases.jsonl")
    handbook = _read_json(ctx.handbook_dir / "handbook.json", {})

    guard_examples: list[str] = []
    for rec in load_sessions(ctx):
        for t in rec.sales_turns:
            g = (t.get("metadata") or {}).get("content_guard") or {}
            guard_examples.extend(g.get("warnings") or [])

    (ctx.reports_dir / "cross_persona_comparison.md").write_text(
        _cross_persona_md(metrics, ctx.dry_run), encoding="utf-8"
    )
    (ctx.reports_dir / "training_guide.md").write_text(
        _training_guide_md(handbook, phrases, metrics, guard_examples, ctx.dry_run),
        encoding="utf-8",
    )
    (ctx.root / "EXEC_SUMMARY.md").write_text(
        _exec_summary_md(ctx, metrics, phrases, quality_mode), encoding="utf-8"
    )

    tracer.step(
        "compose",
        title="报告汇总",
        summary={
            "会话数": len(metrics),
            "话术条数": len(phrases),
            "护栏改写记录": len(guard_examples),
            "质量分析模式": quality_mode,
        },
        output_md=(
            "- `reports/cross_persona_comparison.md`\n"
            "- `reports/training_guide.md`\n"
            "- `EXEC_SUMMARY.md`"
        ),
    )
    ctx.set_stage(AGENT_KEY, "done", reports=3)
    tracer.log("三份报告写出完成，入口看 `EXEC_SUMMARY.md`", level="ok")


def main() -> int:
    ap = argparse.ArgumentParser(description="汇总所有环节产物为最终报告")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    bootstrap.init()
    import yaml

    cfg = yaml.safe_load((bootstrap.AGENT_ROOT / "config" / "pipeline.yaml").read_text("utf-8"))
    rid = args.run_id or RunContext.latest_run_id()
    if not rid:
        print("没有找到任何 run，先跑一次 run_all.py")
        return 2
    ctx = RunContext.load(rid)
    compose(ctx, cfg)
    print(f"[{AGENT_KEY}] run={rid}")
    print(f"  → {ctx.root / 'EXEC_SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
