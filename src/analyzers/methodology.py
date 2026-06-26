"""V2-① 报告可解释性：分析方法说明（单一事实源）。

``build_methodology()`` 返回结构化的「分析方法说明」，由 ``report_aggregator`` 注入
``summary["methodology"]``，供前端弹窗与导出 HTML **同源渲染**——保证两端文案永不漂移，
也为后续"维度可自定义"留出数据化基础（Phase 1：固定但完全透明）。

内容口径直接复用代码常量（如 6 维评分 ``SCORE_DIMENSIONS``、优秀话术分组 ``GROUP_LABEL``），
避免与实际打分逻辑脱节。
"""

from __future__ import annotations

from typing import Any

from src.analyzers.excellence_scorer import GROUP_LABEL, GROUP_ORDER
from src.analyzers.handbook_scorer import SCORE_DIMENSION_SPEC

METHODOLOGY_VERSION = "v3.0"

# 教练复盘 13 维（与 prompts/coach_prompt.md 对齐）
_COACH_DIMS: list[tuple[str, str]] = [
    ("结果归因 outcome_analysis", "本场成交/放弃/超时的根本原因与关键转折轮次。"),
    ("有效策略 what_worked", "销冠用对的策略，逐条配对话证据与生效原因。"),
    ("失效操作 what_failed", "销冠的错误/无效操作，逐条配证据与失效原因。"),
    ("场景契合 scene_fit_review", "门店场景是否充分用到店内动作（上手/真机演示/柜台对比），有无把客户引去网上查的反店内话术。"),
    ("工具使用 tool_use_review", "web_search 等工具的成功/失败次数、是否反复重试失败工具、是否该搜未搜、是否伪造证据。"),
    ("人设洞察 persona_insight", "对这类客户的新认识。"),
    ("关键经验 key_lessons", "可直接写进培训手册的 3-5 条可操作经验。"),
    ("更优反驳 suggested_rebuttals", "针对核心异议的 3 条更优话术模板。"),
    ("难度评分 difficulty_rating", "该人设的压力难度 1-10 及理由。"),
    ("可复用战术 reusable_tactics", "提炼 2-3 个带名称的可复用策略模式及使用条件。"),
    ("剧本覆盖 playbook_coverage_review", "逐阶段评价 playbook_action 的使用/缺失/过度堆叠/阶段错配。"),
    ("配比节奏 weight_balance_review", "各阶段轮次分配是否失衡、节奏问题与重来建议。"),
    ("地区一致性 localization_review", "货币串台/信源跨境/跨境参数混用扫描 + localization_score(0-10)。"),
]


def build_methodology() -> dict[str, Any]:
    """构造「分析方法说明」结构化数据。"""
    six_dim = []
    for d in SCORE_DIMENSION_SPEC:
        a = d["anchors"]
        six_dim.append({
            "name": f"{d['layer']}｜{d['name']}（{d['name_en']}）",
            "desc": (
                f"{d['definition']} "
                f"0~3：{a['0-3']} 4~7：{a['4-7']} 8~10：{a['8-10']}"
            ),
        })
    coach = [{"name": n, "desc": d} for n, d in _COACH_DIMS]
    groups_txt = "、".join(GROUP_LABEL[g] for g in GROUP_ORDER)

    return {
        "version": METHODOLOGY_VERSION,
        "intro": (
            "本报告由「销冠对话 → 逐句机检分类与打分 → 教练复盘 → 聚合」多智能体流水线生成。"
            "以下透明列出全部分析维度、评分口径与判定逻辑，确保每条结论可解释、可追溯。"
        ),
        "sections": [
            {
                "key": "structure",
                "title": "一、手册结构（135910）覆盖",
                "desc": (
                    "全量手册=1 介绍 / 3 卖点 / 3 竞品对比 / 5 参数 / 9 FAQ / 10 演示动作=31 条。"
                    "每条销冠发言经『关键词预筛 → LLM 多标签精分类(置信度≥0.4) → 硬过滤』映射到上述条目，"
                    "统计各条命中次数、覆盖会话数，得到覆盖率。"
                ),
                "items": [],
            },
            {
                "key": "six_dim",
                "title": "二、话术质量评分 · 三层 6 维（0-10，内部打分）",
                "desc": (
                    "每条命中手册的发言由 LLM 按「信任基石 / 价值传递 / 转化驱动」三层共 6 维打分"
                    "（对照每档分值锚定），用于排序、诊断与挑选；明细面板仍在后台驱动所有排序。"
                ),
                "items": six_dim,
            },
            {
                "key": "excellence",
                "title": "三、优秀话术判定（解耦手册一致性）",
                "desc": (
                    "核心原则：『优秀 ≠ 照搬手册』。手册没提到但真正打动客户的话术同样算优秀，"
                    "因此评分**剔除『参数真实性』（口径一致）维度**，改由两路结合（各占 50%）。"
                ),
                "items": [
                    {
                        "name": "行为信号（免费，数据驱动）",
                        "desc": (
                            "用紧邻的客户反应衡量这句话的真实效果："
                            "score = 0.45·成交意愿(本句后) + 0.30·成交意愿涨幅(归一化) + 0.25·态度正向度；"
                            "客户流失×0.3、投诉×0.15 惩罚。"
                        ),
                    },
                    {
                        "name": "LLM 优秀度（0-10）",
                        "desc": "对候选池逐句打优秀度 + 给出『为什么好』，明确不以是否照搬手册为门槛。",
                    },
                    {
                        "name": "分组与排序",
                        "desc": f"命中手册→按 135910 主标签归组；未命中→『手册外金句』。分组：{groups_txt}。",
                    },
                ],
            },
            {
                "key": "revision",
                "title": "四、手册迭代建议（31 条逐条）",
                "desc": (
                    "按 135910 顺序对全部 31 条逐条给建议（即便表现好也给强化建议），"
                    "每条标注状态（保持/强化/补充/修正/新增）+ 覆盖统计 + TOP3 真实原声。"
                ),
                "items": [],
            },
            {
                "key": "demo",
                "title": "五、现场演示识别（双保险）",
                "desc": "解决『演示覆盖率=0』：演示句常在关键词预筛被挤出候选，故用两路 content 信号兜底。",
                "items": [
                    {"name": "保险①：全角括号舞台指示", "desc": "销冠按规则把演示动作用全角（）包裹，如『（拿起样机演示分屏）』，便于机检与人工一眼可辨。"},
                    {"name": "保险②：演示动词", "desc": "检测『拿样机/上手/体验/试两笔/现场打开/给您看/演示』等动词。任一命中即把全部 10 条演示条目保底放入候选集交 LLM 归类。"},
                ],
            },
            {
                "key": "coach",
                "title": "六、教练复盘 13 维（会话级定性）",
                "desc": "每场对话结束后由教练 Agent 做一次定性复盘，覆盖以下 13 个维度，每条须配具体轮次证据。",
                "items": coach,
            },
        ],
    }
