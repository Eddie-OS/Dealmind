"""读取 logs/purax_detail.json，看 preflight + content_guard 是否在跑。"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

path = Path("logs/purax_detail.json")
if not path.exists():
    print("缺少 logs/purax_detail.json")
    sys.exit(1)

d = json.load(path.open("r", encoding="utf-8-sig"))
print("session.id        =", d.get("id"))
print("status            =", d.get("status"))
print("runtime_status    =", d.get("runtime_status"))
turns = d.get("turns", [])
print("turns_count       =", len(turns))

guard_hits = 0
forbidden_words = ("M-Pencil", "M Pencil", "Mpencil", "手写笔")
violations = []

print("\n----- turns ↓ -----")
for t in turns:
    idx = t.get("idx")
    spk = t.get("speaker")
    cnt = (t.get("content", "") or "")[:160]
    meta = t.get("metadata") or {}
    guard = meta.get("content_guard") or {}
    pa = meta.get("playbook_action") or meta.get("strategy", {}).get("playbook_action")
    tool_n = len(meta.get("tool_calls", []) or [])
    prod_n = len((meta.get("rag_hits", {}) or {}).get("product", []) or [])
    suffix = ""
    if guard.get("rewritten"):
        guard_hits += 1
        suffix = f" [GUARD rewrote {len(guard.get('warnings', []))} 处]"
    print(f"  #{idx} {spk}: {cnt}{suffix}")
    if spk == "sales":
        for w in forbidden_words:
            if w in t.get("content", ""):
                violations.append((idx, w, cnt))

print("\n----- 统计 -----")
print(f"content_guard 触发轮数  = {guard_hits}")
print(f"出现违禁词 (手写笔/M-Pencil) 的 sales 轮: {len(violations)}")
for v in violations:
    print(f"  · round {v[0]}: 包含 '{v[1]}' → {v[2]}")
