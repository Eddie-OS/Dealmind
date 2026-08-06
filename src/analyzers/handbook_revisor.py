"""⑤ 手册迭代建议 —— 按 135910 的 31 个条目**逐条**生成。

旧 `_build_revision_proposals` 只对"未覆盖 / 短板 / 全局维度"出建议，导致：
  - 覆盖不全（表现好的条目完全没建议）；
  - 内容重复（同组套用同一模板）。

本模块按手册结构顺序（1→3→3→5→9→10）遍历全部 31 个条目，每条都：
  1) 汇总销冠在真实对话里对它的演绎（命中次数 / 场次 / 非 accuracy 维度均分 / 问题）；
  2) 取 TOP3 命中该条目的优秀原声（按非 accuracy 维度均分排序，与改动⑥"解耦手册
     一致性"理念一致）用于展示；
  3) 把该条目命中的**全部**真实演绎交给 LLM，产出
     {status(保持/强化/修正), assessment, suggestion, revised_text(对原文这一句的改写后版本)}——
     **即使表现很好也必须给出能让它更强的具体建议**；
  4) LLM 不可用 / 失败时回退到确定性模板，保证永远有产出。
"""
from __future__ import annotations

import logging
import re as _re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Optional

from src.analyzers.handbook_classifier import _iter_categories
from src.analyzers.handbook_scorer import EXCELLENCE_EXCLUDE_DIM
from src.llm import (
    LLMCallError,
    LLMJsonParseError,
    call_llm_json,
    with_llm_override,
)
from src.perf_config import aux_llm_override

logger = logging.getLogger(__name__)

_GROUP_CN = {
    "intro": "一句话定位",
    "sell": "核心卖点",
    "comp": "竞品对比",
    "param": "核心参数",
    "faq": "FAQ",
    "demo": "现场演示",
    # playbook_v1
    "open": "开场破冰",
    "say": "核心卖点（按人设）",
    "compete": "竞品应对",
    "respond": "常见问答",
}
# 状态精简为 3 个：补充并入强化、新增（死条目）并入修正，只保留 保持/强化/修正。
_STATUS_VALID = {"保持", "强化", "修正"}
_STATUS_MERGE = {"补充": "强化", "新增": "修正"}


def _normalize_status(status: str) -> str:
    """把 LLM 可能给出的旧 5 状态归一到 3 状态；不识别返回空串。"""
    s = (status or "").strip()
    s = _STATUS_MERGE.get(s, s)
    return s if s in _STATUS_VALID else ""
# 每条目现在携带「全部命中原声」，单条 prompt 体量变大，故缩小每次分片的条目数。
_LLM_CHUNK = 3
_TOP_QUOTES = 3
# 展示用原声的最低分类置信度：分类器对 0.4–0.6 的"隐含相关"归属常常文不对题
# （如开场白条目的关键词误命中对话中段讲 WPS/演示的销售轮），只把"明显引用大意"
# 及以上（≥0.6）的轮次作为该条目的参考范例展示；喂给 LLM 的 _samples 仍取全量。
_QUOTE_MIN_CONF = 0.6
# 开场破冰条目额外的"对话位置"闸门：开场白正文的关键词（WPS/Excel/键盘…）与卖点/
# 演示高度重叠，分类器会把对话中段的演示/报价轮高置信地误判成开场。开场的本质是
# "对话起手"，因此其展示范例必须来自每场最靠前的销售轮（turn idx≤此阈值，即前几轮）。
_OPEN_MAX_TURN_IDX = 2
# 改动量阈值：改写与原文「去空白后」的字符相似度 ≥ 此值视为「伪改写」（只换了一两个词
# 或在原文后拼一句问候），既触发二次精修、也用于最终的「微调·未实质重写」交付标记。
# 开场板块原文是「客户识别线索」而非话术，天然与改写低相似，故对 open 不做此判定。
_NEAR_IDENTICAL_SIM = 0.85
# 开场范例里「体验邀请 / 人设钩子」信号词：用于在开场原声里优先选差异化范例、压低纯问候。
_OPEN_HOOK_WORDS = (
    "试", "体验", "上手", "感受", "拿", "摸", "对比", "演示", "画", "写", "记",
    "看", "屏", "笔", "键盘", "续航", "分屏", "投屏", "出差", "会议", "课",
)


