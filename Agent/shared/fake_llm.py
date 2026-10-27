"""dry-run 用的假模型：不发一个网络请求，跑通全链路验证文件产出。

用途很窄，就一件事 —— 在真正烧钱跑 94 场之前，先确认
"手册解析 → 全量对练 → 话术提炼 → 质量分析 → 报告汇总"
这条链路上每个环节的 MD 都能正确落盘、格式正确、互相引用不断链。

它生成的文案是模板拼的，**没有任何分析价值**，所有产出 MD 都会
在头部标注 `dry_run: true`，不要拿去当真实结论。

实现上直接替换 src.llm 的三个入口函数。必须在 vendored 业务模块
被 import 之前替换（bootstrap.init 已保证这个顺序），否则那些模块
`from src.llm import call_llm_json` 拿到的会是真函数。
"""
from __future__ import annotations

import itertools
import threading
from typing import Any

_lock = threading.Lock()
_counters: dict[str, itertools.count] = {}


def reset_thread() -> None:
    """清空当前线程的计数。编排器在每场会话开始前调用。

    不清的话，同一个工作线程跑第二场时轮次计数会接着上一场往下走，
    第二场开局就命中"第 12 轮成交"，整场只有一两轮，看起来像 bug 实际是夹具问题。
    """
    suffix = f"@{threading.current_thread().name}"
    with _lock:
        for key in [k for k in _counters if k.endswith(suffix)]:
            del _counters[key]


def _tick(kind: str) -> int:
    """按 (调用方, 线程) 计数。并发跑批时每个会话在自己的线程里，
    这样每场的轮次序列各自独立，购买信号才会呈现单调上升而不是交错乱跳。"""
    key = f"{kind}@{threading.current_thread().name}"
    with _lock:
        if key not in _counters:
            _counters[key] = itertools.count(1)
        return next(_counters[key])


_CUSTOMER_LINES = [
    "这个价格我得再想想，我看别家同配置的便宜不少。",
    "你说的这些参数听着不错，但我平时也就刷刷视频，用得上吗？",
    "我朋友买了别的牌子，说续航很一般，你们这个能撑多久？",
    "有没有什么优惠？学生证能打折吗？",
    "我不太懂这些，你直接告诉我值不值这个钱。",
    "先不急着定，我回去和家里人商量一下。",
]

_SALES_LINES = [
    "理解您的顾虑，我先不谈价格，先帮您确认这台是不是您真正需要的。",
    "您刚提到主要是学习用，那这块屏幕的护眼认证对您来说是最直接的价值。",
    "同价位里确实有更便宜的，但差别在于售后和保值，我给您具体算一笔。",
    "这样，我现场给您演示一下，您自己上手感受两分钟再决定。",
    "您担心的这一点很常见，我这边有实测数据，您看一下就清楚了。",
    "那咱们今天先不定，我把配置和优惠给您记下来，您回去商量完随时找我。",
]


def _persona_payload() -> dict[str, Any]:
    n = _tick("persona")
    # 第 12 轮成交：既走通提前结束分支，又留下够长的对话给下游分析
    return {
        "content": f"[DRY-RUN 第{n}轮客户] " + _CUSTOMER_LINES[(n - 1) % len(_CUSTOMER_LINES)],
        "hidden_state": {
            "intent": "比价" if n % 2 else "观望",
            "attitude": "谨慎",
            "purchase_signal": round(min(0.07 * n, 0.95), 2),
            "status": "DEAL_DONE" if n >= 12 else "CONTINUE",
        },
    }


def _sales_payload() -> dict[str, Any]:
    n = _tick("sales")
    return {
        "content": f"[DRY-RUN 第{n}轮销冠] " + _SALES_LINES[(n - 1) % len(_SALES_LINES)],
        "strategy": {
            "intent": "建立信任" if n <= 2 else "处理异议",
            "used_product_context": True,
            "used_handbook": True,
            "next_action": "引导体验",
        },
    }


def _judge_payload() -> dict[str, Any]:
    n = _tick("judge")
    stage = f"S{min(1 + n // 2, 5)}"
    return {
        "should_continue": True,
        "current_stage": stage,
        "next_stage": stage,
        "dialogue_quality_score": 6.5,
        "sales_score": {
            "responsiveness": 7.0,
            "specificity": 6.0,
            "evidence_usage": 6.5,
            "objection_handling": 6.0,
            "closing_progress": 5.0,
        },
        "persona_instruction": "[DRY-RUN] 继续追问价格与竞品差异。",
        "sales_instruction": "[DRY-RUN] 用手册里的实测数据回应，不要空谈。",
        "avoid_repeating": [],
        "end_status": "CONTINUE",
        "reason": "[DRY-RUN] 假裁判固定评分，无分析价值。",
    }


def _memory_payload() -> dict[str, Any]:
    return {
        "current_need": "[DRY-RUN] 学习与轻办公，预算有限",
        "main_objections": ["价格偏高", "担心用不上高配"],
        "budget_boundary": "[DRY-RUN] 2500 元上下",
        "emotional_state": "谨慎但有兴趣",
        "mentioned_competitors": ["竞品A"],
        "decision_constraints": ["需与家人商量"],
        "do_not_repeat": ["已解释过屏幕参数"],
        "next_best_action": "给出具体优惠方案并引导现场体验",
    }


