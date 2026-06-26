"""Web 搜索工具（Stage 14 Phase B）。

支持 provider：
- ``tavily``  → ``https://api.tavily.com/search``（推荐：返回干净摘要 + URL）
- ``serpapi`` → ``https://serpapi.com/search``（兜底）
- ``bing``    → Azure Bing Web Search API（保留扩展点，本轮抛"未实现"）

设计要点：
1. API key 与 provider 都在运行期从 ``agent_skills_config`` 表读取，
   不需要 UI 改动配置后重启服务；
2. 未配置 key / 空 query / HTTP 异常 → 返回结构化 ``{"error": "..."}`` 而不是抛，
   保证 Sales Agent tool-loop 即使没 key 也能继续走老 RAG 路径；
3. 整体限时 8s，结果截断（最多 5 条 + 每条摘要 600 字），避免污染上下文窗口。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests
from pydantic import BaseModel, Field

from src.tools.registry import ToolContext, tool

logger = logging.getLogger(__name__)


_REQUEST_TIMEOUT = 8.0
_MAX_RESULTS_HARD = 5
_SNIPPET_LIMIT = 600


# ---------------------------------------------------------------------------
# 运行期配置读取
# ---------------------------------------------------------------------------


def _load_web_search_cfg() -> dict[str, Any]:
    """从 agent_skills_config 读 provider/key；任何异常返回默认值。"""
    try:
        from src.storage.db import get_agent_skills_config, get_connection
    except Exception as exc:  # noqa: BLE001
        logger.debug("storage 不可用，web_search cfg 用默认值：%s", exc)
        return {"provider": "tavily", "api_key": ""}
    try:
        conn = get_connection()
    except Exception as exc:  # noqa: BLE001
        logger.debug("连接 SQLite 失败，web_search cfg 用默认值：%s", exc)
        return {"provider": "tavily", "api_key": ""}
    try:
        cfg = get_agent_skills_config(conn)
        return {
            "provider": str(cfg.get("web_search_provider") or "tavily").lower().strip(),
            "api_key": str(cfg.get("web_search_api_key") or "").strip(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 web_search cfg 失败：%s", exc)
        return {"provider": "tavily", "api_key": ""}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def _call_tavily(
    query: str,
    top_k: int,
    api_key: str,
    *,
    include_domains: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Tavily Search API。文档：https://docs.tavily.com/docs/rest-api/api-reference

    v0.2.1：``include_domains`` 非空时强制只查这些域名 → 实现 strict_local 信源锁定。
    """
    payload: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": top_k,
        "include_answer": True,
        "include_raw_content": False,
        "include_images": False,
    }
    if include_domains:
        # Tavily 原生支持，参数名就是 include_domains，传 list[str]
        payload["include_domains"] = list(include_domains)
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {"error": f"Tavily 网络异常: {type(exc).__name__}: {exc}"}
    if resp.status_code != 200:
        return {
            "error": f"Tavily HTTP {resp.status_code}: {resp.text[:300]}",
        }
    try:
        data = resp.json() or {}
    except Exception as exc:
        return {"error": f"Tavily 响应非 JSON: {exc}"}
    results_raw = data.get("results") or []
    results: list[dict[str, Any]] = []
    for r in results_raw[:top_k]:
        content = (r.get("content") or "")
        if len(content) > _SNIPPET_LIMIT:
            content = content[:_SNIPPET_LIMIT] + "…"
        results.append({
            "title": r.get("title"),
            "url": r.get("url"),
            "snippet": content,
            "score": r.get("score"),
        })
    return {
        "provider": "tavily",
        "query": query,
        "answer": data.get("answer"),
        "count": len(results),
        "results": results,
    }


