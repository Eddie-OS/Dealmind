"""① 实测：验证 loader 市场字段修复后，销冠能本地化报价而非"查官网"。

只跑 1 个销冠 turn（含工具循环），不跑整场会话，省时省 token。
检查：
  - web_search 是否被锁定到该 persona 的本地域名（.my）
  - 销冠回复是否给出具体 RM 数字，而不是"查官网"敷衍
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.agents import generate_sales_turn
from src.persona.loader import persona_from_db_row
from src.schema import DialogueState, JudgeFeedback, SessionMemory, Turn
from src.storage import db as sdb
from src.utils import now_timestamp

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PERSONA_ID = 3  # 法汉 Farhan（马来西亚，关注 RM 套装价/竞品）
PRICE_QUESTION = (
    "Uncle，直接讲数字：MatePad 12X 加键盘加笔，套装在马来西亚卖多少 RM？"
    "另外 iPad Air 在马来这边大概多少钱？我要拿来对比，别叫我自己查。"
)


def main() -> None:
    with sdb.connection_scope() as conn:
        row = sdb.get_persona_by_id(conn, PERSONA_ID)
    persona = persona_from_db_row(row)

    print("=== persona 市场字段（修复后应非空）===")
    print("  name          =", persona.name)
    print("  country_code  =", persona.country_code)
    print("  currency      =", persona.currency)
    print("  market_domains=", persona.market_domains)
    print()

    state = DialogueState(
        session_id=f"smoke_{now_timestamp()}",
        topic="华为 MatePad 12X 平板销售模拟",
        product_text="华为 MatePad 12X 平板电脑（含星闪键盘、M-Pencil 套装）。",
        persona_profile=persona,
        round_idx=2,
        max_rounds=12,
        current_stage="异议处理与价格谈判",
        session_memory=SessionMemory.empty(),
        judge_feedback=JudgeFeedback.empty(),
    )
    persona_turn = Turn(idx=1, speaker="persona", content=PRICE_QUESTION)
    state.recent_history.append(persona_turn)
    state.full_history.append(persona_turn)

    print("=== 客户提问 ===")
    print(" ", PRICE_QUESTION)
    print("\n(销冠生成中，含 web_search 工具循环…)\n")

    turn = generate_sales_turn(state)

    print("=== 销冠回复 ===")
    print(turn.content)
    print()

    tool_calls = turn.metadata.get("tool_calls") or []
    print(f"=== 工具调用（{len(tool_calls)} 次）===")
    used_local_domain = False
    called_web = False
    for c in tool_calls:
        name = c.get("name")
        args = c.get("arguments") or {}
        data = c.get("result_data") or {}
        print(f"  - {name}  query={args.get('query')!r}")
        if name == "web_search":
            called_web = True
            cc = data.get("persona_country_code")
            results = data.get("results") or []
            urls = [r.get("url", "") for r in results][:3]
            print(f"      persona_country_code={cc}  urls={urls}")
            if cc == "MY" or any(".my" in (u or "") for u in urls):
                used_local_domain = True

    txt = turn.content or ""
    has_rm = ("RM" in txt) or ("MYR" in txt)
    deferred = "查官网" in txt or "官网给您看" in txt

    print("\n=== 判定 ===")
    print(f"  调用了 web_search：           {called_web}")
    print(f"  web_search 锁定本地(.my/MY)： {used_local_domain}")
    print(f"  回复含 RM/MYR 具体报价：       {has_rm}")
    print(f"  回复仍在'查官网'敷衍：         {deferred}")

    guard = turn.metadata.get("content_guard")
    if guard:
        print(f"  content_guard 改写：          {guard.get('warnings')}")


if __name__ == "__main__":
    main()
