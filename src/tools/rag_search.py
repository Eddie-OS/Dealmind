"""内置 RAG 检索工具（Stage 14）。

4 个工具一一对应蓝图：
- ``search_product_kb``：检索当前会话绑定的产品知识库。
- ``search_enterprise_kb``：检索当前会话绑定的企业知识库。
- ``search_sales_cases``：从 ``sales_cases`` 表里按关键词检索历史精彩案例。
- ``search_excellent_phrases``：从「优秀话术库」检索历史沉淀的单条优秀销冠话术。

所有工具均做了"无 kb / 无命中 / Chroma 异常"的优雅降级——返回空列表
而不是抛异常，由 ``run_tool_safe`` 包装后传回 LLM。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.storage.db import get_connection
from src.tools.registry import ToolContext, tool

logger = logging.getLogger(__name__)


_TEXT_LIMIT = 600   # 单个 chunk 文本截断，避免一次 tool result 几千 token
_MAX_TOP_K = 8


# ---------------------------------------------------------------------------
# 通用：调 KBStore
# ---------------------------------------------------------------------------


def _kb_query(
    kb_id: Optional[int],
    kb_type: str,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    if not kb_id or not (query or "").strip():
        return []
    try:
        from src.rag.kb_store import KBStore  # 延迟导入：CLI 模式可无 chroma
        store = KBStore(int(kb_id), kb_type)
        hits = store.query(query.strip(), top_k=top_k, scope_kb_only=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("KB query failed (kb=%s, type=%s): %s", kb_id, kb_type, exc)
        return []
    out: list[dict[str, Any]] = []
    for h in hits:
        text = (h.get("text") or "")
        if len(text) > _TEXT_LIMIT:
            text = text[:_TEXT_LIMIT] + "…"
        meta = h.get("metadata") or {}
        out.append({
            "id": h.get("id"),
            "text": text,
            "filename": meta.get("filename") or meta.get("file_name"),
            "section": meta.get("section"),
            "score": h.get("score"),
        })
    return out


# ---------------------------------------------------------------------------
# 1. search_product_kb
# ---------------------------------------------------------------------------


class _ProductKBArgs(BaseModel):
    query: str = Field(..., description="检索查询，建议为客户提出的问题或核心异议关键词，越具体越好")
    top_k: int = Field(3, ge=1, le=_MAX_TOP_K, description="返回前 K 条命中，1-8")


@tool(
    name="search_product_kb",
    description=(
        "检索本次销售会话绑定的产品知识库（华为 MatePad / Mate60 / 手表等产品规格、价格、卖点、"
        "参数对比）。当客户问到具体产品参数、价格、功能差异时优先调用。"
        "注意：不要拿来回答企业/政策/服务承诺类问题——那些请用 search_enterprise_kb。"
        "【重要】知识库文档为英文，查询时请同时包含中文关键词和对应英文术语，"
        "例如：'平板 续航 battery life hours'、'屏幕 分辨率 screen resolution display'，"
        "这样能大幅提高检索命中率。"
    ),
    schema=_ProductKBArgs,
    category="rag",
)
def _search_product_kb(args: _ProductKBArgs, ctx: ToolContext) -> dict[str, Any]:
    hits = _kb_query(ctx.product_kb_id, "product", args.query, args.top_k)
    return {
        "query": args.query,
        "kb_id": ctx.product_kb_id,
        "count": len(hits),
        "hits": hits,
    }


# ---------------------------------------------------------------------------
# 2. search_enterprise_kb
# ---------------------------------------------------------------------------


class _EnterpriseKBArgs(BaseModel):
    query: str = Field(..., description="检索查询，常用于服务/品牌/售后/方法论类问题")
    top_k: int = Field(2, ge=1, le=_MAX_TOP_K, description="返回前 K 条命中，1-8")


@tool(
    name="search_enterprise_kb",
    description=(
        "检索本次销售会话绑定的企业知识库（销售方法论、门店培训、话术 SOP、品牌故事等）。"
        "客户聊到品牌信任、售后服务、退换政策、对比友商品牌或需要销售技巧参考时调用。"
        "【重要】知识库文档为英文，查询时请同时包含中文关键词和对应英文术语，"
        "例如：'销售技巧 objection handling customer'、'成交 closing deal sale'，"
        "这样能大幅提高检索命中率。"
    ),
    schema=_EnterpriseKBArgs,
    category="rag",
)
def _search_enterprise_kb(args: _EnterpriseKBArgs, ctx: ToolContext) -> dict[str, Any]:
    hits = _kb_query(ctx.enterprise_kb_id, "enterprise", args.query, args.top_k)
    return {
        "query": args.query,
        "kb_id": ctx.enterprise_kb_id,
        "count": len(hits),
        "hits": hits,
    }


# ---------------------------------------------------------------------------
# 3. search_sales_cases
# ---------------------------------------------------------------------------


class _CasesArgs(BaseModel):
    query: str = Field(..., description="检索关键词，比如客户类型/异议类型/产品名")
    top_k: int = Field(3, ge=1, le=_MAX_TOP_K, description="返回前 K 条案例，1-8")


@tool(
    name="search_sales_cases",
    description=(
        "检索沉淀的精彩销售案例集（来自历史 judge 高分、coach 推荐、人工收藏、预设训练材料）。"
        "当遇到棘手客户、特殊异议、不知怎么 close 时，先来这里翻翻同类历史是怎么打的。"
    ),
    schema=_CasesArgs,
    category="rag",
)
def _search_sales_cases(args: _CasesArgs, ctx: ToolContext) -> dict[str, Any]:
    q = (args.query or "").strip()
    if not q:
        return {"query": q, "count": 0, "hits": []}
    # 简单 LIKE 检索（避免再上一套向量索引；Phase B 可以替换为 chroma）
    like = f"%{q}%"
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, title, scene, source, why_excellent,
                   persona_tags_json, tags_json, raw_content
            FROM sales_cases
            WHERE title LIKE ? OR scene LIKE ? OR why_excellent LIKE ?
                  OR raw_content LIKE ? OR tags_json LIKE ? OR persona_tags_json LIKE ?
            ORDER BY votes DESC, id DESC
            LIMIT ?
            """,
            (like, like, like, like, like, like, int(args.top_k)),
        ).fetchall()
    finally:
        conn.close()

    hits: list[dict[str, Any]] = []
    for r in rows:
        raw = (r["raw_content"] or "")[:_TEXT_LIMIT]
        if len(r["raw_content"] or "") > _TEXT_LIMIT:
            raw += "…"
        hits.append({
            "id": r["id"],
            "title": r["title"],
            "scene": r["scene"],
            "source": r["source"],
            "why_excellent": (r["why_excellent"] or "")[:300],
            "excerpt": raw,
        })
    return {"query": q, "count": len(hits), "hits": hits}


