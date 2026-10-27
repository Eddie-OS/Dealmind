"""04 · 客户人设 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402

AGENT_KEY = "04_customer_agent"
EVENT_TYPES = ("persona_turn",)


def render(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    turn = event.get("turn") or {}
    # 上游把 HiddenState 的字段直接铺平进 metadata，没有 "hidden_state" 这一层
    hidden = turn.get("metadata") or {}
    rnd = event.get("round_idx", 0)

    body = [f"> {turn.get('content', '')}", ""]
    if hidden.get("walk_away_reason"):
        body += [f"**离场原因**：{hidden['walk_away_reason']}", ""]

    return {
        "name": f"r{rnd:02d}",
        "title": f"客户 · 第 {rnd} 轮",
        "summary": {
            "阶段": event.get("stage") or "-",
            "意图": hidden.get("intent") or "-",
            "态度": hidden.get("attitude") or "-",
            "购买信号": hidden.get("purchase_signal", 0.0),
            "状态": hidden.get("status") or "CONTINUE",
            "字数": len(turn.get("content") or ""),
        },
        "output_md": "\n".join(body),
    }


def selftest(dry_run: bool = False) -> int:
    bootstrap.init(dry_run=dry_run or None)
    from shared.fixtures import demo_state
    from src.agents import generate_persona_turn

    turn = generate_persona_turn(demo_state())
    meta = turn.metadata or {}
    print(f"[{AGENT_KEY}] 客户发言：\n{turn.content}\n")
    print(
        f"意图={meta.get('intent')}  态度={meta.get('attitude')}  "
        f"购买信号={meta.get('purchase_signal')}  状态={meta.get('status')}"
    )
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="客户人设 Agent")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.selftest:
        print(f"{AGENT_KEY} 是会话内 agent，由 00_orchestrator 驱动。")
        print("单独验证请加 --selftest（详见同目录 AGENT.md）。")
        sys.exit(0)
    sys.exit(selftest(a.dry_run))
