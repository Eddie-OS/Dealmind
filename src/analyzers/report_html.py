"""分析报告 · 精排 HTML 渲染（打印即可转 PDF）。

与 ``routes_analysis.render_analysis_markdown`` 消费同一个 ``job["summary"]``
（v2.0 schema），但产出一份**固定模板、设计统一、内容由分析填充**的交付物，
对标用户提供的 V3.1 实战话术手册 PDF 的版式质感。

设计原则：
  - 单文件自包含（内联 <style>），浏览器直接打开 / 一键打印成 PDF；
  - 失败安全：任一字段缺失只跳过该板块，不抛异常；
  - 所有正文文本 HTML 转义，避免话术原声里的特殊字符破版。

公开 API：
  - ``render_analysis_html(job: dict) -> str``
"""
from __future__ import annotations

import html
from typing import Any

_OUTCOME_LABEL = {
    "DEAL_DONE": "成交",
    "FOLLOW_UP": "跟进中",
    "WALK_AWAY": "离开",
    "COMPLAINT": "投诉",
    "TIMEOUT": "超时",
    "CANCELLED": "取消",
}

_SEVERITY_LABEL = {"high": "高", "medium": "中", "low": "低"}

_GROUP_LABEL = {
    "intro": "一句话定位",
    "sell": "核心卖点",
    "comp": "竞品对比",
    "param": "核心参数",
    "faq": "常见问答",
    "demo": "现场演示",
}

# 导出报告中隐藏的 135910 板块（按用户要求删减「核心参数」「现场演示」）。
# 仅影响导出 PDF/HTML 的展示，后台打分 / 覆盖率统计仍保留全量。
_HIDDEN_GROUPS = {"param", "demo"}


def _e(s: Any) -> str:
    """HTML 转义，None → 空串。"""
    if s is None:
        return ""
    return html.escape(str(s))


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _pct(v: Any) -> float:
    """把 0~1 或 0~100 统一成 0~100 的展示值。"""
    f = _num(v)
    return f * 100 if f <= 1.0 else f


def _bar(pct: float, tone: str = "good") -> str:
    """渲染一个进度条（pct 0~100）。"""
    pct = max(0.0, min(100.0, pct))
    return (
        f'<div class="bar"><span class="bar-fill bar-{tone}" '
        f'style="width:{pct:.0f}%"></span></div>'
    )


def _score_tone(v: float) -> str:
    if v >= 8.0:
        return "good"
    if v >= 6.0:
        return "warn"
    return "bad"


# ---------------------------------------------------------------------------
# 各板块渲染
# ---------------------------------------------------------------------------


def _cover(job: dict[str, Any], s: dict[str, Any]) -> str:
    src = (
        f"会话 {_e(job.get('session_id'))}"
        if job.get("session_id")
        else f"批次 #{_e(job.get('batch_id'))}"
    )
    hb = _e(s.get("handbook_name") or "未命名手册")
    gen = _e(s.get("generated_at") or job.get("ended_at") or "")
    sess_n = int(s.get("session_count", 0) or 0)
    clf_n = int(s.get("total_classifications", 0) or 0)
    cov = _pct(s.get("coverage_pct"))
    outcomes = s.get("outcome_join") or s.get("outcome_distribution") or {}

    outcome_chips = ""
    for k, v in outcomes.items():
        tone = "good" if k == "DEAL_DONE" else ("warn" if k in ("FOLLOW_UP",) else "bad")
        outcome_chips += (
            f'<span class="chip chip-{tone}">{_e(_OUTCOME_LABEL.get(k, k))} '
            f'{int(v)}</span>'
        )

    return f"""
<header class="cover">
  <div class="cover-kicker">销售演绎反馈 · 话术分析与手册迭代报告</div>
  <h1 class="cover-title">{hb}</h1>
  <div class="cover-sub">{src} · 分析任务 #{_e(job.get('id'))} · 生成于 {gen}</div>
  <div class="kpi-grid">
    <div class="kpi"><div class="kpi-v">{cov:.0f}%</div><div class="kpi-l">手册覆盖率</div></div>
    <div class="kpi"><div class="kpi-v">{sess_n}</div><div class="kpi-l">会话场次</div></div>
    <div class="kpi"><div class="kpi-v">{clf_n}</div><div class="kpi-l">话术分类条数</div></div>
  </div>
  <div class="chips">{outcome_chips}</div>
</header>
"""


