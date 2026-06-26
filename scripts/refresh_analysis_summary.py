#!/usr/bin/env python3
"""仅重算 analysis_job 的 summary（不重新跑 LLM 分类）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.analyzers.analysis_runner import AnalysisRunner  # noqa: E402
from src.analyzers.report_aggregator import aggregate_report  # noqa: E402
from src.storage import db as sdb  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", type=int, required=True)
    args = ap.parse_args()

    with sdb.connection_scope() as conn:
        job = sdb.get_analysis_job(conn, args.job_id)
        if not job:
            raise SystemExit(f"job {args.job_id} 不存在")
        hb_id = job.get("handbook_id")
        hb = sdb.get_handbook(conn, int(hb_id)) if hb_id else None
        if not hb:
            raise SystemExit("handbook 不存在")
        session_ids = AnalysisRunner._resolve_session_ids(conn, job)
        rows = sdb.list_turn_classifications(conn, args.job_id, limit=50000)

    classifications = []
    for r in rows:
        scores = r.get("scores")
        issues = r.get("issues")
        if isinstance(r.get("scores_json"), str):
            try:
                scores = json.loads(r["scores_json"])
            except Exception:
                pass
        if isinstance(r.get("issues_json"), str):
            try:
                issues = json.loads(r["issues_json"])
            except Exception:
                pass
        classifications.append({
            "session_id": r["session_id"],
            "turn_idx": r["turn_idx"],
            "category_id": r["category_id"],
            "confidence": r.get("confidence") or 0,
            "scores": scores or {},
            "issues": issues or [],
            "suggestion": r.get("suggestion") or "",
            "reference_text": r.get("reference_text") or "",
        })

    report = aggregate_report(
        job_id=args.job_id,
        session_ids=session_ids,
        handbook=hb,
        classifications=classifications,
    )
    summary = report.get("summary") or {}
    voice = summary.get("customer_voice") or []
    print(f"customer_voice: {len(voice)} 个 persona 分组")
    if voice:
        print(f"  首组样本数: {voice[0].get('sample_count')}")

    with sdb.connection_scope() as conn:
        sdb.update_analysis_job(
            conn, args.job_id, summary=summary,
        )
        sdb.delete_analysis_persona_insights(conn, args.job_id)
        sdb.insert_analysis_persona_insights(
            conn, args.job_id, report.get("persona_insights") or [],
        )
    print(f"job #{args.job_id} summary 已刷新")


if __name__ == "__main__":
    main()
