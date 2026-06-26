"""验证 content_guard 在拿到 Handbook 后不再误杀真实数字。

模拟两种场景：
  A) 不传 handbook_text + 无 fact_card → 旧 bug 路径：所有数字都会被改写
  B) 传 handbook_text 包含 ¥3399 / 12英寸 / 100W / 14小时 → 新路径：保留
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.content_guard import verify_and_rewrite  # noqa: E402


HANDBOOK = """\
**问：MatePad 12X 256GB 多少钱？** 答：标准版 ¥3099，柔光版 ¥3399。
五大核心参数：
- 屏幕：12 英寸 144Hz 自适应高刷
- 续航：10100mAh 大电池，14 小时本地视频播放
- 充电：100W SuperCharge 超级快充
- 系统：HarmonyOS 4.3
"""

SALES_TEXT_PRICE = (
    "MatePad 12X 标准版 ¥3099 起，柔光版 ¥3399，您要试哪款？"
)
SALES_TEXT_PARAMS = (
    "这款屏幕 12 英寸，144Hz 高刷，10100mAh 电池，14 小时续航，100W 快充。"
)
SALES_TEXT_FAKE = (
    "MatePad 12X 顶配只要 ¥1999，13.2 英寸 OLED，120W 闪充。"  # 三个数字都不在 Handbook
)


def _show(label: str, text: str, **kwargs):
    new, warns = verify_and_rewrite(text, fact_card=None, **kwargs)
    print(f"\n=== {label} ===")
    print(f"  原文: {text}")
    print(f"  改写: {new}")
    print(f"  警告: {warns}")
    return new, warns


def main() -> None:
    # A) 旧 bug：handbook_text=None → fact_card 也是 None → 全杀
    a_new, a_warns = _show(
        "A · 无 handbook（旧 bug，对照组）",
        SALES_TEXT_PRICE,
        handbook_text=None,
    )
    assert any("¥3" in w for w in a_warns), "对照组应该改写价格"

    # B) 新路径：传 handbook → 价格不被改写
    b_new, b_warns = _show(
        "B · 传 handbook（修复后）",
        SALES_TEXT_PRICE,
        handbook_text=HANDBOOK,
    )
    assert "¥3099" in b_new and "¥3399" in b_new, "修复后价格必须保留"
    assert not b_warns, f"修复后不应有改写警告: {b_warns}"

    # C) 参数全部命中 Handbook → 保留
    c_new, c_warns = _show(
        "C · 参数全部命中 handbook",
        SALES_TEXT_PARAMS,
        handbook_text=HANDBOOK,
    )
    assert "12 英寸" in c_new and "100W" in c_new and "14 小时" in c_new, (
        f"修复后参数必须保留, got: {c_new}"
    )
    assert "144Hz" in c_new or "144 Hz" in c_new
    assert not c_warns, f"修复后不应有改写警告: {c_warns}"

    # D) 销售脑补数字 → 仍应改写
    d_new, d_warns = _show(
        "D · 销售脑补假数字（应改写）",
        SALES_TEXT_FAKE,
        handbook_text=HANDBOOK,
    )
    # ¥1999, 13.2英寸, 120W 都不在 Handbook，应该被改写
    # 注意 ¥1999 数字 "1999" 不在 corpus 里，13.2 也不在，120 也不在
    assert d_warns, "脑补数字应该触发警告"
    assert "1999" not in d_new or "具体" in d_new, f"假价格应被改写: {d_new}"

    print("\n✅ ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
