"""A2+A3 合并：单条销冠 turn 一次 LLM 完成多标签分类 + 每标签 6 维评分。

替代 classify_turn_multilabel + N×score_turn_six_dims，将 745 turn 的 API 次数
从 ~2200 降到 ~745，配合 turn 级并发满足 2h SLA。
"""
from __future__ import annotations

import logging
from typing import Any

from src.analyzers.handbook_classifier import has_demo_signal, shortlist_candidates
from src.analyzers.handbook_scorer import (
    SCORE_DIMENSIONS,
    _empty_score_pkg,
    build_scorecard_md,
    build_scores_json_template,
)
from src.llm import (
    LLMCallError,
    LLMJsonParseError,
    call_llm_json,
    with_llm_override,
)
from src.perf_config import aux_llm_override


logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是产品话术分类与质量评审专家。"
    "给定一条销冠发言和若干候选手册条目，请：\n"
    "1) 判断发言实质命中哪些条目（多标签，confidence≥0.4）；\n"
    "2) 对每个命中条目按新版【评分机制】三层共 6 个维度 0-10 整数打分（对照分值锚定），"
    "并给出 issues、suggestion、reference_text。\n"
    "**只输出 JSON**，结构见用户提示。"
)


def _build_merged_user_prompt(
    content: str,
    candidates: list[dict[str, Any]],
) -> str:
    cand_lines = "\n".join(
        f"- id={c['id']}  group={c.get('group','')}  label={c.get('label','')}  "
        f"text=<<{(c.get('text') or '').strip()[:200]}>>"
        for c in candidates
    )
    return (
        "## 销冠这条发言\n"
        f"```\n{content.strip()[:1200]}\n```\n\n"
        "## 候选手册条目\n"
        f"{cand_lines}\n\n"
        "## 评分机制 · 三层 6 维（每个命中条目都要填 scores，对照分值锚定）\n"
        f"{build_scorecard_md()}\n\n"
        "## 输出格式（**只输出 JSON 对象**）\n"
        "{\n"
        '  "labels": [\n'
        "    {\n"
        '      "category_id": "sell_2",\n'
        '      "confidence": 0.0~1.0,\n'
        '      "reason": "≤30字",\n'
        f'      "scores": {build_scores_json_template()},\n'
        '      "issues": ["..."],\n'
        '      "suggestion": "≤60字",\n'
        '      "reference_text": "从条目原文摘≤120字"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "规则：无实质命中 → labels 为空；最多 4 个条目；confidence<0.4 不要返回；"
        "严禁 markdown 包裹。"
    )


def _normalize_scores(raw: dict[str, Any]) -> dict[str, int]:
    scores_in = raw.get("scores") or {}
    out: dict[str, int] = {}
    for k, _ in SCORE_DIMENSIONS:
        try:
            v = int(round(float(scores_in.get(k, 0))))
        except (TypeError, ValueError):
            v = 0
        out[k] = max(0, min(10, v))
    return out


def analyze_turn_once(
    *,
    content: str,
    handbook_struct: dict,
    top_k: int = 10,
    min_confidence: float = 0.4,
) -> list[dict[str, Any]]:
    """返回 classification 行列表，可直接 insert_turn_classifications。

    每项：
      session_id / turn_idx 由调用方填入；
      category_id, confidence, scores, issues, suggestion, reference_text
    """
    content = (content or "").strip()
    if len(content) < 6:
        return []

    candidates = shortlist_candidates(
        content, handbook_struct, top_k=top_k, force_demo=has_demo_signal(content),
    )
    if not candidates:
        return []

    cand_ids = {c["id"] for c in candidates}

    try:
        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(
                _SYSTEM_PROMPT,
                _build_merged_user_prompt(content, candidates),
                temperature=0.2,
            )
    except (LLMCallError, LLMJsonParseError) as exc:
        logger.warning("[turn_analyzer] LLM 失败：%s", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[turn_analyzer] 未知异常：%s", exc)
        return []

    raw_labels: list[Any] = []
    if isinstance(raw, dict):
        raw_labels = raw.get("labels") or []
    elif isinstance(raw, list):
        raw_labels = raw

    rows: list[dict[str, Any]] = []
    for lab in raw_labels:
        if not isinstance(lab, dict):
            continue
        cid = lab.get("category_id") or lab.get("id")
        if not cid or cid not in cand_ids:
            continue
        try:
            conf = float(lab.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < min_confidence:
            continue
        pkg = _empty_score_pkg()
        if lab.get("scores"):
            pkg["scores"] = _normalize_scores(lab)
        if isinstance(lab.get("issues"), list):
            pkg["issues"] = [str(x) for x in lab["issues"][:4]]
        if lab.get("suggestion"):
            pkg["suggestion"] = str(lab["suggestion"])[:200]
        if lab.get("reference_text"):
            pkg["reference_text"] = str(lab["reference_text"])[:200]
        rows.append({
            "category_id": cid,
            "confidence": conf,
            "scores": pkg["scores"],
            "issues": pkg["issues"],
            "suggestion": pkg["suggestion"],
            "reference_text": pkg["reference_text"],
        })
    return rows