def _group_of_cid(cid: str) -> str:
    head = (cid or "").split("_", 1)[0]
    return head if head in _GROUP_CN else "intro"


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _non_accuracy_avg(scores: dict[str, Any]) -> float:
    """剔除「参数真实性」维度后的均分（解耦手册一致性）。"""
    vals = [_to_float(v) for k, v in (scores or {}).items()
            if k != EXCELLENCE_EXCLUDE_DIM]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


# ============================================================
# LLM 逐条建议（批量分片）
# ============================================================

# 各板块的改写标准（注入到 prompt，针对性约束 revised_text 的结构与重点）
_GROUP_REWRITE_GUIDE = {
    # playbook_v1
    "open": "【开场破冰】注意：本条目『原文』是该人设的**客户识别线索**（顾客自己会说的话，用来判断他属于哪类人设），"
            "不是现成话术，**不要去改写这句客户的话**。你的任务是：基于该识别线索 + 给到的『通用开场白（手册原话术）』，"
            "写出销冠面对这类顾客时的**开场话术**——1–2 句短钩子，第一句先共情/呼应他这类人最在意的场景，"
            "第二句给一个能立刻上手的轻量体验邀请（如“要不您先拿笔在类纸屏上写两笔？”）；不堆演示步骤、不报价、不罗列参数。"
            "revised_text 只写这段开场话术本身。",
    "say": "【核心卖点】结构=卖点是什么 → 对客户的具体收益 → 一个现场演示动作。保留原文已有的关键参数，"
           "把销冠验证有效的演示融进来，让导购能照着说、照着演。",
    "compete": "【竞品应对】保留“客户问 / 应答”多轮结构，客户问句逐字保留不改。每条应答=先认可竞品一句 → "
               "转向我方差异化 → 给可验证对比 → 邀请现场体验/对比；不诋毁竞品。",
    "respond": "【FAQ】保留 Q/A 结构，问句逐字保留不改。答案=直接回答顾虑 → 一句话打消焦虑 → 给一个下一步动作。",
    # 旧 135910
    "intro": "【一句话定位】一句话说清产品定位与核心价值，凝练有力。",
    "sell": "【核心卖点】卖点 → 客户收益 → 演示动作。",
    "comp": "【竞品对比】认可 → 差异化 → 可验证对比 → 邀请体验。",
    "param": "【核心参数】参数原值 + 一句生活化类比 + 口播范本。",
    "faq": "【FAQ】直接回答 → 打消焦虑 → 下一步动作。",
    "demo": "【现场演示】演示步骤 + 口播 + 触发时机 + 演示后过渡成交句。",
}


def _group_guide(grp: str) -> str:
    return _GROUP_REWRITE_GUIDE.get(grp, "")


# revised_text 的统一质量标准（system 提示 + 自检 + 后置质量门都引用同一套）
_QUALITY_BAR = (
    "revised_text 的质量目标（必须全部达到，这是一份要直接放回产品手册的成品话术）：\n"
    "Q1 必须比原文更强：更具体、更有场景感、更易照着说；绝不能比原文更弱、更空泛、更短到丢信息。\n"
    "Q2 必须保留原文最有价值的内容（核心卖点、人设场景钩子、关键参数），不能借“重写”把它删掉。\n"
    "Q3 必须真正重组，不能是“原文整段 + 拼一句”，也不能与原文几乎一致。\n"
    "Q4 必须把 suggestion 里的每个要点都落实到 revised_text。\n"
    "Q5 只能用手册原文已有的事实（参数/认证/机型/价格口径），禁止编造、禁止改对比方向、"
    "禁止写入单个客户的个案细节（如“你的 50MB Excel”“312.70 zł”）。\n"
    "Q6 正文必须与原文主体语言一致：原文正文是英文就用英文、是中文就用中文，绝不能擅自改成另一种语言"
    "（手册里的“演示：/客户：/应答：”等标注不代表正文语言）；完整成句不截断；竞品/FAQ 保留问答结构且客户问句逐字不改。"
)

