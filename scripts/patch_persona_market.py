"""v0.2.1 真实性补丁：批量给所有 persona 补 country_code / currency / market_domains。

策略（user q1=auto_infer）：
1. 调 ``init_schema`` 触发列迁移（幂等）
2. 扫库；对每个 persona 跑 ``infer_market_from_persona``
3. 把推断结果写入 DB（用 ``update_persona``）
4. 打印结果表，方便人工核对

幂等：再次执行只会刷新已被人工修改的字段 → 故只在 country_code 为空时才写入，
有 country_code 的人工值保护不动。

执行：
    python scripts/patch_persona_market.py            # 默认只填空字段
    python scripts/patch_persona_market.py --force    # 强制重写所有 persona
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from src.locales import (  # noqa: E402
    DEFAULT_GLOBAL_MARKET,
    infer_market_from_persona,
)
from src.storage.db import (  # noqa: E402
    get_connection,
    init_schema,
    list_personas,
    update_persona,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="强制重写所有 persona")
    args = parser.parse_args()

    conn = get_connection()
    init_schema(conn)  # 触发列迁移
    rows = list_personas(conn)

    print(f"\n扫描到 {len(rows)} 个 persona，开始推断...\n")
    print(f"{'id':>3} | {'name':<22} | {'cc':<6} | {'cur':<4} | {'updated':<8} | domains")
    print("-" * 130)

    updated = 0
    skipped = 0
    for r in rows:
        pid = int(r["id"])
        name = (r.get("name") or "")[:22]
        existing_cc = r.get("country_code")

        if existing_cc and not args.force:
            print(f"{pid:>3} | {name:<22} | {existing_cc:<6} | "
                  f"{r.get('currency') or '-':<4} | SKIP     | (已存在)")
            skipped += 1
            continue

        mkt = infer_market_from_persona(
            locale=r.get("locale"),
            source=r.get("source"),
            prompt_text=r.get("prompt_text"),
            tags=r.get("tags"),
        )

        update_persona(
            conn,
            pid,
            country_code=mkt.code,
            country_name=mkt.name_cn,
            currency=mkt.currency,
            market_domains=list(mkt.market_domains),
        )
        flag = "YES" if mkt.code != DEFAULT_GLOBAL_MARKET.code else "GLOBAL"
        print(f"{pid:>3} | {name:<22} | {mkt.code:<6} | {mkt.currency:<4} | "
              f"{flag:<8} | {', '.join(mkt.market_domains)}")
        updated += 1

    print(f"\n完成：更新 {updated} 条，跳过 {skipped} 条（已存在）。")

    # 收尾：分国家分布统计
    rows2 = list_personas(conn)
    dist: dict[str, int] = {}
    for r in rows2:
        cc = r.get("country_code") or "(空)"
        dist[cc] = dist.get(cc, 0) + 1
    print("\n国家分布：")
    for cc, n in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {cc}: {n} 个")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
