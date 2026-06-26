"""Batch #13 44场逐场审计：Handbook缺口 vs Agent执行问题（只读）。"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.storage import db as sdb  # noqa: E402

BATCH_ID = 13
PUNT = ("官网", "打开官网", "帮您查", "稍后", "确认一下", "我查", "在线查")

GAP_LABELS = {
    "local_currency_price": "本币/含税总价（美元/林吉特/RM等）",
    "app_google_drive": "Google Drive / 原生离线办公",
    "app_eco": "第三方App生态（WPS/猿辅导/多邻国等）",
    "third_party_proof": "第三方测试报告/充电曲线/延迟帧率",
    "warranty_local": "本地保修/服务点/渠道",
    "price": "价格透明度",
    "proof": "硬数据证明",
    "service": "售后渠道",
}

AGENT_LABELS = {
    "未执行演示动作": "手册有demo但未演示（手电筒/珠光/防反光）",
    "推诿查官网": "多次推诿查官网",
    "客户要价仍查官网": "客户明确问价仍查官网",
    "编造/混淆型号": "编造Air/11.5/13.2等型号",
    "编造国际版/Air映射": "编造国际版或Air映射",
    "LLM解析失败": "整轮JSON解析失败",
    "客户问屏幕未报Handbook参数": "客户问屏幕未报144Hz等参数",
    "客户提竞品未用Handbook竞品话术": "提iPad/三星未用竞品话术",
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with sdb.connection_scope() as conn:
        batch = sdb.get_batch_job(conn, BATCH_ID)
        sids = batch.get("session_ids") or []
        if not sids:
            rows = conn.execute(
                "SELECT id FROM sessions WHERE id LIKE '%_b13' ORDER BY created_at"
            ).fetchall()
            sids = [r["id"] for r in rows]

        hb_row = conn.execute(
            "SELECT structure_json FROM product_handbooks WHERE id=?",
            (batch.get("handbook_id") or 1,),
        ).fetchone()
        hb = json.loads(hb_row["structure_json"]) if hb_row else {}
        hb_text = json.dumps(hb, ensure_ascii=False).lower()

        results = []
        gap_counter: Counter[str] = Counter()
        agent_counter: Counter[str] = Counter()

        for sid in sids:
            sess = sdb.get_session_by_id(conn, sid)
            if not sess:
                continue
            summ = json.loads(sess.get("summary_json") or "{}")
            outcome = summ.get("outcome") or "?"
            rounds = summ.get("total_rounds") or 0
            pid = sess.get("persona_id")
            p = sdb.get_persona_by_id(conn, pid) if pid else None
            pname = (p or {}).get("name", f"p{pid}")

            turns = list(
                conn.execute(
                    "SELECT idx, role, content FROM turns WHERE session_id=? ORDER BY idx",
                    (sid,),
                ).fetchall()
            )

            sales = [t for t in turns if t["role"] == "sales"]
            persona_turns = [t for t in turns if t["role"] == "persona"]
            sales_text = " ".join((t["content"] or "") for t in sales)
            persona_text = " ".join((t["content"] or "") for t in persona_turns)
            all_text = " ".join((t["content"] or "") for t in turns)

            gaps: list[str] = []
            agent_issues: list[str] = []

            if re.search(r"Google Drive|谷歌盘|原生.*离线", persona_text, re.I):
                if "google drive" not in hb_text:
                    gaps.append("app_google_drive")
            if re.search(r"美元|USD|林吉特|RM\b|比索|卢布|本币", persona_text, re.I):
                gaps.append("local_currency_price")
            if re.search(r"测试报告|充电曲线|延迟.*毫秒|帧率|第三方.*测", persona_text):
                gaps.append("third_party_proof")
            if re.search(r"保修|售后|服务点|授权店", persona_text):
                if "保修" not in hb_text:
                    gaps.append("warranty_local")
            if re.search(
                r"WPS|猿辅导|多邻国|小叶子|钢伴|YouTube|离线.*App|应用商店",
                persona_text,
                re.I,
            ):
                if "google" not in hb_text and "wps" not in hb_text.lower():
                    gaps.append("app_eco")

            if re.search(r"多少钱|报价|总价|含税|键盘.*价|笔.*价", persona_text):
                if not re.search(r"¥|元|价格|报价", sales_text):
                    gaps.append("price")

            if any(d in persona_text for d in ("演示", "上手试", "手电筒", "珠光")):
                if not any(
                    d in sales_text for d in ("手电筒", "珠光", "防反光", "演示", "我给您")
                ):
                    agent_issues.append("未执行演示动作")

            punt_n = sum(
                1 for t in sales if any(p in (t["content"] or "") for p in PUNT)
            )
            if punt_n >= 2:
                agent_issues.append("推诿查官网")
            if punt_n >= 1 and re.search(r"价格|多少钱|报价|总价", persona_text):
                agent_issues.append("客户要价仍查官网")

            if re.search(r"MatePad Air|11\.5|13\.2|\bSE\b", sales_text):
                agent_issues.append("编造/混淆型号")
            if "国际版" in sales_text or "Air 2025" in sales_text:
                agent_issues.append("编造国际版/Air映射")
            if "解析失败" in all_text:
                agent_issues.append("LLM解析失败")

            if re.search(r"刷新率|Hz|屏幕|护眼", persona_text, re.I):
                if "144" not in sales_text and not re.search(r"144\s*Hz", sales_text, re.I):
                    agent_issues.append("客户问屏幕未报Handbook参数")

            if re.search(r"iPad|三星|Samsung|Apple Pencil", persona_text, re.I):
                if not re.search(r"iPad|Apple Pencil|三星|Samsung", sales_text, re.I):
                    agent_issues.append("客户提竞品未用Handbook竞品话术")

            gaps = list(dict.fromkeys(gaps))
            agent_issues = list(dict.fromkeys(agent_issues))
            for g in gaps:
                gap_counter[g] += 1
            for a in agent_issues:
                agent_counter[a] += 1

            results.append(
                {
                    "sid": sid,
                    "persona": pname,
                    "outcome": outcome,
                    "rounds": rounds,
                    "gaps": gaps,
                    "agent": agent_issues,
                    "punt": punt_n,
                }
            )

    out_dir = Path(__file__).resolve().parents[1] / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "batch13_per_session_audit.md"

    lines = [
        "# Batch #13 逐场审计（44场）",
        "",
        "## 汇总",
        "",
        f"- 会话数: {len(results)}",
        f"- WALK_AWAY/TIMEOUT/COMPLAINT: {sum(1 for r in results if r['outcome'] in ('WALK_AWAY','TIMEOUT','COMPLAINT'))}",
        f"- DEAL_DONE: {sum(1 for r in results if r['outcome'] == 'DEAL_DONE')}",
        "",
        "### Handbook 缺口频次（Persona问了，135910未覆盖或不足）",
        "",
        "| 缺口 | 场次 | 说明 |",
        "|------|------|------|",
    ]
    for k, v in gap_counter.most_common():
        lines.append(f"| {k} | {v} | {GAP_LABELS.get(k, k)} |")

    lines += [
        "",
        "### Agent 执行问题频次（手册有/该做但没做）",
        "",
        "| 问题 | 场次 | 说明 |",
        "|------|------|------|",
    ]
    for k, v in agent_counter.most_common():
        lines.append(f"| {k} | {v} | {AGENT_LABELS.get(k, k)} |")

    lines += [
        "",
        "## 逐场明细",
        "",
        "| # | Outcome | Persona | Rounds | Handbook缺口 | Agent问题 | 推诿次数 |",
        "|---|---------|---------|--------|--------------|-----------|----------|",
    ]
    for i, r in enumerate(results, 1):
        g = "; ".join(GAP_LABELS.get(x, x) for x in r["gaps"]) or "—"
        a = "; ".join(AGENT_LABELS.get(x, x) for x in r["agent"]) or "—"
        lines.append(
            f"| {i} | {r['outcome']} | {r['persona'][:20]} | {r['rounds']} | {g} | {a} | {r['punt']} |"
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"\nSessions: {len(results)}")
    print("\n=== GAP ===")
    for k, v in gap_counter.most_common():
        print(f"  {GAP_LABELS.get(k,k)}: {v}")
    print("\n=== AGENT ===")
    for k, v in agent_counter.most_common():
        print(f"  {AGENT_LABELS.get(k,k)}: {v}")


if __name__ == "__main__":
    main()
