"""验证 content_guard v0.2.4：派生价格放行(B1) + 兜底话术去重(Layer 1)。

复现并回归 outputs/session_20260624_103327_p1 里销冠"复读兜底"导致客户流失的 bug：
  - 折抵估值 / 月供等派生价格被每轮抹成同一句兜底
  - 一条消息里同一兜底被堆叠成 "[兜底]-[兜底]……[兜底]"
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

DISCLAIMER = "准确价格我让同事现场给您调单核一下"

# 基准价 RM 2,025 在 handbook 里 → grounded，可作为 B1 锚点
HANDBOOK = "华为平板 12X（256GB）官方售价 RM 2,025，支持 0% 分期。"


def _show(label: str, text: str, **kwargs):
    new, warns = verify_and_rewrite(text, fact_card=None, **kwargs)
    print(f"\n=== {label} ===")
    print(f"  原文: {text}")
    print(f"  改写: {new}")
    print(f"  警告: {warns}")
    return new, warns


def main() -> None:
    # A) 旧 bug 复现：无 handbook 锚点 + 价格区间 + 月供 → 旧逻辑会复读兜底。
    #    修复后：兜底只出现一次（区间合并 + 跨子句去重）。
    a_text = (
        "您的iPad Air预计可折 RM 1,800–RM 2,000，具体看检测。"
        "12个月0%分期支持Maybank，月供约 RM 168 起。现在确认卡种就能开单。"
    )
    a_new, _ = _show("A · 无锚点·区间+月供（去重后兜底仅 1 次）", a_text, handbook_text=None)
    assert a_new.count(DISCLAIMER) == 1, f"兜底应只出现 1 次，实际 {a_new.count(DISCLAIMER)}：{a_new}"
    assert f"{DISCLAIMER}-{DISCLAIMER}" not in a_new and f"{DISCLAIMER}–{DISCLAIMER}" not in a_new, "不应出现相邻复读"

    # B) B1 核心：有基准价锚点(RM 2,025 grounded) → 同消息折抵区间 + 月供 + 每日成本全部放行。
    b_text = (
        "您的iPad Air初评可折 RM 1,800–RM 2,000，最终以现场检测为准。"
        "华为平板12X 售价 RM 2,025，Maybank 12个月0%分期，月供约 RM 168，每天不到 RM 9。"
    )
    b_new, b_warns = _show("B · 有锚点·派生价格全放行", b_text, handbook_text=HANDBOOK)
    for keep in ("RM 1,800", "RM 2,000", "RM 2,025", "RM 168", "RM 9"):
        assert keep in b_new, f"派生/基准价 {keep} 应被保留：{b_new}"
    assert DISCLAIMER not in b_new and not b_warns, f"有锚点时不应改写：{b_warns}"

    # C) B1 不是"放行一切"：有锚点，但非派生语境的"假兄弟价格"仍要被改写。
    c_text = "标准版 RM 2,025，顶配只要 RM 1,499。"
    c_new, c_warns = _show("C · 有锚点·假兄弟价仍改写", c_text, handbook_text=HANDBOOK)
    assert "RM 2,025" in c_new, f"基准价应保留：{c_new}"
    assert "RM 1,499" not in c_new and DISCLAIMER in c_new, f"非派生假价应改写：{c_new}"

    # D) 硬参数不受 B1 影响：即便有价格锚点，未证实的延迟仍要改写。
    d_text = "屏幕手写笔延迟只有 75ms，售价 RM 2,025。"
    d_new, d_warns = _show("D · 硬参数仍严格校验", d_text, handbook_text=HANDBOOK)
    assert "75ms" not in d_new, f"未证实延迟应改写：{d_new}"
    assert "RM 2,025" in d_new, f"基准价应保留：{d_new}"
    assert any("75ms" in w for w in d_warns), f"应有延迟改写警告：{d_warns}"

    # E) 金融百分比不再被误判成电量；真正的电量百分比仍要改写。
    e_text = "支持 0% 分期，首付 30%，年化 5%。"
    e_new, e_warns = _show("E · 金融百分比不误判", e_text, handbook_text=None)
    assert "0%" in e_new and "30%" in e_new and "5%" in e_new, f"金融百分比应原样保留：{e_new}"
    assert "耗电" not in e_new and not e_warns, f"不应触发电量改写：{e_warns}"

    e2_text = "导航1小时耗电 88%，完全没问题。"
    e2_new, e2_warns = _show("E2 · 真实电量百分比仍改写", e2_text, handbook_text=None)
    assert "88%" not in e2_new, f"未证实电量应改写：{e2_new}"
    assert "准确耗电数据" in e2_new, f"应改写为电量兜底：{e2_new}"

    # F) 裸数字宽松匹配收紧：短数字不再被更大数字蒙混成"已证实"。
    f_text = "手写笔延迟只有 1ms。"
    f_hb = "官方售价 RM 2,025，12 个月分期。"  # 含 2025 / 12，旧逻辑会让 "1" 蒙混通过
    f_new, f_warns = _show("F · 短数字不被子串蒙混", f_text, handbook_text=f_hb)
    assert "1ms" not in f_new, f"未证实延迟应改写（不应被 2025/12 蒙混）：{f_new}"
    assert any("1ms" in w for w in f_warns), f"应有延迟改写警告：{f_warns}"

    print("\n✅ ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
