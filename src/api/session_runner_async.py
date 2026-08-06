"""Stage 6a：异步 SessionRunner。

把同步的 `src.session.run_session` 跑在线程池里，
通过 asyncio.Queue 把同步线程里产生的事件桥接到 WebSocket 协程。

关键模式：
1. 启动时记录 main loop（`asyncio.get_running_loop()`）。
2. 线程里的 `on_event(evt)` 调 `loop.call_soon_threadsafe(queue.put_nowait, evt)`，
   保证跨线程往 asyncio Queue 入队是安全的。
3. WebSocket 协程 `stream_events` `await queue.get()` 然后 `send_json`。
4. `cancel_flag: threading.Event` 让协程能干净停掉线程里的循环。
5. 模块级 `_active_runners: dict[session_id, SessionRunner]` 让 WS 端点
   按 session_id 找到对应 runner。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

from src.agents import generate_persona_turn, generate_sales_turn  # noqa: F401（导入即触发模板检查）
from src.api.session_persistence import persist_event
from src.judge import judge_dialogue
from src.memory import update_session_memory
from src.schema import PersonaProfile
from src.session import run_session
from src.storage import db as storage_db


logger = logging.getLogger(__name__)


# 线程池：所有 session 共用。每场 session 至少占 1 个线程整段会话时长。
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="session-runner")

# 事件队列哨兵：协程看到这个就退出
_QUEUE_SENTINEL: dict[str, Any] = {"__sentinel__": True}


# ============================================================
# 并发会话闸门（2GB 小机稳定性护栏）
# ------------------------------------------------------------
# 每场实时会话会长期占用 1 个线程 + 一路 LLM 调用 + 内存里的历史/记忆，
# 同时跑太多会把小内存机器打满导致整机卡死。这里用一个进程内计数信号量
# 限制"同时在跑的实时会话数"，超过上限的新会话直接被路由层拒绝（HTTP 429），
# 前端提示"稍候再试"，而不是硬扛到 OOM。
#
# 通过环境变量 DM_MAX_CONCURRENT_SESSIONS 调整（默认 3）。
# ============================================================
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
    """归还一个会话名额（幂等下限保护，不会减到负数）。"""
    global _active_slots
    with _slot_lock:
        if _active_slots > 0:
            _active_slots -= 1


def session_slot_stats() -> dict[str, int]:
    with _slot_lock:
        return {"active": _active_slots, "max": _MAX_CONCURRENT_SESSIONS}


@dataclass
class SessionRunner:
    """单场 session 的运行容器。"""

    session_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    pause_flag: threading.Event = field(default_factory=threading.Event)
    loop: Optional[asyncio.AbstractEventLoop] = None
    future: Any = None
    status: str = "pending"  # pending / running / done / cancelled / failed
    final_state: Any = None
    error: Optional[str] = None
    # 是否持有一个并发会话名额（由路由层 try_acquire_session_slot 占用，
    # 本 runner 在 _run_blocking 结束时负责归还，保证名额不泄漏）。
    holds_slot: bool = False

    def request_cancel(self) -> None:
        """请求中断。下一轮循环检查 cancel_flag 时停止。"""
        self.cancel_flag.set()
        # 中断优先于暂停：清掉暂停标志，避免卡在暂停等待里
        self.pause_flag.clear()

    def _emit_status(self) -> None:
        """把当前 paused 状态推一条 session_status 事件给前端。"""
        if self.loop is None or self.loop.is_closed():
            return
        evt = {"type": "session_status", "data": {"paused": self.pause_flag.is_set()}}
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, evt)
        except RuntimeError:
            pass

    def request_pause(self) -> None:
        """请求暂停。下一轮循环开头挂起。"""
        if not self.cancel_flag.is_set():
            self.pause_flag.set()
            self._emit_status()

    def request_resume(self) -> None:
        """解除暂停，继续运行。"""
        self.pause_flag.clear()
        self._emit_status()

    def _make_on_event(self) -> Any:
        """构造给同步 run_session 用的 on_event 回调。

        Stage 7：在原有"投队列给 WS"之上加一层"实时持久化"。
        Stage 9：持久化逻辑已抽到 `session_persistence.persist_event`，
                 让 BatchRunner 复用同一份落库行为。
        """
        loop = self.loop
        queue = self.queue
        sid = self.session_id

        def on_event(evt: dict) -> None:
            persist_event(sid, evt)
            if loop is None or loop.is_closed():
                return
            try:
                loop.call_soon_threadsafe(queue.put_nowait, evt)
            except RuntimeError:  # loop 已关
                logger.warning("loop closed when pushing event for %s", sid)

        return on_event

    def _run_blocking(
        self,
        *,
        product_text: str,
        persona: PersonaProfile,
        topic: str,
        max_rounds: int,
        judge_interval: int,
        memory_interval: int,
        who_speaks_first: str,
        opening_line: str,
        max_rounds_floor: int,
        output_dir: str,
        product_kb_id: Optional[int] = None,
        enterprise_kb_id: Optional[int] = None,
        handbook_id: Optional[int] = None,
        language: str = "zh-CN",
    ) -> None:
        """在 worker 线程中实际跑 run_session。"""
        self.status = "running"
        on_event = self._make_on_event()
        try:
            state = run_session(
                product_text=product_text,
                persona=persona,
                topic=topic,
                max_rounds=max_rounds,
                judge_interval=judge_interval,
                memory_interval=memory_interval,
                output_dir=output_dir,
                judge_fn=judge_dialogue,
                memory_fn=update_session_memory,
                who_speaks_first=who_speaks_first,
                opening_line=opening_line,
                max_rounds_floor=max_rounds_floor,
                on_event=on_event,
                cancel_flag=self.cancel_flag,
                pause_flag=self.pause_flag,
                session_id=self.session_id,
                product_kb_id=product_kb_id,
                enterprise_kb_id=enterprise_kb_id,
                handbook_id=handbook_id,
                language=language,
            )
            self.final_state = state
            self.status = "cancelled" if state.outcome == "CANCELLED" else "done"

            # 持久化收尾：更新 sessions 行（保留过程中累计的 latest_memory）
            try:
                with storage_db.connection_scope() as conn:
                    row = storage_db.get_session_by_id(conn, self.session_id)
                    summary = (row or {}).get("summary") or {}
                    summary.update({
                        "outcome": state.outcome,
                        "total_rounds": state.round_idx,
                        "persona_turns": sum(
                            1 for t in state.full_history if t.speaker == "persona"
                        ),
                        "sales_turns": sum(
                            1 for t in state.full_history if t.speaker == "sales"
                        ),
                        # 终态画像兜底（无 memory_update 时也有值）
                        "latest_memory": state.session_memory.model_dump(),
                    })
                    storage_db.update_session(
                        conn,
                        self.session_id,
                        status=self.status,
                        ended_at=storage_db._now_iso(),
                        summary=summary,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("update_session on finish failed for %s: %s",
                               self.session_id, exc)

        except Exception as exc:  # noqa: BLE001
            self.status = "failed"
            self.error = f"{type(exc).__name__}: {exc}"
            logger.exception("session %s failed: %s", self.session_id, exc)
            # 上抛一条 log 事件给前端
            on_event({"type": "log", "data": {
                "level": "error", "message": self.error,
            }})
            try:
                with storage_db.connection_scope() as conn:
                    storage_db.update_session(
                        conn,
                        self.session_id,
                        status="failed",
                        ended_at=storage_db._now_iso(),
                        summary={"error": self.error},
                    )
            except Exception:
                pass

        finally:
            # 归还并发名额（无论成功/失败/中断都要放，避免名额泄漏把闸门锁死）
            if self.holds_slot:
                self.holds_slot = False
                release_session_slot()
            # 无论成功/失败/中断，最后塞 sentinel 通知 stream 协程退出
            if self.loop and not self.loop.is_closed():
                try:
                    self.loop.call_soon_threadsafe(
                        self.queue.put_nowait, _QUEUE_SENTINEL
                    )
                except RuntimeError:
                    pass

    def start_in_executor(self, **kwargs: Any) -> None:
        """在线程池里启动一场 session。必须先在主协程内调用以捕获 running loop。"""
        if self.future is not None:
            raise RuntimeError(f"SessionRunner {self.session_id} 已启动")
        self.loop = asyncio.get_running_loop()
        self.future = _executor.submit(self._run_blocking, **kwargs)

        # 标记 DB 中已 started
        try:
            with storage_db.connection_scope() as conn:
                storage_db.update_session(
                    conn,
                    self.session_id,
                    status="running",
                    started_at=storage_db._now_iso(),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("update_session on start failed for %s: %s",
                           self.session_id, exc)

    async def stream_events(self, websocket: Any) -> None:
        """主 WS 协程：从 queue 取事件 send_json，遇 sentinel 退出。

        websocket 必须已 accept()。
        """
        while True:
            evt = await self.queue.get()
            if evt is _QUEUE_SENTINEL:
                break
            try:
                await websocket.send_json(evt)
            except Exception as exc:  # noqa: BLE001
                # 客户端断开：标 cancel 并退出
                logger.info("ws send failed for %s, requesting cancel: %s",
                            self.session_id, exc)
                self.request_cancel()
                break


# 全局活跃 runner 注册表
_active_runners: dict[str, SessionRunner] = {}
_registry_lock = threading.Lock()


def register_runner(runner: SessionRunner) -> None:
    with _registry_lock:
        _active_runners[runner.session_id] = runner


def get_runner(session_id: str) -> Optional[SessionRunner]:
    with _registry_lock:
        return _active_runners.get(session_id)


def remove_runner(session_id: str) -> None:
    with _registry_lock:
        _active_runners.pop(session_id, None)


def list_runners() -> list[dict[str, Any]]:
    with _registry_lock:
        return [
            {
                "session_id": r.session_id,
                "status": r.status,
                "queue_size": r.queue.qsize(),
                "cancelled": r.cancel_flag.is_set(),
            }
            for r in _active_runners.values()
        ]
