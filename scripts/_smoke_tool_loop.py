"""Stage 14 端到端冒烟：销冠 Agent 启用工具后是否真的会调用并把结果写到 metadata.tool_calls。

跑法：
    python scripts/_smoke_tool_loop.py

成功标志：
    - 不抛异常
    - turn.metadata 里能看到 tool_calls 字段且至少 1 条
    - 打印的 content 不为空
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents import generate_sales_turn
from src.schema import DialogueState, PersonaProfile, SessionMemory, Turn
from src.storage.db import get_connection, init_schema, update_agent_skills_config


def main() -> None:
    # 1) 确保技能配置已启用 3 个 RAG 工具
    conn = get_connection()
    init_schema(conn)
    update_agent_skills_config(
        conn,
        enabled_tools=["search_product_kb", "search_enterprise_kb", "search_sales_cases"],
        max_tool_loops=2,
        tool_top_k_default=3,
    )
    conn.close()

    # 2) 构造一个最小可用 DialogueState
    persona_open = Turn(
        idx=0,
        speaker="persona",
        content="我刚带娃，预算 5000 左右，想给孩子上网课用的平板，MatePad 12X 和 iPad 比怎么选？",
        metadata={},
        created_at="2026-05-23T00:00:00+00:00",
    )
    persona = PersonaProfile(
        id="smoke_persona",
        name="新手宝妈·小赵",
        age=30,
    )
    state = DialogueState(
        session_id="smoke_s14",
        topic="向新手宝妈推荐华为 MatePad 12X",
        product_text="华为 MatePad 12X 主打学习场景，支持星闪笔与护眼屏。",
        persona_profile=persona,
        round_idx=1,
        max_rounds=8,
        current_stage="开场与需求暴露",
        recent_history=[persona_open],
        session_memory=SessionMemory.empty(),
        product_kb_id=1,
        enterprise_kb_id=2,
    )

    # 3) 调销冠 Agent
    turn = generate_sales_turn(state)

    # 4) 检查
    meta = turn.metadata or {}
    tool_calls = meta.get("tool_calls")
    tool_mode = meta.get("tool_mode")
    print("=== speaker:", turn.speaker, "| idx:", turn.idx)
    print("=== content (前 200 字):", (turn.content or "")[:200])
    print("=== tool_mode:", tool_mode)
    if tool_calls:
        print(f"=== tool_calls 命中 {len(tool_calls)} 次：")
        for i, tc in enumerate(tool_calls):
            args = json.dumps(tc.get("arguments", {}), ensure_ascii=False)
            print(f"  [{i}] loop={tc.get('loop')} name={tc.get('name')} ok={tc.get('ok')} args={args}")
            preview = (tc.get("result_preview") or "").replace("\n", " ")[:140]
            print(f"      result_preview={preview}")
    else:
        print("=== tool_calls 为空（可能 LLM 选择不调工具，或走了 fallback 老路径）")

    ok = bool(turn.content) and bool(tool_calls)
    print("=== smoke result:", "OK" if ok else "FAIL")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
