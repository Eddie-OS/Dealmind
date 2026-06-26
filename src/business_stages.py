"""business_stages 加载器 / 校验器。

读 ``prompts/business_stages.yaml``，给 Sales / Judge / Coach 提供统一查询接口。

设计原则：
- 单一信息源：所有阶段定义、playbook 词表、weight、gate、倒退策略只写在 YAML 里
- 模块全部失败安全：任何异常（文件缺失、解析错、字段错）都回退到内置默认
- 模块级单例 + 1 秒级 mtime cache：每次读不重复 IO，但用户手工改 YAML 也能秒级生效
- 公共 API 全部走小函数（``get_stage`` / ``get_allowed_actions`` / ``is_valid_transition``），
  不要让上层直接拿原始 dict 自己遍历，否则改 YAML schema 时改不完。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.config import PROJECT_ROOT


logger = logging.getLogger(__name__)


_STAGES_YAML_PATH = PROJECT_ROOT / "prompts" / "business_stages.yaml"

# 五阶段的固定顺序（也是 catalog 在前端展示的顺序）
STAGE_ORDER: List[str] = ["S1", "S2", "S3", "S4", "S5"]


@dataclass
class StageSpec:
    """单个阶段的完整定义（YAML 单条 stage 的 in-memory 视图）。

    v0.3：新增 v10.1/10.2 字段——`required_trigger` / `gate_condition` /
    `persona_logic` / `persona_constraints` / `sales_logic` / `sales_constraints`。
    旧 YAML（v0.2）缺这些字段时为空串，UI / prompt 走默认提示，不破坏向后兼容。
    """

    id: str
    name: str
    cn_name: str
    weight: float
    sales_actions: List[str] = field(default_factory=list)
    sales_must_not: List[str] = field(default_factory=list)
    allowed_playbook_actions: List[str] = field(default_factory=list)
    judge_gate_machine: List[str] = field(default_factory=list)
    judge_gate_llm: List[str] = field(default_factory=list)
    stage_fail_signal: List[str] = field(default_factory=list)

    # v0.3 NEW
    required_trigger: str = ""        # v10.1：导购员核心驱动动作（晋级的唯一触发条件）
    gate_condition: str = ""          # v10.1：消费者阶段流转大闸（Judge 判定的硬条件）
    persona_logic: str = ""           # v10.2：Persona 该阶段的执行逻辑
    persona_constraints: str = ""     # v10.2：Persona 该阶段的行为约束
    sales_logic: str = ""             # v10.2：Sales 该阶段的执行逻辑
    sales_constraints: str = ""       # v10.2：Sales 该阶段的行为约束

    def to_prompt_block(self, *, role: str) -> str:
        """渲染成可注入 prompt 的中文段落。

        role:
          - "sales"  → 仅当前阶段的 actions / must_not / allowed_actions（销冠只看自己当下该做什么）
          - "judge"  → 当前阶段的 judge_gate + fail_signal（裁判按 gate 逐项判断）
          - "coach"  → 完整一段，含 weight，用于复盘配比
        """
        bullets = lambda items: "\n".join(f"- {x}" for x in items) if items else "（无）"
        v3_extra_sales = (
            f"\n\nv10.1 必须发起的核心动作（Required Trigger）：{self.required_trigger}"
            if self.required_trigger else ""
        )
        v3_extra_judge = (
            f"\n\nv10.1 导购员核心驱动动作（required_trigger）：{self.required_trigger}"
            f"\nv10.1 消费者阶段流转大闸（gate_condition）：{self.gate_condition}"
            if (self.required_trigger or self.gate_condition) else ""
        )
        if role == "sales":
            return (
                f"【阶段 {self.id} · {self.cn_name}】\n"
                f"本阶段你应该做的：\n{bullets(self.sales_actions)}\n\n"
                f"本阶段你绝不能做的：\n{bullets(self.sales_must_not)}\n\n"
                f"本阶段允许的 playbook_action（必须选其一填入 strategy.playbook_action）：\n"
                f"{', '.join(self.allowed_playbook_actions) if self.allowed_playbook_actions else '（无）'}"
                f"{v3_extra_sales}"
            )
        if role == "judge":
            return (
                f"【阶段 {self.id} · {self.cn_name}】（weight={self.weight}）\n"
                f"判定进入下一阶段的 machine_check（任一不满足都判停在本阶段）：\n"
                f"{bullets(self.judge_gate_machine)}\n\n"
                f"machine_check 全部通过后，再判定 llm_check（你来主观判断）：\n"
                f"{bullets(self.judge_gate_llm)}\n\n"
                f"本阶段失败信号（命中则触发倒退或短路终止）：\n"
                f"{bullets(self.stage_fail_signal)}"
                f"{v3_extra_judge}"
            )
        if role == "coach":
            return (
                f"【阶段 {self.id} · {self.cn_name}】 期望权重 {self.weight:.0%}\n"
                f"  核心动作：{', '.join(self.sales_actions[:3])}…\n"
                f"  剧本词表：{', '.join(self.allowed_playbook_actions)}"
            )
        raise ValueError(f"未知 role: {role!r}")


@dataclass
class BusinessStagesConfig:
    """business_stages.yaml 解析后的整体配置。"""

    version: str
    stages: Dict[str, StageSpec]
    # playbook_action_catalog 展平后的 action_id → {stage_id, cn} 索引，方便前端徽章/复盘查表
    playbook_index: Dict[str, Dict[str, str]]
    stage_regression_enabled: bool
    allowed_regressions: List[Dict[str, str]]   # [{"from": "S3", "to": "S2", "reason": "..."}]
    outcome_short_circuit_statuses: List[str]   # 命中即立即结束 session 的 persona.status 列表
    memory_refresh_interval_default: int
    weight_tolerance: float
    weight_usage: str

    def get_stage(self, stage_id: str) -> Optional[StageSpec]:
        return self.stages.get(stage_id)

    def get_allowed_actions(self, stage_id: str) -> List[str]:
        spec = self.get_stage(stage_id)
        return list(spec.allowed_playbook_actions) if spec else []

    def is_valid_transition(self, from_stage: str, to_stage: str) -> bool:
        """是否是合法的 next_stage 切换。
        合法包括：
          - 原地停留（from==to）
          - 前进一格（STAGE_ORDER 中 to_idx == from_idx + 1）
          - 显式声明的倒退（出现在 allowed_regressions 里）
        """
        if from_stage == to_stage:
            return True
        if from_stage not in STAGE_ORDER or to_stage not in STAGE_ORDER:
            return False
        i_from = STAGE_ORDER.index(from_stage)
        i_to = STAGE_ORDER.index(to_stage)
        if i_to == i_from + 1:
            return True
        if i_to < i_from and self.stage_regression_enabled:
            for r in self.allowed_regressions:
                if r.get("from") == from_stage and r.get("to") == to_stage:
                    return True
        return False

    def get_regression_reason(self, from_stage: str, to_stage: str) -> Optional[str]:
        for r in self.allowed_regressions:
            if r.get("from") == from_stage and r.get("to") == to_stage:
                return str(r.get("reason") or "")
        return None

    def all_stage_ids(self) -> List[str]:
        """按 STAGE_ORDER 返回当前 YAML 实际定义的 stage id 列表。"""
        return [sid for sid in STAGE_ORDER if sid in self.stages]


# ============================================================
# 内部：加载 + cache（线程安全）
# ============================================================

_lock = threading.Lock()
_cached: Optional[BusinessStagesConfig] = None
_cached_mtime: float = 0.0


def _default_config() -> BusinessStagesConfig:
    """YAML 完全不可读时的兜底——给一个最小化 5 阶段空骨架，至少让上层不崩。"""
    minimal = {
        "S1": StageSpec(id="S1", name="CONNECTING", cn_name="开场与需求暴露", weight=0.15,
                       allowed_playbook_actions=["warmup_greeting"]),
        "S2": StageSpec(id="S2", name="EXPLORING", cn_name="核心异议与动机挖掘", weight=0.30,
                       allowed_playbook_actions=["spin_problem"]),
        "S3": StageSpec(id="S3", name="EXPERIENCE", cn_name="方案匹配与价值锚定", weight=0.40,
                       allowed_playbook_actions=["anchor_3a", "evidence_3b"]),
        "S4": StageSpec(id="S4", name="CLOSING", cn_name="成交推进与强压测试", weight=0.10,
                       allowed_playbook_actions=["assumptive_close"]),
        "S5": StageSpec(id="S5", name="LOYALTY", cn_name="峰终体验与退出", weight=0.05,
                       allowed_playbook_actions=["graceful_farewell"]),
    }
    return BusinessStagesConfig(
        version="0.0-default",
        stages=minimal,
        playbook_index={a: {"stage_id": sid, "cn": a} for sid, s in minimal.items()
                        for a in s.allowed_playbook_actions},
        stage_regression_enabled=True,
        allowed_regressions=[{"from": "S3", "to": "S2", "reason": "default"}],
        outcome_short_circuit_statuses=["WALK_AWAY", "COMPLAINT"],
        memory_refresh_interval_default=2,
        weight_tolerance=0.10,
        weight_usage="coach_report_only",
    )


def _coerce_text(v: Any) -> str:
    """v0.3：YAML 新字段允许是 str 或 list[str]（多行）；统一压成 markdown bullet 或单段字符串。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        items = [str(x).strip() for x in v if x is not None and str(x).strip()]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return "\n".join(f"- {x}" for x in items)
    return str(v).strip()


