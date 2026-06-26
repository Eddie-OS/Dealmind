"""Stage 11：销售案例集（Sales Case Collection）。

三轨自动入库：
- judge_auto: session 结束时 dialogue_quality_score >= 8.0 自动整场归档
- coach_auto: 遍历 coach_review.what_worked 按 round 抽 ±N 轮上下文归档
- manual:     会话详情页人工「收藏为案例」

预填：
- preset: 启动时解析 4 个 .pptx 训练文件作为案例
"""

from src.cases.extractor import (
    HIGH_SCORE_THRESHOLD,
    auto_extract_cases,
    extract_judge_auto_case,
    extract_coach_auto_cases,
    save_manual_case_from_turn,
)
from src.cases.seed import seed_preset_cases_if_empty

__all__ = [
    "HIGH_SCORE_THRESHOLD",
    "auto_extract_cases",
    "extract_judge_auto_case",
    "extract_coach_auto_cases",
    "save_manual_case_from_turn",
    "seed_preset_cases_if_empty",
]
