"""核心数据结构定义。

设计分两类：
- 严格校验类（PersonaProfile / PressureProfile）：人工编写的输入，必填字段强校验。
- LLM 输出类（Turn / SessionMemory / JudgeFeedback / CoachReview）：模型输出，
  允许字段缺失或额外字段，使用宽松解析 + 默认值兜底，避免一次 LLM 抖动毁掉整场对话。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


SpeakerType = Literal["persona", "sales"]
# Stage 5.5：新增 COMPLAINT（服务/态度类投诉），让早结束机制可分类描述
StatusType = Literal[
    "CONTINUE", "DEAL_DONE", "WALK_AWAY", "FOLLOW_UP", "TIMEOUT", "COMPLAINT"
]
FirstSpeakerType = Literal["sales", "persona"]


class PressureProfile(BaseModel):
    """用户压力参数，9 维全部 0-1 之间。"""

    model_config = ConfigDict(extra="forbid")

    price_sensitivity: float = Field(..., ge=0.0, le=1.0)
    trust_threshold: float = Field(..., ge=0.0, le=1.0)
    patience: float = Field(..., ge=0.0, le=1.0)
    competitor_awareness: float = Field(..., ge=0.0, le=1.0)
    decision_power: float = Field(..., ge=0.0, le=1.0)
    emotion_volatility: float = Field(..., ge=0.0, le=1.0)
    need_urgency: float = Field(..., ge=0.0, le=1.0)
    skepticism: float = Field(..., ge=0.0, le=1.0)
    bargaining_aggressiveness: float = Field(..., ge=0.0, le=1.0)

    def summary(self) -> str:
        """一行紧凑摘要，便于注入 Prompt。"""
        return (
            f"price_sensitivity={self.price_sensitivity}, "
            f"trust_threshold={self.trust_threshold}, "
            f"patience={self.patience}, "
            f"competitor_awareness={self.competitor_awareness}, "
            f"decision_power={self.decision_power}, "
            f"emotion_volatility={self.emotion_volatility}, "
            f"need_urgency={self.need_urgency}, "
            f"skepticism={self.skepticism}, "
            f"bargaining_aggressiveness={self.bargaining_aggressiveness}"
        )


PersonaFormat = Literal["structured", "prompt_based"]


class PersonaProfile(BaseModel):
    """用户人设。

    支持两种来源：
    - structured（MVP 路径）：personas/*.yaml 严格定义全部业务字段。
    - prompt_based（Stage 3+ 路径）：仅靠 prompt_text 完整描述角色，
      其余结构化字段可缺省，由 LLM 直接按 prompt_text 扮演。
    """

    # 允许额外字段，便于上层 DB 行带 created_at 等元数据时直接构造，
    # 同时不破坏 MVP YAML 加载（YAML 字段是子集）。
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    age: Optional[int] = None
    occupation: Optional[str] = None
    budget: Optional[Any] = None

    # structured 模式必填，prompt_based 模式给出占位默认值即可
    personality: str = ""
    pain_points: List[str] = Field(default_factory=list)
    objection_style: str = ""
    purchase_goal: str = ""
    pressure_profile: PressureProfile = Field(
        default_factory=lambda: PressureProfile(
            price_sensitivity=0.5,
            trust_threshold=0.5,
            patience=0.5,
            competitor_awareness=0.5,
            decision_power=0.5,
            emotion_volatility=0.5,
            need_urgency=0.5,
            skepticism=0.5,
            bargaining_aggressiveness=0.5,
        )
    )

    # Stage 3 新增：双格式 + 标签 + 区域
    format_type: PersonaFormat = "structured"
    prompt_text: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    locale: str = "zh-CN"
    source: Optional[str] = None

    # business_stages v0.2.1 真实性 / 地区一致性补丁：
    # 把"客户所在国家 / 货币 / 可信信源域名"作为结构化字段，让 sales_prompt / web_search / Judge
    # 都能拿到。优先级：persona.country_code 显式 > 由 locales.infer_market 自动推断 > 全球兜底。
    # 全部 Optional，老 persona 不强制迁移；新 persona / 编辑时 UI 暴露。
    country_code: Optional[str] = None         # ISO-3166-1 alpha-2，如 "MY" / "PH" / "CN"
    country_name: Optional[str] = None         # 显示名，如 "马来西亚 / Malaysia"
    currency: Optional[str] = None             # ISO-4217，如 "MYR" / "PHP" / "CNY"
    # 该国家可信信源域名清单（华为官网 + 本地电商 + 必要时本地 tech 媒体）。
    # web_search 工具会强制只允许这些域名（strict_local），sales_prompt 也会列出来。
    market_domains: List[str] = Field(default_factory=list)


class HiddenState(BaseModel):
    """Persona Turn 的隐式状态标签。"""

    model_config = ConfigDict(extra="allow")

    intent: Optional[str] = None
    attitude: Optional[str] = None
    purchase_signal: float = 0.0
    status: StatusType = "CONTINUE"
    # Stage 5.5：当 status ∈ {WALK_AWAY, COMPLAINT} 时给出原因（"过早推销"/"不被尊重"等）
    walk_away_reason: Optional[str] = None


class SalesStrategy(BaseModel):
    """Sales Turn 的策略标签。"""

    model_config = ConfigDict(extra="allow")

    intent: Optional[str] = None
    used_product_context: bool = False
    # v3 强引用：销冠自报本轮是否引用了 Handbook（卖点 / 竞品 / 参数 / FAQ / 演示）
    # —— 正常情况应当 true，false 是异常信号（Handbook 没起作用）。
    used_handbook: bool = False
    next_action: Optional[str] = None
    # business_stages v0.2 新增：销冠自报本轮使用的剧本动作（必须属于当前 stage 的 allowed_playbook_actions）。
    # 全集见 prompts/business_stages.yaml.playbook_action_catalog。
    # 例如 S2 阶段："spin_problem"；S3 阶段："evidence_3b"；S4 阶段："assumptive_close"。
    playbook_action: Optional[str] = None


class Turn(BaseModel):
    """一轮发言。"""

    model_config = ConfigDict(extra="allow")

    idx: int
    speaker: SpeakerType
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class SessionMemory(BaseModel):
    """当前会话画像记忆。LLM 输出，宽松解析。"""

    model_config = ConfigDict(extra="allow")

    current_need: str = ""
    main_objections: List[str] = Field(default_factory=list)
    budget_boundary: str = ""
    emotional_state: str = ""
    mentioned_competitors: List[str] = Field(default_factory=list)
    decision_constraints: List[str] = Field(default_factory=list)
    do_not_repeat: List[str] = Field(default_factory=list)
    next_best_action: str = ""

    @classmethod
    def empty(cls) -> "SessionMemory":
        return cls()


class SalesScore(BaseModel):
    """Judge 给销冠打分。"""

    model_config = ConfigDict(extra="allow")

    responsiveness: float = 0.0
    specificity: float = 0.0
    evidence_usage: float = 0.0
    objection_handling: float = 0.0
    closing_progress: float = 0.0


class StageTransition(BaseModel):
    """business_stages v0.2 新增：Judge 决策 stage 切换的可解释轨迹。

    用于：
      - 持久化到 session.judge_feedback.stage_transition，供前端阶段进度条显示"S3 ↩ S2"
      - Coach 复盘时识别"哪一轮触发了倒退、原因是什么"
    """

    model_config = ConfigDict(extra="allow")

    from_stage: str = ""           # 进入本轮 Judge 时的 stage id（如 "S2"）
    to_stage: str = ""             # Judge 决定的 next stage id（如 "S3" 或回退 "S2"）
    direction: str = "stay"        # advance / stay / regress 三选一
    machine_check_pass: bool = True
    llm_check_pass: bool = True
    fail_reasons: List[str] = Field(default_factory=list)
    triggered_fail_signal: Optional[str] = None  # 命中的 stage_fail_signal 文本


class JudgeFeedback(BaseModel):
    """Judge Agent 输出。"""

    model_config = ConfigDict(extra="allow")

    should_continue: bool = True
    current_stage: str = ""
    next_stage: str = ""
    dialogue_quality_score: float = 0.0
    sales_score: SalesScore = Field(default_factory=SalesScore)
    persona_instruction: str = ""
    sales_instruction: str = ""
    avoid_repeating: List[str] = Field(default_factory=list)
    end_status: StatusType = "CONTINUE"
    reason: str = ""
    # business_stages v0.2 新增：本轮 Judge 决策出的 stage 切换轨迹（None 表示未做 stage 评估）。
    stage_transition: Optional[StageTransition] = None

    @classmethod
    def empty(cls) -> "JudgeFeedback":
        return cls()


class CoachReview(BaseModel):
    """Coach Agent 输出。extra='allow' 保证未来字段扩展无崩溃。"""

    model_config = ConfigDict(extra="allow")

    # 本次复盘结果分析
    outcome_analysis: str = ""

    # 有效策略列表: [{round, strategy, evidence, why_effective}]
    what_worked: List[Dict[str, Any]] = Field(default_factory=list)

    # 失效操作列表: [{round, strategy, evidence, why_failed}]
    what_failed: List[Dict[str, Any]] = Field(default_factory=list)

    # 对这类用户的新认识
    persona_insight: str = ""

    # 可直接写入培训手册的经验
    key_lessons: List[str] = Field(default_factory=list)

    # 更优话术模板: [{objection, rebuttal_template}]
    suggested_rebuttals: List[Dict[str, Any]] = Field(default_factory=list)

    # 人设压力难度评分 1-10
    difficulty_rating: int = 0
    difficulty_reason: str = ""

    # 可复用策略模式: [{name, condition, example}]
    reusable_tactics: List[Dict[str, Any]] = Field(default_factory=list)


class ProductFactCard(BaseModel):
    """v0.2.2 真实性补丁 — 会话启动前抽取的"产品事实卡"，
    供 sales_prompt / Judge / content_guard 三方共用作 ground-truth。

    设计原则：
      - 字段 **可空**，preflight 拿到什么填什么；统统拿不到 → ``confidence=UNCERTAIN``，
        销冠 prompt 直接降级（本场禁止任何具体参数）。
      - 仅存"可机检的强事实"：定位、是否支持手写笔/折叠、屏幕/电池/芯片/价格区间。
        软描述（卖点话术等）不在此卡，由 RAG 在每轮按需补。
    """

    model_config = ConfigDict(extra="allow")

    product_name: str = ""                       # "Pura X" / "Mate 80 Pro"
    confidence: str = "UNCERTAIN"                # KNOWN / PARTIAL / UNCERTAIN
    # 关键事实点（preflight 能填到一项就是 PARTIAL；全空就是 UNCERTAIN）
    product_category: Optional[str] = None        # "折叠屏手机" / "平板" / "笔记本" 等
    supports_stylus: Optional[bool] = None        # True / False / None=未知
    has_foldable: Optional[bool] = None
    screen_spec: Optional[str] = None             # "6.3 寸 LTPO 120Hz" 等原文片段
    chipset: Optional[str] = None
    battery: Optional[str] = None
    local_price_range: Optional[str] = None       # 带货币符号，如 "RM 4,999 - 5,999"
    is_available_in_market: Optional[bool] = None
    # 用作 Judge fact_grounding 兜底比对：本张卡所引用的所有原始 URL + KB chunk 摘要
    sources: List[str] = Field(default_factory=list)
    # 给 sales_prompt 用的可读 markdown 块（preflight 渲染好直接注入）
    render_block: str = ""


class DialogueState(BaseModel):
    """整场会话的内存状态对象。在多轮主循环中持续被读写。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    topic: str
    product_text: str
    product_summary: str = ""
    persona_profile: PersonaProfile

    # v0.2.2 真实性补丁：会话启动时由 preflight 抽取一次，
    # 注入到 sales_prompt 顶部，并供 Judge / content_guard 复查。
    product_fact_card: Optional[ProductFactCard] = None

    round_idx: int = 0
    max_rounds: int = 20
    current_stage: str = ""
    # business_stages v0.2：S1-S5 阶段 id（与 current_stage 中文名并存）。
    # 旧字段 current_stage 保留给前端和老逻辑使用；新字段 current_stage_id 作为
    # Judge / Sales / Coach 的统一锚点。stage 倒退时 current_stage_id 会真的回退。
    current_stage_id: str = "S1"
    outcome: str = ""

    recent_history: List[Turn] = Field(default_factory=list)
    full_history: List[Turn] = Field(default_factory=list)
    session_memory: SessionMemory = Field(default_factory=SessionMemory.empty)
    judge_feedback: JudgeFeedback = Field(default_factory=JudgeFeedback.empty)
    coach_review: Optional[CoachReview] = None

    # Stage 5.5：渐进式对话引擎参数
    who_speaks_first: FirstSpeakerType = "sales"
    opening_line: str = ""
    # 最小护栏轮数：在该轮次之前禁止任何 end_status != CONTINUE（防过早成交/早撤）
    max_rounds_floor: int = 0

    # Stage 6b：双 KB 接入。None 表示该侧不查 RAG。
    product_kb_id: Optional[int] = None
    enterprise_kb_id: Optional[int] = None

    # Handbook Analysis v2：本场绑定的产品手册（1/3/3/5/9/10 框架），
    # 注入到 sales_prompt 顶部强约束销冠按手册口径回答。None 时按通用销售经验。
    handbook_id: Optional[int] = None

    # Stage 15c：对话语言（BCP-47 子集）。所有 Agent 的 system_prompt
    # 会注入"请用 {language} 进行回应"。默认 zh-CN。
    language: str = "zh-CN"
