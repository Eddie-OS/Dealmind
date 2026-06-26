"""导入 MatePad Air 对齐人设种子（A/B/C/D 均衡）→ 落库 + 补市场字段 + 抽 9 维压力。

读取 ``训练文件/air_personas_seed.json``（list[persona]，结构同 2.2 海外消费者人设_40.json），
默认 dry-run，加 ``--apply`` 才真正写库：

1. ``bulk_create_personas`` 批量导入（format_type=prompt_based）。
2. 对每条 ``update_persona`` 直写 country_code / country_name / currency / market_domains。
3. （需 LLM）逐条 ``extract_pressure_profile`` 抽 9 维参数写回；LLM 不可用时可加
   ``--skip-pressure`` 跳过（压力维度留默认 0.5，不影响跑对话）。

执行：
    python scripts/apply_air_personas.py                  # 预览
    python scripts/apply_air_personas.py --apply          # 落库 + 抽压力
    python scripts/apply_air_personas.py --apply --skip-pressure   # 落库，跳过抽压力
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from src.locales import get_market  # noqa: E402
from src.persona.pressure_extractor import extract_pressure_profile  # noqa: E402
from src.storage.db import (  # noqa: E402
    bulk_create_personas,
    get_connection,
    list_personas,
    update_persona,
)

JSON_PATH = ROOT / "训练文件" / "air_personas_seed.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认仅预览）")
    parser.add_argument("--skip-pressure", action="store_true", help="跳过 9 维压力抽取（LLM 不可用时）")
    parser.add_argument("--workers", type=int, default=5, help="压力抽取并发数")
    args = parser.parse_args()

    recs = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    print(f"读取 {len(recs)} 条 Air 人设 ← {JSON_PATH.name}\n")

    conn = get_connection()
    before = list_personas(conn)
    print(f"当前库内 {len(before)} 条 persona。")

    # 分布预览
    def _type_of(rec: dict) -> str:
        for t in rec.get("tags") or []:
            if str(t).startswith("类型"):
                return str(t)
        return "(未标类型)"

    dist_type: dict[str, int] = {}
    dist_cc: dict[str, int] = {}
    for r in recs:
        dist_type[_type_of(r)] = dist_type.get(_type_of(r), 0) + 1
        dist_cc[r["country_code"]] = dist_cc.get(r["country_code"], 0) + 1

    if not args.apply:
        print("\n[dry-run] 未写库。将执行：")
        print(f"  - 导入 {len(recs)} 条 Air 人设")
        print(f"  - 为每条补 country_code/currency/market_domains")
        print(f"  - {'跳过' if args.skip_pressure else '抽取'} 9 维压力")
        print("  - 类型分布：", dict(sorted(dist_type.items())))
        print("  - 国家分布：", dict(sorted(dist_cc.items())))
        print("\n加 --apply 执行。")
        conn.close()
        return 0

    # 1) 批量导入
    items = [
        {
            "name": r["name"],
            "format_type": "prompt_based",
            "prompt_text": r["prompt"],
            "source": r.get("source"),
            "tags": r.get("tags") or [],
            "locale": r.get("locale") or "zh-CN",
        }
        for r in recs
    ]
    new_ids = bulk_create_personas(conn, items)
    print(f"\n[1] 已导入 {len(new_ids)} 条，新 id：{new_ids[0]}..{new_ids[-1]}")

    # 2) 直写市场字段
    for pid, r in zip(new_ids, recs):
        mkt = get_market(r["country_code"])
        update_persona(
            conn,
            pid,
            country_code=r["country_code"],
            country_name=r.get("country_name") or mkt.name_cn,
            currency=r.get("currency") or mkt.currency,
            market_domains=list(mkt.market_domains),
        )
    print(f"[2] 已为 {len(new_ids)} 条补 country_code/currency/market_domains")

    # 3) 9 维压力抽取（可跳过）
    if args.skip_pressure:
        print("[3] 已跳过压力抽取（pressure_extracted=False，维度留默认 0.5）")
    else:
        def _extract(pid: int, prompt: str) -> tuple[int, dict]:
            return pid, extract_pressure_profile(prompt)

        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {
                pool.submit(_extract, pid, r["prompt"]): pid
                for pid, r in zip(new_ids, recs)
            }
            for fut in as_completed(futs):
                pid = futs[fut]
                try:
                    _, pressure = fut.result()
                except Exception as exc:  # noqa: BLE001
                    print(f"  ✗ 压力抽取 id={pid} 失败：{exc}")
                    continue
                update_persona(conn, pid, pressure=pressure, pressure_extracted=True)
                done += 1
        print(f"[3] 已抽取并写回 9 维压力 {done}/{len(new_ids)} 条")

    # 4) 体检
    after = list_personas(conn)
    new_set = set(new_ids)
    new_rows = [r for r in after if int(r["id"]) in new_set]
    missing_mkt = [int(r["id"]) for r in new_rows if not r.get("country_code") or not r.get("currency")]
    print("\n===== 体检 =====")
    print(f"persona 总数：{len(after)}（导入前 {len(before)}，新增 {len(new_ids)}）")
    print(f"新人设缺市场字段：{missing_mkt or '无'}")
    print("新人设类型分布：", dict(sorted(dist_type.items())))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
