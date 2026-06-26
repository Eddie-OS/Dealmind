"""Handbook Analysis 模块 · 分析任务 API

提供给前端 AnalysisReport 页面用的端点：

  POST   /api/analysis/jobs           创建并立即异步启动
  GET    /api/analysis/jobs           列表（按 batch_id / session_id / status 过滤）
  GET    /api/analysis/jobs/{id}      详情（jobs 行 + summary_json）
  GET    /api/analysis/jobs/{id}/turns           分类+评分详情（按 category 过滤）
  GET    /api/analysis/jobs/{id}/persona_insights  persona 维度洞察
  POST   /api/analysis/jobs/{id}/cancel          取消正在跑的任务
  DELETE /api/analysis/jobs/{id}                 删除（级联 classifications / insights）

数据源约束（v2 schema）：
  CreatePayload 必须二选一：session_id 或 batch_id。
  handbook_id 可空 — 自动套用全库唯一 ready handbook。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.analyzers.analysis_runner import (
    get_runner,
    start_analysis_job,
)
from src.storage import db as storage_db


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ============================================================
# Pydantic
# ============================================================

class CreateAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: Optional[int] = None
    session_id: Optional[str] = None
    handbook_id: Optional[int] = Field(
        default=None,
        description="可空 — 兜底用全库唯一 ready Handbook（决策 4 自动套用）",
    )

    @model_validator(mode="after")
    def _check_source(self) -> "CreateAnalysisPayload":
        if not self.batch_id and not self.session_id:
            raise ValueError("必须提供 batch_id 或 session_id 之一")
        if self.batch_id and self.session_id:
            raise ValueError("batch_id 与 session_id 互斥")
        return self


class AnalysisJobInfo(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    batch_id: Optional[int] = None
    session_id: Optional[str] = None
    handbook_id: Optional[int] = None
    status: str
    progress: float
    total_turns: int
    classified_turns: int
    error_msg: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    created_at: str
    updated_at: str


# ============================================================
# 路由
# ============================================================

@router.post("/jobs", summary="创建并启动分析任务")
def create_analysis_job_endpoint(payload: CreateAnalysisPayload) -> dict[str, Any]:
    # 资源存在性校验
    with storage_db.connection_scope() as conn:
        if payload.batch_id is not None:
            b = storage_db.get_batch_job(conn, payload.batch_id)
            if not b:
                raise HTTPException(404, f"batch_id={payload.batch_id} 不存在")
        if payload.session_id is not None:
            s = storage_db.get_session_by_id(conn, payload.session_id)
            if not s:
                raise HTTPException(404, f"session_id={payload.session_id} 不存在")
        if payload.handbook_id is not None:
            hb = storage_db.get_handbook(conn, payload.handbook_id)
            if not hb:
                raise HTTPException(404, f"handbook_id={payload.handbook_id} 不存在")
        else:
            # 检查兜底可用
            default_id = storage_db.resolve_default_handbook_id(conn)
            if not default_id:
                raise HTTPException(
                    400,
                    "未指定 handbook_id 且全库没有唯一 ready Handbook，无法自动套用",
                )

    try:
        job_id = start_analysis_job(
            batch_id=payload.batch_id,
            session_id=payload.session_id,
            handbook_id=payload.handbook_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("启动分析任务失败")
        raise HTTPException(500, f"启动失败: {exc}") from exc

    with storage_db.connection_scope() as conn:
        job = storage_db.get_analysis_job(conn, job_id)
    return {"job_id": job_id, "job": job}


@router.get("/jobs", summary="列出分析任务")
def list_analysis_jobs_endpoint(
    batch_id: Optional[int] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    handbook_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        rows = storage_db.list_analysis_jobs(
            conn,
            batch_id=batch_id, session_id=session_id,
            handbook_id=handbook_id, status=status,
            limit=limit,
        )
    return {"items": rows, "total": len(rows)}


@router.get("/jobs/{job_id}", summary="任务详情 + summary")
def get_analysis_job_endpoint(job_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        job = storage_db.get_analysis_job(conn, job_id)
    if not job:
        raise HTTPException(404, f"job_id={job_id} 不存在")
    # 解析 summary_json
    import json
    summary: dict[str, Any] = {}
    if job.get("summary_json"):
        try:
            summary = json.loads(job["summary_json"])
        except Exception:  # noqa: BLE001
            summary = {"_parse_error": True}
    job["summary"] = summary
    job.pop("summary_json", None)
    return {"job": job}


@router.get("/jobs/{job_id}/turns", summary="分类+评分明细")
def list_turns_endpoint(
    job_id: int,
    category_id: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        if not storage_db.get_analysis_job(conn, job_id):
            raise HTTPException(404, f"job_id={job_id} 不存在")
        rows = storage_db.list_turn_classifications(
            conn, job_id,
            category_id=category_id, limit=limit,
        )
    # 反序列化 JSON 字段
    import json
    for r in rows:
        for k in ("scores_json", "issues_json"):
            raw = r.pop(k, None)
            short = k.replace("_json", "")
            if raw:
                try:
                    r[short] = json.loads(raw)
                except Exception:  # noqa: BLE001
                    r[short] = None
            else:
                r[short] = None
    return {"items": rows, "total": len(rows)}


@router.get("/jobs/{job_id}/persona_insights", summary="persona 维度洞察")
def list_persona_insights_endpoint(job_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        if not storage_db.get_analysis_job(conn, job_id):
            raise HTTPException(404, f"job_id={job_id} 不存在")
        rows = storage_db.list_analysis_persona_insights(conn, job_id)
    import json
    for r in rows:
        for k in ("top_concerns_json", "sample_objections_json"):
            raw = r.pop(k, None)
            short = k.replace("_json", "")
            if raw:
                try:
                    r[short] = json.loads(raw)
                except Exception:  # noqa: BLE001
                    r[short] = None
            else:
                r[short] = None
    return {"items": rows, "total": len(rows)}


@router.post("/jobs/{job_id}/cancel", summary="取消正在跑的任务")
def cancel_analysis_job_endpoint(job_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        if not storage_db.get_analysis_job(conn, job_id):
            raise HTTPException(404, f"job_id={job_id} 不存在")
    runner = get_runner(job_id)
    if not runner:
        return {"cancelled": False, "reason": "任务不在活跃运行池中（可能已完成）"}
    runner.request_cancel()
    return {"cancelled": True}


@router.delete("/jobs/{job_id}", summary="删除分析任务（级联）")
def delete_analysis_job_endpoint(job_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        ok = storage_db.delete_analysis_job(conn, job_id)
    if not ok:
        raise HTTPException(404, f"job_id={job_id} 不存在")
    return {"deleted": True, "job_id": job_id}


# ============================================================
# 导出（单 job） · 给 SessionHistory 批量导出和报告页"下载报告"复用
# ============================================================

_EXPORT_MEDIA = {
    "json": ("application/json; charset=utf-8", "json"),
    "md":   ("text/markdown; charset=utf-8",     "md"),
    "html": ("text/html; charset=utf-8",         "html"),
}


def _load_job_with_summary(job_id: int) -> dict[str, Any]:
    with storage_db.connection_scope() as conn:
        job = storage_db.get_analysis_job(conn, job_id)
    if not job:
        raise HTTPException(404, f"job_id={job_id} 不存在")
    summary: dict[str, Any] = {}
    raw = job.pop("summary_json", None)
    if raw:
        try:
            summary = json.loads(raw)
        except Exception:  # noqa: BLE001
            summary = {"_parse_error": True}
    job["summary"] = summary
    return job


def render_analysis_markdown(job: dict[str, Any]) -> str:
    """把分析任务结果渲染成人类可读的 Markdown 报告。

    给单文件下载 + bulk_export zip 包共用。结构对齐前端 AnalysisReport
    最重要的几个板块：封面 / KPI / 6 维评分 / 健康度 / 强弱项 /
    建议 / 关键数字。
    """
    s = job.get("summary") or {}
    lines: list[str] = []
    push = lines.append

    src_label = (
        f"会话 `{job.get('session_id')}`"
        if job.get("session_id")
        else f"批次 #{job.get('batch_id')}"
    )
    push(f"# 分析报告 · {src_label}")
    push("")
    push(f"- **任务 ID**: {job.get('id')}")
    push(f"- **状态**: {job.get('status')}")
    push(f"- **Handbook**: {s.get('handbook_name') or '-'}（id={job.get('handbook_id')}）")
    push(f"- **会话数**: {s.get('session_count', 0)} · **总分类条数**: "
         f"{s.get('total_classifications', 0)}")
    push(f"- **生成时间**: {s.get('generated_at') or job.get('ended_at') or '-'}")
    push("")

    cov_pct = s.get("coverage_pct")
    if cov_pct is not None:
        push("## 一、覆盖率")
        push(f"- Handbook 条目覆盖：**{cov_pct:.1f}%**"
             f"（{s.get('categories_covered', 0)} / "
             f"{s.get('categories_total', 0)}）")
        for g, stat in (s.get("coverage_by_group") or {}).items():
            push(f"  - {g}: "
                 f"{stat.get('coverage_pct', 0):.0f}%覆盖 · "
                 f"质量 {stat.get('weighted_avg_quality', 0):.1f}/10")
        push("")

    conv = (s.get("conversation_persona_breakdown") or {}).get("distribution") or []
    if conv:
        cp = s.get("conversation_persona_breakdown") or {}
        push("## 对话客户类型分布（运行时 LLM 判定）")
        push(f"- 共 {cp.get('session_total', 0)} 场，已判定 "
             f"{cp.get('classified', 0)} 场")
        for r in conv:
            p = r.get("persona") or "?"
            name = "未判定" if p == "?" else f"{p} · {r.get('persona_label') or ''}"
            line = f"- **{name}**：{int(r.get('sessions', 0))} 场"
            if p != "?":
                line += (f" · 本类专属话术覆盖 "
                         f"{int(r.get('own_cats_covered', 0))}/"
                         f"{int(r.get('own_cats_total', 0))}"
                         f"（{float(r.get('own_coverage_pct', 0)):.0f}%）")
            push(line)
            oc = r.get("outcomes") or {}
            if oc:
                push("  - 结局：" + "、".join(f"{k} {v}" for k, v in oc.items()))
        push("")

    weak = s.get("weak_categories") or []
    if weak:
        push("## 二、弱项 Top（按平均质量升序）")
        for w in weak[:8]:
            push(f"- **{w.get('label') or w.get('category_id')}** · "
                 f"平均 {float(w.get('avg_quality', 0)):.1f}/10 · "
                 f"命中 {w.get('hits', 0)} 次")
            if w.get("reason"):
                push(f"  - {w['reason']}")
            for it in (w.get("issue_top") or [])[:3]:
                push(f"  - issue: {it.get('text')}（×{it.get('count')}）")
        push("")

    strong = s.get("strong_categories") or []
    if strong:
        push("## 三、强项 Top")
        for st in strong[:6]:
            push(f"- **{st.get('label') or st.get('category_id')}** · "
                 f"平均 {float(st.get('avg_quality', 0)):.1f}/10 · "
                 f"命中 {st.get('hits', 0)} 次")
            if st.get("highlight_reason"):
                push(f"  - {st['highlight_reason']}")
        push("")

    uncov = s.get("uncovered_categories") or []
    if uncov:
        push("## 四、未覆盖条目")
        for u in uncov:
            push(f"- {u}")
        push("")

    revisions = s.get("handbook_revisions") or []
    if revisions:
        _rev_grp = {"intro": "① 一句话定位", "sell": "③ 核心卖点", "comp": "③ 竞品对比",
                    "param": "⑤ 核心参数", "faq": "⑨ FAQ", "demo": "⑩ 现场演示",
                    "open": "① 开场破冰", "say": "② 核心卖点（按人设）",
                    "compete": "③ 竞品应对", "respond": "④ 常见问答"}
        _is_pb = s.get("doc_type") == "playbook_v1"
        push(f"## 五、Handbook 迭代建议 · 逐条（{len(revisions)} 条）")
        if _is_pb:
            push("> 按 开场/卖点/竞品/FAQ 对全部条目逐条给建议，即使表现好也给增强点，每条附 TOP3 原声。")
        else:
            push("> 按 1/3/3/5/9/10 对全部条目逐条给建议，即使表现好也给增强点，每条附 TOP3 原声。")
        push("")
        cur_grp = None
        for it in revisions:
            g = it.get("group")
            if g != cur_grp:
                cur_grp = g
                push(f"### {_rev_grp.get(g, g)}")
            cov = it.get("coverage") or {}
            cov_line = (
                f"命中 {cov.get('hits', 0)} 次 / {cov.get('sessions', 0)} 场 · "
                f"均分 {float(cov.get('avg_quality', 0)):.1f}"
                if cov.get("covered") else "本批 0 次引用（死条目）"
            )
            _qmap = {"ok": "可直接采纳", "review": "需人工确认", "kept_original": "仅保留原文"}
            _qtxt = _qmap.get(it.get("quality_flag") or "", "")
            _qsuffix = f" · {_qtxt}" if _qtxt else ""
            push(f"- **[{it.get('status')}] {it.get('label')}** · {cov_line}{_qsuffix}")
            if it.get("handbook_text"):
                push(f"  - 原文：{it['handbook_text']}")
            if it.get("assessment"):
                push(f"  - 评估：{it['assessment']}")
            if it.get("suggestion"):
                push(f"  - 建议：{it['suggestion']}")
            if it.get("revised_text"):
                push(f"  - 修改后：{it['revised_text']}")
            if it.get("fact_warnings"):
                push(f"  - ⚠ 事实核查：{'；'.join(it['fact_warnings'])}"
                     f"（手册外信息，需人工确认）")
            for q in (it.get("top_quotes") or [])[:3]:
                push(f"  - 原声[{float(q.get('score', 0)):.1f}] "
                     f"{q.get('persona_name', '-')}")
                if q.get("customer_question"):
                    push(f"    - 客户原文：{q['customer_question']}")
                push(f"    - 销售原文：{q.get('content', '')}")
        push("")

    exc_groups = ((s.get("excellent_by_group") or {}).get("groups")) or []
    if exc_groups:
        push("## 七、优秀话术原声（按手册结构归类）")
        push("> 优秀 = 行为信号（客户购买信号↑/态度转正）⊕ LLM 优秀度，"
             "不以「是否照搬手册」评判；「手册外精彩话术」可直接喂迭代建议。")
        push("")
        for g in exc_groups:
            push(f"### {g.get('label')}（{g.get('count', 0)} 条）")
            for t in (g.get("items") or [])[:8]:
                push(f"- **{float(t.get('excellence_score', 0)):.1f}/10** · "
                     f"{t.get('persona_name', '-')} · 购买信号 "
                     f"{float(t.get('purchase_signal_before', 0)):.1f}→"
                     f"{float(t.get('purchase_signal_after', 0)):.1f}")
                if t.get("customer_question"):
                    push(f"  > 客户：{t['customer_question']}")
                push(f"  > 销冠：{t.get('sales_content', '')}")
                for r in (t.get("why_good") or [])[:3]:
                    push(f"  - 亮点：{r}")
            push("")

    problematic = s.get("problematic_turns") or []
    if problematic:
        push("## 八、问题话术 Top")
        for t in problematic[:8]:
            push(f"### R{t.get('turn_idx')} · {t.get('persona_name', '-')} "
                 f"· 平均 {float(t.get('avg_quality', 0)):.1f}/10")
            if t.get("customer_question"):
                push(f"> 客户：{t['customer_question']}")
            push(f"> 销冠：{t.get('sales_content', '')}")
            for r in (t.get("why_bad") or [])[:3]:
                push(f"- 问题：{r}")
            if t.get("suggestion"):
                push(f"- 建议：{t['suggestion']}")
            push("")

    return "\n".join(lines)


@router.get("/jobs/{job_id}/export", summary="导出单份分析报告（md / json）")
def export_analysis_job_endpoint(
    job_id: int, format: str = Query("md"),
) -> Response:
    fmt = format.lower()
    if fmt not in _EXPORT_MEDIA:
        raise HTTPException(400, f"format 必须是 md|json|html，收到 {format!r}")
    job = _load_job_with_summary(job_id)
    if fmt == "json":
        body = json.dumps(job, ensure_ascii=False, indent=2)
    elif fmt == "html":
        from src.analyzers.report_html import render_analysis_html
        body = render_analysis_html(job)
    else:
        body = render_analysis_markdown(job)
    media_type, ext = _EXPORT_MEDIA[fmt]
    filename = f"analysis-{job_id}.{ext}"
    # HTML 用 inline，方便浏览器直接打开预览并打印成 PDF；其余仍走下载。
    disposition = "inline" if fmt == "html" else "attachment"
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Length": str(len(body.encode("utf-8"))),
        },
    )


def find_latest_completed_job_for_session(session_id: str) -> Optional[dict[str, Any]]:
    """给 SessionHistory bulk_export 用：找该会话最新已完成的分析报告。"""
    with storage_db.connection_scope() as conn:
        rows = storage_db.list_analysis_jobs(
            conn,
            session_id=session_id,
            status="completed",
            limit=1,
        )
    if not rows:
        return None
    return _load_job_with_summary(int(rows[0]["id"]))
