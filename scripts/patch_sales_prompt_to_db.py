"""把 prompts/sales_prompt.md 的最新内容同步到 agent_profiles.sales.system_prompt。

business_stages v0.2 更新引入了 stage_playbook_block / allowed_playbook_actions_csv 等
新占位符，UI 上保存的 sales_prompt 是旧版，直接跑会缺占位符 → 必须 patch。

幂等：
- 文件内容与 DB 完全一致时不做任何 UPDATE，也不 bump 版本。
- 内容不一致时执行 update_agent_profile(... bump_version=True)，并打印版本号。
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.storage.db import (
        get_agent_profile,
        get_connection,
        update_agent_profile,
    )

    prompt_path = project_root / "prompts" / "sales_prompt.md"
    if not prompt_path.exists():
        print(f"[ERROR] 文件不存在: {prompt_path}")
        return 1

    new_prompt = prompt_path.read_text(encoding="utf-8")

    conn = get_connection()
    try:
        cur = get_agent_profile(conn, "sales")
        if not cur:
            print("[ERROR] agent_profiles.sales 不存在（应已被 _seed_sales_profile 自动创建）")
            return 1

        old_prompt = cur.get("system_prompt") or ""
        if old_prompt == new_prompt:
            print("[OK] DB 中 sales.system_prompt 已是最新，跳过。")
            return 0

        updated = update_agent_profile(
            conn,
            "sales",
            system_prompt=new_prompt,
            bump_version=True,
            version_comment="v0.3 sync (v10.1/10.2 stage required_trigger + gate_condition + sales logic/constraints + stage_window/budget_hint)",
        )
        print(
            f"[OK] 已同步 sales.system_prompt; "
            f"旧={len(old_prompt)} chars, 新={len(new_prompt)} chars, "
            f"version={updated.get('version')}"
        )
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
