"""V2-② 人设重构落库：导入 40 海外人设 + 删 4 CN + 补市场字段 + 9 维压力抽取。

读取 ``训练文件/2.2 海外消费者人设_40.json``，按以下步骤落库（默认 dry-run，
加 ``--apply`` 才真正写库）：

1. ``bulk_create_personas`` 导入 40 条（format_type=prompt_based）。
2. 对新建的每条 ``update_persona`` 直写 country_code / country_name / currency /
   market_domains（来自 spec 已知国家，比 infer 更准）。
3. 删除 4 个 CN 人设 id 32/35/39/40（sessions FK = ON DELETE SET NULL，历史会话保留、persona 链置空）。
4. 逐条 ``extract_pressure_profile`` 抽 9 维参数并写回（40 次 LLM 调用，并发）。
5. 打印最终分布与体检。

执行：
    python scripts/apply_persona_restructure.py            # 预览
    python scripts/apply_persona_restructure.py --apply    # 落库
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
    delete_persona,
    get_connection,
    list_personas,
    update_persona,
)

JSON_PATH = ROOT / "训练文件" / "2.2 海外消费者人设_40.json"
# 待删除的 4 个 CN 人设（id → 期望姓名前缀，做安全校验）
CN_DELETE = {32: "陈墨", 35: "林悦", 39: "阿强", 40: "苏苏"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认仅预览）")
    parser.add_argument("--workers", type=int, default=5, help="压力抽取并发数")
    args = parser.parse_args()

    recs = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    print(f"读取 {len(recs)} 条新人设 ← {JSON_PATH.name}\n")

    conn = get_connection()
    before = list_personas(conn)
    by_id = {int(r["id"]): r for r in before}
    print(f"当前库内 {len(before)} 条 persona。")

    # 校验待删除 CN 人设
    del_ok: list[int] = []
    for pid, expect in CN_DELETE.items():
        row = by_id.get(pid)
        if not row:
            print(f"  [删除] id={pid} 不存在，跳过")
            continue
        nm = row.get("name") or ""
        if expect in nm:
            del_ok.append(pid)
            print(f"  [删除] id={pid} {nm}  ✓ 匹配「{expect}」")
        else:
            print(f"  [删除] id={pid} {nm}  ✗ 与期望「{expect}」不符 → 跳过保护")

    if not args.apply:
        print("\n[dry-run] 未写库。将执行：")
        print(f"  - 导入 {len(recs)} 条新海外人设")
        print(f"  - 删除 CN 人设 id：{del_ok}")
        print("  - 为新人设补 country_code/currency/market_domains + 抽 9 维压力")
        dist: dict[str, int] = {}
        for r in recs:
            dist[r["country_code"]] = dist.get(r["country_code"], 0) + 1
        print("  - 新人设国家分布：", dict(sorted(dist.items())))
        print("\n加 --apply 执行。")
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

    # 3) 删除 CN
    for pid in del_ok:
        delete_persona(conn, pid)
    print(f"[3] 已删除 CN 人设：{del_ok}")

    # 4) 9 维压力抽取（并发）
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
    print(f"[4] 已抽取并写回 9 维压力 {done}/{len(new_ids)} 条")

    # 5) 体检
    after = list_personas(conn)
    cn = [r for r in after if (r.get("country_code") or "") == "CN"]
    new_set = set(new_ids)
    new_rows = [r for r in after if int(r["id"]) in new_set]
    missing_mkt = [int(r["id"]) for r in new_rows if not r.get("country_code") or not r.get("currency")]
    not_pressed = [int(r["id"]) for r in new_rows if not r.get("pressure_extracted")]
    dist: dict[str, int] = {}
    for r in after:
        dist[r.get("country_code") or "(空)"] = dist.get(r.get("country_code") or "(空)", 0) + 1

    print("\n===== 体检 =====")
    print(f"persona 总数：{len(after)}（期望 80）")
    print(f"CN 人设剩余：{len(cn)}（期望 0）")
    print(f"新人设缺市场字段：{missing_mkt or '无'}")
    print(f"新人设未抽压力：{not_pressed or '无'}")
    print("国家分布：", dict(sorted(dist.items())))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
