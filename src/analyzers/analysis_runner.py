"""A1 · 分析任务编排器

负责把一个 analysis_job 从 pending → running → completed/failed 的全流程：
  1) 解析数据源：batch_id 或 session_id → 拉销冠 turns
  2) 拉 Handbook 结构（resolve_default 兜底）
  3) 调 handbook_classifier 做多标签分类
  4) 调 handbook_scorer 做 6 维度打分
  5) 调 report_aggregator 出聚合报告
  6) 写入 turn_classifications + analysis_persona_insights + analysis_jobs.summary_json
  7) 失败 → status=failed + error_msg
  8) 进度 progress 用 (已分类 turn 数 / 总 turn 数) 实时回写

线程模型：
  与 BatchRunner 同模式 —— FastAPI 端点提交到 _analysis_executor，
  在独立线程跑，主事件循环不阻塞。

并发：
  单任务内部分类 / 评分顺序串行（一个 turn 一次 LLM 调用），不并发，
  避免把 LLM provider rate limit 打爆。后续需要时再加 worker。
"""
from __future__ import annotations

import json
import logging
import threading
import traceback
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any, Optional

from src.perf_config import ANALYSIS_TURN_WORKERS
from src.storage import db as sdb


logger = logging.getLogger(__name__)

_analysis_executor = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="analysis-runner"
)

_active_runners: dict[int, "AnalysisRunner"] = {}
_registry_lock = threading.Lock()


# ============================================================
# Registry —— 后续 WS 进度推送 / 取消支持
# ============================================================

def register_runner(runner: "AnalysisRunner") -> None:
    with _registry_lock:
        _active_runners[runner.job_id] = runner


def get_runner(job_id: int) -> Optional["AnalysisRunner"]:
    with _registry_lock:
        return _active_runners.get(job_id)


def remove_runner(job_id: int) -> None:
    with _registry_lock:
        _active_runners.pop(job_id, None)


# ============================================================
# AnalysisRunner
# ============================================================


