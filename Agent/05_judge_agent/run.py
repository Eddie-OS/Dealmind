"""05 · 会中裁判 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402

AGENT_KEY = "05_judge_agent"
EVENT_TYPES = ("judge_feedback", "stage_change")


def render(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    rnd = event.get("round_idx", 0)

    if "judge_feedback" not in event:
        # stage_change 事件
        direction = event.get("direction", "stay")
        arrow = {"advance": "→", "regress": "↩", "stay": "="}.get(direction, "·")
        return {
            "name": f"stage_r{rnd:02d}",
            "title": f"阶段变更 · 第 {rnd} 轮",
            "summary": {
                "变更": f"{event.get('from_stage_id','?')} {arrow} {event.get('to_stage_id','?')}",
                "方向": direction,
                "触发方": event.get("trigger", "-"),
            },
            "output_md": f"**原因**：{event.get('reason') or '（未给出）'}",
        }

    fb = event.get("judge_feedback") or {}
    score = fb.get("sales_score") or {}
    st = fb.get("stage_transition") or {}

    body = [
        "**给客户的指令**",
        "",
        f"> {fb.get('persona_instruction') or '（无）'}",
        "",
        "**给销冠的指令**",
        "",
        f"> {fb.get('sales_instruction') or '（无）'}",
        "",
        f"**判定理由**：{fb.get('reason') or '（无）'}",
    ]
    if st.get("fail_reasons"):
        body += ["", "**未通过项**", ""] + [f"- {r}" for r in st["fail_reasons"]]
    if fb.get("avoid_repeating"):
        body += ["", "**避免重复**", ""] + [f"- {r}" for r in fb["avoid_repeating"]]

    return {
        "name": f"r{rnd:02d}",
        "title": f"裁判 · 第 {rnd} 轮",
        "summary": {
            "质量分": fb.get("dialogue_quality_score", 0),
            "响应度": score.get("responsiveness", 0),
            "具体性": score.get("specificity", 0),
            "证据使用": score.get("evidence_usage", 0),
            "异议处理": score.get("objection_handling", 0),
            "推进度": score.get("closing_progress", 0),
            "阶段": f"{fb.get('current_stage','-')} → {fb.get('next_stage','-')}",
            "方向": st.get("direction", "-"),
            "终止信号": fb.get("end_status", "CONTINUE"),
        },
        "output_md": "\n".join(body),
    }


def selftest(dry_run: bool = False) -> int:
    bootstrap.init(dry_run=dry_run or None)
    from shared.fixtures import demo_state
    from src.judge import judge_dialogue

    state = demo_state()
    fb = judge_dialogue(state)
    print(f"[{AGENT_KEY}] 质量分 ={fb.dialogue_quality_score} 阶段 {fb.current_stage} → {fb.next_stage}")
    print(f"给销冠：{fb.sales_instruction}")
    print(f"给客户：{fb.persona_instruction}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="会中裁判 Agent")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.selftest:
        print(f"{AGENT_KEY} 是会话内 agent，由 00_orchestrator 驱动。")
        print("单独验证请加 --selftest（详见同目录 AGENT.md）。")
        sys.exit(0)
    sys.exit(selftest(a.dry_run))
