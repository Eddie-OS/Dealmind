"""调 LLM 从 prompt_text 抽取 9 维量化压力参数。

接口：
- extract_pressure_profile(prompt_text) -> dict[str, float]

失败兜底：返回所有维度=0.5 + raise=False。
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.llm import LLMCallError, LLMJsonParseError, call_llm_json

logger = logging.getLogger(__name__)


_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "pressure_extractor_prompt.md"

DIMENSIONS: tuple[str, ...] = (
    "price_sensitivity",
    "trust_threshold",
    "patience",
    "competitor_awareness",
    "decision_power",
    "emotion_volatility",
    "need_urgency",
    "skepticism",
    "bargaining_aggressiveness",
)

DEFAULT_PRESSURE: dict[str, float] = {k: 0.5 for k in DIMENSIONS}


def _load_template() -> str:
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt 模板缺失: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _coerce_float(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.5
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return round(f, 2)


def extract_pressure_profile(prompt_text: str) -> dict[str, float]:
    """对 prompt_text 调一次 LLM，返回完整 9 维 dict。

    - 缺失字段补 0.5
    - 越界值 clamp 到 [0,1]
    - 调用/解析失败返回全 0.5 并记录 warning
    """
    if not prompt_text or not prompt_text.strip():
        logger.warning("pressure_extractor: prompt_text 为空，返回默认 0.5")
        return DEFAULT_PRESSURE.copy()

    template = _load_template()
    user_prompt = template.replace("{persona_prompt}", prompt_text.strip())
    system_prompt = (
        "你是消费者行为分析助手。严格输出包含 9 个浮点字段的 JSON 对象，"
        "不要任何解释、markdown 包裹或额外字段。"
    )

    try:
        raw = call_llm_json(system_prompt, user_prompt, temperature=0.0)
    except (LLMCallError, LLMJsonParseError) as exc:
        logger.warning("pressure_extractor LLM 调用失败，返回默认值: %s", exc)
        return DEFAULT_PRESSURE.copy()

    if not isinstance(raw, dict):
        logger.warning("pressure_extractor LLM 返回非 dict（%s），返回默认值", type(raw).__name__)
        return DEFAULT_PRESSURE.copy()

    result: dict[str, float] = {}
    for k in DIMENSIONS:
        result[k] = _coerce_float(raw.get(k, 0.5))
    return result
