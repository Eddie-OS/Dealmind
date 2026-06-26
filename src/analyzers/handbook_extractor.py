"""B1 · Handbook 结构化抽取器

输入：Handbook 关联的所有 handbook_files 的 parsed_text（拼接后）
输出：1/3/3/5/9/10 结构 JSON，可直接写入 product_handbooks.structure_json

抽取的 JSON 形状（与 db / agents._build_handbook_block 约定一致）：
{
  "intro_1":  { "id": "intro_1", "label": "一句话定位", "text": "..." },
  "selling_points": [
    {"id": "sell_1", "label": "卖点① ...", "text": "..."},
    {"id": "sell_2", "label": "卖点② ...", "text": "..."},
    {"id": "sell_3", "label": "卖点③ ...", "text": "..."}
  ],
  "competitor_points": [
    {"id": "comp_1", "label": "...", "vs": "iPad Air", "text": "..."},
    ...
  ],
  "core_params": [
    {"id": "param_1", "label": "屏幕", "text": "..."},
    ... 共 5 项
  ],
  "faq": [
    {"id": "faq_1", "label": "...", "q": "...", "a": "..."},
    ... 共 9 项
  ],
  "demo_actions": [
    {"id": "demo_1", "label": "...", "text": "..."},
    ... 共 10 项
  ]
}

设计要点：
  - 单次 LLM 调用拿到全部 1/3/3/5/9/10（强 schema 约束）
  - parsed_text 过长 → 截到前 ~24000 字符（DeepSeek 256K 余量足够，但
    抽取任务不需要太长上下文；截断点说明给 LLM）
  - 解析失败/缺字段 → 用占位补齐，确保结构完整；记 warnings
  - 永远返回 (struct, warnings)，不抛
"""
from __future__ import annotations

import logging
from typing import Any

from src.llm import (
    LLMCallError,
    LLMJsonParseError,
    LLMOverride,
    call_llm_json,
    with_llm_override,
)


logger = logging.getLogger(__name__)

# 数量约束（1/3/3/5/9/10）
EXPECTED_COUNTS = {
    "selling_points": 3,
    "competitor_points": 3,
    "core_params": 5,
    "faq": 9,
    "demo_actions": 10,
}

# DeepSeek 256K 上下文，抽取需要"照单全收"不丢章节，故放宽到 6 万字符
# （单份 playbook 解析后含表格通常 1.5w~4.5w 字符；超出仍会截断并告警）。
MAX_TEXT_CHARS = 60000


_SYSTEM_PROMPT = (
    "你是产品手册结构化抽取专家。任务：从训练材料文本里抽出"
    "1/3/3/5/9/10 结构 —— 1 句话定位 / 3 卖点 / 3 竞品对比 / "
    "5 核心参数 / 9 FAQ / 10 演示动作。"
    "**只输出 JSON 对象**，结构由用户提示给出。"
)


def _user_prompt(text: str, product_name: str = "") -> str:
    head = (
        f"## 产品名称\n{product_name or '（未提供）'}\n\n"
        "## 训练材料原文（节选）\n"
        f"```\n{text[:MAX_TEXT_CHARS]}\n```\n\n"
    )
    schema = (
        "## 必须输出的 JSON 结构\n"
        '{\n'
        '  "intro_1": {"id": "intro_1", "label": "一句话定位", "text": "≤80字一句话"},\n'
        '  "selling_points": [\n'
        '    {"id": "sell_1", "label": "卖点① · XXX", "text": "60-180字"},\n'
        '    {"id": "sell_2", "label": "卖点② · XXX", "text": "60-180字"},\n'
        '    {"id": "sell_3", "label": "卖点③ · XXX", "text": "60-180字"}\n'
        '  ],\n'
        '  "competitor_points": [\n'
        '    {"id": "comp_1", "label": "竞品① · 主题", "vs": "iPad/三星等", "text": "差异点 60-180字"},\n'
        '    {"id": "comp_2", "label": "...", "vs": "...", "text": "..."},\n'
        '    {"id": "comp_3", "label": "...", "vs": "...", "text": "..."}\n'
        '  ],\n'
        '  "core_params": [\n'
        '    {"id": "param_1", "label": "屏幕", "text": "具体参数+数值"},\n'
        '    {"id": "param_2", "label": "音质/键盘/...", "text": "..."},\n'
        '    {"id": "param_3", "label": "...", "text": "..."},\n'
        '    {"id": "param_4", "label": "...", "text": "..."},\n'
        '    {"id": "param_5", "label": "...", "text": "..."}\n'
        '  ],\n'
        '  "faq": [\n'
        '    {"id": "faq_1", "label": "短主题", "q": "客户问题原句", "a": "标准答案 60-200字"},\n'
        '    ... 共 9 项 (faq_1 ~ faq_9)\n'
        '  ],\n'
        '  "demo_actions": [\n'
        '    {"id": "demo_1", "label": "动作名", "text": "如何引导客户体验：动作+话术 60-150字"},\n'
        '    ... 共 10 项 (demo_1 ~ demo_10)\n'
        '  ]\n'
        '}\n\n'
    )
    rules = (
        "## 抽取规则（必须遵守）\n"
        "1. 严格 1/3/3/5/9/10 个数，少了用 \"（文档未明确提及）\" 填占位；不要多；\n"
        "2. id 命名固定（如 sell_1 ~ sell_3、faq_1 ~ faq_9），不要自创；\n"
        "3. 所有 text 字段必须忠实于原文 — 不要编造原文没有的具体数字；\n"
        "4. faq 的 q 要写客户会真问的口语句，不要写成内部讲师口吻；\n"
        "5. demo_actions 要写“销冠在店里要做的动作”，不是产品说明；\n"
        "6. 严禁加 markdown、解释、前后缀文字。"
    )
    return head + schema + rules


