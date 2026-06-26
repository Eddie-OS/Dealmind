#!/usr/bin/env python3
"""对已完成 batch 重新跑 Handbook 分析报告（使用加速后的管线）。

用法:
  python scripts/rerun_batch_analysis.py --batch-id 13
  python scripts/rerun_batch_analysis.py --batch-id 13 --cancel-job 14
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.analyzers.analysis_runner import start_analysis_job  # noqa: E402
from src.storage import db as sdb  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-id", type=int, required=True)
    ap.add_argument("--cancel-job", type=int, default=None, help="先取消旧 job")
    ap.add_argument("--poll-sec", type=float, default=15.0)
    args = ap.parse_args()

    if args.cancel_job:
        with sdb.connection_scope() as conn:
            from src.analyzers.analysis_runner import get_runner

            r = get_runner(args.cancel_job)
            if r:
                r.request_cancel()
            sdb.update_analysis_job(
                conn, args.cancel_job, status="cancelled", mark_ended=True,
            )
        print(f"已请求取消 job #{args.cancel_job}")

    with sdb.connection_scope() as conn:
        batch = sdb.get_batch_job(conn, args.batch_id)
        if not batch:
            raise SystemExit(f"batch {args.batch_id} 不存在")
        hb_id = batch.get("handbook_id")
        if not hb_id:
            raise SystemExit("batch 未绑定 handbook_id")

    job_id = start_analysis_job(
        batch_id=args.batch_id,
        handbook_id=int(hb_id),
    )
    print(f"已启动 analysis job #{job_id}（batch={args.batch_id}）")

    t0 = time.time()
    while True:
        with sdb.connection_scope() as conn:
            job = sdb.get_analysis_job(conn, job_id)
        if not job:
            raise SystemExit("job 消失")
        st = job["status"]
        prog = float(job.get("progress") or 0)
        ct = int(job.get("classified_turns") or 0)
        tt = int(job.get("total_turns") or 0)
        elapsed = time.time() - t0
        print(
            f"[{elapsed/60:.1f}min] status={st} "
            f"progress={prog*100:.1f}% ({ct}/{tt})",
        )
        if st in ("completed", "failed", "cancelled"):
            if st == "completed":
                print("完成")
            else:
                print(f"结束: {st} err={job.get('error_msg')}")
            break
        time.sleep(args.poll_sec)


if __name__ == "__main__":
    main()