def _call_serpapi(
    query: str,
    top_k: int,
    api_key: str,
    *,
    include_domains: Optional[list[str]] = None,
) -> dict[str, Any]:
    """SerpAPI Google 通用搜索。

    v0.2.1：``include_domains`` 非空时把 ``site:`` operator 拼进 query 实现信源锁定。
    Google 语法是 ``query (site:a.com OR site:b.com OR ...)``。
    """
    q_final = query
    if include_domains:
        sites_or = " OR ".join(f"site:{d}" for d in include_domains)
        q_final = f"{query} ({sites_or})"
    params = {
        "engine": "google",
        "q": q_final,
        "api_key": api_key,
        "num": top_k,
    }
    try:
        resp = requests.get(
            "https://serpapi.com/search",
            params=params,
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {"error": f"SerpAPI 网络异常: {type(exc).__name__}: {exc}"}
    if resp.status_code != 200:
        return {
            "error": f"SerpAPI HTTP {resp.status_code}: {resp.text[:300]}",
        }
    try:
        data = resp.json() or {}
    except Exception as exc:
        return {"error": f"SerpAPI 响应非 JSON: {exc}"}
    organic = data.get("organic_results") or []
    results: list[dict[str, Any]] = []
    for r in organic[:top_k]:
        snippet = (r.get("snippet") or "")
        if len(snippet) > _SNIPPET_LIMIT:
            snippet = snippet[:_SNIPPET_LIMIT] + "…"
        results.append({
            "title": r.get("title"),
            "url": r.get("link"),
            "snippet": snippet,
            "score": r.get("position"),
        })
    answer_box = data.get("answer_box") or {}
    return {
        "provider": "serpapi",
        "query": query,
        "answer": answer_box.get("answer") or answer_box.get("snippet"),
        "count": len(results),
        "results": results,
    }


def _dispatch(
    provider: str,
    query: str,
    top_k: int,
    api_key: str,
    *,
    include_domains: Optional[list[str]] = None,
) -> dict[str, Any]:
    p = (provider or "tavily").lower().strip()
    if p == "tavily":
        return _call_tavily(query, top_k, api_key, include_domains=include_domains)
    if p == "serpapi":
        return _call_serpapi(query, top_k, api_key, include_domains=include_domains)
    if p == "bing":
        return {"error": "Bing Web Search 暂未接入，请先切换到 tavily / serpapi"}
    return {"error": f"未知 provider：{provider}"}


# ---------------------------------------------------------------------------
# 对外暴露函数（供 routes_agent_skills 的 /test_web_search 直接调用）
# ---------------------------------------------------------------------------


def run_web_search(
    query: str,
    top_k: int = 3,
    *,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    include_domains: Optional[list[str]] = None,
) -> dict[str, Any]:
    """带 provider/key 覆盖入参的工具调用，**永远不抛**，错误转 ``{"error": ...}``。

    v0.2.1：``include_domains`` 把信源锁定到 persona 的本地市场域名。
    """
    q = (query or "").strip()
    if not q:
        return {"error": "query 不能为空"}
    if top_k < 1:
        top_k = 1
    if top_k > _MAX_RESULTS_HARD:
        top_k = _MAX_RESULTS_HARD

    cfg = _load_web_search_cfg()
    p = provider or cfg["provider"]
    k = api_key if api_key is not None else cfg["api_key"]

    if not k:
        return {
            "error": (
                f"Web Search 未配置 API Key。请到「系统设置 → 销冠技能 → 全局参数」"
                f"里填入 {p} 的 API Key。"
            ),
        }
    try:
        return _dispatch(p, q, top_k, k, include_domains=include_domains)
    except Exception as exc:  # noqa: BLE001
        logger.exception("web_search 调用未预期异常")
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# 注册为 Sales Agent 可调用的工具
# ---------------------------------------------------------------------------


class _WebSearchArgs(BaseModel):
    query: str = Field(
        ...,
        description="检索关键词。常用于查友商对比价格、行业新闻、第三方评测、客户提到的陌生概念等。",
    )
    top_k: int = Field(
        3, ge=1, le=_MAX_RESULTS_HARD,
        description=f"返回前 K 条结果，1-{_MAX_RESULTS_HARD}",
    )


@tool(
    name="web_search",
    description=(
        "调用外部搜索引擎检索实时互联网信息。当产品库 / 企业库 / 案例库都覆盖不到客户提问"
        "（友商最新价格、行业新闻、第三方评测、新品对比、政策变动等）时使用。"
        "不要拿来回答可以从内部知识库回答的问题——优先调 search_product_kb / search_enterprise_kb。"
        " v0.2.1 起：本工具自动锁定客户所在国家的可信信源（华为官方该国分站 + 该国主流电商）"
        "，你拿到的 URL 一定属于客户本地市场。"
    ),
    schema=_WebSearchArgs,
    category="web",
)
def _tool_web_search(args: _WebSearchArgs, ctx: ToolContext) -> dict[str, Any]:
    """v0.2.1 真实性补丁：从 ToolContext 拿 persona_market_domains，
    强制 include_domains 实现 strict_local 信源锁定。

    如果 ctx 上没 persona_market_domains（独立测试 / 未传 persona），
    fallback 到全球 huawei 主站（DEFAULT_GLOBAL_MARKET.market_domains）。
    """
    # 优先用 persona 显式域名；否则 fallback 到全球 huawei 主站
    domains = list(ctx.persona_market_domains or [])
    if not domains:
        from src.locales import DEFAULT_GLOBAL_MARKET
        domains = list(DEFAULT_GLOBAL_MARKET.market_domains)

    result = run_web_search(args.query, args.top_k, include_domains=domains)

    # 附加 "applied_domains" 元信息，方便前端可视化 + Judge 复查
    if isinstance(result, dict) and "error" not in result:
        result["applied_domains"] = domains
        result["persona_country_code"] = ctx.persona_country_code
        result["persona_currency"] = ctx.persona_currency
    return result
