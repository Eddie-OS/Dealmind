"""高频异议聚合 —— 把销冠/客户沉淀的自由文本异议归并成有意义的主题簇。

背景：批量报告的"高频异议"原先按**完全相同字符串**折叠，导致 LLM 写出的
近义异议（"价格太贵了" / "有点贵" / "预算不太够"）各自 count=1，247 条全是 1，
报告完全失去"高频"意义。

本模块两级归并（纯确定性，无 LLM，适合同步接口）：
  1) 主题规则：按关键词把异议映射到固定主题（价格 / 续航 / 重量 / 竞品 …），
     跨措辞甚至跨中英都能并到同一主题。
  2) 相似度兜底：命不中任何主题的长尾，按归一化文本的字符相似度聚类，
     近义自动并簇，代表文本取簇内最高频/最短者。
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Optional

# 主题规则：(主题标签, 关键词…)。命中任一关键词即归入该主题；按列表顺序优先，
# 故把更具体/更易误并的主题排在更靠前。关键词尽量覆盖中文 + 常见英文/本地化表达。
# 注意：单字关键词（重 / 卡 / 笔 / 轻 …）极易误命中（"重复""MIR卡""笔记本""年轻"），
# 一律用更具体的二字以上词；且把「键盘/办公」排在「笔/手写」之前，避免"笔记本"被
# 误判成手写笔。
_THEME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("价格/预算顾虑", (
        "太贵", "很贵", "贵了", "价格", "多少钱", "价位", "预算", "便宜",
        "划算", "性价比", "优惠", "折扣", "降价", "太高", "承受", "肉疼",
        "price", "expensive", "budget", "cost", "cheap", "afford", "discount",
    )),
    ("续航/充电顾虑", (
        "续航", "电池", "充电", "待机", "耗电", "电量", "毫安", "battery",
        "charge", "charging", "standby",
    )),
    ("键盘/办公能力", (
        "键盘", "打字", "文档", "表格", "excel", "ppt", "word", "办公",
        "替代笔记本", "笔记本", "生产力", "keyboard", "typing", "office",
    )),
    ("竞品对比", (
        "ipad", "苹果", "apple", "三星", "samsung", "小米", "xiaomi", "联想",
        "lenovo", "对比", "竞品", "比起", "不如", "别家", "其他品牌",
        "比较", "matebook", "surface", "airdrop", "原生",
    )),
    ("生态/软件兼容", (
        "软件", "应用", "兼容", "生态", "photoshop", "wps", "系统", "安卓",
        "android", "鸿蒙", "harmony", "harmonyos", "文件", "格式", "谷歌",
        "google", "gms", "装不了", "适配", "app",
    )),
    ("屏幕/护眼", (
        "护眼", "眼睛", "反光", "亮度", "分辨率", "色彩", "色温", "柔光",
        "屏幕", "类纸屏", "刺眼", "眩光", "screen", "display", "护眼模式",
    )),
    ("笔/手写体验", (
        "手写", "压感", "类纸", "书写", "pencil", "stylus", "跟手", "画画",
        "绘画", "防误触", "笔触", "手写笔", "writing",
    )),
    ("性能/流畅度", (
        "性能", "卡顿", "很卡", "会卡", "卡死", "流畅", "处理器", "芯片",
        "内存", "跑分", "死机", "发热", "散热", "制程", "performance",
        "lag", "slow",
    )),
    ("重量/便携顾虑", (
        "便携", "携带", "重量", "太重", "很重", "太沉", "轻便", "够轻",
        "portable", "weight", "heavy", "carry",
    )),
    ("售后/质保", (
        "售后", "保修", "质保", "维修", "换货", "退货", "返修", "碎屏",
        "联保", "warranty", "service", "repair", "after-sales", "after sales",
    )),
    ("必要性/犹豫拖延", (
        "再考虑", "再看看", "不着急", "没必要", "用不上", "回去想", "想想",
        "暂时", "再说", "看看再说", "下次", "think about", "later", "not sure",
    )),
    ("信任/品牌口碑", (
        "牌子", "品牌", "信任", "没听过", "口碑", "靠谱", "山寨", "brand",
        "trust", "reliable",
    )),
    ("需求不明确", (
        "不知道", "随便看看", "没想好", "逛逛", "just looking",
    )),
]

# 长尾相似度聚类阈值（归一化后字符相似度）。
_SIM_THRESHOLD = 0.72


def _normalize(text: str) -> str:
    """归一化：NFKC + 小写 + 去所有空白与标点，用于主题匹配 / 相似度比对。"""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(r"[\s\W_]+", "", t, flags=re.UNICODE)
    return t


def classify_theme(text: str) -> Optional[str]:
    """把一条异议映射到固定主题；命不中返回 None。"""
    norm = _normalize(text)
    if not norm:
        return None
    for label, keywords in _THEME_RULES:
        for kw in keywords:
            k = _normalize(kw)
            if k and k in norm:
                return label
    return None


def _similar(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


class _Cluster:
    __slots__ = ("label", "theme", "count", "variants", "personas",
                 "outcomes", "session_ids", "_rep_norm")

    def __init__(self, label: str, theme: Optional[str], rep_norm: str) -> None:
        self.label = label
        self.theme = theme
        self.count = 0
        self.variants: Counter = Counter()
        self.personas: set = set()
        self.outcomes: Counter = Counter()
        self.session_ids: list[str] = []
        self._rep_norm = rep_norm

    def add(self, row: dict[str, Any]) -> None:
        self.count += 1
        text = (row.get("text") or "").strip()
        if text:
            self.variants[text] += 1
        p = row.get("persona")
        if p:
            self.personas.add(p)
        self.outcomes[row.get("outcome") or "UNKNOWN"] += 1
        sid = row.get("session_id")
        if sid:
            self.session_ids.append(sid)

    def to_dict(self, *, variant_top: int = 5, session_top: int = 5) -> dict[str, Any]:
        # 主题簇用主题标签；长尾簇用簇内最高频的原文做代表
        if self.theme:
            label = self.label
        else:
            label = self.variants.most_common(1)[0][0] if self.variants else self.label
        return {
            "text": label,
            "theme": self.theme,
            "count": self.count,
            "variants": [
                {"text": t, "count": n}
                for t, n in self.variants.most_common(variant_top)
            ],
            "personas": sorted(self.personas),
            "outcomes": [
                {"outcome": k, "count": v} for k, v in self.outcomes.most_common()
            ],
            "session_ids": self.session_ids[:session_top],
        }


def aggregate_objections(
    rows: list[dict[str, Any]],
    *,
    top: Optional[int] = None,
) -> list[dict[str, Any]]:
    """把异议记录两级归并成主题簇并按频次倒序返回。

    rows: 每条 {text, persona?, outcome?, session_id?}。
    """
    theme_clusters: dict[str, _Cluster] = {}
    tail_clusters: list[_Cluster] = []

    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        theme = classify_theme(text)
        if theme:
            cl = theme_clusters.get(theme)
            if cl is None:
                cl = _Cluster(theme, theme, _normalize(theme))
                theme_clusters[theme] = cl
            cl.add(row)
            continue
        # 长尾：相似度归簇
        norm = _normalize(text)
        best: Optional[_Cluster] = None
        best_sim = 0.0
        for cl in tail_clusters:
            sim = _similar(norm, cl._rep_norm)
            if sim > best_sim:
                best_sim, best = sim, cl
        if best is not None and best_sim >= _SIM_THRESHOLD:
            best.add(row)
        else:
            cl = _Cluster(text, None, norm)
            cl.add(row)
            tail_clusters.append(cl)

    clusters = list(theme_clusters.values()) + tail_clusters
    clusters.sort(key=lambda c: c.count, reverse=True)
    out = [c.to_dict() for c in clusters]
    if top is not None:
        out = out[:top]
    return out