def extract_handbook_structure(
    *,
    parsed_text: str,
    product_name: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """主入口。返回 (structure_json, warnings)。"""
    warnings: list[str] = []
    text = (parsed_text or "").strip()
    if not text:
        warnings.append("parsed_text 为空，无法抽取")
        return _empty_struct(warnings), warnings
    if len(text) > MAX_TEXT_CHARS:
        warnings.append(f"原文过长被截断到 {MAX_TEXT_CHARS} 字符")

    try:
        from src.perf_config import aux_llm_override

        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(_SYSTEM_PROMPT, _user_prompt(text, product_name))
    except (LLMCallError, LLMJsonParseError) as exc:
        warnings.append(f"LLM 抽取失败：{type(exc).__name__}: {exc}")
        logger.warning("[extractor] LLM 失败：%s", exc)
        return _empty_struct(warnings), warnings
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"LLM 未知异常：{exc}")
        logger.exception("[extractor] 未知异常")
        return _empty_struct(warnings), warnings

    if not isinstance(raw, dict):
        warnings.append("LLM 返回不是对象，已降级为空结构")
        return _empty_struct(warnings), warnings

    # 规整 + 补齐
    out = _normalize(raw, warnings)
    return out, warnings


# ============================================================
# helper
# ============================================================

def _empty_struct(warnings: list[str]) -> dict[str, Any]:
    return {
        "intro_1": {"id": "intro_1", "label": "一句话定位", "text": "（待补充）"},
        "selling_points": [
            {"id": f"sell_{i}", "label": f"卖点{i}", "text": "（待补充）"}
            for i in range(1, 4)
        ],
        "competitor_points": [
            {"id": f"comp_{i}", "label": f"竞品对比{i}", "vs": "", "text": "（待补充）"}
            for i in range(1, 4)
        ],
        "core_params": [
            {"id": f"param_{i}", "label": f"参数{i}", "text": "（待补充）"}
            for i in range(1, 6)
        ],
        "faq": [
            {"id": f"faq_{i}", "label": f"FAQ{i}", "q": "（待补充）", "a": "（待补充）"}
            for i in range(1, 10)
        ],
        "demo_actions": [
            {"id": f"demo_{i}", "label": f"演示{i}", "text": "（待补充）"}
            for i in range(1, 11)
        ],
        "_warnings": list(warnings),
    }


