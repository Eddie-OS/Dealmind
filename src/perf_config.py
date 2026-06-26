"""批量模拟 / 分析报告的性能相关环境变量（商业 SLA 调优入口）。"""
from __future__ import annotations

import os

from src.llm import LLMOverride


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# 批量模拟：会话级并发（14GB 机器默认 3；可用 BATCH_SESSION_CONCURRENCY 覆盖）
BATCH_SESSION_CONCURRENCY = _env_int("BATCH_SESSION_CONCURRENCY", 3)
BATCH_JUDGE_INTERVAL = _env_int("BATCH_JUDGE_INTERVAL", 6)
BATCH_MEMORY_INTERVAL = _env_int("BATCH_MEMORY_INTERVAL", 6)

# 分析报告：turn 级并发 + 全局限流
ANALYSIS_TURN_WORKERS = _env_int("ANALYSIS_TURN_WORKERS", 16)
LLM_MAX_IN_FLIGHT = _env_int("LLM_MAX_IN_FLIGHT", 12)

# 辅助链路（judge / memory / coach / 分析）用轻量模型；销冠仍走 DB/.env 默认 pro
AUX_MODEL_NAME = os.getenv("AUX_MODEL_NAME", "deepseek-v4-flash")


def aux_llm_override(*, thinking_mode: str = "disabled") -> LLMOverride:
    """Judge / Memory / Coach / Handbook 分析等非销冠路径。"""
    return LLMOverride(model=AUX_MODEL_NAME, thinking_mode=thinking_mode)
