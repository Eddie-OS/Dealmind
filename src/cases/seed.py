"""Stage 11：训练文件预填（preset 案例）。

启动时若 sales_cases 表为空，则解析 训练文件/ 下 4 个区域销冠 .pptx：
- Country R_Arman Grigorian_MatePad 12X.pptx
- LATAM_MEXICO_MATEPAD 12X_ALBERTO DANIEL CRUZ.pptx
- MEA - UAE - Matepad 12X - Jeofrey B Mendviel.pptx
- MEA - UAE - Matepad 12X - Yassin Ahmed.pptx

策略：每个文件落 1 条案例（按文件名抽 region/作者作为元数据，
全部幻灯片文本拼为 raw_content 便于全文搜索）。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.storage import db as dbm

logger = logging.getLogger(__name__)

TRAINING_DIR = PROJECT_ROOT / "训练文件"

# (region_tag, file_name_substring)
# 用子串匹配兼容文件名带空格 / 大小写差异；命中第一个即可
PRESET_FILES: list[tuple[str, str]] = [
    ("Country R",   "country r"),
    ("LATAM",       "latam"),
    ("MEA UAE",     "jeofrey"),
    ("MEA UAE",     "yassin"),
]


def _find_pptx_files() -> list[tuple[str, Path]]:
    """扫描训练文件目录，按 PRESET_FILES 顺序定位每个 .pptx。

    返回 [(region, path)] 列表。找不到的项跳过。
    """
    if not TRAINING_DIR.exists():
        logger.warning("训练文件目录不存在：%s", TRAINING_DIR)
        return []
    all_pptx = [p for p in TRAINING_DIR.iterdir()
                if p.is_file() and p.suffix.lower() == ".pptx"]
    out: list[tuple[str, Path]] = []
    for region, needle in PRESET_FILES:
        for p in all_pptx:
            if needle.lower() in p.name.lower():
                out.append((region, p))
                break
    return out


_NON_AUTHOR_TOKENS = (
    "matepad", "huawei", "country", "latam", "mexico", "mea", "uae",
)


def _extract_author(file_stem: str) -> str:
    """从文件名抠出作者，例如:
        'Country R_Arman Grigorian_MatePad 12X'              → 'Arman Grigorian'
        'MEA - UAE - Matepad 12X - Jeofrey B Mendviel'      → 'Jeofrey B Mendviel'
        'LATAM_MEXICO_MATEPAD 12X_ALBERTO DANIEL CRUZ'      → 'ALBERTO DANIEL CRUZ'
    大小写不敏感地剔除产品名 / 区域名，剩下含 2+ 单词的最长段优先。
    """
    parts = re.split(r"[_\-]", file_stem)
    parts = [p.strip() for p in parts if p.strip()]

    candidates: list[str] = []
    for p in parts:
        lower = p.lower()
        if any(tok in lower for tok in _NON_AUTHOR_TOKENS):
            continue
        if not any(c.isalpha() for c in p):
            continue
        if len(p.split()) >= 2:
            candidates.append(p)

    if candidates:
        # 倾向最长（更可能是人名全称）
        return max(candidates, key=len)

    # 退化：剔除产品/区域后剩下的最后一段，否则原文件名
    leftover = [
        p for p in parts
        if not any(tok in p.lower() for tok in _NON_AUTHOR_TOKENS)
    ]
    return leftover[-1] if leftover else (parts[-1] if parts else file_stem)


def _build_raw_content(path: Path) -> str:
    """把整份 .pptx 拼成可全文检索的纯文本。"""
    try:
        from src.rag.parsers import parse_file
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG parsers 导入失败：%s", exc)
        return ""

    try:
        chunks = parse_file(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pptx 解析失败 %s: %s", path.name, exc)
        return ""

    out_lines: list[str] = []
    for c in chunks:
        section = (c.get("section") or "").strip()
        content = (c.get("content") or c.get("text") or "").strip()
        if section:
            out_lines.append(f"## {section}")
        if content:
            out_lines.append(content)
        out_lines.append("")
    return "\n".join(out_lines).strip()


def _build_excerpt(raw_content: str, max_chars: int = 800) -> list[dict[str, Any]]:
    """preset 没有真实对话，把摘要塞进 sales 角色一条 turn 内供 UI 展示。"""
    if not raw_content:
        return []
    head = raw_content[:max_chars]
    if len(raw_content) > max_chars:
        head += "\n…（更多内容请见 raw_content）"
    return [{
        "idx": 0,
        "speaker": "sales",
        "content": head,
        "stage": "preset_excerpt",
    }]


def seed_preset_cases_if_empty(conn: sqlite3.Connection) -> int:
    """若 sales_cases 表完全为空，则导入预填案例；否则跳过。

    Returns: 新增条数（0 表示跳过或失败）。
    """
    existing = dbm.count_sales_cases(conn)
    if existing > 0:
        logger.info("sales_cases 已有 %d 条，跳过 preset 预填", existing)
        return 0

    files = _find_pptx_files()
    if not files:
        logger.warning("未发现可预填的 .pptx 文件")
        return 0

    inserted = 0
    for region, path in files:
        try:
            author = _extract_author(path.stem)
            raw = _build_raw_content(path)
            excerpt = _build_excerpt(raw)
            title = f"[{region}] {author} · MatePad 12X 销售案例"
            why = (
                f"来自训练资料《{path.name}》：{region} 区域销冠 {author} "
                f"在 MatePad 12X 实战中沉淀的成功打法，覆盖目标客户画像、"
                f"关键卖点、典型异议处理与成交节奏。"
            )
            tags = ["preset", region]
            persona_tags = ["B端", "区域销冠"]

            dbm.create_sales_case(
                conn,
                source="preset",
                title=title,
                session_id=None,
                scene="MatePad 12X 销售实战",
                persona_id=None,
                persona_tags=persona_tags,
                dialogue_excerpt=excerpt,
                raw_content=raw or None,
                why_excellent=why,
                tags=tags,
                file_source=path.name,
            )
            inserted += 1
            logger.info("preset case 已导入：%s", path.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("preset case 导入失败 %s: %s", path.name, exc)

    conn.commit()
    logger.info("preset 预填完成，共新增 %d 条", inserted)
    return inserted
