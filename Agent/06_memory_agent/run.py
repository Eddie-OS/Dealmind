"""06 · 会话记忆 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402

AGENT_KEY = "06_memory_agent"
EVENT_TYPES = ("memory_update",)


def render(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    mem = event.get("session_memory") or {}
    rnd = event.get("round_idx", 0)

    def _list(key: str) -> str:
        items = mem.get(key) or []
        return "\n".join(f"- {x}" for x in items) if items else "_（无）_"

    body = [
        f"**核心需求**：{mem.get('current_need') or '（未识别）'}",
        f"**预算边界**：{mem.get('budget_boundary') or '（未暴露）'}",
        f"**情绪状态**：{mem.get('emotional_state') or '（未判定）'}",
        f"**下一步建议**：{mem.get('next_best_action') or '（无）'}",
        "",
        "**未解决异议**",
        "",
        _list("main_objections"),
        "",
        "**不许重复**",
        "",
        _list("do_not_repeat"),
        "",
        "**提及竞品**",
        "",
        _list("mentioned_competitors"),
        "",
        "**决策约束**",
        "",
        _list("decision_constraints"),
    ]

    return {
        "name": f"r{rnd:02d}",
        "title": f"客户画像 · 第 {rnd} 轮刷新",
        "summary": {
            "异议数": len(mem.get("main_objections") or []),
            "禁重复条目": len(mem.get("do_not_repeat") or []),
            "提及竞品": len(mem.get("mentioned_competitors") or []),
            "情绪": mem.get("emotional_state") or "-",
        },
        "output_md": "\n".join(body),
    }


def selftest(dry_run: bool = False) -> int:
    bootstrap.init(dry_run=dry_run or None)
    from shared.fixtures import demo_state
    from src.memory import update_session_memory

    mem = update_session_memory(demo_state())
    print(f"[{AGENT_KEY}] 核心需求：{mem.current_need}")
    print(f"异议：{mem.main_objections}")
    print(f"禁重复：{mem.do_not_repeat}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="会话记忆 Agent")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.selftest:
        print(f"{AGENT_KEY} 是会话内 agent，由 00_orchestrator 驱动。")
        print("单独验证请加 --selftest（详见同目录 AGENT.md）。")
        sys.exit(0)
    sys.exit(selftest(a.dry_run))
