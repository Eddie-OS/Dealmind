"""Stage 8：首页数据看板聚合接口。

3 个纯 SQL 聚合接口，全部 read-only：
  GET /api/dashboard/summary
  GET /api/dashboard/trends?days=30
  GET /api/dashboard/persona_difficulty?limit=15

SQL 设计要点：
  - 所有指标基于 sessions + evaluations 两张表，不再扫 turns（避免大表全表）
  - dialogue_quality_score 取 json_extract(evaluations.feedback_json,'$.dialogue_quality_score')
    平均值（仅 evaluator_role='judge' 的样本）
  - outcome 来自 json_extract(sessions.summary_json,'$.outcome')
  - 空数据返回 0 / [] 而非报错，前端 el-empty 占位即可
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query

from src.storage import db as storage_db


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ============================================================
# 1. summary：4 核心指标 + outcome 分布
# ============================================================


@router.get("/summary", summary="首页 4 大核心指标 + outcome 分布")
def get_summary() -> dict[str, Any]:
    """返回:
        total_sessions   全部会话数
        total_personas   人设总数
        avg_quality      所有 judge 评分的 dialogue_quality_score 平均（0~10）
        deal_rate        DEAL_DONE / 已结束会话（0~1）
        outcome_dist     [{outcome, count}]
        finished_count   已结束（done/cancelled/failed）会话数
    """
    with storage_db.connection_scope() as conn:
        total_sessions = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions"
        ).fetchone()["n"]

        total_personas = conn.execute(
            "SELECT COUNT(*) AS n FROM personas"
        ).fetchone()["n"]

        # judge 评分平均（NULL/非数字会被 AVG 忽略）
        avg_row = conn.execute(
            """
            SELECT AVG(CAST(
                json_extract(feedback_json, '$.dialogue_quality_score') AS REAL
            )) AS avg_q
            FROM evaluations
            WHERE evaluator_role = 'judge'
              AND json_extract(feedback_json, '$.dialogue_quality_score') IS NOT NULL
            """
        ).fetchone()
        avg_quality = float(avg_row["avg_q"]) if avg_row["avg_q"] is not None else 0.0

        # outcome 分布（只统计有 outcome 字段的）
        rows = conn.execute(
            """
            SELECT
                COALESCE(json_extract(summary_json, '$.outcome'), 'UNKNOWN') AS outcome,
                COUNT(*) AS n
            FROM sessions
            WHERE json_extract(summary_json, '$.outcome') IS NOT NULL
            GROUP BY outcome
            ORDER BY n DESC
            """
        ).fetchall()
        outcome_dist = [{"outcome": r["outcome"], "count": int(r["n"])} for r in rows]

        # 已结束会话数 = 状态非 pending/running
        finished_row = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE status NOT IN ('pending', 'running')"
        ).fetchone()
        finished_count = int(finished_row["n"]) if finished_row else 0

        deal_count = sum(
            r["count"] for r in outcome_dist if r["outcome"] == "DEAL_DONE"
        )
        deal_rate = (deal_count / finished_count) if finished_count > 0 else 0.0

    return {
        "total_sessions": int(total_sessions),
        "total_personas": int(total_personas),
        "avg_quality": round(avg_quality, 2),
        "deal_rate": round(deal_rate, 3),
        "outcome_dist": outcome_dist,
        "finished_count": finished_count,
        "deal_count": deal_count,
    }


# ============================================================
# 2. trends：近 N 天每日会话数 + 平均质量
# ============================================================


@router.get("/trends", summary="近 N 天每日会话数 + 平均质量分曲线")
def get_trends(days: int = Query(30, ge=1, le=365)) -> dict[str, Any]:
    """返回:
        days       连续 N 天日期数组（YYYY-MM-DD，最旧到最新）
        sessions   对应日的会话数
        quality    对应日的 judge 平均质量分（无样本则 0）
    缺数据日期都补 0，前端折线图就不会出现断点。
    """
    # 注意时区：使用 server 本地日期；与前端展示一致即可
    today = date.today()
    start = today - timedelta(days=days - 1)
    date_list = [(start + timedelta(days=i)).isoformat() for i in range(days)]

    with storage_db.connection_scope() as conn:
        # 每日 session 数（以 started_at 计；pending 没 started_at 的不计）
        # SQLite SUBSTR 取 YYYY-MM-DD（ISO8601 头 10 个字符）
        sess_rows = conn.execute(
            """
            SELECT SUBSTR(started_at, 1, 10) AS d, COUNT(*) AS n
            FROM sessions
            WHERE started_at IS NOT NULL
              AND SUBSTR(started_at, 1, 10) >= ?
            GROUP BY d
            """,
            (start.isoformat(),),
        ).fetchall()
        sess_map = {r["d"]: int(r["n"]) for r in sess_rows}

        # 每日平均质量（按 evaluations.created_at 聚合）
        qual_rows = conn.execute(
            """
            SELECT SUBSTR(created_at, 1, 10) AS d,
                   AVG(CAST(json_extract(feedback_json, '$.dialogue_quality_score') AS REAL)) AS avg_q
            FROM evaluations
            WHERE evaluator_role = 'judge'
              AND json_extract(feedback_json, '$.dialogue_quality_score') IS NOT NULL
              AND SUBSTR(created_at, 1, 10) >= ?
            GROUP BY d
            """,
            (start.isoformat(),),
        ).fetchall()
        qual_map = {
            r["d"]: round(float(r["avg_q"]), 2)
            for r in qual_rows if r["avg_q"] is not None
        }

    return {
        "days": date_list,
        "sessions": [sess_map.get(d, 0) for d in date_list],
        "quality": [qual_map.get(d, 0.0) for d in date_list],
    }


# ============================================================
# 3. persona_difficulty：各 persona 平均质量（低=难）
# ============================================================


@router.get(
    "/persona_difficulty",
    summary="各 persona 平均质量分 + 会话数（低质量 = 客户更难搞）",
)
def get_persona_difficulty(limit: int = Query(15, ge=1, le=100)) -> dict[str, Any]:
    """对每个被使用过的 persona：
        - sessions   该 persona 跑过的会话数
        - avg_quality 全部 judge 评分均值（0~10，低 = 难）
        - deal_count  outcome=DEAL_DONE 数
        - tags        persona.tags_json（首个 tag 用于前端分组着色）
    按 avg_quality 升序（最难的在前），最多 limit 条。
    """
    sql = """
    SELECT
        s.persona_id AS persona_id,
        COALESCE(p.name, '#' || s.persona_id) AS persona_name,
        p.tags_json AS tags_json,
        COUNT(DISTINCT s.id) AS sessions,
        SUM(CASE
            WHEN json_extract(s.summary_json, '$.outcome') = 'DEAL_DONE'
            THEN 1 ELSE 0
        END) AS deal_count,
        AVG(CAST(
            json_extract(e.feedback_json, '$.dialogue_quality_score') AS REAL
        )) AS avg_q
    FROM sessions s
    LEFT JOIN personas p   ON s.persona_id = p.id
    LEFT JOIN evaluations e ON e.session_id = s.id AND e.evaluator_role = 'judge'
    WHERE s.persona_id IS NOT NULL
      AND s.status NOT IN ('pending')
    GROUP BY s.persona_id
    HAVING sessions > 0
    ORDER BY (CASE WHEN avg_q IS NULL THEN 1 ELSE 0 END) ASC,
             avg_q ASC
    LIMIT ?
    """
    with storage_db.connection_scope() as conn:
        rows = conn.execute(sql, (int(limit),)).fetchall()

    import json
    items: list[dict[str, Any]] = []
    for r in rows:
        tags_raw = r["tags_json"]
        try:
            tags = json.loads(tags_raw) if tags_raw else []
        except Exception:
            tags = []
        items.append({
            "persona_id": r["persona_id"],
            "persona_name": r["persona_name"],
            "sessions": int(r["sessions"]),
            "deal_count": int(r["deal_count"] or 0),
            "avg_quality": (
                round(float(r["avg_q"]), 2) if r["avg_q"] is not None else None
            ),
            "tags": tags if isinstance(tags, list) else [],
        })

    return {"items": items, "total": len(items)}


# ============================================================
# 4. insights：首页 4 张运营分析图（一次性返回，减少往返）
#    - deal_trend          每日成交率趋势
#    - hit_rate            每日「经验库命中率」（销售话术被知识/经验库检索命中的占比）
#    - experience_vs_deal  经验库规模(累计) × 当日成交率 散点 + 线性趋势
#    - objections          常见异议排行（persona 意图聚合）
#
# 口径说明（全部来自历史落库，可追溯）：
#    经验库 = excellent_phrases(优秀话术) + sales_cases(销售案例) 的累计沉淀。
#    经验库规模 = 截至当日累计条数。
#    成交率 = 当日 outcome=DEAL_DONE / 当日有结论(outcome 非空)的会话。
#    命中率 = 当日 role=sales 的 turn 中，检索命中(used_product_kb / used_enterprise_kb /
#             used_handbook 任一非空)的占比。
#    异议   = role=persona 的 turn 的 intent 中归属异议类的聚合占比。
# ============================================================

# persona intent → 异议类目（合并同义意图）。非异议意图（positive_signal /
# vague_browsing / purchase_commitment 等）不计入异议排行。
_OBJECTION_MAP: dict[str, str] = {
    "price_objection": "价格异议",
    "price_inquiry": "价格异议",
    "price_clarification": "价格异议",
    "bargaining": "价格异议",
    "bargaining_push": "价格异议",
    "trust_question": "信任质疑·要证据",
    "need_clarification": "信息不足·待澄清",
    "competitor_compare": "竞品对比",
    "comparator_compare": "竞品对比",
    "walk_away_threat": "流失风险·想离开",
    "delay_ultimatum": "流失风险·想离开",
    "time_cost_objection": "周期/时间顾虑",
}


@router.get("/insights", summary="首页运营分析 4 图（成交率趋势/命中率/经验库×成交/异议排行）")
def get_insights(days: int = Query(30, ge=1, le=365)) -> dict[str, Any]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    start_iso = start.isoformat()
    date_list = [(start + timedelta(days=i)).isoformat() for i in range(days)]

    with storage_db.connection_scope() as conn:
        # ---- 每日成交 / 有结论会话数 ----
        deal_rows = conn.execute(
            """
            SELECT SUBSTR(started_at, 1, 10) AS d,
                   SUM(CASE WHEN json_extract(summary_json,'$.outcome')='DEAL_DONE'
                            THEN 1 ELSE 0 END) AS deals,
                   SUM(CASE WHEN json_extract(summary_json,'$.outcome') IS NOT NULL
                            THEN 1 ELSE 0 END) AS concluded
            FROM sessions
            WHERE started_at IS NOT NULL
              AND SUBSTR(started_at,1,10) >= ?
            GROUP BY d
            """,
            (start_iso,),
        ).fetchall()
        deal_map = {
            r["d"]: (int(r["deals"] or 0), int(r["concluded"] or 0)) for r in deal_rows
        }

        # ---- 经验库累计规模（基线 + 窗口内每日新增）----
        base_phr = conn.execute(
            "SELECT COUNT(*) n FROM excellent_phrases WHERE SUBSTR(created_at,1,10) < ?",
            (start_iso,),
        ).fetchone()["n"]
        base_case = conn.execute(
            "SELECT COUNT(*) n FROM sales_cases WHERE SUBSTR(created_at,1,10) < ?",
            (start_iso,),
        ).fetchone()["n"]
        baseline = int(base_phr or 0) + int(base_case or 0)

        grow_rows = conn.execute(
            """
            SELECT d, SUM(n) AS n FROM (
                SELECT SUBSTR(created_at,1,10) AS d, COUNT(*) AS n
                FROM excellent_phrases WHERE SUBSTR(created_at,1,10) >= ? GROUP BY d
                UNION ALL
                SELECT SUBSTR(created_at,1,10) AS d, COUNT(*) AS n
                FROM sales_cases WHERE SUBSTR(created_at,1,10) >= ? GROUP BY d
            ) GROUP BY d
            """,
            (start_iso, start_iso),
        ).fetchall()
        grow_map = {r["d"]: int(r["n"] or 0) for r in grow_rows}

        # ---- 每日命中率（sales turn 检索命中占比）----
        hit_rows = conn.execute(
            """
            SELECT SUBSTR(created_at,1,10) AS d,
                   COUNT(*) AS total,
                   SUM(CASE WHEN
                        COALESCE(json_array_length(json_extract(metadata_json,'$.used_product_kb')),0) > 0
                     OR COALESCE(json_array_length(json_extract(metadata_json,'$.used_enterprise_kb')),0) > 0
                     OR (json_extract(metadata_json,'$.used_handbook') IS NOT NULL
                         AND json_extract(metadata_json,'$.used_handbook') NOT IN ('', '[]', '0', 'false'))
                       THEN 1 ELSE 0 END) AS hits
            FROM turns
            WHERE role='sales' AND metadata_json IS NOT NULL
              AND SUBSTR(created_at,1,10) >= ?
            GROUP BY d
            """,
            (start_iso,),
        ).fetchall()
        hit_map = {
            r["d"]: (int(r["hits"] or 0), int(r["total"] or 0)) for r in hit_rows
        }

        # ---- 异议意图聚合 ----
        intent_rows = conn.execute(
            """
            SELECT json_extract(metadata_json,'$.intent') AS intent, COUNT(*) AS n
            FROM turns
            WHERE role='persona' AND metadata_json IS NOT NULL
              AND json_extract(metadata_json,'$.intent') IS NOT NULL
              AND SUBSTR(created_at,1,10) >= ?
            GROUP BY intent
            """,
            (start_iso,),
        ).fetchall()

    # ---------- 组装 deal_trend ----------
    deal_rate: list[float | None] = []
    for d in date_list:
        deals, concluded = deal_map.get(d, (0, 0))
        deal_rate.append(round(deals / concluded, 4) if concluded > 0 else None)

    # ---------- 组装 experience_vs_deal（散点 + 线性趋势）----------
    cumulative = baseline
    points: list[dict[str, Any]] = []
    for d in date_list:
        cumulative += grow_map.get(d, 0)
        deals, concluded = deal_map.get(d, (0, 0))
        if concluded > 0:  # 只取当天有成交结论的点，散点才有意义
            points.append({
                "day": d,
                "size": cumulative,
                "deal_rate": round(deals / concluded, 4),
                "concluded": concluded,
            })

    trend = _linear_fit(
        [p["size"] for p in points], [p["deal_rate"] for p in points]
    )

    # ---------- 组装 hit_rate ----------
    hit_rate: list[float | None] = []
    for d in date_list:
        hits, total = hit_map.get(d, (0, 0))
        hit_rate.append(round(hits / total, 4) if total > 0 else None)

    # ---------- 组装 objections ----------
    obj_counter: dict[str, int] = {}
    for r in intent_rows:
        label = _OBJECTION_MAP.get(r["intent"])
        if label is None:
            continue
        obj_counter[label] = obj_counter.get(label, 0) + int(r["n"] or 0)
    obj_total = sum(obj_counter.values())
    objections = [
        {
            "label": label,
            "count": cnt,
            "pct": round(cnt / obj_total, 4) if obj_total > 0 else 0.0,
        }
        for label, cnt in sorted(obj_counter.items(), key=lambda kv: kv[1], reverse=True)
    ]

    return {
        "days": date_list,
        "deal_trend": {"days": date_list, "deal_rate": deal_rate},
        "hit_rate": {"days": date_list, "rate": hit_rate},
        "experience_vs_deal": {"points": points, "trend": trend},
        "objections": objections,
    }


def _linear_fit(xs: list[float], ys: list[float]) -> dict[str, Any] | None:
    """最小二乘线性拟合，返回趋势线两端点供前端画虚线。点不足时返回 None。"""
    n = len(xs)
    if n < 2:
        return None
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    x_min, x_max = min(xs), max(xs)
    return {
        "slope": slope,
        "intercept": intercept,
        "x_min": x_min,
        "x_max": x_max,
        "y_at_min": round(slope * x_min + intercept, 4),
        "y_at_max": round(slope * x_max + intercept, 4),
    }
