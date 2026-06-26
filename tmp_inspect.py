import json, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

with open("tmp_detail.json", "r", encoding="utf-8") as f:
    d = json.load(f)

s = d["session"]
print("status:", s.get("status"), "runtime:", s.get("runtime_status"))
print("config.language:", (s.get("config") or {}).get("language"))
print("total_rounds:", d["metrics"]["total_rounds"])
print("---- turns (last 6) ----")
for t in d["turns"][-6:]:
    print(f"[{t['idx']}] {t['speaker']}: {t['content'][:160]}")
