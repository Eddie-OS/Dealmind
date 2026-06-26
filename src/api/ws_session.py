"""Stage 6a：WebSocket 端点 /ws/session/{session_id}/live。

设计要点：
1. 客户端连上 → accept() → 找 runner → 调 runner.stream_events(ws)。
2. runner.stream_events 内部从 asyncio.Queue 取事件 send_json。
3. runner 完成（done / cancelled / failed）后会塞 sentinel，stream 协程退出。
4. 客户端可以下行发送 {"type": "cancel"} 来主动中断（或 POST /api/sessions/{id}/cancel）。
   仅关闭 ws（切标签 / 网络抖动 / 冷启动卡顿）**不再**中断会话——runner 在后台继续跑到结束。
5. 短时连不上 runner（client 在 runner 创建前抢连）→ 给 5 秒 grace window 重试。
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.session_runner_async import get_runner


logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/session/{session_id}/live")
async def session_live(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    logger.info("ws connected for session %s", session_id)

    runner = get_runner(session_id)
    # Grace window：前端从 POST /start 到打开 ws 可能竞速，等最多 5 秒
    waited = 0.0
    while runner is None and waited < 5.0:
        await asyncio.sleep(0.2)
        waited += 0.2
        runner = get_runner(session_id)

    if runner is None:
        await websocket.send_json({
            "type": "log",
            "data": {
                "level": "error",
                "message": f"session {session_id} 未找到活跃 runner，请先 POST /api/sessions/{{id}}/start",
            },
        })
        await websocket.close(code=1008)
        return

    # 并发跑 stream_events 和客户端控制消息接收
    sender_task = asyncio.create_task(runner.stream_events(websocket))
    receiver_task = asyncio.create_task(_recv_loop(websocket, runner, session_id))

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
    logger.info("ws closed for session %s", session_id)


async def _recv_loop(websocket: WebSocket, runner, session_id: str) -> None:
    """监听客户端下行消息。
    仅处理 {"type": "cancel"} 和 ping/pong。其他消息忽略。
    """
    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = (msg or {}).get("type", "")
            if msg_type == "cancel":
                logger.info("client requested cancel via ws for %s", session_id)
                runner.request_cancel()
            elif msg_type == "pause":
                logger.info("client requested pause via ws for %s", session_id)
                runner.request_pause()
            elif msg_type == "resume":
                logger.info("client requested resume via ws for %s", session_id)
                runner.request_resume()
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong", "data": {}})
            # 其他消息忽略；不让客户端噪音干扰
    except WebSocketDisconnect:
        # 观察端断开（切标签 / 网络抖动 / 首次冷启动加载 embedder 卡顿）不应中断正在跑的会话——
        # 仅停止本连接推流，runner 继续在后台跑到结束。显式中断仍可走 {"type":"cancel"} 或
        # POST /api/sessions/{id}/cancel。（修复：冷启动期 WS 掉线导致 0 轮 CANCELLED）
        logger.info("client disconnected ws for %s (run continues; no auto-cancel)", session_id)
    except Exception as exc:  # noqa: BLE001
        logger.info("ws recv loop exit for %s: %s", session_id, exc)
