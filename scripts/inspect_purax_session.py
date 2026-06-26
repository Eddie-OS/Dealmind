"""扫近 10 场会话；如果命中 Pura X，dump 出关键字段（话题 / persona 国家 / 工具调用 / 前 6 轮内容）。"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.storage.db import get_connection


def main() -> int:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, topic, persona_id, product_kb_id, status, started_at, ended_at, summary_json "
        "FROM sessions ORDER BY id DESC LIMIT 10"
    ).fetchall()
    print(f"近 10 场会话：\n{'='*120}")
    for r in rows:
        d = dict(r)
        topic = (d.get("topic") or "")[:80]
        print(f"id={d['id']:>3} | persona={d['persona_id']} | "
              f"product_kb={d['product_kb_id']} | status={d['status']:<12} | started={d.get('started_at')}")
        print(f"        topic: {topic}")

    # 找含 Pura X / pura x 的会话
    print(f"\n{'='*120}\n候选：含 'Pura X' / 'pura x' 的会话\n")
    hits = [dict(r) for r in rows if "pura" in (r["topic"] or "").lower()]
    if not hits:
        print("（未命中 Pura X，按最近一场分析）")
        hits = [dict(rows[0])]

    for h in hits[:2]:
        sid = h["id"]
        pid = h.get("persona_id")
        print(f"\n{'-'*120}\n【会话 #{h['id']}】topic={h.get('topic')}\n")

        # persona
        if pid:
            prow = conn.execute(
                "SELECT id, name, country_code, currency, market_domains_json "
                "FROM personas WHERE id = ?", (pid,)
            ).fetchone()
            if prow:
                pd = dict(prow)
                md = json.loads(pd.get("market_domains_json") or "[]")
                print(f"  persona: id={pd['id']} name={pd['name']} country={pd.get('country_code')}/"
                      f"{pd.get('currency')} domains={md}")

        # turns
        turns = conn.execute(
            "SELECT idx, role, content, metadata_json "
            "FROM turns WHERE session_id = ? ORDER BY id ASC LIMIT 30",
            (sid,),
        ).fetchall()
        print(f"  共 {len(turns)} 轮（只打印前 30）：")
        for t in turns:
            td = dict(t)
            content = (td.get("content") or "").replace("\n", " ").strip()
            short = content[:240]
            print(f"\n    [round={td['idx']} role={td['role']}]")
            print(f"      {short}")
            # 工具调用
            meta_raw = td.get("metadata_json")
            if meta_raw:
                try:
                    meta = json.loads(meta_raw)
                except Exception:
                    meta = {}
                tc = meta.get("tool_calls") or []
                if tc:
                    for c in tc[:3]:
                        nm = c.get("name") or c.get("tool")
                        args = c.get("args") or c.get("arguments") or {}
                        if isinstance(args, str):
                            args_s = args[:120]
                        else:
                            args_s = json.dumps(args, ensure_ascii=False)[:120]
                        result_preview = str(c.get("result") or c.get("result_preview") or "")[:160].replace("\n", " ")
                        print(f"      tool: {nm}  args={args_s}")
                        print(f"             result: {result_preview}")
                pa = meta.get("strategy", {}).get("playbook_action") if isinstance(meta.get("strategy"), dict) else None
                if pa:
                    print(f"      playbook_action: {pa}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
