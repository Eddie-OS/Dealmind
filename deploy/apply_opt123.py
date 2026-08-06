#!/usr/bin/env python3
"""在服务器上就地应用「稳定性优化 1/2/3」补丁（幂等，可重复运行）。

三项优化：
  1. 开机预加载 embedding 模型（server.py lifespan）——把内存峰值挪到启动时。
  2. 限制同时进行的会话数（session_runner_async.py + routes_sessions.py）。
  3. SQLite 开 WAL + busy_timeout（storage/db.py）——多人读写不再互相阻塞。

用法（在 /opt/dealmind 下）：
    sudo /opt/dealmind/.venv/bin/python deploy/apply_opt123.py
或直接 python3（只要能 import 无所谓，这脚本纯文本改写）：
    python3 deploy/apply_opt123.py

每个补丁：已应用 → SKIP；锚点找不到 → 报错并整体退出（不写坏文件）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PatchError(RuntimeError):
    pass


def patch(rel_path: str, old: str, new: str, *, marker: str) -> str:
    """把 rel_path 里的 old 替换成 new。

    - 若 marker 已在文件里 → 认为已应用，返回 'SKIP'。
    - 若 old 不在文件里（且未应用）→ 抛错。
    """
    p = ROOT / rel_path
    text = p.read_text(encoding="utf-8")
    if marker in text:
        return f"SKIP  {rel_path} (已应用)"
    if old not in text:
        raise PatchError(
            f"{rel_path}: 找不到锚点，无法安全打补丁。"
            f"（服务器上的该文件可能与预期版本不一致）"
        )
    if text.count(old) != 1:
        raise PatchError(f"{rel_path}: 锚点出现 {text.count(old)} 次，不唯一，拒绝改写。")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"OK    {rel_path}"


PATCHES: list[tuple[str, str, str, str]] = []

# ---- 优化 3：SQLite WAL（storage/db.py）----
PATCHES.append((
    "src/storage/db.py",
    '''    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn''',
    '''    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    # 多人并发加固：WAL（读写不互相阻塞）+ busy_timeout（拿不到锁最多等 5s）
    # + synchronous=NORMAL（WAL 下安全且更快）。
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn''',
    "PRAGMA journal_mode = WAL;",
))

# ---- 优化 2a：并发闸门实现（session_runner_async.py）----
PATCHES.append((
    "src/api/session_runner_async.py",
    """import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor""",
    """import asyncio
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor""",
    "import os\nimport threading\nfrom concurrent.futures import ThreadPoolExecutor",
))

PATCHES.append((
    "src/api/session_runner_async.py",
    '''# 事件队列哨兵：协程看到这个就退出
_QUEUE_SENTINEL: dict[str, Any] = {"__sentinel__": True}''',
    '''# 事件队列哨兵：协程看到这个就退出
_QUEUE_SENTINEL: dict[str, Any] = {"__sentinel__": True}


# 并发会话闸门（2GB 小机稳定性护栏）。DM_MAX_CONCURRENT_SESSIONS 调整（默认 3）。
def _resolve_max_concurrent() -> int:
    try:
        v = int(os.getenv("DM_MAX_CONCURRENT_SESSIONS", "3"))
        return v if v > 0 else 3
    except (TypeError, ValueError):
        return 3


_MAX_CONCURRENT_SESSIONS = _resolve_max_concurrent()
_slot_lock = threading.Lock()
_active_slots = 0


def try_acquire_session_slot() -> bool:
    """原子地尝试占用一个会话名额；满了返回 False。"""
    global _active_slots
    with _slot_lock:
        if _active_slots >= _MAX_CONCURRENT_SESSIONS:
            return False
        _active_slots += 1
        return True


def release_session_slot() -> None:
    global _active_slots
    with _slot_lock:
        if _active_slots > 0:
            _active_slots -= 1


def session_slot_stats() -> dict[str, int]:
    with _slot_lock:
        return {"active": _active_slots, "max": _MAX_CONCURRENT_SESSIONS}''',
    "def try_acquire_session_slot() -> bool:",
))

PATCHES.append((
    "src/api/session_runner_async.py",
    """    status: str = "pending"  # pending / running / done / cancelled / failed
    final_state: Any = None
    error: Optional[str] = None""",
    """    status: str = "pending"  # pending / running / done / cancelled / failed
    final_state: Any = None
    error: Optional[str] = None
    # 是否持有一个并发会话名额，_run_blocking 结束时负责归还。
    holds_slot: bool = False""",
    "holds_slot: bool = False",
))

PATCHES.append((
    "src/api/session_runner_async.py",
    """        finally:
            # 无论成功/失败/中断，最后塞 sentinel 通知 stream 协程退出
            if self.loop and not self.loop.is_closed():""",
    """        finally:
            # 归还并发名额（无论成功/失败/中断都要放，避免名额泄漏把闸门锁死）
            if self.holds_slot:
                self.holds_slot = False
                release_session_slot()
            # 无论成功/失败/中断，最后塞 sentinel 通知 stream 协程退出
            if self.loop and not self.loop.is_closed():""",
    "归还并发名额（无论成功/失败/中断都要放",
))

# ---- 优化 2b：路由层闸门（routes_sessions.py）----
PATCHES.append((
    "src/api/routes_sessions.py",
    """from src.api.session_runner_async import (
    SessionRunner,
    get_runner,
    register_runner,
)""",
    """from src.api.session_runner_async import (
    SessionRunner,
    get_runner,
    register_runner,
    release_session_slot,
    remove_runner,
    session_slot_stats,
    try_acquire_session_slot,
)""",
    "try_acquire_session_slot,",
))

PATCHES.append((
    "src/api/routes_sessions.py",
    """    cfg = row.get("config") or {}
    runner = SessionRunner(session_id=session_id)
    register_runner(runner)

    runner.start_in_executor(
        product_text=product_text,
        persona=persona,
        topic=row.get("topic") or "学习平板销售模拟",
        max_rounds=int(row.get("max_rounds") or 50),
        judge_interval=int(cfg.get("judge_interval") or 3),
        memory_interval=int(cfg.get("memory_interval") or 3),
        who_speaks_first=cfg.get("who_speaks_first") or "sales",
        opening_line=row.get("opening_line") or "",
        max_rounds_floor=int(cfg.get("max_rounds_floor") or 0),
        output_dir="outputs",
        product_kb_id=row.get("product_kb_id"),
        enterprise_kb_id=row.get("enterprise_kb_id"),
        handbook_id=row.get("handbook_id"),
        language=(cfg.get("language") or "zh-CN"),
    )""",
    """    # 并发闸门：小内存机器同时跑太多实时会话会 OOM 卡死整机。
    if not try_acquire_session_slot():
        stats = session_slot_stats()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"当前同时进行的会话已满（{stats['active']}/{stats['max']}），"
            f"请稍候几分钟再试。",
        )

    cfg = row.get("config") or {}
    runner = SessionRunner(session_id=session_id, holds_slot=True)
    register_runner(runner)

    try:
        runner.start_in_executor(
            product_text=product_text,
            persona=persona,
            topic=row.get("topic") or "学习平板销售模拟",
            max_rounds=int(row.get("max_rounds") or 50),
            judge_interval=int(cfg.get("judge_interval") or 3),
            memory_interval=int(cfg.get("memory_interval") or 3),
            who_speaks_first=cfg.get("who_speaks_first") or "sales",
            opening_line=row.get("opening_line") or "",
            max_rounds_floor=int(cfg.get("max_rounds_floor") or 0),
            output_dir="outputs",
            product_kb_id=row.get("product_kb_id"),
            enterprise_kb_id=row.get("enterprise_kb_id"),
            handbook_id=row.get("handbook_id"),
            language=(cfg.get("language") or "zh-CN"),
        )
    except Exception:
        runner.holds_slot = False
        release_session_slot()
        remove_runner(session_id)
        raise""",
    "if not try_acquire_session_slot():",
))

# ---- 优化 1：开机预加载 embedding 模型（server.py lifespan）----
PATCHES.append((
    "src/api/server.py",
    """            logger.info("indexer thread requested · pending=%d started=%s",
                        len(pending), started)

    yield
    logger.info("DealMind API stopping")""",
    """            logger.info("indexer thread requested · pending=%d started=%s",
                        len(pending), started)

    # 开机预加载 embedding 模型：把内存峰值挪到启动时（此刻整机最空），
    # 避免第一次跑会话/检索时才惰性加载打满小内存机器。DM_PRELOAD_EMBEDDER=0 可关。
    if os.getenv("DM_PRELOAD_EMBEDDER", "1") == "1":
        try:
            from src.rag.embedder import get_embedder

            logger.info("preloading embedding model at startup ...")
            emb = get_embedder()
            emb.ensure_loaded()
            logger.info("embedding model preloaded · %s", emb.info())
        except Exception as exc:  # noqa: BLE001
            logger.warning("preload embedder failed (会后续惰性加载): %s", exc)

    yield
    logger.info("DealMind API stopping")""",
    "preloading embedding model at startup",
))


def main() -> int:
    print(f"[apply_opt123] ROOT = {ROOT}")
    results = []
    for rel, old, new, marker in PATCHES:
        try:
            results.append(patch(rel, old, new, marker=marker))
        except PatchError as e:
            print(f"FAIL  {e}")
            print("已中止，未对该文件写入。请检查服务器文件版本是否与本地一致。")
            return 2
    for r in results:
        print(r)
    print("[apply_opt123] 完成。请重启后端：sudo systemctl restart dealmind-api")
    return 0


if __name__ == "__main__":
    sys.exit(main())
