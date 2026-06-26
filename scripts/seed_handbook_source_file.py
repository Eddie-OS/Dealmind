"""Handbook 预置脚本 · 直接把 PPTX 落库为"已解析"来源文件

把 训练文件\5. Laurent_HUAWEI MatePad 12 X_Instore Training Guide.pptx
解析后挂到已有的 handbook 上，等价于"用户在 UI 上传 + 后端解析完成"，
但跳过整条 HTTP 链路，方便首启示例 / 排查问题 / CI 重复执行。

用法（PowerShell）：
    cd f:\Langraph
    python scripts/seed_handbook_source_file.py

幂等：
- 若指定 handbook 不存在则报错退出（请先跑 seed_first_handbook.py）
- 若同名文件已挂在此 handbook 下且状态 parsed，则跳过（不会重复落盘）
"""
from __future__ import annotations

import logging
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.rag.parsers import SUPPORTED_SUFFIXES, parse_file
from src.storage import db as storage_db


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("seed_handbook_file")


# ============================================================
# 配置
# ============================================================

HANDBOOK_NAME = "华为 MatePad 12X / Air 2025 · 销冠 Handbook"
SOURCE_PPTX = ROOT / "训练文件" / "5. Laurent_HUAWEI MatePad 12 X_Instore Training Guide.pptx"
UPLOAD_DIR = ROOT / "data" / "handbook_uploads"
MAX_PARSED_TEXT_BYTES = 500 * 1024  # 与 routes_handbook.py 保持一致


# ============================================================
# 主流程
# ============================================================

def parse_to_text(path: Path) -> str:
    """与 routes_handbook.py 的 _parse_to_text 保持完全一致的拼接口径。"""
    chunks = parse_file(path)
    parts: list[str] = []
    for c in chunks:
        section = c.get("section") or ""
        text = (c.get("text") or "").strip()
        if not text:
            continue
        if section:
            parts.append(f"[{section}]\n{text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


def main() -> None:
    if not SOURCE_PPTX.exists():
        logger.error("源 PPTX 不存在: %s", SOURCE_PPTX)
        sys.exit(1)

    suffix = SOURCE_PPTX.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        logger.error("不支持的后缀 %s（受支持的：%s）", suffix, SUPPORTED_SUFFIXES)
        sys.exit(2)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with storage_db.connection_scope() as conn:
        storage_db.init_schema(conn)

        # ---- 1) 定位现有 handbook ----
        hb = storage_db.get_handbook_by_name(conn, HANDBOOK_NAME)
        if not hb:
            logger.error(
                "Handbook 不存在: %r。请先执行 `python scripts/seed_first_handbook.py`",
                HANDBOOK_NAME,
            )
            sys.exit(3)
        handbook_id = int(hb["id"])
        logger.info("Handbook 命中: id=%s name=%s", handbook_id, hb["name"])

        # ---- 2) 幂等检查 ----
        existing = storage_db.list_handbook_files(conn, handbook_id)
        same = [
            f for f in existing
            if (f.get("filename") or "") == SOURCE_PPTX.name
            and f.get("status") == "parsed"
        ]
        if same:
            logger.info(
                "已存在同名 parsed 文件（id=%s, %d bytes parsed_text），跳过预置",
                same[0]["id"],
                len(same[0].get("parsed_text") or ""),
            )
            return

        # ---- 3) 复制到 upload 目录 ----
        safe_name = f"{uuid.uuid4().hex}{suffix}"
        dest = UPLOAD_DIR / safe_name
        shutil.copy2(SOURCE_PPTX, dest)
        size_bytes = dest.stat().st_size
        logger.info("已复制源文件 -> %s（%.1f KB）", dest.name, size_bytes / 1024)

        # ---- 4) 入库 status=parsing ----
        file_id = storage_db.create_handbook_file(
            conn,
            handbook_id=handbook_id,
            filename=SOURCE_PPTX.name,
            file_path=str(dest.resolve()),
            file_type=suffix.lstrip("."),
            file_size=size_bytes,
            status="parsing",
        )
        logger.info("已创建 handbook_files 行 id=%s", file_id)

        # ---- 5) 解析 ----
        try:
            parsed = parse_to_text(dest)
            if not parsed.strip():
                raise RuntimeError("解析后内容为空（PPT 可能纯图片）")
            truncated = parsed.encode("utf-8")[:MAX_PARSED_TEXT_BYTES].decode(
                "utf-8", errors="ignore"
            )
            storage_db.update_handbook_file(
                conn,
                file_id,
                parsed_text=truncated,
                status="parsed",
            )
            logger.info(
                "解析完成：%d chars 入库（实际 %d chars，截断阈值 %d KB）",
                len(truncated), len(parsed), MAX_PARSED_TEXT_BYTES // 1024,
            )
        except Exception as exc:
            storage_db.update_handbook_file(
                conn,
                file_id,
                status="failed",
                error_msg=str(exc)[:500],
            )
            logger.exception("解析失败：%s", exc)
            sys.exit(4)

    logger.info("=== 预置完成 ===")


if __name__ == "__main__":
    main()
