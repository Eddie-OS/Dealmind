"""B2 · Handbook 抽取后台任务

由 routes_handbook.trigger_extract_endpoint 通过 threading.Thread 调起。
全程不抛异常 — 失败也要把 status 写回 failed + 错误日志。
"""
from __future__ import annotations

import logging
from typing import Any

from src.analyzers.handbook_extractor import (
    PLAYBOOK_DOC_TYPE,
    extract_handbook_structure,
    extract_playbook_structure,
)
from src.storage import db as sdb


logger = logging.getLogger(__name__)


def _concat_parsed_text(files: list[dict[str, Any]]) -> str:
    """把多份 parsed_text 拼起来，每份前面加 [filename] 行头。"""
    parts: list[str] = []
    for f in files:
        txt = (f.get("parsed_text") or "").strip()
        if not txt:
            continue
        parts.append(f"\n\n===== {f.get('filename', '(unnamed)')} =====\n\n{txt}")
    return "".join(parts).strip()


def run_extract_in_background(
    handbook_id: int, doc_type: str = "handbook_135910"
) -> None:
    """B2 后台任务入口。

    doc_type:
      - "handbook_135910"（默认）：旧 1/3/3/5/9/10 结构；
      - "playbook_v1"：新「按人设 + 4 章流程」结构（变长）。
    """
    log_buf: list[str] = [
        f"[handbook_id={handbook_id}] extract started (doc_type={doc_type})"
    ]
    try:
        with sdb.connection_scope() as conn:
            hb = sdb.get_handbook(conn, handbook_id)
            if not hb:
                logger.warning("[extract_runner] handbook %s 不存在", handbook_id)
                return
            files = sdb.list_handbook_files(conn, handbook_id)
        parsed_files = [
            f for f in files
            if (f.get("parsed_text") or "").strip()
            and f.get("status") == "parsed"
        ]
        if not parsed_files:
            _fail(handbook_id, log_buf, "无可用 parsed 文件")
            return

        text = _concat_parsed_text(parsed_files)
        log_buf.append(
            f"concat parsed_text: {len(parsed_files)} files, {len(text)} chars"
        )

        if doc_type == PLAYBOOK_DOC_TYPE:
            struct, warnings = extract_playbook_structure(
                parsed_text=text,
                product_name=hb.get("name") or "",
            )
            log_buf.extend(f"warn: {w}" for w in (warnings or []))
            has_real_content = bool(
                (struct.get("open") or {}).get("persona_openers")
                or struct.get("say")
            )
            if not has_real_content:
                _fail(handbook_id, log_buf, "playbook 抽取无实质内容（开场/卖点为空）")
                return
        else:
            struct, warnings = extract_handbook_structure(
                parsed_text=text,
                product_name=hb.get("name") or "",
            )
            log_buf.extend(f"warn: {w}" for w in (warnings or []))

            # 判定：是否构造出非占位的实质内容
            intro_text = (struct.get("intro_1") or {}).get("text") or ""
            sells_text = [
                (s.get("text") or "")
                for s in (struct.get("selling_points") or [])
            ]
            has_real_content = any(
                t and "待补充" not in t and "未明确提及" not in t
                for t in [intro_text, *sells_text]
            )

            if not has_real_content:
                _fail(handbook_id, log_buf, "LLM 抽取结果全部为占位，无可用结构")
                return

        with sdb.connection_scope() as conn:
            sdb.update_handbook(
                conn, handbook_id,
                structure=struct,
                status="ready",
                bump_version=True,
                extraction_log="\n".join(log_buf + ["done"]),
            )
        logger.info(
            "[extract_runner] handbook=%s ready (warns=%d)",
            handbook_id, len(warnings or []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[extract_runner] unexpected error")
        _fail(handbook_id, log_buf, f"unexpected: {type(exc).__name__}: {exc}")


def _fail(handbook_id: int, log_buf: list[str], msg: str) -> None:
    log_buf.append(f"FAIL: {msg}")
    try:
        with sdb.connection_scope() as conn:
            sdb.update_handbook(
                conn, handbook_id,
                status="failed",
                extraction_log="\n".join(log_buf),
            )
    except Exception:  # noqa: BLE001
        logger.exception("写 failed status 也失败")