def _coverage(s: dict[str, Any]) -> str:
    cov = s.get("coverage_by_group") or {}
    if not cov:
        return ""
    _is_pb = s.get("doc_type") == "playbook_v1"
    _cov_lead = (
        "按 开场/卖点/竞品/FAQ 四大板块统计销冠实际命中情况——0% 覆盖即「死条目」，是迭代第一优先。"
        if _is_pb else
        "按 1/3/3/9 四大板块统计销冠实际命中情况——0% 覆盖即「死条目」，是迭代第一优先。"
    )
    rows = ""
    for g, stat in cov.items():
        if g in _HIDDEN_GROUPS:
            continue
        label = _GROUP_LABEL.get(g, g)
        cp = _pct(stat.get("coverage_pct"))
        q = _num(stat.get("weighted_avg_quality"))
        covered = int(stat.get("covered", 0) or 0)
        total = int(stat.get("total", 0) or 0)
        tone = "good" if cp >= 80 else ("warn" if cp >= 40 else "bad")
        rows += f"""
    <tr>
      <td class="g-name">{_e(label)} <span class="g-frac">{covered}/{total}</span></td>
      <td class="g-bar">{_bar(cp, tone)}</td>
      <td class="g-pct">{cp:.0f}%</td>
      <td class="g-q">质量 {q:.1f}</td>
    </tr>"""
    return f"""
<section class="block">
  <h2><span class="sec-no">01</span> 手册结构覆盖率</h2>
  <p class="lead">{_cov_lead}</p>
  <table class="cov-table">{rows}
  </table>
</section>
"""


_REV_GROUP_LABEL = {
    "intro": "① 一句话定位", "sell": "③ 核心卖点", "comp": "③ 竞品对比",
    "param": "⑤ 核心参数", "faq": "⑨ FAQ", "demo": "⑩ 现场演示",
    # playbook_v1
    "open": "① 开场破冰", "say": "② 核心卖点（按人设）",
    "compete": "③ 竞品应对", "respond": "④ 常见问答",
}
_REV_GROUP_ORDER = [g for g in ("intro", "sell", "comp", "param", "faq", "demo",
                                "open", "say", "compete", "respond")
                    if g not in _HIDDEN_GROUPS]
_REV_STATUS_TONE = {"保持": "good", "强化": "warn", "修正": "bad"}


def _proposals(s: dict[str, Any]) -> str:
    """§02 手册迭代建议 —— 逐条（每条含 TOP3 原声）。135910 与 playbook_v1 通用。"""
    _prop_lead = (
        "按 开场/卖点/竞品/FAQ 各条目逐条给建议——即使表现好也给增强点，每条附 TOP3 命中原声。"
        if s.get("doc_type") == "playbook_v1" else
        "按 1/3/3/9 对各条目逐条给建议——即使表现好也给增强点，每条附 TOP3 命中原声。"
    )
    # 状态图例（消除"保持/强化/修正到底指什么"的歧义）
    _status_legend = (
        '<p class="rev-legend">'
        '<b>状态说明：</b>'
        '<span class="lg good">保持</span>演绎良好、作范本沉淀（仍给增强点）　'
        '<span class="lg warn">强化</span>已被使用但说服力一般，或内容需补强　'
        '<span class="lg bad">修正</span>演绎质量偏低需纠正口径 / 具体度，或本批 0 次引用的死条目（需激活或考虑删减）'
        '</p>'
    )
    revs = s.get("handbook_revisions") or []
    if not revs:
        return ""
    by_group: dict[str, list[dict]] = {}
    for r in revs:
        by_group.setdefault(r.get("group") or "intro", []).append(r)

    blocks = ""
    for gkey in _REV_GROUP_ORDER:
        items = by_group.get(gkey) or []
        if not items:
            continue
        cards = ""
        for it in items:
            status = it.get("status") or ""
            tone = _REV_STATUS_TONE.get(status, "warn")
            cov = it.get("coverage") or {}
            if cov.get("covered"):
                cov_line = (
                    f'命中 {int(cov.get("hits", 0))} 次 · {int(cov.get("sessions", 0))} 场 · '
                    f'均分 {_num(cov.get("avg_quality")):.1f}'
                )
            else:
                cov_line = "本批 0 次引用（死条目）"
            original = (it.get("handbook_text") or "").strip()
            assessment = it.get("assessment") or ""
            suggestion = it.get("suggestion") or ""
            revised_text = (it.get("revised_text") or "").strip()
            fact_warnings = it.get("fact_warnings") or []
            warn_html = ""
            if fact_warnings:
                warn_html = (
                    '<div class="prop-line prop-warn"><b>⚠ 事实核查</b>'
                    + _e("；".join(fact_warnings))
                    + "（手册外信息，请人工确认后再决定是否采纳）</div>"
                )
            quotes = ""
            for q in (it.get("top_quotes") or [])[:3]:
                cust = (q.get("customer_question") or "").strip()
                quotes += f"""
        <div class="rev-quote">
          <div class="rev-quote-meta"><span class="rev-quote-score">{_num(q.get("score")):.1f}</span>
            <span class="rev-quote-by">{_e(q.get("persona_name"))}</span></div>
          {f'<div class="rev-quote-line"><b>客户原文</b>{_e(cust[:200])}</div>' if cust else ""}
          <div class="rev-quote-line"><b>销售原文</b>{_e((q.get("content") or "")[:200])}</div>
        </div>"""
            # 第二徽章只在「需人工确认」时显示——其余(可直接采纳/仅保留原文)与
            # 状态徽章 + 覆盖行(死条目)语义重复，去掉以免冗余。
            qflag = it.get("quality_flag") or ""
            qmap = {
                "review": ("q-review", "需人工确认"),
            }
            qcls, qtxt = qmap.get(qflag, ("", ""))
            qbadge = f'<span class="q-badge {qcls}">{qtxt}</span>' if qtxt else ""
            cards += f"""
    <div class="prop sev-{tone}">
      <div class="prop-head">
        <span class="sev-badge sev-b-{tone}">{_e(status)}</span>
        <span class="prop-tag">{_e(it.get('label'))}</span>
        {qbadge}
        <span class="prop-cov">{cov_line}</span>
      </div>
      {f'<div class="prop-line"><b>原文</b>{_e(original)}</div>' if original else ""}
      {f'<div class="prop-line"><b>评估</b>{_e(assessment)}</div>' if assessment else ""}
      {f'<div class="prop-line prop-fix"><b>建议</b>{_e(suggestion)}</div>' if suggestion else ""}
      {f'<div class="prop-line prop-fix"><b>修改后</b>{_e(revised_text)}</div>' if revised_text else ""}
      {warn_html}
      {f'<div class="rev-quotes">{quotes}</div>' if quotes else ""}
    </div>"""
        blocks += f'\n  <h3 class="rev-grp">{_e(_REV_GROUP_LABEL.get(gkey, gkey))}</h3>\n  <div class="prop-wrap">{cards}\n  </div>'
    return f"""
<section class="block block-key">
  <h2><span class="sec-no">02</span> 手册迭代建议 · 逐条 <span class="sec-flag">本报告核心</span></h2>
  <p class="lead">{_prop_lead}</p>
  {_status_legend}
  {blocks}
</section>
"""


