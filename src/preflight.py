"""v0.2.2 真实性补丁 — 会话启动前的"产品事实预检"。

流程：
  1. 从 ``topic`` 抽取核心产品名（正则优先，抓不到再调 LLM）
  2. 用产品名做 KB 检索（product_kb_id）+ web_search（锁 persona 本地市场域名）
  3. 把命中的内容粗解析为 ``ProductFactCard``（定位 / 是否有手写笔 / 屏幕 / 芯片 / 价格 / 是否上市）
  4. 全 0 命中 → confidence="UNCERTAIN"，渲染块明文写"本场禁止任何具体参数"

设计原则：
  - **永不抛**：任何环节失败都返回"UNCERTAIN 卡"，绝不把整场会话搞挂
  - **轻量**：只调一次 LLM（且仅在正则抓不到时）；KB 查 5 条 + web_search 查 3 条
  - **可注入**：返回的 render_block 直接拼到 sales_prompt 顶部，无需 prompt 改造
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from src.locales import DEFAULT_GLOBAL_MARKET, get_market
from src.schema import PersonaProfile, ProductFactCard

logger = logging.getLogger(__name__)


# ============================================================
# Step 1: 从 topic 抽产品名（正则优先）
# ============================================================


# 华为常见型号正则。重点：
#   · 用「前后无字母数字」边界（兼容中文邻接，"手机pura x" 也能匹配）
#   · 顺序"先长后短"，避免 "Mate" 抢走 "Mate 80 Pro"
_BL = r"(?<![a-z0-9])"  # 左边非字母数字
_BR = r"(?![a-z0-9])"   # 右边非字母数字

_PRODUCT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Pura X",       re.compile(rf"{_BL}pura\s*x{_BR}", re.IGNORECASE)),
    ("Mate XT",      re.compile(rf"{_BL}mate\s*xt{_BR}", re.IGNORECASE)),
    ("Mate X6",      re.compile(rf"{_BL}mate\s*x6{_BR}", re.IGNORECASE)),
    ("Mate 90 Pro",  re.compile(rf"{_BL}mate\s*90\s*pro{_BR}", re.IGNORECASE)),
    ("Mate 90",      re.compile(rf"{_BL}mate\s*90{_BR}", re.IGNORECASE)),
    ("Mate 80 Pro",  re.compile(rf"{_BL}mate\s*80\s*pro{_BR}", re.IGNORECASE)),
    ("Mate 80",      re.compile(rf"{_BL}mate\s*80{_BR}", re.IGNORECASE)),
    ("Mate 70 Pro",  re.compile(rf"{_BL}mate\s*70\s*pro{_BR}", re.IGNORECASE)),
    ("Mate 70",      re.compile(rf"{_BL}mate\s*70{_BR}", re.IGNORECASE)),
    ("Mate 60 Pro",  re.compile(rf"{_BL}mate\s*60\s*pro{_BR}", re.IGNORECASE)),
    ("Mate 60",      re.compile(rf"{_BL}mate\s*60{_BR}", re.IGNORECASE)),
    ("Pura 80 Pro",  re.compile(rf"{_BL}pura\s*80\s*pro{_BR}", re.IGNORECASE)),
    ("Pura 80",      re.compile(rf"{_BL}pura\s*80{_BR}", re.IGNORECASE)),
    ("Pura 70 Pro",  re.compile(rf"{_BL}pura\s*70\s*pro{_BR}", re.IGNORECASE)),
    ("Pura 70",      re.compile(rf"{_BL}pura\s*70{_BR}", re.IGNORECASE)),
    ("MatePad Pro 13.2", re.compile(rf"{_BL}matepad\s*pro\s*13\.?2?{_BR}", re.IGNORECASE)),
    ("MatePad Pro 12",   re.compile(rf"{_BL}matepad\s*pro\s*12{_BR}", re.IGNORECASE)),
    ("MatePad Pro 11",   re.compile(rf"{_BL}matepad\s*pro\s*11{_BR}", re.IGNORECASE)),
    ("MatePad Pro",      re.compile(rf"{_BL}matepad\s*pro{_BR}", re.IGNORECASE)),
    ("MatePad 12X",      re.compile(rf"{_BL}matepad\s*12x{_BR}", re.IGNORECASE)),
    ("MatePad 11.5",     re.compile(rf"{_BL}matepad\s*11\.?5?{_BR}", re.IGNORECASE)),
    ("MatePad",          re.compile(rf"{_BL}matepad{_BR}", re.IGNORECASE)),
    ("Watch GT 5",       re.compile(rf"{_BL}watch\s*gt\s*5{_BR}", re.IGNORECASE)),
    ("Watch GT 4",       re.compile(rf"{_BL}watch\s*gt\s*4{_BR}", re.IGNORECASE)),
    ("MateBook X Pro",   re.compile(rf"{_BL}matebook\s*x\s*pro{_BR}", re.IGNORECASE)),
    ("MateBook 14",      re.compile(rf"{_BL}matebook\s*14{_BR}", re.IGNORECASE)),
)


def extract_product_from_topic(topic: str) -> Optional[str]:
    """从 topic 字符串里提取核心产品名。

    策略：
      1. 顺序匹配 _PRODUCT_PATTERNS（先长后短）
      2. 全部没命中 → 返回 None（调用方决定是否走 LLM fallback）
    """
    if not (topic or "").strip():
        return None
    for name, pat in _PRODUCT_PATTERNS:
        if pat.search(topic):
            return name
    return None


def extract_product_with_llm(topic: str) -> Optional[str]:
    """LLM fallback：让 LLM 从 topic 抽产品名。仅在正则没命中时调用。

    失败安全：LLM 不可用 / 解析失败都返回 None。
    """
    from src.llm import LLMCallError, call_llm_json
    try:
        raw = call_llm_json(
            system_prompt=(
                "你只做一件事：从用户提供的销售场景描述里，识别出"
                "本次模拟销售的核心**产品名**（包括子型号），输出 JSON。"
                "如果场景描述是泛泛而谈（没有任何具体型号），返回 product_name=null。"
            ),
            user_prompt=(
                f"销售场景：{topic}\n\n"
                "请输出 JSON：{\"product_name\": \"具体型号或 null\"}\n"
                "示例：\n"
                "  \"卖 Pura X 给学生\" → {\"product_name\": \"Pura X\"}\n"
                "  \"华为零售店各机型对比\" → {\"product_name\": null}\n"
                "  \"推荐一款手机\" → {\"product_name\": null}"
            ),
            temperature=0.0,
        )
    except (LLMCallError, Exception) as exc:  # noqa: BLE001
        logger.debug("LLM 抽取产品名失败：%s", exc)
        return None
    name = (raw or {}).get("product_name")
    if not isinstance(name, str) or not name.strip() or name.strip().lower() == "null":
        return None
    return name.strip()


# ============================================================
# Step 2: 检索 KB + web_search 拿事实
# ============================================================


def _query_product_kb(kb_id: Optional[int], product_name: str) -> list[dict[str, Any]]:
    """直接复用 rag_search 的 _kb_query。失败返回 []。"""
    if not kb_id:
        return []
    try:
        from src.tools.rag_search import _kb_query
        return _kb_query(kb_id, "product", product_name, top_k=5)
    except Exception as exc:  # noqa: BLE001
        logger.warning("preflight: KB 查询失败 kb_id=%s err=%s", kb_id, exc)
        return []


def _query_web_search(product_name: str, market_domains: list[str]) -> dict[str, Any]:
    """调 web_search，已经在工具层锁好 include_domains。失败返回带 error 的 dict。"""
    try:
        from src.tools.web_search import run_web_search
        return run_web_search(
            query=f"{product_name} 规格 参数 价格",
            top_k=3,
            include_domains=market_domains or list(DEFAULT_GLOBAL_MARKET.market_domains),
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


# ============================================================
# Step 3: 把命中粗解析成 ProductFactCard 各字段
# ============================================================


# 这里**故意不做**深度 NLP，只做最简单的"关键词出现 → 标记字段"，避免被噪声带偏。
# 目标是"宁可留空也不要给错"。


_STYLUS_HINTS_POSITIVE = ("m-pencil", "手写笔", "stylus", "支持手写笔")
_STYLUS_HINTS_NEGATIVE = ("不支持手写笔", "no stylus", "without stylus")
_FOLDABLE_HINTS = ("折叠屏", "foldable", "flip", "fold")
# 产品类别推断（粗，按产品名前缀）：手机/平板/笔记本/手表
_CATEGORY_BY_PREFIX = {
    "mate ": "智能手机",
    "pura ": "智能手机",
    "matepad": "平板电脑",
    "matebook": "笔记本电脑",
    "watch": "智能手表",
}
# Pura X 是个特例（小折叠手机），单独覆盖
_CATEGORY_OVERRIDE = {
    "pura x": "折叠屏手机",
    "mate xt": "三折叠手机",
    "mate x6": "折叠屏手机",
}


def _infer_category(product_name: str) -> Optional[str]:
    lc = product_name.lower().strip()
    if lc in _CATEGORY_OVERRIDE:
        return _CATEGORY_OVERRIDE[lc]
    for prefix, cat in _CATEGORY_BY_PREFIX.items():
        if lc.startswith(prefix):
            return cat
    return None


def _scan_evidence_text(corpus: str, product_name: str) -> dict[str, Any]:
    """从全部命中文本里粗提一些事实点。返回字段都是 Optional。"""
    text = corpus.lower()
    facts: dict[str, Any] = {}

    # 手写笔（先看负向再看正向）
    if any(kw in text for kw in _STYLUS_HINTS_NEGATIVE):
        facts["supports_stylus"] = False
    elif any(kw in text for kw in _STYLUS_HINTS_POSITIVE):
        facts["supports_stylus"] = True

    # 折叠屏
    if any(kw in text for kw in _FOLDABLE_HINTS):
        facts["has_foldable"] = True

    # 屏幕参数（找 "x.x 寸" + Hz）
    m = re.search(r"(\d{1,2}\.?\d?\s*[寸英寸]).{0,40}?(\d{2,3}\s*Hz)", corpus)
    if m:
        facts["screen_spec"] = f"{m.group(1)} / {m.group(2)}"

    # 芯片
    chip_match = re.search(r"(麒麟\s*9\d{3}\w*|Kirin\s*9\d{3}\w*|骁龙\s*8\s*Gen\s*\d|Snapdragon\s*8\s*Gen\s*\d)", corpus, re.IGNORECASE)
    if chip_match:
        facts["chipset"] = chip_match.group(1).strip()

    # 电池
    bat = re.search(r"(\d{3,5})\s*mAh", corpus, re.IGNORECASE)
    if bat:
        facts["battery"] = f"{bat.group(1)} mAh"

    return facts


# Pura X 这种"显式无手写笔"的产品 → preflight 强制提示
# 即便 web_search 0 命中，也要把这条"知识库外的硬常识"塞进去
_HARDCODED_PRODUCT_FACTS: dict[str, dict[str, Any]] = {
    "pura x": {
        "product_category": "折叠屏手机",
        "supports_stylus": False,
        "has_foldable": True,
        "_hint": "Pura X 是华为小折叠手机（横折），**不支持外接手写笔（无 M-Pencil 支持）**。"
                 "如果客户问手写笔相关问题，请明确告知客户：Pura X 是手机不是平板，"
                 "需要手写笔体验请看 MatePad 系列。",
    },
    "mate xt": {
        "product_category": "三折叠手机",
        "supports_stylus": False,
        "has_foldable": True,
        "_hint": "Mate XT 是华为三折叠手机，**不支持外接手写笔**。",
    },
}


# ============================================================
# Step 4: 主函数 build_product_fact_card
# ============================================================


def build_product_fact_card(
    *,
    topic: str,
    persona: PersonaProfile,
    product_kb_id: Optional[int],
    use_llm_fallback: bool = True,
) -> ProductFactCard:
    """整合 1+2+3，返回一张 ProductFactCard。永不抛。"""

    # —— 1. 抽产品名 ——
    product_name = extract_product_from_topic(topic)
    if not product_name and use_llm_fallback:
        product_name = extract_product_with_llm(topic)
    if not product_name:
        return _uncertain_card(
            product_name='（未识别到具体产品）',
            reason=(
                'topic 里没找到具体型号，本场按"通用泛聊"模式 — '
                '销冠**禁止提任何具体型号的具体参数 / 价格 / 配色 / 政策**，'
                '客户问到时先反问"您想了解哪一款？"或推荐 1-2 款让客户选。'
            ),
        )

    # —— 2. 准备市场上下文 ——
    market = get_market(getattr(persona, "country_code", None) or "")
    domains = list(getattr(persona, "market_domains", []) or market.market_domains)
    currency = getattr(persona, "currency", None) or market.currency

    # —— 3. 查 KB ——
    kb_hits = _query_product_kb(product_kb_id, product_name)
    kb_corpus = "\n".join((h.get("text") or "") for h in kb_hits)

    # —— 4. 查 web_search（被锁本地域名） ——
    web_result = _query_web_search(product_name, domains)
    web_corpus = ""
    web_urls: list[str] = []
    if isinstance(web_result, dict) and "error" not in web_result:
        # 兼容 run_web_search 直接返回 / 走 dispatch 包装
        results = (
            web_result.get("results")
            or (web_result.get("data") or {}).get("results")
            or []
        )
        for r in results[:3]:
            web_corpus += "\n" + (r.get("snippet") or r.get("content") or "")
            url = r.get("url") or r.get("link")
            if url:
                web_urls.append(url)
        ans = web_result.get("answer") or (web_result.get("data") or {}).get("answer")
        if ans:
            web_corpus += "\n" + ans

    # —— 5. 粗扫事实点 + 注入硬编码常识 ——
    facts = _scan_evidence_text(kb_corpus + "\n" + web_corpus, product_name)
    if not facts.get("product_category"):
        cat = _infer_category(product_name)
        if cat:
            facts["product_category"] = cat

    hardcoded = _HARDCODED_PRODUCT_FACTS.get(product_name.lower(), {})
    hardcoded_hint = hardcoded.pop("_hint", None) if hardcoded else None
    # hardcoded 覆盖 scan（硬常识优先级高）
    for k, v in (hardcoded or {}).items():
        facts[k] = v

    # —— 6. 价格区间（仅从 web_corpus 找带货币的字符串） ——
    price_pat = re.compile(
        rf"({re.escape(currency)}|RM|₱|Rp|฿|د\.إ|﷼|R|₺|₽|MX\$|￥|¥|\$)\s*[\d,]+",
        re.IGNORECASE,
    )
    prices = price_pat.findall(web_corpus + "\n" + kb_corpus)
    # findall 上面返回 group(1) 列表（货币符号），重新跑一次拿完整 match
    price_matches = price_pat.finditer(web_corpus + "\n" + kb_corpus)
    price_strs = [m.group(0) for m in price_matches]
    if price_strs:
        facts["local_price_range"] = " / ".join(sorted(set(price_strs))[:3])

    # —— 7. confidence 判定 ——
    has_any_fact = any(v is not None for v in facts.values()) or kb_hits or web_urls
    if not has_any_fact:
        return _uncertain_card(
            product_name=product_name,
            reason=(
                f"对【{product_name}】在产品知识库和 {currency} 市场可信信源里"
                f"**完全没拿到任何事实**（KB 0 命中，web_search 0 命中）。"
                f"本场销冠**禁止提任何具体参数 / 价格 / 配色 / 政策**——"
                f'客户问到具体数字一律说"我帮您当场打开官网确认"，绝不凭印象编造。'
            ),
            hardcoded_hint=hardcoded_hint,
        )

    confidence = "KNOWN" if (len([v for v in facts.values() if v is not None]) >= 3) else "PARTIAL"

    card = ProductFactCard(
        product_name=product_name,
        confidence=confidence,
        product_category=facts.get("product_category"),
        supports_stylus=facts.get("supports_stylus"),
        has_foldable=facts.get("has_foldable"),
        screen_spec=facts.get("screen_spec"),
        chipset=facts.get("chipset"),
        battery=facts.get("battery"),
        local_price_range=facts.get("local_price_range"),
        # is_available_in_market 暂时只看 web_search 是否有该市场域名命中
        is_available_in_market=bool(web_urls),
        sources=web_urls[:5] + [h.get("filename") or "kb_chunk" for h in kb_hits[:3]],
    )
    card.render_block = _render_card(card, hardcoded_hint=hardcoded_hint)
    return card


# ============================================================
# 渲染：给 sales_prompt 用的 markdown 块
# ============================================================


def _uncertain_card(
    *,
    product_name: str,
    reason: str,
    hardcoded_hint: Optional[str] = None,
) -> ProductFactCard:
    card = ProductFactCard(product_name=product_name, confidence="UNCERTAIN")
    pieces = [
        f"**产品事实卡：{product_name}**   _可信度：UNCERTAIN_",
        "",
        "⚠️ **强制降级 — 销冠本场行为约束**：",
        f"  · {reason}",
    ]
    if hardcoded_hint:
        pieces.append(f"  · {hardcoded_hint}")
    pieces.extend([
        "",
        "**销冠唯一被允许的话术模板**：",
        '  · "您问的这个具体参数我立刻帮您查官网，30 秒就有"',
        '  · "店里就有现机，我直接打开页面给您看"',
        '  · "您想了解哪个具体型号？我把官方资料调出来"',
    ])
    card.render_block = "\n".join(pieces)
    return card


def _bool_label(v: Optional[bool]) -> str:
    if v is True:
        return "✅ 是"
    if v is False:
        return "❌ 否"
    return "—"


def _render_card(card: ProductFactCard, *, hardcoded_hint: Optional[str] = None) -> str:
    lines = [
        f"**产品事实卡：{card.product_name}**   _可信度：{card.confidence}_",
        "",
        "| 字段 | 值 |",
        "| --- | --- |",
        f"| 产品类别 | {card.product_category or '—'} |",
        f"| 是否支持手写笔 | {_bool_label(card.supports_stylus)} |",
        f"| 是否折叠屏 | {_bool_label(card.has_foldable)} |",
        f"| 屏幕规格 | {card.screen_spec or '—'} |",
        f"| 芯片 | {card.chipset or '—'} |",
        f"| 电池 | {card.battery or '—'} |",
        f"| 本地价格区间 | {card.local_price_range or '—'} |",
        f"| 本地市场是否在售 | {_bool_label(card.is_available_in_market)} |",
        "",
        "⚠️ **本场事实硬约束**：",
        '  · 上表标 ✅/❌ 的字段是**已经核实的硬事实**，销冠不得说反（如表里 supports_stylus=❌ 还说"配手写笔"=严重违规）。',
        '  · 上表标"—"的字段表示**未拿到证据**，销冠不得自行编造具体数字/型号，必须说"具体我现场打开官网给您看"。',
    ]
    if hardcoded_hint:
        lines.extend(["", f"📌 **该产品特别提示**：{hardcoded_hint}"])
    if card.sources:
        lines.append("")
        lines.append("**事实卡来源**：" + "、".join(card.sources[:5]))
    return "\n".join(lines)
