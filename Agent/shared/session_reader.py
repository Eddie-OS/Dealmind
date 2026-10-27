"""把一次 run 里所有会话的落盘文件读回内存，供 09 / 10 / 11 共用。

这三个 agent 都要遍历全部会话，各写一遍加载与派生指标只会让三份口径
慢慢分叉（"引用手册率"在报告 A 和报告 B 里算出不同数字是最常见的事故）。
派生指标统一在这里算一次。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from shared.runctx import RunContext


@dataclass
class SessionRecord:
    persona_id: str
    persona_name: str
    dir: Path
    log: dict[str, Any]

    turns: list[dict[str, Any]] = field(default_factory=list)
    sales_turns: list[dict[str, Any]] = field(default_factory=list)
    persona_turns: list[dict[str, Any]] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        return self.log.get("outcome") or "UNKNOWN"

    @property
    def total_rounds(self) -> int:
        return int(self.log.get("total_rounds") or 0)

    @property
    def final_stage(self) -> str:
        return self.log.get("final_stage") or "-"

    @property
    def coach(self) -> dict[str, Any]:
        return self.log.get("coach_review") or {}

    @property
    def judge(self) -> dict[str, Any]:
        return self.log.get("judge_feedback") or {}

    @property
    def memory(self) -> dict[str, Any]:
        return self.log.get("session_memory") or {}

    @property
    def sales_score(self) -> dict[str, float]:
        raw = self.judge.get("sales_score") or {}
        return {k: float(v or 0) for k, v in raw.items() if isinstance(v, (int, float))}

    @property
    def judged(self) -> bool:
        """裁判到底给这场打过分没有。

        会话可能在第一次裁判介入（默认第 3 轮）之前就结束 —— 客户扭头就走、
        开局异常等等。这种场次的 judge_feedback 是空的，把它当成"0 分"计入均值
        会凭空拉低整体表现，必须和"真的打了低分"区分开。
        """
        q = self.judge.get("dialogue_quality_score")
        if isinstance(q, (int, float)) and q > 0:
            return True
        return any(v > 0 for v in self.sales_score.values())

    @property
    def quality_score(self) -> float:
        """优先用裁判的整体质量分；没有就退回 5 维均值。未打分的场次返回 0。"""
        q = self.judge.get("dialogue_quality_score")
        if isinstance(q, (int, float)) and q > 0:
            return float(q)
        vals = list(self.sales_score.values())
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    @property
    def difficulty(self) -> int:
        return int(self.coach.get("difficulty_rating") or 0)

    @property
    def guard_rewrites(self) -> int:
        """本场销冠被护栏改写的轮数。数字越大说明越爱编。"""
        return sum(
            1
            for t in self.sales_turns
            if ((t.get("metadata") or {}).get("content_guard") or {}).get("rewritten")
        )

    @property
    def handbook_citation_rate(self) -> float:
        """销冠自报引用了手册的轮次占比。"""
        if not self.sales_turns:
            return 0.0
        cited = sum(1 for t in self.sales_turns if (t.get("metadata") or {}).get("used_handbook"))
        return round(cited / len(self.sales_turns), 3)

    @staticmethod
    def _signal_of(turn: dict[str, Any]) -> Optional[float]:
        """HiddenState 的字段被上游铺平写进 metadata，这里直接取顶层。"""
        v = (turn.get("metadata") or {}).get("purchase_signal")
        return float(v) if isinstance(v, (int, float)) else None

    def signal_at(self, turn_idx: int) -> Optional[float]:
        """取某个 idx 之后最近一次客户发言的购买信号。"""
        for t in self.persona_turns:
            if t.get("idx", -1) > turn_idx:
                return self._signal_of(t)
        return None

    def signal_before(self, turn_idx: int) -> Optional[float]:
        prev = [t for t in self.persona_turns if t.get("idx", 10**9) < turn_idx]
        return self._signal_of(prev[-1]) if prev else None

    def signal_series(self) -> list[float]:
        """全场购买信号序列，缺失的轮次跳过。"""
        out = []
        for t in self.persona_turns:
            v = self._signal_of(t)
            if v is not None:
                out.append(v)
        return out

    def customer_line_before(self, turn_idx: int) -> str:
        prev = [t for t in self.persona_turns if t.get("idx", 10**9) < turn_idx]
        return (prev[-1].get("content") or "") if prev else ""


def iter_sessions(ctx: RunContext) -> Iterator[SessionRecord]:
    """按人设目录名排序遍历本次 run 已完成的会话。"""
    if not ctx.sessions_dir.is_dir():
        return
    for d in sorted(p for p in ctx.sessions_dir.iterdir() if p.is_dir()):
        log_path = d / "session_log.json"
        if not log_path.is_file():
            continue
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        persona = log.get("persona") or {}
        rec = SessionRecord(
            persona_id=str(persona.get("id") or d.name),
            persona_name=str(persona.get("name") or d.name),
            dir=d,
            log=log,
        )
        rec.turns = list(log.get("full_history") or [])
        rec.sales_turns = [t for t in rec.turns if t.get("speaker") == "sales"]
        rec.persona_turns = [t for t in rec.turns if t.get("speaker") == "persona"]
        yield rec


def load_sessions(ctx: RunContext) -> list[SessionRecord]:
    return list(iter_sessions(ctx))
