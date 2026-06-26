"""读 smoke session 的所有 turn，检查 playbook_action / stage_id / stage_transition 是否齐全。"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SID = sys.argv[1] if len(sys.argv) > 1 else "session_20260525_200543_p1"


def main() -> int:
    with urlopen(f"http://127.0.0.1:8000/api/sessions/{SID}/detail", timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))

    turns = data.get("turns") or []
    print(f"Session: {SID}")
    print(f"Outcome: {data.get('summary', {}).get('outcome')}")
    print(f"Total turns: {len(turns)}")
    print()

    sales_with_pa = 0
    sales_with_sid = 0
    sales_total = 0
    pa_counter: dict = {}
    sid_counter: dict = {}

    for t in turns:
        role = t.get("role")
        meta = t.get("metadata") or {}
        if role == "sales":
            sales_total += 1
            pa = meta.get("playbook_action")
            sid = meta.get("stage_id")
            if pa:
                sales_with_pa += 1
                pa_counter[pa] = pa_counter.get(pa, 0) + 1
            if sid:
                sales_with_sid += 1
                sid_counter[sid] = sid_counter.get(sid, 0) + 1

    print(f"Sales turns total: {sales_total}")
    print(f"  with playbook_action: {sales_with_pa}/{sales_total}")
    print(f"  with stage_id:        {sales_with_sid}/{sales_total}")
    print(f"\nplaybook_action counts:")
    for k, v in sorted(pa_counter.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"\nstage_id counts:")
    for k, v in sorted(sid_counter.items()):
        print(f"  {k}: {v}")

    # 打印每一轮 sales 的简要
    print(f"\n=== sales turns 简要 ===")
    for t in turns:
        if t.get("role") != "sales":
            continue
        meta = t.get("metadata") or {}
        sid = meta.get("stage_id") or "-"
        pa = meta.get("playbook_action") or "-"
        intent = meta.get("intent") or "-"
        content_brief = (t.get("content") or "")[:60]
        print(f"  round {t.get('idx')} [stage={sid}] [pa={pa}] [intent={intent}] {content_brief}")

    # judge feedback / stage transitions
    judge_evals = data.get("judge_evaluations") or []
    print(f"\n=== judge evaluations ({len(judge_evals)}) ===")
    for e in judge_evals:
        fb = e.get("feedback") or {}
        st = fb.get("stage_transition") or {}
        print(
            f"  round {e.get('round_idx')} "
            f"stage_transition={st.get('from_stage', '-')}→{st.get('to_stage', '-')} "
            f"direction={st.get('direction', '-')} "
            f"machine={st.get('machine_check_pass', '-')} llm={st.get('llm_check_pass', '-')} "
            f"end_status={fb.get('end_status', '-')}"
        )
        if st.get("fail_reasons"):
            print(f"    fail_reasons: {st['fail_reasons']}")
        if st.get("triggered_fail_signal"):
            print(f"    triggered_fail_signal: {st['triggered_fail_signal']}")

    coach = data.get("coach_review") or {}
    if coach:
        print(f"\n=== coach review ===")
        print(f"  outcome_analysis: {(coach.get('outcome_analysis') or '')[:200]}")
        print(f"  playbook_coverage_review: {(coach.get('playbook_coverage_review') or '')[:200]}")
        print(f"  weight_balance_review: {(coach.get('weight_balance_review') or '')[:200]}")
        ps = coach.get("playbook_stats") or {}
        if ps:
            print(f"  [stats] total_sales_turns={ps.get('total_sales_turns')}, actions_count={ps.get('actions_count')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
