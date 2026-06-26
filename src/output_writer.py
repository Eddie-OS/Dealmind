"""会话结束后的文件输出模块。

输出 4 个文件到 outputs/{session_id}/ 目录：
  1. session_log.json       — 完整结构化会话记录（含 coach_review）
  2. dialogue.jsonl         — 每轮对话的 JSONL（每行一条 turn）
  3. lessons_candidate.jsonl — CoachReview 中的 key_lessons 和 reusable_tactics（人工审核用）
  4. summary.md             — 人类可读的 Markdown 会话摘要
"""

from __future__ import annotations

import json
from pathlib import Path

from src.safe_console import SafeConsole
from src.schema import CoachReview, DialogueState
from src.utils import now_timestamp, safe_json_dumps


console = SafeConsole()


def write_session_outputs(state: DialogueState, output_dir: str = "outputs") -> Path:
    """将本次会话写出到 outputs/{session_id}/ 并返回该目录路径。"""
    session_dir = Path(output_dir) / state.session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    _write_session_log(state, session_dir)
    _write_dialogue_jsonl(state, session_dir)
    _write_lessons_candidate(state, session_dir)
    _write_summary_md(state, session_dir)

    console.print(f"[green]输出文件已写入: {session_dir}[/green]")
    return session_dir


# ───────────────────────── 1. session_log.json ─────────────────────────


def _write_session_log(state: DialogueState, session_dir: Path) -> None:
    payload = {
        "session_id": state.session_id,
        "topic": state.topic,
        "outcome": state.outcome,
        "total_rounds": state.round_idx,
        "final_stage": state.current_stage,
        "persona": state.persona_profile.model_dump(),
        "session_memory": state.session_memory.model_dump(),
        "judge_feedback": state.judge_feedback.model_dump(),
        "coach_review": state.coach_review.model_dump() if state.coach_review else None,
        "full_history": [t.model_dump() for t in state.full_history],
        "exported_at": now_timestamp(),
    }
    path = session_dir / "session_log.json"
    path.write_text(safe_json_dumps(payload, indent=2), encoding="utf-8")
    console.print(f"  [dim]session_log.json: {len(state.full_history)} turns[/dim]")


# ───────────────────────── 2. dialogue.jsonl ──────────────────────────


def _write_dialogue_jsonl(state: DialogueState, session_dir: Path) -> None:
    path = session_dir / "dialogue.jsonl"
    lines: list[str] = []
    for t in state.full_history:
        row = {
            "session_id": state.session_id,
            "turn_idx": t.idx,
            "speaker": t.speaker,
            "content": t.content,
            "stage": t.metadata.get("stage", ""),
            "metadata": t.metadata,
        }
        lines.append(json.dumps(row, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"  [dim]dialogue.jsonl: {len(lines)} lines[/dim]")


# ─────────────────────── 3. lessons_candidate.jsonl ───────────────────


def _write_lessons_candidate(state: DialogueState, session_dir: Path) -> None:
    review: CoachReview | None = state.coach_review
    path = session_dir / "lessons_candidate.jsonl"
    lines: list[str] = []

    if review:
        for lesson in review.key_lessons:
            row = {
                "type": "key_lesson",
                "session_id": state.session_id,
                "persona_id": state.persona_profile.id,
                "outcome": state.outcome,
                "content": lesson,
                "difficulty_rating": review.difficulty_rating,
                "status": "candidate",
                "exported_at": now_timestamp(),
            }
            lines.append(json.dumps(row, ensure_ascii=False))

        for tactic in review.reusable_tactics:
            row = {
                "type": "reusable_tactic",
                "session_id": state.session_id,
                "persona_id": state.persona_profile.id,
                "outcome": state.outcome,
                "name": tactic.get("name", ""),
                "condition": tactic.get("condition", ""),
                "example": tactic.get("example", ""),
                "status": "candidate",
                "exported_at": now_timestamp(),
            }
            lines.append(json.dumps(row, ensure_ascii=False))

        for rb in review.suggested_rebuttals:
            row = {
                "type": "rebuttal_template",
                "session_id": state.session_id,
                "persona_id": state.persona_profile.id,
                "outcome": state.outcome,
                "objection": rb.get("objection", ""),
                "rebuttal_template": rb.get("rebuttal_template", ""),
                "status": "candidate",
                "exported_at": now_timestamp(),
            }
            lines.append(json.dumps(row, ensure_ascii=False))

    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    console.print(f"  [dim]lessons_candidate.jsonl: {len(lines)} entries[/dim]")


# ───────────────────────── 4. summary.md ──────────────────────────────


def _write_summary_md(state: DialogueState, session_dir: Path) -> None:
    p = state.persona_profile
    mem = state.session_memory
    review = state.coach_review

    lines: list[str] = [
        f"# 会话摘要",
        f"",
        f"| 字段 | 值 |",
        f"|------|-----|",
        f"| session_id | `{state.session_id}` |",
        f"| 话题 | {state.topic} |",
        f"| 人设 | {p.name}（{p.occupation}，预算{p.budget}） |",
        f"| 最终结果 | **{state.outcome}** |",
        f"| 总轮数 | {state.round_idx} |",
        f"| 最终阶段 | {state.current_stage} |",
        f"",
        f"## 会话画像记忆",
        f"",
        f"- **核心需求**：{mem.current_need}",
        f"- **预算边界**：{mem.budget_boundary}",
        f"- **情绪状态**：{mem.emotional_state}",
        f"- **主要异议**：",
    ]
    for obj in mem.main_objections:
        lines.append(f"  - {obj}")
    if mem.do_not_repeat:
        lines.append(f"- **避免重复**：")
        for d in mem.do_not_repeat:
            lines.append(f"  - {d}")
    lines.append(f"- **下一步建议**：{mem.next_best_action}")
    lines.append("")

    if review:
        lines += [
            f"## Coach 复盘",
            f"",
            f"**结果分析**：{review.outcome_analysis}",
            f"",
            f"**人设难度**：{review.difficulty_rating}/10 — {review.difficulty_reason}",
            f"",
            f"**人设洞察**：{review.persona_insight}",
            f"",
            f"### 有效策略",
        ]
        for w in review.what_worked:
            lines.append(
                f"- 第{w.get('round','')}轮 [{w.get('strategy','')}]：{w.get('why_effective','')}"
            )
            if w.get("evidence"):
                lines.append(f"  > {w.get('evidence','')}")

        lines.append("")
        lines.append("### 失效操作")
        for f_ in review.what_failed:
            lines.append(
                f"- 第{f_.get('round','')}轮 [{f_.get('strategy','')}]：{f_.get('why_failed','')}"
            )
            if f_.get("evidence"):
                lines.append(f"  > {f_.get('evidence','')}")

        lines.append("")
        lines.append("### 销售经验（可写入培训手册）")
        for i, lesson in enumerate(review.key_lessons, 1):
            lines.append(f"{i}. {lesson}")

        lines.append("")
        lines.append("### 更优话术模板")
        for rb in review.suggested_rebuttals:
            lines.append(f"- **{rb.get('objection','')}**")
            lines.append(f"  > {rb.get('rebuttal_template','')}")

        lines.append("")
        lines.append("### 可复用策略模式")
        for tactic in review.reusable_tactics:
            lines.append(f"- **{tactic.get('name','')}**")
            lines.append(f"  - 使用条件：{tactic.get('condition','')}")
            lines.append(f"  - 示例：{tactic.get('example','')}")

    lines.append("")
    lines.append(f"---")
    lines.append(f"*导出时间：{now_timestamp()}*")

    path = session_dir / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"  [dim]summary.md: {len(lines)} lines[/dim]")
