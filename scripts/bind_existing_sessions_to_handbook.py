"""把所有未绑定 Handbook 的历史 session / batch 全部绑到指定 Handbook。

默认目标：HANDBOOK_NAME = '华为 MatePad 12X / Air 2025 · 销冠 Handbook'

用法：
    cd f:\\Langraph
    python scripts/bind_existing_sessions_to_handbook.py

幂等：
- 只更新 handbook_id IS NULL 的行
- 已绑定到别的 handbook 的不动
- 没找到目标 handbook 时直接报错退出
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.storage import db as sdb


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("bind_existing")

TARGET_HANDBOOK_NAME = "华为 MatePad 12X / Air 2025 · 销冠 Handbook"


def main() -> None:
    with sdb.connection_scope() as conn:
        hb = sdb.get_handbook_by_name(conn, TARGET_HANDBOOK_NAME)
        if not hb:
            logger.error(
                "目标 Handbook 不存在: %r。请先 seed。", TARGET_HANDBOOK_NAME,
            )
            sys.exit(1)
        hb_id = int(hb["id"])
        logger.info("目标 Handbook: id=%s name=%s", hb_id, hb["name"])

        # ---- sessions ----
        rows = conn.execute(
            "SELECT id FROM sessions WHERE handbook_id IS NULL"
        ).fetchall()
        sess_total = len(rows)
        logger.info("未绑定 session 数：%d", sess_total)

        with conn:
            cur = conn.execute(
                "UPDATE sessions SET handbook_id = ?, updated_at = ? "
                "WHERE handbook_id IS NULL",
                (hb_id, sdb._now_iso()),
            )
            sess_changed = cur.rowcount
        logger.info("已绑定 session 数：%d", sess_changed)

        # ---- batch_jobs ----
        rows = conn.execute(
            "SELECT id FROM batch_jobs WHERE handbook_id IS NULL"
        ).fetchall()
        batch_total = len(rows)
        logger.info("未绑定 batch 数：%d", batch_total)

        with conn:
            cur = conn.execute(
                "UPDATE batch_jobs SET handbook_id = ?, updated_at = ? "
                "WHERE handbook_id IS NULL",
                (hb_id, sdb._now_iso()),
            )
            batch_changed = cur.rowcount
        logger.info("已绑定 batch 数：%d", batch_changed)

        # ---- 校验 ----
        n_sess_bound = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE handbook_id = ?", (hb_id,),
        ).fetchone()["n"]
        n_sess_unbound = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE handbook_id IS NULL",
        ).fetchone()["n"]
        n_batch_bound = conn.execute(
            "SELECT COUNT(*) AS n FROM batch_jobs WHERE handbook_id = ?", (hb_id,),
        ).fetchone()["n"]
        n_batch_unbound = conn.execute(
            "SELECT COUNT(*) AS n FROM batch_jobs WHERE handbook_id IS NULL",
        ).fetchone()["n"]
        logger.info(
            "完成 · sessions: %d 绑定 / %d 仍未绑（应=0）· batches: %d 绑定 / %d 仍未绑（应=0）",
            n_sess_bound, n_sess_unbound, n_batch_bound, n_batch_unbound,
        )


if __name__ == "__main__":
    main()