def _excellent_groups(s: dict[str, Any]) -> str:
    """§06 优秀话术原声 —— 按 135910 + 手册外分组（改动⑥，解耦手册一致性）。"""
    data = s.get("excellent_by_group") or {}
    groups = data.get("groups") or []
    if not groups:
        return ""
    blocks = ""
    for g in groups:
        items = g.get("items") or []
        if not items:
            continue
        cards = ""
        for t in items:
            exc = _num(t.get("excellence_score"))
            persona = t.get("persona_name") or "-"
            cq = t.get("customer_question") or ""
            sc = t.get("sales_content") or ""
            psb = _num(t.get("purchase_signal_before"))
            psa = _num(t.get("purchase_signal_after"))
            att = t.get("attitude_after") or ""
            hb = t.get("handbook_label") or ""
            whys = "".join(f"<li>{_e(w)}</li>" for w in (t.get("why_good") or [])[:3])
            tags = ""
            if hb:
                tags += f'<span class="exc-tag">{_e(hb)}</span>'
            if att:
                tags += f'<span class="exc-tag">客户转「{_e(att)}」</span>'
            cards += f"""
    <div class="exc-card">
      <div class="exc-top">
        <span class="exc-score">{exc:.1f}/10</span>
        <span class="exc-sig">购买信号 {psb:.1f} → {psa:.1f}</span>
        {tags}
        <span class="exc-by">{_e(persona)}</span>
      </div>
      {f'<div class="exc-cust"><b>客户</b>{_e(cq)}</div>' if cq else ""}
      <div class="exc-sales">{_e(sc)}</div>
      {f'<ul class="exc-why">{whys}</ul>' if whys else ""}
    </div>"""
        is_off = g.get("key") == "off_handbook"
        badge_cls = "exc-badge-off" if is_off else "exc-badge-hb"
        hint = (
            '<span class="exc-hint">手册没提到但很有效 → 建议补进 Handbook</span>'
            if is_off else ""
        )
        blocks += f"""
  <div class="exc-group">
    <div class="exc-group-head">
      <span class="exc-badge {badge_cls}">{_e(g.get('label'))}</span>
      <span class="exc-count">{int(g.get('count', 0))} 条</span>{hint}
    </div>
    {cards}
  </div>"""
    return f"""
<section class="block">
  <h2><span class="sec-no">06</span> 优秀话术原声（按手册结构归类）</h2>
  <p class="lead">优秀 = 行为信号（客户购买信号↑ / 态度转正）⊕ LLM 优秀度，
  <b>不以"是否照搬手册"评判</b>；"手册外精彩话术"可直接喂迭代建议。</p>
  {blocks}
</section>
"""


