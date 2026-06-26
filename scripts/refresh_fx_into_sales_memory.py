"""统计人设包覆盖的国家，调一次汇率 API，把 CNY→各国货币 的汇率写进销冠 agent 记忆。

用途：销冠在本地无官方价时，用 Handbook 的 ¥ 原价按真实汇率换算成当地估价。
- 国家来源：personas 表（按 persona_from_db_row 的 country_code，含 source/prompt/tags 推断）
- 汇率来源：open.er-api.com（免 key，base=CNY）
- 落地位置：agent_profiles(name='sales').extra['fx_rates']

直接运行：python scripts/refresh_fx_into_sales_memory.py
加 --dry-run 只统计 + 拉取、不写库。
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import datetime, timezone

# 清掉可能失效的代理环境变量（与启动脚本一致），保证 httpx 直连
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from src.locales import COUNTRY_REGISTRY, get_market
from src.persona.loader import persona_from_db_row
from src.storage import db as sdb

FX_API = "https://open.er-api.com/v6/latest/CNY"
PROFILE_NAME = "sales"


def tally_countries() -> tuple[Counter, int]:
    """遍历全部 persona，按 country_code 统计国家分布（GLOBAL 单列）。"""
    with sdb.connection_scope() as conn:
        rows = sdb.list_personas(conn)
    counter: Counter = Counter()
    for row in rows:
        try:
            persona = persona_from_db_row(row)
            code = (getattr(persona, "country_code", None) or "GLOBAL").upper()
        except Exception:
            code = "GLOBAL"
        counter[code] += 1
    return counter, len(rows)


def fetch_fx() -> dict:
    """拉一次 CNY→各币种汇率（免 key）。"""
    resp = httpx.get(FX_API, timeout=20, trust_env=False)
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise RuntimeError(f"FX API 返回异常：{data.get('result')}")
    return data


def main() -> None:
    dry = "--dry-run" in sys.argv

    counter, total = tally_countries()
    real_countries = [c for c in counter if c != "GLOBAL"]
    print(f"人设总数：{total}")
    print(f"覆盖国家数（不含 GLOBAL）：{len(real_countries)}")
    print("国家分布：")
    for code, n in counter.most_common():
        mkt = get_market(code) if code != "GLOBAL" else None
        label = f"{mkt.name_cn}({mkt.currency})" if mkt else "全球/未识别"
        print(f"  {code:<7} {label:<18} {n} 人")

    data = fetch_fx()
    all_rates = data.get("rates") or {}

    # 只保留人设覆盖国家的币种（GLOBAL→USD 也一并带上做兜底）
    by_country: dict[str, dict] = {}
    rates: dict[str, float] = {}
    needed_codes = real_countries + (["GLOBAL"] if counter.get("GLOBAL") else [])
    seen_ccy: set[str] = set()
    for code in needed_codes:
        mkt = get_market(code)  # GLOBAL→DEFAULT_GLOBAL_MARKET(USD)
        ccy = mkt.currency
        rate = all_rates.get(ccy)
        if rate is None:
            print(f"  [warn] 汇率表缺币种 {ccy}（{code}），跳过")
            continue
        by_country[mkt.code] = {
            "name": mkt.name_cn,
            "currency": ccy,
            "symbol": mkt.currency_symbol,
            "cny_to_local": rate,
            "persona_count": counter.get(code, 0),
        }
        if ccy not in seen_ccy:
            rates[ccy] = rate
            seen_ccy.add(ccy)

    fx_memory = {
        "base": "CNY",
        "source": "open.er-api.com",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_time_last_update_utc": data.get("time_last_update_utc"),
        "api_time_next_update_utc": data.get("time_next_update_utc"),
        "persona_country_count": len(real_countries),
        "note": "1 CNY = rate 当地货币；销冠用 Handbook ¥ 原价 × rate 得当地估价（标注估算，以本地发布价为准）",
        "rates": dict(sorted(rates.items())),
        "by_country": dict(sorted(by_country.items())),
    }

    print(f"\n已构建汇率记忆：base=CNY，币种 {len(rates)} 种，覆盖国家 {len(by_country)} 个")
    print("  示例：", {k: fx_memory["rates"][k] for k in list(fx_memory["rates"])[:6]})

    if dry:
        print("\n[dry-run] 未写库。")
        return

    with sdb.connection_scope() as conn:
        profile = sdb.get_agent_profile(conn, PROFILE_NAME) or {}
        extra = dict(profile.get("extra") or {})
        extra["fx_rates"] = fx_memory
        sdb.update_agent_profile(
            conn,
            PROFILE_NAME,
            extra=extra,
            bump_version=True,
            version_comment=f"刷新汇率记忆：base=CNY，{len(rates)} 币种 / {len(by_country)} 国",
        )
    print("\n[OK] 已写入销冠 agent 记忆 extra['fx_rates']（并建版本快照）。")


if __name__ == "__main__":
    main()