_LLM_SYSTEM = (
    "你是华为线下零售《销售话术手册》的迭代顾问。针对手册里的某个条目，先读完销冠在真实对话里"
    "对它的全部演绎记录，再产出：① 真实诊断的评估；② 具体可执行的建议；③ 可直接写进手册的高质量改写。"
    "即使表现已经很好，也要给出能让它更强的增强点。\n\n"
    + _QUALITY_BAR + "\n\n"
    "其它硬性规则：\n"
    "· assessment / suggestion 用中文，且不得引用任何内部编号或 id。\n"
    "· 若该条目本批 0 次被引用（死条目），没有真实演绎可依据，revised_text 直接返回与原文一致、不得臆造，"
    "只在 suggestion 里说明为何没被触发、如何激活。\n"
    "· 输出前对每条 revised_text 按 Q1–Q6 逐项自检，不达标就先重写再输出。\n"
    "只输出 JSON。"
)


# 高/低分演绎分档阈值（非参数真实性维度均分，0~10）。
_WIN_SCORE = 7.0
_FAIL_SCORE = 5.5
_SAMPLE_CAP = 6  # 每档最多喂给 LLM 的样本数，控体量


def _split_samples(samples: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """把命中演绎分成「高分（有效打法）/ 低分（薄弱点）」两档喂给 LLM（修复④）。

    让改写真正吃到 94 人设跑出来的信号：高分里验证有效的打法固化进改写，
    低分暴露的问题在改写里针对性补强。没有明显高/低分时退回 TOP/BOTTOM 几条保证有上下文。
    """
    if not samples:
        return [], []
    wins = [s for s in samples if _to_float(s.get("score")) >= _WIN_SCORE][:_SAMPLE_CAP]
    fails = [s for s in sorted(samples, key=lambda s: _to_float(s.get("score")))
             if _to_float(s.get("score")) < _FAIL_SCORE][:_SAMPLE_CAP]
    if not wins:
        wins = sorted(samples, key=lambda s: -_to_float(s.get("score")))[:min(3, len(samples))]
    return wins, fails


def _build_llm_prompt(chunk: list[dict[str, Any]]) -> str:
    blocks = []
    for it in chunk:
        cov = it["coverage"]
        if cov["covered"]:
            cov_line = (
                f"命中 {cov['hits']} 次 / {cov['sessions']} 场 · "
                f"非参数真实性维度均分 {cov['avg_quality']:.1f}/10"
            )
        else:
            cov_line = "本批 0 次被销冠引用（疑似死条目）"
        wins, fails = _split_samples(it["_samples"])
        win_block = "\n".join(f"    · {s['content'][:160]}" for s in wins) or "    （无）"
        fail_block = "\n".join(f"    · {s['content'][:160]}" for s in fails) or "    （无）"
        lang = _lang_cn(it.get("handbook_text") or "")
        is_open = it["group"] == "open"
        # 开场条目：原文是「客户识别线索」，额外给出手册通用开场白作为话术参照基线（修复②）。
        if is_open:
            ref = (it.get("_open_ref") or "").strip()
            orig_label = "客户识别线索（顾客的话，勿改写）"
            ref_line = (
                f"  通用开场白（手册原话术，作为改写参照）：{ref[:800]}\n" if ref
                else "  通用开场白：（手册未提供，按识别线索自拟开场话术）\n"
            )
        else:
            orig_label = "条目原文"
            ref_line = ""
        blocks.append(
            f"- id={it['_pid']}\n"
            f"  条目类别：{_GROUP_CN.get(it['group'], it['group'])}\n"
            f"  本类改写标准：{_group_guide(it['group'])}\n"
            f"  条目标签：{it['label']}\n"
            f"  正文语言：{lang}（revised_text 必须用{lang}输出，绝不能改成其它语言）\n"
            f"  {orig_label}：{(it['handbook_text'] or '（缺正文）')[:2000]}\n"
            f"{ref_line}"
            f"  覆盖情况：{cov_line}\n"
            f"  高分演绎（说服力高、已被验证有效，请把其中的有效打法固化进改写）：\n{win_block}\n"
            f"  低分/失败演绎（暴露了薄弱点，请在改写里针对性补强，但不得照搬其中的新事实）：\n{fail_block}"
        )
    body = "\n".join(blocks)
    return (
        "## 待评估手册条目\n"
        f"{body}\n\n"
        "## 输出格式（**只输出 JSON 对象**，不要 markdown）\n"
        "{\n"
        '  "items": [\n'
        '    {"id": 0, "status": "保持/强化/修正", '
        '"assessment": "≤80字：综合全部演绎记录看，这条目前演绎得如何、问题在哪", '
        '"suggestion": "≤150字：下一版具体怎么改，可直接执行", '
        '"revised_text": "按本类改写标准 + Q1–Q6，把原文重写成可直接回写手册的成品话术"}\n'
        "  ]\n"
        "}\n\n"
        "规则：status 三选一——『保持』表现很好（suggestion 仍要给增强点）/『强化』已被使用但"
        "说服力一般或需补充内容 /『修正』演绎质量偏低需纠正；命中为 0 的死条目用『修正』，"
        "且 revised_text 必须原样返回条目原文（死条目不臆造）；每个 id 都要返回；"
        "assessment/suggestion 必须基于该条目的全部真实演绎与手册原文得出；"
        "改写时务必：把『高分演绎』里验证有效的表达/打法固化进 revised_text，"
        "并针对『低分/失败演绎』暴露的薄弱点做补强；"
        "revised_text 必须遵守上面的『本类改写标准』与质量目标 Q1–Q6，并把 suggestion 逐点落实。"
    )


def _llm_suggest(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for start in range(0, len(items), _LLM_CHUNK):
        chunk = items[start:start + _LLM_CHUNK]
        try:
            with with_llm_override(aux_llm_override(thinking_mode="disabled")):
                raw = call_llm_json(_LLM_SYSTEM, _build_llm_prompt(chunk), temperature=0.4)
        except (LLMCallError, LLMJsonParseError) as exc:
            logger.warning("[revisor] LLM 分片失败：%s", exc)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("[revisor] LLM 未知异常：%s", exc)
            continue
        rows = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            try:
                pid = int(r.get("id"))
            except (TypeError, ValueError):
                continue
            out[pid] = {
                "status": _normalize_status(str(r.get("status") or "")),
                "assessment": str(r.get("assessment") or "").strip()[:300],
                "suggestion": str(r.get("suggestion") or "").strip()[:600],
                # 放开到足以容纳竞品/FAQ 的完整改写（含多轮 Q/A），避免断句
                "revised_text": str(r.get("revised_text") or "").strip()[:2200],
            }
    return out


# ============================================================
# 回退（无 LLM）
# ============================================================

def _fallback(item: dict[str, Any]) -> dict[str, str]:
    cov = item["coverage"]
    label = item["label"]
    grp = item["group"]
    original = (item.get("handbook_text") or "").strip()
    if not cov["covered"]:
        return {
            "status": "修正",
            "assessment": "本批 0 次被销冠引用，等同死条目。",
            "suggestion": _add_template(grp, label),
            "revised_text": original,
        }
    q = cov["avg_quality"]
    if q < 5:
        status, head = "修正", "演绎质量偏低，口径/具体度不足。"
    elif q < 6.5:
        status, head = "强化", "已被使用但说服力一般。"
    else:
        status, head = "保持", "演绎良好，可作范本沉淀。"
    return {
        "status": status,
        "assessment": f"{head}（均分 {q:.1f}/10，命中 {cov['hits']} 次）",
        "suggestion": _improve_template(grp, label),
        "revised_text": original,
    }


def _add_template(grp: str, label: str) -> str:
    base = {
        "sell": "补：① 30 字黄金一句话；② 客户痛点引入场景；③ 关联演示动作；④ 一句 closing-push。",
        "comp": "补：① 可验证数字对比；② 不诋毁竞品的合规话术；③ 客户提竞品时 3 句快速回应。",
        "param": "补：① 参数原值+来源；② 一句生活化类比；③ 销冠口播范本。",
        "faq": "补：① 问题 3 个变体；② 标准答；③ 一句反问引导；④ 一句 closing-push。",
        "demo": "补：① 演示完整 step；② 销冠口播；③ 触发时机；④ 演示后过渡成交句。",
        "intro": "补：① 一句话定位的销冠口播；② 适用客户画像；③ 接续话术。",
    }
    return f"为「{label}」{base.get(grp, base['intro'])}"


def _improve_template(grp: str, label: str) -> str:
    return (
        f"对「{label}」下一版增强：① 用可验证具体数字替换泛词；"
        f"② 给 3 个口播变体（破冰/紧迫/异议）；③ 列禁忌说法；④ 配 1 个客户场景演绎。"
    )


# ============================================================
# 事实白名单 —— 改写后校验（whitelist + 后置告警）
# ============================================================

# 认证 / 机型 / 充电功率等"易被对话污染"的锚点：出现在改写里但手册原文没有 → 告警
_CERT_ANCHORS = [
    "tüv", "tuv", "rheinland", "full care", "five-star", "five star",
    "eye-comfort", "eye comfort", "low visual fatigue", "iso ",
]
_MODEL_ANCHORS = [
    "12x", "m-pencil pro", "matepad pro", "matepad 11", "matepad se",
]
# 数字参数（功率/容量/刷新率/延迟/键程等）
_SPEC_RE = _re.compile(
    r"\d+(?:\.\d+)?\s?(?:w|mah|hz|ms|mm|nits|wh|gb|tb)\b", _re.IGNORECASE
)
# 具体金额（任何币种）—— 通用手册不应写入个案价格
_MONEY_RE = _re.compile(
    r"(?:[$£€¥]\s?\d[\d,.]*)|(?:\d[\d,.]*\s?(?:zł|vnd|triệu|đồng|soles|usd|eur|gbp|rmb|元|韩元))",
    _re.IGNORECASE,
)


def _norm(text: str) -> str:
    return _re.sub(r"\s+", " ", (text or "").lower())


def _similarity(a: str, b: str) -> float:
    """改写与原文的字符相似度（0~1）。去掉所有空白再比，避免标点/换行干扰判定。"""
    na = _re.sub(r"\s+", "", a or "")
    nb = _re.sub(r"\s+", "", b or "")
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _dedup_similar(rows: list[dict], *, key: str = "content", thr: float = 0.8) -> list[dict]:
    """按文本相似度去重近似条目（保留先到者）。用于开场范例去掉重复问候。"""
    kept: list[dict] = []
    for r in rows:
        txt = (r.get(key) or "").strip()
        if any(_similarity(txt, (k.get(key) or "").strip()) >= thr for k in kept):
            continue
        kept.append(r)
    return kept


def _handbook_corpus(struct: dict) -> str:
    """全手册可用事实语料（所有条目原文 + 标签）的归一化串，用作'允许事实'的判定底。"""
    parts: list[str] = []
    for c in _iter_categories(struct or {}):
        parts.append(c.get("text") or "")
        parts.append(c.get("label") or "")
    return _norm(" ".join(parts))


def _fact_warnings(revised: str, corpus: str) -> list[str]:
    """检查改写文本里是否出现手册语料中没有的事实（认证/机型/数字/金额）。

    只告警、不改写——交给人工判断（可能是真该补进手册的好料，也可能是幻觉）。
    """
    if not revised:
        return []
    rev = _norm(revised)
    warns: list[str] = []

    for anchor in _CERT_ANCHORS:
        if anchor in rev and anchor not in corpus:
            warns.append(f"认证/标准“{anchor.strip()}”手册原文未出现")
    for anchor in _MODEL_ANCHORS:
        if anchor in rev and anchor not in corpus:
            warns.append(f"机型/配件“{anchor.strip()}”手册原文未出现")
    for m in _SPEC_RE.findall(revised):
        tok = _norm(m)
        if tok not in corpus:
            warns.append(f"参数“{m.strip()}”手册原文未出现")
    if _MONEY_RE.search(revised):
        warns.append("出现具体金额（个案数据，不应写进通用手册）")

    # 去重、限量
    seen: set[str] = set()
    uniq: list[str] = []
    for w in warns:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq[:6]


# ============================================================
# 改写质量门 + 二次精修（self-check / rewrite）
# ============================================================

def _dominant_lang(text: str) -> str:
    """按 CJK 汉字 vs 拉丁字母占比判定正文主体语言。

    手册原文常含“演示：/客户：/应答：”等中文标注，单看是否有汉字会误判，
    故用占比判定主体语言。返回 'cjk' | 'en' | 'other'。
    """
    cjk = len(_re.findall(r"[\u4e00-\u9fff]", text or ""))
    lat = len(_re.findall(r"[A-Za-z]", text or ""))
    if cjk == 0 and lat == 0:
        return "other"
    return "cjk" if cjk > lat else "en"


def _lang_cn(text: str) -> str:
    return {"cjk": "中文", "en": "英文"}.get(_dominant_lang(text), "原文语言")


def _quality_issues(
    original: str, revised: str, corpus: str, *, grp: str = ""
) -> list[str]:
    """检测覆盖类条目改写的硬伤（用于触发二次重写）。死条目不走这里。"""
    issues: list[str] = []
    original = (original or "").strip()
    revised = (revised or "").strip()
    if not revised:
        return ["改写为空"]
    no, nr = _norm(original), _norm(revised)
    # 原文整段被照搬进改写（“原文 + 拼一句”/没真正重写）
    if no and len(no) > 40 and no in nr:
        issues.append("照搬原文整段，未真正重写")
    if nr == no:
        issues.append("与原文几乎完全相同")
    # 改动量阈值：相似度过高视为「伪改写」（只换一两个词 / 原文后拼一句问候）。
    # open 板块原文是客户识别线索而非话术，与开场话术天然低相似，故跳过此判定。
    elif grp != "open" and _similarity(original, revised) >= _NEAR_IDENTICAL_SIM:
        issues.append("改动量过小，与原文高度相似（未实质重写）")
    # 正文主体语言与原文不一致（如原文英文、改写串成中文）
    if original and (_dominant_lang(original) != _dominant_lang(revised)):
        issues.append(f"正文语言与原文不一致（应保持{_lang_cn(original)}）")
    # 引入手册外事实
    if _fact_warnings(revised, corpus):
        issues.append("引入手册外事实")
    return issues


_REWRITE_SYSTEM = (
    "你在对一份销售话术手册做二次精修。下面给你：条目原文、上一版改写、它存在的问题、"
    "本类改写标准，以及销冠真实演绎。请重写出更好的 revised_text，把所有问题修掉。\n\n"
    + _QUALITY_BAR + "\n\n"
    "只输出 JSON 对象：{\"revised_text\": \"...\"}。"
)


def _build_rewrite_prompt(item: dict[str, Any], prior: str, issues: list[str]) -> str:
    wins, fails = _split_samples(item.get("_samples", []))
    win_block = "\n".join(f"    · {s['content'][:160]}" for s in wins) or "    （无）"
    fail_block = "\n".join(f"    · {s['content'][:160]}" for s in fails) or "    （无）"
    lang = _lang_cn(item.get("handbook_text") or "")
    is_open = item.get("group") == "open"
    if is_open:
        ref = (item.get("_open_ref") or "").strip()
        orig_label = "客户识别线索（顾客的话，勿改写）"
        ref_line = f"通用开场白（手册原话术，作为参照）：{ref[:800]}\n" if ref else ""
    else:
        orig_label = "条目原文"
        ref_line = ""
    return (
        f"条目类别：{_GROUP_CN.get(item['group'], item['group'])}\n"
        f"本类改写标准：{_group_guide(item['group'])}\n"
        f"条目标签：{item['label']}\n"
        f"正文语言：{lang}（revised_text 必须用{lang}输出，绝不能改成其它语言）\n"
        f"{orig_label}：{(item.get('handbook_text') or '')[:2000]}\n"
        f"{ref_line}"
        f"上一版改写：{prior[:2000]}\n"
        f"上一版的问题（必须全部修掉）：{('；'.join(issues)) or '（质量不足，需更强）'}\n"
        f"高分演绎（固化其有效打法）：\n{win_block}\n"
        f"低分/失败演绎（针对性补强，不得照搬新事实）：\n{fail_block}\n\n"
        f"请用{lang}输出修正后的成品话术。"
    )


def _rewrite_one(item: dict[str, Any], prior: str, issues: list[str]) -> str:
    """对一条改写做单条二次精修；失败则返回空串（保留上一版）。"""
    try:
        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(
                _REWRITE_SYSTEM, _build_rewrite_prompt(item, prior, issues),
                temperature=0.5,
            )
    except (LLMCallError, LLMJsonParseError) as exc:
        logger.warning("[revisor] 二次精修失败 label=%s：%s", item.get("label"), exc)
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("[revisor] 二次精修未知异常 label=%s：%s", item.get("label"), exc)
        return ""
    if isinstance(raw, dict):
        return str(raw.get("revised_text") or "").strip()[:2200]
    return ""


def _quality_flag(
    *,
    covered: bool,
    fact_warnings: list[str],
    issues: list[str],
    near_identical: bool = False,
) -> str:
    """每条改写的可交付标记：
    - kept_original=死条目仅保留原文；
    - review=有事实越界/其它硬伤，需人工确认；
    - minor=二次精修后改动量仍过小（实质未重写），价值有限、建议人工再强化；
    - ok=实质改写、可直接采纳。
    """
    if not covered:
        return "kept_original"
    if fact_warnings:
        return "review"
    # 「改动量过小」单独归为 minor；其它硬伤才算 review。
    other_issues = [i for i in issues if "改动量过小" not in i and "几乎完全相同" not in i]
    if other_issues:
        return "review"
    if near_identical:
        return "minor"
    return "ok"


# ============================================================
# 编排入口
# ============================================================

def build_handbook_revisions(
    *,
    struct: dict,
    label_map: dict[str, str],
    classifications: list[dict[str, Any]],
    turn_index: dict[tuple[str, int], dict],
    prev_customer: dict[tuple[str, int], str],
    sess_to_persona: dict[str, Any],
    persona_rows: dict[Any, dict],
    use_llm: bool = True,
) -> list[dict[str, Any]]:
    """按 31 条结构顺序产出逐条迭代建议（每条含 TOP3 原声）。"""
    cats = _iter_categories(struct)
    if not cats:
        return []

    # 开场板块：手册里真正的「销冠开场话术」是 open.opener（通用开场白），而逐条 open_* 的
    # 原文只是各人设的「客户识别线索」。把通用开场白 + 时机提示抽出来，作为 open 条目改写的
    # 参照基线喂给 LLM（修复②：区分客户识别线索 vs 销冠开场话术）。
    _open_blk = (struct or {}).get("open") or {}
    _open_opener_ref = " ".join(
        s for s in [
            (_open_blk.get("opener") or "").strip(),
            (_open_blk.get("timing_cue") or _open_blk.get("timing") or "").strip(),
        ] if s
    ).strip()

    # 命中每个 cid 的 turn（合并同 turn 多分类，取非 accuracy 维度均分）
    by_cid: dict[str, list[dict]] = defaultdict(list)
    for c in classifications:
        by_cid[c.get("category_id")].append(c)

    items: list[dict[str, Any]] = []
    for cat in cats:
        cid = cat["id"]
        grp = cat.get("group") or _group_of_cid(cid)
        hits = by_cid.get(cid) or []
        sessions = len({h["session_id"] for h in hits})
        # 每个命中 turn 的代表分 + 内容
        turn_scored: list[dict] = []
        seen_keys: set[tuple[str, int]] = set()
        for h in hits:
            key = (h["session_id"], int(h["turn_idx"]))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            content = ((turn_index.get(key) or {}).get("content") or "").strip()
            if not content:
                continue
            pid = sess_to_persona.get(h["session_id"])
            pname = (persona_rows.get(pid) or {}).get("name") if pid is not None else None
            turn_scored.append({
                "session_id": h["session_id"],
                "turn_idx": int(h["turn_idx"]),
                "content": content,
                "customer_question": (prev_customer.get(key, "") or "").strip(),
                "persona_name": pname or (f"#{pid}" if pid is not None else "—"),
                "score": _non_accuracy_avg(h.get("scores") or {}),
                "confidence": _to_float(h.get("confidence")),
            })
        turn_scored.sort(key=lambda r: -r["score"])
        avg_q = round(sum(t["score"] for t in turn_scored) / len(turn_scored), 2) if turn_scored else 0.0
        # 展示用原声：先用分类置信度做相关性闸门（剔除文不对题的弱归属），
        # 再按表达分取 TOP3；闸门后为空则退回置信度最高的一条，保证不空。
        coherent = [t for t in turn_scored if t["confidence"] >= _QUOTE_MIN_CONF]
        if not coherent and turn_scored:
            coherent = sorted(turn_scored, key=lambda r: -r["confidence"])[:1]
        # 开场破冰：再用"对话位置"闸门——开场范例应是对话起手，优先取 idx≤阈值的早段轮；
        # 早段无命中时退回全集。修复③：先去重近似问候，再「差异化优先」排序——
        # 含体验邀请/人设钩子词的范例排前，纯问候排后，避免 TOP 全是“您好欢迎光临”。
        if grp == "open":
            early = [t for t in coherent if int(t.get("turn_idx", 99)) <= _OPEN_MAX_TURN_IDX]
            pool = _dedup_similar(early or coherent)

            def _open_rank(r: dict) -> tuple:
                content = r.get("content") or ""
                has_hook = any(w in content for w in _OPEN_HOOK_WORDS)
                # 钩子优先(0) > 纯问候(1)；同档内最早轮优先、长一点(信息多)优先
                return (0 if has_hook else 1, int(r.get("turn_idx", 99)), -len(content))

            quote_src = sorted(pool, key=_open_rank)[:_TOP_QUOTES]
        else:
            quote_src = sorted(coherent, key=lambda r: -r["score"])[:_TOP_QUOTES]
        # 开场不打分（修复③）：开场是“起手破冰”，对它套用说服力评分没有意义，score 置空，
        # 前端/导出端据此隐藏分数，只展示人设 + 范例本身。
        top_quotes = [
            {"content": t["content"][:200], "persona_name": t["persona_name"],
             "customer_question": t["customer_question"][:200],
             "score": (None if grp == "open" else t["score"]),
             "session_id": t["session_id"], "turn_idx": t["turn_idx"]}
            for t in quote_src
        ]
        items.append({
            "category_id": cid,
            "group": grp,
            "label": cat["label"],
            "handbook_text": cat["text"],
            "coverage": {
                "covered": len(turn_scored) > 0,
                "hits": len(turn_scored),
                "sessions": sessions,
                "avg_quality": avg_q,
            },
            "top_quotes": top_quotes,
            # 喂给 LLM 的是本条目命中的**全部**真实演绎（不再只取 TOP-N 样本），
            # 评估/建议/改写后均基于全部记录得出。
            "_samples": turn_scored,
            # open 条目专用：通用开场白原话术 + 时机提示，作为改写参照基线（修复②）。
            "_open_ref": _open_opener_ref if grp == "open" else "",
        })

    # LLM 逐条建议（含对原文这一句的「修改后」改写）
    for i, it in enumerate(items):
        it["_pid"] = i
    llm_out: dict[int, dict[str, Any]] = {}
    if use_llm:
        llm_out = _llm_suggest(items)

    corpus = _handbook_corpus(struct)
    out: list[dict[str, Any]] = []
    for it in items:
        pid = it.pop("_pid")
        samples = it.pop("_samples", None) or []
        llm = llm_out.get(pid)
        fb = _fallback(it)
        original = (it.get("handbook_text") or "").strip()
        it["status"] = (llm or {}).get("status") or fb["status"]
        it["assessment"] = (llm or {}).get("assessment") or fb["assessment"]
        it["suggestion"] = (llm or {}).get("suggestion") or fb["suggestion"]
        revised = (llm or {}).get("revised_text") or fb["revised_text"]
        covered = bool(it["coverage"]["covered"])

        grp = it["group"]
        issues: list[str] = []
        if not covered:
            # 死条目（本批 0 命中）不臆造：改写一律回退到原文
            revised = original
        elif use_llm and llm:
            # 质量门：命中条目若改写有硬伤（照搬/弱化/改动量过小/语言/事实越界）→ 单条二次精修
            issues = _quality_issues(original, revised, corpus, grp=grp)
            if issues:
                it["_samples"] = samples  # 供精修 prompt 取演绎
                better = _rewrite_one(it, revised, issues)
                it.pop("_samples", None)
                if better:
                    new_issues = _quality_issues(original, better, corpus, grp=grp)
                    # 仅当精修确实变好（硬伤更少）才采纳
                    if len(new_issues) < len(issues):
                        revised, issues = better, new_issues

        it["revised_text"] = revised
        # 事实白名单后置校验：改写引入手册没有的认证/机型/参数/金额 → 告警（不强改）
        it["fact_warnings"] = _fact_warnings(revised, corpus) if covered else []
        # 改动量复核：精修后仍与原文高度相似 → 标记为 minor（实质未重写、价值有限）。
        near_identical = bool(
            covered and grp != "open"
            and _similarity(original, revised) >= _NEAR_IDENTICAL_SIM
        )
        # 可交付标记：ok / review / minor / kept_original
        it["quality_flag"] = _quality_flag(
            covered=covered,
            fact_warnings=it["fact_warnings"],
            issues=issues,
            near_identical=near_identical,
        )
        it.pop("_open_ref", None)  # 内部参照字段，不外泄到报告 JSON
        out.append(it)
    return out