def _weak_strong(s: dict[str, Any]) -> str:
    weak = s.get("weak_categories") or []
    strong = s.get("strong_categories") or []
    uncov = s.get("uncovered_categories") or []
    if not (weak or strong or uncov):
        return ""

    def _cat_list(items, cls):
        out = ""
        for it in items[:8]:
            label = it.get("label") or it.get("category_id")
            q = _num(it.get("avg_quality"))
            hits = int(it.get("hits", 0) or 0)
            reason = it.get("reason") or it.get("highlight_reason") or ""
            out += f"""
      <li class="{cls}">
        <div class="cat-h"><span class="cat-name">{_e(label)}</span>
          <span class="cat-meta">{q:.1f}/10 · {hits}次</span></div>
        {f'<div class="cat-reason">{_e(reason)}</div>' if reason else ""}
      </li>"""
        return out

    uncov_html = "".join(f'<span class="dead">{_e(u)}</span>' for u in uncov)
    return f"""
<section class="block">
  <h2><span class="sec-no">03</span> 强弱项与死条目</h2>
  <div class="ws-grid">
    <div class="ws-col">
      <h3 class="ws-bad-title">弱项 Top（亟需迭代）</h3>
      <ul class="cat-list">{_cat_list(weak, "cat-bad")}</ul>
    </div>
    <div class="ws-col">
      <h3 class="ws-good-title">强项 Top（保留口径）</h3>
      <ul class="cat-list">{_cat_list(strong, "cat-good")}</ul>
    </div>
  </div>
  {f'<div class="dead-wrap"><div class="dead-title">未覆盖 / 死条目（0 次命中）</div><div class="dead-list">{uncov_html}</div></div>' if uncov else ""}
</section>
"""


def _turns(s: dict[str, Any], key: str, title: str, no: str, good: bool) -> str:
    items = s.get(key) or []
    if not items:
        return ""
    cards = ""
    for t in items[:8]:
        q = _num(t.get("avg_quality"))
        persona = t.get("persona_name") or "-"
        cq = t.get("customer_question") or ""
        sc = t.get("sales_content") or ""
        reasons = t.get("why_good") if good else t.get("why_bad")
        reason_html = "".join(
            f'<li>{_e(r)}</li>' for r in (reasons or [])[:3]
        )
        sug = t.get("suggestion") or ""
        cards += f"""
    <div class="turn turn-{'good' if good else 'bad'}">
      <div class="turn-head">
        <span class="turn-persona">{_e(persona)}</span>
        <span class="turn-q turn-q-{_score_tone(q)}">{q:.1f}/10</span>
      </div>
      {f'<div class="turn-cust"><b>客户</b>{_e(cq)}</div>' if cq else ""}
      <div class="turn-sales"><b>销冠</b>{_e(sc)}</div>
      {f'<ul class="turn-reasons">{reason_html}</ul>' if reason_html else ""}
      {f'<div class="turn-sug"><b>建议</b>{_e(sug)}</div>' if (sug and not good) else ""}
    </div>"""
    return f"""
<section class="block">
  <h2><span class="sec-no">{no}</span> {_e(title)}</h2>
  <div class="turn-wrap">{cards}
  </div>
</section>
"""


def _voice(s: dict[str, Any]) -> str:
    voices = s.get("customer_voice") or []
    if not voices:
        return ""
    cards = ""
    for v in voices[:14]:
        name = v.get("persona_name") or f"persona {v.get('persona_id')}"
        samples = v.get("samples") or []
        if not samples:
            continue
        q = samples[0].get("content") or ""
        cards += f"""
    <blockquote class="voice">
      <div class="voice-q">{_e(q)}</div>
      <div class="voice-by">— {_e(name)}</div>
    </blockquote>"""
    if not cards:
        return ""
    return f"""
<section class="block">
  <h2><span class="sec-no">05</span> 客户原声（离开/异议时刻）</h2>
  <p class="lead">话术迭代背后的真实用户声音——离开前最后一句，往往直指手册缺口。</p>
  <div class="voice-wrap">{cards}
  </div>
</section>
"""


# ---------------------------------------------------------------------------
# 样式
# ---------------------------------------------------------------------------

