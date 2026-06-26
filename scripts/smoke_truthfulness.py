"""v0.2.2 真实性补丁 — 三层防御的 smoke 测试。

覆盖场景：
  A. 产品名命中（Pura X）→ preflight 应该返回一个带"硬事实=不支持手写笔"的卡，
     content_guard 应该把"M-Pencil 手写体验"改写成否决声明。
  B. 产品名零命中（"小众老机型"）→ preflight 应返回 UNCERTAIN 卡，
     content_guard 应把销冠胡编的具体 ms/mAh 全部改写成"现场查官网"。
  C. 销冠编纯数字但没有产品名上下文 → content_guard 仍能基于"UNCERTAIN 视为零证据"
     把数字改写。

所有测试**不联网**——_query_web_search / KB 查询都打 monkeypatch 走空集，
preflight 走 _HARDCODED_PRODUCT_FACTS 路径。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# 准备一个最小 PersonaProfile（无外部依赖）
# ---------------------------------------------------------------------------
from src.schema import PersonaProfile, PressureProfile  # noqa: E402


def _make_persona() -> PersonaProfile:
    pp_kwargs = {
        f: 0.5 for f in (
            "price_sensitivity", "trust_threshold", "patience",
            "competitor_awareness", "decision_power", "emotion_volatility",
            "need_urgency", "skepticism", "bargaining_aggressiveness",
        )
    }
    return PersonaProfile(
        id="smoke-1",
        name="测试客户",
        occupation="自由职业",
        budget="6000-9000 MYR",
        personality="务实理性",
        pain_points=["手写笔做笔记", "续航"],
        objection_style="直来直去",
        pressure_profile=PressureProfile(**pp_kwargs),
        country_code="MY",
        country_name="Malaysia",
        currency="MYR",
        market_domains=["consumer.huawei.com/my"],
    )


# ===========================================================================
# Case A：Pura X — preflight 必须命中硬事实卡，content_guard 必须否决 M-Pencil
# ===========================================================================


def test_case_a_pura_x() -> None:
    print("\n===== Case A：Pura X（已知硬事实：不支持手写笔）=====")

    from src import preflight  # noqa: PLC0415

    # 不让 preflight 真去查 KB / web — 走硬编码
    def _empty_kb(*a, **kw):  # type: ignore[no-untyped-def]
        return []

    def _empty_web(*a, **kw):  # type: ignore[no-untyped-def]
        return {"ok": False, "data": {"results": []}}

    preflight._query_product_kb = _empty_kb  # type: ignore[assignment]
    preflight._query_web_search = _empty_web  # type: ignore[assignment]

    persona = _make_persona()
    card = preflight.build_product_fact_card(
        topic="华为零售店：客户对 Pura X 反复砍价",
        persona=persona,
        product_kb_id=None,
    )

    print(f"  product_name      = {card.product_name}")
    print(f"  confidence        = {card.confidence}")
    print(f"  supports_stylus   = {card.supports_stylus}")
    print(f"  product_category  = {card.product_category}")
    assert card.product_name.lower() == "pura x", "product_name 提取失败"
    assert card.supports_stylus is False, "Pura X 硬事实必须 supports_stylus=False"
    assert card.confidence in {"KNOWN", "PARTIAL"}, f"硬编码卡至少 PARTIAL，实得 {card.confidence}"

    # 销冠胡编的发言（含 M-Pencil + 具体 ms + 具体 mAh）
    sales_text = (
        "Pura X 配的 M-Pencil 第二代延迟低到 2ms，"
        "手写体验跟纸一样。电池 5800 mAh，刷新率 120Hz，"
        "今天到店还能给您 RM 5,499 的活动价。"
    )

    from src.content_guard import verify_and_rewrite  # noqa: PLC0415

    new_text, warnings = verify_and_rewrite(
        sales_text, fact_card=card, tool_calls=None
    )

    print("  ----- 原文 -----")
    print(f"  {sales_text}")
    print("  ----- 改写后 -----")
    print(f"  {new_text}")
    print(f"  warnings ({len(warnings)} 条):")
    for w in warnings:
        print(f"    · {w}")

    assert "M-Pencil" not in new_text or "不支持外接手写笔" in new_text, \
        "M-Pencil 必须被改写为否决声明"
    assert "2ms" not in new_text, "未证实 ms 数字必须被改写"
    assert "5800 mAh" not in new_text and "5800mAh" not in new_text, \
        "未证实 mAh 数字必须被改写"
    assert len(warnings) >= 3, f"至少应有 3 条 warnings，实际 {len(warnings)}"
    print("  ✓ Case A 通过")


# ===========================================================================
# Case B：零命中（小众机型）— UNCERTAIN 卡，所有数字应改写
# ===========================================================================


def test_case_b_unknown_product() -> None:
    print("\n===== Case B：未知产品 → UNCERTAIN 卡 + 全数字改写 =====")

    from src import preflight  # noqa: PLC0415

    def _empty_kb(*a, **kw):  # type: ignore[no-untyped-def]
        return []

    def _empty_web(*a, **kw):  # type: ignore[no-untyped-def]
        return {"ok": False, "data": {"results": []}}

    preflight._query_product_kb = _empty_kb  # type: ignore[assignment]
    preflight._query_web_search = _empty_web  # type: ignore[assignment]

    # LLM 兜底也禁掉（topic 里不放任何品牌词 → 正则也提不出来）
    preflight.extract_product_with_llm = lambda topic: None  # type: ignore[assignment]

    persona = _make_persona()
    card = preflight.build_product_fact_card(
        topic="客户随便问问",  # 无产品名
        persona=persona,
        product_kb_id=None,
    )

    print(f"  product_name = {card.product_name}")
    print(f"  confidence   = {card.confidence}")
    assert card.confidence == "UNCERTAIN", "无产品名应返回 UNCERTAIN"

    sales_text = (
        "我们今天主打这款机器，跑分 172 万安兔兔，"
        "电池 6000 mAh，66W 快充，6.7 寸 OLED 屏，活动价 RM 3,999。"
    )

    from src.content_guard import verify_and_rewrite  # noqa: PLC0415

    new_text, warnings = verify_and_rewrite(
        sales_text, fact_card=card, tool_calls=None
    )

    print("  ----- 原文 -----")
    print(f"  {sales_text}")
    print("  ----- 改写后 -----")
    print(f"  {new_text}")
    print(f"  warnings ({len(warnings)} 条):")
    for w in warnings:
        print(f"    · {w}")

    for forbidden in ("172 万", "6000 mAh", "66W", "6.7 寸", "RM 3,999"):
        assert forbidden not in new_text, f"UNCERTAIN 卡下 '{forbidden}' 必须被改写"
    assert len(warnings) >= 4, f"至少 4 条改写，实际 {len(warnings)}"
    print("  ✓ Case B 通过")


# ===========================================================================
# Case C：fact_card 提供，但销冠数字与证据语料不匹配（监督 _claim_is_grounded）
# ===========================================================================


def test_case_c_grounded_check() -> None:
    print("\n===== Case C：fact_card 有 + 工具命中提供了部分数字 → 仅未匹配数字被改写 =====")

    from src.schema import ProductFactCard  # noqa: PLC0415

    # 手工造一张"中等可信"的卡：知道电池 5500mAh、刷新率 120Hz；
    # 不知道延迟 / 价格 / 跑分。
    card = ProductFactCard(
        product_name="Mate 80 Pro",
        confidence="PARTIAL",
        product_category="智能手机",
        supports_stylus=None,
        has_foldable=False,
        screen_spec="6.8 寸 OLED",
        chipset="Kirin 9020",
        battery="5500 mAh",
        local_price_range=None,
        is_available_in_market=True,
        sources=["consumer.huawei.com/my"],
        render_block="（test only）",
    )

    # 模拟一条 tool_calls：web_search 命中了 "120Hz" 和 "RM 5,999" 这两条数字
    tool_calls = [{
        "name": "web_search",
        "result": {
            "ok": True,
            "data": {
                "results": [{
                    "snippet": "Mate 80 Pro 配 6.8 寸 OLED 120Hz 屏, 售价 RM 5,999."
                }]
            }
        }
    }]

    sales_text = (
        "Mate 80 Pro 屏幕 120Hz 很流畅，电池 5500 mAh 一天没问题，"
        "活动价 RM 5,999。另外充电延迟低到 2ms，刷新率峰值 240Hz。"
    )

    from src.content_guard import verify_and_rewrite  # noqa: PLC0415

    new_text, warnings = verify_and_rewrite(
        sales_text, fact_card=card, tool_calls=tool_calls
    )

    print("  ----- 原文 -----")
    print(f"  {sales_text}")
    print("  ----- 改写后 -----")
    print(f"  {new_text}")
    print(f"  warnings ({len(warnings)} 条):")
    for w in warnings:
        print(f"    · {w}")

    # 已证实数字应保留
    assert "120Hz" in new_text, "120Hz 在 tool_calls 里有命中，应保留"
    assert "5500 mAh" in new_text, "5500 mAh 在 fact_card 里有，应保留"
    assert "RM 5,999" in new_text, "RM 5,999 在 tool_calls 里有，应保留"
    # 未证实数字应改写
    assert "2ms" not in new_text, "2ms 无证据，应改写"
    assert "240Hz" not in new_text, "240Hz 无证据，应改写"

    print("  ✓ Case C 通过")


# ===========================================================================
# 提取器 smoke：再次验证 _PRODUCT_PATTERNS 的中英文混排边界
# ===========================================================================


def test_extractor() -> None:
    print("\n===== Extractor smoke =====")
    from src.preflight import extract_product_from_topic  # noqa: PLC0415

    cases = [
        ("华为手机pura x 模拟销售", "Pura X"),
        ("零售店：客户对最新 Mate 80 Pro 反复砍价", "Mate 80 Pro"),
        ("华为 matepad 12x 销售模拟", "MatePad 12X"),
        ("Pura 70 Pro vs iPhone 比较", "Pura 70 Pro"),
        ("泛聊一下手机", None),
    ]
    for topic, expected in cases:
        got = extract_product_from_topic(topic)
        flag = "✓" if got == expected else "✗"
        print(f"  {flag}  '{topic}'  ->  {got}  (expected {expected})")
        assert got == expected, f"extract 失败: {topic} 得到 {got}"
    print("  ✓ extractor 通过")


# ===========================================================================
# main
# ===========================================================================


def main() -> int:
    try:
        test_extractor()
        test_case_a_pura_x()
        test_case_b_unknown_product()
        test_case_c_grounded_check()
    except AssertionError as exc:
        print(f"\n❌ smoke FAILED: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"\n❌ smoke crashed: {exc}")
        traceback.print_exc()
        return 1
    print("\n✅ 全部 smoke 通过 (truthfulness v0.2.2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
