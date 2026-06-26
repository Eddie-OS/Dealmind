"""Persona Agent 与 Sales Champion Agent。

每个 Agent 对外只暴露一个函数：
- generate_persona_turn(state) -> Turn
- generate_sales_turn(state) -> Turn

内部流程：加载 prompt 模板 → 渲染变量 → call_llm_json → 解析为 Turn。
JSON 解析失败时返回 fallback Turn 而非崩溃，保证主循环能继续运行。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.business_stages import (
    get_allowed_actions,
    get_stage,
    is_valid_playbook_action,
    render_stage_for_sales,
    stage_cn_name,
)
from src.lang import lang_instruction
from src.llm import LLMCallError, LLMJsonParseError, call_llm_json, call_llm_with_tools
from src.safe_console import SafeConsole


logger = logging.getLogger(__name__)
from src.schema import (
    DialogueState,
    HiddenState,
    SalesStrategy,
    SpeakerType,
    Turn,
)
from src.utils import extract_json, safe_json_dumps


console = SafeConsole()

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_MAX_PRODUCT_CHARS = 5000
_MAX_RECENT_HISTORY = 10

# Stage 6b：RAG 单条 chunk 文本截断（前端展示+prompt 注入共用上限）
_RAG_CHUNK_TEXT_LIMIT = 600
# Stage 6b：每场查询的 top_k 默认值
_RAG_TOP_K_PRODUCT = 3
_RAG_TOP_K_ENTERPRISE = 2


# ============================================================
# Stage 5.5：按阶段动态约束（注入到 prompt）
# ============================================================
#
# 设计：
#   - 4 个 phase: mining (0~50%) / matching (50~70%) / pressure (70~85%) / closing (85~100%)
#   - 每个 phase 给 sales 和 persona 各自一段中文规则 + 字数区间
#   - 区间值同时回传，方便 prompt 在格式说明里展示"本轮字数：N~M 字"
# ============================================================


# ============================================================
# Stage 15f：销售场景上下文 + 工具状态摘要（注入 sales_prompt）
# ============================================================
#
# 设计动机：
#   · 历史会话里销冠把"店内"对话当成"线上客服"在做——客户在华为零售店，
#     销冠却一直说"您去花粉论坛搜""B 站搜评测视频"，明显不符合场景；
#   · web_search 工具因 API Key 未配置而每次返回 error，销冠却反复尝试同一
#     失败工具最多 20+ 次，没有降级策略；
#   · 销冠也不知道 LLM 训练数据可能不覆盖最新机型，无法主动给客户合理交代。
# ============================================================


_DEFAULT_SALES_CONTEXT = (
    "你身处一家**线下零售门店**，正面对一位**已到店、站在你面前**的客户。"
    "店内有所有当季展示机型的样机、配件、宣传物料，可以邀请客户上手 / 演示 / 对比；"
    "门店有当日促销政策、首批名额、以旧换新、赠品等可当场承诺的资源；"
    "你身后有同事和后台系统，可以当场开单 / 锁库存 / 发短信。"
    "你的核心优势是『现场感』——真机+试用+演示 永远优于把客户引到网上去看链接。"
)

_STORE_CONTEXT_KEYWORDS = (
    "零售店", "门店", "店里", "店内", "实体店", "柜台", "现场", "展厅",
    "专卖店", "授权店", "线下店",
)


def _infer_sales_context(topic: str) -> str:
    """从 topic 文本里粗粒度推断销售场景；命中关键词就给店内场景，否则给通用销售场景。

    后续若想细化成"4S 店 / 餐厅 / 美容院 / 线上电商"，只要扩 _STORE_CONTEXT_KEYWORDS 表
    或改成调用一次 LLM 抽取场景类型即可。本版优先保证简单可解释。
    """
    t = (topic or "").strip()
    if any(kw in t for kw in _STORE_CONTEXT_KEYWORDS):
        return _DEFAULT_SALES_CONTEXT
    # topic 含"销售模拟 / 销售"这种泛词时，默认按"店内"处理（项目 PRD 就是店内场景）
    if "销售" in t:
        return _DEFAULT_SALES_CONTEXT
    return (
        "你是一名职业销冠，正在与一位潜在客户对话。请基于话题里给出的产品 / 服务，"
        "用职业销售的方式逐步建立信任、回应异议、推进成交；不要假定客户在什么物理场景，"
        "话术里不要使用『到店 / 柜台 / 现场』等只适用于线下门店的表达。"
    )


def _tool_status_summary(
    *,
    tools_enabled: list[str] | None = None,
    web_search_available: bool | None = None,
) -> str:
    """生成"本轮工具实时状态"字符串，注入 prompt 让销冠先看后调。

    web_search_available=None 时表示 tool-use 路径未启用，整段写"无可用工具"。
    """
    lines: list[str] = []
    if not tools_enabled:
        return "（本轮未启用任何外部工具。请只基于上方知识库与你的销售经验作答。）"
    lines.append("本轮可用工具：" + "、".join(tools_enabled))
    if web_search_available is True:
        lines.append("  · web_search ✅ 可用（含最新互联网信息；客户问到新品、新款、最新评测、最新友商动态时**必须**先查）")
    elif web_search_available is False:
        lines.append(
            "  · web_search ❌ **不可用**（API Key 未配置）。"
            "客户问到 LLM 训练数据后才发布的新品（如最新型号 / 最新参数 / 最新友商对比）时，"
            "**不要反复尝试调用** web_search，按 sales_prompt 里『工具失败应对』三选一兜底："
            "(a) 现场动作 / (b) 同类已知产品类比 / (c) 诚实降级 + 推进。"
        )
    return "\n".join(lines)


def _is_web_search_available() -> bool:
    """检测 web_search 的 API Key 是否已配置——决定是否在 prompt 里告诉销冠工具可用。"""
    try:
        from src.tools.web_search import _load_web_search_cfg  # noqa: WPS433

        cfg = _load_web_search_cfg()
        return bool((cfg or {}).get("api_key"))
    except Exception:  # noqa: BLE001
        return False


def _phase_from_state(state: DialogueState) -> str:
    """从「客户已暴露的信号 + 临近上限程度」算出当前 phase 大类。

    Stage 15d 重构（替换原 round/max_rounds 比例硬切）：
        旧版按 round_idx/max_rounds 比例强切 phase，导致 max_rounds=50 时
        销冠被规则锁在"mining 期"前 25 轮、严禁推产品 → 凑轮次问废话。
        新版改为"客户信号驱动"，配合"临近上限时强制收口"。
    """
    sm = state.session_memory

    # ── 1. 临近上限：剩余 ≤ 3 轮或已到 85% → 必须 closing ─────────
    if state.max_rounds > 0:
        progress = max(state.round_idx, 0) / state.max_rounds
        rounds_left = state.max_rounds - state.round_idx
        if rounds_left <= 3 or progress >= 0.85:
            return "closing"

    # ── 2. 客户已发出强购买信号（hidden_state.purchase_signal≥0.7）→ closing ──
    latest_persona = next(
        (t for t in reversed(state.full_history) if t.speaker == "persona"),
        None,
    )
    if latest_persona:
        try:
            sig = float((latest_persona.metadata or {}).get("purchase_signal") or 0)
        except (TypeError, ValueError):
            sig = 0.0
        if sig >= 0.7:
            return "closing"

    # ── 3. 信号累积驱动 mining → matching → pressure ────────────────
    info_score = 0
    if (sm.current_need or "").strip():
        info_score += 1
    if (sm.budget_boundary or "").strip():
        info_score += 1
    if len(sm.main_objections) >= 1:
        info_score += 1
    if len(sm.mentioned_competitors) >= 1:
        info_score += 1

    if info_score == 0:
        return "mining"        # 还啥都不知道 → 探需求
    if info_score == 1:
        return "matching"      # 知道一个维度 → 可以开始给方案
    return "pressure"          # 多维度信息齐全 → 直面异议、推进成交


_SALES_PHASE_BLOCKS = {
    "mining": (
        "【挖掘期 · 客户还没暴露明确需求】\n"
        "1. 用 1-2 个有针对性的开放问题挖客户场景 / 使用人 / 痛点；不要一次问 3 个以上。\n"
        "2. **如果客户已经主动给出明确需求或目标产品（例如「我想买华为手机，预算 3000」），\n"
        "   立刻进入响应模式——直接确认 1-2 个关键参数后就推具体型号，不要再绕回去探需求。**\n"
        "3. 客户说「我先看看 / 随便逛逛」时，给一句轻量钩子（如「有合适我帮您介绍下」），不要追问。\n"
        "4. **不要重复问已经问过的维度**（session_memory 已记录就别再问）。\n"
    ),
    "matching": (
        "【匹配期 · 客户已暴露 ≥1 个核心需求】\n"
        "1. **立即从产品资料 / 通用经验里挑出 1-2 款匹配的具体型号或方案**呈现给客户，\n"
        "   配关键参数 / 价格区间 / 适配理由——这一步不要再做需求探问。\n"
        "2. 还没问清的维度可以在推荐时顺带问（如『这款够您看 PDF 了，您主要在哪用？』），\n"
        "   不要单独再开一轮纯探问。\n"
        "3. 引用产品事实必须来自知识库或公开常识，不确定时说『我帮您确认』，不要编造。\n"
    ),
    "pressure": (
        "【强压期 · 客户暴露了多个维度或有明确异议】\n"
        "1. 直面客户最强异议（价格 / 竞品 / 信任）：先共情，再给具体证据（数字 / 政策 / 案例）。\n"
        "2. 可以主动给优惠条件，最好带时间或动作边界（如『今日下单送 XX / 3 日内有效』）。\n"
        "3. 客户已明确意向时，**主动提议下一步**（试用 / 配送 / 锁库存），不要继续讨论参数。\n"
    ),
    "closing": (
        "【收单期 · 接近上限或客户购买意向强】\n"
        "1. **核心任务：拿一个明确的『下一步』承诺**（开单 / 试用 / 预约 / 留联系 / 延期跟进）。\n"
        "2. 给客户一个低成本的 yes（如『先帮您锁库存 / 留 5 分钟过下规格』）。\n"
        "3. 客户明显拒绝（如『不考虑了 / 不合适』）时干净收尾，给个台阶，**不要纠缠、不要再推参数**。\n"
        "4. 如果已接近最大轮数：用 1-2 句锁定具体后续动作，不要拖。\n"
    ),
}

_PERSONA_PHASE_BLOCKS = {
    "mining": (
        "【挖掘期 · 销冠还在了解你】\n"
        "1. 渐进披露：第 1-2 轮可以只给一个『模糊方向』（如『想换台手机』），让销冠问具体；\n"
        "   销冠**针对性问到**某维度时（用途 / 预算 / 品牌偏好 / 已用过的）就**坦诚回答**，\n"
        "   不要刻意挤牙膏。\n"
        "2. 配合人设压力参数让态度有温度（耐心低 → 简短；怀疑高 → 反问）。\n"
        "3. 销冠如果**一直只问不答**、连续 2 轮没给任何产品信息时，可以表达不耐烦或威胁离开。\n"
    ),
    "matching": (
        "【匹配期 · 销冠开始给方案】\n"
        "1. 销冠给具体产品时，结合人设挑刺（拿用过的 / 家里有的 / 朋友推荐的对比）。\n"
        "2. 真正符合你需求的方案，可以表达初步认可，但保留 1-2 个核心异议待销冠回应。\n"
    ),
    "pressure": (
        "【强压期 · 你和销冠在拉锯异议】\n"
        "1. 把最强异议（价格 / 竞品 / 售后 / 保值）摆出来，可以砍价 / 要求白纸黑字承诺。\n"
        "2. 销冠的模糊承诺要追问到具体条件。\n"
        "3. 异议被实质回应后，可以表态意向（DEAL_DONE 或 FOLLOW_UP）。\n"
    ),
    "closing": (
        "【收单期 · 临近收尾】\n"
        "1. 给出清晰的 yes / no / 再想想，不要再反复挑刺。\n"
        "2. 决策权低的人设可以以『回去商量』作为 FOLLOW_UP 过渡。\n"
    ),
}

# 字数动态区间（开场/挖掘短，异议/强压长）
_PHASE_WORD_LIMIT = {
    "mining":   ("20", "60"),
    "matching": ("40", "120"),
    "pressure": ("50", "150"),
    "closing":  ("30", "120"),
}


def _walk_away_trigger_block() -> str:
    """Persona prompt 通用 walk_away / complaint 触发说明（v1 v2 共用）。

    Stage 15d 调整：DEAL_DONE 不再硬性要求"过 50% 轮次"——只要核心顾虑被
    实质回应即可。否则用户设了 max_rounds=50 时客户即使想买前 25 轮也不能。
    """
    return (
        "【特殊状态触发（满足任一条件则在 hidden_state.status 中标记 + 给 walk_away_reason）】\n"
        "  · status=WALK_AWAY · reason=\"过早强推\"——销售一上来不问需求就硬塞具体型号或砍价。\n"
        "  · status=WALK_AWAY · reason=\"不被尊重\"——你说『自己看看』后销售还在追问或强推。\n"
        "  · status=WALK_AWAY · reason=\"凑话问废话\"——销售连续 3 轮以上只问不答，或重复你已经回答过的问题。\n"
        "  · status=COMPLAINT · reason=\"服务态度差\"——销售言语轻视、嘲讽，或暗示你买不起。\n"
        "  · status=DEAL_DONE——你的核心顾虑已被实质回应、对方案满意、确认要买。**任何轮次都可触发**。\n"
        "  · status=FOLLOW_UP——你已感兴趣但需要回去商量或比较，约定后续跟进。\n"
        "  · 其他情况一律 status=CONTINUE。\n"
    )


# ============================================================
# Stage 6b：RAG 检索辅助
# ============================================================
# 设计：
#   - query 由「最近 2 条 turn 内容」+「session_memory.main_objections」拼接
#   - 双 KB 各自查询、各自注入 prompt 占位
#   - 全部失败/不存在 → 走 fallback 文本，不让会话崩
#   - 返回结构：list of {id, text, score, metadata}


_ZH_EN_TERM_MAP: dict[str, str] = {
    "价格": "price cost",
    "多少钱": "price how much",
    "屏幕": "screen display",
    "续航": "battery life hours",
    "内存": "RAM memory storage",
    "摄像头": "camera",
    "处理器": "processor CPU chip",
    "手写笔": "stylus pen M-Pencil",
    "键盘": "keyboard",
    "充电": "charging",
    "重量": "weight",
    "厚度": "thickness",
    "防水": "waterproof",
    "分辨率": "resolution",
    "刷新率": "refresh rate",
    "保修": "warranty",
    "售后": "after-sales service",
    "对比": "compare vs comparison",
    "优势": "advantage feature benefit",
    "功能": "function feature",
    "办公": "office productivity",
    "学习": "education student",
    "游戏": "gaming",
    "平板": "tablet iPad",
    "华为": "Huawei HUAWEI",
    "销售": "sales selling",
    "客户": "customer client",
    "异议": "objection concern",
}


def _append_en_keywords(text: str) -> str:
    """在中文查询文本末尾附加对应英文关键词，提升跨语言向量检索召回。"""
    en_terms: list[str] = []
    for zh, en in _ZH_EN_TERM_MAP.items():
        if zh in text:
            en_terms.append(en)
    if en_terms:
        return text + " | " + " ".join(en_terms)
    return text


def _build_rag_query(state: DialogueState) -> str:
    """从对话状态构造 RAG 查询文本。

    Stage 15c 修订：``topic`` 始终作为第一段高权重 anchor 加入 query，
    避免对话上下文里没出现话题关键词时（例如刚开场只有一句"您好"），
    RAG 召回与本场话题无关的旧资料（典型 bug：话题"手机销售"却召回平板）。

    附加英文关键词映射，改善中文查询对英文知识库文档的跨语言召回率。

    返回示例（截断）：
        "本场话题：手机销售模拟 | 客户：预算 3000 以内 | 核心异议：保值率差 | price sales"
    """
    parts: list[str] = []

    topic = (state.topic or "").strip()
    if topic:
        parts.append(f"本场话题：{topic[:120]}")

    recent = state.recent_history[-2:] if state.recent_history else []
    for t in recent:
        role = "客户" if t.speaker == "persona" else "销冠"
        snippet = (t.content or "").strip().replace("\n", " ")
        if snippet:
            parts.append(f"{role}：{snippet[:160]}")

    objs = (state.session_memory.main_objections or [])[:3]
    if objs:
        parts.append("核心异议：" + " / ".join(o for o in objs if o))

    query = " | ".join(parts)
    query = query.strip() or topic[:120] or "销售对话"
    return _append_en_keywords(query)


def _fetch_kb_hits(
    kb_id: Optional[int],
    kb_type: str,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """对一个 KB 跑一次检索。任何异常或 kb_id 为空都返回 []，**永远不抛**。"""
    if not kb_id or not query:
        return []
    try:
        # 延迟导入避免 agents 模块在无 Chroma 环境也能 import（CLI / 单元测试）
        from src.rag.kb_store import KBStore  # noqa: WPS433

        store = KBStore(int(kb_id), kb_type)
        hits = store.query(query, top_k=top_k, scope_kb_only=True)
    except Exception as exc:  # noqa: BLE001
        console.print(
            f"[yellow]RAG 检索失败 (kb_id={kb_id}, type={kb_type}): {exc}[/yellow]"
        )
        return []
    # 截断 text 防止注入 prompt 过长
    for h in hits:
        t = h.get("text") or ""
        if len(t) > _RAG_CHUNK_TEXT_LIMIT:
            h["text"] = t[:_RAG_CHUNK_TEXT_LIMIT] + "…"
    return hits


def _format_hits_for_prompt(
    hits: list[dict[str, Any]],
    *,
    empty_text: str,
) -> str:
    """把检索结果拼成可读 markdown 段，注入 sales_prompt。"""
    if not hits:
        return empty_text
    lines: list[str] = []
    for i, h in enumerate(hits, 1):
        meta = h.get("metadata") or {}
        section = meta.get("section") or ""
        filename = meta.get("filename") or ""
        score = h.get("score")
        score_txt = f" · score={score:.3f}" if isinstance(score, (int, float)) else ""
        head = f"[{i}] 《{filename}》"
        if section:
            head += f" · {section}"
        head += score_txt
        lines.append(head)
        lines.append(h.get("text") or "")
        lines.append("")  # 空行分隔
    return "\n".join(lines).strip()


def _phase_pack(state: DialogueState, role: str) -> dict[str, str]:
    """返回当前轮 prompt 注入用的阶段相关变量。

    role: 'sales' / 'persona'
    """
    phase = _phase_from_state(state)
    lo, hi = _PHASE_WORD_LIMIT[phase]
    if role == "sales":
        block = _SALES_PHASE_BLOCKS[phase]
    else:
        block = _PERSONA_PHASE_BLOCKS[phase] + "\n" + _walk_away_trigger_block()
    return {
        "phase": phase,
        "phase_constraints": block,
        "word_min": lo,
        "word_max": hi,
        "word_limit": f"{lo}~{hi}",
    }


# ============================================================
# business_stages v0.2：S1-S5 stage id 推断 + 渲染包
# ============================================================
#
# 历史包袱：旧版用中文长名 (state.current_stage = "开场与需求暴露" 等 6 个) 表示阶段。
# 新版改用 S1~S5 五阶段 id (state.current_stage_id)。两个字段并存：
#   - state.current_stage_id 由 Judge 主写、Session 读取后渲染 prompt
#   - state.current_stage 继续保留给前端老逻辑 / 老历史会话
# 这里给出双向兼容映射，让任何一侧不一致都能恢复出合理 stage id。
# ============================================================


_LEGACY_STAGE_NAME_TO_ID = {
    # 旧 6 阶段命名 → 新 5 阶段 id
    "开场与需求暴露":        "S1",
    "核心异议出现":          "S2",
    "销冠挖掘动机":          "S2",
    "方案匹配与价值锚定":    "S3",
    "强压测试":              "S4",
    "成交推进或失败退出":    "S4",
}


def _infer_stage_id(state: DialogueState) -> str:
    """从 DialogueState 推断当前 S1-S5。

    优先级：
      1. state.current_stage_id 有值且合法 → 直接用
      2. state.current_stage（中文）能查表 → 转换
      3. 都不行 → S1（开场）
    """
    sid = (getattr(state, "current_stage_id", "") or "").strip()
    if sid in {"S1", "S2", "S3", "S4", "S5"}:
        return sid

    legacy_name = (state.current_stage or "").strip()
    if legacy_name in _LEGACY_STAGE_NAME_TO_ID:
        return _LEGACY_STAGE_NAME_TO_ID[legacy_name]

    return "S1"


def _stage_pack(state: DialogueState) -> dict[str, str]:
    """渲染 sales_prompt / persona_prompt 用的 business_stages 块（5 阶段视野中的当前阶段）。

    返回字典 keys：
      - current_stage_id              : "S3"
      - current_stage_cn              : "方案匹配与价值锚定"
      - stage_playbook_block          : YAML 中当前 stage 的 actions / must_not / allowed_actions 段
      - allowed_playbook_actions_csv  : 允许的 playbook_action 逗号串（供格式说明引用）
      - client_market_block           : v0.2.1 真实性补丁。客户所在国家/货币/可信信源块。

    v0.3 新增：
      - stage_required_trigger        : v10.1 导购员核心驱动动作
      - stage_gate_condition          : v10.1 消费者流转大闸
      - stage_sales_logic             : v10.2 销冠该阶段执行逻辑
      - stage_sales_constraints       : v10.2 销冠该阶段行为约束
      - stage_persona_logic           : v10.2 Persona 该阶段执行逻辑
      - stage_persona_constraints     : v10.2 Persona 该阶段行为约束
      - stage_window_str              : "4-9" (按 state.max_rounds 算的本阶段 ideal 轮次窗口)
      - stage_budget_hint             : "在窗口内剩 3 轮" / "已超窗 2 轮，必须收口"
    """
    sid = _infer_stage_id(state)
    spec = get_stage(sid)

    # v0.3：拉新字段（缺省 = 友好兜底）
    req_trigger = (spec.required_trigger if spec else "") or "（本阶段未定义 required_trigger）"
    gate_cond = (spec.gate_condition if spec else "") or "（本阶段未定义 gate_condition）"
    s_logic = (spec.sales_logic if spec else "") or ""
    s_constr = (spec.sales_constraints if spec else "") or ""
    p_logic = (spec.persona_logic if spec else "") or ""
    p_constr = (spec.persona_constraints if spec else "") or ""

    # v0.3：本阶段 ideal 轮次窗口 + 预算提示
    try:
        from src.stage_quota import current_stage_phase  # noqa: PLC0415
        phase_info = current_stage_phase(
            round_idx=state.round_idx,
            current_stage_id=sid,
            max_rounds=state.max_rounds,
        )
        window_str = phase_info.get("ideal_window_str", "—")
        over = int(phase_info.get("over_budget_rounds", 0) or 0)
        left = int(phase_info.get("rounds_left_in_stage", 0) or 0)
        if over > 0:
            budget_hint = f"⚠️ 已超本阶段 ideal 窗口 {over} 轮，必须立刻执行 required_trigger 或推下阶段。"
        else:
            budget_hint = f"本阶段 ideal 窗口 {window_str}（剩余 {left} 轮）。"
    except Exception as exc:  # noqa: BLE001
        logger.warning("_stage_pack quota 计算失败：%s", exc)
        window_str = "—"
        budget_hint = ""

    return {
        "current_stage_id": sid,
        "current_stage_cn": stage_cn_name(sid),
        "stage_playbook_block": render_stage_for_sales(sid),
        "allowed_playbook_actions_csv": ", ".join(get_allowed_actions(sid)) or "（无）",
        "client_market_block": _build_client_market_block(state),
        # v0.3 NEW
        "stage_required_trigger": req_trigger,
        "stage_gate_condition": gate_cond,
        "stage_sales_logic": s_logic,
        "stage_sales_constraints": s_constr,
        "stage_persona_logic": p_logic,
        "stage_persona_constraints": p_constr,
        "stage_window_str": window_str,
        "stage_budget_hint": budget_hint,
    }


def _build_client_market_block(state: DialogueState) -> str:
    """v0.2.1：渲染 persona 的 country/currency/market_domains 给 sales_prompt 用。

    persona 上有显式字段就用显式字段；否则 fallback DEFAULT_GLOBAL_MARKET。
    完全失败安全（出异常返回兜底文本）。
    """
    from src.locales import render_client_market_block

    try:
        persona = state.persona_profile
        return render_client_market_block(
            country_code=getattr(persona, "country_code", None),
            country_name=getattr(persona, "country_name", None),
            currency=getattr(persona, "currency", None),
            market_domains=list(getattr(persona, "market_domains", []) or []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("_build_client_market_block 失败：%s", exc)
        return "客户所在国家：未指定（按全球站 + USD 兜底，谨慎报价）"


def _build_brand_profile_block(state: DialogueState) -> str:
    """③ 注入产品无关的「华为零售店身份」铁律。读默认品牌人格；DB 不可用时回落到内置原文。"""
    try:
        from src.storage import db as _bp_db

        with _bp_db.connection_scope() as _conn:
            bp = _bp_db.get_default_brand_profile(_conn)
        if bp and (bp.get("identity_block") or "").strip():
            return bp["identity_block"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("_build_brand_profile_block 失败，回落内置：%s", exc)
    from src.storage.db import _DEFAULT_HUAWEI_IDENTITY_BLOCK
    return _DEFAULT_HUAWEI_IDENTITY_BLOCK


def _build_market_facts_block(state: DialogueState) -> str:
    """② 注入对话前预研的「市场事实表」。仅读缓存（不在对话轮里现搜，保证快 + 省 quota）。

    缓存键 = (resolved handbook_id, persona.country_code)。无缓存 / 出异常都降级为提示文本。
    """
    try:
        from src.research.market_research import render_market_facts_block
        from src.storage import db as _mf_db

        persona = state.persona_profile
        cc = (getattr(persona, "country_code", None) or "").strip().upper()
        if not cc or cc == "GLOBAL":
            return render_market_facts_block(None)

        with _mf_db.connection_scope() as _conn:
            hb_id = getattr(state, "handbook_id", None) or _mf_db.resolve_default_handbook_id(_conn)
            row = _mf_db.get_market_facts(_conn, handbook_id=hb_id, country_code=cc)
        return render_market_facts_block(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("_build_market_facts_block 失败：%s", exc)
        from src.research.market_research import render_market_facts_block
        return render_market_facts_block(None)


def _build_playbook_block(hb: dict[str, Any], struct: dict[str, Any]) -> str:
    """playbook_v1（按人设 + 4 章流程）注入块：开场 / 卖点(按人设) / 竞品 / Q&A。"""
    name = hb.get("name") or "产品手册"
    open_blk = struct.get("open") or {}
    opener = (open_blk.get("opener") or "").strip()
    timing = (open_blk.get("timing_cue") or "").strip()

    # ① 开场破冰
    opener_lines: list[str] = []
    if opener:
        opener_lines.append(f"通用开场问句：{opener}")
    if timing:
        opener_lines.append(f"（时机：{timing}）")
    for po in open_blk.get("persona_openers") or []:
        p = (po.get("persona") or "?").strip()
        lab = (po.get("persona_label") or "").strip()
        txt = (po.get("text") or "").strip()
        if txt:
            opener_lines.append(f"  - {p} · {lab}：{txt}")
    open_text = "\n".join(opener_lines) or "_（暂无）_"

    # ② 核心卖点（按人设）
    say_blocks: list[str] = []
    for blk in struct.get("say") or []:
        p = (blk.get("persona") or "?").strip()
        lab = (blk.get("persona_label") or "").strip()
        say_blocks.append(f"【{p} · {lab}】")
        for i, pt in enumerate(blk.get("points") or [], 1):
            say_blocks.append(
                f"  {i}. **{(pt.get('label') or '').strip()}** — {(pt.get('text') or '').strip()}"
            )
            demo = (pt.get("demo") or "").strip()
            if demo:
                say_blocks.append(f"     演示：{demo}")
    say_text = "\n".join(say_blocks) or "_（暂无）_"

    # ③ 竞品应对
    comp_blocks: list[str] = []
    for blk in struct.get("compete") or []:
        vs = (blk.get("vs") or "").strip()
        note = (blk.get("note") or "").strip()
        comp_blocks.append(f"〔vs {vs}〕" + (f"（{note}）" if note else ""))
        for pr in blk.get("pairs") or []:
            cust = (pr.get("customer") or "").strip()
            resp = (pr.get("response") or "").strip()
            if cust:
                comp_blocks.append(f"  · 客户：{cust}")
            if resp:
                comp_blocks.append(f"    应答：{resp}")
    comp_text = "\n".join(comp_blocks) or "_（暂无）_"

    # ④ 常见问答
    faq_blocks: list[str] = []
    for i, q in enumerate(struct.get("respond") or [], 1):
        faq_blocks.append(f"  {i}. **Q：{(q.get('q') or '').strip()}**")
        faq_blocks.append(f"     A：{(q.get('a') or '').strip()}")
        demo = (q.get("demo") or "").strip()
        if demo:
            faq_blocks.append(f"     演示：{demo}")
    faq_text = "\n".join(faq_blocks) or "_（暂无）_"

    # 人设清单：从本手册实际抽取的 say/open 动态生成（不写死 A/B/C/D 标签，
    # 不同手册人设命名不同，如 atypica=Business/Content/Student/Parent，
    # WorkBuddy=Digital Note-taker/Mobile Creator/Light Office Nomad）。
    persona_seen: dict[str, str] = {}
    for src_blk in (struct.get("say") or []), (
        (open_blk.get("persona_openers") or [])
    ):
        for it in src_blk:
            p = (it.get("persona") or "").strip()
            lab = (it.get("persona_label") or "").strip()
            if p and p not in persona_seen:
                persona_seen[p] = lab
    if persona_seen:
        persona_hint = " / ".join(
            f"{p}={lab}" if lab else p for p, lab in persona_seen.items()
        )
    else:
        persona_hint = "见下方各人设话术"

    return (
        f"**产品手册：{name}**（playbook · version v{hb.get('version_no', 1)} · "
        f"status={hb.get('status', 'ready')}）\n\n"
        "本手册是你本场对话的**销冠剧本**（销售流程 4 章），与上方“产品事实卡”同为最高优先级。\n"
        "⚑ **第一步：先判断眼前客户属于哪类人设，再用对应话术**——"
        f"{persona_hint}。"
        "判断不准时先用通用开场问句试探，再切换到对应人设话术。\n\n"
        f"### ① 开场破冰（OPEN）\n{open_text}\n\n"
        f"### ② 核心卖点（SAY · 按人设）\n{say_text}\n\n"
        f"### ③ 竞品应对（COMPETE）\n{comp_text}\n\n"
        f"### ④ 常见问答（RESPOND）\n{faq_text}\n\n"
        "⚠️ **铁律**：\n"
        "- 客户命中上述任一条目时，**必须**引用该项原文/数字，并优先用对应人设的话术；\n"
        "- 客户问到的内容不在手册中时，按销售经验回答，并坦诚说“这点我帮您当场查官网确认”；\n"
        "- 严禁说手册明确否定/未授权的内容（含虚构参数、跨产品对比、超出政策的承诺）。"
    )


def _build_handbook_block_with_meta(
    state: DialogueState,
) -> tuple[str, dict[str, Any]]:
    """与 _build_handbook_block 同接口，但同时返回签名 metadata，
    供 turn.metadata 追溯用。

    返回 (block_text, meta)：
      meta = {
        "handbook_id": int | None,       # 实际使用的 handbook id（自动套用后的）
        "handbook_resolved_from": "explicit" | "default" | "none",
        "handbook_block_len": int,        # 块字符数
        "handbook_block_hash": str,       # block 文本 sha1 前 12 位
        "handbook_version_no": int | None,
        "handbook_status": str | None,
      }
    """
    import hashlib
    from src.storage import db as _hb_db

    explicit_id = getattr(state, "handbook_id", None)
    meta: dict[str, Any] = {
        "handbook_id": explicit_id,
        "handbook_resolved_from": "explicit" if explicit_id else "none",
        "handbook_block_len": 0,
        "handbook_block_hash": "",
        "handbook_version_no": None,
        "handbook_status": None,
    }

    text = "**产品手册：未绑定**\n\n本场未绑定 Handbook，按通用销售经验回答。"
    hb_id = explicit_id

    try:
        with _hb_db.connection_scope() as _conn:
            if not hb_id:
                hb_id = _hb_db.resolve_default_handbook_id(_conn)
                if hb_id:
                    meta["handbook_resolved_from"] = "default"
            if hb_id:
                meta["handbook_id"] = int(hb_id)
                hb = _hb_db.get_handbook(_conn, int(hb_id))
            else:
                hb = None
    except Exception as exc:  # noqa: BLE001
        text = f"**产品手册：读取失败**\n\n（{exc}）请按通用销售经验回答。"
        meta["handbook_block_len"] = len(text)
        meta["handbook_block_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        return text, meta

    if not hb_id:
        text = (
            "**产品手册：未绑定**\n\n"
            "本场未绑定 Handbook。请按你的通用销售经验作答，"
            "并继续遵守上方“产品事实卡”的硬约束。"
        )
        meta["handbook_block_len"] = len(text)
        meta["handbook_block_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        return text, meta

    if not hb:
        text = (
            "**产品手册：未找到（id="
            + str(hb_id)
            + "）**\n\n请按通用销售经验回答。"
        )
        meta["handbook_block_len"] = len(text)
        meta["handbook_block_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        return text, meta

    meta["handbook_version_no"] = hb.get("version_no")
    meta["handbook_status"] = hb.get("status")

    struct = hb.get("structure_json") or {}
    if not isinstance(struct, dict) or not struct:
        text = (
            f"**产品手册:{hb.get('name')}(结构未抽取)**\n\n"
            "Handbook 尚未抽取结构，请去『知识与资产 → 产品手册』完善。"
        )
        meta["handbook_block_len"] = len(text)
        meta["handbook_block_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        return text, meta

    # playbook_v1（按人设 + 4 章流程）：走专用注入块
    if struct.get("doc_type") == "playbook_v1":
        meta["handbook_version_no"] = hb.get("version_no")
        meta["handbook_status"] = hb.get("status")
        meta["handbook_doc_type"] = "playbook_v1"
        text = _build_playbook_block(hb, struct)
        meta["handbook_block_len"] = len(text)
        meta["handbook_block_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        return text, meta

    def _join(items, fmt):
        out: list[str] = []
        for i, it in enumerate(items or [], 1):
            try:
                out.append(fmt(i, it))
            except Exception:
                continue
        return "\n".join(out) if out else "_（暂无）_"

    intro = struct.get("intro_1") or {}
    intro_text = (intro.get("text") or "").strip() if isinstance(intro, dict) else ""

    sell_lines = _join(
        struct.get("selling_points"),
        lambda i, it: f"  {i}. **{it.get('label', '')}** — {it.get('text', '')}",
    )
    comp_lines = _join(
        struct.get("competitor_points"),
        lambda i, it: (
            f"  {i}. **{it.get('label', '')}**"
            + (f"（vs {it.get('vs')}）" if it.get("vs") else "")
            + f" — {it.get('text', '')}"
        ),
    )
    param_lines = _join(
        struct.get("core_params"),
        lambda i, it: f"  {i}. **{it.get('label', '')}**：{it.get('text', '')}",
    )
    faq_lines = _join(
        struct.get("faq"),
        lambda i, it: (
            f"  {i}. **Q：{it.get('q', '')}**\n"
            f"     A：{it.get('a', '')}"
        ),
    )
    demo_lines = _join(
        struct.get("demo_actions"),
        lambda i, it: f"  {i}. **{it.get('label', '')}** — {it.get('text', '')}",
    )

    text = (
        f"**产品手册：{hb.get('name')}**（version v{hb.get('version_no', 1)} · "
        f"status={hb.get('status', 'ready')}）\n\n"
        "本手册是你本场对话的**销冠剧本**，与上方“产品事实卡”同为最高优先级。\n"
        "**你必须严格按本手册口径回答**：卖点要照搬卖点表述，参数要对齐参数表，"
        "FAQ 出现时优先用手册标准答案，演示动作要主动引导客户体验。\n\n"
        + (f"### ① 一句话定位\n{intro_text}\n\n" if intro_text else "")
        + f"### ③ 三大核心卖点\n{sell_lines}\n\n"
        + f"### ③ 三大竞品差异\n{comp_lines}\n\n"
        + f"### ⑤ 五大核心参数\n{param_lines}\n\n"
        + f"### ⑨ 九大 FAQ\n{faq_lines}\n\n"
        + f"### ⑩ 十大演示动作\n{demo_lines}\n\n"
        + "⚠️ **铁律**：\n"
        + "- 客户的问题命中上述任何一项时，**必须**引用该项原文/数字，不得自由发挥；\n"
        + "- 客户问到的内容不在手册中时，按你的销售经验回答，并坦诚说“这点我帮您当场查官网确认”；\n"
        + "- 严禁说手册明确否定/未授权的内容（含虚构参数、跨产品对比、超出政策的承诺）。"
    )
    meta["handbook_block_len"] = len(text)
    meta["handbook_block_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return text, meta


def _build_handbook_block(state: DialogueState) -> str:
    """Handbook Analysis · 在销冠 prompt 顶部注入 1/3/3/5/9/10 强约束块。

    决策路径（来自用户决策 3 乙 + 决策 4 自动套用）：
      1. state.handbook_id 有显式绑定 → 用之
      2. 否则全库唯一一份 ready Handbook → 自动套用
      3. 否则返回 "未绑定" 提示文本（销冠按通用经验作答）

    渲染口径：
      - 完整列出 1 句话定位 / 3 卖点 / 3 竞品 / 5 参数 / 9 FAQ / 10 演示
      - 强调"必须严格按该手册口径"，作为销冠最高优先级行为约束
      - 任何错误读不到（DB / JSON / Handbook 缺字段）都降级为提示而非崩溃

    本函数等价于 _build_handbook_block_with_meta(state)[0]，保留是为了
    向后兼容现有调用点；新代码请优先使用带 meta 的版本以拿到签名。
    """
    return _build_handbook_block_with_meta(state)[0]


def _build_product_fact_card_block(state: DialogueState) -> str:
    """v0.2.2 真实性补丁：渲染产品事实卡 block 注入 sales_prompt。

    没卡（preflight 失败 / 未启用）→ 返回保守提示文本。
    """
    card = getattr(state, "product_fact_card", None)
    if card is None:
        return (
            "**产品事实卡：未生成**   _可信度：UNCERTAIN_\n\n"
            "⚠️ 本场未做产品事实预检 — 你**禁止凭印象编造**任何具体参数 / 价格 / 配色 / 政策。\n"
            "客户问到具体数字一律说：\"我帮您当场打开官网确认\"。"
        )
    if getattr(card, "render_block", ""):
        return card.render_block
    # 兜底：手工拼一个最小卡（理论上 preflight 出的卡都已带 render_block）
    return f"**产品事实卡：{card.product_name}**   _可信度：{card.confidence}_"


def _validate_and_fix_playbook_action(
    strategy: SalesStrategy, stage_id: str
) -> SalesStrategy:
    """销冠如果输出了非法 playbook_action，记日志并清空（不抛错，避免一轮坏掉整场）。"""
    pa = (strategy.playbook_action or "").strip()
    if not pa:
        return strategy
    if not is_valid_playbook_action(stage_id, pa):
        logger.warning(
            "销冠输出 playbook_action=%r 不在 stage=%s 的 allowed 列表里，已清空",
            pa, stage_id,
        )
        strategy.playbook_action = None
    return strategy


def load_prompt(name: str) -> str:
    """加载 prompt 模板。

    Stage 15a 改造：对 ``sales_prompt`` 优先读 ``agent_profiles.system_prompt``
    （UI 在线编辑生效），其他 prompt 继续走 ``prompts/<name>.md`` 文件。
    DB 读取任何异常都安全回退到文件，保证 CLI / 单元测试不依赖 DB。
    """
    if name == "sales_prompt":
        try:
            from src.storage.db import get_agent_profile, get_connection  # 延迟导入
            conn = get_connection()
            try:
                profile = get_agent_profile(conn, "sales")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            if profile and (profile.get("system_prompt") or "").strip():
                return profile["system_prompt"]
        except Exception:
            pass

    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt 模板不存在: {path}。请检查 prompts/ 目录。"
        )
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, variables: dict[str, Any]) -> str:
    """简单字符串替换渲染，占位符格式为 {key}。

    不使用 Python str.format_map 以避免模板里的 JSON 示例中的 {} 被误解析。
    """
    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", str(value) if value is not None else "")
    return result


def _format_history_for_prompt(turns: list[Turn]) -> str:
    """把最近 N 条 Turn 格式化为可读文本注入 Prompt。"""
    if not turns:
        return "（暂无对话记录，这是第一轮）"
    lines = []
    for t in turns[-_MAX_RECENT_HISTORY:]:
        speaker_label = "用户" if t.speaker == "persona" else "销冠"
        lines.append(f"{speaker_label}：{t.content}")
    return "\n".join(lines)


def _format_session_memory(state: DialogueState) -> str:
    """把 SessionMemory 格式化为 JSON 字符串注入 Prompt。"""
    mem = state.session_memory
    if not any([
        mem.current_need,
        mem.main_objections,
        mem.budget_boundary,
        mem.do_not_repeat,
    ]):
        return "（会话画像尚未建立，这是对话初期）"
    return safe_json_dumps(mem.model_dump())


def _format_judge_instruction(state: DialogueState, role: str) -> str:
    """从 judge_feedback 中取对应角色的指令。"""
    fb = state.judge_feedback
    if role == "persona":
        return fb.persona_instruction or "按人设自然表达你的需求和顾虑。"
    return fb.sales_instruction or "回应用户当前问题，必要时追问需求。"


def _format_avoid_repeating(state: DialogueState) -> str:
    """格式化 avoid_repeating 列表。"""
    items = state.judge_feedback.avoid_repeating or []
    if not items:
        return "（暂无限制）"
    return "\n".join(f"- {item}" for item in items)


def _now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _make_fallback_turn(
    idx: int,
    speaker: SpeakerType,
    raw_output: str,
    error: str,
) -> Turn:
    """LLM 解析彻底失败时的兜底 Turn，保留对话流程，不让整场崩溃。"""
    content = (
        f"（系统提示：本轮 {speaker} 响应解析失败，原始输出已记录在 metadata 中）"
    )
    return Turn(
        idx=idx,
        speaker=speaker,
        content=content,
        metadata={"parse_error": error, "raw_output": raw_output[:500]},
        created_at=_now_str(),
    )


def _build_structured_persona_text(persona) -> str:
    """structured 模式：把结构化字段拼成可读画像文本。"""
    return (
        f"姓名：{persona.name}\n"
        f"年龄：{persona.age or '未知'}\n"
        f"职业：{persona.occupation or '未知'}\n"
        f"预算：{persona.budget or '未知'}\n"
        f"性格：{persona.personality}\n"
        f"痛点：{chr(10).join('- ' + p for p in persona.pain_points)}\n"
        f"异议风格：{persona.objection_style}\n"
        f"购买目标：{persona.purchase_goal}"
    )


_OPENING_SYSTEM = (
    "你是线下数码门店的资深导购，正在迎接一位刚走进店里的顾客。"
    "你只需要说一句自然、亲切、口语化的开场招呼，把对方引进话题——"
    "不要报参数 / 价格、不要推销具体型号、不要长篇大论、不要列举卖点。"
)


def generate_opening_line(state: DialogueState) -> str:
    """销售先开口时，用 LLM 现场生成一句开场招呼（随会话语言切换）。

    设计：开场白不再写死中文模板，而是让 LLM 按本场 ``state.language``
    自然生成；选英语就出英文招呼、选中文就出中文招呼。

    失败安全：任何异常都回退到 ``OPENING_TEMPLATES[0]``。
    """
    from src.session import OPENING_TEMPLATES

    system_prompt = _OPENING_SYSTEM + lang_instruction(state.language, role="sales")
    user_prompt = (
        f"销售话题：{state.topic}\n"
        "请只输出一句开场招呼（顾客刚进店时你说的第一句话）。\n"
        '严格 JSON：{"opening": "你的开场招呼"}'
        + lang_instruction(state.language, role="sales")
    )
    try:
        from src.llm import LLMOverride, with_llm_override
        with with_llm_override(LLMOverride(thinking_mode="disabled")):
            raw = call_llm_json(system_prompt, user_prompt, temperature=0.7)
        text = (raw.get("opening") or "").strip()
        if text:
            return text
    except (LLMCallError, LLMJsonParseError) as exc:
        console.print(f"[yellow]开场白生成失败，回退模板：{exc}[/yellow]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]开场白生成异常，回退模板：{exc}[/yellow]")
    return OPENING_TEMPLATES[0]


def generate_persona_turn(state: DialogueState) -> Turn:
    """调用 Persona Agent，生成用户这轮发言。

    按 persona.format_type 分流：
    - structured（YAML/MVP）：用 persona_prompt.md，注入拼接的结构化画像
    - prompt_based（panel/上传/生成）：用 persona_prompt_v2.md，
      直接把 prompt_text 作为角色主体，pressure 仅作隐性约束
    """
    persona = state.persona_profile
    fmt = getattr(persona, "format_type", "structured")

    phase_pack = _phase_pack(state, "persona")
    stage_pack = _stage_pack(state)  # v0.3：把 v10.1/10.2 stage 字段也喂给 persona

    base_vars = {
        "pressure_profile": persona.pressure_profile.summary(),
        "topic": state.topic,
        "stage": state.current_stage or "开场与需求暴露",
        "round_idx": state.round_idx,
        "max_rounds": state.max_rounds,
        "persona_instruction": _format_judge_instruction(state, "persona"),
        "session_memory": _format_session_memory(state),
        "recent_history": _format_history_for_prompt(state.recent_history),
        # Stage 15c：把语言指令注入到 user_prompt 末尾，位置离 LLM 生成最近，
        # 优先级高于 system_prompt（覆盖 persona 人设里的隐含语言倾向）
        "language_directive": lang_instruction(state.language, role="persona"),
        **phase_pack,
        **stage_pack,
    }

    if fmt == "prompt_based" and getattr(persona, "prompt_text", None):
        template = load_prompt("persona_prompt_v2")
        variables = {**base_vars, "prompt_text": persona.prompt_text}
    else:
        template = load_prompt("persona_prompt")
        variables = {
            **base_vars,
            "persona_profile": _build_structured_persona_text(persona),
        }

    system_prompt = (
        "你是销售模拟系统中的用户人设 Agent。严格按照给定画像和规则扮演用户。"
        + lang_instruction(state.language, role="persona")
    )
    user_prompt = render_prompt(template, variables)

    turn_idx = state.round_idx
    try:
        # Persona = 用户角色扮演，单轮 JSON 输出，不需要 thinking 模式（也不应该开，
        # 因为 V4-Pro 默认开 thinking 会让 reasoning_tokens 飙升、成本无端翻倍）。
        from src.llm import LLMOverride, with_llm_override
        with with_llm_override(LLMOverride(thinking_mode="disabled")):
            raw = call_llm_json(system_prompt, user_prompt, temperature=0.8)
    except (LLMCallError, LLMJsonParseError) as exc:
        console.print(f"[red]Persona Agent 调用失败 (round {turn_idx}):[/red] {exc}")
        raw_out = exc.raw_output if isinstance(exc, LLMJsonParseError) else ""
        return _make_fallback_turn(turn_idx, "persona", raw_out, str(exc))

    content = raw.get("content", "")
    hidden_raw = raw.get("hidden_state", {})
    try:
        hidden = HiddenState.model_validate(hidden_raw)
    except Exception:
        hidden = HiddenState()

    return Turn(
        idx=turn_idx,
        speaker="persona",
        content=content,
        metadata=hidden.model_dump(),
        created_at=_now_str(),
    )


def generate_sales_turn(state: DialogueState) -> Turn:
    """调用 Sales Champion Agent，生成销冠这轮回应（含 model_override 注入）。

    Stage 15a Phase B-2 增强：
      在进入实际生成前，读 ``agent_profiles.sales.model_override``，并用
      :func:`src.llm.with_llm_override` 包住整段调用，让销冠这轮（含工具循环、
      含失败 fallback）使用销冠专属的 provider / temperature / max_tokens。
      任何读 DB 失败都安全回退到全局默认。

    V4-Pro 兼容性补丁：
      销售调用是「多轮工具循环」路径，DeepSeek V4-Pro 服务端默认开启 thinking，
      会强制要求历史 assistant message 含 ``reasoning_content``，否则 400。
      官方又明确：thinking mode 不支持 function calling。
      因此销售路径**永远显式 thinking_mode="disabled"**（除非 DB 显式覆盖为 enabled）。
    """
    from src.llm import LLMOverride, with_llm_override

    override = _read_sales_override_silent() or LLMOverride()
    if override.thinking_mode is None:
        override.thinking_mode = "disabled"
    with with_llm_override(override):
        return _generate_sales_turn_impl(state)


def _read_sales_override_silent() -> Optional[Any]:
    """从 ``agent_profiles.sales.model_override`` 构造 LLMOverride，失败返回 None。"""
    try:
        from src.llm import LLMOverride
        from src.storage.db import get_agent_profile, get_connection
        conn = get_connection()
        try:
            profile = get_agent_profile(conn, "sales")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if not profile:
            return None
        mo = profile.get("model_override") or {}
        if not isinstance(mo, dict):
            return None
        provider_id = mo.get("provider_id")
        model = mo.get("model")
        temperature = mo.get("temperature")
        max_tokens = mo.get("max_tokens")
        # 全空 → 不需要覆盖，省去开销
        if (
            provider_id in (None, "", 0)
            and not model
            and temperature in (None, "")
            and not max_tokens
        ):
            return None
        return LLMOverride(
            provider_id=int(provider_id) if provider_id else None,
            model=str(model) if model else None,
            temperature=float(temperature) if temperature not in (None, "") else None,
            max_tokens=int(max_tokens) if max_tokens else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("读销冠 model_override 失败，回退全局默认：%s", exc)
        return None


def _generate_sales_turn_impl(state: DialogueState) -> Turn:
    """销冠 turn 实际生成逻辑（不含 override 包装），保持原 Stage 6b/14 行为。"""
    # Stage 14：tool-use 分流（任何异常都 fallback 到老路径）
    try:
        skills_cfg = _load_agent_skills_cfg_silent()
    except Exception:
        skills_cfg = None
    if skills_cfg and skills_cfg.get("enabled_tools"):
        try:
            return _generate_sales_turn_with_tools(state, skills_cfg)
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"[yellow]tool-use 路径异常，降级到普通 RAG 路径: {exc}[/yellow]"
            )

    template = load_prompt("sales_prompt")

    # ── 1. RAG 检索 ────────────────────────────────────────────────
    rag_query = _build_rag_query(state)
    product_hits = _fetch_kb_hits(
        state.product_kb_id, "product", rag_query, _RAG_TOP_K_PRODUCT,
    )
    enterprise_hits = _fetch_kb_hits(
        state.enterprise_kb_id, "enterprise", rag_query, _RAG_TOP_K_ENTERPRISE,
    )

    # ── 2. Stage 15c 修订：取消"任何话题都强行注入 data/product.md"的兜底 ──
    # 旧版会无脑把 state.product_text（学习平板）灌给销冠，结果用户选"手机销售"
    # 话题时销冠依然在聊平板。新行为：若 product KB 未选或命中为 0，仅给销冠
    # 一段"提示语"（在下面 _format_hits_for_prompt 的 empty_text 里），让他
    # 凭通用销售经验作答，或自行调用 web_search 等工具检索。
    product_fallback_used = False

    # ── 3. 渲染 prompt ─────────────────────────────────────────────
    phase_pack = _phase_pack(state, "sales")
    stage_pack = _stage_pack(state)
    _market_facts_text = _build_market_facts_block(state)

    rounds_left = max(0, state.max_rounds - state.round_idx)
    variables = {
        "brand_profile_block": _build_brand_profile_block(state),
        "topic": state.topic,
        "sales_context": _infer_sales_context(state.topic),
        "tool_status": _tool_status_summary(tools_enabled=None),
        "stage": state.current_stage or "开场与需求暴露",
        "round_idx": state.round_idx,
        "max_rounds": state.max_rounds,
        "rounds_left": rounds_left,
        "product_hits": _format_hits_for_prompt(
            product_hits,
            empty_text=(
                "（产品知识库内无与本场话题相关的命中。请按以下顺序处理：\n"
                "  1) 若你对话题中的产品有通用常识把握，可直接基于通用经验作答；\n"
                "  2) 涉及具体规格 / 价格 / 政策时，明确告诉客户「我帮您确认」"
                "，绝不要编造数字；\n"
                "  3) 不要把对话引到知识库里其他不相关的产品上。）"
            ),
        ),
        "enterprise_hits": _format_hits_for_prompt(
            enterprise_hits,
            empty_text="（暂无企业方法论参考：靠你的销售经验回应）",
        ),
        "session_memory": _format_session_memory(state),
        "sales_instruction": _format_judge_instruction(state, "sales"),
        "avoid_repeating": _format_avoid_repeating(state),
        "recent_history": _format_history_for_prompt(state.recent_history),
        "language_directive": lang_instruction(state.language, role="sales"),
        "product_fact_card_block": _build_product_fact_card_block(state),
        "market_facts_block": _market_facts_text,
        **phase_pack,
        **stage_pack,
    }

    _hb_block_text, _hb_block_meta = _build_handbook_block_with_meta(state)
    variables["handbook_block"] = _hb_block_text

    system_prompt = (
        "你是销售模拟系统中的销冠 Agent。严格按照给定规则和检索结果扮演销冠。"
        + lang_instruction(state.language, role="sales")
    )
    user_prompt = render_prompt(template, variables)

    # ── 4. 调 LLM ──────────────────────────────────────────────────
    turn_idx = state.round_idx
    try:
        raw = call_llm_json(system_prompt, user_prompt, temperature=0.6)
    except (LLMCallError, LLMJsonParseError) as exc:
        console.print(f"[red]Sales Agent 调用失败 (round {turn_idx}):[/red] {exc}")
        raw_out = exc.raw_output if isinstance(exc, LLMJsonParseError) else ""
        return _make_fallback_turn(turn_idx, "sales", raw_out, str(exc))

    content = raw.get("content", "")
    strategy_raw = raw.get("strategy", {})
    try:
        strategy = SalesStrategy.model_validate(strategy_raw)
    except Exception:
        strategy = SalesStrategy()
    strategy = _validate_and_fix_playbook_action(strategy, stage_pack["current_stage_id"])

    # ── 5. RAG 命中元数据写入 turn ──────────────────────────────────
    used_product_kb = [h["id"] for h in product_hits if h.get("id") and not product_fallback_used]
    used_enterprise_kb = [h["id"] for h in enterprise_hits if h.get("id")]
    rag_hits_payload = {
        "query": rag_query[:200],
        "product": [_compact_hit(h) for h in product_hits],
        "enterprise": [_compact_hit(h) for h in enterprise_hits],
        "product_fallback": product_fallback_used,
    }

    metadata = strategy.model_dump()
    metadata["used_product_kb"] = used_product_kb
    metadata["used_enterprise_kb"] = used_enterprise_kb
    metadata["rag_hits"] = rag_hits_payload
    metadata["stage_id"] = stage_pack["current_stage_id"]
    metadata["handbook_inject"] = _hb_block_meta

    # v0.2.2 真实性补丁 Layer B：销冠出口前过一道 content_guard 改写
    # v0.2.3：必须把 Handbook 文本作为强证据源传入，否则 Handbook 里写明的
    # 价格 / 屏幕尺寸 / 续航等数字会被 guard 当成"未证实"全部改写。
    content, guard_warnings = _run_content_guard(
        content,
        state=state,
        tool_calls=None,  # 无工具路径
        handbook_text=_hb_block_text,
        market_facts_text=_market_facts_text,
        kb_evidence_text="\n".join(
            str(variables.get(k) or "") for k in ("product_hits", "enterprise_hits")
        ),
    )
    if guard_warnings:
        metadata["content_guard"] = {
            "rewritten": True,
            "warnings": guard_warnings,
        }

    return Turn(
        idx=turn_idx,
        speaker="sales",
        content=content,
        metadata=metadata,
        created_at=_now_str(),
    )


def _run_content_guard(
    content: str,
    *,
    state: DialogueState,
    tool_calls: Optional[list[dict[str, Any]]],
    handbook_text: Optional[str] = None,
    market_facts_text: Optional[str] = None,
    kb_evidence_text: Optional[str] = None,
) -> tuple[str, list[str]]:
    """对销冠最终输出文本执行 content_guard 改写。永不抛。

    v0.2.3：必须传 ``handbook_text``（本轮注入到 prompt 的 Handbook 全文），
    否则 guard 会把 Handbook 里明确写的价格 / 参数当成"未证实"全部改写，
    导致销冠话术全废。

    v0.2.5（价格放行）：把销冠在 prompt 里看到的 KB 召回文本
    （product_hits / enterprise_hits）一并作为强证据传入——产品知识库里
    已有的价格 / 参数应直接放行，不应被改写成降级话术。
    """
    try:
        from src.content_guard import verify_and_rewrite

        extra_pieces = [p for p in (market_facts_text, kb_evidence_text) if p]
        extra_evidence_text = "\n".join(extra_pieces) if extra_pieces else None

        new_text, warnings = verify_and_rewrite(
            content,
            fact_card=getattr(state, "product_fact_card", None),
            tool_calls=tool_calls,
            handbook_text=handbook_text,
            extra_evidence_text=extra_evidence_text,
        )
        if warnings:
            preview = " | ".join(warnings[:3])
            console.print(f"[yellow]content_guard 改写 {len(warnings)} 处：[/yellow]{preview}")
        return new_text, warnings
    except Exception as exc:  # noqa: BLE001
        logger.warning("_run_content_guard 失败（保留原文）：%s", exc)
        return content, []


def _compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """RAG hit 的紧凑表示（用于 turn.metadata 持久化 + 前端展示）。

    去掉冗余字段、限制文本长度，避免 metadata 膨胀。
    """
    meta = hit.get("metadata") or {}
    return {
        "id": hit.get("id"),
        "text": (hit.get("text") or "")[:_RAG_CHUNK_TEXT_LIMIT],
        "score": hit.get("score"),
        "filename": meta.get("filename"),
        "section": meta.get("section"),
        "file_id": meta.get("file_id"),
        "kb_id": meta.get("kb_id"),
        "kb_type": meta.get("kb_type"),
    }


# ============================================================
# Stage 14：tool-use 循环（Sales Agent 自主调用工具版本）
# ============================================================


_TOOL_RESULT_TEXT_LIMIT = 3000  # 单条 tool 返回给 LLM 的字符上限，避免上下文爆炸
_TOOL_LOOP_HARD_MAX = 8         # 即使 cfg.max_tool_loops 调到很大也再卡一层硬上限


def _load_agent_skills_cfg_silent() -> Optional[dict[str, Any]]:
    """读取 agent_skills_config。任何异常（DB 不存在 / 表未建）返回 None。"""
    try:
        from src.storage.db import get_agent_skills_config, get_connection  # 延迟导入
    except Exception:
        return None
    try:
        conn = get_connection()
    except Exception:
        return None
    try:
        return get_agent_skills_config(conn)
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _build_tool_context(state: DialogueState) -> Any:
    """从 DialogueState 拼一个 ToolContext，供工具运行时用。

    v0.2.1 真实性补丁：把 persona 的 country_code / currency / market_domains
    塞进 ToolContext，让 web_search 工具能强制 include_domains。
    """
    from src.tools.registry import ToolContext
    from src.locales import get_market

    persona = state.persona_profile  # PersonaProfile
    persona_id: Optional[int] = None
    try:
        # PersonaProfile.id 是 str；DB 主键是 int。能转就转，不能转就忽略。
        persona_id = int(persona.id) if persona and getattr(persona, "id", None) else None
    except (TypeError, ValueError):
        persona_id = None

    # 取 persona 上的显式字段；缺失则用 locales.get_market 兜底（GLOBAL 站点）
    p_cc = (getattr(persona, "country_code", None) or "").strip() or None
    p_cur = (getattr(persona, "currency", None) or "").strip() or None
    p_name = (getattr(persona, "country_name", None) or "").strip() or None
    p_domains = list(getattr(persona, "market_domains", []) or [])
    if not p_domains:
        # 没显式 domains → 用 country_code 查 registry；再没有就用全球
        mkt = get_market(p_cc)
        p_domains = list(mkt.market_domains)
        if not p_cur:
            p_cur = mkt.currency
        if not p_name:
            p_name = mkt.name_cn
        if not p_cc and mkt.code != "GLOBAL":
            p_cc = mkt.code

    return ToolContext(
        product_kb_id=state.product_kb_id,
        enterprise_kb_id=state.enterprise_kb_id,
        session_id=state.session_id,
        persona_id=persona_id,
        persona_country_code=p_cc,
        persona_country_name=p_name,
        persona_currency=p_cur,
        persona_market_domains=p_domains,
        extra={"topic": state.topic, "round_idx": state.round_idx},
    )


def _truncate_tool_result(payload: Any) -> str:
    """tool result → 文本，截断到 _TOOL_RESULT_TEXT_LIMIT 以内。"""
    try:
        s = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        s = str(payload)
    if len(s) > _TOOL_RESULT_TEXT_LIMIT:
        s = s[:_TOOL_RESULT_TEXT_LIMIT] + "…(truncated)"
    return s


def _generate_sales_turn_with_tools(
    state: DialogueState,
    skills_cfg: dict[str, Any],
) -> Turn:
    """Stage 14 tool-use 路径。

    流程：
    1. 渲染 prompt（不预先做 RAG 注入，product_hits/enterprise_hits 占位用提示替换）；
    2. 调 LLM，带 tools=enabled_tools；
    3. 若返回 tool_calls，逐个执行，把 result append 为 tool message，再调；
    4. 循环至无 tool_calls 或达到 max_loops；
    5. 最后一轮强制 tool_choice="none" + JSON 输出，得到 final content + strategy；
    6. tool_calls 全程记录到 turn.metadata.tool_calls 用于前端可视化。
    """
    from src.tools.registry import (
        get_enabled_tools,
        get_tool_schemas,
        run_tool_safe,
    )

    enabled_names: list[str] = list(skills_cfg.get("enabled_tools") or [])
    max_loops = int(skills_cfg.get("max_tool_loops") or 3)
    max_loops = max(1, min(max_loops, _TOOL_LOOP_HARD_MAX))

    enabled_entries = get_enabled_tools(enabled_names)
    if not enabled_entries:
        # 启用列表里全是未知工具 → 抛回外层 fallback
        raise RuntimeError("启用列表中无任何已注册工具")

    tools_schema = get_tool_schemas(enabled_names)
    tool_ctx = _build_tool_context(state)
    turn_idx = state.round_idx

    # ── 1. 渲染 prompt（不预 RAG，留给工具自己取） ──
    template = load_prompt("sales_prompt")
    phase_pack = _phase_pack(state, "sales")
    stage_pack = _stage_pack(state)
    _market_facts_text = _build_market_facts_block(state)
    _brand_profile_text = _build_brand_profile_block(state)
    tool_hint_text = (
        "（本轮已启用工具自助检索：" + "、".join(e.name for e in enabled_entries) +
        "。请你按需调用工具检索后再正式回复客户。)"
    )
    variables = {
        "brand_profile_block": _brand_profile_text,
        "topic": state.topic,
        "sales_context": _infer_sales_context(state.topic),
        "tool_status": _tool_status_summary(
            tools_enabled=[e.name for e in enabled_entries],
            web_search_available=_is_web_search_available()
            if "web_search" in [e.name for e in enabled_entries] else None,
        ),
        "stage": state.current_stage or "开场与需求暴露",
        "round_idx": state.round_idx,
        "max_rounds": state.max_rounds,
        "rounds_left": max(0, state.max_rounds - state.round_idx),
        "product_hits": tool_hint_text,
        "enterprise_hits": tool_hint_text,
        "session_memory": _format_session_memory(state),
        "sales_instruction": _format_judge_instruction(state, "sales"),
        "avoid_repeating": _format_avoid_repeating(state),
        "recent_history": _format_history_for_prompt(state.recent_history),
        "language_directive": lang_instruction(state.language, role="sales"),
        "product_fact_card_block": _build_product_fact_card_block(state),
        "market_facts_block": _market_facts_text,
        **phase_pack,
        **stage_pack,
    }
    _hb_block_text, _hb_block_meta = _build_handbook_block_with_meta(state)
    variables["handbook_block"] = _hb_block_text
    system_prompt = (
        "你是销售模拟系统中的销冠 Agent。你被赋予了若干可调用的检索工具。"
        "请在确实需要的时候调用工具（不要为了用而用），用完工具后必须严格按 JSON schema "
        '{"content": str, "strategy": {...}} 输出最终回复。'
        + lang_instruction(state.language, role="sales")
    )
    user_prompt = render_prompt(template, variables)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    tool_calls_log: list[dict[str, Any]] = []

    # ── 2. tool-use 循环 ──
    final_message = None
    for loop_idx in range(max_loops):
        try:
            msg = call_llm_with_tools(
                messages,
                tools=tools_schema,
                temperature=0.6,
            )
        except LLMCallError as exc:
            console.print(
                f"[red]Sales Agent tool-loop 调用失败 (round {turn_idx}, loop {loop_idx}):"
                f"[/red] {exc}"
            )
            return _make_fallback_turn(turn_idx, "sales", "", str(exc))

        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            final_message = msg
            break

        # 把 assistant 消息（含 tool_calls）追加进 messages，否则 OpenAI 协议会报错
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        # 执行每个工具调用
        for tc in tool_calls:
            t_name = tc.function.name
            t_args_raw = tc.function.arguments or "{}"
            try:
                t_args = json.loads(t_args_raw)
                if not isinstance(t_args, dict):
                    raise ValueError("arguments 不是 JSON object")
            except Exception as exc:
                t_args = {}
                t_result = {"ok": False, "error": f"参数解析失败: {exc}; raw={t_args_raw[:200]}"}
            else:
                t_result = run_tool_safe(t_name, t_args, tool_ctx)

            result_text = _truncate_tool_result(t_result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": t_name,
                "content": result_text,
            })
            # 直接存储结构化 data，避免截断 JSON 导致后续解析失败
            _t_ok = bool(t_result.get("ok")) if isinstance(t_result, dict) else True
            _t_data = t_result.get("data") if isinstance(t_result, dict) else None
            tool_calls_log.append({
                "loop": loop_idx,
                "name": t_name,
                "arguments": t_args,
                "result_preview": result_text[:800],
                "result_data": _t_data,
                "ok": _t_ok,
            })

    # ── 3. 收尾：若循环用尽仍在调工具，强制 tool_choice=none + JSON 输出 ──
    if final_message is None:
        try:
            final_message = call_llm_with_tools(
                messages
                + [{
                    "role": "user",
                    "content": (
                        "工具调用预算已用完，请基于上面工具返回的内容，"
                        '严格输出 JSON：{"content": "...", "strategy": {...}}。'
                    ),
                }],
                tools=tools_schema,
                temperature=0.6,
                response_format_json=True,
                tool_choice="none",
            )
        except LLMCallError as exc:
            return _make_fallback_turn(turn_idx, "sales", "", str(exc))

    # ── 4. 解析 final content/strategy ──
    final_content_raw = (final_message.content or "").strip()
    parsed: dict[str, Any]
    try:
        parsed = extract_json(final_content_raw)
        if not isinstance(parsed, dict):
            raise ValueError("最终输出不是 JSON object")
    except Exception:
        # 再补救一次：要求重新输出 JSON
        try:
            retry_msg = call_llm_with_tools(
                messages
                + [{
                    "role": "user",
                    "content": (
                        '请只输出 JSON 对象：{"content": "...", "strategy": {...}}，'
                        "不要解释、不要 markdown 代码块。"
                    ),
                }],
                tools=None,
                temperature=0.3,
                response_format_json=True,
            )
            parsed = extract_json((retry_msg.content or "").strip())
            if not isinstance(parsed, dict):
                raise ValueError("retry 仍非 JSON object")
        except Exception as exc:
            console.print(
                f"[red]Sales tool-use 最终 JSON 解析失败 (round {turn_idx}): {exc}[/red]"
            )
            return _make_fallback_turn(turn_idx, "sales", final_content_raw[:500], str(exc))

    content = parsed.get("content", "") or ""
    strategy_raw = parsed.get("strategy", {}) or {}
    try:
        strategy = SalesStrategy.model_validate(strategy_raw)
    except Exception:
        strategy = SalesStrategy()
    strategy = _validate_and_fix_playbook_action(strategy, stage_pack["current_stage_id"])

    metadata = strategy.model_dump()
    # 兼容老 schema：保留 used_*_kb / rag_hits 字段
    used_product = []
    used_enterprise = []
    rag_product: list[dict[str, Any]] = []
    rag_enterprise: list[dict[str, Any]] = []
    for c in tool_calls_log:
        if not c.get("ok"):
            continue
        # 优先用 result_data（结构化，无截断风险）；旧日志回退到解析 result_preview
        data = c.get("result_data")
        if not isinstance(data, dict):
            try:
                payload = json.loads(c.get("result_preview") or "")
                data = (payload or {}).get("data") if isinstance(payload, dict) else None
            except Exception:
                data = None
        if not isinstance(data, dict):
            continue
        hits = data.get("hits") or []
        if c["name"] == "search_product_kb":
            for h in hits:
                if h.get("id"):
                    used_product.append(h["id"])
                rag_product.append({
                    "id": h.get("id"),
                    "text": h.get("text", ""),
                    "filename": h.get("filename"),
                    "section": h.get("section"),
                    "score": h.get("score"),
                })
        elif c["name"] == "search_enterprise_kb":
            for h in hits:
                if h.get("id"):
                    used_enterprise.append(h["id"])
                rag_enterprise.append({
                    "id": h.get("id"),
                    "text": h.get("text", ""),
                    "filename": h.get("filename"),
                    "section": h.get("section"),
                    "score": h.get("score"),
                })

    metadata["used_product_kb"] = used_product
    metadata["used_enterprise_kb"] = used_enterprise
    metadata["rag_hits"] = {
        "query": "(via tools)",
        "product": rag_product,
        "enterprise": rag_enterprise,
        "product_fallback": False,
    }
    metadata["tool_calls"] = tool_calls_log
    metadata["tool_mode"] = "function_call"
    metadata["stage_id"] = stage_pack["current_stage_id"]
    metadata["handbook_inject"] = _hb_block_meta

    # v0.2.2 真实性补丁 Layer B：销冠出口前过一道 content_guard 改写
    # 工具路径把本轮 tool_calls 一并喂给 guard，作为"已证实证据"
    # v0.2.3：同时把 Handbook 文本作为强证据源传入（详见 _run_content_guard 文档）
    content, guard_warnings = _run_content_guard(
        content,
        state=state,
        tool_calls=[
            {"name": c["name"], "result": _safe_json_load(c.get("result_preview", ""))}
            for c in tool_calls_log
            if c.get("ok")
        ],
        handbook_text=_hb_block_text,
        market_facts_text=_market_facts_text,
    )
    if guard_warnings:
        metadata["content_guard"] = {
            "rewritten": True,
            "warnings": guard_warnings,
        }

    return Turn(
        idx=turn_idx,
        speaker="sales",
        content=content,
        metadata=metadata,
        created_at=_now_str(),
    )


def _safe_json_load(s: str) -> Any:
    """安全 json.loads；失败返回原字符串。"""
    try:
        return json.loads(s)
    except Exception:
        return s