_STYLE = """
:root{
  --ink:#1a1d24; --muted:#6b7280; --line:#e6e8ec; --paper:#ffffff; --bg:#f4f5f7;
  --brand:#b3122c; --brand-2:#8a0f22; --good:#1f9d57; --warn:#d98a00; --bad:#c0392b;
  --soft:#f8f4f0;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{font-family:"Noto Serif SC",Georgia,"Songti SC",serif;color:var(--ink);
  background:var(--bg);line-height:1.65;font-size:14px;}
.page{max-width:880px;margin:0 auto;background:var(--paper);
  box-shadow:0 1px 24px rgba(0,0,0,.06);}
.sans{font-family:"Noto Sans SC","Helvetica Neue",Arial,sans-serif;}

/* Cover */
.cover{background:linear-gradient(135deg,var(--brand) 0%,var(--brand-2) 100%);
  color:#fff;padding:52px 56px 40px;}
.cover-kicker{font-family:"Noto Sans SC",sans-serif;font-size:12px;letter-spacing:3px;
  text-transform:uppercase;opacity:.85;margin-bottom:14px;}
.cover-title{font-size:34px;line-height:1.25;margin:0 0 10px;font-weight:700;}
.cover-sub{font-family:"Noto Sans SC",sans-serif;font-size:13px;opacity:.9;margin-bottom:26px;}
.kpi-grid{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px;}
.kpi{background:rgba(255,255,255,.14);border-radius:10px;padding:14px 18px;min-width:104px;
  flex:1;backdrop-filter:blur(2px);}
.kpi-bad .kpi-v{color:#ffd7d0;}
.kpi-v{font-size:28px;font-weight:700;font-family:"Noto Sans SC",sans-serif;}
.kpi-l{font-family:"Noto Sans SC",sans-serif;font-size:11px;opacity:.88;margin-top:2px;}
.chips{display:flex;gap:8px;flex-wrap:wrap;}
.chip{font-family:"Noto Sans SC",sans-serif;font-size:12px;padding:4px 12px;border-radius:20px;
  background:rgba(255,255,255,.18);}
.chip-good{background:rgba(255,255,255,.28);font-weight:600;}
.chip-bad{background:rgba(0,0,0,.18);}

/* Sections */
.block{padding:30px 56px;border-bottom:1px solid var(--line);}
.block-key{background:var(--soft);}
h2{font-size:21px;margin:0 0 6px;display:flex;align-items:center;gap:12px;}
.sec-no{font-family:"Noto Sans SC",sans-serif;font-size:13px;color:#fff;background:var(--brand);
  width:30px;height:30px;border-radius:7px;display:inline-flex;align-items:center;
  justify-content:center;font-weight:700;}
.sec-flag{font-family:"Noto Sans SC",sans-serif;font-size:11px;color:var(--brand);
  border:1px solid var(--brand);border-radius:4px;padding:2px 8px;font-weight:600;}
.lead{color:var(--muted);font-size:13px;margin:0 0 18px;font-family:"Noto Sans SC",sans-serif;}
.mth-sec{margin:0 0 16px;font-family:"Noto Sans SC",sans-serif;}
.mth-sec-t{font-size:15px;font-weight:700;color:var(--ink);margin-bottom:3px;}
.mth-sec-d{font-size:12.5px;line-height:1.6;color:var(--muted);margin-bottom:7px;}
.mth-items{margin:0;padding:0;list-style:none;}
.mth-items li{font-size:12.5px;line-height:1.55;padding:5px 0 5px 14px;
  border-bottom:1px dashed var(--line);position:relative;}
.mth-items li:before{content:"";position:absolute;left:0;top:11px;width:5px;height:5px;
  border-radius:50%;background:var(--brand);}
.mth-name{font-weight:600;color:var(--ink);margin-right:6px;}
.mth-desc{color:#374151;}
h3{font-size:15px;margin:0 0 12px;font-family:"Noto Sans SC",sans-serif;}

/* bars */
.bar{background:#edeef1;border-radius:6px;height:9px;overflow:hidden;width:100%;}
.bar-fill{display:block;height:100%;border-radius:6px;}
.bar-good{background:var(--good);} .bar-warn{background:var(--warn);} .bar-bad{background:var(--bad);}

/* coverage table */
.cov-table{width:100%;border-collapse:collapse;font-family:"Noto Sans SC",sans-serif;}
.cov-table td{padding:9px 6px;vertical-align:middle;border-bottom:1px solid var(--line);}
.g-name{width:150px;font-weight:600;font-size:13px;}
.g-frac{color:var(--muted);font-weight:400;font-size:11px;}
.g-bar{width:auto;}.g-pct{width:48px;text-align:right;font-weight:700;}
.g-q{width:78px;text-align:right;color:var(--muted);font-size:12px;}

/* dimensions */
.dim-row{display:flex;align-items:center;gap:14px;margin-bottom:11px;
  font-family:"Noto Sans SC",sans-serif;}
.dim-label{width:90px;font-size:13px;font-weight:600;}
.dim-score{width:48px;text-align:right;font-weight:700;}
.dim-good{color:var(--good);} .dim-warn{color:var(--warn);} .dim-bad{color:var(--bad);}

/* health */
.health-grid{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px;}
.health-card{flex:1;min-width:110px;border:1px solid var(--line);border-radius:10px;
  padding:14px 16px;font-family:"Noto Sans SC",sans-serif;}
.health-bad{border-color:#f2c9c2;background:#fdf3f1;}
.h-v{font-size:24px;font-weight:700;}.h-l{font-size:11px;color:var(--muted);margin-top:2px;}
.token-cloud{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;}
.token{font-family:"Noto Sans SC",sans-serif;font-size:12px;background:#eef1f4;
  border-radius:6px;padding:4px 10px;}
.token i{color:var(--brand);font-style:normal;font-weight:700;margin-left:4px;}
.punt-title,.dead-title,.punt-title{font-family:"Noto Sans SC",sans-serif;font-size:12px;
  color:var(--muted);margin-bottom:6px;}
blockquote.punt{margin:0 0 8px;padding:8px 14px;border-left:3px solid var(--bad);
  background:#fbf0ee;font-size:13px;color:#7a2a20;border-radius:0 6px 6px 0;}

/* proposals */
.prop-wrap{display:flex;flex-direction:column;gap:12px;}
.prop{border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:8px;
  padding:13px 16px;background:#fff;}
.prop.sev-high{border-left-color:var(--bad);}
.prop.sev-low{border-left-color:var(--good);}
.prop-head{display:flex;align-items:center;gap:10px;margin-bottom:8px;
  font-family:"Noto Sans SC",sans-serif;}
.sev-badge{font-size:11px;color:#fff;border-radius:4px;padding:1px 8px;font-weight:700;}
.sev-b-high{background:var(--bad);}.sev-b-medium{background:var(--warn);}.sev-b-low{background:var(--good);}
.prop-tag{font-weight:700;font-size:14px;}
.prop-kind{font-size:11px;color:var(--muted);margin-left:auto;}
.prop-line{font-size:13px;margin-top:5px;}
.prop-line b{font-family:"Noto Sans SC",sans-serif;font-size:11px;color:var(--muted);
  display:inline-block;min-width:38px;margin-right:6px;}
.prop-fix{color:var(--brand-2);}
.prop-warn{color:#b45309;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:4px 8px;margin-top:4px;font-size:12.5px;}
.q-badge{font-size:11px;padding:1px 7px;border-radius:10px;font-weight:600;}
.q-ok{background:#dcfce7;color:#166534;}
.q-review{background:#fef3c7;color:#92400e;}
.q-keep{background:#e5e7eb;color:#4b5563;}
.prop-ev{color:var(--muted);}
.prop.sev-good{border-left-color:var(--good);}
.prop.sev-warn{border-left-color:var(--warn);}
.prop.sev-bad{border-left-color:var(--bad);}
.sev-b-good{background:var(--good);}.sev-b-warn{background:var(--warn);}.sev-b-bad{background:var(--bad);}
.prop-cov{font-size:11px;color:var(--muted);margin-left:auto;}
.rev-legend{font-size:12px;color:var(--muted);margin:0 0 14px;line-height:1.9;
  font-family:"Noto Sans SC",sans-serif;background:#f8fafc;border:1px solid var(--line);
  border-radius:6px;padding:8px 12px;}
.rev-legend .lg{display:inline-block;font-size:11px;font-weight:700;color:#fff;
  padding:1px 7px;border-radius:9px;margin:0 4px 0 10px;}
.rev-legend .lg.good{background:var(--good);}
.rev-legend .lg.warn{background:var(--warn);}
.rev-legend .lg.bad{background:var(--bad);}
.rev-grp{font-size:14px;font-weight:700;margin:16px 0 8px;
  border-bottom:2px solid var(--line);padding-bottom:5px;font-family:"Noto Sans SC",sans-serif;}
.rev-quotes{margin-top:8px;border-top:1px dashed var(--line);padding-top:6px;}
.rev-quote{font-size:12px;padding:7px 0;border-bottom:1px dashed var(--line);}
.rev-quote:last-child{border-bottom:none;}
.rev-quote-meta{display:flex;align-items:baseline;gap:8px;margin-bottom:3px;}
.rev-quote-score{font-weight:700;color:var(--good);min-width:28px;}
.rev-quote-by{color:var(--muted);font-size:11px;}
.rev-quote-line{font-size:12.5px;line-height:1.55;margin-top:2px;}
.rev-quote-line b{font-family:"Noto Sans SC",sans-serif;font-size:11px;color:var(--muted);
  display:inline-block;min-width:52px;margin-right:6px;vertical-align:top;}
.rev-quote-fix{color:var(--brand-2);}

/* weak/strong */
.ws-grid{display:flex;gap:24px;}
.ws-col{flex:1;}
.ws-bad-title{color:var(--bad);}.ws-good-title{color:var(--good);}
.cat-list{list-style:none;margin:0;padding:0;}
.cat-list li{border:1px solid var(--line);border-radius:7px;padding:9px 12px;margin-bottom:8px;}
.cat-bad{border-left:3px solid var(--bad);}.cat-good{border-left:3px solid var(--good);}
.cat-h{display:flex;justify-content:space-between;font-family:"Noto Sans SC",sans-serif;}
.cat-name{font-weight:600;font-size:13px;}
.cat-meta{color:var(--muted);font-size:12px;}
.cat-reason{font-size:12px;color:var(--muted);margin-top:4px;}
.dead-wrap{margin-top:18px;}
.dead-list{display:flex;flex-wrap:wrap;gap:6px;}
.dead{font-family:"Noto Sans SC",sans-serif;font-size:12px;background:#f0e6e6;color:#8a3030;
  border-radius:5px;padding:3px 9px;}

/* turns */
.turn-wrap{display:flex;flex-direction:column;gap:12px;}
.turn{border:1px solid var(--line);border-radius:9px;padding:13px 16px;}
.turn-good{border-left:4px solid var(--good);background:#f4faf6;}
.turn-bad{border-left:4px solid var(--bad);background:#fcf4f3;}
.turn-head{display:flex;justify-content:space-between;margin-bottom:8px;
  font-family:"Noto Sans SC",sans-serif;}
.turn-persona{font-weight:700;font-size:13px;}
.turn-q{font-weight:700;font-size:13px;}
.turn-q-good{color:var(--good);}.turn-q-warn{color:var(--warn);}.turn-q-bad{color:var(--bad);}
.turn-cust,.turn-sales,.turn-sug{font-size:13px;margin-top:6px;}
.turn-cust b,.turn-sales b,.turn-sug b{font-family:"Noto Sans SC",sans-serif;font-size:11px;
  color:var(--muted);display:inline-block;min-width:34px;margin-right:6px;}
.turn-cust{color:#555;}
.turn-reasons{margin:8px 0 0;padding-left:20px;font-size:12px;color:var(--muted);}
.turn-sug{color:var(--brand-2);}
.exc-group{margin-bottom:16px;}
.exc-group-head{display:flex;align-items:center;gap:10px;margin:4px 0 10px;
  font-family:"Noto Sans SC",sans-serif;}
.exc-badge{font-weight:700;font-size:13px;padding:3px 12px;border-radius:6px;color:#fff;}
.exc-badge-hb{background:var(--brand-2,#2563eb);}
.exc-badge-off{background:#d97706;}
.exc-count{font-size:12px;color:var(--muted);}
.exc-hint{font-size:11px;color:#d97706;font-style:italic;}
.exc-card{border:1px solid var(--line);border-left:4px solid var(--good);
  border-radius:9px;padding:11px 14px;margin-bottom:8px;background:#f4faf6;}
.exc-top{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:6px;
  font-family:"Noto Sans SC",sans-serif;}
.exc-score{font-weight:700;font-size:13px;color:var(--good);}
.exc-sig{font-size:11px;color:var(--muted);}
.exc-tag{font-size:11px;background:#eef2ff;color:#3730a3;border-radius:4px;padding:1px 7px;}
.exc-by{margin-left:auto;font-size:11px;color:var(--muted);}
.exc-cust{font-size:12.5px;color:#555;margin-top:4px;}
.exc-cust b{font-family:"Noto Sans SC",sans-serif;font-size:11px;color:var(--muted);
  display:inline-block;min-width:34px;margin-right:6px;}
.exc-sales{font-size:13px;margin-top:5px;line-height:1.6;}
.exc-why{margin:7px 0 0;padding-left:20px;font-size:12px;color:#047857;}

/* key numbers */
.kn-table{width:100%;border-collapse:collapse;font-family:"Noto Sans SC",sans-serif;font-size:13px;}
.kn-table th{text-align:left;color:var(--muted);font-weight:600;font-size:11px;
  border-bottom:2px solid var(--line);padding:6px;}
.kn-table td{padding:7px 6px;border-bottom:1px solid var(--line);}
.kn-v{font-weight:700;color:var(--brand);white-space:nowrap;}
.kn-src{color:var(--muted);font-size:12px;}

/* voice */
.voice-wrap{display:flex;flex-direction:column;gap:10px;}
blockquote.voice{margin:0;padding:12px 18px;background:#f7f7f9;border-radius:8px;
  border-left:3px solid var(--ink);}
.voice-q{font-size:13px;font-style:italic;}
.voice-by{font-family:"Noto Sans SC",sans-serif;font-size:12px;color:var(--muted);margin-top:6px;}

/* footer */
.foot{padding:22px 56px;color:var(--muted);font-family:"Noto Sans SC",sans-serif;font-size:11px;
  text-align:center;}

@media print{
  body{background:#fff;}
  .page{box-shadow:none;max-width:none;}
  .block{page-break-inside:avoid;}
  .prop,.turn,.cat-list li{page-break-inside:avoid;}
  @page{margin:14mm;}
}
"""


