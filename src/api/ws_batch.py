"""Stage 9：WebSocket 端点 /ws/batch/{batch_id}。

行为与 /ws/session/{id}/live 完全对称：
1. accept → grace 5s 等 BatchRunner 出现
2. sender 协程：runner.stream_events(ws)
3. receiver 协程：监听 {"type":"cancel"} / "ping"
4. 任一退出即关 ws
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.batch.runner import get_batch_runner


logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/batch/{batch_id}")
async def batch_live(websocket: WebSocket, batch_id: int) -> None:
    await websocket.accept()
    logger.info("ws connected for batch %s", batch_id)

    runner = get_batch_runner(batch_id)
    waited = 0.0
    while runner is None and waited < 5.0:
        await asyncio.sleep(0.2)
        waited += 0.2
        runner = get_batch_runner(batch_id)

    if runner is None:
        await websocket.send_json({
            "type": "log",
            "data": {
                "level": "error",
                "message": (
                    f"batch {batch_id} 未找到活跃 runner（已结束 / 不存在）；"
                    "如需查看历史，请走 GET /api/batch/{id}"
                ),
            },
        })
        await websocket.close(code=1008)
        return

    sender_task = asyncio.create_task(runner.stream_events(websocket))
    receiver_task = asyncio.create_task(_recv_loop(websocket, runner, batch_id))

    done, pending = await asyncio.wait(
        {sender_task, receiver_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()

    try:
        await websocket.close()
    except Exception:
        pass
    logger.info("ws closed for batch %s", batch_id)


async def _recv_loop(websocket: WebSocket, runner, batch_id: int) -> None:
    try:
        while True:
            msg = await websocket.receive_json()
            mtype = (msg or {}).get("type", "")
            if mtype == "cancel":
                logger.info("client requested cancel via ws for batch %s", batch_id)
                runner.request_cancel()
            elif mtype == "ping":
                await websocket.send_json({"type": "pong", "data": {}})
    except WebSocketDisconnect:
        logger.info("client disconnected ws for batch %s", batch_id)
        # 关掉 ws 不意味着停 batch（batch 可能跑很久，用户只是关页面）
    except Exception as exc:  # noqa: BLE001
        logger.info("ws recv loop exit for batch %s: %s", batch_id, exc)