def _normalize(raw: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    # intro
    intro = raw.get("intro_1") or {}
    if isinstance(intro, str):
        intro = {"id": "intro_1", "label": "一句话定位", "text": intro}
    elif not isinstance(intro, dict):
        intro = {"id": "intro_1", "label": "一句话定位", "text": "（待补充）"}
        warnings.append("intro_1 缺失或类型错误，已补占位")
    intro.setdefault("id", "intro_1")
    intro.setdefault("label", "一句话定位")
    intro["text"] = str(intro.get("text") or "").strip() or "（待补充）"

    def _fix_group(
        key: str, prefix: str, expected: int, extra_fields: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        items = raw.get(key) or []
        if not isinstance(items, list):
            warnings.append(f"{key} 不是数组，已重置")
            items = []
        out: list[dict[str, Any]] = []
        for i in range(1, expected + 1):
            src = items[i - 1] if i - 1 < len(items) else {}
            if not isinstance(src, dict):
                src = {"text": str(src)}
            cid = f"{prefix}_{i}"
            item: dict[str, Any] = {
                "id": cid,
                "label": str(src.get("label") or f"{prefix}_{i}").strip(),
            }
            for f in extra_fields:
                item[f] = str(src.get(f) or "").strip() or (
                    "（文档未明确提及）" if f != "vs" else ""
                )
            out.append(item)
        if len(items) > expected:
            warnings.append(f"{key} 多于 {expected} 项，已截断")
        elif len(items) < expected:
            warnings.append(f"{key} 不足 {expected} 项（实 {len(items)}），已补占位")
        return out

    return {
        "intro_1": intro,
        "selling_points": _fix_group("selling_points", "sell", 3, ("text",)),
        "competitor_points": _fix_group(
            "competitor_points", "comp", 3, ("vs", "text"),
        ),
        "core_params": _fix_group("core_params", "param", 5, ("text",)),
        "faq": _fix_group("faq", "faq", 9, ("q", "a")),
        "demo_actions": _fix_group("demo_actions", "demo", 10, ("text",)),
        "_warnings": list(warnings),
    }


# ============================================================
# Playbook（按人设 + 4 章流程）抽取 —— doc_type = playbook_v1
# ============================================================
#
# 与 1/3/3/5/9/10 的区别：
#   - 组织轴是「客户人设 + 销售流程 4 章」，不是「产品内容分类」；
#   - 变长：卖点/竞品异议对/FAQ 数量不固定，照单全收，不截断、不补占位；
#   - 演示动作内嵌在卖点 / FAQ 里，不单列章节。

PLAYBOOK_DOC_TYPE = "playbook_v1"

_PLAYBOOK_SYSTEM_PROMPT = (
    "你是销售 Playbook 结构化抽取专家。输入是一份『店内销售流程手册』，"
    "它按销售流程 4 章组织：开场破冰(open) / 核心卖点(say) / 竞品应对(compete) / "
    "常见问答(respond)，并且开场与卖点是**按客户人设(A/B/C/D)**分别给话术的。"
    "请忠实抽取，保持原文语言（英文就保留英文，不要翻译），数量照原文实际有多少抽多少，"
    "不要凑数也不要截断。**只输出 JSON 对象**，结构见用户提示。"
)


def _playbook_user_prompt(text: str, product_name: str = "") -> str:
    head = (
        f"## 产品名称\n{product_name or '（未提供）'}\n\n"
        "## 训练材料原文（节选）\n"
        f"```\n{text[:MAX_TEXT_CHARS]}\n```\n\n"
    )
    schema = (
        "## 必须输出的 JSON 结构\n"
        '{\n'
        '  "doc_type": "playbook_v1",\n'
        '  "product_name": "产品名",\n'
        '  "open": {\n'
        '    "opener": "一句通用开场问句",\n'
        '    "timing_cue": "时机提示（没有就空串）",\n'
        '    "persona_openers": [\n'
        '      {"persona": "A", "persona_label": "Business Professional", "text": "针对该人设的一句开场定位"},\n'
        '      {"persona": "B", "persona_label": "...", "text": "..."}\n'
        '    ]\n'
        '  },\n'
        '  "say": [\n'
        '    {"persona": "A", "persona_label": "Business Professional", "points": [\n'
        '      {"label": "卖点名", "text": "卖点话术正文", "demo": "演示动作步骤，没有就空串"}\n'
        '    ]}\n'
        '  ],\n'
        '  "compete": [\n'
        '    {"vs": "竞品名(如 iPad Air / Samsung Galaxy Tab)", "note": "一句备注，可空",\n'
        '     "pairs": [{"customer": "客户异议原句", "response": "我方应答原文"}]}\n'
        '  ],\n'
        '  "respond": [\n'
        '    {"q": "客户问题原句", "a": "标准答案原文", "demo": "演示动作，没有就空串"}\n'
        '  ]\n'
        '}\n\n'
    )
    rules = (
        "## 抽取规则（必须遵守）\n"
        "1. 数量按原文实际，有几个写几个；不要截断、不要补凑、不要写占位；\n"
        "2. persona 用单字母 A/B/C/D，persona_label 用原文人设名（如 Business Professional / Student）；\n"
        "3. 所有正文忠实原文，保持原语言，不翻译、不改写、不编造数字；\n"
        "4. 卖点/FAQ 里若原文带店内演示动作（如 ATTACH→OPEN→SHOW），放进 demo 字段；\n"
        "5. compete 按竞品分组，每个竞品下放它的全部「客户说/我方应答」对；\n"
        "6. 严禁加 markdown、解释、前后缀文字。"
    )
    return head + schema + rules


def extract_playbook_structure(
    *,
    parsed_text: str,
    product_name: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Playbook（doc_type=playbook_v1）结构抽取。返回 (structure_json, warnings)。"""
    warnings: list[str] = []
    text = (parsed_text or "").strip()
    if not text:
        warnings.append("parsed_text 为空，无法抽取")
        return _empty_playbook_struct(warnings), warnings
    if len(text) > MAX_TEXT_CHARS:
        warnings.append(f"原文过长被截断到 {MAX_TEXT_CHARS} 字符")

    try:
        from src.perf_config import aux_llm_override

        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(
                _PLAYBOOK_SYSTEM_PROMPT, _playbook_user_prompt(text, product_name)
            )
    except (LLMCallError, LLMJsonParseError) as exc:
        warnings.append(f"LLM 抽取失败：{type(exc).__name__}: {exc}")
        logger.warning("[extractor] playbook LLM 失败：%s", exc)
        return _empty_playbook_struct(warnings), warnings
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"LLM 未知异常：{exc}")
        logger.exception("[extractor] playbook 未知异常")
        return _empty_playbook_struct(warnings), warnings

    if not isinstance(raw, dict):
        warnings.append("LLM 返回不是对象，已降级为空结构")
        return _empty_playbook_struct(warnings), warnings

    return _normalize_playbook(raw, product_name, warnings), warnings


def _empty_playbook_struct(warnings: list[str]) -> dict[str, Any]:
    return {
        "doc_type": PLAYBOOK_DOC_TYPE,
        "product_name": "",
        "open": {"opener": "", "timing_cue": "", "persona_openers": []},
        "say": [],
        "compete": [],
        "respond": [],
        "_warnings": list(warnings),
    }


def _norm_str(v: Any) -> str:
    return str(v or "").strip()


def _normalize_playbook(
    raw: dict[str, Any], product_name: str, warnings: list[str]
) -> dict[str, Any]:
    # open
    raw_open = raw.get("open") if isinstance(raw.get("open"), dict) else {}
    persona_openers: list[dict[str, Any]] = []
    for po in raw_open.get("persona_openers") or []:
        if not isinstance(po, dict):
            continue
        txt = _norm_str(po.get("text"))
        if not txt:
            continue
        persona_openers.append({
            "persona": _norm_str(po.get("persona")) or "?",
            "persona_label": _norm_str(po.get("persona_label")),
            "text": txt,
        })

    # say（按人设分组，变长）
    say: list[dict[str, Any]] = []
    for blk in raw.get("say") or []:
        if not isinstance(blk, dict):
            continue
        persona = _norm_str(blk.get("persona")) or "?"
        points: list[dict[str, Any]] = []
        for n, p in enumerate(blk.get("points") or [], 1):
            if not isinstance(p, dict):
                continue
            text = _norm_str(p.get("text"))
            if not text and not _norm_str(p.get("label")):
                continue
            points.append({
                "id": f"say_{persona}_{n}",
                "label": _norm_str(p.get("label")),
                "text": text,
                "demo": _norm_str(p.get("demo")),
            })
        if points:
            say.append({
                "persona": persona,
                "persona_label": _norm_str(blk.get("persona_label")),
                "points": points,
            })

    # compete（按竞品分组，每组多对异议/应答）
    compete: list[dict[str, Any]] = []
    for n, blk in enumerate(raw.get("compete") or [], 1):
        if not isinstance(blk, dict):
            continue
        pairs: list[dict[str, Any]] = []
        for pr in blk.get("pairs") or []:
            if not isinstance(pr, dict):
                continue
            cust = _norm_str(pr.get("customer"))
            resp = _norm_str(pr.get("response"))
            if not (cust or resp):
                continue
            pairs.append({"customer": cust, "response": resp})
        if pairs:
            compete.append({
                "id": f"comp_{n}",
                "vs": _norm_str(blk.get("vs")),
                "note": _norm_str(blk.get("note")),
                "pairs": pairs,
            })

    # respond（FAQ，变长）
    respond: list[dict[str, Any]] = []
    for n, q in enumerate(raw.get("respond") or [], 1):
        if not isinstance(q, dict):
            continue
        qq = _norm_str(q.get("q"))
        aa = _norm_str(q.get("a"))
        if not (qq or aa):
            continue
        respond.append({
            "id": f"faq_{n}",
            "q": qq,
            "a": aa,
            "demo": _norm_str(q.get("demo")),
        })

    if not persona_openers and not say:
        warnings.append("playbook 抽取缺少开场/卖点，可能不是 playbook 文档")

    return {
        "doc_type": PLAYBOOK_DOC_TYPE,
        "product_name": _norm_str(raw.get("product_name")) or _norm_str(product_name),
        "open": {
            "opener": _norm_str(raw_open.get("opener")),
            "timing_cue": _norm_str(raw_open.get("timing_cue")),
            "persona_openers": persona_openers,
        },
        "say": say,
        "compete": compete,
        "respond": respond,
        "_warnings": list(warnings),
    }
