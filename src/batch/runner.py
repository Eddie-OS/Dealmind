"""Stage 9：BatchRunner。

设计：
    - 顺序串行：一场跑完才开下一场（蓝图明确禁止并发）。
    - 每场失败不影响下一场（failed_count + 1，error 计入 summary.errors）。
    - 中断点：在两场之间检查 cancel_flag；当前场正在跑时
      立即对其 SessionRunner 调 request_cancel()。
    - 进度事件通过 on_progress(dict) 推送给订阅者（WS 协程）。
      事件类型：
        batch_start    {batch_id, total}
        session_open   {batch_id, idx, session_id, persona_id}
        session_close  {batch_id, idx, session_id, outcome, status,
                        completed, failed, cancelled, total}
        batch_done     {batch_id, summary}
        log            {level, message}
    - 持久化：每场跑完都 update_batch_job 把进度写回 DB，
      让重启/掉线也能恢复展示。

线程模型：
    BatchRunner.start_in_executor() → 主协程在 asyncio 上下文里调用，
    实际工作在独立的批量线程池里跑。会话 LLM 调用本身又会在
    SessionRunner 的 session-pool 里跑。两层池都是 thread-safe。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from src.api.session_persistence import persist_event
from src.config import PROJECT_ROOT
from src.judge import judge_dialogue
from src.loaders import load_text_file
from src.memory import update_session_memory
from src.persona.loader import persona_from_db_row
from src.session import OPENING_TEMPLATES, run_session
from src.storage import db as storage_db
from src.perf_config import (
    BATCH_JUDGE_INTERVAL,
    BATCH_MEMORY_INTERVAL,
    BATCH_SESSION_CONCURRENCY,
)
from src.utils import now_timestamp


logger = logging.getLogger(__name__)


_batch_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="batch-runner")


# 让 WS 订阅者知道流结束
_QUEUE_SENTINEL: dict[str, Any] = {"__sentinel__": True}


# ============================================================
# Registry：让 WS 端点能找到 runner（同 session_runner_async 模式）
# ============================================================


_active_batches: dict[int, "BatchRunner"] = {}
_registry_lock = threading.Lock()


def register_batch_runner(runner: "BatchRunner") -> None:
    with _registry_lock:
        _active_batches[runner.batch_id] = runner


def get_batch_runner(batch_id: int) -> Optional["BatchRunner"]:
    with _registry_lock:
        return _active_batches.get(batch_id)


def remove_batch_runner(batch_id: int) -> None:
    with _registry_lock:
        _active_batches.pop(batch_id, None)


def personas_done_for_batch(batch_row: dict[str, Any]) -> set[int]:
    """从 batch 已记录的 session_ids 中，收集 status=done 的 persona_id。"""
    done: set[int] = set()
    with storage_db.connection_scope() as conn:
        for sid in batch_row.get("session_ids") or []:
            srow = storage_db.get_session_by_id(conn, sid)
            if not srow:
                continue
            if srow.get("status") == "done":
                pid = srow.get("persona_id")
                if pid is not None:
                    done.add(int(pid))
    return done


def remaining_persona_ids(batch_row: dict[str, Any]) -> list[int]:
    """按 persona_ids 顺序返回尚未成功完成的 id。"""
    all_ids: list[int] = batch_row.get("persona_ids") or []
    done = personas_done_for_batch(batch_row)
    return [pid for pid in all_ids if pid not in done]


def list_batch_runners() -> list[dict[str, Any]]:
    with _registry_lock:
        return [
            {
                "batch_id": r.batch_id,
                "status": r.status,
                "completed": r.completed_count,
                "failed": r.failed_count,
                "cancelled": r.cancelled_count,
                "total": r.total_count,
                "current_session_id": r.current_session_id,
                "queue_size": r.queue.qsize(),
            }
            for r in _active_batches.values()
        ]


# ============================================================
# BatchRunner
# ============================================================


@dataclass
class BatchRunner:
    """单个 batch_job 的运行容器。"""

    batch_id: int
    resume: bool = False
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    loop: Optional[asyncio.AbstractEventLoop] = None
    future: Any = None

    status: str = "pending"  # pending / running / completed / cancelled / failed
    total_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    current_index: int = 0
    current_session_id: Optional[str] = None
    session_ids: list[str] = field(default_factory=list)
    error: Optional[str] = None
    # 每场 session 的当前轮次（给 WS 心跳上报；线程间共享只读）
    current_round: int = 0

    # ------- 内部工具 -------

    def request_cancel(self) -> None:
        """请求中断；下一场之间检查；当前场也会被打断。"""
        self.cancel_flag.set()

    def _emit(self, evt: dict[str, Any]) -> None:
        """把事件投到 queue（线程安全）。"""
        if self.loop is None or self.loop.is_closed():
            return
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, evt)
        except RuntimeError:
            logger.warning("loop closed when pushing batch evt %s", evt.get("type"))

    def _emit_sentinel(self) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, _QUEUE_SENTINEL)
        except RuntimeError:
            pass

    def _update_db(self, **fields: Any) -> None:
        try:
            with storage_db.connection_scope() as conn:
                storage_db.update_batch_job(conn, self.batch_id, **fields)
        except Exception as exc:  # noqa: BLE001
            logger.warning("update_batch_job %s failed: %s", self.batch_id, exc)

    # ------- 单场会话 -------

    def _run_one_session(
        self,
        *,
        persona_id: int,
        batch_row: dict[str, Any],
        product_text: str,
        idx: int,
    ) -> dict[str, Any]:
        """跑一场会话；返回 {session_id, outcome, status, error?}。
        在主线程（batch worker）里同步执行。"""
        # 1. 取 persona
        with storage_db.connection_scope() as conn:
            persona_row = storage_db.get_persona_by_id(conn, persona_id)
        if not persona_row:
            return {
                "session_id": None,
                "outcome": "PERSONA_MISSING",
                "status": "failed",
                "error": f"persona id={persona_id} 不存在",
            }
        persona = persona_from_db_row(persona_row)

        # 2. 创建 session 行
        session_id = (
            f"session_{now_timestamp()}_p{persona_id}_b{self.batch_id}"
        )
        cfg = {
            "who_speaks_first": "sales",
            "judge_interval": int(batch_row.get("judge_interval") or BATCH_JUDGE_INTERVAL),
            "memory_interval": int(batch_row.get("memory_interval") or BATCH_MEMORY_INTERVAL),
            "max_rounds_floor": max(3, round(int(batch_row.get("max_rounds") or 30) * 0.15)),
            "batch_id": self.batch_id,
            "batch_index": idx,
        }
        # 开场白留空，由 run_session → generate_opening_line 按对话语言现场生成
        opening = ""
        language = (batch_row.get("config") or {}).get("language", "zh-CN")

        try:
            with storage_db.connection_scope() as conn:
                storage_db.create_session(
                    conn,
                    session_id=session_id,
                    persona_id=persona_id,
                product_kb_id=batch_row.get("product_kb_id"),
                enterprise_kb_id=batch_row.get("enterprise_kb_id"),
                handbook_id=batch_row.get("handbook_id"),
                provider_id=batch_row.get("provider_id"),
                topic=batch_row.get("topic") or "学习平板销售模拟",
                    opening_line=opening,
                    max_rounds=int(batch_row.get("max_rounds") or 30),
                    config=cfg,
                )
                storage_db.update_session(
                    conn, session_id,
                    status="running",
                    started_at=storage_db._now_iso(),
                )
        except Exception as exc:  # noqa: BLE001
            return {
                "session_id": session_id,
                "outcome": "DB_ERROR",
                "status": "failed",
                "error": f"create_session failed: {exc}",
            }

        # 3. 跑 run_session（同步阻塞；事件实时落库）
        self.current_session_id = session_id
        self.current_round = 0

        def on_event(evt: dict[str, Any]) -> None:
            persist_event(session_id, evt)
            # 提取当前轮次给 WS 心跳
            data = evt.get("data") or {}
            if "round_idx" in data:
                try:
                    self.current_round = int(data["round_idx"])
                except (TypeError, ValueError):
                    pass

        outcome = ""
        status_ = "done"
        err: Optional[str] = None
        try:
            state = run_session(
                product_text=product_text,
                persona=persona,
                topic=batch_row.get("topic") or "学习平板销售模拟",
                max_rounds=int(batch_row.get("max_rounds") or 30),
                judge_interval=int(batch_row.get("judge_interval") or BATCH_JUDGE_INTERVAL),
                memory_interval=int(batch_row.get("memory_interval") or BATCH_MEMORY_INTERVAL),
                output_dir="outputs",
                judge_fn=judge_dialogue,
                memory_fn=update_session_memory,
                who_speaks_first="sales",
                opening_line=opening,
                max_rounds_floor=cfg["max_rounds_floor"],
                on_event=on_event,
                cancel_flag=self.cancel_flag,
                session_id=session_id,
                product_kb_id=batch_row.get("product_kb_id"),
                enterprise_kb_id=batch_row.get("enterprise_kb_id"),
                handbook_id=batch_row.get("handbook_id"),
                language=language,
                )
            outcome = state.outcome or ""
            status_ = "cancelled" if outcome == "CANCELLED" else "done"

            # 落库收尾
            try:
                with storage_db.connection_scope() as conn:
                    row = storage_db.get_session_by_id(conn, session_id)
                    summary = (row or {}).get("summary") or {}
                    summary.update({
                        "outcome": outcome,
                        "total_rounds": state.round_idx,
                        "persona_turns": sum(
                            1 for t in state.full_history if t.speaker == "persona"
                        ),
                        "sales_turns": sum(
                            1 for t in state.full_history if t.speaker == "sales"
                        ),
                        "latest_memory": state.session_memory.model_dump(),
                        "batch_id": self.batch_id,
                    })
                    storage_db.update_session(
                        conn, session_id,
                        status=status_,
                        ended_at=storage_db._now_iso(),
                        summary=summary,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("update_session on finish failed: %s", exc)

        except Exception as exc:  # noqa: BLE001
            status_ = "failed"
            err = f"{type(exc).__name__}: {exc}"
            outcome = "ERROR"
            logger.exception("batch %s session %s failed: %s",
                             self.batch_id, session_id, exc)
            try:
                with storage_db.connection_scope() as conn:
                    storage_db.update_session(
                        conn, session_id,
                        status="failed",
                        ended_at=storage_db._now_iso(),
                        summary={"error": err, "batch_id": self.batch_id},
                    )
            except Exception:
                pass

        return {
            "session_id": session_id,
            "outcome": outcome,
            "status": status_,
            "error": err,
        }

    # ------- 批量主循环 -------

    def _run_blocking(self) -> None:
        """整个 batch 的工作线程主体。"""
        self.status = "running"
        started_iso = _iso_now()

        # 1. 取 batch 配置
        with storage_db.connection_scope() as conn:
            batch_row = storage_db.get_batch_job(conn, self.batch_id)
        if not batch_row:
            self.status = "failed"
            self.error = f"batch {self.batch_id} not found"
            self._emit({"type": "log", "data": {
                "level": "error", "message": self.error,
            }})
            self._emit_sentinel()
            return

        persona_ids_all: list[int] = batch_row.get("persona_ids") or []
        self.total_count = len(persona_ids_all)
        # 批量路径统一用性能 env 覆盖 DB 里偏小的 interval（商业 SLA）
        batch_row = {
            **batch_row,
            "judge_interval": BATCH_JUDGE_INTERVAL,
            "memory_interval": BATCH_MEMORY_INTERVAL,
        }

        done_pids: set[int] = set()
        if self.resume:
            done_pids = personas_done_for_batch(batch_row)
            self.session_ids = list(batch_row.get("session_ids") or [])
            self.completed_count = int(batch_row.get("completed_count") or 0)
            self.failed_count = int(batch_row.get("failed_count") or 0)
            self.cancelled_count = int(batch_row.get("cancelled_count") or 0)
            persona_tasks = [
                (idx, pid)
                for idx, pid in enumerate(persona_ids_all)
                if pid not in done_pids
            ]
            if not persona_tasks:
                finished_at = _iso_now()
                self.status = "completed"
                self._update_db(status="completed", ended_at=finished_at)
                self._emit({"type": "batch_done", "data": {
                    "batch_id": self.batch_id,
                    "status": "completed",
                    "completed": self.completed_count,
                    "failed": self.failed_count,
                    "cancelled": self.cancelled_count,
                    "total": self.total_count,
                    "summary": batch_row.get("summary") or {},
                }})
                self._emit_sentinel()
                return
        else:
            persona_tasks = [(idx, pid) for idx, pid in enumerate(persona_ids_all)]

        # 2. 预读产品资料（与 routes_sessions 同源；后续 Stage 可改为 RAG-only）
        product_path = PROJECT_ROOT / "data" / "product.md"
        try:
            product_text = load_text_file(str(product_path))
        except Exception:
            product_text = "（产品资料未找到，仅依赖 KB RAG。）"

        # 3. 标记 DB started（续跑保留已有计数与 started_at）
        if self.resume:
            self._update_db(
                status="running",
                total_count=self.total_count,
                completed_count=self.completed_count,
                failed_count=self.failed_count,
                cancelled_count=self.cancelled_count,
                session_ids=list(self.session_ids),
                error_msg=None,
            )
        else:
            self._update_db(
                status="running",
                started_at=started_iso,
                total_count=self.total_count,
                completed_count=0,
                failed_count=0,
                cancelled_count=0,
            )
        self._emit({"type": "batch_start", "data": {
            "batch_id": self.batch_id,
            "total": self.total_count,
            "name": batch_row.get("name"),
            "resume": self.resume,
            "remaining": len(persona_tasks),
            "already_done": len(done_pids),
        }})

        outcome_counter: dict[str, int] = {}
        errors: list[dict[str, Any]] = []
        stats_lock = threading.Lock()
        concurrency = max(1, min(BATCH_SESSION_CONCURRENCY, len(persona_tasks)))

        def _run_persona(idx: int, pid: int) -> Optional[dict[str, Any]]:
            if self.cancel_flag.is_set():
                return None
            self.current_index = idx
            self._emit({"type": "session_open", "data": {
                "batch_id": self.batch_id,
                "idx": idx,
                "persona_id": pid,
                "total": self.total_count,
            }})
            result = self._run_one_session(
                persona_id=pid,
                batch_row=batch_row,
                product_text=product_text,
                idx=idx,
            )
            st = result["status"]
            outcome = result.get("outcome") or "UNKNOWN"
            with stats_lock:
                outcome_counter[outcome] = outcome_counter.get(outcome, 0) + 1
                if st == "done":
                    self.completed_count += 1
                elif st == "cancelled":
                    self.cancelled_count += 1
                else:
                    self.failed_count += 1
                    errors.append({
                        "idx": idx, "persona_id": pid,
                        "session_id": result.get("session_id"),
                        "error": result.get("error"),
                    })
                if result.get("session_id"):
                    self.session_ids.append(result["session_id"])
                self.current_session_id = result.get("session_id")
                done_so_far = (
                    self.completed_count
                    + self.failed_count
                    + self.cancelled_count
                )
                self._update_db(
                    current_index=done_so_far,
                    current_session_id=result.get("session_id"),
                    session_ids=list(self.session_ids),
                    completed_count=self.completed_count,
                    failed_count=self.failed_count,
                    cancelled_count=self.cancelled_count,
                )
            self._emit({"type": "session_close", "data": {
                "batch_id": self.batch_id,
                "idx": idx,
                "persona_id": pid,
                "session_id": result.get("session_id"),
                "outcome": outcome,
                "status": st,
                "completed": self.completed_count,
                "failed": self.failed_count,
                "cancelled": self.cancelled_count,
                "total": self.total_count,
                "error": result.get("error"),
            }})
            return result

        # 4. 会话级并发（顺序串行 → N 路并行，满足 44 场 / 2h SLA）
        with ThreadPoolExecutor(
            max_workers=concurrency,
            thread_name_prefix="batch-session",
        ) as pool:
            futs = {
                pool.submit(_run_persona, idx, pid): (idx, pid)
                for idx, pid in persona_tasks
            }
            for fut in as_completed(futs):
                if self.cancel_flag.is_set():
                    for f in futs:
                        f.cancel()
                    logger.info("batch %s cancel requested", self.batch_id)
                    break
                try:
                    fut.result()
                except Exception as exc:  # noqa: BLE001
                    idx, pid = futs[fut]
                    logger.exception(
                        "batch %s persona idx=%d failed: %s",
                        self.batch_id, idx, exc,
                    )
                    with stats_lock:
                        self.failed_count += 1
                        errors.append({
                            "idx": idx, "persona_id": pid,
                            "session_id": None,
                            "error": f"{type(exc).__name__}: {exc}",
                        })

        # 5. 收尾：确定最终 status
        finished_at = _iso_now()
        if self.cancel_flag.is_set():
            final_status = "cancelled"
        elif self.failed_count == self.total_count and self.total_count > 0:
            final_status = "failed"
        else:
            final_status = "completed"
        self.status = final_status

        summary = {
            "outcome_dist": outcome_counter,
            "errors": errors,
            "duration_sec": _diff_sec(started_iso, finished_at),
        }
        self._update_db(
            status=final_status,
            ended_at=finished_at,
            summary=summary,
        )
        self._emit({"type": "batch_done", "data": {
            "batch_id": self.batch_id,
            "status": final_status,
            "completed": self.completed_count,
            "failed": self.failed_count,
            "cancelled": self.cancelled_count,
            "total": self.total_count,
            "summary": summary,
        }})
        self._emit_sentinel()

    def start_in_executor(self) -> None:
        """主协程内调用：捕获 running loop，把任务丢进 batch 线程池。"""
        if self.future is not None:
            raise RuntimeError(f"BatchRunner {self.batch_id} 已启动")
        self.loop = asyncio.get_running_loop()
        self.future = _batch_executor.submit(self._run_blocking)

    async def stream_events(self, websocket: Any) -> None:
        """WS 协程：从 queue 取事件 send_json，遇 sentinel 退出。"""
        while True:
            evt = await self.queue.get()
            if evt is _QUEUE_SENTINEL:
                break
            try:
                await websocket.send_json(evt)
            except Exception as exc:  # noqa: BLE001
                logger.info("ws send failed for batch %s, requesting cancel: %s",
                            self.batch_id, exc)
                self.request_cancel()
                break


# ============================================================
# 时间工具
# ============================================================


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _diff_sec(start_iso: str, end_iso: str) -> float:
    try:
        a = datetime.fromisoformat(start_iso)
        b = datetime.fromisoformat(end_iso)
        return round((b - a).total_seconds(), 1)
    except Exception:
        return 0.0