def _parse_yaml(data: Dict[str, Any]) -> BusinessStagesConfig:
    stages_data = data.get("stages") or []
    stages: Dict[str, StageSpec] = {}
    for raw in stages_data:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id") or "").strip()
        if sid not in STAGE_ORDER:
            logger.warning("business_stages.yaml: 跳过未知 stage id=%r", sid)
            continue
        gate = raw.get("judge_gate") or {}
        stages[sid] = StageSpec(
            id=sid,
            name=str(raw.get("name") or sid),
            cn_name=str(raw.get("cn_name") or sid),
            weight=float(raw.get("weight") or 0.0),
            sales_actions=[str(x) for x in (raw.get("sales_actions") or [])],
            sales_must_not=[str(x) for x in (raw.get("sales_must_not") or [])],
            allowed_playbook_actions=[str(x) for x in (raw.get("allowed_playbook_actions") or [])],
            judge_gate_machine=[str(x) for x in (gate.get("machine_check") or [])],
            judge_gate_llm=[str(x) for x in (gate.get("llm_check") or [])],
            stage_fail_signal=[str(x) for x in (raw.get("stage_fail_signal") or [])],
            # v0.3 新字段（缺省 = 空串；YAML 里 list 也接受 → join 兜底）
            required_trigger=_coerce_text(raw.get("required_trigger")),
            gate_condition=_coerce_text(raw.get("gate_condition")),
            persona_logic=_coerce_text(raw.get("persona_logic")),
            persona_constraints=_coerce_text(raw.get("persona_constraints")),
            sales_logic=_coerce_text(raw.get("sales_logic")),
            sales_constraints=_coerce_text(raw.get("sales_constraints")),
        )

    catalog = data.get("playbook_action_catalog") or {}
    playbook_index: Dict[str, Dict[str, str]] = {}
    for sid, actions in catalog.items():
        if not isinstance(actions, list):
            continue
        for a in actions:
            if not isinstance(a, dict):
                continue
            aid = str(a.get("id") or "").strip()
            if not aid:
                continue
            playbook_index[aid] = {"stage_id": sid, "cn": str(a.get("cn") or aid)}

    rules = data.get("global_rules") or {}
    reg = rules.get("stage_regression_policy") or {}
    return BusinessStagesConfig(
        version=str(data.get("version") or "unknown"),
        stages=stages,
        playbook_index=playbook_index,
        stage_regression_enabled=bool(reg.get("enabled", True)),
        allowed_regressions=[
            {"from": str(r.get("from") or ""),
             "to": str(r.get("to") or ""),
             "reason": str(r.get("reason") or "")}
            for r in (reg.get("allowed_transitions") or [])
            if isinstance(r, dict)
        ],
        outcome_short_circuit_statuses=_extract_short_circuit_statuses(rules),
        memory_refresh_interval_default=int(rules.get("memory_refresh_interval_default") or 2),
        weight_tolerance=float(rules.get("weight_tolerance") or 0.10),
        weight_usage=str(rules.get("weight_usage") or "coach_report_only"),
    )


