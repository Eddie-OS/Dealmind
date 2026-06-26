"""市场事实表研究节点（② 深度研究）。

目标：在对话开始前，对「当前手册对应的产品 × persona 所在市场」做一轮真实研究，
落地一份结构化「市场事实表」(MarketFactSheet) 注入销冠，让销冠开口就能给出
当地货币的本品报价 / 竞品报价 / 促销分期 / 政策法规 / 本地化卖点。

设计：
- **取证靠 web_search**：信源被锁定在该市场域名（locales.market_domains），不跨境；
- **蒸馏靠 LLM**：只允许基于检索到的证据填表，证据里没有的价格一律留空 —— 不许编；
- **缓存按 (handbook_id, country_code)**：同市场同产品多个 persona 复用，省 quota；
- **失败安全**：web_search 不可用 / 无证据时仍返回一张「价格留空 + 标注未取到」的表，
  不抛异常，不污染对话主流程。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from src.llm import LLMCallError, LLMJsonParseError, call_llm_json
from src.locales import get_market
from src.storage import db
from src.tools.web_search import run_web_search

logger = logging.getLogger(__name__)

_MAX_COMPETITORS = 3          # 竞品研究上限，控制 web_search 调用次数与 quota
_SEARCH_TOP_K = 3
_DEFAULT_MAX_AGE_DAYS = 30    # 缓存新鲜度窗口


# ---------------------------------------------------------------------------
# 手册 → 产品名 / 竞品名
# ---------------------------------------------------------------------------


def _derive_product_and_competitors(
    handbook: Optional[dict[str, Any]],
) -> tuple[str, list[str]]:
    """从 handbook 结构里提取「研究用产品名」和「竞品名列表」。

    产品名优先用手册 name；竞品取 competitor_points[].vs 去重。
    华为兜底：拿不到竞品时返回空列表（researcher 只研究本品）。
    """
    if not handbook:
        return "华为平板", []
    product_name = (handbook.get("name") or "").strip() or "华为平板"
    struct = handbook.get("structure_json") or {}
    if not isinstance(struct, dict):
        struct = {}
    competitors: list[str] = []
    for it in struct.get("competitor_points") or []:
        if not isinstance(it, dict):
            continue
        vs = (it.get("vs") or "").strip()
        if vs and vs not in competitors:
            competitors.append(vs)
    return product_name, competitors[:_MAX_COMPETITORS]


# ---------------------------------------------------------------------------
# web_search 取证
# ---------------------------------------------------------------------------


def _collect_evidence(
    *,
    product_name: str,
    competitors: list[str],
    market,
) -> tuple[list[str], list[str]]:
    """对本品 + 竞品 + 促销/政策跑锁定信源的 web_search，返回 (证据片段, 来源URL)。"""
    domains = list(market.market_domains)
    cur = market.currency
    queries: list[str] = [
        f"{product_name} {market.name_en} price {cur} 价格",
        f"{product_name} {market.name_en} promotion installment warranty 促销 分期 保修",
    ]
    for comp in competitors:
        queries.append(f"{comp} {market.name_en} price {cur}")

    evidence: list[str] = []
    sources: list[str] = []
    for q in queries:
        res = run_web_search(q, _SEARCH_TOP_K, include_domains=domains)
        if not isinstance(res, dict) or res.get("error"):
            logger.info("market_research web_search 跳过（%s）：q=%s", res, q)
            continue
        answer = (res.get("answer") or "").strip()
        if answer:
            evidence.append(f"[查询] {q}\n[综述] {answer}")
        for item in res.get("results") or []:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("content") or item.get("snippet") or "").strip()
            if not (title or content):
                continue
            evidence.append(f"[查询] {q}\n[标题] {title}\n[来源] {url}\n[摘要] {content}")
            if url:
                sources.append(url)
    # 去重 sources，保序
    seen: set[str] = set()
    sources = [u for u in sources if not (u in seen or seen.add(u))]
    return evidence, sources


# ---------------------------------------------------------------------------
# LLM 蒸馏
# ---------------------------------------------------------------------------


_EMPTY_SHEET = {
    "own_product": {"name": "", "price": "", "channels": []},
    "competitors": [],
    "promotions": [],
    "policies": [],
    "local_selling_points": [],
    "currency": "",
    "evidence_quality": "none",
    "notes": "",
}


def _distill_sheet(
    *,
    product_name: str,
    competitors: list[str],
    market,
    evidence: list[str],
) -> dict[str, Any]:
    """把 web_search 证据蒸馏成 MarketFactSheet。无证据时返回价格留空的空表。"""
    base = json.loads(json.dumps(_EMPTY_SHEET))  # deep copy
    base["own_product"]["name"] = product_name
    base["currency"] = market.currency
    if not evidence:
        base["notes"] = "未取到本地实价证据（web_search 无结果或不可用）。"
        return base

    evidence_text = "\n\n---\n\n".join(evidence[:12])
    comp_hint = "、".join(competitors) if competitors else "（手册未列竞品）"
    system_prompt = (
        "你是一名严谨的市场调研分析员。你只能基于给定的检索证据填写市场事实表，"
        "证据里没有出现的价格 / 数字一律留空字符串，绝对禁止凭印象编造或估算。"
        "你的整个回复必须是可被 json.loads 直接解析的 JSON 对象，不要 markdown。"
    )
    user_prompt = (
        f"## 任务\n"
        f"为「{product_name}」在 **{market.name_cn}（{market.name_en}）** 市场整理一份事实表。\n"
        f"货币锁定为 **{market.currency}（{market.currency_symbol}）**，所有价格用该货币表述。\n"
        f"关注竞品：{comp_hint}。\n\n"
        f"## 检索证据（只能用这里的信息）\n{evidence_text}\n\n"
        f"## 输出 JSON schema（严格）\n"
        "{\n"
        '  "own_product": {"name": "产品名", "price": "本品当地报价(证据无则空串)", "channels": ["渠道名"]},\n'
        '  "competitors": [{"name": "竞品名", "price": "当地报价(证据无则空串)", "note": "一句话差异"}],\n'
        '  "promotions": ["当地促销/分期/赠品要点"],\n'
        '  "policies": ["保修/进口/合规等政策要点"],\n'
        '  "local_selling_points": ["结合当地市场的卖点话术，可结合证据中的痛点"],\n'
        f'  "currency": "{market.currency}",\n'
        '  "evidence_quality": "high|medium|low",\n'
        '  "notes": "重要说明，如哪些数据没查到"\n'
        "}\n\n"
        "规则：\n"
        "1. price 字段必须能在证据里找到出处，否则留空字符串并在 notes 里说明；\n"
        "2. 数组无内容就给空数组 []，不要编占位；\n"
        "3. local_selling_points 可基于证据中的当地价格/竞品/痛点提炼，但不得虚构参数。"
    )
    try:
        raw = call_llm_json(system_prompt, user_prompt, temperature=0.2)
    except (LLMCallError, LLMJsonParseError) as exc:
        logger.warning("market_research 蒸馏失败：%s", exc)
        base["notes"] = f"证据已取到但蒸馏失败：{exc}"
        return base
    if not isinstance(raw, dict):
        base["notes"] = "蒸馏输出非对象。"
        return base

    # 规整：补齐缺失字段，保证 schema 稳定
    sheet = json.loads(json.dumps(_EMPTY_SHEET))
    op = raw.get("own_product") or {}
    sheet["own_product"] = {
        "name": str(op.get("name") or product_name),
        "price": str(op.get("price") or ""),
        "channels": [str(c) for c in (op.get("channels") or []) if c],
    }
    comps = []
    for c in raw.get("competitors") or []:
        if not isinstance(c, dict):
            continue
        comps.append({
            "name": str(c.get("name") or ""),
            "price": str(c.get("price") or ""),
            "note": str(c.get("note") or ""),
        })
    sheet["competitors"] = comps
    sheet["promotions"] = [str(x) for x in (raw.get("promotions") or []) if x]
    sheet["policies"] = [str(x) for x in (raw.get("policies") or []) if x]
    sheet["local_selling_points"] = [
        str(x) for x in (raw.get("local_selling_points") or []) if x
    ]
    sheet["currency"] = str(raw.get("currency") or market.currency)
    sheet["evidence_quality"] = str(raw.get("evidence_quality") or "low")
    sheet["notes"] = str(raw.get("notes") or "")
    return sheet


# ---------------------------------------------------------------------------
# 对外：研究 / 缓存读取 / 缓存优先
# ---------------------------------------------------------------------------


def research_market(
    *,
    handbook_id: Optional[int],
    country_code: str,
    conn=None,
) -> dict[str, Any]:
    """对 (handbook_id, country_code) 跑一轮研究并写入缓存，返回缓存行（含 facts/sources）。

    永不抛：任何环节失败都落一张「尽力而为」的表。
    """
    cc = (country_code or "").upper()
    market = get_market(cc)

    own_conn = conn is None
    if own_conn:
        conn = db.get_connection()
    try:
        handbook = db.get_handbook(conn, int(handbook_id)) if handbook_id else None
        product_name, competitors = _derive_product_and_competitors(handbook)
        evidence, sources = _collect_evidence(
            product_name=product_name, competitors=competitors, market=market,
        )
        sheet = _distill_sheet(
            product_name=product_name,
            competitors=competitors,
            market=market,
            evidence=evidence,
        )
        row = db.upsert_market_facts(
            conn,
            handbook_id=handbook_id,
            country_code=cc,
            product_name=product_name,
            facts=sheet,
            sources=sources,
        )
        if own_conn:
            conn.commit()
        return row
    finally:
        if own_conn:
            conn.close()


def _is_fresh(researched_at: str, max_age_days: int) -> bool:
    try:
        dt = datetime.fromisoformat(researched_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - dt
        return age.days < max_age_days
    except Exception:
        return False


def get_or_research(
    *,
    handbook_id: Optional[int],
    country_code: str,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    force: bool = False,
    conn=None,
) -> Optional[dict[str, Any]]:
    """缓存优先：命中且新鲜直接返回；否则现研究。country_code 为空/GLOBAL 时跳过（返回 None）。"""
    cc = (country_code or "").upper()
    if not cc or cc == "GLOBAL":
        return None

    own_conn = conn is None
    if own_conn:
        conn = db.get_connection()
    try:
        if not force:
            cached = db.get_market_facts(conn, handbook_id=handbook_id, country_code=cc)
            if cached and _is_fresh(cached.get("researched_at") or "", max_age_days):
                return cached
        return research_market(handbook_id=handbook_id, country_code=cc, conn=conn)
    finally:
        if own_conn:
            conn.close()


# ---------------------------------------------------------------------------
# 渲染成 sales_prompt 注入块
# ---------------------------------------------------------------------------


def render_market_facts_block(row: Optional[dict[str, Any]]) -> str:
    """把缓存行渲染成可注入 sales_prompt 的「市场事实表」文本。无表时返回空提示。"""
    if not row or not row.get("facts"):
        return (
            "**市场事实表：未研究**\n\n"
            "本场未预研当地市场实价。涉及当地价格 / 竞品报价时，"
            "按上方信息优先级处理；确无来源时才当场查官网（整场最多 1 次）。"
        )
    f = row["facts"]
    op = f.get("own_product") or {}
    cur = f.get("currency") or ""
    lines: list[str] = []
    lines.append(
        f"**市场事实表**（{row.get('product_name', '')} · 货币 {cur} · "
        f"研究于 {row.get('researched_at', '')[:10]} · 证据强度 {f.get('evidence_quality', 'low')}）"
    )
    lines.append("> 以下为对话前预研的当地实况，可直接引用；价格留空表示未查到，别编。\n")

    own_price = op.get("price") or "（未查到，按手册/官网口径）"
    own_channels = "、".join(op.get("channels") or []) or "—"
    lines.append(f"### 本品当地行情\n- 报价：{own_price}\n- 渠道：{own_channels}")

    comps = f.get("competitors") or []
    if comps:
        comp_lines = "\n".join(
            f"  - **{c.get('name', '')}**：{c.get('price') or '（未查到）'}"
            + (f" — {c.get('note')}" if c.get("note") else "")
            for c in comps
        )
        lines.append(f"### 竞品当地行情\n{comp_lines}")

    promos = f.get("promotions") or []
    if promos:
        lines.append("### 当地促销 / 分期\n" + "\n".join(f"  - {x}" for x in promos))

    policies = f.get("policies") or []
    if policies:
        lines.append("### 当地政策 / 保修\n" + "\n".join(f"  - {x}" for x in policies))

    points = f.get("local_selling_points") or []
    if points:
        lines.append("### 本地化卖点话术\n" + "\n".join(f"  - {x}" for x in points))

    notes = f.get("notes")
    if notes:
        lines.append(f"> 备注：{notes}")
    return "\n\n".join(lines)
