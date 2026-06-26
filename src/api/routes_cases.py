"""Stage 11：销售案例集 REST API。

GET    /api/cases                   分页 + 筛选（source/persona_id/tag/keyword）
GET    /api/cases/sources           各 source 计数（前端 tab 徽标）
GET    /api/cases/{id}              详情
PATCH  /api/cases/{id}              更新 title/why_excellent/tags/votes
DELETE /api/cases/{id}              删除一条
POST   /api/cases/reseed_preset     若表空则重跑 preset（方便开发）
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.cases.seed import seed_preset_cases_if_empty
from src.storage import db as storage_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cases", tags=["sales_cases"])


# ============================================================
# Pydantic
# ============================================================

class CaseUpdate(BaseModel):
    title: Optional[str] = None
    scene: Optional[str] = None
    why_excellent: Optional[str] = None
    tags: Optional[list[str]] = None
    persona_tags: Optional[list[str]] = None
    votes: Optional[int] = Field(default=None, ge=0)


# ============================================================
# 1. 列表（分页 + 筛选）
# ============================================================

@router.get("", summary="销售案例列表（分页 + 筛选）")
def list_cases(
    source: Optional[str] = Query(
        None, description="judge_auto / coach_auto / manual / preset"
    ),
    persona_id: Optional[int] = Query(None),
    session_id: Optional[str] = Query(None),
    tag: Optional[str] = Query(None, description="单标签精确匹配（JSON 子串）"),
    keyword: Optional[str] = Query(None, description="title/scene/raw_content 模糊"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    if source and source not in ("judge_auto", "coach_auto", "manual", "preset"):
        raise HTTPException(400, f"source 取值非法: {source}")
    offset = (page - 1) * page_size
    with storage_db.connection_scope() as conn:
        items, total = storage_db.list_sales_cases(
            conn,
            source=source,
            persona_id=persona_id,
            session_id=session_id,
            tag=tag,
            keyword=keyword,
            limit=page_size,
            offset=offset,
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ============================================================
# 2. 各 source 计数（前端 tab 徽标 + 全部）
# ============================================================

@router.get("/sources", summary="各 source 计数")
def get_sources_count() -> dict[str, Any]:
    sources = ("judge_auto", "coach_auto", "manual", "preset")
    with storage_db.connection_scope() as conn:
        total = storage_db.count_sales_cases(conn)
        by_source = {
            s: storage_db.count_sales_cases(conn, source=s) for s in sources
        }
    return {"total": total, "by_source": by_source}


# ============================================================
# 3. 详情
# ============================================================

@router.get("/{case_id}", summary="案例详情")
def get_case(case_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        case = storage_db.get_sales_case(conn, case_id)
    if not case:
        raise HTTPException(404, f"case {case_id} 不存在")
    return case


# ============================================================
# 4. 更新
# ============================================================

@router.patch("/{case_id}", summary="更新 title / why / tags / votes")
def update_case(case_id: int, payload: CaseUpdate) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        existing = storage_db.get_sales_case(conn, case_id)
        if not existing:
            raise HTTPException(404, f"case {case_id} 不存在")
        fields = {
            k: v for k, v in payload.model_dump(exclude_unset=True).items()
            if v is not None
        }
        if not fields:
            return existing
        case = storage_db.update_sales_case(conn, case_id, **fields)
    return case


# ============================================================
# 5. 删除
# ============================================================

@router.delete("/{case_id}", summary="删除案例")
def delete_case(case_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        ok = storage_db.delete_sales_case(conn, case_id)
    if not ok:
        raise HTTPException(404, f"case {case_id} 不存在")
    return {"ok": True, "deleted_id": case_id}


# ============================================================
# 6. 重跑 preset 预填（开发辅助；为空表才会写入）
# ============================================================

@router.post("/reseed_preset", summary="若案例表为空则重新导入 preset")
def reseed_preset() -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        inserted = seed_preset_cases_if_empty(conn)
    return {"inserted": inserted}
