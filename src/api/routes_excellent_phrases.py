"""优秀话术库 REST API。

GET    /api/excellent-phrases             分页 + 筛选（group_key / keyword / min_score）
GET    /api/excellent-phrases/groups      各分组计数（前端 tab 徽标）
DELETE /api/excellent-phrases/{id}        删除一条

数据来源：分析任务完成后由 analysis_runner 自动沉淀（source=analysis_auto）。
供「优秀话术库」页面浏览，并供销冠 Agent 的 search_excellent_phrases 工具检索学习。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from src.storage import db as storage_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/excellent-phrases", tags=["excellent_phrases"])

# 与 excellence_scorer.GROUP_ORDER 对齐的分组中文标签
_GROUP_LABEL = {
    "intro": "一句话定位",
    "sell": "核心卖点",
    "comp": "竞品对比",
    "param": "核心参数",
    "faq": "FAQ 应答",
    "demo": "现场演示",
    "off_handbook": "手册外精彩话术",
}


@router.get("", summary="优秀话术列表（分页 + 筛选）")
def list_phrases(
    group_key: Optional[str] = Query(None, description="按 135910 + 手册外分组过滤"),
    keyword: Optional[str] = Query(None, description="话术/客户上文/标签模糊检索"),
    min_score: Optional[float] = Query(None, ge=0, le=10),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    offset = (page - 1) * page_size
    with storage_db.connection_scope() as conn:
        items, total = storage_db.list_excellent_phrases(
            conn,
            group_key=group_key,
            keyword=keyword,
            min_score=min_score,
            limit=page_size,
            offset=offset,
        )
    for it in items:
        it["group_label"] = _GROUP_LABEL.get(it.get("group_key"), it.get("group_key"))
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/groups", summary="各分组计数")
def group_counts() -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        counts = storage_db.count_excellent_phrases_by_group(conn)
    groups = [
        {"key": k, "label": _GROUP_LABEL.get(k, k), "count": counts.get(k, 0)}
        for k in _GROUP_LABEL
        if counts.get(k, 0) > 0
    ]
    return {"groups": groups, "total": sum(counts.values())}


@router.delete("/{phrase_id}", summary="删除一条优秀话术")
def delete_phrase(phrase_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        ok = storage_db.delete_excellent_phrase(conn, phrase_id)
    if not ok:
        raise HTTPException(404, f"phrase_id={phrase_id} 不存在")
    return {"deleted": True, "id": phrase_id}
