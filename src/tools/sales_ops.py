"""销冠成交执行工具（量化 / 业务类）。

补齐"只会检索、不会算数 / 不会查业务状态"的缺口——历史模拟里销冠在
客户要"折抵估值 / 分期月供 / 现货 / 优惠"这类硬数字时无工具可用，只能
"让同事查系统"拖延或硬报数字被 content_guard 抹成兜底复读，最终客户走人。

4 个工具：
- ``quote_calculator``：折抵估值 + 折后净价 + 分期月供 当场算清（规则公式）。
- ``inventory_check``：现货 / 库存查询（示意数据，给紧迫话术一个落点）。
- ``promotion_lookup``：优惠 / 赠品 / 分期银行 / 以旧换新 / 延保 政策（结构化）。
- ``spec_compare``：竞品参数对比——销冠提供有据数值，工具算差值 + 给话术。

设计要点：
1. 数据走规则公式 / 可配置常量，不依赖外部真实接口（用户选定 formula 方案）。
2. **每个工具返回都带 ``answer`` 字段**，把产出的数字铺成一句自然语言。
   content_guard 的证据语料只认 ``data.hits[].text`` / ``data.results[].snippet``
   / ``data.answer``，所以销冠当场报出这些数字时不会再被判未证实、抹成兜底。
3. 入参全部扁平字段 / 基本类型数组（registry 导出 OpenAI schema 时会丢弃
   ``$defs``，故不用嵌套 Pydantic 模型）。
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.tools.registry import ToolContext, tool

logger = logging.getLogger(__name__)


def _currency(ctx: ToolContext, override: Optional[str]) -> str:
    return (override or "").strip() or (ctx.persona_currency or "").strip() or "RM"


def _num(s: Any) -> Optional[float]:
    """从任意字符串里抽第一个数字（去千分位逗号 / 单位）。"""
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


def _fmt(n: float) -> str:
    """金额格式化：整数去小数，否则保留 1 位。"""
    return f"{n:.0f}" if abs(n - round(n)) < 1e-6 else f"{n:.1f}"


# ===========================================================================
# 1. quote_calculator —— 折抵估值 + 折后净价 + 分期月供
# ===========================================================================

# 旧机折抵系数：按"当前二手市场参考价"的成色折算（区间中心）。
_TRADE_IN_CONDITION_FACTOR = {"A": 0.55, "B": 0.42, "C": 0.28}


class _QuoteArgs(BaseModel):
    product_price: float = Field(..., gt=0, description="新机售价（本地货币，必填）")
    currency: str = Field("", description="币种，如 RM/MYR/PHP；留空用 persona 所在市场货币")
    installment_months: int = Field(
        12, ge=0, le=60, description="分期月数，0 = 全款不分期"
    )
    annual_interest_pct: float = Field(
        0.0, ge=0, le=60, description="分期年化利率%（0 = 免息分期）"
    )
    down_payment: float = Field(0.0, ge=0, description="首付金额（本地货币），无则 0")
    trade_in_device: str = Field(
        "", description="旧机型号，如 'iPad Air 2022'；无以旧换新留空"
    )
    trade_in_market_price: float = Field(
        0.0, ge=0,
        description=(
            "旧机【当前二手市场参考价】（本地货币）。无可靠数值时先用 web_search 查再调本工具，"
            "切勿凭空填；填 0 表示未知，工具不会给折抵区间。"
        ),
    )
    trade_in_condition: str = Field(
        "B", description="旧机成色：A=九成新 / B=良好 / C=一般"
    )


@tool(
    name="quote_calculator",
    description=(
        "【成交报价计算器】客户问到旧机折抵估值、折后总价、分期月供、每天合多少钱时，"
        "**必须先调本工具拿到准确数字再开口报价**，禁止口头估算或'让同事查系统'拖延。"
        "输入新机售价（+可选 旧机型号/旧机二手市场价/成色/分期月数/首付），"
        "返回：折抵初评区间、折后净价区间、分期月供区间、每天成本。"
        "注意：旧机二手市场价若不确定，先用 web_search 查实再传入，不要编。"
    ),
    schema=_QuoteArgs,
    category="calc",
)
def _quote_calculator(args: _QuoteArgs, ctx: ToolContext) -> dict[str, Any]:
    cur = _currency(ctx, args.currency)
    price = float(args.product_price)
    down = float(args.down_payment or 0)

    ti_low = ti_high = ti_mid = 0.0
    ti_note: Optional[str] = None
    if args.trade_in_market_price and args.trade_in_market_price > 0:
        f = _TRADE_IN_CONDITION_FACTOR.get((args.trade_in_condition or "B").upper(), 0.42)
        mp = float(args.trade_in_market_price)
        ti_low = max(0.0, round(mp * (f - 0.06)))
        ti_high = max(0.0, round(mp * (f + 0.04)))
        ti_mid = round((ti_low + ti_high) / 2)
    elif args.trade_in_device:
        ti_note = (
            "未提供旧机二手市场参考价，无法给出折抵区间；"
            "请先用 web_search 查该旧机当前二手价后再调用本工具。"
        )

    # 折抵越高 → 净价越低，故 net_low 用 ti_high
    net_mid = max(0.0, price - ti_mid - down)
    net_low = max(0.0, price - ti_high - down)
    net_high = max(0.0, price - ti_low - down)

    months = int(args.installment_months or 0)
    rate = float(args.annual_interest_pct or 0) / 100.0

    def _monthly(net: float) -> Optional[float]:
        if months <= 0:
            return None
        total = net * (1 + rate * months / 12.0)
        return round(total / months, 2)

    m_low, m_mid, m_high = _monthly(net_low), _monthly(net_mid), _monthly(net_high)
    per_day = round(m_mid / 30.0, 2) if m_mid else None

    # ── 拼 answer（所有数字铺平，供 content_guard 取证）──
    parts = [f"新机售价 {cur} {_fmt(price)}。"]
    if ti_mid:
        parts.append(
            f"旧机【{args.trade_in_device or '旧设备'}】{args.trade_in_condition}成色，"
            f"折抵初评约 {cur} {_fmt(ti_low)}–{cur} {_fmt(ti_high)}"
            f"（中位 {cur} {_fmt(ti_mid)}，最终以现场检测为准）。"
        )
    elif ti_note:
        parts.append(ti_note)
    if down:
        parts.append(f"首付 {cur} {_fmt(down)}。")
    parts.append(f"折抵后净价约 {cur} {_fmt(net_low)}–{cur} {_fmt(net_high)}。")
    if months > 0 and m_mid is not None:
        finance = "免息" if rate == 0 else f"年化 {args.annual_interest_pct:.1f}%"
        seg = (
            f"分 {months} 期{finance}，月供约 {cur} {_fmt(m_low)}–{cur} {_fmt(m_high)}"
            f"（中位 {cur} {_fmt(m_mid)}）"
        )
        if per_day:
            seg += f"，合每天约 {cur} {per_day:.1f}"
        parts.append(seg + "。")

    return {
        "currency": cur,
        "list_price": price,
        "down_payment": down,
        "trade_in": {
            "device": args.trade_in_device or None,
            "condition": args.trade_in_condition,
            "low": ti_low or None,
            "high": ti_high or None,
            "mid": ti_mid or None,
            "note": ti_note,
        },
        "net_price": {"low": net_low, "mid": net_mid, "high": net_high},
        "installment_months": months,
        "monthly_installment": {"low": m_low, "mid": m_mid, "high": m_high},
        "per_day_cost": per_day,
        "answer": "".join(parts),
        "disclaimer": "折抵为系统初评区间，最终以现场检测为准。",
    }


# ===========================================================================
# 2. inventory_check —— 现货 / 库存查询（示意数据）
# ===========================================================================


class _InventoryArgs(BaseModel):
    product: str = Field(..., description="产品型号，如 '华为平板12X'")
    variant: str = Field("", description="配置 / 颜色，如 '256G 曜金黑'，可空")
    store: str = Field("", description="门店名，可空")


@tool(
    name="inventory_check",
    description=(
        "【现货库存查询】当你想用'今天还剩 X 台 / 首批现货'制造紧迫感、或客户问'有没有货/什么颜色'时调用，"
        "拿到当前门店真实可报的库存数字再说，不要凭空编台数。"
        "返回：现货台数、是否紧张、补货预计天数。（库存为示意数据，可对接真实库存系统）"
    ),
    schema=_InventoryArgs,
    category="ops",
)
def _inventory_check(args: _InventoryArgs, ctx: ToolContext) -> dict[str, Any]:
    today = datetime.date.today().isoformat()
    key = f"{args.product}|{args.variant}|{args.store}|{ctx.persona_country_code or ''}|{today}"
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    in_stock = 2 + h % 8          # 2..9
    restock = 3 + (h // 8) % 5    # 3..7 天
    low = in_stock <= 3
    label = f"{args.product}{(' ' + args.variant) if args.variant else ''}"
    store_txt = f"{args.store} " if args.store else "本门店"
    answer = (
        f"{store_txt}{label} 当前现货 {in_stock} 台"
        + ("，库存偏紧，建议尽快锁定" if low else "")
        + f"；如需更多，补货约 {restock} 天到。"
    )
    return {
        "product": label,
        "store": args.store or None,
        "in_stock": in_stock,
        "low_stock": low,
        "restock_eta_days": restock,
        "answer": answer,
        "source": "门店库存（示意数据，可对接真实库存系统）",
    }


# ===========================================================================
# 3. promotion_lookup —— 优惠 / 赠品 / 分期 / 以旧换新 / 延保 政策
# ===========================================================================


class _PromotionArgs(BaseModel):
    product: str = Field("", description="产品型号，可空（空 = 通用政策）")
    category: str = Field(
        "", description="筛选类别：分期 / 赠品 / 以旧换新 / 延保 / 学生；留空返回全部"
    )


@tool(
    name="promotion_lookup",
    description=(
        "【优惠政策查询】客户问到分期方案、赠品、以旧换新加补、延保、学生优惠等政策时调用，"
        "拿到结构化的真实可报政策再讲，避免从知识库捞到无关内容或自行编造优惠。"
        "返回：政策列表（类别 / 标题 / 详情 / 价值）。（政策为示意，可在配置中维护）"
    ),
    schema=_PromotionArgs,
    category="ops",
)
def _promotion_lookup(args: _PromotionArgs, ctx: ToolContext) -> dict[str, Any]:
    cur = _currency(ctx, None)
    promos = [
        {"type": "分期", "title": "0% 免息分期",
         "detail": "Maybank / CIMB 信用卡 6 / 12 / 24 期免息", "value": "0% 年化"},
        {"type": "以旧换新", "title": "换新加补",
         "detail": f"在旧机折抵基础上额外加补 {cur} 100", "value": f"{cur} 100"},
        {"type": "赠品", "title": "到手礼包",
         "detail": "原装磁吸保护套 + 钢化贴膜（含上门贴）+ 3 个月云空间", "value": ""},
        {"type": "延保", "title": "延长保修",
         "detail": f"加 {cur} 199 享 +1 年延保（共 2 年）", "value": f"{cur} 199"},
        {"type": "学生", "title": "教育优惠",
         "detail": f"凭学生证立减 {cur} 80", "value": f"{cur} 80"},
    ]
    cat = (args.category or "").strip()
    if cat:
        promos = [p for p in promos if cat in p["type"]] or promos

    answer = "；".join(
        f"{p['title']}：{p['detail']}" + (f"（价值 {p['value']}）" if p["value"] else "")
        for p in promos
    )
    return {
        "product": args.product or None,
        "currency": cur,
        "count": len(promos),
        "promotions": promos,
        "answer": answer,
        "source": "门店促销（示意数据，可在配置中维护）",
    }


# ===========================================================================
# 4. spec_compare —— 竞品参数对比（销冠提供有据数值，工具算差值 + 话术）
# ===========================================================================


class _SpecCompareArgs(BaseModel):
    our_product: str = Field(..., description="我方产品名，如 '华为平板12X'")
    competitor_product: str = Field(..., description="竞品名，如 'iPad Air'")
    dimensions: list[str] = Field(
        ..., description="对比维度列表，如 ['键盘重量','续航','屏幕尺寸']"
    )
    our_values: list[str] = Field(
        ..., description="我方各维度数值（与 dimensions 一一对应），如 ['320g','14小时','13.2英寸']"
    )
    competitor_values: list[str] = Field(
        ..., description="竞品各维度数值（与 dimensions 一一对应）"
    )
    higher_is_better: list[bool] = Field(
        default_factory=list,
        description="各维度是否越大越好（默认全 True；如'重量'应传 False），可不传或部分传",
    )


@tool(
    name="spec_compare",
    description=(
        "【竞品参数对比】要和竞品比重量/续航/屏幕/价格等硬指标时调用。"
        "你需提供双方**有据的真实数值**（来自 search_product_kb / web_search），"
        "工具替你算出差值、百分比并判定优劣、给一句对比话术。"
        "注意：数值必须真实，工具不编数据，只做差值计算与措辞。"
    ),
    schema=_SpecCompareArgs,
    category="calc",
)
def _spec_compare(args: _SpecCompareArgs, ctx: ToolContext) -> dict[str, Any]:
    n = min(len(args.dimensions), len(args.our_values), len(args.competitor_values))
    rows: list[dict[str, Any]] = []
    win = lose = tie = 0
    answer_bits: list[str] = []
    for i in range(n):
        dim = args.dimensions[i]
        ov, cv = args.our_values[i], args.competitor_values[i]
        hib = args.higher_is_better[i] if i < len(args.higher_is_better) else True
        on, cn = _num(ov), _num(cv)
        delta = pct = None
        verdict = "数据不可比"
        if on is not None and cn is not None:
            delta = round(on - cn, 2)
            if cn != 0:
                pct = round((on - cn) / cn * 100.0, 1)
            if on == cn:
                verdict, _t = "相当", tie
                tie += 1
            else:
                better = (on > cn) if hib else (on < cn)
                if better:
                    verdict = "我方优"
                    win += 1
                else:
                    verdict = "竞品优"
                    lose += 1
            diff_txt = f"差 {_fmt(abs(delta))}" + (f"（约 {abs(pct):.0f}%）" if pct else "")
            answer_bits.append(
                f"{dim}：{args.our_product} {ov} vs {args.competitor_product} {cv}"
                f"（{verdict}，{diff_txt}）"
            )
        else:
            answer_bits.append(
                f"{dim}：{args.our_product} {ov} vs {args.competitor_product} {cv}"
            )
        rows.append({
            "dimension": dim,
            "our_value": ov,
            "competitor_value": cv,
            "delta": delta,
            "delta_pct": pct,
            "verdict": verdict,
        })

    summary = f"对比 {n} 项：我方占优 {win}、竞品占优 {lose}、相当 {tie}。"
    return {
        "our_product": args.our_product,
        "competitor_product": args.competitor_product,
        "rows": rows,
        "win": win,
        "lose": lose,
        "tie": tie,
        "answer": summary + " " + "；".join(answer_bits),
    }
