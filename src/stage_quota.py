"""按 weight 等比例算每阶段的理想轮次窗口。

v10.1 混合推进机制：
  - 系统以 ``max_rounds`` 为基准生命周期，按每阶段 ``weight`` 等比例分轮次；
  - 每阶段保底 1 轮（即使权重 = 0.05 在 20 轮里也至少 1 轮）；
  - 余数补回**权重最大**的阶段；
  - 给 Judge 用："当前 round_idx 是否仍在本阶段的 ideal 窗口内？超窗多少轮？"

公共 API：
  - ``compute_stage_quota(max_rounds, cfg=None) -> dict[str, tuple[int, int]]``
      返回 {stage_id: (start_round_inclusive, end_round_inclusive)}；按 STAGE_ORDER 顺序首尾相接。
  - ``stage_window(stage_id, max_rounds, cfg=None) -> (start, end)``
  - ``current_stage_phase(round_idx, current_stage_id, max_rounds, cfg=None) -> dict``
      返回 {"in_window": bool, "over_budget_rounds": int, "ideal_window": (s,e), "rounds_left_in_stage": int}
  - ``render_quota_table(max_rounds, cfg=None) -> str``
      给 Judge prompt 用的 markdown 表（一行一阶段）。

设计原则：纯函数 + 失败安全（任何异常返回兜底配额，绝不抛）。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from src.business_stages import (
    STAGE_ORDER,
    BusinessStagesConfig,
    load_stages,
    stage_cn_name,
)

logger = logging.getLogger(__name__)


def _safe_int(v: object, default: int) -> int:
    try:
        i = int(v)
        return i if i > 0 else default
    except Exception:
        return default


def compute_stage_quota(
    max_rounds: int,
    cfg: Optional[BusinessStagesConfig] = None,
) -> Dict[str, Tuple[int, int]]:
    """按 weight 等比例切 max_rounds，保底每阶段 1 轮。

    Args:
        max_rounds: 整场会话的轮数上限（≥ 阶段数；不足时强制为 阶段数）。
        cfg: business_stages 配置（默认走 cache 单例）。

    Returns:
        ``{"S1": (1, 3), "S2": (4, 9), ...}``，端点都是 1-based、inclusive。
        若 YAML 不可用或 stages 为空，返回兜底等分配额。
    """
    try:
        cfg = cfg or load_stages()
        stage_ids = cfg.all_stage_ids() or list(STAGE_ORDER)
    except Exception as exc:  # noqa: BLE001
        logger.warning("compute_stage_quota: load_stages 失败 → 等分兜底: %s", exc)
        stage_ids = list(STAGE_ORDER)
        cfg = None

    n = max(1, len(stage_ids))
    mr = max(_safe_int(max_rounds, 8), n)  # 至少够每阶段 1 轮

    # 读 weights，缺省 = 等分
    weights: List[float] = []
    for sid in stage_ids:
        spec = cfg.get_stage(sid) if cfg else None
        w = float(spec.weight) if (spec and spec.weight > 0) else 1.0 / n
        weights.append(w)
    total_w = sum(weights) or 1.0
    weights = [w / total_w for w in weights]

    # 1) 按权重四舍五入
    raw_counts = [max(1, round(mr * w)) for w in weights]

    # 2) 修正总和到 mr —— 余数补回权重最大的阶段（保持加总 = mr）
    diff = mr - sum(raw_counts)
    if diff != 0:
        order_by_weight = sorted(range(n), key=lambda i: -weights[i])
        idx = 0
        while diff > 0:
            raw_counts[order_by_weight[idx % n]] += 1
            diff -= 1
            idx += 1
        idx = 0
        # diff < 0 时只能从权重最大、且 >1 的阶段扣
        while diff < 0:
            i = order_by_weight[idx % n]
            if raw_counts[i] > 1:
                raw_counts[i] -= 1
                diff += 1
            idx += 1
            if idx > n * 10:  # 兜底防死循环
                break

    # 3) 拼连续区间
    out: Dict[str, Tuple[int, int]] = {}
    cursor = 1
    for sid, count in zip(stage_ids, raw_counts):
        start = cursor
        end = cursor + count - 1
        out[sid] = (start, end)
        cursor = end + 1
    return out


def stage_window(
    stage_id: str,
    max_rounds: int,
    cfg: Optional[BusinessStagesConfig] = None,
) -> Tuple[int, int]:
    """单个阶段的 (start, end) 轮次窗口；未知阶段返回 (1, max_rounds)。"""
    q = compute_stage_quota(max_rounds, cfg=cfg)
    return q.get(stage_id, (1, max(1, _safe_int(max_rounds, 8))))


def current_stage_phase(
    round_idx: int,
    current_stage_id: str,
    max_rounds: int,
    cfg: Optional[BusinessStagesConfig] = None,
) -> Dict[str, object]:
    """给 Judge / Sales 用：当前轮在不在当前阶段的 ideal 窗口里？

    Returns:
        dict with:
          - ``in_window``: round_idx ∈ [start, end]
          - ``over_budget_rounds``: round_idx > end 时的超出轮数（正数），否则 0
          - ``rounds_left_in_stage``: max(0, end - round_idx)  本阶段还允许的剩余轮数
          - ``ideal_window``: (start, end)
          - ``ideal_window_str``: "1-3" 这种字符串
    """
    start, end = stage_window(current_stage_id, max_rounds, cfg=cfg)
    over = max(0, round_idx - end)
    return {
        "in_window": start <= round_idx <= end,
        "over_budget_rounds": over,
        "rounds_left_in_stage": max(0, end - round_idx),
        "ideal_window": (start, end),
        "ideal_window_str": f"{start}-{end}",
    }


def render_quota_table(
    max_rounds: int,
    current_stage_id: Optional[str] = None,
    round_idx: int = 0,
    cfg: Optional[BusinessStagesConfig] = None,
) -> str:
    """给 Judge prompt 用的 markdown 表，按 STAGE_ORDER 一行一阶段。

    若给了 current_stage_id 和 round_idx，会在当前阶段那行后面打 `← 你现在在这里 (round X/Y)` 标。
    """
    try:
        cfg = cfg or load_stages()
        q = compute_stage_quota(max_rounds, cfg=cfg)
    except Exception as exc:  # noqa: BLE001
        logger.warning("render_quota_table 失败：%s", exc)
        return "（无法渲染阶段配额表）"

    lines = [
        "| 阶段 | 中文名 | 权重 | 理想轮次窗口 | 必须发起的核心动作 |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for sid in cfg.all_stage_ids():
        spec = cfg.get_stage(sid)
        if not spec:
            continue
        start, end = q.get(sid, (0, 0))
        window_str = f"{start}-{end} 轮"
        if current_stage_id == sid and round_idx > 0:
            window_str += f" ← **你现在在这里 (round {round_idx}/{max_rounds})**"
        trigger = (spec.required_trigger or "—").replace("\n", " ").strip()
        if len(trigger) > 80:
            trigger = trigger[:78] + "…"
        lines.append(
            f"| {sid} | {stage_cn_name(sid)} | {int(spec.weight * 100)}% | {window_str} | {trigger} |"
        )
    return "\n".join(lines)
