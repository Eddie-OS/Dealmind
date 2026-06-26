"""LLM 调用层。

封装 OpenAI 兼容 SDK 的最小调用面，对外提供：
- call_llm：纯文本调用
- call_llm_json：要求模型返回 JSON 并做兜底解析

设计要点：
1. Client 用模块级 lazy 单例，避免每次调用都新建连接。
2. API Key 永远不进日志；rich 控制台只打印模型名 / 重试次数 / 状态。
3. 网络/服务端错误重试 max_retries 次，每次间隔 2s。
4. JSON 解析失败时**额外重试一次**，并在 user_prompt 末尾追加"只输出 JSON"。
5. 仍失败抛 LLMJsonParseError，保留原始输出片段，方便上层 fallback 兜底而不是直接崩。
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

import httpx
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
from src.config import Settings, load_settings
from src.safe_console import SafeConsole
from src.utils import extract_json


console = SafeConsole()
logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None
_settings: Optional[Settings] = None
_source: Optional[str] = None

# 自愈代理：环境里配了 HTTP(S)_PROXY/ALL_PROXY 但代理实际没开（连接被拒）时，
# OpenAI/httpx 默认会去走这个坏代理 → APIConnectionError。这里探活一次，
# 不可达就让 LLM 客户端直连（trust_env=False）绕过坏代理。进程内只判一次。
_http_client: Optional[httpx.Client] = None
_http_client_ready = False


def _proxy_alive(proxy_url: str, timeout: float = 0.6) -> bool:
    """快速 TCP 探测代理是否在监听。"""
    try:
        parsed = urlparse(proxy_url if "://" in proxy_url else f"http://{proxy_url}")
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _build_http_client() -> Optional[httpx.Client]:
    """给 OpenAI client 用的 httpx client。

    返回 None → 用 OpenAI 默认行为（含 trust_env 读取系统代理）；
    若检测到环境代理不可达，则返回一个 trust_env=False 的直连 client，绕过坏代理。
    """
    global _http_client, _http_client_ready
    if _http_client_ready:
        return _http_client

    proxy = (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
        or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    )
    if proxy and not _proxy_alive(proxy):
        logger.warning(
            "代理 %s 不可达，LLM 客户端改为直连（trust_env=False）以绕过坏代理环境变量",
            proxy,
        )
        _http_client = httpx.Client(trust_env=False, timeout=httpx.Timeout(60.0))
    else:
        _http_client = None
    _http_client_ready = True
    return _http_client


# ---------------------------------------------------------------------------
# Stage 15a Phase B-2：Agent 级 LLM 覆盖（per-call provider/temperature/max_tokens）
#
# 用法：``with with_llm_override(LLMOverride(provider_id=3, temperature=0.2)):``
#   - 在该上下文中所有 ``call_llm*`` 都会：
#       1. 如指定 ``provider_id``，临时构造一个对应的 OpenAI client + settings
#          （不污染全局单例）。
#       2. 如指定 ``temperature``/``max_tokens``，在 chat 请求中覆盖默认值。
#   - 退出上下文后立即恢复成全局单例。
# 设计原则：调用方零侵入（不需要改函数签名），其它进程内并发也通过 contextvars 安全隔离。
# ---------------------------------------------------------------------------


@dataclass
class LLMOverride:
    provider_id: Optional[int] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    # DeepSeek V4 系列专属：thinking 模式开关 + 推理强度
    # thinking_mode: "enabled" | "disabled" | None（None=不覆盖，跟随模型默认）
    # reasoning_effort: "high" | "max" | None（仅 thinking enabled 时生效）
    thinking_mode: Optional[str] = None
    reasoning_effort: Optional[str] = None


_override_var: ContextVar[Optional[LLMOverride]] = ContextVar(
    "llm_override", default=None
)

# 全局限流：批量并发 + 分析并发时防止打爆 provider
_llm_inflight: Optional[threading.Semaphore] = None
_llm_inflight_lock = threading.Lock()


def _acquire_llm_slot() -> None:
    global _llm_inflight
    with _llm_inflight_lock:
        if _llm_inflight is None:
            try:
                from src.perf_config import LLM_MAX_IN_FLIGHT

                n = max(1, LLM_MAX_IN_FLIGHT)
            except Exception:  # noqa: BLE001
                n = 12
            _llm_inflight = threading.Semaphore(n)
    _llm_inflight.acquire()


def _release_llm_slot() -> None:
    if _llm_inflight is not None:
        _llm_inflight.release()


@contextmanager
def with_llm_override(override: Optional[LLMOverride]) -> Iterator[None]:
    """临时切换 LLM provider / 采样参数（线程&协程安全）。

    ``override`` 为 ``None`` / 全空时等价于 no-op，永远不会抛异常。
    """
    if override is None or (
        override.provider_id is None
        and override.model is None
        and override.temperature is None
        and override.max_tokens is None
        and override.thinking_mode is None
        and override.reasoning_effort is None
    ):
        yield
        return
    token = _override_var.set(override)
    try:
        yield
    finally:
        _override_var.reset(token)


def _current_override() -> Optional[LLMOverride]:
    return _override_var.get()


def _settings_from_provider_id(provider_id: int) -> Optional[Settings]:
    """根据 provider_id 从 DB 构造 ``Settings``，失败安全返回 None。"""
    try:
        from src.storage.db import get_connection, get_provider_by_id  # 延迟导入
    except Exception as exc:  # noqa: BLE001
        logger.debug("storage 不可用，无法读 provider_id=%s：%s", provider_id, exc)
        return None
    try:
        conn = get_connection()
    except Exception as exc:  # noqa: BLE001
        logger.warning("无法连接 SQLite，跳过 override provider：%s", exc)
        return None
    try:
        row = get_provider_by_id(conn, int(provider_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("读 provider_id=%s 失败：%s", provider_id, exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    if not row or not row.get("api_key"):
        return None
    return Settings(
        api_key=row["api_key"],
        base_url=row["base_url"],
        model_name=row["model_name"],
        temperature=float(row["temperature"]),
        max_retries=int(row["max_retries"]),
    )


class LLMCallError(RuntimeError):
    """所有 LLM 网络/服务端调用失败统一抛这个。"""


class LLMJsonParseError(RuntimeError):
    """LLM 输出经过两轮解析仍不是合法 JSON 时抛出，附带原始输出片段。"""

    def __init__(self, message: str, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


def _settings_from_db_provider() -> Optional[Settings]:
    """尝试从 SQLite default provider 读出 Settings；任何异常都返回 None。

    隔离原则：DB 不可用时不能影响 MVP CLI / 单测路径，
    所以在这层把所有异常吞掉并记日志，由上层 fallback 到 .env。
    """
    try:
        from src.storage.db import get_connection, get_default_provider  # 延迟导入避免循环
    except Exception as exc:  # noqa: BLE001
        logger.debug("storage 模块不可用，跳过 DB provider 读取：%s", exc)
        return None

    try:
        conn = get_connection()
    except Exception as exc:  # noqa: BLE001
        logger.debug("无法连接 SQLite，回退 .env：%s", exc)
        return None

    try:
        row = get_default_provider(conn)
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询 default provider 失败，回退 .env：%s", exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if not row:
        return None
    if not row.get("api_key"):
        logger.warning("DB default provider 缺少 api_key，回退 .env")
        return None

    return Settings(
        api_key=row["api_key"],
        base_url=row["base_url"],
        model_name=row["model_name"],
        temperature=float(row["temperature"]),
        max_retries=int(row["max_retries"]),
    )


def _get_client_and_settings() -> tuple[OpenAI, Settings]:
    """惰性初始化 client；进程内复用。

    优先级：
      1. 当前上下文 ``with_llm_override(provider_id=...)`` → 一次性临时 client（不缓存）
      2. DB default provider → 进程内单例
      3. .env（MVP 行为）→ 进程内单例
    """
    # ① override 路径：每次调用都临时构造，不污染全局单例
    ov = _current_override()
    if ov is not None and ov.provider_id is not None:
        ov_settings = _settings_from_provider_id(int(ov.provider_id))
        if ov_settings is not None:
            ov_client = OpenAI(
                api_key=ov_settings.api_key,
                base_url=ov_settings.base_url,
                http_client=_build_http_client(),
            )
            return ov_client, ov_settings
        logger.warning(
            "with_llm_override 指定 provider_id=%s 读取失败，回退全局 client",
            ov.provider_id,
        )

    # ② 全局单例路径
    global _client, _settings, _source
    if _client is None or _settings is None:
        db_settings = _settings_from_db_provider()
        if db_settings is not None:
            _settings = db_settings
            _source = "db"
            logger.info(
                "LLM provider from DB: base_url=%s model=%s",
                _settings.base_url, _settings.model_name,
            )
        else:
            _settings = load_settings()
            _source = "env"
            logger.info(
                "LLM provider from .env: base_url=%s model=%s",
                _settings.base_url, _settings.model_name,
            )
        _client = OpenAI(
            api_key=_settings.api_key,
            base_url=_settings.base_url,
            http_client=_build_http_client(),
        )
    return _client, _settings


def get_active_source() -> Optional[str]:
    """返回当前 client 的来源：'db' / 'env' / None（未初始化）。"""
    return _source


def reset_client_for_test() -> None:
    """单测/切换 provider 时使用，重置 client 缓存。"""
    global _client, _settings, _source
    _client = None
    _settings = None
    _source = None


def _is_thinking_enabled(ov: Optional[LLMOverride]) -> bool:
    """判断当前是否启用了思考模式（仅看 override 显式设置）。"""
    return ov is not None and ov.thinking_mode == "enabled"


def _build_deepseek_extra_body(ov: Optional[LLMOverride]) -> dict[str, Any]:
    """根据 override 构造 DeepSeek V4 专属 extra_body 参数。

    通过 OpenAI SDK 的 ``extra_body`` 透传非标准字段，
    保证对 OpenAI / 其它兼容服务零副作用（被忽略）。
    """
    if ov is None:
        return {}
    extra: dict[str, Any] = {}
    if ov.thinking_mode in ("enabled", "disabled"):
        extra["thinking"] = {"type": ov.thinking_mode}
    if ov.reasoning_effort in ("high", "max"):
        extra["reasoning_effort"] = ov.reasoning_effort
    return extra


def _log_usage(resp: Any, model_name: str) -> None:
    """打印 token / cache 命中统计，方便观测 DeepSeek 上下文缓存折扣。"""
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        hit = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        miss = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = 0
        if details is not None:
            reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0
        hit_ratio = (hit / prompt_tokens * 100) if prompt_tokens else 0.0
        console.print(
            f"[dim]LLM usage[/dim] model=[cyan]{model_name}[/cyan] "
            f"prompt={prompt_tokens} (cache hit={hit}/{hit_ratio:.0f}%) "
            f"completion={completion_tokens}"
            + (f" (reasoning={reasoning_tokens})" if reasoning_tokens else "")
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("usage 日志打印失败：%s", exc)


def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: Optional[float] = None,
    response_format_json: bool = False,
) -> str:
    """调用模型，返回纯文本。

    Args:
        system_prompt: 系统提示。
        user_prompt: 用户提示。
        temperature: 不传则用 .env 默认值。思考模式下会被服务端忽略。
        response_format_json: True 时尝试启用 response_format={"type":"json_object"}，
            某些兼容服务不支持会自动降级。

    Raises:
        LLMCallError: 所有重试均失败。
    """
    client, settings = _get_client_and_settings()
    ov = _current_override()
    thinking_on = _is_thinking_enabled(ov)
    # 优先级 temperature: 显式参数 > override > settings 默认
    if temperature is not None:
        temp = temperature
    elif ov is not None and ov.temperature is not None:
        temp = ov.temperature
    else:
        temp = settings.temperature
    model_name = (ov.model if ov and ov.model else settings.model_name)

    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    # 思考模式下 temperature/top_p 被服务端忽略，干脆不传，避免误导日志
    if not thinking_on:
        kwargs["temperature"] = temp
    if ov is not None and ov.max_tokens:
        kwargs["max_tokens"] = int(ov.max_tokens)
    if response_format_json:
        kwargs["response_format"] = {"type": "json_object"}
    extra_body = _build_deepseek_extra_body(ov)
    if extra_body:
        kwargs["extra_body"] = extra_body

    last_error: Optional[Exception] = None
    for attempt in range(1, settings.max_retries + 2):  # max_retries 次重试 = 总共 +1 次
        try:
            think_tag = ""
            if extra_body.get("thinking"):
                think_tag = f" thinking={extra_body['thinking']['type']}"
                if extra_body.get("reasoning_effort"):
                    think_tag += f"/effort={extra_body['reasoning_effort']}"
            console.print(
                f"[dim]LLM call[/dim] model=[cyan]{model_name}[/cyan] "
                f"temp={'-' if thinking_on else temp}{think_tag} "
                f"attempt={attempt}/{settings.max_retries + 1}"
            )
            _acquire_llm_slot()
            try:
                resp = client.chat.completions.create(**kwargs)
            finally:
                _release_llm_slot()
            content = resp.choices[0].message.content or ""
            _log_usage(resp, model_name)
            return content
        except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
            last_error = exc
            console.print(
                f"[yellow]LLM 暂时性错误（attempt {attempt}）:[/yellow] "
                f"{type(exc).__name__}: {exc}"
            )
            if attempt <= settings.max_retries:
                time.sleep(2)
                continue
            break
        except APIError as exc:
            msg = str(exc).lower()
            if response_format_json and "response_format" in msg:
                console.print(
                    "[yellow]当前服务不支持 response_format=json_object，自动降级到纯文本模式。[/yellow]"
                )
                kwargs.pop("response_format", None)
                continue
            # thinking / reasoning_effort 不被服务端支持 → 自动剥离重试
            if extra_body and ("thinking" in msg or "reasoning_effort" in msg):
                console.print(
                    "[yellow]当前服务不支持 thinking/reasoning_effort，自动剥离重试。[/yellow]"
                )
                kwargs.pop("extra_body", None)
                extra_body = {}
                continue
            last_error = exc
            console.print(f"[red]LLM API 错误:[/red] {type(exc).__name__}: {exc}")
            if attempt <= settings.max_retries:
                time.sleep(2)
                continue
            break

    raise LLMCallError(
        f"LLM 调用失败，已重试 {settings.max_retries} 次。最后错误: "
        f"{type(last_error).__name__ if last_error else 'Unknown'}: {last_error}"
    )


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    temperature: Optional[float] = None,
) -> Any:
    """要求模型返回 JSON，并保证解析成功（或抛出可读错误）。

    解析失败 → 在 user_prompt 末尾追加强约束重试一次 → 仍失败抛 LLMJsonParseError。

    Returns:
        解析后的 dict / list。
    """
    raw = call_llm(
        system_prompt,
        user_prompt,
        temperature=temperature,
        response_format_json=True,
    )
    try:
        return extract_json(raw)
    except ValueError as exc:
        console.print(
            f"[yellow]首轮 JSON 解析失败:[/yellow] {exc}\n[dim]触发强约束重试...[/dim]"
        )

    reinforced_prompt = (
        user_prompt.rstrip()
        + "\n\n"
        + "请只输出合法 JSON 对象，不要任何 markdown 代码块、解释、前后缀文字。"
        + "你的整个回复必须可以被 json.loads 直接解析。"
    )
    retry_raw = call_llm(
        system_prompt,
        reinforced_prompt,
        temperature=temperature,
        response_format_json=True,
    )
    try:
        return extract_json(retry_raw)
    except ValueError as exc:
        preview = (retry_raw or "")[:500]
        raise LLMJsonParseError(
            f"LLM 输出经两轮解析仍非合法 JSON。最后错误: {exc}",
            raw_output=preview,
        ) from exc


# ===========================================================================
# Stage 14: 带工具调用的 chat 接口
# ===========================================================================


def call_llm_with_tools(
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    *,
    temperature: Optional[float] = None,
    response_format_json: bool = False,
    tool_choice: Optional[Any] = None,
) -> Any:
    """带 ``tools`` 参数的 chat completion，**直接返回 OpenAI message 对象**。

    返回的是 ``resp.choices[0].message``（含 ``content`` 和 ``tool_calls``），
    由上层（``agents.py``）解析 tool_calls 并循环。

    - 当 ``tools`` 为空时退化为普通 chat。
    - 当 ``response_format_json=True`` 且服务不支持时自动降级到纯文本，与 ``call_llm`` 一致。
    """
    client, settings = _get_client_and_settings()
    ov = _current_override()
    thinking_on = _is_thinking_enabled(ov)
    if temperature is not None:
        temp = temperature
    elif ov is not None and ov.temperature is not None:
        temp = ov.temperature
    else:
        temp = settings.temperature
    model_name = (ov.model if ov and ov.model else settings.model_name)

    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if not thinking_on:
        kwargs["temperature"] = temp
    if ov is not None and ov.max_tokens:
        kwargs["max_tokens"] = int(ov.max_tokens)
    # DeepSeek 文档明确：思考模式不支持 function calling，自动禁用 tools 路径
    if tools and not thinking_on:
        kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
    elif tools and thinking_on:
        logger.info("当前 thinking 模式不支持 tools，本次调用自动跳过工具透传。")
    if response_format_json:
        kwargs["response_format"] = {"type": "json_object"}
    extra_body = _build_deepseek_extra_body(ov)
    # 防御性：tools 路径 = 工具循环 + 多轮（assistant message 来回传），
    # DeepSeek V4-Pro 服务端默认开启 thinking，会强制要求把 reasoning_content
    # 传回 API，否则 400。这里只要传了 tools，就强制 disable thinking，避免踩坑。
    # （除非调用方显式 enabled——那种情况上面已经把 tools 剥离了。）
    if tools and not thinking_on:
        extra_body.setdefault("thinking", {"type": "disabled"})
    if extra_body:
        kwargs["extra_body"] = extra_body

    last_error: Optional[Exception] = None
    for attempt in range(1, settings.max_retries + 2):
        try:
            think_tag = ""
            if extra_body.get("thinking"):
                think_tag = f" thinking={extra_body['thinking']['type']}"
                if extra_body.get("reasoning_effort"):
                    think_tag += f"/effort={extra_body['reasoning_effort']}"
            console.print(
                f"[dim]LLM call (tools={len(tools or [])})[/dim] "
                f"model=[cyan]{model_name}[/cyan] "
                f"temp={'-' if thinking_on else temp}{think_tag} "
                f"attempt={attempt}/{settings.max_retries + 1}"
            )
            _acquire_llm_slot()
            try:
                resp = client.chat.completions.create(**kwargs)
            finally:
                _release_llm_slot()
            _log_usage(resp, model_name)
            return resp.choices[0].message
        except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
            last_error = exc
            console.print(
                f"[yellow]LLM 暂时性错误（attempt {attempt}）:[/yellow] "
                f"{type(exc).__name__}: {exc}"
            )
            if attempt <= settings.max_retries:
                time.sleep(2)
                continue
            break
        except APIError as exc:
            msg = str(exc).lower()
            if response_format_json and "response_format" in msg:
                console.print(
                    "[yellow]当前服务不支持 response_format=json_object，自动降级。[/yellow]"
                )
                kwargs.pop("response_format", None)
                continue
            if extra_body and ("thinking" in msg or "reasoning_effort" in msg):
                console.print(
                    "[yellow]当前服务不支持 thinking/reasoning_effort，自动剥离重试。[/yellow]"
                )
                kwargs.pop("extra_body", None)
                extra_body = {}
                continue
            last_error = exc
            console.print(f"[red]LLM API 错误:[/red] {type(exc).__name__}: {exc}")
            if attempt <= settings.max_retries:
                time.sleep(2)
                continue
            break

    raise LLMCallError(
        f"LLM(tools) 调用失败，已重试 {settings.max_retries} 次。最后错误: "
        f"{type(last_error).__name__ if last_error else 'Unknown'}: {last_error}"
    )
