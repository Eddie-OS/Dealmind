"""Persona 加载工具：DB 行 → PersonaProfile。

被 src/runner.py (CLI) 和 src/api/routes_sessions.py (Web) 共享，
确保两条入口对同一 persona 数据的解读完全一致。
"""

from __future__ import annotations

from typing import Any

from src.schema import PersonaProfile, PressureProfile


_PRESSURE_KEYS = (
    "price_sensitivity", "trust_threshold", "patience",
    "competitor_awareness", "decision_power", "emotion_volatility",
    "need_urgency", "skepticism", "bargaining_aggressiveness",
)


def persona_from_db_row(row: dict[str, Any]) -> PersonaProfile:
    """把 personas 表行（已由 db._row_to_persona 解码）转 PersonaProfile。

    - structured 行的 profile 含 age/occupation/personality/...
    - prompt_based 行的 profile 为空，prompt_text 给出全部角色描述
    - 9 维 pressure 字段缺失时默认 0.5
    """
    profile_extra: dict[str, Any] = row.get("profile") or {}
    pressure_dict: dict[str, Any] = row.get("pressure") or {}
    pressure = PressureProfile(**{
        k: float(pressure_dict.get(k, 0.5)) for k in _PRESSURE_KEYS
    })

    # v0.2.1 市场字段：DB 显式值优先；为空时按 source/prompt_text/tags 反推国家，
    # 否则 country_code 永远是 None，sales/judge/coach/preflight 全部回退到 GLOBAL，
    # web_search 锁不住本地域名 → 报不出当地竞品实价。
    country_code = (row.get("country_code") or "").strip() or None
    country_name = row.get("country_name") or None
    currency = row.get("currency") or None
    market_domains = list(row.get("market_domains") or [])
    if not country_code:
        from src.locales import infer_market_from_persona
        mkt = infer_market_from_persona(
            source=row.get("source"),
            prompt_text=row.get("prompt_text"),
            tags=row.get("tags") or [],
        )
        if mkt.code != "GLOBAL":
            country_code = mkt.code
            country_name = country_name or mkt.name_cn
            currency = currency or mkt.currency
            if not market_domains:
                market_domains = list(mkt.market_domains)

    return PersonaProfile(
        id=f"db:{row['id']}",
        name=row["name"],
        format_type=row.get("format_type") or "structured",
        prompt_text=row.get("prompt_text"),
        tags=row.get("tags") or [],
        locale=row.get("locale") or "zh-CN",
        source=row.get("source"),
        age=profile_extra.get("age"),
        occupation=profile_extra.get("occupation"),
        budget=profile_extra.get("budget"),
        personality=profile_extra.get("personality") or "",
        pain_points=profile_extra.get("pain_points") or [],
        objection_style=profile_extra.get("objection_style") or "",
        purchase_goal=profile_extra.get("purchase_goal") or "",
        pressure_profile=pressure,
        country_code=country_code,
        country_name=country_name,
        currency=currency,
        market_domains=market_domains,
    )