def _extract_short_circuit_statuses(rules: Dict[str, Any]) -> List[str]:
    """从 outcome_short_circuit 文本里提取 status 关键字（WALK_AWAY/COMPLAINT/...）。

    YAML 里写的是自然语言句子，这里只做关键词提取，保守起见硬编码已知 token 列表。
    """
    known = {"WALK_AWAY", "COMPLAINT", "DEAL_DONE", "FOLLOW_UP", "TIMEOUT"}
    text = " ".join(str(x) for x in (rules.get("outcome_short_circuit") or []))
    hits = [t for t in known if t in text and t in ("WALK_AWAY", "COMPLAINT")]
    return hits or ["WALK_AWAY", "COMPLAINT"]


def load_stages(force_reload: bool = False) -> BusinessStagesConfig:
    """读 business_stages.yaml；含 mtime cache，热修改 YAML 秒级生效。"""
    global _cached, _cached_mtime

    path = _STAGES_YAML_PATH
    with _lock:
        if not path.exists():
            if _cached is None:
                logger.error("business_stages.yaml 不存在: %s，使用默认骨架", path)
                _cached = _default_config()
            return _cached

        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0

        if (not force_reload) and _cached is not None and mtime == _cached_mtime:
            return _cached

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                raise ValueError("YAML 顶层不是 mapping")
            cfg = _parse_yaml(data)
        except Exception as exc:  # noqa: BLE001
            logger.error("解析 business_stages.yaml 失败，使用默认骨架: %s", exc)
            if _cached is None:
                _cached = _default_config()
            return _cached

        _cached = cfg
        _cached_mtime = mtime
        return cfg


