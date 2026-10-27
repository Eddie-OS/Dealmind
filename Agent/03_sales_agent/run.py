"""03 · 销冠 Agent。契约见同目录 AGENT.md。

会话内 agent 的统一形态：
    render(event)  —— 把主循环抛出的事件渲染成这一步的 MD，由 orchestrator 调用
    selftest()     —— 单独跑一轮，用于调 prompt 时快速看效果
真正的生成逻辑在 shared/vendor/src/agents.py，这里不复制它。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402

AGENT_KEY = "03_sales_agent"
EVENT_TYPES = ("sales_turn",)


def render(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    turn = event.get("turn") or {}
    # 上游把 SalesStrategy 的字段直接铺平进 metadata，没有 "strategy" 这一层
    meta = turn.get("metadata") or {}
    guard = meta.get("content_guard") or {}
    rag = meta.get("rag_hits") or {}
    hb = meta.get("handbook_inject") or {}
    rnd = event.get("round_idx", 0)

    hits = list(rag.get("product") or []) + list(rag.get("enterprise") or [])
    body = [f"> {turn.get('content', '')}", ""]
    if hits:
        body += ["**本轮知识命中**", ""]
        for h in hits[:5]:
            m = h.get("metadata") or {}
            body.append(f"- `{m.get('filename', '?')}` / {m.get('section') or '(无小节)'}")
        body.append("")
    if guard.get("warnings"):
        body += ["**事实护栏改写**", ""]
        body += [f"- {w}" for w in guard["warnings"]]
        body.append("")

    return {
        "name": f"r{rnd:02d}",
        "title": f"销冠 · 第 {rnd} 轮",
        "summary": {
            "阶段": meta.get("stage_id") or event.get("stage") or "-",
            "剧本动作": meta.get("playbook_action") or "-",
            "本轮意图": meta.get("intent") or "-",
            "引用手册": meta.get("used_handbook"),
            "手册块字数": hb.get("handbook_block_len", 0),
            "护栏改写": bool(guard.get("rewritten")),
            "字数": len(turn.get("content") or ""),
        },
        "output_md": "\n".join(body),
    }


def selftest(dry_run: bool = False) -> int:
    bootstrap.init(dry_run=dry_run or None)
    from shared.fixtures import demo_state
    from src.agents import generate_sales_turn

    turn = generate_sales_turn(demo_state())
    meta = turn.metadata or {}
    print(f"[{AGENT_KEY}] 销冠发言：\n{turn.content}\n")
    print(
        f"意图={meta.get('intent')}  剧本动作={meta.get('playbook_action')}  "
        f"引用手册={meta.get('used_handbook')}"
    )
    guard = (turn.metadata or {}).get("content_guard")
    if guard:
        print(f"护栏改写 {len(guard.get('warnings', []))} 处")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="销冠 Agent")
    ap.add_argument("--selftest", action="store_true", help="用固定上下文生成一轮发言")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.selftest:
        print(f"{AGENT_KEY} 是会话内 agent，由 00_orchestrator 驱动。")
        print("单独验证请加 --selftest（详见同目录 AGENT.md）。")
        sys.exit(0)
    sys.exit(selftest(a.dry_run))