def _playbook_persona(s: dict[str, Any]) -> str:
    """playbook：按客户人设(A/B/C/D)汇总「开场+卖点」话术的覆盖与演绎质量。"""
    rows = s.get("playbook_persona_breakdown") or []
    if not rows:
        return ""
    cells = ""
    for r in rows:
        cov_pct = _num(r.get("coverage_pct"))
        cells += (
            '<div style="flex:1;min-width:190px;border:1px solid #e5e7eb;'
            'border-radius:10px;padding:12px 14px">'
            f'<div style="font-weight:700;font-size:14px;margin-bottom:6px">'
            f'{_e(r.get("persona"))} · {_e(r.get("persona_label"))}</div>'
            f'<div style="font-size:12.5px;color:#374151">话术覆盖 '
            f'{int(r.get("covered", 0))}/{int(r.get("total", 0))}'
            f'（{cov_pct:.0f}%）</div>'
            f'<div style="font-size:12.5px;color:#374151">命中 '
            f'{int(r.get("hits", 0))} 次 · 均分 {_num(r.get("avg_quality")):.1f}/10</div>'
            "</div>"
        )
    return f"""
<section class="block">
  <h2><span class="sec-no">03</span> 按客户人设的话术演绎 · A/B/C/D</h2>
  <p class="lead">面向各类客户的话术（开场 + 卖点）被销冠在真实对话里实际演绎的覆盖率与质量——看哪类客户的剧本最该补强。</p>
  <div style="display:flex;gap:12px;flex-wrap:wrap">{cells}</div>
</section>
"""


