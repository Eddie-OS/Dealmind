"""单一职责：把 run_session 流出的事件实时写入 SQLite。

设计：
    - 不依赖 asyncio / WebSocket / FastAPI；纯同步同线程，
      既可在 SessionRunner._make_on_event 里组合用，
      也可在 BatchRunner 里独立用（Stage 9）。
    - 任何 DB 异常都"吃掉 + 打日志"，绝不阻断会话主流程。
    - 这里只处理 6 类已落库事件：
        persona_turn / sales_turn / judge_feedback /
        coach_review / memory_update
      其它事件（log/turn_skipped/cancelled/done 等）只用于推 WS，本函数忽略。
"""

from __future__ import annotations

import logging
from typing import Any

from src.storage import db as storage_db


logger = logging.getLogger(__name__)


def persist_event(session_id: str, evt: dict[str, Any]) -> None:
    """把单条 on_event 事件落库。对未知 type 直接 no-op。"""
    etype = evt.get("type")
    data = evt.get("data") or {}
    try:
        if etype in ("persona_turn", "sales_turn"):
            turn = data.get("turn") or {}
            with storage_db.connection_scope() as conn:
                storage_db.create_turn(
                    conn,
                    session_id=session_id,
                    idx=int(turn.get("idx", 0)),
                    role=turn.get("speaker")
                         or ("persona" if etype == "persona_turn" else "sales"),
                    content=turn.get("content", ""),
                    stage=data.get("stage"),
                    metadata=turn.get("metadata"),
                    created_at=turn.get("created_at"),
                )
        elif etype == "judge_feedback":
            jf = data.get("judge_feedback") or {}
            with storage_db.connection_scope() as conn:
                storage_db.create_evaluation(
                    conn,
                    session_id=session_id,
                    evaluator_role="judge",
                    turn_idx=data.get("round_idx"),
                    score=jf.get("sales_score"),
                    feedback=jf,
                )
        elif etype == "coach_review":
            cr = data.get("coach_review") or {}
            with storage_db.connection_scope() as conn:
                storage_db.create_evaluation(
                    conn,
                    session_id=session_id,
                    evaluator_role="coach",
                    turn_idx=None,
                    score=None,
                    feedback=cr,
                )
        elif etype == "memory_update":
            mem = data.get("session_memory") or {}
            with storage_db.connection_scope() as conn:
                row = storage_db.get_session_by_id(conn, session_id)
                current = (row or {}).get("summary") or {}
                current["latest_memory"] = mem
                current["latest_memory_round"] = data.get("round_idx")
                storage_db.update_session(conn, session_id, summary=current)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist event %s for %s failed: %s",
                       etype, session_id, exc)
