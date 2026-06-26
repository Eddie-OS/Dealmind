"""v10.1 阶段轮次配额 smoke：测 8 / 20 / 30 / 50 轮分配是否正确。

校验三件事：
  1. 所有阶段的窗口端点 (start, end) 加起来覆盖 [1, max_rounds] 全闭区间，无空洞、无重叠；
  2. 每个阶段配额 ≥ 1（即使权重最小的 S5=5% 在 8 轮也得 ≥ 1）；
  3. 权重最大的阶段（默认 S3=40%）配额是最大；
  4. render_quota_table 输出可读 markdown 且当前阶段被高亮。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.business_stages import load_stages
from src.stage_quota import (
    compute_stage_quota,
    current_stage_phase,
    render_quota_table,
)


def assert_quota_valid(max_rounds: int) -> None:
    print(f"\n===== max_rounds = {max_rounds} =====")
    q = compute_stage_quota(max_rounds)
    cfg = load_stages()
    stage_ids = cfg.all_stage_ids()
    print("  分配:")
    for sid in stage_ids:
        s, e = q[sid]
        spec = cfg.get_stage(sid)
        w_pct = int((spec.weight if spec else 0) * 100)
        print(f"    {sid} ({w_pct:>3}%): rounds {s:>2}-{e:<2} (= {e - s + 1} 轮)")
    # 校验 1：覆盖
    cursor = 1
    for sid in stage_ids:
        s, e = q[sid]
        assert s == cursor, f"{sid} start={s} 不连续，期望 {cursor}"
        cursor = e + 1
    assert cursor - 1 == max_rounds, f"配额总和 = {cursor - 1}，期望 {max_rounds}"
    # 校验 2：每段 ≥ 1
    for sid in stage_ids:
        s, e = q[sid]
        assert e - s + 1 >= 1, f"{sid} 配额 < 1"
    # 校验 3：S3 权重最大 → 配额应也最大
    s3_count = q["S3"][1] - q["S3"][0] + 1
    for sid in stage_ids:
        if sid == "S3":
            continue
        cnt = q[sid][1] - q[sid][0] + 1
        assert s3_count >= cnt, f"S3 应有最多轮数，实得 S3={s3_count}, {sid}={cnt}"
    print("  ✓ 覆盖完整 / 每段≥1 / S3 最大")


def assert_phase_helper() -> None:
    print("\n===== current_stage_phase smoke =====")
    info = current_stage_phase(round_idx=2, current_stage_id="S1", max_rounds=20)
    print(f"  S1 round=2 (window {info['ideal_window']}) → in_window={info['in_window']}, over={info['over_budget_rounds']}")
    assert info["in_window"] is True

    info = current_stage_phase(round_idx=10, current_stage_id="S1", max_rounds=20)
    print(f"  S1 round=10 → in_window={info['in_window']}, over={info['over_budget_rounds']}")
    assert info["in_window"] is False
    assert info["over_budget_rounds"] > 0

    print("  ✓ phase helper 通过")


def render_table_check() -> None:
    print("\n===== render_quota_table for 20 rounds =====")
    md = render_quota_table(max_rounds=20, current_stage_id="S3", round_idx=12)
    print(md)
    assert "S3" in md and "你现在在这里" in md, "table 应高亮 S3"
    print("  ✓ table 输出 OK")


def main() -> int:
    try:
        for mr in (8, 20, 30, 50):
            assert_quota_valid(mr)
        assert_phase_helper()
        render_table_check()
    except AssertionError as exc:
        print(f"\n❌ smoke FAILED: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"\n❌ smoke crashed: {exc}")
        traceback.print_exc()
        return 1
    print("\n✅ stage_quota smoke 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