def _conversation_persona(s: dict[str, Any]) -> str:
    """playbook：按每场对话 LLM 判定的客户类型，汇总对话分布 + 各类型专属话术覆盖。"""
    data = s.get("conversation_persona_breakdown") or {}
    rows = data.get("distribution") or []
    if not rows:
        return ""
    total = int(data.get("session_total", 0) or 0)
    classified = int(data.get("classified", 0) or 0)
    cells = ""
    for r in rows:
        p = r.get("persona") or "?"
        is_unknown = p == "?"
        name = "未判定" if is_unknown else f'{_e(p)} · {_e(r.get("persona_label"))}'
        oc = r.get("outcomes") or {}
        oc_txt = "、".join(f"{_e(k)} {v}" for k, v in oc.items()) or "—"
        cov = (
            ""
            if is_unknown else
            f'<div style="font-size:12.5px;color:#374151">本类专属话术覆盖 '
            f'{int(r.get("own_cats_covered", 0))}/{int(r.get("own_cats_total", 0))}'
            f'（{_num(r.get("own_coverage_pct")):.0f}%）</div>'
        )
        cells += (
            '<div style="flex:1;min-width:190px;border:1px solid #e5e7eb;'
            'border-radius:10px;padding:12px 14px">'
            f'<div style="font-weight:700;font-size:14px;margin-bottom:6px">{name}</div>'
            f'<div style="font-size:12.5px;color:#374151">对话场次 '
            f'<b>{int(r.get("sessions", 0))}</b> 场</div>'
            f'<div style="font-size:12px;color:#6b7280">结局：{oc_txt}</div>'
            f'{cov}'
            "</div>"
        )
    return f"""
<section class="block">
  <h2><span class="sec-no">04</span> 对话客户类型分布 · 运行时判定</h2>
  <p class="lead">由 LLM 按每场对话的客户发言判定其最接近 A/B/C/D 哪类客户（共 {total} 场，已判定 {classified} 场）——再看每类客户对话里、该类专属剧本（开场+卖点）的实际覆盖。</p>
  <div style="display:flex;gap:12px;flex-wrap:wrap">{cells}</div>
</section>
"""


def render_analysis_html(job: dict[str, Any]) -> str:
    """把分析任务结果渲染成自包含的精排 HTML（浏览器打印即可转 PDF）。

    消费 ``job["summary"]``（v2.0 schema）。任一板块字段缺失自动跳过。
    """
    s = job.get("summary") or {}
    title = _e(s.get("handbook_name") or "分析报告")

    body_parts = [
        _cover(job, s),
        _coverage(s),
        _proposals(s),
        _playbook_persona(s),
        _conversation_persona(s),
        _weak_strong(s),
        _excellent_groups(s),
        _turns(s, "problematic_turns", "问题话术（重点修正）", "07", good=False),
        # 客户原声按用户要求固定放在报告最后
        _voice(s),
    ]
    body = "\n".join(p for p in body_parts if p)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} · 分析报告</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;600;700&family=Noto+Serif+SC:wght@400;600;700&display=swap" rel="stylesheet"/>
<style>{_STYLE}</style>
</head>
<body>
<div class="page">
{body}
<div class="foot">本报告由销售演绎分析系统自动生成 · 内容源自全部会话原声 · 供内部话术迭代使用</div>
</div>
</body>
</html>"""
