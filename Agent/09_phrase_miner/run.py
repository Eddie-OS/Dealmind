"""09 · 优秀话术提炼 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402
from shared.runctx import RunContext  # noqa: E402
from shared.session_reader import SessionRecord, load_sessions  # noqa: E402
from shared.trace import Tracer  # noqa: E402

AGENT_KEY = "09_phrase_miner"
_MIN_CHARS = 30
_UNCLASSIFIED = "其他 / 未归类"


def _theme_of(text: str) -> str:
    from src.analyzers.objection_cluster import classify_theme

    return classify_theme(text or "") or _UNCLASSIFIED


def _mine_session(rec: SessionRecord, min_score: float) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """返回 (候选话术, 各道筛子刷掉的条数)。"""
    rejects = defaultdict(int)
    picked: list[dict[str, Any]] = []

    if not rec.judged:
        rejects["整场未被裁判打分（提前结束）"] = len(rec.sales_turns)
        return [], dict(rejects)
    if rec.quality_score < min_score:
        rejects["整场质量分不达标"] = len(rec.sales_turns)
        return [], dict(rejects)

    for turn in rec.sales_turns:
        idx = int(turn.get("idx") or 0)
        content = (turn.get("content") or "").strip()
        meta = turn.get("metadata") or {}

        if len(content) < _MIN_CHARS:
            rejects["过短"] += 1
            continue
        if (meta.get("content_guard") or {}).get("rewritten"):
            rejects["被护栏改写"] += 1
            continue
        if not meta.get("used_handbook"):
            rejects["未引用手册"] += 1
            continue

        before = rec.signal_before(idx)
        after = rec.signal_at(idx)
        if before is None or after is None:
            rejects["缺少前后购买信号"] += 1
            continue
        lift = round(after - before, 3)
        if lift <= 0:
            rejects["客户信号未提升"] += 1
            continue

        objection = rec.customer_line_before(idx)
        picked.append(
            {
                "theme": _theme_of(objection),
                "objection": objection,
                "phrase": content,
                "signal_before": before,
                "signal_after": after,
                "signal_lift": lift,
                "persona_id": rec.persona_id,
                "persona_name": rec.persona_name,
                "turn_idx": idx,
                "stage": meta.get("stage_id") or "",
                "playbook_action": meta.get("playbook_action") or "",
                "session_quality": rec.quality_score,
                "source": "验证",
            }
        )
    return picked, dict(rejects)


def _collect_coach_templates(sessions: list[SessionRecord]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in sessions:
        for rb in rec.coach.get("suggested_rebuttals") or []:
            objection = str(rb.get("objection") or "").strip()
            template = str(rb.get("rebuttal_template") or "").strip()
            if not template:
                continue
            out.append(
                {
                    "theme": _theme_of(objection),
                    "objection": objection,
                    "phrase": template,
                    "persona_id": rec.persona_id,
                    "persona_name": rec.persona_name,
                    "source": "教练建议",
                }
            )
    return out


def _render_md(
    verified: list[dict[str, Any]],
    templates: list[dict[str, Any]],
    rejects: dict[str, int],
    top: int,
    min_score: float,
    session_count: int,
) -> str:
    by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in verified[:top]:
        by_theme[item["theme"]].append(item)

    lines = [
        "# 优秀话术库",
        "",
        f"- 素材来源：本次 run 的 **{session_count}** 场对练",
        f"- 实战验证话术：**{len(verified)}** 条（下方展示前 {min(top, len(verified))} 条）",
        f"- 教练建议模板：{len(templates)} 条（未经对话验证，单独成节）",
        f"- 入选门槛：整场质量分 ≥ {min_score}、未被护栏改写、引用手册、客户购买信号上升",
        "",
        "> 排序依据是**客户购买信号的提升幅度**，不是话术本身好不好听。",
        "",
    ]

    if not verified:
        lines += [
            "## 没有话术入选",
            "",
            "所有候选都被筛掉了。各道筛子的刷除数见下方「筛选漏斗」，",
            "最常见的原因是 dry-run 数据没有真实的购买信号变化。",
            "",
        ]

    for theme in sorted(by_theme, key=lambda t: -len(by_theme[t])):
        items = by_theme[theme]
        lines += [f"## {theme}（{len(items)} 条）", ""]
        for i, it in enumerate(items, 1):
            lines += [
                f"### {i}. 信号 {it['signal_before']} → {it['signal_after']}（+{it['signal_lift']}）",
                "",
                f"**客户说**：{it['objection'] or '（开场，无前置异议）'}",
                "",
                f"**销冠答**：",
                "",
                f"> {it['phrase']}",
                "",
                f"<sub>出处：`{it['persona_name']}` 第 {it['turn_idx']} 轮 · 阶段 {it['stage'] or '-'}"
                f" · 剧本动作 {it['playbook_action'] or '-'} · 整场质量分 {it['session_quality']}</sub>",
                "",
            ]

    if templates:
        tpl_by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for t in templates:
            tpl_by_theme[t["theme"]].append(t)
        lines += [
            "---",
            "",
            "## 教练建议模板（未经对话验证）",
            "",
            "这些是复盘教练针对遇到的异议提出的更优说法，**没有在真实对话里跑过**，",
            "拿去用之前建议先在下一轮全量对抗里验证一遍。",
            "",
        ]
        for theme in sorted(tpl_by_theme, key=lambda t: -len(tpl_by_theme[t])):
            lines += [f"### {theme}", ""]
            for t in tpl_by_theme[theme]:
                lines += [
                    f"- **异议**：{t['objection'] or '（未标注）'}",
                    f"  > {t['phrase']}",
                    f"  <sub>来自 `{t['persona_name']}` 场次的复盘</sub>",
                    "",
                ]

    lines += ["---", "", "## 筛选漏斗", "", "| 刷除原因 | 条数 |", "|----------|------|"]
    for reason, n in sorted(rejects.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {reason} | {n} |")
    lines.append("")
    return "\n".join(lines)


def mine(ctx: RunContext, cfg: dict[str, Any]) -> dict[str, Any]:
    tracer = Tracer(ctx, AGENT_KEY)
    rcfg = cfg.get("reports") or {}
    top = int(rcfg.get("top_phrases") or 40)
    min_score = float(rcfg.get("min_turn_score") or 6.5)

    sessions = load_sessions(ctx)
    tracer.log(f"读取 {len(sessions)} 场会话")

    verified: list[dict[str, Any]] = []
    rejects: dict[str, int] = defaultdict(int)
    for rec in sessions:
        picked, rej = _mine_session(rec, min_score)
        verified.extend(picked)
        for k, v in rej.items():
            rejects[k] += v
        tracer.step(
            f"mine_{rec.persona_id}",
            title=f"提炼 · {rec.persona_name}",
            summary={
                "整场质量分": rec.quality_score,
                "销冠轮数": len(rec.sales_turns),
                "入选": len(picked),
                "护栏改写轮数": rec.guard_rewrites,
            },
            output_md="\n".join(f"- (+{p['signal_lift']}) {p['phrase'][:80]}…" for p in picked)
            or "_（本场无入选）_",
        )

    verified.sort(key=lambda x: (-x["signal_lift"], -x["session_quality"]))
    templates = _collect_coach_templates(sessions)

    md = _render_md(verified, templates, dict(rejects), top, min_score, len(sessions))
    (ctx.reports_dir / "excellent_phrases.md").write_text(md, encoding="utf-8")
    with (ctx.reports_dir / "excellent_phrases.jsonl").open("w", encoding="utf-8") as fh:
        for item in verified + templates:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    ctx.set_stage(AGENT_KEY, "done", verified=len(verified), templates=len(templates))
    tracer.log(
        f"实战验证话术 **{len(verified)}** 条，教练模板 {len(templates)} 条 → `reports/excellent_phrases.md`",
        level="ok",
    )
    return {"verified": verified, "templates": templates}


def main() -> int:
    ap = argparse.ArgumentParser(description="从已完成会话提炼优秀话术")
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
    res = mine(ctx, cfg)
    print(f"[{AGENT_KEY}] run={rid} 验证话术 {len(res['verified'])} 条")
    print(f"  → {ctx.reports_dir / 'excellent_phrases.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
