#!/usr/bin/env python3
"""分析任务完成后质量门禁（V2 报告关键字段非空）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.storage import db as sdb  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", type=int, required=True)
    args = ap.parse_args()

    with sdb.connection_scope() as conn:
        job = sdb.get_analysis_job(conn, args.job_id)
    if not job:
        raise SystemExit(f"job {args.job_id} 不存在")
    if job["status"] != "completed":
        raise SystemExit(f"job 状态={job['status']}，非 completed")

    raw = job.get("summary_json") or "{}"
    summary = json.loads(raw) if isinstance(raw, str) else (raw or {})

    assert summary.get("version"), "缺少 version"
    cov = summary.get("coverage_pct")
    assert cov is not None and cov >= 0, "coverage_pct 无效"
    eng = summary.get("engagement") or {}
    assert "handbook_mention_rate" in eng, "缺少 engagement.handbook_mention_rate"
    exc = summary.get("excellent_turns") or []
    prob = summary.get("problematic_turns") or []
    assert len(exc) + len(prob) > 0, "优秀/问题话术均为空"
    dim = summary.get("dim_avg") or {}
    assert len(dim) >= 4, "6 维评分不足"

    print("quality gate OK", {
        "coverage_pct": cov,
        "excellent": len(exc),
        "problematic": len(prob),
        "handbook_mention_rate": eng.get("handbook_mention_rate"),
    })


if __name__ == "__main__":
    main()