def _coach_payload() -> dict[str, Any]:
    return {
        "outcome_analysis": "[DRY-RUN] 假复盘，仅用于验证文件产出链路。",
        "what_worked": [
            {
                "round": 2,
                "strategy": "先确认需求再谈价",
                "evidence": "[DRY-RUN] 示例引用",
                "why_effective": "降低了客户的防御心理",
            }
        ],
        "what_failed": [
            {
                "round": 4,
                "strategy": "直接报价",
                "evidence": "[DRY-RUN] 示例引用",
                "why_failed": "客户尚未建立价值认知",
            }
        ],
        "persona_insight": "[DRY-RUN] 该类客户对数字敏感，需要可验证证据。",
        "key_lessons": [
            "[DRY-RUN] 价格异议出现在价值建立之前时，先回到需求确认。",
            "[DRY-RUN] 用实测数据替代形容词。",
        ],
        "suggested_rebuttals": [
            {
                "objection": "别家更便宜",
                "rebuttal_template": "[DRY-RUN] 同价位确实有更便宜的，差别在售后与保值，我给您算一笔。",
            }
        ],
        "difficulty_rating": 6,
        "difficulty_reason": "[DRY-RUN] 假评分。",
        "reusable_tactics": [
            {
                "name": "算总账",
                "condition": "客户拿低价竞品比较时",
                "example": "[DRY-RUN] 把使用周期摊到每天成本上对比。",
            }
        ],
    }


def _handbook_payload() -> dict[str, Any]:
    def _items(prefix: str, count: int, label: str) -> list[dict[str, str]]:
        return [
            {
                "id": f"{prefix}_{i}",
                "label": f"[DRY-RUN] {label}{i}",
                "text": f"[DRY-RUN] {label}{i} 的占位说明，非真实内容。",
            }
            for i in range(1, count + 1)
        ]

    return {
        "intro_1": {
            "id": "intro_1",
            "label": "一句话定位",
            "text": "[DRY-RUN] 这是 dry-run 生成的占位定位，非真实手册内容。",
        },
        "selling_points": _items("sell", 3, "卖点"),
        "competitor_points": [
            {**it, "vs": "竞品A"} for it in _items("comp", 3, "竞品差异")
        ],
        "core_params": _items("param", 5, "参数"),
        "faq": [
            {
                "id": f"faq_{i}",
                "label": f"[DRY-RUN] 常见问题{i}",
                "q": f"[DRY-RUN] 问题{i}？",
                "a": f"[DRY-RUN] 回答{i}。",
            }
            for i in range(1, 10)
        ],
        "demo_actions": _items("demo", 10, "演示动作"),
    }


# 指纹取自各调用方 system_prompt 的固定抬头（见 src/agents.py、judge.py、
# memory.py、coach.py、analyzers/handbook_extractor.py）。
# 注意：人设扮演的指令在 user_prompt 里，system_prompt 只有这句固定抬头，
# 不要拿 prompts/*.md 的首行当指纹。
_FINGERPRINTS = (
    ("销售培训教练", "coach"),
    ("会中裁判", "judge"),
    ("会话画像提取专家", "memory"),
    ("用户人设 Agent", "persona"),
    ("资深导购", "opening"),
    ("结构化抽取专家", "handbook"),
    ("销冠 Agent", "sales"),
)

_BUILDERS = {
    "coach": _coach_payload,
    "judge": _judge_payload,
    "memory": _memory_payload,
    "persona": _persona_payload,
    "handbook": _handbook_payload,
    "sales": _sales_payload,
    "opening": lambda: {"opening": "[DRY-RUN] 您好，随便看看？我给您介绍两句。"},
}


def _dispatch(system_prompt: str, user_prompt: str) -> Any:
    """按 system_prompt 抬头判断调用方。顺序要紧：判别力强的排前面。"""
    del user_prompt
    sp = system_prompt or ""
    for marker, kind in _FINGERPRINTS:
        if marker in sp:
            return _BUILDERS[kind]()
    # 分析器类调用（分类 / 打分）统统给空结构，让它们走自己的降级分支
    return {}


def install() -> None:
    """替换 src.llm 的对外调用入口。"""
    import src.llm as llm

    if getattr(llm, "_agent_fake_installed", False):
        return

    def call_llm_json(
        system_prompt: str, user_prompt: str, temperature: Any = None
    ) -> Any:
        del temperature
        return _dispatch(system_prompt, user_prompt)

    def call_llm(system_prompt: str, user_prompt: str, **_kwargs: Any) -> str:
        del system_prompt, user_prompt
        return "[DRY-RUN] 假文本响应。"

    def call_llm_with_tools(*_args: Any, **_kwargs: Any) -> Any:
        raise llm.LLMCallError("dry-run 模式不支持 tool-use 路径")

    llm.call_llm_json = call_llm_json
    llm.call_llm = call_llm
    llm.call_llm_with_tools = call_llm_with_tools
    llm._agent_fake_installed = True
