"""08 · 事实护栏 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402

AGENT_KEY = "08_content_guard"
# 护栏没有独立事件，它搭 sales_turn 的车，只在真的改写了才落文件。
EVENT_TYPES = ("sales_turn",)


def render(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    turn = event.get("turn") or {}
    guard = (turn.get("metadata") or {}).get("content_guard") or {}
    if not guard.get("rewritten"):
        return None

    rnd = event.get("round_idx", 0)
    warnings = guard.get("warnings") or []
    body = ["**改写清单**", ""] + [f"- {w}" for w in warnings]
    body += ["", "**改写后的最终发言**", "", f"> {turn.get('content', '')}"]

    return {
        "name": f"r{rnd:02d}",
        "title": f"事实护栏拦截 · 第 {rnd} 轮",
        "summary": {"改写处数": len(warnings), "阶段": event.get("stage") or "-"},
        "output_md": "\n".join(body),
    }


def check_text(text: str, dry_run: bool = False) -> int:
    """对一段文本单独跑护栏。用最近一次 run 的手册作为证据源。

    这里刻意读渲染后的 handbook.md 而不是 handbook.json —— 对话里注入给
    销冠的就是渲染后的文本，拿 JSON 原始 dump 当证据会宽松得多
    （结构键名和 id 里的数字都会被当成"手册里有这个数"）。
    """
    bootstrap.init(dry_run=dry_run or None)

    from shared.runctx import RunContext
    from src.content_guard import verify_and_rewrite

    handbook_text = ""
    rid = RunContext.latest_run_id()
    if rid:
        hb_path = bootstrap.AGENT_ROOT / "runs" / rid / "01_handbook" / "handbook.md"
        if hb_path.is_file():
            handbook_text = hb_path.read_text(encoding="utf-8")

    new_text, warnings = verify_and_rewrite(
        text, fact_card=None, handbook_text=handbook_text or None
    )
    print(f"[{AGENT_KEY}] 证据源：{'最近一次 run 的手册' if handbook_text else '无（全部数字都会被改写）'}")
    print(f"改写 {len(warnings)} 处")
    for w in warnings:
        print(f"  - {w}")
    print(f"\n原文：{text}")
    print(f"改后：{new_text}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="事实护栏 Agent")
    ap.add_argument("--text", default=None, help="对一段销冠话术单独跑护栏")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.text:
        sys.exit(check_text(a.text, a.dry_run))
    print(f"{AGENT_KEY} 挂在销冠出口上，由 00_orchestrator 驱动。")
    print('单独验证请加 --text "……"（详见同目录 AGENT.md）。')
    sys.exit(0)
