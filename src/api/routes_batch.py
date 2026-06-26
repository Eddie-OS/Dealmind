"""Stage 9：批量测试 REST 端点。

6 个接口：
    GET    /api/batch                  分页列出 batch_jobs
    POST   /api/batch                  创建 + 立刻 start
    GET    /api/batch/{id}             基本信息 + 运行时进度
    GET    /api/batch/{id}/sessions    返回该 batch 关联的所有 session 行（含 outcome）
    POST   /api/batch/{id}/cancel      请求中断
    POST   /api/batch/{id}/resume      续跑（进程重启后 DB 仍为 running 的僵尸任务）
    DELETE /api/batch/{id}             删 batch_jobs 行（不级联删 session）
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.batch.runner import (
    BatchRunner,
    get_batch_runner,
    register_batch_runner,
    remaining_persona_ids,
)
from src.storage import db as storage_db


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/batch", tags=["batch"])


# ============================================================
# Request models
# ============================================================


class CreateBatchRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200,
                      description="批量任务名，仅用于展示")
    persona_ids: list[int] = Field(..., min_length=1, max_length=200,
                                   description="参与会话的 persona id 列表（去重后顺序）")
    product_kb_id: Optional[int] = None
    enterprise_kb_id: Optional[int] = None
    handbook_id: Optional[int] = Field(
        None,
        description="可选，绑定的产品手册 id（Handbook Analysis）。"
        "若不传且全库只有一份 ready Handbook，运行时会自动套用。",
    )
    topic: str = Field("学习平板销售模拟", max_length=200)
    language: str = Field("zh-CN", description="对话语言（BCP-47 子集），开场白由 LLM 按此语言生成")
    max_rounds: int = Field(30, ge=8, le=80)
    judge_interval: int = Field(3, ge=1, le=10)
    memory_interval: int = Field(3, ge=1, le=10)


# ============================================================
# Helpers
# ============================================================


def _enrich_with_runtime(row: dict[str, Any]) -> dict[str, Any]:
    """合并 DB 行 + 活跃 runner 的实时进度，给前端单一字段使用。

    is_active 仅在 runner 真的还在跑（status='running'）时为 True。
    已完成 / 已取消 / 已失败的 runner 即便还驻留在 registry 中也算 inactive。
    """
    runner = get_batch_runner(row["id"])
    runtime: dict[str, Any] = {
        "runtime_status": row.get("status"),
        "is_active": False,
    }
    if runner is not None:
        runtime["runtime_status"] = runner.status
        runtime["is_active"] = runner.status == "running"
        runtime.update({
            "current_round": runner.current_round,
            "current_session_id": runner.current_session_id,
            "live_completed": runner.completed_count,
            "live_failed": runner.failed_count,
            "live_cancelled": runner.cancelled_count,
        })
    # 僵尸 running：DB 显示进行中，但内存无 runner（后端崩溃/重启）
    stale_running = (
        row.get("status") == "running"
        and not runtime["is_active"]
    )
    remaining = remaining_persona_ids(row) if stale_running else []
    runtime["stale_running"] = stale_running
    runtime["can_resume"] = stale_running and len(remaining) > 0
    runtime["remaining_count"] = len(remaining)
    return {**row, **runtime}


# ============================================================
# Endpoints
# ============================================================


@router.get("", summary="分页列出 batch_jobs")
def list_batches(
    status_: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    """按 created_at DESC 返回。"""
    offset = (page - 1) * size
    with storage_db.connection_scope() as conn:
        rows, total = storage_db.list_batch_jobs(
            conn, status=status_, limit=size, offset=offset,
        )
    items = [_enrich_with_runtime(r) for r in rows]
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建并立即启动批量任务")
async def create_and_start_batch(req: CreateBatchRequest) -> dict[str, Any]:
    """1. 校验 persona / KB 存在
    2. 创建 batch_jobs 行
    3. 立刻 register + start_in_executor（无需 client 再发 /start）

    返回完整 batch 行 + ws_url。
    """
    # ── 去重保持顺序 ──
    seen: set[int] = set()
    ids: list[int] = []
    for pid in req.persona_ids:
        if pid not in seen:
            seen.add(pid)
            ids.append(pid)
    if not ids:
        raise HTTPException(400, "persona_ids 全部重复或为空")

    # ── 校验 persona / KB ──
    with storage_db.connection_scope() as conn:
        for pid in ids:
            if not storage_db.get_persona_by_id(conn, pid):
                raise HTTPException(404, f"persona id={pid} 不存在")
        if req.product_kb_id is not None and not storage_db.get_kb_by_id(
            conn, req.product_kb_id
        ):
            raise HTTPException(404, f"product_kb_id={req.product_kb_id} 不存在")
        if req.handbook_id is not None and not storage_db.get_handbook(
            conn, req.handbook_id
        ):
            raise HTTPException(404, f"handbook_id={req.handbook_id} 不存在")
        if req.enterprise_kb_id is not None and not storage_db.get_kb_by_id(
            conn, req.enterprise_kb_id
        ):
            raise HTTPException(404, f"enterprise_kb_id={req.enterprise_kb_id} 不存在")

        from src.lang import normalize as normalize_lang
        row = storage_db.create_batch_job(
            conn,
            name=req.name,
            persona_ids=ids,
            product_kb_id=req.product_kb_id,
            enterprise_kb_id=req.enterprise_kb_id,
            handbook_id=req.handbook_id,
            topic=req.topic,
            opening_line=None,
            max_rounds=req.max_rounds,
            judge_interval=req.judge_interval,
            memory_interval=req.memory_interval,
            config={
                "source": "web",
                "language": normalize_lang(req.language),
            },
        )

    batch_id = int(row["id"])
    runner = BatchRunner(batch_id=batch_id)
    register_batch_runner(runner)
    runner.start_in_executor()

    logger.info("batch %s started: %d personas", batch_id, len(ids))
    return {
        **_enrich_with_runtime(row),
        "ws_url": f"/ws/batch/{batch_id}",
    }


@router.get("/{batch_id}", summary="单条 batch 详情 + 实时进度")
def get_batch(batch_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        row = storage_db.get_batch_job(conn, batch_id)
    if not row:
        raise HTTPException(404, f"batch {batch_id} 不存在")
    return _enrich_with_runtime(row)


@router.get(
    "/{batch_id}/sessions",
    summary="该 batch 关联的全部 session（按 batch_index 排序）",
)
def list_batch_sessions(batch_id: int) -> dict[str, Any]:
    """从 batch 行的 session_ids 顺序取出全部 sessions，
    跳过 DB 中已被删的 session_id。"""
    with storage_db.connection_scope() as conn:
        row = storage_db.get_batch_job(conn, batch_id)
        if not row:
            raise HTTPException(404, f"batch {batch_id} 不存在")
        sids: list[str] = row.get("session_ids") or []
        items: list[dict[str, Any]] = []
        for idx, sid in enumerate(sids):
            srow = storage_db.get_session_by_id(conn, sid)
            if not srow:
                continue
            summary = srow.get("summary") or {}
            items.append({
                "batch_index": idx,
                "id": srow["id"],
                "persona_id": srow.get("persona_id"),
                "status": srow.get("status"),
                "outcome": summary.get("outcome"),
                "total_rounds": summary.get("total_rounds") or 0,
                "started_at": srow.get("started_at"),
                "ended_at": srow.get("ended_at"),
                "error": summary.get("error"),
            })
    return {"items": items, "total": len(items)}


@router.post("/{batch_id}/resume", summary="续跑批量任务（跳过已完成的 session）")
async def resume_batch(batch_id: int) -> dict[str, Any]:
    """进程重启后 DB 仍停留在 running、但内存 runner 已丢失时，从已完成场次接着跑。"""
    existing = get_batch_runner(batch_id)
    if existing is not None and existing.status == "running":
        raise HTTPException(409, f"batch {batch_id} 已在运行中")

    with storage_db.connection_scope() as conn:
        row = storage_db.get_batch_job(conn, batch_id)
    if not row:
        raise HTTPException(404, f"batch {batch_id} 不存在")

    if row.get("status") == "completed":
        raise HTTPException(400, "任务已完成，无需续跑")
    if row.get("status") == "cancelled":
        raise HTTPException(400, "任务已中断，请新建批量任务")

    remaining = remaining_persona_ids(row)
    if not remaining:
        finished_at = storage_db._now_iso()
        with storage_db.connection_scope() as conn:
            storage_db.update_batch_job(
                conn, batch_id,
                status="completed",
                ended_at=finished_at,
            )
            row = storage_db.get_batch_job(conn, batch_id)
        return {
            **_enrich_with_runtime(row),
            "resumed": False,
            "message": "全部场次已完成，已标记为 completed",
            "ws_url": f"/ws/batch/{batch_id}",
        }

    runner = BatchRunner(batch_id=batch_id, resume=True)
    register_batch_runner(runner)
    runner.start_in_executor()
    logger.info(
        "batch %s resumed: %d remaining of %d personas",
        batch_id, len(remaining), row.get("total_count"),
    )
    with storage_db.connection_scope() as conn:
        row = storage_db.get_batch_job(conn, batch_id)
    return {
        **_enrich_with_runtime(row),
        "resumed": True,
        "remaining_count": len(remaining),
        "ws_url": f"/ws/batch/{batch_id}",
    }


@router.post("/{batch_id}/cancel", summary="请求中断批量任务")
def cancel_batch(batch_id: int) -> dict[str, Any]:
    runner = get_batch_runner(batch_id)
    if runner is None:
        # 进程重启 / worker 崩溃后，DB 可能仍停留在 running，但内存 runner 已不存在。
        # 这种“僵尸 running”必须允许用户中断，否则前端会永远显示进行中且无法删除。
        with storage_db.connection_scope() as conn:
            row = storage_db.get_batch_job(conn, batch_id)
            if not row:
                raise HTTPException(404, f"batch {batch_id} 不存在")
            if row.get("status") not in ("pending", "running"):
                return {
                    "batch_id": batch_id,
                    "status": row.get("status"),
                    "cancel_requested": False,
                    "stale_runner": True,
                }

            total = int(row.get("total_count") or len(row.get("persona_ids") or []) or 0)
            done = int(row.get("completed_count") or 0)
            failed = int(row.get("failed_count") or 0)
            already_cancelled = int(row.get("cancelled_count") or 0)
            remaining = max(0, total - done - failed - already_cancelled)
            summary = row.get("summary") or {}
            summary.update({
                "cancel_reason": "stale batch runner was not found; force-cancelled by API",
                "stale_runner": True,
            })
            storage_db.update_batch_job(
                conn,
                batch_id,
                status="cancelled",
                ended_at=storage_db._now_iso(),
                cancelled_count=already_cancelled + remaining,
                error_msg="stale runner not found; force-cancelled",
                summary=summary,
            )
        logger.warning("batch %s force-cancelled because runner was missing", batch_id)
        return {
            "batch_id": batch_id,
            "status": "cancelled",
            "cancel_requested": True,
            "stale_runner": True,
        }
    runner.request_cancel()
    return {"batch_id": batch_id, "status": runner.status, "cancel_requested": True}


@router.delete("/{batch_id}", summary="删除 batch_jobs 行（不级联删 session）")
def delete_batch(batch_id: int) -> dict[str, Any]:
    runner = get_batch_runner(batch_id)
    if runner is not None and runner.status == "running":
        raise HTTPException(409, "batch 还在跑，请先 cancel 再删")
    with storage_db.connection_scope() as conn:
        ok = storage_db.delete_batch_job(conn, batch_id)
    if not ok:
        raise HTTPException(404, f"batch {batch_id} 不存在")
    return {"batch_id": batch_id, "deleted": True}
