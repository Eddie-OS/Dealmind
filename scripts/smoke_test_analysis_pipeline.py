"""A1-A4 端到端 smoke：mock LLM 不调真模型，跑通整条分析管道。

验证：
  - start_analysis_job → analysis_runner → handbook_classifier (mock)
    → handbook_scorer (mock) → report_aggregator → DB 写入
  - 末态 jobs.status == completed
  - turn_classifications 行数 > 0
  - analysis_persona_insights 至少 1 行
  - summary.coverage_pct / weak_categories / strong_categories 出来
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

import src.analyzers.handbook_classifier as cls_mod  # noqa: E402
import src.analyzers.handbook_scorer as scorer_mod  # noqa: E402
from src.analyzers.analysis_runner import start_analysis_job  # noqa: E402
from src.storage import db as sdb  # noqa: E402


# ============== mock 分类器：按关键词命中 sell_1/sell_2/faq_1 ==============
def _mock_classify(*, content, handbook_struct, top_k=10, min_confidence=0.4):
    """强制每条 turn 返回 1-2 个标签，覆盖测试。"""
    out = [{"category_id": "sell_1", "confidence": 0.66, "reason": "mock"}]
    if len(content) > 80:
        out.append({"category_id": "param_1", "confidence": 0.55, "reason": "mock-长 turn"})
    if "试" in content or "体验" in content or "您" in content:
        out.append({"category_id": "demo_1", "confidence": 0.72, "reason": "mock-demo"})
    return out


def _mock_score(*, content, category_id, handbook_struct):
    # 简单：内容越长越好，避免全 0
    base = min(8, max(3, len(content) // 30))
    return {
        "scores": {
            "accuracy": base,
            "specificity": base - 1 if base > 1 else 0,
            "delivery": 6,
            "customer_fit": 5,
            "closing_push": 4 if "试" in content else 3,
            "risk_compliance": 9,
        },
        "issues": [] if base >= 6 else ["未给出具体数字"],
        "suggestion": "可加屏幕亮度数字增强说服力" if base < 6 else "",
        "reference_text": "示例参考文本",
    }


cls_mod.classify_turn_multilabel = _mock_classify  # type: ignore
scorer_mod.score_turn_six_dims = _mock_score  # type: ignore


def main() -> None:
    with sdb.connection_scope() as conn:
        rows = list(conn.execute(
            "SELECT id, persona_id, handbook_id FROM sessions "
            "WHERE id IN (SELECT session_id FROM turns WHERE role='sales' "
            "GROUP BY session_id HAVING COUNT(*) >= 5) "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchall())
    if not rows:
        print("ERROR: 没有可用 session")
        sys.exit(1)
    target_sid = rows[0]["id"]
    print(f"Target session: {target_sid} (handbook_id={rows[0]['handbook_id']})")

    job_id = start_analysis_job(session_id=target_sid)
    print(f"Started job_id={job_id}")

    deadline = time.time() + 30
    last_status = None
    while time.time() < deadline:
        with sdb.connection_scope() as conn:
            job = sdb.get_analysis_job(conn, job_id)
        if not job:
            print("ERROR: job 消失")
            sys.exit(1)
        if job["status"] != last_status:
            print(f"  status={job['status']} progress={job['progress']:.2f} "
                  f"classified_turns={job['classified_turns']}/{job['total_turns']}")
            last_status = job["status"]
        if job["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.5)
    else:
        print("ERROR: 超时 30s")
        sys.exit(1)

    print(f"\nFinal status: {job['status']}")
    if job["status"] != "completed":
        print(f"error: {job.get('error_msg')}")
        sys.exit(1)

    import json
    summary = json.loads(job["summary_json"] or "{}")
    print(f"\n--- summary V1 ---")
    print(f"schema version: {summary.get('version')}")
    print(f"coverage_pct: {summary.get('coverage_pct')}%  "
          f"categories_covered={summary.get('categories_covered')}/{summary.get('categories_total')}")
    print(f"total_classifications: {summary.get('total_classifications')}")
    print(f"weak_categories: {len(summary.get('weak_categories') or [])}")
    print(f"strong_categories: {len(summary.get('strong_categories') or [])}")
    print(f"dim_avg: {summary.get('dim_avg')}")
    print(f"outcome_join: {summary.get('outcome_join')}")

    print(f"\n--- summary V2 长报告字段 ---")
    excellent = summary.get('excellent_turns') or []
    problematic = summary.get('problematic_turns') or []
    proposals = summary.get('revision_proposals') or []
    voice = summary.get('customer_voice') or []
    knums = summary.get('key_numbers') or []
    cov_grp = summary.get('coverage_by_group') or {}
    print(f"excellent_turns: {len(excellent)} 条")
    if excellent:
        e0 = excellent[0]
        print(f"  例 #1  avg_q={e0['avg_quality']} persona={e0['persona_name']}")
        print(f"         销冠原话: {(e0['sales_content'] or '')[:60]}…")
        print(f"         why_good: {e0.get('why_good')}")
    print(f"problematic_turns: {len(problematic)} 条")
    if problematic:
        p0 = problematic[0]
        print(f"  例 #1  avg_q={p0['avg_quality']} persona={p0['persona_name']}")
        print(f"         销冠原话: {(p0['sales_content'] or '')[:60]}…")
        print(f"         why_bad : {p0.get('why_bad')}")
        print(f"         建议    : {(p0.get('suggestion') or '')[:60]}")
    print(f"revision_proposals: {len(proposals)} 条")
    for pr in proposals[:3]:
        print(f"  - [{pr.get('severity')}] {pr.get('kind')} · "
              f"{pr.get('category_label') or pr.get('dimension_label')}")
        print(f"    建议: {(pr.get('suggestion') or '')[:80]}…")
    print(f"customer_voice groups: {len(voice)} 个 persona")
    for g in voice[:3]:
        print(f"  - {g['persona_name']} ({g['persona_cluster']}) "
              f"sample_count={g['sample_count']}")
    print(f"key_numbers: {len(knums)} 个数字")
    for n in knums[:5]:
        print(f"  · {n['value']:>10}  {n['context'][:20]:<20}  ({n['source_group']})")
    print(f"coverage_by_group: {list(cov_grp.keys())}")
    for k, stat in cov_grp.items():
        print(f"  - {k}: covered={stat['covered']}/{stat['total']} "
              f"({stat['coverage_pct']}%) hits={stat['hits']} q={stat['weighted_avg_quality']}")

    eng = summary.get('engagement') or {}
    print(f"\n--- 销售健康度仪表 (engagement) ---")
    if eng:
        print(f"  total_sales_turns      : {eng.get('total_sales_turns')}")
        print(f"  handbook_mention_rate  : {eng.get('handbook_mention_rate')} "
              f"({eng.get('handbook_mention_count')}/{eng.get('total_sales_turns')})")
        print(f"  punt_rate              : {eng.get('punt_rate')} "
              f"({eng.get('punt_count')}/{eng.get('total_sales_turns')})")
        print(f"  parse_fail_rate        : {eng.get('parse_fail_rate')} "
              f"({eng.get('parse_fail_count')}/{eng.get('total_sales_turns')})")
        print(f"  repetition_rate        : {eng.get('repetition_rate')} "
              f"({eng.get('repetition_count')} 重复 turn)")
        print(f"  avg_length             : {eng.get('avg_length')} 字符")
        print(f"  token_count            : {eng.get('token_count')} 个 handbook 关键词")
        print(f"  top_hit_tokens (Top 5) :")
        for t in (eng.get('top_hit_tokens') or [])[:5]:
            print(f"    · {t['token']:<10} x{t['count']}")
        print(f"  punt_examples ({len(eng.get('punt_examples') or [])} 条)")
        for s in (eng.get('punt_examples') or [])[:3]:
            print(f"    · {s[:80]}")

    with sdb.connection_scope() as conn:
        cls_rows = sdb.list_turn_classifications(conn, job_id, limit=5)
        ins_rows = sdb.list_analysis_persona_insights(conn, job_id)
    print(f"\nturn_classifications: {len(cls_rows)} 行（前 3 示例）")
    for r in cls_rows[:3]:
        print(f"  sess={r['session_id'][-16:]} turn={r['turn_idx']} cid={r['category_id']} "
              f"conf={r['confidence']:.2f} suggestion={r['suggestion'][:30]}")
    print(f"\npersona_insights: {len(ins_rows)} 行")
    for r in ins_rows:
        print(f"  pid={r['persona_id']} cluster={r['persona_cluster']} "
              f"deal_rate={r['deal_rate']} avg_q={r['avg_quality']}")

    # 强断言：V2 字段必须存在（即使为空 list）
    assert 'excellent_turns' in summary, 'V2: missing excellent_turns'
    assert 'problematic_turns' in summary, 'V2: missing problematic_turns'
    assert 'revision_proposals' in summary, 'V2: missing revision_proposals'
    assert 'customer_voice' in summary, 'V2: missing customer_voice'
    assert 'key_numbers' in summary, 'V2: missing key_numbers'
    assert 'coverage_by_group' in summary, 'V2: missing coverage_by_group'

    print("\n=== SMOKE PASS ===")


if __name__ == "__main__":
    main()
