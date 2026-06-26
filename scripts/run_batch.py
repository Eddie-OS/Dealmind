"""无头跑一整批会话（不依赖 UI/WS）。

默认镜像最近的全量批次（44 个 persona × handbook=1），用于在新机制
（② 市场事实表 + ③ 品牌人格解耦）下做真批量对话。

用法：
  # 全量 44 场（镜像 batch #13 配置）
  python scripts/run_batch.py

  # 先小批验证：指定 persona id
  python scripts/run_batch.py --personas 1,3,9,17,25,33

  # 自定义
  python scripts/run_batch.py --handbook 1 --max-rounds 30 --name "新机制全量"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.batch.runner import BatchRunner
from src.perf_config import BATCH_SESSION_CONCURRENCY
from src.storage import db
from src.utils import now_timestamp

# 镜像 batch #13 的全量配置
_REF = {
    "product_kb_id": 1,
    "enterprise_kb_id": 2,
    "handbook_id": 1,
    "topic": "华为 MatePad 销售模拟",
    "max_rounds": 30,
}


def main() -> None:
    ap = argparse.ArgumentParser(description="无头跑一整批会话")
    ap.add_argument("--personas", type=str, default=None, help="逗号分隔 persona id；缺省=全部")
    ap.add_argument("--handbook", type=int, default=_REF["handbook_id"])
    ap.add_argument("--product-kb", type=int, default=_REF["product_kb_id"],
                    help="产品知识库 id；传 0 或负数表示不挂产品库（NULL，agent 仅用手册）")
    ap.add_argument("--enterprise-kb", type=int, default=_REF["enterprise_kb_id"])
    ap.add_argument("--topic", type=str, default=_REF["topic"])
    ap.add_argument("--max-rounds", type=int, default=_REF["max_rounds"])
    ap.add_argument("--name", type=str, default=None)
    ap.add_argument("--language", type=str, default="zh-CN",
                    help="对话语言，如 en / en-US / zh-CN（写入 batch config.language）")
    args = ap.parse_args()

    with db.connection_scope() as conn:
        db.init_schema(conn)
        if args.personas:
            persona_ids = [int(x) for x in args.personas.split(",") if x.strip()]
        else:
            persona_ids = [p["id"] for p in db.list_personas(conn)]
        name = args.name or f"新机制批量-{now_timestamp()}"
        product_kb = args.product_kb if args.product_kb and args.product_kb > 0 else None
        batch = db.create_batch_job(
            conn,
            name=name,
            persona_ids=persona_ids,
            product_kb_id=product_kb,
            enterprise_kb_id=args.enterprise_kb,
            handbook_id=args.handbook,
            topic=args.topic,
            max_rounds=args.max_rounds,
            config={"language": args.language},
        )
        batch_id = batch["id"]

    print(f"batch_id={batch_id} name={name!r}")
    print(f"persona 数={len(persona_ids)} | 并发={BATCH_SESSION_CONCURRENCY} | "
          f"handbook={args.handbook} max_rounds={args.max_rounds} | language={args.language}")
    print("开始运行（同步阻塞，事件落库；进度见下）...\n")

    t0 = time.time()
    runner = BatchRunner(batch_id=batch_id)
    # 轻量进度打印：覆盖 _emit（无 asyncio loop 时原本静默）
    def _print_evt(evt: dict) -> None:
        t = evt.get("type")
        d = evt.get("data") or {}
        if t == "session_close":
            print(
                f"  [{d.get('completed', 0)+d.get('failed', 0)+d.get('cancelled', 0)}"
                f"/{d.get('total')}] persona={d.get('persona_id')} "
                f"outcome={d.get('outcome')} status={d.get('status')}"
                + (f" ERR={d.get('error')}" if d.get("error") else "")
            )
        elif t == "batch_done":
            print(f"\n批次完成：{d.get('status')} | "
                  f"completed={d.get('completed')} failed={d.get('failed')} "
                  f"cancelled={d.get('cancelled')} / {d.get('total')}")
    runner._emit = _print_evt          # type: ignore[assignment]
    runner._emit_sentinel = lambda: None  # type: ignore[assignment]

    runner._run_blocking()

    dt = time.time() - t0
    print(f"\n总耗时 {dt/60:.1f} 分钟 | batch_id={batch_id}")
    print(f"分析报告：python scripts/export_analysis_html.py 或走 /analysis 接口（batch_id={batch_id}）")


if __name__ == "__main__":
    main()
