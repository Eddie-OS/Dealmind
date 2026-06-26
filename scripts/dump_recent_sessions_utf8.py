"""把最近 N 个会话的逐句对话 + LLM 调用元信息 dump 到 UTF-8 文件。
避免 PowerShell GBK 编码截断中文/俄文。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.storage import db as sdb  # noqa: E402

OUT = ROOT / "scripts" / "_recent_sessions_dump.txt"

N = 5


def main() -> None:
    with sdb.connection_scope() as conn:
        rows = conn.execute(
            "SELECT s.id, s.topic, s.persona_id, s.handbook_id, "
            "s.status, s.started_at, p.name AS persona_name "
            "FROM sessions s LEFT JOIN personas p ON s.persona_id=p.id "
            "ORDER BY s.started_at DESC LIMIT ?", (N,)
        ).fetchall()
        sessions = [dict(r) for r in rows]
        if not sessions:
            print("no sessions")
            return

        lines: list[str] = []
        for s in sessions:
            sid = s["id"]
            lines.append("=" * 100)
            lines.append(
                f"session={sid}\n  topic={s['topic']}\n  "
                f"persona={s['persona_name']}\n  handbook_id={s['handbook_id']}\n  "
                f"status={s['status']}\n  started_at={s['started_at']}"
            )
            turns = conn.execute(
                "SELECT idx, role, content, metadata_json "
                "FROM turns WHERE session_id=? ORDER BY idx, id",
                (sid,),
            ).fetchall()
            for t in turns:
                t = dict(t)
                spk = t["role"]
                content = (t["content"] or "").strip().replace("\n", " ")
                meta = {}
                try:
                    meta = json.loads(t["metadata_json"] or "{}")
                except Exception:
                    meta = {}
                meta_brief = {}
                # sales metadata 关键字段
                for k in ("intent", "next_action", "used_handbook",
                          "rag_hits", "tool_calls", "handbook_inject",
                          "content_guard", "raw_output", "error",
                          "fallback_reason", "used_product_context"):
                    if k in meta:
                        v = meta[k]
                        if isinstance(v, str) and len(v) > 200:
                            v = v[:200] + "…"
                        meta_brief[k] = v
                lines.append(f"  [{t['idx']:>2}] {spk}: {content[:400]}")
                if meta_brief:
                    lines.append(f"       meta: {json.dumps(meta_brief, ensure_ascii=False)[:600]}")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK dumped {len(sessions)} sessions to {OUT}")


if __name__ == "__main__":
    main()