# ============================================================
# 对外便捷 API（薄包装，全部走 cache 单例）
# ============================================================

def get_stage(stage_id: str) -> Optional[StageSpec]:
    return load_stages().get_stage(stage_id)


def get_allowed_actions(stage_id: str) -> List[str]:
    return load_stages().get_allowed_actions(stage_id)


def is_valid_transition(from_stage: str, to_stage: str) -> bool:
    return load_stages().is_valid_transition(from_stage, to_stage)


def get_regression_reason(from_stage: str, to_stage: str) -> Optional[str]:
    return load_stages().get_regression_reason(from_stage, to_stage)


def all_stage_ids() -> List[str]:
    return load_stages().all_stage_ids()


def short_circuit_statuses() -> List[str]:
    return list(load_stages().outcome_short_circuit_statuses)


def memory_interval_default() -> int:
    return load_stages().memory_refresh_interval_default


def render_all_stages_for_judge() -> str:
    """把 5 个阶段拼成一段 markdown 注入 judge_prompt 的"全图视野"。"""
    cfg = load_stages()
    chunks = []
    for sid in cfg.all_stage_ids():
        spec = cfg.stages[sid]
        chunks.append(spec.to_prompt_block(role="judge"))
    return "\n\n".join(chunks) if chunks else "（business_stages.yaml 未加载，按你的常识自由判断）"


def render_stage_for_sales(stage_id: str) -> str:
    """给 sales_prompt 用的"仅当前阶段视野"段落。"""
    spec = get_stage(stage_id)
    if not spec:
        return "（当前阶段未在 business_stages.yaml 中定义，按通用销售常识作答）"
    return spec.to_prompt_block(role="sales")


def is_valid_playbook_action(stage_id: str, action: str) -> bool:
    """销冠输出 playbook_action 后校验：必须属于当前 stage 的 allowed 列表。"""
    allowed = get_allowed_actions(stage_id)
    return action in allowed


def stage_cn_name(stage_id: str) -> str:
    """前端进度条用：S1-S5 → 中文名。"""
    spec = get_stage(stage_id)
    return spec.cn_name if spec else stage_id


def playbook_cn(action_id: str) -> str:
    """前端徽章用：action_id → 中文名。"""
    idx = load_stages().playbook_index
    return idx.get(action_id, {}).get("cn", action_id)


def playbook_catalog() -> List[Dict[str, Any]]:
    """前端展示用：完整 catalog（按 stage 分组）。"""
    cfg = load_stages()
    out = []
    for sid in cfg.all_stage_ids():
        spec = cfg.stages[sid]
        out.append({
            "stage_id": sid,
            "stage_cn": spec.cn_name,
            "weight": spec.weight,
            "actions": [
                {"id": a, "cn": playbook_cn(a)}
                for a in spec.allowed_playbook_actions
            ],
        })
    return out