class AnalysisRunner:
    """单个 analysis_job 的执行器。"""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        self._cancel_flag = threading.Event()
        self._future: Optional[Future] = None

    # ---------------- 公开 API ----------------

    def start_in_executor(self) -> Future:
        """提交到独立线程池跑。"""
        register_runner(self)
        self._future = _analysis_executor.submit(self._run_safe)
        return self._future

    def request_cancel(self) -> None:
        self._cancel_flag.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    # ---------------- 内部 ----------------

    def _run_safe(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            logger.exception("[analysis_runner] job=%s failed", self.job_id)
            try:
                with sdb.connection_scope() as conn:
                    sdb.update_analysis_job(
                        conn,
                        self.job_id,
                        status="failed",
                        error_msg=f"{type(exc).__name__}: {exc}",
                        mark_ended=True,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("write failed status also failed")
        finally:
            remove_runner(self.job_id)

    def _run(self) -> None:
        # 0) 读 job + 数据源
        with sdb.connection_scope() as conn:
            job = sdb.get_analysis_job(conn, self.job_id)
            if not job:
                raise RuntimeError(f"analysis_job {self.job_id} 不存在")
            handbook_id = job.get("handbook_id")
            if not handbook_id:
                raise RuntimeError(
                    "analysis_job 缺少 handbook_id 且全库没有 ready Handbook"
                )
            hb = sdb.get_handbook(conn, int(handbook_id))
            if not hb:
                raise RuntimeError(f"handbook_id={handbook_id} 不存在")

            session_ids = self._resolve_session_ids(conn, job)
            if not session_ids:
                raise RuntimeError("数据源没有任何 session 可分析")

            sdb.update_analysis_job(
                conn,
                self.job_id,
                status="running",
                mark_started=True,
                progress=0.0,
            )

            # 清空旧记录（重跑兼容）
            sdb.delete_turn_classifications(conn, self.job_id)
            sdb.delete_analysis_persona_insights(conn, self.job_id)

            # 拉所有销冠 turns
            turns_payload: list[dict[str, Any]] = []
            for sid in session_ids:
                rows = conn.execute(
                    "SELECT idx, content, metadata_json FROM turns "
                    "WHERE session_id = ? AND role = 'sales' "
                    "ORDER BY idx ASC",
                    (sid,),
                ).fetchall()
                for r in rows:
                    turns_payload.append(
                        {
                            "session_id": sid,
                            "turn_idx": int(r["idx"]),
                            "content": r["content"] or "",
                        }
                    )

        total_turns = len(turns_payload)
        logger.info(
            "[analysis_runner] job=%s start: sessions=%d turns=%d handbook=%s",
            self.job_id, len(session_ids), total_turns, hb["name"],
        )

        if total_turns == 0:
            with sdb.connection_scope() as conn:
                sdb.update_analysis_job(
                    conn,
                    self.job_id,
                    status="completed",
                    total_turns=0,
                    classified_turns=0,
                    progress=1.0,
                    summary={
                        "note": "没有销冠 turn，跳过",
                        "session_ids": session_ids,
                        "handbook_id": handbook_id,
                    },
                    mark_ended=True,
                )
            return

        # 1) 合并分类+评分（A2+A3 一次 LLM），turn 级并发
        from src.analyzers.handbook_turn_analyzer import analyze_turn_once

        struct = hb.get("structure_json") or {}
        if isinstance(struct, str):
            try:
                struct = json.loads(struct)
            except Exception:  # noqa: BLE001
                struct = {}

        all_class_rows: list[dict[str, Any]] = []
        processed = 0
        rows_lock = threading.Lock()
        progress_lock = threading.Lock()
        FLUSH_EVERY = 10
        workers = max(1, min(ANALYSIS_TURN_WORKERS, total_turns))

        with sdb.connection_scope() as conn:
            sdb.update_analysis_job(
                conn, self.job_id,
                total_turns=total_turns, classified_turns=0,
            )

        def _process_turn(t: dict[str, Any]) -> list[dict[str, Any]]:
            if self.cancelled:
                return []
            try:
                label_rows = analyze_turn_once(
                    content=t["content"],
                    handbook_struct=struct,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[analysis_runner] turn failed sess=%s idx=%d: %s",
                    t["session_id"], t["turn_idx"], exc,
                )
                return []
            return [
                {
                    "session_id": t["session_id"],
                    "turn_idx": t["turn_idx"],
                    "category_id": row["category_id"],
                    "confidence": float(row.get("confidence") or 0.0),
                    "scores": row.get("scores") or {},
                    "issues": row.get("issues") or [],
                    "suggestion": row.get("suggestion") or "",
                    "reference_text": row.get("reference_text") or "",
                }
                for row in label_rows
            ]

        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="analysis-turn",
        ) as pool:
            futures = [pool.submit(_process_turn, t) for t in turns_payload]
            for fut in as_completed(futures):
                if self.cancelled:
                    for f in futures:
                        f.cancel()
                    logger.warning("[analysis_runner] job=%s cancelled", self.job_id)
                    with sdb.connection_scope() as conn:
                        sdb.update_analysis_job(
                            conn, self.job_id,
                            status="cancelled",
                            mark_ended=True,
                            classified_turns=processed,
                            progress=processed / max(1, total_turns),
                        )
                    return
                try:
                    turn_rows = fut.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[analysis_runner] future failed: %s", exc)
                    turn_rows = []
                with rows_lock:
                    all_class_rows.extend(turn_rows)
                with progress_lock:
                    processed += 1
                    if (
                        processed % FLUSH_EVERY == 0
                        or processed == total_turns
                    ):
                        with sdb.connection_scope() as conn:
                            sdb.update_analysis_job(
                                conn, self.job_id,
                                classified_turns=processed,
                                progress=processed / total_turns,
                            )

        # 2) 落库：分类+评分
        with sdb.connection_scope() as conn:
            sdb.insert_turn_classifications(conn, self.job_id, all_class_rows)

        # 3) 聚合（A4）
        from src.analyzers.report_aggregator import aggregate_report

        report = aggregate_report(
            job_id=self.job_id,
            session_ids=session_ids,
            handbook=hb,
            classifications=all_class_rows,
        )

        # 4) persona_insights 落库
        with sdb.connection_scope() as conn:
            sdb.insert_analysis_persona_insights(
                conn, self.job_id,
                report.get("persona_insights") or [],
            )
            sdb.update_analysis_job(
                conn, self.job_id,
                status="completed",
                classified_turns=processed,
                progress=1.0,
                summary=report.get("summary") or {},
                mark_ended=True,
            )

        # 4.5) 沉淀「优秀话术库」：把本次分析的优秀话术原声写进 excellent_phrases，
        #      供前端浏览 + 销冠 Agent 在新会话中检索学习。失败不影响主流程。
        try:
            summary = report.get("summary") or {}
            with sdb.connection_scope() as conn:
                n = sdb.persist_excellent_phrases_from_summary(
                    conn,
                    analysis_job_id=self.job_id,
                    handbook_id=int(handbook_id) if handbook_id else None,
                    excellent_by_group=summary.get("excellent_by_group") or {},
                )
            logger.info("[analysis_runner] job=%s 沉淀优秀话术 %d 条", self.job_id, n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[analysis_runner] 沉淀优秀话术失败 job=%s: %s",
                           self.job_id, exc)
        logger.info(
            "[analysis_runner] job=%s done: classified_turns=%d categories=%d",
            self.job_id, processed,
            len(report.get("summary", {}).get("category_coverage") or {}),
        )

    # ---------------- helper ----------------

    @staticmethod
    def _resolve_session_ids(conn, job: dict[str, Any]) -> list[str]:
        """v2 schema：
          - session_id 直接返回
          - batch_id → 走 batch_jobs.session_ids_json（sessions 表无 batch_id 列）
            兜底：按 id 后缀 _bN 模糊匹配，捕捉历史中可能漏写 session_ids 的批次
        """
        if job.get("session_id"):
            return [job["session_id"]]
        bid = job.get("batch_id")
        if not bid:
            return []
        from src.storage import db as _sdb
        batch = _sdb.get_batch_job(conn, int(bid))
        sids = [str(s) for s in (batch.get("session_ids") or []) if s]
        if sids:
            # 过滤掉 DB 中已被删除的 session
            return [
                sid for sid in sids
                if _sdb.get_session_by_id(conn, sid)
            ]
        # 兜底：按 id 后缀 _bN 模糊匹配
        rows = conn.execute(
            "SELECT id FROM sessions WHERE id LIKE ? ORDER BY created_at ASC",
            (f"%_b{int(bid)}",),
        ).fetchall()
        return [r["id"] for r in rows]


# ============================================================
# 公共入口：启动一个分析任务
# ============================================================

def start_analysis_job(
    *,
    batch_id: Optional[int] = None,
    session_id: Optional[str] = None,
    handbook_id: Optional[int] = None,
) -> int:
    """创建并立即异步启动一个 analysis_job，返回 job_id。"""
    with sdb.connection_scope() as conn:
        job_id = sdb.create_analysis_job(
            conn,
            batch_id=batch_id,
            session_id=session_id,
            handbook_id=handbook_id,
        )
    runner = AnalysisRunner(job_id)
    runner.start_in_executor()
    return job_id
