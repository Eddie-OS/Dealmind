"""把 agent_profiles.sales.system_prompt 清空，让系统重新走文件版 prompt。

历史中 UI 可能已经把 system_prompt 写到 DB（agent_profiles 表），
那 load_prompt('sales_prompt') 就走 DB 而非文件。我们这次重写 prompts/sales_prompt.md
后，必须清掉 DB 那一份才能让新规则生效。
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.storage import db as sdb  # noqa: E402

with sdb.connection_scope() as conn:
    row = sdb.get_agent_profile(conn, "sales")
    if not row:
        print("agent_profiles.sales 不存在，无需清理 — 系统会直接读文件。")
    else:
        sp = (row.get("system_prompt") or "").strip()
        print(f"当前 DB 中 sales.system_prompt 长度: {len(sp)} 字符")
        if not sp:
            print("已经是空，无需清理。")
        else:
            print("清空中…")
            conn.execute(
                "UPDATE agent_profiles SET system_prompt = '' WHERE name = 'sales'"
            )
            conn.commit()
            print("已清空。下次销售启动将走 prompts/sales_prompt.md 文件版。")
