"""把 data/product_handbooks/matepad_12x_handbook.json 导入为首份 Handbook 记录。

幂等：name 已存在时跳过；带 --force 会覆盖（结构 + version_no+1）。

用法：
    python scripts/seed_first_handbook.py
    python scripts/seed_first_handbook.py --force
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.storage import db as storage_db


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_handbook")


HANDBOOK_NAME = "华为 MatePad 12X / Air 2025 · 销冠 Handbook"
HANDBOOK_DESC = "1/3/3/5/9/10 框架结构化销售话术（首份 Handbook · 基于训练 PPTX + 人工校对）"
SOURCE_JSON = ROOT / "data" / "product_handbooks" / "matepad_12x_handbook.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="覆盖已有同名 Handbook")
    args = parser.parse_args()

    if not SOURCE_JSON.exists():
        logger.error("Handbook JSON 不存在: %s", SOURCE_JSON)
        sys.exit(1)

    structure = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))

    with storage_db.connection_scope() as conn:
        storage_db.init_schema(conn)
        existing = storage_db.get_handbook_by_name(conn, HANDBOOK_NAME)

        if existing and not args.force:
            logger.info(
                "Handbook 已存在 id=%s status=%s（加 --force 覆盖）",
                existing["id"], existing.get("status"),
            )
            return

        if existing:
            storage_db.update_handbook(
                conn,
                existing["id"],
                description=HANDBOOK_DESC,
                structure=structure,
                status="ready",
                extraction_log="seed_first_handbook.py · 覆盖",
                bump_version=True,
            )
            hb = storage_db.get_handbook(conn, existing["id"])
            logger.info(
                "Handbook 已覆盖 id=%s name=%s v=%s",
                hb["id"], hb["name"], hb.get("version_no"),
            )
        else:
            hb_id = storage_db.create_handbook(
                conn,
                name=HANDBOOK_NAME,
                description=HANDBOOK_DESC,
                structure=structure,
                status="ready",
            )
            storage_db.update_handbook(
                conn,
                hb_id,
                extraction_log="seed_first_handbook.py · 首次导入",
            )
            hb = storage_db.get_handbook(conn, hb_id)
            logger.info(
                "Handbook 已创建 id=%s name=%s status=%s",
                hb["id"], hb["name"], hb.get("status"),
            )

        s = hb.get("structure_json") or {}
        logger.info(
            "结构条数 · intro=%d sell=%d comp=%d param=%d faq=%d demo=%d",
            1 if s.get("intro_1") else 0,
            len(s.get("selling_points") or []),
            len(s.get("competitor_points") or []),
            len(s.get("core_params") or []),
            len(s.get("faq") or []),
            len(s.get("demo_actions") or []),
        )


if __name__ == "__main__":
    main()
