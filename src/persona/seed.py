"""Persona 启动预填：首次启动时把 44 个 panel persona 导入 DB。

策略（按 simplicity first）：
- 首启 personas 表空 → 用 parser 解析 panel JSON → bulk_create_personas
- 全部以默认 0.5 全填的 pressure_profile 入库、pressure_extracted=False
- LLM 抽参不在 startup 同步执行（44×4s ≈ 3 分钟阻塞且易触发限流），
  改为用户在 PersonaLibrary 详情抽屉手动点「重新抽取」按需触发
- 已有数据不重复导入（幂等）
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from src.config import PROJECT_ROOT
from src.persona.parser import PersonaParseError, parse_persona_file
from src.storage.db import bulk_create_personas, count_personas

logger = logging.getLogger(__name__)


_PANEL_JSON = PROJECT_ROOT / "训练文件" / "2.1 消费者人设.json"


def seed_built_in_personas(
    conn: sqlite3.Connection,
    *,
    source_path: Path | None = None,
    force: bool = False,
) -> dict[str, int]:
    """若 personas 表为空，导入 panel JSON 中的全部 persona。

    Args:
        conn: 已打开的 SQLite 连接。
        source_path: 自定义 JSON 路径（默认 训练文件/2.1 消费者人设.json）。
        force: True 时不检查表是否为空，直接追加导入。

    Returns:
        {"existing": <已有条数>, "imported": <本次导入条数>}
    """
    existing = count_personas(conn)
    if existing > 0 and not force:
        logger.info("personas 表已有 %d 条，跳过预填", existing)
        return {"existing": existing, "imported": 0}

    path = source_path or _PANEL_JSON
    if not path.exists():
        logger.warning("Panel 人设文件不存在: %s，跳过预填", path)
        return {"existing": existing, "imported": 0}

    try:
        items = parse_persona_file(path)
    except PersonaParseError as exc:
        logger.error("解析 panel 人设失败: %s", exc)
        return {"existing": existing, "imported": 0}

    if not items:
        logger.warning("Panel 人设文件解析后为空: %s", path)
        return {"existing": existing, "imported": 0}

    ids = bulk_create_personas(conn, items)
    logger.info("已预填 %d 条 panel persona（来源: %s）", len(ids), path.name)
    return {"existing": existing, "imported": len(ids)}
