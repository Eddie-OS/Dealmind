"""Stage 12：运行状态接口。

4 个只读接口，全部尽量轻量（不做任何写入 / 不阻塞主流程）：

  GET /api/status/system       系统信息 + 关键目录占用
  GET /api/status/logs?lines=  最近 N 行日志（默认 200，上限 2000）
  GET /api/status/llm_stats    LLM 调用/对话统计（按 turns 表聚合）
  GET /api/status/tasks        正在跑的 SessionRunner + BatchRunner
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.api.session_runner_async import list_runners
from src.batch.runner import list_batch_runners
from src.config import PROJECT_ROOT
from src.storage import db as storage_db
from src.storage.db import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/status", tags=["status"])


# ============================================================
# 共用工具
# ============================================================

CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "app.log"


def _dir_size(p: Path) -> int:
    """目录占用字节数；目录不存在返回 0。失败安全：忽略个别文件错误。"""
    if not p.exists():
        return 0
    total = 0
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def _fmt_bytes(n: int) -> str:
    """人类可读的大小。"""
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.1f} {u}"
        f /= 1024
    return f"{n} B"


def _safe_pkg_version(name: str) -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version(name)
        except PackageNotFoundError:
            return "-"
    except Exception:  # noqa: BLE001
        return "-"


# ============================================================
# 1. 系统信息
# ============================================================

@router.get("/system", summary="系统 / 进程 / 关键目录占用")
def get_system() -> dict[str, Any]:
    """返回字段：
        python              {version, implementation, executable}
        platform            {system, release, machine}
        deps                关键依赖版本 (fastapi/uvicorn/pydantic/sqlite3/...)
        paths               {project_root, db, chroma, log_dir}
        sizes               {db, chroma, logs, outputs}  bytes + human
        cwd                 当前工作目录
    """
    sqlite_ver = "-"
    try:
        import sqlite3
        sqlite_ver = sqlite3.sqlite_version
    except Exception:  # noqa: BLE001
        pass

    sizes_raw = {
        "db": _dir_size(Path(DEFAULT_DB_PATH)),
        "chroma": _dir_size(CHROMA_DIR),
        "logs": _dir_size(LOG_DIR),
        "outputs": _dir_size(PROJECT_ROOT / "outputs"),
    }
    sizes_human = {k: _fmt_bytes(v) for k, v in sizes_raw.items()}

    return {
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "deps": {
            "fastapi": _safe_pkg_version("fastapi"),
            "uvicorn": _safe_pkg_version("uvicorn"),
            "pydantic": _safe_pkg_version("pydantic"),
            "chromadb": _safe_pkg_version("chromadb"),
            "sentence_transformers": _safe_pkg_version("sentence-transformers"),
            "openai": _safe_pkg_version("openai"),
            "python_pptx": _safe_pkg_version("python-pptx"),
            "sqlite": sqlite_ver,
        },
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "db": str(DEFAULT_DB_PATH),
            "chroma": str(CHROMA_DIR),
            "log_dir": str(LOG_DIR),
            "cwd": os.getcwd(),
        },
        "sizes_bytes": sizes_raw,
        "sizes_human": sizes_human,
    }


# ============================================================
# 2. 日志查看器
# ============================================================

@router.get("/logs", summary="最近 N 行日志（默认 200，上限 2000）")
def get_logs(lines: int = Query(200, ge=10, le=2000)) -> dict[str, Any]:
    """读取 logs/app.log 末尾 N 行；不存在返回空数组。

    简单实现：直接读全文取最后 N 行。日志文件由 RotatingFileHandler
    控制单文件大小，足够安全。
    """
    if not LOG_FILE.exists():
        return {"file": str(LOG_FILE), "exists": False, "lines": []}
    try:
        # utf-8 + errors=replace：日志可能含 cp936 残留
        with LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"读取日志失败: {exc}") from exc

    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return {
        "file": str(LOG_FILE),
        "exists": True,
        "total_lines": len(all_lines),
        "returned": len(tail),
        "lines": [ln.rstrip("\n") for ln in tail],
    }


# ============================================================
# 3. LLM / 对话统计
# ============================================================

@router.get("/llm_stats", summary="对话量统计（按 turns 表近 N 天聚合）")
def get_llm_stats(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    """返回:
        today_turns         今日 turn 数（sales+persona 合计）
        today_sales_turns   今日 sales turn 数（≈ LLM 调用次数下限）
        today_sessions      今日产生 turn 的不同 session 数
        evaluations_today   今日 evaluations 数（judge+coach 合计）
        by_day              [{date, total, sales, persona, sessions}]  近 N 天

    说明：未持久化 token / latency，所以这里以 turn 数为对话量近似指标。
    """
    today = date.today().isoformat()
    start = (date.today() - timedelta(days=days - 1)).isoformat()

    with storage_db.connection_scope() as conn:
        # 今日聚合
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN role = 'sales'   THEN 1 ELSE 0 END) AS sales,
                SUM(CASE WHEN role = 'persona' THEN 1 ELSE 0 END) AS persona,
                COUNT(DISTINCT session_id) AS sessions
            FROM turns
            WHERE SUBSTR(created_at, 1, 10) = ?
            """,
            (today,),
        ).fetchone()
        today_total = int(row["total"] or 0)
        today_sales = int(row["sales"] or 0)
        today_persona = int(row["persona"] or 0)
        today_sessions = int(row["sessions"] or 0)

        # 今日 evaluations 数
        ev_row = conn.execute(
            "SELECT COUNT(*) AS n FROM evaluations "
            "WHERE SUBSTR(created_at, 1, 10) = ?",
            (today,),
        ).fetchone()
        evals_today = int(ev_row["n"] or 0)

        # 近 N 天分组
        rows = conn.execute(
            """
            SELECT
                SUBSTR(created_at, 1, 10) AS d,
                COUNT(*) AS total,
                SUM(CASE WHEN role = 'sales'   THEN 1 ELSE 0 END) AS sales,
                SUM(CASE WHEN role = 'persona' THEN 1 ELSE 0 END) AS persona,
                COUNT(DISTINCT session_id) AS sessions
            FROM turns
            WHERE SUBSTR(created_at, 1, 10) >= ?
            GROUP BY d
            ORDER BY d ASC
            """,
            (start,),
        ).fetchall()

        by_day_map = {
            r["d"]: {
                "date": r["d"],
                "total": int(r["total"] or 0),
                "sales": int(r["sales"] or 0),
                "persona": int(r["persona"] or 0),
                "sessions": int(r["sessions"] or 0),
            }
            for r in rows
        }

    # 补齐空日期
    by_day: list[dict[str, Any]] = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        by_day.append(
            by_day_map.get(
                d,
                {"date": d, "total": 0, "sales": 0, "persona": 0, "sessions": 0},
            )
        )

    return {
        "today_turns": today_total,
        "today_sales_turns": today_sales,
        "today_persona_turns": today_persona,
        "today_sessions": today_sessions,
        "evaluations_today": evals_today,
        "by_day": by_day,
        "note": "尚未持久化 token / latency；以 turn 计数作为对话量近似",
    }


# ============================================================
# 4. 后台任务
# ============================================================

@router.get("/tasks", summary="正在跑的 SessionRunner + BatchRunner")
def get_tasks() -> dict[str, Any]:
    """返回 sessions / batches 两个数组，元素来自各自 registry。

    is_active 字段：
      - session: status == 'running'
      - batch:   status == 'running'
    """
    sess = list_runners()
    btc = list_batch_runners()
    active_sessions = sum(1 for x in sess if x.get("status") == "running")
    active_batches = sum(1 for x in btc if x.get("status") == "running")
    return {
        "sessions": sess,
        "batches": btc,
        "totals": {
            "sessions": len(sess),
            "batches": len(btc),
            "active_sessions": active_sessions,
            "active_batches": active_batches,
        },
    }
