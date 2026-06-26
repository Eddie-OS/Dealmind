"""A2 · Handbook 多标签分类器

输入：单条销冠 turn 的 content + 完整 Handbook 结构
输出：[ { "category_id": "sell_2", "confidence": 0.86 }, ... ]
      （多标签 —— 一条 turn 可对应多 category）

策略（vector pre-screen + LLM 确认）：
  1) 用关键词字典做 cheap 候选筛选（先打分前 TopK）
  2) 把候选连同 turn 一起喂给 LLM，做多标签 + 置信度判定
  3) confidence < 阈值（默认 0.4）的候选丢弃

为什么不用向量库：
  Handbook 总条目 = 1+3+3+5+9+10 = 31 个，规模小到不需要 vector store；
  关键词字典 + LLM 已足够精准且成本低。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.llm import LLMCallError, LLMJsonParseError, call_llm_json, with_llm_override
from src.perf_config import aux_llm_override


logger = logging.getLogger(__name__)


# ============================================================
# 候选生成（不调 LLM，纯字符串匹配 + 词频）
# ============================================================

_PREFIX_MAP = {
    "selling_points": "sell",
    "competitor_points": "comp",
    "core_params": "param",
    "faq": "faq",
    "demo_actions": "demo",
}

# playbook_v1 的 4 章顺序（与渲染层共用）
PLAYBOOK_GROUP_ORDER = ["open", "say", "compete", "respond"]


def _iter_categories(struct: dict) -> list[dict[str, Any]]:
    """把 Handbook 结构铺平成统一的 [{id, group, label, text, persona?}, ...]。

    - 旧 1/3/3/5/9/10：group ∈ {intro, sell, comp, param, faq, demo}
    - playbook_v1：    group ∈ {open, say, compete, respond}，say/open 带 persona
    group 一律用**短名**，与迭代建议/报告渲染层的分组键保持一致。
    """
    if (struct or {}).get("doc_type") == "playbook_v1":
        return _iter_playbook_categories(struct)

    out: list[dict[str, Any]] = []
    intro = struct.get("intro_1") or {}
    if isinstance(intro, dict) and (intro.get("text") or intro.get("label")):
        out.append({
            "id": "intro_1",
            "group": "intro",
            "label": intro.get("label") or "一句话定位",
            "text": intro.get("text") or "",
        })
    for key, prefix in _PREFIX_MAP.items():
        for i, it in enumerate(struct.get(key) or [], 1):
            cid = it.get("id") or f"{prefix}_{i}"
            if key == "faq":
                lab = it.get("label") or f"FAQ {i}"
                text = f"Q: {it.get('q', '')}\nA: {it.get('a', '')}"
            elif key == "competitor_points":
                lab = it.get("label") or f"竞品 {i}"
                vs = it.get("vs") or ""
                text = (
                    (f"（vs {vs}）" if vs else "")
                    + (it.get("text") or "")
                )
            else:
                lab = it.get("label") or f"{prefix} {i}"
                text = it.get("text") or ""
            out.append({
                "id": cid, "group": prefix,
                "label": lab, "text": text,
            })
    return out


def _iter_playbook_categories(struct: dict) -> list[dict[str, Any]]:
    """把 playbook_v1 结构铺平。say/open 携带 persona（A/B/C/D）。"""
    out: list[dict[str, Any]] = []

    open_blk = struct.get("open") or {}
    for po in open_blk.get("persona_openers") or []:
        if not isinstance(po, dict):
            continue
        p = (po.get("persona") or "?").strip()
        plabel = (po.get("persona_label") or "").strip()
        txt = (po.get("text") or "").strip()
        if not txt:
            continue
        out.append({
            "id": f"open_{p}", "group": "open",
            "label": f"开场·{p}·{plabel}".rstrip("·"),
            "text": txt, "persona": p, "persona_label": plabel,
        })

    for blk in struct.get("say") or []:
        if not isinstance(blk, dict):
            continue
        p = (blk.get("persona") or "?").strip()
        plabel = (blk.get("persona_label") or "").strip()
        for n, pt in enumerate(blk.get("points") or [], 1):
            if not isinstance(pt, dict):
                continue
            cid = pt.get("id") or f"say_{p}_{n}"
            label = (pt.get("label") or "").strip()
            text = (pt.get("text") or "").strip()
            demo = (pt.get("demo") or "").strip()
            if demo:
                text = f"{text}\n演示：{demo}" if text else f"演示：{demo}"
            out.append({
                "id": cid, "group": "say",
                "label": f"{p}·{label}", "text": text,
                "persona": p, "persona_label": plabel,
            })

    for n, blk in enumerate(struct.get("compete") or [], 1):
        if not isinstance(blk, dict):
            continue
        base = blk.get("id") or f"comp_{n}"
        vs = (blk.get("vs") or "").strip()
        pairs = [pr for pr in (blk.get("pairs") or []) if isinstance(pr, dict)]
        if not pairs:
            # 没有问答对：退回整块一条，避免丢条目
            out.append({
                "id": base, "group": "compete",
                "label": f"竞品·{vs}" if vs else f"竞品 {n}",
                "text": "", "persona": "", "persona_label": "",
            })
            continue
        # 每个「客户问 / 应答」对单独成条 → 可逐条命中、逐条打分、逐条出建议
        # （与 FAQ 一致的粒度；竞品 vs 名带进 label，客户问句逐字保留作辨识）。
        for m, pr in enumerate(pairs, 1):
            cust = (pr.get("customer") or "").strip()
            resp = (pr.get("response") or "").strip()
            short = cust.strip().strip('"“”').strip()[:24]
            if vs and short:
                label = f"竞品·{vs}·{short}"
            elif vs:
                label = f"竞品·{vs}·应对{m}"
            else:
                label = f"竞品 {n}·应对{m}"
            out.append({
                "id": f"{base}_{m}", "group": "compete",
                "label": label,
                "text": f"客户：{cust}\n应答：{resp}",
                "persona": "", "persona_label": "",
            })

    for n, q in enumerate(struct.get("respond") or [], 1):
        if not isinstance(q, dict):
            continue
        cid = q.get("id") or f"faq_{n}"
        qq = (q.get("q") or "").strip()
        aa = (q.get("a") or "").strip()
        out.append({
            "id": cid, "group": "respond",
            "label": f"FAQ·{qq[:24]}" if qq else f"FAQ {n}",
            "text": f"Q: {qq}\nA: {aa}",
            "persona": "", "persona_label": "",
        })
    return out


def _keyword_score(content: str, label: str, text: str) -> float:
    """简单关键词命中得分：0~1。

    把 label/text 切成 3-12 字片段，落到 content 里命中即加分。
    """
    if not content:
        return 0.0
    combined = f"{label} {text}"
    frags = [
        f.strip()
        for f in re.split(
            r"[，。；：、,;:!\?！？\(\)（）\[\]\n\r\t·•—\-—\|]+", combined
        )
        if 3 <= len(f.strip()) <= 16
    ]
    if not frags:
        return 0.0
    hits = sum(1 for f in frags if f in content)
    return min(1.0, hits / max(3, len(frags) * 0.4))


# 演示信号：演示句的关键词预筛得分通常≈0（demo 条目写的是店内动作，
# 与销冠口语不字面匹配），导致 demo_* 被挤出候选、覆盖率恒为 0。
# 这里用 content 本身的两类信号识别"这是一次现场演示"：
#   ① 含动作词的全角（）舞台指示（如"（拿起样机演示）"）
#   ② 演示动词（拿样机/上手/体验/试两笔/现场打开/给您看/演示…）
_DEMO_VERBS = (
    "拿样机", "拿真机", "拿起样机", "拿出样机", "上手", "体验", "试两笔", "试一试",
    "试两下", "试一下", "现场打开", "现场演示", "放段", "放一段", "给您看", "给您演示",
    "您看这", "您感受", "握笔", "画两笔", "画两下", "演示", "操作给您", "我打开",
)
_DEMO_PAREN_RE = re.compile(r"[（(][^（）()]{1,40}[）)]")
_DEMO_PAREN_VERBS = ("演示", "拿", "操作", "打开", "展示", "试", "体验", "握", "画", "放")


def has_demo_signal(content: str) -> bool:
    """判断这条销冠发言是否包含现场演示动作（content 信号，历史/未来数据通用）。"""
    if not content:
        return False
    if any(v in content for v in _DEMO_VERBS):
        return True
    for m in _DEMO_PAREN_RE.finditer(content):
        inner = m.group(0)
        if any(v in inner for v in _DEMO_PAREN_VERBS):
            return True
    return False


def shortlist_candidates(
    content: str,
    struct: dict,
    *,
    top_k: int = 12,
    keep_intro: bool = True,
    force_demo: bool = False,
) -> list[dict[str, Any]]:
    """返回排序后的候选 category（不含 LLM 调用）。

    force_demo=True 时，把全部 demo_* 条目保底并入候选，让 LLM 能把
    现场演示归到正确的 demo_x（解决 demo 关键词预筛恒被挤出的根因）。
    """
    all_cats = _iter_categories(struct)
    scored: list[tuple[float, dict]] = []
    for c in all_cats:
        score = _keyword_score(content, c["label"], c["text"])
        scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    has_intro = False
    for s, c in scored:
        if len(out) >= top_k and not (keep_intro and not has_intro and c["id"] == "intro_1"):
            continue
        out.append({**c, "kw_score": round(s, 3)})
        if c["id"] == "intro_1":
            has_intro = True
    if force_demo:
        present = {c["id"] for c in out}
        for c in all_cats:
            if c["group"] == "demo" and c["id"] not in present:
                out.append({**c, "kw_score": 0.0})
    return out


# ============================================================
# LLM 多标签确认
# ============================================================

_SYSTEM_PROMPT = (
    "你是产品话术分类专家。给定一条销冠发言和若干候选『手册条目』，"
    "判断这条发言**实质性地讲到了**哪些条目（可多选，也可一个都不选）。"
    "判定口径：销冠是否**主动引用、复述或说服客户去看/试**该条目的内容；"
    "仅出现关键词不算（如客户先说出该词，销冠只是回应）。"
    "**只输出 JSON**，结构见用户提示。"
)


def _user_prompt(content: str, candidates: list[dict[str, Any]]) -> str:
    cand_lines = "\n".join(
        f"- id={c['id']}  group={c['group']}  label={c['label']}  "
        f"text=<<{(c['text'] or '').strip()[:200]}>>"
        for c in candidates
    )
    return (
        "## 销冠这条发言\n"
        f"```\n{content.strip()[:1200]}\n```\n\n"
        "## 候选条目\n"
        f"{cand_lines}\n\n"
        "## 输出格式（**只输出 JSON 对象**，键固定为 labels）\n"
        '{\n'
        '  "labels": [\n'
        '    {"category_id": "sell_2", "confidence": 0.0~1.0, "reason": "一句话原因"},\n'
        '    ...\n'
        '  ]\n'
        '}\n\n'
        "判定规则：\n"
        "1. 没有任何条目实质命中 → labels 留空数组；\n"
        "2. confidence 含义：0.9+ 几乎复述原文 / 0.6-0.9 明显引用大意 / "
        "0.4-0.6 隐含相关；< 0.4 不要返回；\n"
        "3. 每条 reason 不超过 30 字；\n"
        "4. 同一发言可命中多个条目，但请控制在 ≤4 个最相关的。"
    )


def classify_turn_multilabel(
    *,
    content: str,
    handbook_struct: dict,
    top_k: int = 10,
    min_confidence: float = 0.4,
) -> list[dict[str, Any]]:
    """返回 [{ "category_id": str, "confidence": float, "reason": str }, ...]。

    短发言（< 6 字）或全数字 → 直接返回空。
    所有错误 → 记 warn，返回空（绝不把上层 runner 搞挂）。
    """
    content = (content or "").strip()
    if len(content) < 6:
        return []

    candidates = shortlist_candidates(content, handbook_struct, top_k=top_k)
    if not candidates:
        return []

    try:
        with with_llm_override(aux_llm_override(thinking_mode="disabled")):
            raw = call_llm_json(_SYSTEM_PROMPT, _user_prompt(content, candidates))
    except (LLMCallError, LLMJsonParseError) as exc:
        logger.warning("[classifier] LLM 失败：%s", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[classifier] LLM 未知异常：%s", exc)
        return []

    raw_labels = []
    if isinstance(raw, dict):
        raw_labels = raw.get("labels") or []
    elif isinstance(raw, list):
        raw_labels = raw

    cand_ids = {c["id"] for c in candidates}
    out: list[dict[str, Any]] = []
    for lab in raw_labels:
        if not isinstance(lab, dict):
            continue
        cid = lab.get("category_id") or lab.get("id")
        if cid not in cand_ids:
            continue
        try:
            conf = float(lab.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < min_confidence:
            continue
        out.append({
            "category_id": cid,
            "confidence": round(min(1.0, conf), 3),
            "reason": (lab.get("reason") or "")[:80],
        })
    # 按置信度排序，截 Top 4
    out.sort(key=lambda x: x["confidence"], reverse=True)
    return out[:4]
