"""通用工具：JSON 提取与修复、时间戳、字符串处理。

LLM 输出很少是完全干净的 JSON：常见情况包括 ``` 代码块包裹、JSON 前后混入解释文字、
偶尔尾随逗号、字符串里有未转义换行等。本模块给出统一的兜底解析路径，避免一次模型
抖动让整场会话崩掉。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any


_CODE_FENCE_PATTERN = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)


def strip_code_fence(text: str) -> str:
    """去掉 ```json ... ``` 或 ``` ... ``` 包裹。

    若没有代码块，原样返回。多段代码块只剥外层一次。
    """
    if not text:
        return text
    match = _CODE_FENCE_PATTERN.match(text.strip())
    if match:
        return match.group(1).strip()
    return text


def _find_first_json_block(text: str) -> str:
    """从文本中提取第一个看起来完整的 JSON object 或 array。

    用括号配对而非正则，能正确处理嵌套 {} / []。字符串内的括号会被忽略。
    """
    if not text:
        return ""

    open_char = ""
    close_char = ""
    start = -1
    for i, ch in enumerate(text):
        if ch in "{[":
            open_char = ch
            close_char = "}" if ch == "{" else "]"
            start = i
            break
    if start < 0:
        return ""

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def _strip_trailing_commas(text: str) -> str:
    """移除 JSON object/array 中常见的尾随逗号。"""
    return re.sub(r",(\s*[}\]])", r"\1", text)


def extract_json(text: str) -> Any:
    """从可能含杂质的文本中提取 JSON。

    解析顺序：
    1. 直接 json.loads（最快路径，模型守规矩时命中）。
    2. 去掉代码块包裹后再 loads。
    3. 用括号配对截取第一个 JSON 块后 loads。
    4. 移除尾随逗号再 loads。
    任何一步成功就返回；全部失败抛 ValueError，附带原文本前 300 字符。
    """
    if text is None:
        raise ValueError("extract_json 接收到 None")

    raw = text if isinstance(text, str) else str(text)

    attempts = []

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        attempts.append(("raw", str(exc)))

    stripped = strip_code_fence(raw)
    if stripped != raw:
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            attempts.append(("stripped", str(exc)))

    candidate = _find_first_json_block(stripped) or _find_first_json_block(raw)
    if candidate:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            attempts.append(("first_block", str(exc)))
        try:
            return json.loads(_strip_trailing_commas(candidate))
        except json.JSONDecodeError as exc:
            attempts.append(("no_trailing_commas", str(exc)))

    preview = raw[:300].replace("\n", "\\n")
    raise ValueError(
        f"无法从文本中提取合法 JSON。尝试路径={[a[0] for a in attempts]}，"
        f"原文本前 300 字符: {preview!r}"
    )


def safe_json_dumps(data: Any, indent: int = 2) -> str:
    """统一的 JSON 序列化：支持中文、保留缩进、容忍非标准类型。"""
    return json.dumps(data, ensure_ascii=False, indent=indent, default=str)


def now_timestamp() -> str:
    """生成 YYYYMMDD_HHMMSS 格式时间戳，用于 session 目录命名。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")
