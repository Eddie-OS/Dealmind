"""演示提速开关：在「演示档（flash + 精简工具）」与「正常档（pro + 全工具）」间切换。

用法：
    python scripts/demo_speed_toggle.py demo      # 切到演示档（最快）
    python scripts/demo_speed_toggle.py restore   # 还原到正常档
    python scripts/demo_speed_toggle.py status     # 只看当前配置

演示档：销冠模型 deepseek-v4-flash、max_tool_loops=1、关闭 web_search（留本地 KB）。
正常档：销冠模型 deepseek-v4-pro、max_tool_loops=3、开启 web_search。
辅助链路（judge/memory/coach/分析）本就是 flash，不受影响。
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from src.storage.db import connection_scope

PROFILES = {
    "demo": {
        "model_name": "deepseek-v4-flash",
        "max_tool_loops": 1,
        "tools": ["search_product_kb", "search_enterprise_kb", "search_sales_cases"],
    },
    "restore": {
        "model_name": "deepseek-v4-pro",
        "max_tool_loops": 3,
        "tools": [
            "search_product_kb", "search_enterprise_kb",
            "search_sales_cases", "web_search",
        ],
    },
}


def _show(conn) -> None:
    prov = conn.execute(
        "SELECT model_name FROM llm_providers WHERE is_default=1"
    ).fetchone()
    sk = conn.execute(
        "SELECT enabled_tools_json, max_tool_loops FROM agent_skills_config WHERE id=1"
    ).fetchone()
    print(f"  销冠模型     : {prov['model_name']}")
    print(f"  max_tool_loops: {sk['max_tool_loops']}")
    print(f"  enabled_tools : {sk['enabled_tools_json']}")


def main() -> None:
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    with connection_scope() as conn:
        if action == "status":
            print("=== 当前配置 ===")
            _show(conn)
            return
        if action not in PROFILES:
            print(f"未知动作 {action!r}，可选：demo / restore / status")
            sys.exit(2)
        p = PROFILES[action]
        with conn:
            conn.execute(
                "UPDATE llm_providers SET model_name=? WHERE is_default=1",
                (p["model_name"],),
            )
            conn.execute(
                "UPDATE agent_skills_config SET enabled_tools_json=?, max_tool_loops=? WHERE id=1",
                (json.dumps(p["tools"], ensure_ascii=False), p["max_tool_loops"]),
            )
        label = "演示档（最快）" if action == "demo" else "正常档"
        print(f"=== 已切换到{label} ===")
        _show(conn)


if __name__ == "__main__":
    main()
