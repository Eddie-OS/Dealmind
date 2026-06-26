"""A3 · Handbook 话术质量评分器（新版三层 · 6 维评分机制）

针对**一条 (turn, category_id)** 给出：
  - scores: 6 个 0-10 分维度
  - issues: 一条话术存在的具体问题列表
  - suggestion: 一句改进建议（≤ 60 字）
  - reference_text: 命中的 Handbook 原文摘录（用于报告页 hover 看依据）

新版【评分机制】三层 · 6 维（每维含评测定义 + 0~3/4~7/8~10 分值锚定）：
  第一层 · 信任基石（Trust Foundation）
    1. spec_veracity        参数真实性 (Specification Veracity)
    2. behavior_compliance  行为合规性 (Behavioral Compliance)
  第二层 · 价值传递（Value Delivery）
    3. need_alignment       需求匹配度 (Need Alignment)
    4. consumer_language    表达 2C 化 (Consumer-Facing Language)
  第三层 · 转化驱动（Conversion Drive）
    5. delivery_appeal      表达感染力 (Delivery & Rhythm)
    6. conversion_push      转化推进力 (Conversion Promotion)

设计要点：
  - 单次 LLM 调用同时给出 6 维度 + issues + suggestion + reference_text；
  - reference_text 取自 candidate.text，由 LLM 选最贴合的一段（≤120字）；
  - 出错 → 返回全 0 + 错误标注，绝不抛。
"""
from __future__ import annotations

import logging
from typing import Any

from src.llm import LLMCallError, LLMJsonParseError, call_llm_json, with_llm_override
from src.perf_config import aux_llm_override


logger = logging.getLogger(__name__)

# 新版评分机制：三层 · 6 维。每维含评测定义 + 三档分值锚定，作为唯一事实源，
# 供打分 prompt、方法论说明、报告展示统一引用，确保口径不漂移。
SCORE_DIMENSION_SPEC: list[dict[str, Any]] = [
    {
        "key": "spec_veracity",
        "layer": "信任基石", "layer_en": "Trust Foundation",
        "name": "参数真实性", "name_en": "Specification Veracity",
        "definition": "话术的事实严谨度。核查数字、政策、核心卖点，是否与官方最新资料标准表述保持一致，确保信息准确无误、无误导性。",
        "anchors": {
            "0-3": "核心参数有误、随意承诺政策、虚构产品卖点。",
            "4-7": "核心内容无误，部分术语表述不规范，非关键数据存在模糊表述。",
            "8-10": "表述完全对标官方标准，用词精准、信息明确。",
        },
    },
    {
        "key": "behavior_compliance",
        "layer": "信任基石", "layer_en": "Trust Foundation",
        "name": "行为合规性", "name_en": "Behavioral Compliance",
        "definition": "话术的合规边界感。严格恪守权限范围，不贬低竞品、不作出无法兑现的承诺，保持专业职业素养。",
        "anchors": {
            "0-3": "越权承诺、恶意诋毁竞品、过度夸大承诺。",
            "4-7": "未触碰合规红线，但部分表述存在擦边，敏感问题回应含糊。",
            "8-10": "严守规则底线，言行得体，展现专业职业形象。",
        },
    },
    {
        "key": "need_alignment",
        "layer": "价值传递", "layer_en": "Value Delivery",
        "name": "需求匹配度", "name_en": "Need Alignment",
        "definition": "价值的精准交付力。摒弃通用模板，内容、卖点与应答逻辑，紧密贴合客户实际场景、痛点与顾虑，确保\u201c给到客户想要的价值\u201d。",
        "anchors": {
            "0-3": "脱离客户诉求，机械套用固定话术，自说自话，无法传递有效价值。",
            "4-7": "方向基本契合，但多使用通用方案，缺少针对性调整，价值传递流于表面。",
            "8-10": "内容量身适配，句句回应客户诉求与实际场景，实现价值的精准对接。",
        },
    },
    {
        "key": "consumer_language",
        "layer": "价值传递", "layer_en": "Value Delivery",
        "name": "表达2C化", "name_en": "Consumer-Facing Language",
        "definition": "价值的通俗转化力。将专业参数、官方内容转化为大众易懂的语言，结合数据、场景、对比，降低客户理解成本，确保\u201c客户能听懂价值\u201d。",
        "anchors": {
            "0-3": "堆砌专业术语，或内容空洞、缺乏有效信息，导致价值信息断联。",
            "4-7": "包含数据或场景描述，但二者结合不足，缺少直观对比，价值感知不够强烈。",
            "8-10": "数据、场景、对比相辅相成，复杂内容通俗化，让价值感知跃然纸上。",
        },
    },
    {
        "key": "delivery_appeal",
        "layer": "转化驱动", "layer_en": "Conversion Drive",
        "name": "表达感染力", "name_en": "Delivery & Rhythm",
        "definition": "话术的节奏掌控力。规避生硬冗长的朗读式表达，语气自然有共情、节奏张弛有度，主动引导沟通走向。",
        "anchors": {
            "0-3": "语气冷漠、语句拖沓，如同机械念稿。",
            "4-7": "表达通顺流畅，外加节奏平淡，情绪与引导性不足。",
            "8-10": "表达简练有力，共情到位，全程掌控沟通节奏与主动权。",
        },
    },
    {
        "key": "conversion_push",
        "layer": "转化驱动", "layer_en": "Conversion Drive",
        "name": "转化推进力", "name_en": "Conversion Promotion",
        "definition": "话术的进程推动力。懂得主动把沟通往前推，绝不在一个话题上原地打转；引导动作衔接自然，不强硬逼单，同步给到客户下一步明确、简单的行动选择。",
        "anchors": {
            "0-3": "全程原地打转，没有推进意识；或者强推硬催、强行逼单，让客户产生抵触。",
            "4-7": "只有在最后快结束时才提一句下一步，或者推进得太突兀、门槛太高，客户接不住。",
            "8-10": "整个过程都在顺势往前带节奏，推进动作自然不生硬，每一步都给客户准备好了极好落地的下一步选项。",
        },
    },
]

