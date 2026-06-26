"""v0.2.1 真实性补丁 smoke：完全脱机验证 5 件事

1. PersonaProfile schema 接受 4 个新字段（不抛）
2. DB persona 行能正确序列化新字段
3. ToolContext 收到 persona_market_domains 后能往下传
4. _build_client_market_block 渲染含 "MYR / RM / consumer.huawei.com/my"
5. web_search.run_web_search(include_domains=[...]) **能正确把 domains 嵌入 query**
   — 用 monkeypatch 拦截 requests，不发真实网络请求

不依赖大模型 / 不依赖 Tavily / 不依赖前端启动。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PASSED = 0
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  ✗ {name}    {detail}")


print("\n[1] PersonaProfile schema 接受新字段")
from src.schema import PersonaProfile

p = PersonaProfile(
    id="test1",
    name="Test Ah Ming",
    country_code="MY",
    country_name="马来西亚",
    currency="MYR",
    market_domains=["consumer.huawei.com/my", "shopee.com.my"],
)
check("country_code 字段可读", p.country_code == "MY")
check("currency 字段可读", p.currency == "MYR")
check("market_domains 字段可读", "shopee.com.my" in p.market_domains)


print("\n[2] DB → PersonaProfile 序列化（拿 Ah Ming，id=1）")
from src.storage.db import get_connection, get_persona_by_id  # noqa: E402

conn = get_connection()
row = get_persona_by_id(conn, 1)
conn.close()
check("DB row 含 country_code", row.get("country_code") == "MY", f"got={row.get('country_code')}")
check("DB row 含 currency", row.get("currency") == "MYR", f"got={row.get('currency')}")
check("DB row 含 market_domains", "shopee.com.my" in (row.get("market_domains") or []), f"got={row.get('market_domains')}")

row2 = dict(row); row2["id"] = str(row2["id"])
p2 = PersonaProfile.model_validate(row2)
check("DB row → PersonaProfile.country_code", p2.country_code == "MY")
check("DB row → PersonaProfile.market_domains", "consumer.huawei.com/my" in p2.market_domains)


print("\n[3] _build_tool_context 把 persona market 塞到 ToolContext")
from src.agents import _build_tool_context  # noqa: E402
from src.schema import DialogueState  # noqa: E402

state = DialogueState(
    session_id="smoke-loc-1",
    topic="华为 Pura 70 拍照",
    product_text="",
    persona_profile=p2,
    language="zh-CN",
)
ctx = _build_tool_context(state)
check("ToolContext.persona_country_code == MY", ctx.persona_country_code == "MY")
check("ToolContext.persona_currency == MYR", ctx.persona_currency == "MYR")
check(
    "ToolContext.persona_market_domains 含 consumer.huawei.com/my",
    "consumer.huawei.com/my" in ctx.persona_market_domains,
)
check(
    "ToolContext.persona_market_domains 不含 jd.com（不串台）",
    "jd.com" not in ctx.persona_market_domains,
)


print("\n[4] _build_client_market_block 渲染")
from src.agents import _build_client_market_block  # noqa: E402

block = _build_client_market_block(state)
check("block 含 MYR", "MYR" in block)
check("block 含 RM（货币符号）", "RM" in block)
check("block 含 consumer.huawei.com/my", "consumer.huawei.com/my" in block)
check("block 含「马来西亚」", "马来西亚" in block)
check("block 不含 PHP（不串台）", "PHP" not in block)
print(f"\n  block 渲染示例：\n{'-'*70}\n{block}\n{'-'*70}\n")


print("\n[5] web_search 工具 — Tavily 调用时 include_domains 真的塞进 payload")
captured: dict[str, Any] = {}

class _FakeResp:
    status_code = 200
    text = "{}"
    def json(self):
        return {"results": [], "answer": None}

def _fake_post(url, json=None, timeout=None, **kw):
    captured["url"] = url
    captured["payload"] = json
    return _FakeResp()

from src.tools.web_search import _tool_web_search, _WebSearchArgs  # noqa: E402

with patch("src.tools.web_search.requests.post", side_effect=_fake_post), \
     patch("src.tools.web_search._load_web_search_cfg",
           return_value={"provider": "tavily", "api_key": "FAKE_KEY"}):
    args = _WebSearchArgs(query="Pura 70 价格", top_k=3)
    out = _tool_web_search(args, ctx)

check("Tavily POST 被调用", "payload" in captured)
check("payload 含 query", captured.get("payload", {}).get("query") == "Pura 70 价格")
check(
    "payload.include_domains 含 consumer.huawei.com/my",
    "consumer.huawei.com/my" in (captured.get("payload", {}).get("include_domains") or []),
)
check(
    "payload.include_domains 不含 jd.com",
    "jd.com" not in (captured.get("payload", {}).get("include_domains") or []),
)
check(
    "tool 输出 applied_domains 含 consumer.huawei.com/my",
    "consumer.huawei.com/my" in (out.get("applied_domains") or []),
)
check("tool 输出 persona_currency == MYR", out.get("persona_currency") == "MYR")


print("\n[6] web_search — SerpAPI 把 include_domains 转成 site: OR 子句")
captured.clear()

def _fake_get(url, params=None, timeout=None, **kw):
    captured["url"] = url
    captured["params"] = params
    return _FakeResp()

with patch("src.tools.web_search.requests.get", side_effect=_fake_get), \
     patch("src.tools.web_search._load_web_search_cfg",
           return_value={"provider": "serpapi", "api_key": "FAKE_KEY"}):
    args = _WebSearchArgs(query="Pura 70 价格", top_k=3)
    _tool_web_search(args, ctx)

q = captured.get("params", {}).get("q") or ""
check("SerpAPI q 含 'site:consumer.huawei.com/my'", "site:consumer.huawei.com/my" in q, f"q={q!r}")
check("SerpAPI q 含 OR 拼接", " OR " in q, f"q={q!r}")
check("SerpAPI q 含原 query", "Pura 70 价格" in q)


print("\n[7] web_search — 兜底：ToolContext 没 domains 时走全球 huawei 主站")
from src.tools.registry import ToolContext  # noqa: E402

empty_ctx = ToolContext(persona_market_domains=[])
captured.clear()
with patch("src.tools.web_search.requests.post", side_effect=_fake_post), \
     patch("src.tools.web_search._load_web_search_cfg",
           return_value={"provider": "tavily", "api_key": "FAKE_KEY"}):
    args = _WebSearchArgs(query="Mate 80", top_k=1)
    _tool_web_search(args, empty_ctx)

check(
    "无 persona 时也锁了 consumer.huawei.com（全球站兜底）",
    any("consumer.huawei.com" in d for d in
        (captured.get("payload", {}).get("include_domains") or [])),
)


print("\n" + "=" * 70)
total = PASSED + len(FAILED)
print(f"smoke 完成：{PASSED}/{total} 通过")
if FAILED:
    print("\n失败项：")
    for f in FAILED:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
