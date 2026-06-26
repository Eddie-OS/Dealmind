"""AI 辅助生成 Persona（人设）。

两步：
1. ``clarify_persona_idea(idea)`` —— 混合出题：固定核心题（市场/年龄/职业/预算/性格/
   异议风格，选项稳定）中挑出"用户想法里还没说清"的几道，再让 LLM 补 1-2 道针对性
   缺口题；若想法已足够完整则 ``need_clarification=False``，直接进生成。
2. ``generate_persona_draft(idea, answers)`` —— 调 LLM 产出一份与现有阿明/法汉同款的
   完整 prompt_based 人设草稿（name / prompt_text / tags / 国家·货币·信源 / profile /
   9 维 pressure），并做归一化（国家用 registry 权威覆盖货币与信源、pressure clamp）。

设计：草稿**不落库**，由前端预览/编辑后再走 POST /api/personas 创建。
所有 LLM 失败都有兜底，绝不抛到接口外炸 500。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.llm import LLMCallError, LLMJsonParseError, call_llm_json
from src.locales import COUNTRY_REGISTRY
from src.persona.pressure_extractor import DEFAULT_PRESSURE, DIMENSIONS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 固定核心题目录（选项稳定，供"混合出题"复用）
# ---------------------------------------------------------------------------

def _market_options() -> list[dict[str, str]]:
    opts = [
        {"id": m.code, "label": f"{m.name_cn}（{m.code}）"}
        for m in COUNTRY_REGISTRY.values()
    ]
    opts.append({"id": "OTHER", "label": "其他 / 不确定"})
    return opts


CORE_QUESTIONS: dict[str, dict[str, Any]] = {
    "market": {
        "id": "market",
        "prompt": "目标客户主要在哪个市场？（决定货币与可信信源）",
        "type": "single",
        "options": _market_options(),
    },
    "age_group": {
        "id": "age_group",
        "prompt": "客户大致年龄段？",
        "type": "single",
        "options": [
            {"id": "student", "label": "学生（18-24）"},
            {"id": "young", "label": "青年白领（25-34）"},
            {"id": "mid", "label": "成熟中年（35-50）"},
            {"id": "senior", "label": "年长（50+）"},
        ],
    },
    "occupation": {
        "id": "occupation",
        "prompt": "客户的职业/身份大概是？",
        "type": "single",
        "options": [
            {"id": "student", "label": "学生"},
            {"id": "office", "label": "上班族 / 白领"},
            {"id": "freelance", "label": "自由职业者"},
            {"id": "owner", "label": "企业主 / 个体户"},
            {"id": "tech", "label": "技术 / 专业人士"},
            {"id": "home", "label": "家庭主妇 / 主夫"},
            {"id": "other", "label": "其他"},
        ],
    },
    "budget": {
        "id": "budget",
        "prompt": "客户的预算与价格态度？",
        "type": "single",
        "options": [
            {"id": "tight", "label": "预算紧张，很在意价格"},
            {"id": "medium", "label": "预算适中，讲性价比"},
            {"id": "ample", "label": "预算充裕，更看重体验"},
            {"id": "rich", "label": "不差钱，要最好的"},
        ],
    },
    "personality": {
        "id": "personality",
        "prompt": "客户的性格特点？（可多选）",
        "type": "multi",
        "options": [
            {"id": "rational", "label": "理性谨慎"},
            {"id": "outgoing", "label": "外向健谈"},
            {"id": "introvert", "label": "内向少言"},
            {"id": "impatient", "label": "急性子"},
            {"id": "picky", "label": "挑剔强势"},
            {"id": "easygoing", "label": "随和好说话"},
        ],
    },
    "objection_style": {
        "id": "objection_style",
        "prompt": "客户最典型的异议/砍价风格？",
        "type": "single",
        "options": [
            {"id": "price", "label": "死磕价格、爱砍价"},
            {"id": "competitor", "label": "总拿竞品来比"},
            {"id": "skeptic", "label": "怀疑承诺、要实证"},
            {"id": "delay", "label": "拖延、再想想/问家人"},
            {"id": "emotional", "label": "情绪化、易波动"},
        ],
    },
}

_CORE_ORDER = ["market", "age_group", "occupation", "budget", "personality", "objection_style"]


# ---------------------------------------------------------------------------
# 1. 澄清/出题
# ---------------------------------------------------------------------------

def clarify_persona_idea(idea: str) -> dict[str, Any]:
    """判断 idea 是否够完整；不够则返回需要补全的题目（核心题 + AI 缺口题）。

    返回：{"need_clarification": bool, "questions": [question, ...]}
    question = {"id","prompt","type":"single|multi","options":[{"id","label"}]}
    """
    idea = (idea or "").strip()
    if not idea:
        # 完全没输入：直接抛全部核心题
        return {
            "need_clarification": True,
            "questions": [CORE_QUESTIONS[k] for k in _CORE_ORDER],
        }

    core_catalog = "\n".join(
        f"- {k}: {CORE_QUESTIONS[k]['prompt']}" for k in _CORE_ORDER
    )
    system = (
        "你是销售模拟系统的人设搭建助手。用户给出一个粗略的客户想法，"
        "你判断要生成一个鲜活、可直接用于销售模拟的完整人设，还缺哪些关键信息。"
        "只输出 JSON。"
    )
    user = (
        f"用户的粗略想法：\n{idea}\n\n"
        f"核心维度清单（id: 含义）：\n{core_catalog}\n\n"
        "请判断：\n"
        "1) need_clarification：若想法已经足够具体（至少能推断出市场、人群、预算、性格倾向），"
        "填 false；否则 true。\n"
        "2) missing：上面核心维度中，想法里**没有明确说清、也无法合理推断**的 id 列表"
        "（已能从想法推断的不要列）。\n"
        "3) extra：最多 2 道针对这个具体想法的缺口补充题（核心清单之外的关键信息，"
        "如具体使用场景、对某功能的执念等），每题 2-4 个选项。\n\n"
        '严格输出 JSON：{"need_clarification": bool, "missing": [str], '
        '"extra": [{"prompt": str, "type": "single"|"multi", "options": [str]}]}'
    )
    try:
        data = call_llm_json(system, user)
    except (LLMCallError, LLMJsonParseError) as exc:
        logger.warning("clarify_persona_idea LLM 失败，回退核心题：%s", exc)
        return {
            "need_clarification": True,
            "questions": [CORE_QUESTIONS[k] for k in _CORE_ORDER],
        }
    if not isinstance(data, dict):
        return {"need_clarification": False, "questions": []}

    need = bool(data.get("need_clarification"))
    if not need:
        return {"need_clarification": False, "questions": []}

    questions: list[dict[str, Any]] = []
    missing = data.get("missing") or []
    if isinstance(missing, list):
        for mid in missing:
            if mid in CORE_QUESTIONS:
                questions.append(CORE_QUESTIONS[mid])

    extra = data.get("extra") or []
    if isinstance(extra, list):
        for i, q in enumerate(extra[:2]):
            if not isinstance(q, dict):
                continue
            prompt = str(q.get("prompt") or "").strip()
            raw_opts = q.get("options") or []
            if not prompt or not isinstance(raw_opts, list) or len(raw_opts) < 2:
                continue
            qtype = "multi" if q.get("type") == "multi" else "single"
            options = [
                {"id": f"o{j}", "label": str(o).strip()}
                for j, o in enumerate(raw_opts[:4]) if str(o).strip()
            ]
            if len(options) >= 2:
                questions.append({
                    "id": f"extra_{i}",
                    "prompt": prompt,
                    "type": qtype,
                    "options": options,
                })

    # 兜底：判定需要补全但没产出任何题 → 给核心题
    if not questions:
        questions = [CORE_QUESTIONS[k] for k in _CORE_ORDER]
    return {"need_clarification": True, "questions": questions}


# ---------------------------------------------------------------------------
# 2. 生成完整人设草稿
# ---------------------------------------------------------------------------

def _format_answers(answers: Optional[list[dict[str, Any]]]) -> str:
    if not answers:
        return "（用户未补充额外信息，请你按想法合理设定）"
    lines = []
    for a in answers:
        if not isinstance(a, dict):
            continue
        q = str(a.get("question") or "").strip()
        v = a.get("answer")
        if isinstance(v, list):
            v = "、".join(str(x) for x in v)
        v = str(v or "").strip()
        if q and v:
            lines.append(f"- {q} → {v}")
    return "\n".join(lines) if lines else "（用户未补充额外信息）"


def _normalize_draft(raw: dict[str, Any], idea: str) -> dict[str, Any]:
    """把 LLM 产出的草稿归一化为可直接喂给 POST /api/personas 的结构。"""
    name = str(raw.get("name") or "").strip() or "新客户人设"
    prompt_text = str(raw.get("prompt_text") or "").strip()

    tags = raw.get("tags") or []
    tags = [str(t).strip() for t in tags if str(t).strip()][:8] if isinstance(tags, list) else []

    # 国家：以 registry 为权威，覆盖货币 / 信源 / 中文名
    cc = str(raw.get("country_code") or "").strip().upper()
    country_name = str(raw.get("country_name") or "").strip() or None
    currency = str(raw.get("currency") or "").strip() or None
    market_domains = raw.get("market_domains") or []
    if isinstance(market_domains, list):
        market_domains = [str(d).strip() for d in market_domains if str(d).strip()]
    else:
        market_domains = []
    if cc in COUNTRY_REGISTRY:
        m = COUNTRY_REGISTRY[cc]
        country_name = m.name_cn
        currency = m.currency
        if not market_domains:
            market_domains = list(m.market_domains)
    elif cc == "OTHER" or cc == "":
        cc = None

    # profile
    profile = raw.get("profile") or {}
    if not isinstance(profile, dict):
        profile = {}

    # pressure：clamp + 补缺
    raw_pressure = raw.get("pressure") or {}
    pressure = dict(DEFAULT_PRESSURE)
    if isinstance(raw_pressure, dict):
        for k in DIMENSIONS:
            if k in raw_pressure:
                try:
                    f = float(raw_pressure[k])
                    pressure[k] = round(min(1.0, max(0.0, f)), 2)
                except (TypeError, ValueError):
                    pass

    return {
        "name": name,
        "format_type": "prompt_based",
        "prompt_text": prompt_text,
        "tags": tags,
        "country_code": cc,
        "country_name": country_name,
        "currency": currency,
        "market_domains": market_domains,
        "profile": profile,
        "pressure": pressure,
        "avatar_key": None,
    }


def generate_persona_draft(
    idea: str,
    answers: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """调 LLM 生成一份完整 prompt_based 人设草稿（不落库）。"""
    idea = (idea or "").strip()
    answers_block = _format_answers(answers)
    markets_hint = "、".join(
        f"{m.name_cn}={m.code}/{m.currency}" for m in COUNTRY_REGISTRY.values()
    )

    system = (
        "你是资深的销售人设撰写专家。基于用户的想法 + 补充答案，产出一个鲜活、可直接用于"
        "销售模拟的【完整客户人设】。人设要有血有肉、细节具体、口吻真实，避免泛泛而谈。只输出 JSON。"
    )
    user = (
        f"## 用户想法\n{idea or '（空）'}\n\n"
        f"## 用户补充答案\n{answers_block}\n\n"
        "## 你要产出的 JSON 字段\n"
        "- name: 人设名，中文名 + 英文名，如 \"阿明 Ah Ming\"\n"
        "- prompt_text: **Markdown 格式的完整角色描述**，必须包含这些小节：\n"
        "    1) `# 标题`（人设名）后跟一段背景（年龄/职业/所在城市/收入/已有设备）；\n"
        "    2) `## 购买场景与需求`；\n"
        "    3) `## 决策风格与关注点`（用 `* **要点**：…` 列 3-4 条）；\n"
        "    4) `## 语言风格`（说话口吻、常用词、是否中英夹杂）；\n"
        "    5) `## 异议与对话风格`（典型异议、砍价方式、对销售的态度）。\n"
        "    篇幅 600-1200 字，细节落地，像真人。\n"
        "- tags: 3-6 个中文标签（如 \"价格敏感\"、\"竞品意识强\"、\"决策权高\"）\n"
        f"- country_code: 该客户所在市场的两位国家码（可选：{markets_hint}；不确定填 \"OTHER\"）\n"
        "- country_name / currency / market_domains: 按 country_code 给出（不确定可留空，后端会用权威表覆盖）\n"
        "- profile: {age:int, occupation:str, budget:str, personality:str, "
        "pain_points:[str], objection_style:str, purchase_goal:str}\n"
        "- pressure: 9 维量化（0~1 两位小数，**要按人设差异化、不要都填 0.5**）：\n"
        "    price_sensitivity, trust_threshold, patience, competitor_awareness, "
        "decision_power, emotion_volatility, need_urgency, skepticism, bargaining_aggressiveness\n\n"
        "严格输出上述字段的 JSON，不要任何解释或 markdown 代码块包裹。"
    )
    try:
        raw = call_llm_json(system, user)
    except (LLMCallError, LLMJsonParseError) as exc:
        logger.warning("generate_persona_draft LLM 失败：%s", exc)
        raise
    if not isinstance(raw, dict):
        raise ValueError("生成结果不是 JSON 对象")
    return _normalize_draft(raw, idea)