# 优秀话术判定 / 迭代建议里"解耦手册一致性"时需剔除的维度（= 参数真实性，对应旧 accuracy）。
EXCELLENCE_EXCLUDE_DIM = "spec_veracity"


def _compact_desc(d: dict[str, Any]) -> str:
    a = d["anchors"]
    return (
        f"{d['definition']}"
        f"（0~3：{a['0-3']} 4~7：{a['4-7']} 8~10：{a['8-10']}）"
    )


# 维度键 + 中文说明（保持 (key, desc) 形态，兼容所有 `for k, desc in SCORE_DIMENSIONS` 的遍历）
SCORE_DIMENSIONS: list[tuple[str, str]] = [
    (d["key"], f"{d['name']}：{_compact_desc(d)}") for d in SCORE_DIMENSION_SPEC
]

# 维度键 → 中文短标签（供报告 why_good / why_bad 展示）
DIM_LABEL: dict[str, str] = {d["key"]: d["name"] for d in SCORE_DIMENSION_SPEC}


def build_scorecard_md() -> str:
    """渲染新版三层评分卡（给打分 prompt 看，含定义 + 三档锚定）。"""
    lines: list[str] = []
    cur_layer = None
    for d in SCORE_DIMENSION_SPEC:
        if d["layer"] != cur_layer:
            cur_layer = d["layer"]
            lines.append(f"【{d['layer']}（{d['layer_en']}）】")
        a = d["anchors"]
        lines.append(
            f"- {d['key']}（{d['name']} / {d['name_en']}）：{d['definition']}\n"
            f"    · 0~3（不合格）：{a['0-3']}\n"
            f"    · 4~7（良好）：{a['4-7']}\n"
            f"    · 8~10（优秀）：{a['8-10']}"
        )
    return "\n".join(lines)


def build_scores_json_template() -> str:
    """按当前维度键生成打分 JSON 模板片段，避免在多处硬编码维度名。"""
    inner = ",\n".join(f'    "{d["key"]}": 0-10' for d in SCORE_DIMENSION_SPEC)
    return "{\n" + inner + "\n  }"


_SYSTEM_PROMPT = (
    "你是销售话术质量评审专家。给定一条销冠发言和它命中的 Handbook 条目，"
    "请严格按新版【评分机制】三层共 6 个维度逐项打分（整数 0-10，对照每档分值锚定），"
    "并指出具体 issues 和一句改进建议。**只输出 JSON**，结构见用户提示。"
)


