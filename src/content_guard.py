"""v0.2.2 真实性补丁 — Layer B：销冠输出后的事实自查 + 改写。

设计原则（user q3 = rewrite_to_disclaimer）：
  - **保护漂亮表达**：不删整句、不强插错误词，只把"未证实的具体数字"原地
    替换为"具体我帮您当场查官网确认"。
  - **只看具体数字与具体型号**：开放表达（情感 / 共鸣 / 推销话术）不动。
  - **匹配证据**：
      a) ProductFactCard 上的硬字段（电池 / 屏幕 / 芯片 / 价格区间等）
      b) 本轮 tool_calls 里 RAG/web_search 命中的原文片段
      c) 本轮历史中已经说过的可信表述（不重复警告）
  - **永不抛**：guard 出任何异常都返回原文 + 空 warnings。

公开 API：
  - ``extract_numeric_claims(text)``  → list[(claim_text, span_start, span_end, kind)]
  - ``extract_specific_models(text)`` → list[(model_text, span_start, span_end)]
  - ``verify_and_rewrite(text, *, fact_card, tool_calls)``  →
      (new_text, list[str] warnings)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from src.schema import ProductFactCard

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 具体数字提取 — 只抓"销冠最容易胡编的"几种 unit
# ---------------------------------------------------------------------------

# 每条 (kind, regex)；提取的 group(0) 就是完整 claim 文本。
_NUMERIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 延迟（最高频翻车：手写笔延迟 / 触控延迟）
    ("latency_ms",   re.compile(r"\d+(?:\.\d+)?\s*ms\b", re.IGNORECASE)),
    # 跑分（动辄"172万"）
    ("benchmark",    re.compile(r"\d+(?:\.\d+)?\s*万(?=\D|$)")),
    # 屏幕刷新率
    ("refresh_hz",   re.compile(r"\d{2,3}\s*Hz\b", re.IGNORECASE)),
    # 电池容量
    ("battery_mah",  re.compile(r"\d{3,5}\s*mAh\b", re.IGNORECASE)),
    # 充电功率
    ("charge_w",     re.compile(r"\d{2,4}\s*W\b(?!\w)")),
    # 屏幕尺寸（带寸）
    ("screen_inch",  re.compile(r"\d{1,2}\.\d\s*(?:寸|英寸|inch)", re.IGNORECASE)),
    # 像素 / 分辨率
    ("megapixel",    re.compile(r"\d{2,4}\s*MP\b", re.IGNORECASE)),
    # 电量百分比（"导航 1 小时耗电 12%"）——必须带电量语境，否则
    # "0%分期 / 首付 30% / 年化 5%" 这类金融百分比会被误判成电量并改写。
    (
        "battery_pct",
        re.compile(r"(?:耗电|掉电|掉到|用电|电量|续航|满电|充到)[^%\d]{0,6}\d{1,3}\s*%"),
    ),
    # 货币 + 金额（被 client_market 已经管"币种"；这里抓"具体金额"是否有据）
    (
        "price_amount",
        re.compile(
            r"(?:RM|MYR|PHP|₱|Rp|IDR|฿|THB|د\.إ|AED|﷼|SAR|R|ZAR|₺|TRY|₽|RUB|MX\$|MXN|￥|¥|CNY|RMB|USD|\$)"
            r"\s*[\d,]+(?:\.\d+)?",
            re.IGNORECASE,
        ),
    ),
)


def extract_numeric_claims(text: str) -> list[tuple[str, int, int, str]]:
    """返回 [(claim_text, span_start, span_end, kind), ...]。互不重叠（同区间保留先匹到的）。"""
    if not text:
        return []
    raw_hits: list[tuple[str, int, int, str]] = []
    for kind, pat in _NUMERIC_PATTERNS:
        for m in pat.finditer(text):
            raw_hits.append((m.group(0), m.start(), m.end(), kind))
    # 去掉嵌套 / 重叠：按 start 排序，丢弃任何与已选 span 相交的
    raw_hits.sort(key=lambda x: (x[1], -(x[2] - x[1])))
    out: list[tuple[str, int, int, str]] = []
    last_end = -1
    for c, s, e, k in raw_hits:
        if s >= last_end:
            out.append((c, s, e, k))
            last_end = e
    return out


# ---------------------------------------------------------------------------
# 具体型号 / 配件名提取（销冠会脑补"M-Pencil""星闪笔""第三代 XX"）
# ---------------------------------------------------------------------------

_MODEL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"第[一二三四五六七八九十]+代\s*M-Pencil", re.IGNORECASE),
    re.compile(r"M-?Pencil(?:\s*\d?)?", re.IGNORECASE),
    re.compile(r"星闪(?:笔)?", re.IGNORECASE),
    re.compile(r"NearLink", re.IGNORECASE),
    re.compile(r"麒麟\s*9\d{3}\w*", re.IGNORECASE),
    re.compile(r"Kirin\s*9\d{3}\w*", re.IGNORECASE),
    re.compile(r"骁龙\s*8\s*Gen\s*\d", re.IGNORECASE),
    re.compile(r"Snapdragon\s*8\s*Gen\s*\d", re.IGNORECASE),
    re.compile(r"A1[5-9]\s*Pro", re.IGNORECASE),    # iPhone A15-A19 Pro
)


def extract_specific_models(text: str) -> list[tuple[str, int, int]]:
    """返回 [(model_text, start, end), ...]，互不重叠。"""
    if not text:
        return []
    raw: list[tuple[str, int, int]] = []
    for pat in _MODEL_PATTERNS:
        for m in pat.finditer(text):
            raw.append((m.group(0), m.start(), m.end()))
    raw.sort(key=lambda x: (x[1], -(x[2] - x[1])))
    out: list[tuple[str, int, int]] = []
    last_end = -1
    for c, s, e in raw:
        if s >= last_end:
            out.append((c, s, e))
            last_end = e
    return out


# ---------------------------------------------------------------------------
# 证据集合：把 fact_card + 本轮 tool_calls 全部命中文本压成一个 lower 的大字符串
# ---------------------------------------------------------------------------


def _collect_evidence_corpus(
    *,
    fact_card: Optional[ProductFactCard],
    tool_calls: list[dict[str, Any]] | None,
    handbook_text: Optional[str] = None,
    extra_evidence_text: Optional[str] = None,
) -> str:
    """把所有"可信文本来源"拼成一个大字符串，供 substring 比对。

    证据来源（任一命中即算 grounded）：
      1. ``handbook_text``：本场注入到销冠 prompt 的 Handbook 全文
         （含价格 / 参数 / FAQ 等结构化卖点），强证据源
      2. ``fact_card``：经过校验的硬字段
      3. ``tool_calls``：本轮工具调用命中的 chunks / web_search 结果
      4. ``extra_evidence_text``：② 对话前预研的市场事实表全文
         （含当地本品价 / 竞品价 / 促销），同为强证据源
    """
    pieces: list[str] = []
    if handbook_text:
        pieces.append(str(handbook_text))
    if extra_evidence_text:
        pieces.append(str(extra_evidence_text))
    if fact_card:
        for field in (
            "screen_spec", "chipset", "battery",
            "local_price_range",
        ):
            v = getattr(fact_card, field, None)
            if v:
                pieces.append(str(v))
    if tool_calls:
        for c in tool_calls:
            res = c.get("result") if isinstance(c, dict) else None
            if res is None:
                continue
            # res 可能是 dict 也可能是 str；统一序列化
            if isinstance(res, dict):
                # 把命中的 text / snippet / answer 拼出来
                data = res.get("data") or res
                hits = data.get("hits") if isinstance(data, dict) else None
                if isinstance(hits, list):
                    for h in hits:
                        t = (h or {}).get("text") or (h or {}).get("snippet")
                        if t:
                            pieces.append(str(t))
                results = data.get("results") if isinstance(data, dict) else None
                if isinstance(results, list):
                    for r in results:
                        s = (r or {}).get("snippet") or (r or {}).get("content")
                        if s:
                            pieces.append(str(s))
                if isinstance(data, dict) and data.get("answer"):
                    pieces.append(str(data["answer"]))
            else:
                pieces.append(str(res))
    return "\n".join(pieces).lower()


def _normalize_for_match(s: str) -> str:
    """把空格 / 全半角统一，便于 substring 比对。"""
    return re.sub(r"\s+", "", s.lower())


_NUMBER_RE = re.compile(r"\d+(?:[\.,]\d+)?")


def _extract_bare_numbers(claim: str) -> list[str]:
    """从 claim 文本中抽出纯数字（去掉单位 / 币种 / 千分位逗号）。

    用于在 corpus 里做宽松匹配——例如销售说 ``13.2英寸``，
    而 Handbook 里写的是 ``12英寸``，这里抽出 ``13.2`` 去查 corpus；
    如果 corpus 里有 ``12`` 但没 ``13.2``，会回到主路径判定为未证实。
    千分位逗号统一去掉，``$1,234`` 与 ``1234`` 视为同一数字。
    """
    nums: list[str] = []
    for m in _NUMBER_RE.finditer(claim):
        raw = m.group(0).replace(",", "")
        # 去掉末尾的 .0（"3399.0" → "3399"）
        if "." in raw:
            try:
                f = float(raw)
                if f.is_integer():
                    raw = str(int(f))
            except ValueError:
                pass
        nums.append(raw)
    return nums


def _claim_is_grounded(claim: str, corpus_normalized: str) -> bool:
    """claim 是否在 corpus 里能找到。两级匹配：

    1) 整 claim 去空格后 substring 命中（最严格）
    2) 把 claim 拆成裸数字（去单位 / 币种），任一裸数字在 corpus 里
       出现即算命中（宽松，挡住"单位/币种不同"造成的误伤）
    """
    if _normalize_for_match(claim) in corpus_normalized:
        return True
    bare_nums = _extract_bare_numbers(claim)
    if not bare_nums:
        return False
    # corpus 里也只看数字（去千分位），避免 "$3,399" vs "3399" 错过
    corpus_digits_only = re.sub(r",(?=\d)", "", corpus_normalized)
    for n in bare_nums:
        # 必须整段数字 token 命中，不能是更大数字的子串，否则短数字会被
        # 蒙混（"1" 命中 "2025"/"12X"、"75" 命中 "256"）而漏判未证实。
        if re.search(rf"(?<![\d.]){re.escape(n)}(?![\d.])", corpus_digits_only):
            return True
    return False


# ---------------------------------------------------------------------------
# 主函数 verify_and_rewrite
# ---------------------------------------------------------------------------

# 通用 disclaimer 文本（替换所有未证实具体数字时用）
# 线下华为旗舰店语境：禁用"打开官网/发链接"（违背店内铁律），
# 统一改写成"现场真机实测 / 同事调单核价"这类店内动作话术。
_DISCLAIMER_TEMPLATES = {
    "latency_ms":   "准确毫秒数我现场拿真机给您实测",
    "benchmark":    "具体跑分我现场拿真机给您跑一遍",
    "refresh_hz":   "准确刷新率我现场拿真机给您看实测",
    "battery_mah":  "准确电池容量我让同事现场给您核一下",
    "charge_w":     "准确充电功率我现场拿真机给您测",
    "screen_inch":  "准确屏幕尺寸我现场拿真机给您量",
    "megapixel":    "准确像素我现场拿真机给您拍样张看",
    "battery_pct":  "准确耗电数据我现场拿真机给您实测",
    "price_amount": "准确价格我让同事现场给您调单核一下",
}
_GENERIC_DISCLAIMER = "这个准确数字我现场给您核一下"


# ---------------------------------------------------------------------------
# B1：派生价格识别 + 去重（v0.2.4）
# ---------------------------------------------------------------------------

# "派生/区间"语境关键词：命中其一即认为该价格是折抵估值 / 分期月供 / 价格区间
# 等销售可自由报的派生值（而非凭空捏造的硬规格价）。
_DERIVED_PRICE_MARKERS: tuple[str, ...] = (
    "月供", "分期", "每天", "每月", "每周", "首付", "尾款", "定金",
    "折", "抵", "估值", "可折", "起", "低至", "省", "立减", "优惠", "减",
    "区间", "大约", "大概", "预计",
)
# 区间分隔符（"RM A–RM B"），出现在价格紧邻处也算派生语境。
_RANGE_SEP_CHARS = "–—-~～至到/"

# 相邻 rewrite 之间只隔这些字符时视为"同一处"（价格区间 / 连写），可合并。
_SEP_ONLY_RE = re.compile(rf"^[\s{re.escape(_RANGE_SEP_CHARS)}、,，]*$")

# 删除重复兜底时，连同其前的修饰词（月供/约/起 等）一起吃掉，避免残句。
_DUP_LEFT_RE = re.compile(
    r"[，,、]?\s*(?:每月)?(?:月供|供)?\s*(?:大约|大概|约|仅|只|低至)?\s*$"
)
_DUP_RIGHT_RE = re.compile(r"\s*(?:起|左右|上下)?")


def _is_derived_price(text: str, s: int, e: int) -> bool:
    """判断 text[s:e] 处的价格是否处于"派生/区间"语境（折抵 / 月供 / 区间等）。"""
    left = text[max(0, s - 12):s]
    right = text[e:e + 8]
    window = left + right
    if any(kw in window for kw in _DERIVED_PRICE_MARKERS):
        return True
    # 紧邻区间分隔符（如 "RM A–RM B" 的两端）
    if right[:2] and any(c in _RANGE_SEP_CHARS for c in right[:2]):
        return True
    if left[-2:] and any(c in _RANGE_SEP_CHARS for c in left[-2:]):
        return True
    return False


def _dedup_rewrites(
    rewrites: list[tuple[int, int, str, str]], text: str
) -> list[tuple[int, int, str, str]]:
    """合并/去重替换，避免同一兜底话术在一条消息里复读。

    两步：
      1) 相邻合并：替换文本相同、且两段之间只隔分隔符（价格区间 "A–B"），
         合并成一个 span，渲染成单句兜底而非 "[兜底]-[兜底]"。
      2) 全局去重：同一替换文本在消息内只保留首次出现；后续重复 span 连同
         紧邻的修饰词（月供/约/起 等）一并删除，避免残留断句。
    """
    if len(rewrites) <= 1:
        return rewrites
    ordered = sorted(rewrites, key=lambda x: x[0])

    # 1) 相邻合并
    merged: list[tuple[int, int, str, str]] = []
    for s, e, orig, repl in ordered:
        if merged:
            ps, pe, _po, prepl = merged[-1]
            if repl == prepl and _SEP_ONLY_RE.match(text[pe:s]):
                merged[-1] = (ps, e, text[ps:e], repl)
                continue
        merged.append((s, e, orig, repl))

    # 2) 全局去重（保留首次出现，重复项删除 + 吞掉紧邻修饰词）
    seen: set[str] = set()
    out: list[tuple[int, int, str, str]] = []
    prev_end = 0
    for s, e, orig, repl in merged:
        if repl not in seen:
            seen.add(repl)
            out.append((s, e, orig, repl))
            prev_end = e
            continue
        frag = text[prev_end:s]
        lm = _DUP_LEFT_RE.search(frag)
        ls = prev_end + lm.start() if lm else s
        rm = _DUP_RIGHT_RE.match(text, e)
        re_end = rm.end() if rm else e
        out.append((ls, re_end, text[ls:re_end], ""))
        prev_end = re_end
    return out


def _tidy_after_rewrite(text: str) -> str:
    """去重删除留下的标点 / 空白碎片清理。"""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+(?=[，。.！!？?；;、])", "", text)
    text = re.sub(r"[，,、]+(?=[，,。.！!？?；;])", "", text)
    text = re.sub(r"(?<=[。.！!？?；;])[，,、]+", "", text)
    return text.strip()


def verify_and_rewrite(
    text: str,
    *,
    fact_card: Optional[ProductFactCard],
    tool_calls: list[dict[str, Any]] | None = None,
    handbook_text: Optional[str] = None,
    extra_evidence_text: Optional[str] = None,
) -> tuple[str, list[str]]:
    """对 sales 输出做事实自查并原地改写未证实的具体数字 / 型号。

    返回 ``(new_text, warnings)``：
      - warnings：人类可读的违规清单（每条形如 "未证实 claim: '2ms' → 已改写"）

    Args:
        text: 销冠原始 content。
        fact_card: 本场会话的 ProductFactCard（可能为 None）。
        tool_calls: 本轮销冠调用工具的记录（dict 列表，含 result）。
        handbook_text: 本场注入到销冠 prompt 的 Handbook 全文（强证据源）。
            **必须**传入，否则当 fact_card 为 UNCERTAIN/None 时会把
            Handbook 里明确写的数字（价格 / 参数）也当成"未证实"改写掉，
            导致销冠输出全是"具体XX我现场打开官网给您看"——这是 v0.2.3 bugfix。

    Failure-safe：任何异常 → 返回 (text, [])，不影响主流程。
    """
    try:
        if not text or not text.strip():
            return text, []

        corpus_normalized = _normalize_for_match(
            _collect_evidence_corpus(
                fact_card=fact_card,
                tool_calls=tool_calls,
                handbook_text=handbook_text,
                extra_evidence_text=extra_evidence_text,
            )
        )

        # 1. 提取所有 claim
        numeric_claims = extract_numeric_claims(text)
        model_claims = extract_specific_models(text)

        # 2. 找出未证实的部分
        rewrites: list[tuple[int, int, str, str]] = []  # (start, end, original, replacement)
        warnings: list[str] = []

        # v0.2.3：永远走 corpus substring + 裸数字双级匹配，不再走"UNCERTAIN
        # 卡 → 全杀"的硬路径——只要 Handbook / fact_card / tool_calls 任一源
        # 里能查到 claim 中的数字，就算 grounded；corpus 空时自然没东西匹配，
        # 与旧"全杀"行为等价但不会误伤 Handbook 写明的数字。
        #
        # B1（v0.2.4）：折抵估值 / 分期月供这类**派生价格**是销售在成交阶段
        # 必须能自由报的数字，且天然不会逐字出现在静态证据里（月供=售价÷期数，
        # 折抵=动态评估），旧逻辑每轮都把它们当"未证实"抹成同一句兜底，直接
        # 导致客户拿不到数字而流失。修复：只要同一条消息里至少有一个 price_amount
        # 已证实（基准价 grounded），就放行该消息里**处于派生/区间语境**的价格；
        # 硬参数（延迟 / 跑分 / 电池等）仍逐条严格校验，不受影响。
        price_anchor_grounded = any(
            kind == "price_amount" and _claim_is_grounded(claim, corpus_normalized)
            for claim, _s, _e, kind in numeric_claims
        )

        for claim, s, e, kind in numeric_claims:
            if _claim_is_grounded(claim, corpus_normalized):
                continue
            if (
                kind == "price_amount"
                and price_anchor_grounded
                and _is_derived_price(text, s, e)
            ):
                continue
            replacement = _DISCLAIMER_TEMPLATES.get(kind, _GENERIC_DISCLAIMER)
            rewrites.append((s, e, claim, replacement))
            warnings.append(f"未证实数字 '{claim}' (kind={kind}) → 已改写")

        # 型号 / 配件名 — 只在 fact_card 明确否决时改写（如 supports_stylus=False
        # 时销冠却提 M-Pencil）；其余型号过于宽泛，先不动。
        if fact_card and fact_card.supports_stylus is False:
            stylus_kw = ("m-pencil", "m pencil", "mpencil", "手写笔", "星闪笔", "stylus")
            for claim, s, e in model_claims:
                if any(kw in claim.lower() for kw in stylus_kw):
                    replacement = (
                        f"（{fact_card.product_name} 不支持外接手写笔，需要手写笔体验请看 MatePad 系列）"
                    )
                    rewrites.append((s, e, claim, replacement))
                    warnings.append(
                        f"违反硬事实：fact_card 显示 supports_stylus=False，"
                        f"但销冠提到 '{claim}' → 已改写为否决声明"
                    )

        if not rewrites:
            return text, []

        # 去重 Layer 1（v0.2.4）：同一兜底话术在一条消息里只出现一次。
        # 否则价格区间 "RM A–RM B" 与多处未证实价格会被替换成 "[兜底]-[兜底]
        # ……[兜底]" 的复读断句。
        rewrites = _dedup_rewrites(rewrites, text)

        # 3. 按 span 倒序应用 rewrites（避免下标漂移）
        rewrites.sort(key=lambda x: -x[0])
        new_text = text
        for s, e, _orig, repl in rewrites:
            new_text = new_text[:s] + repl + new_text[e:]

        new_text = _tidy_after_rewrite(new_text)
        return new_text, warnings

    except Exception as exc:  # noqa: BLE001
        logger.warning("verify_and_rewrite 失败（返回原文）：%s", exc)
        return text, []