# ---------------------------------------------------------------------------
# 4. search_excellent_phrases（优秀话术库）
# ---------------------------------------------------------------------------


class _PhrasesArgs(BaseModel):
    query: str = Field(..., description="检索关键词，比如客户异议/卖点/产品名/场景")
    top_k: int = Field(3, ge=1, le=_MAX_TOP_K, description="返回前 K 条优秀话术，1-8")


@tool(
    name="search_excellent_phrases",
    description=(
        "检索「优秀话术库」——历史模拟销售中沉淀下来的、单条经过验证有效的销冠金句"
        "（含客户上文、销冠原话、为什么好、客户购买信号变化）。"
        "当你想参考过去面对同类客户/异议时，哪句话真正打动了客户、推进了成交时调用，"
        "学习并化用这些话术，但要结合当前客户语境改写，不要生硬照搬。"
    ),
    schema=_PhrasesArgs,
    category="rag",
)
def _search_excellent_phrases(args: _PhrasesArgs, ctx: ToolContext) -> dict[str, Any]:
    q = (args.query or "").strip()
    if not q:
        return {"query": q, "count": 0, "hits": []}
    from src.storage import db as sdb
    conn = get_connection()
    try:
        items, _total = sdb.list_excellent_phrases(
            conn, keyword=q, limit=int(args.top_k),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_excellent_phrases failed: %s", exc)
        return {"query": q, "count": 0, "hits": []}
    finally:
        conn.close()

    hits: list[dict[str, Any]] = []
    for it in items:
        sc = (it.get("sales_content") or "")[:_TEXT_LIMIT]
        hits.append({
            "id": it.get("id"),
            "handbook_label": it.get("handbook_label"),
            "customer_question": (it.get("customer_question") or "")[:300],
            "sales_content": sc,
            "excellence_score": it.get("excellence_score"),
            "why_good": (it.get("why_good") or [])[:3],
        })
    return {"query": q, "count": len(hits), "hits": hits}
