"""把某个分析任务导出为精排 HTML 报告（浏览器打开后可打印成 PDF）。

用法：
    python scripts/export_analysis_html.py 15
    python scripts/export_analysis_html.py 15 --out outputs/report_15.html
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.analyzers.report_html import render_analysis_html
from src.storage import db as sdb

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id", type=int)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with sdb.connection_scope() as conn:
        job = sdb.get_analysis_job(conn, args.job_id)
    if not job:
        raise SystemExit(f"job_id={args.job_id} 不存在")

    raw = job.pop("summary_json", None)
    job["summary"] = json.loads(raw) if raw else {}

    html = render_analysis_html(job)

    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[1] / "outputs" / f"analysis_report_{args.job_id}.html"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"已生成报告：{out}")
    print(f"  字节数：{len(html.encode('utf-8'))}")
    print(f"  浏览器打开后 Ctrl+P → 另存为 PDF 即可。")


if __name__ == "__main__":
    main()
