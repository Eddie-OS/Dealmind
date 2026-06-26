"""KB 启动预填 + 后台索引调度。

策略：
- 启动 lifespan 中调 seed_default_kbs(conn)：若 knowledge_bases 表空就插入两个 KB
  并把 训练文件/ 里对应文件登记为 status='pending' 的 knowledge_files 行。
- 然后调 start_indexer_thread()：后台 daemon thread 拉所有 pending 文件，
  逐个解析 + 嵌入 + 入 Chroma，状态 pending → indexing → indexed/failed。
- 每个 thread 单独创建 SQLite 连接（sqlite3 单连接不能跨线程）。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.config import PROJECT_ROOT
from src.rag.kb_store import KBStore
from src.rag.parsers import ParserError, parse_file
from src.storage import db as storage_db

logger = logging.getLogger(__name__)


_TRAINING_DIR = PROJECT_ROOT / "训练文件"


@dataclass
class SeedFileSpec:
    """一条预填记录：(kb_name, filename_pattern)，pattern 用 glob 在训练文件夹里查。"""

    kb_name: str
    pattern: str  # glob pattern，因为训练文件名有版本号变体


# product KB
PRODUCT_KB = ("华为 MatePad 12X", "product", "华为 MatePad 12X 产品资料、销售话术与 FAQ")
PRODUCT_FILES = [
    "1.2 HUAWEI Tablet*Introductory*.pptx",
    "2. *HUAWEI MatePad*Sales Talk*.pptx",
    "7. *HUAWEI MatePad*FAQ*.xlsx",
]

# enterprise KB
ENTERPRISE_KB = ("销售方法论", "enterprise", "零售销售心法、表达技巧与门店培训手册")
ENTERPRISE_FILES = [
    "4.1 *Retail Doctors*.pdf",
    "4.2 *Steve Jobs*.pdf",
    "5. *Instore Training*.pptx",
]


def _glob_first(pattern: str) -> Optional[Path]:
    """在训练文件夹中按 glob 找第一个匹配文件。"""
    if not _TRAINING_DIR.exists():
        return None
    matches = sorted(_TRAINING_DIR.glob(pattern))
    return matches[0] if matches else None


def _register_files(
    conn,
    kb_id: int,
    patterns: list[str],
) -> tuple[int, list[str]]:
    """按 patterns 注册文件到 knowledge_files 表（status=pending）。

    Returns: (注册成功数, 未找到的 pattern 列表)
    """
    ok = 0
    missing: list[str] = []
    for pat in patterns:
        f = _glob_first(pat)
        if f is None:
            missing.append(pat)
            logger.warning("seed: 未找到训练文件 pattern=%s", pat)
            continue
        try:
            size = f.stat().st_size
        except OSError:
            size = None
        storage_db.create_kb_file(
            conn,
            kb_id=kb_id,
            filename=f.name,
            file_path=str(f.resolve()),
            file_type=f.suffix.lower().lstrip("."),
            file_size=size,
            status="pending",
        )
        ok += 1
    return ok, missing


def seed_default_kbs(conn) -> dict:
    """若 knowledge_bases 表为空，预填两个 KB + 登记待索引文件。"""
    existing = storage_db.count_kbs(conn)
    if existing > 0:
        logger.info("knowledge_bases 表已有 %d 条，跳过 KB 预填", existing)
        return {"existing": existing, "created": 0, "files_registered": 0}

    if not _TRAINING_DIR.exists():
        logger.warning("训练文件目录不存在: %s，跳过 KB 预填", _TRAINING_DIR)
        return {"existing": 0, "created": 0, "files_registered": 0}

    created = 0
    files_registered = 0
    for (name, kb_type, desc), patterns in [
        (PRODUCT_KB, PRODUCT_FILES),
        (ENTERPRISE_KB, ENTERPRISE_FILES),
    ]:
        if storage_db.get_kb_by_name(conn, name):
            logger.info("KB 已存在，跳过: %s", name)
            continue
        kb_id = storage_db.create_kb(conn, name=name, kb_type=kb_type, description=desc)
        ok, missing = _register_files(conn, kb_id, patterns)
        created += 1
        files_registered += ok
        logger.info("seed KB created: %s (id=%s) · files=%d missing=%d",
                    name, kb_id, ok, len(missing))
    return {"existing": 0, "created": created, "files_registered": files_registered}


# ============================================================
# 后台索引线程
# ============================================================

_indexer_lock = threading.Lock()
_indexer_running = False


def _index_one_file(file_id: int) -> None:
    """索引单个文件：parse → embed → upsert → 更新状态 + KB 统计。"""
    # 每个调用独立 connection（跨线程安全）
    with storage_db.connection_scope() as conn:
        row = storage_db.get_kb_file(conn, file_id)
        if not row:
            return
        kb = storage_db.get_kb_by_id(conn, row["kb_id"])
        if not kb:
            return
        storage_db.update_kb_file_status(conn, file_id, status="indexing", error_msg="")
        kb_id = kb["id"]
        kb_type = kb["kb_type"]
        filename = row["filename"]
        file_path = row["file_path"]

    try:
        chunks = parse_file(Path(file_path))
    except ParserError as exc:
        with storage_db.connection_scope() as conn:
            storage_db.update_kb_file_status(
                conn, file_id, status="failed", error_msg=str(exc)[:500]
            )
            storage_db.recompute_kb_stats(conn, kb_id)
        logger.error("parse failed file=%s: %s", filename, exc)
        return
    except Exception as exc:  # noqa: BLE001
        with storage_db.connection_scope() as conn:
            storage_db.update_kb_file_status(
                conn, file_id, status="failed", error_msg=f"unexpected: {exc}"[:500]
            )
            storage_db.recompute_kb_stats(conn, kb_id)
        logger.exception("parse unexpected failed file=%s", filename)
        return

    try:
        store = KBStore(kb_id=kb_id, kb_type=kb_type)
        # 重索引前清掉旧 chunks（避免重复入库）
        store.delete_by_file(file_id)
        added = store.add_chunks(file_id=file_id, filename=filename, chunks=chunks)
    except Exception as exc:  # noqa: BLE001
        with storage_db.connection_scope() as conn:
            storage_db.update_kb_file_status(
                conn, file_id, status="failed", error_msg=f"embed/store: {exc}"[:500]
            )
            storage_db.recompute_kb_stats(conn, kb_id)
        logger.exception("embed/store failed file=%s", filename)
        return

    with storage_db.connection_scope() as conn:
        storage_db.update_kb_file_status(
            conn, file_id, status="indexed", chunk_count=added, error_msg=""
        )
        storage_db.recompute_kb_stats(conn, kb_id)
    logger.info("indexed file=%s · chunks=%d", filename, added)


def _indexer_loop() -> None:
    """循环消费所有 pending / indexing 文件，跑完就退出。"""
    global _indexer_running
    try:
        while True:
            with storage_db.connection_scope() as conn:
                pending = storage_db.list_pending_files(conn)
            if not pending:
                break
            for row in pending:
                try:
                    _index_one_file(int(row["id"]))
                except Exception:
                    logger.exception("indexer error file_id=%s", row.get("id"))
            # 短暂 sleep 避免极端情况死循环
            time.sleep(0.2)
    finally:
        with _indexer_lock:
            _indexer_running = False
        logger.info("indexer loop exited")


def start_indexer_thread() -> bool:
    """启动后台索引 daemon 线程；若已在跑就跳过。Returns 是否真的启动了。"""
    global _indexer_running
    with _indexer_lock:
        if _indexer_running:
            return False
        _indexer_running = True
    t = threading.Thread(target=_indexer_loop, name="kb-indexer", daemon=True)
    t.start()
    logger.info("indexer thread started")
    return True
