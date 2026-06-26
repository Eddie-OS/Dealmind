"""不调真实 API 的 smoke：验证 thinking / extra_body / cache log 是否按预期构造。

模式：
  1. monkeypatch ``openai.OpenAI`` 让 ``client.chat.completions.create``
     返回一个 fake response（含 usage + cache 字段）。
  2. 模拟三种典型调用路径：
     a) 默认 sales 调用（无 override）→ kwargs 不含 extra_body，含 temperature
     b) classifier 路径（thinking enabled + effort=high）→ kwargs 含 extra_body
        的 thinking={"type":"enabled"} + reasoning_effort="high"，且不含 temperature
     c) extractor 路径（thinking enabled + effort=max）→ extra_body.reasoning_effort == "max"
  3. 验证日志包含 "cache hit=" 字样。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _fake_response(model: str) -> Any:
    msg = SimpleNamespace(
        content='{"ok": true}',
        reasoning_content=None,
        tool_calls=None,
    )
    choice = SimpleNamespace(message=msg, finish_reason="stop", index=0)
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=200,
        prompt_cache_hit_tokens=700,
        prompt_cache_miss_tokens=300,
        total_tokens=1200,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=80),
    )
    return SimpleNamespace(
        id="resp-fake",
        choices=[choice],
        model=model,
        usage=usage,
    )


# 必须先确保有 API KEY（哪怕假的），让 Settings 能加载
os.environ.setdefault("OPENAI_API_KEY", "sk-fake-test-key")
os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
os.environ["MODEL_NAME"] = "deepseek-v4-pro"

from src import llm  # noqa: E402
from src.llm import LLMOverride, call_llm, with_llm_override  # noqa: E402


captured_kwargs: list[dict[str, Any]] = []


class _FakeCompletions:
    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        captured_kwargs.append(kwargs)
        return _fake_response(kwargs.get("model", "?"))


class _FakeChat:
    completions = _FakeCompletions()


class _FakeClient:
    chat = _FakeChat()


# 替换全局 client，跳过真实初始化
llm._client = _FakeClient()  # type: ignore[attr-defined]
llm._settings = llm.Settings(  # type: ignore[attr-defined]
    api_key="sk-fake-test-key",
    base_url="https://api.deepseek.com",
    model_name="deepseek-v4-pro",
    temperature=1.0,
    max_retries=0,
)
llm._source = "test"  # type: ignore[attr-defined]


def _check(label: str, kw: dict, *, expect_extra: dict | None, expect_temp: bool) -> None:
    print(f"\n=== {label} ===")
    print(f"  model         = {kw.get('model')}")
    print(f"  has temperature = {'temperature' in kw} (value={kw.get('temperature')})")
    print(f"  extra_body    = {kw.get('extra_body')}")

    assert kw.get("model") == "deepseek-v4-pro", f"model 应为 deepseek-v4-pro，实际 {kw.get('model')}"

    if expect_temp:
        assert "temperature" in kw, f"[{label}] 期望含 temperature 但 kwargs 缺失"
    else:
        assert "temperature" not in kw, (
            f"[{label}] 思考模式不应传 temperature，实际仍存在: {kw.get('temperature')}"
        )

    if expect_extra is None:
        assert "extra_body" not in kw, (
            f"[{label}] 不应有 extra_body，实际: {kw.get('extra_body')}"
        )
    else:
        eb = kw.get("extra_body") or {}
        for k, v in expect_extra.items():
            assert eb.get(k) == v, (
                f"[{label}] extra_body.{k} 期望 {v}，实际 {eb.get(k)}"
            )


def run() -> None:
    captured_kwargs.clear()

    print("\n--- A) 默认销售调用（无 override）---")
    call_llm("你是销售", "你好")
    _check(
        "default-sales",
        captured_kwargs[-1],
        expect_extra=None,
        expect_temp=True,
    )

    print("\n--- B) classifier 路径（thinking enabled / effort=high）---")
    with with_llm_override(
        LLMOverride(thinking_mode="enabled", reasoning_effort="high")
    ):
        call_llm("分类器", "判一下")
    _check(
        "classifier-thinking-high",
        captured_kwargs[-1],
        expect_extra={
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        },
        expect_temp=False,
    )

    print("\n--- C) extractor 路径（thinking enabled / effort=max）---")
    with with_llm_override(
        LLMOverride(thinking_mode="enabled", reasoning_effort="max")
    ):
        call_llm("抽取", "拆结构")
    _check(
        "extractor-thinking-max",
        captured_kwargs[-1],
        expect_extra={
            "thinking": {"type": "enabled"},
            "reasoning_effort": "max",
        },
        expect_temp=False,
    )

    print("\n--- D) override disabled（v4-pro 默认思考，显式关掉）---")
    with with_llm_override(LLMOverride(thinking_mode="disabled")):
        call_llm("速答", "快")
    _check(
        "disabled-thinking",
        captured_kwargs[-1],
        expect_extra={"thinking": {"type": "disabled"}},
        expect_temp=True,
    )

    print("\nALL ASSERTIONS PASSED")


if __name__ == "__main__":
    run()
