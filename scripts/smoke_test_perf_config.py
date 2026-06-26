#!/usr/bin/env python3
"""快速校验性能配置与合并分析模块可导入。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.perf_config import (  # noqa: E402
    ANALYSIS_TURN_WORKERS,
    BATCH_SESSION_CONCURRENCY,
    LLM_MAX_IN_FLIGHT,
    AUX_MODEL_NAME,
)
from src.analyzers.handbook_turn_analyzer import analyze_turn_once  # noqa: E402


def main() -> None:
    assert BATCH_SESSION_CONCURRENCY >= 1
    assert ANALYSIS_TURN_WORKERS >= 1
    assert LLM_MAX_IN_FLIGHT >= 1
    assert AUX_MODEL_NAME
    assert callable(analyze_turn_once)
    print("perf_config OK:", {
        "BATCH_SESSION_CONCURRENCY": BATCH_SESSION_CONCURRENCY,
        "ANALYSIS_TURN_WORKERS": ANALYSIS_TURN_WORKERS,
        "LLM_MAX_IN_FLIGHT": LLM_MAX_IN_FLIGHT,
        "AUX_MODEL_NAME": AUX_MODEL_NAME,
    })


if __name__ == "__main__":
    main()
