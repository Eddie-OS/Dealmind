"""07 · 复盘教练 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402

AGENT_KEY = "07_coach_agent"
EVENT_TYPES = ("coach_review",)


def render(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    r = event.get("coach_review") or {}

    body = [
        f"**结果分析**：{r.get('outcome_analysis') or '（无）'}",
        "",
        f"**人设洞察**：{r.get('persona_insight') or '（无）'}",
        "",
        f"**难度评分**：{r.get('difficulty_rating', 0)}/10 — {r.get('difficulty_reason') or ''}",
        "",
        "## 有效策略",
        "",
    ]
    for w in r.get("what_worked") or []:
        body.append(f"- 第 {w.get('round','?')} 轮 [{w.get('strategy','')}]：{w.get('why_effective','')}")
        if w.get("evidence"):
            body.append(f"  > {w['evidence']}")
    if not (r.get("what_worked")):
        body.append("_（无）_")

    body += ["", "## 失效操作", ""]
    for f in r.get("what_failed") or []:
        body.append(f"- 第 {f.get('round','?')} 轮 [{f.get('strategy','')}]：{f.get('why_failed','')}")
        if f.get("evidence"):
            body.append(f"  > {f['evidence']}")
    if not (r.get("what_failed")):
        body.append("_（无）_")

    body += ["", "## 可写入手册的经验", ""]
    body += [f"{i}. {x}" for i, x in enumerate(r.get("key_lessons") or [], 1)] or ["_（无）_"]

    body += ["", "## 更优话术模板", ""]
    for rb in r.get("suggested_rebuttals") or []:
        body.append(f"- **{rb.get('objection','')}**")
        body.append(f"  > {rb.get('rebuttal_template','')}")
    if not (r.get("suggested_rebuttals")):
        body.append("_（无）_")

    body += ["", "## 可复用策略", ""]
    for t in r.get("reusable_tactics") or []:
        body.append(f"- **{t.get('name','')}**（触发：{t.get('condition','')}）")
        body.append(f"  > {t.get('example','')}")
    if not (r.get("reusable_tactics")):
        body.append("_（无）_")

    return {
        "name": "review",
        "title": "会后复盘",
        "summary": {
            "难度": f"{r.get('difficulty_rating', 0)}/10",
            "有效策略": len(r.get("what_worked") or []),
            "失效操作": len(r.get("what_failed") or []),
            "经验条目": len(r.get("key_lessons") or []),
            "话术模板": len(r.get("suggested_rebuttals") or []),
            "可复用策略": len(r.get("reusable_tactics") or []),
        },
        "output_md": "\n".join(body),
    }


def rerun_for_session(session_dir: Path, dry_run: bool = False) -> int:
    """对一场已经跑完的会话重新复盘。用于复盘 prompt 改了以后回补。"""
    bootstrap.init(dry_run=dry_run or None)
    log_path = session_dir / "session_log.json"
    if not log_path.is_file():
        print(f"找不到 {log_path}")
        return 2

    from src.coach import run_coach
    from src.schema import DialogueState, PersonaProfile, Turn

    data = json.loads(log_path.read_text(encoding="utf-8"))
    history = [Turn.model_validate(t) for t in data.get("full_history") or []]
    state = DialogueState(
        session_id=data.get("session_id", "rerun"),
        topic=data.get("topic", ""),
        product_text="",
        persona_profile=PersonaProfile.model_validate(data.get("persona") or {}),
        round_idx=int(data.get("total_rounds") or len(history)),
        outcome=data.get("outcome", ""),
        recent_history=history[-6:],
        full_history=history,
    )
    review = run_coach(state)
    out = session_dir / "coach_review_rerun.json"
    out.write_text(
        json.dumps(review.model_dump() if review else {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[{AGENT_KEY}] 重新复盘完成 → {out}")
    return 0


def selftest(dry_run: bool = False) -> int:
    bootstrap.init(dry_run=dry_run or None)
    from shared.fixtures import demo_state
    from src.coach import run_coach

    state = demo_state()
    state.outcome = "TIMEOUT"
    review = run_coach(state)
    print(f"[{AGENT_KEY}] 难度 {review.difficulty_rating}/10")
    print(f"经验条目 {len(review.key_lessons)} 条，话术模板 {len(review.suggested_rebuttals)} 条")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="复盘教练 Agent")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--session", default=None, help="对指定会话目录重跑复盘")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.session:
        sys.exit(rerun_for_session(Path(a.session), a.dry_run))
    if not a.selftest:
        print(f"{AGENT_KEY} 是会话内 agent，由 00_orchestrator 驱动。")
        print("单独验证请加 --selftest，对已有会话重跑请加 --session（详见 AGENT.md）。")
        sys.exit(0)
    sys.exit(selftest(a.dry_run))
