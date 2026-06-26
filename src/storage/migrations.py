"""数据迁移：把 .env 里的 LLM 配置一次性导入 llm_providers 表。

幂等规则：
- 仅当 llm_providers 表 **完全为空** 时才迁移；
- 不在每次启动都重写，避免覆盖用户在 UI 里改过的值。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from src.config import Settings, load_settings
from src.storage.db import create_provider


_BASE_URL_TO_TYPE: list[tuple[str, str]] = [
    ("deepseek.com",      "deepseek"),
    ("api.openai.com",    "openai"),
    ("dashscope.aliyuncs", "qwen"),
    ("moonshot.cn",       "moonshot"),
    ("bigmodel.cn",       "zhipu"),
]


def infer_provider_type(base_url: str) -> str:
    """按 base_url 关键字推断 provider_type；都不匹配返回 'custom'。"""
    low = (base_url or "").lower()
    for keyword, ptype in _BASE_URL_TO_TYPE:
        if keyword in low:
            return ptype
    return "custom"


def migrate_env_to_db(
    conn: sqlite3.Connection,
    settings: Optional[Settings] = None,
) -> Optional[int]:
    """若 llm_providers 表空且 .env 有 OPENAI_API_KEY，则插入一条 default。

    Args:
        conn: 已 init_schema 的连接。
        settings: 测试时可注入；正常路径自动 load_settings()。

    Returns:
        新插入行的 id；表已有数据 / .env 无 key 时返回 None。
    """
    row = conn.execute("SELECT COUNT(*) AS n FROM llm_providers").fetchone()
    if row["n"] > 0:
        return None

    if settings is None:
        try:
            settings = load_settings()
        except RuntimeError:
            return None

    if not settings.api_key:
        return None

    return create_provider(
        conn,
        name="default",
        provider_type=infer_provider_type(settings.base_url),
        base_url=settings.base_url,
        api_key=settings.api_key,
        model_name=settings.model_name,
        temperature=settings.temperature,
        max_retries=settings.max_retries,
        is_active=True,
        is_default=True,
    )