def _build_user_prompt(
    content: str,
    category: dict[str, Any],
) -> str:
    cat_text = (category.get("text") or "").strip()
    cat_label = category.get("label") or category.get("id") or ""
    cat_group = category.get("group") or ""
    return (
        "## 销冠这条发言\n"
        f"```\n{content.strip()[:1200]}\n```\n\n"
        "## 它命中的 Handbook 条目\n"
        f"- id: {category.get('id')}\n"
        f"- group: {cat_group}\n"
        f"- label: {cat_label}\n"
        f"- 原文: {cat_text[:400]}\n\n"
        "## 评分机制 · 三层 6 维（每项 0-10 整数，严格对照分值锚定）\n"
        f"{build_scorecard_md()}\n\n"
        "## 输出格式（**只输出 JSON 对象**）\n"
        '{\n'
        f'  "scores": {build_scores_json_template()},\n'
        '  "issues": ["issue1", "issue2"],\n'
        '  "suggestion": "一句话改进建议（≤60 字）",\n'
        '  "reference_text": "从『原文』中摘出最贴合的一段（≤120 字）"\n'
        '}\n\n'
        "硬要求：\n"
        "1. 所有 score 必须是 0-10 整数；缺一律按 0 处理；\n"
        "2. issues 用一句话指出问题，最多 4 条；如无问题给空数组；\n"
        "3. 严禁加 markdown、解释、前后缀文字。"
    )


def _empty_score_pkg() -> dict[str, Any]:
    return {
        "scores": {k: 0 for k, _ in SCORE_DIMENSIONS},
        "issues": [],
        "suggestion": "",
        "reference_text": "",
    }


def _looked_up_category(struct: dict, category_id: str) -> dict[str, Any]:
    """从 struct 找到 category_id 对应的条目，构造 {id,group,label,text}。"""
    intro = struct.get("intro_1") or {}
    if category_id == "intro_1":
        return {
            "id": "intro_1", "group": "intro",
            "label": intro.get("label") or "一句话定位",
            "text": intro.get("text") or "",
        }
    group_map = {
        "sell": "selling_points",
        "comp": "competitor_points",
        "param": "core_params",
        "faq": "faq",
        "demo": "demo_actions",
    }
    prefix = category_id.split("_")[0]
    grp = group_map.get(prefix)
    if not grp:
        return {"id": category_id, "group": "?", "label": category_id, "text": ""}
    for it in struct.get(grp) or []:
        if (it.get("id") or "") == category_id:
            if grp == "faq":
                return {
                    "id": category_id, "group": grp,
                    "label": it.get("label") or "",
                    "text": f"Q: {it.get('q','')}\nA: {it.get('a','')}",
                }
            if grp == "competitor_points":
                vs = it.get("vs") or ""
                return {
                    "id": category_id, "group": grp,
                    "label": it.get("label") or "",
                    "text": (f"（vs {vs}）" if vs else "") + (it.get("text") or ""),
                }
            return {
                "id": category_id, "group": grp,
                "label": it.get("label") or "",
                "text": it.get("text") or "",
            }
    return {"id": category_id, "group": grp, "label": category_id, "text": ""}


def score_turn_six_dims(
    *,
    content: str,
    category_id: str,
    handbook_struct: dict,
) -> dict[str, Any]:
    """返回 { scores, issues, suggestion, reference_text }，永不抛。"""
    content = (content or "").strip()
    if not content or not category_id:
        return _empty_score_pkg()

    cat = _looked_up_category(handbook_struct or {}, category_id)
    try:
        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(_SYSTEM_PROMPT, _build_user_prompt(content, cat))
    except (LLMCallError, LLMJsonParseError) as exc:
        logger.warning("[scorer] LLM 失败 cid=%s: %s", category_id, exc)
        return _empty_score_pkg()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[scorer] LLM 未知异常 cid=%s: %s", category_id, exc)
        return _empty_score_pkg()

    raw = raw or {}
    if not isinstance(raw, dict):
        return _empty_score_pkg()

    scores_in = raw.get("scores") or {}
    scores_out: dict[str, int] = {}
    for k, _ in SCORE_DIMENSIONS:
        try:
            v = int(round(float(scores_in.get(k, 0))))
        except (TypeError, ValueError):
            v = 0
        scores_out[k] = max(0, min(10, v))

    issues = raw.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    issues = [str(x)[:120] for x in issues][:4]

    return {
        "scores": scores_out,
        "issues": issues,
        "suggestion": str(raw.get("suggestion") or "")[:120],
        "reference_text": str(raw.get("reference_text") or cat.get("text") or "")[:280],
    }
