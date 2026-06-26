"""多格式人设文件解析。

支持的格式：
- .json：顶层含 `personas` 数组 → panel 批量；否则按单 persona dict 解析
- .yaml/.yml：单 persona，按 MVP 严格结构
- .md/.txt：整段文本作为 prompt_text，构造 prompt_based persona

统一输出：list[dict]，每条 dict 字段：
    id (可选；DB 会重新分配), name, source, tier, tags, locale,
    format_type, prompt_text, age/occupation/budget/...（structured 字段可空）,
    pressure_profile（dict，缺省 0.5 全填）
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Union

import yaml

PathLike = Union[str, Path]


class PersonaParseError(RuntimeError):
    """人设文件解析失败。"""


def _default_pressure() -> dict[str, float]:
    return {
        "price_sensitivity": 0.5,
        "trust_threshold": 0.5,
        "patience": 0.5,
        "competitor_awareness": 0.5,
        "decision_power": 0.5,
        "emotion_volatility": 0.5,
        "need_urgency": 0.5,
        "skepticism": 0.5,
        "bargaining_aggressiveness": 0.5,
    }


def _normalize_panel_item(raw: dict[str, Any]) -> dict[str, Any]:
    """panel JSON 中的单条 persona → 统一字典。"""
    if "name" not in raw or "prompt" not in raw:
        raise PersonaParseError(
            "panel persona 缺少必需字段 name 或 prompt"
        )
    return {
        "external_id": str(raw.get("id", "")) or None,
        "name": str(raw["name"]).strip(),
        "source": raw.get("source") or "panel_import",
        "tier": raw.get("tier"),
        "tags": list(raw.get("tags") or []),
        "locale": raw.get("locale") or "zh-CN",
        "format_type": "prompt_based",
        "prompt_text": str(raw["prompt"]).strip(),
        "pressure_profile": _default_pressure(),
        "pressure_extracted": False,
    }


def _normalize_structured_yaml(raw: dict[str, Any]) -> dict[str, Any]:
    """structured YAML 单条 persona → 统一字典。"""
    if "name" not in raw:
        raise PersonaParseError("structured 人设缺少 name 字段")

    pressure = raw.get("pressure_profile") or _default_pressure()
    # 若 YAML 只给了部分字段，补齐到 9 维默认 0.5
    full_pressure = _default_pressure()
    full_pressure.update({k: v for k, v in pressure.items() if k in full_pressure})

    return {
        "external_id": str(raw.get("id", "")) or None,
        "name": str(raw["name"]).strip(),
        "source": raw.get("source") or "yaml_import",
        "tier": raw.get("tier"),
        "tags": list(raw.get("tags") or []),
        "locale": raw.get("locale") or "zh-CN",
        "format_type": "structured",
        "prompt_text": None,
        "age": raw.get("age"),
        "occupation": raw.get("occupation"),
        "budget": raw.get("budget"),
        "personality": raw.get("personality", ""),
        "pain_points": list(raw.get("pain_points") or []),
        "objection_style": raw.get("objection_style", ""),
        "purchase_goal": raw.get("purchase_goal", ""),
        "pressure_profile": full_pressure,
        "pressure_extracted": True,  # YAML 中的参数视为已确定
    }


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _normalize_markdown_prompt(text: str, fallback_name: str) -> dict[str, Any]:
    """.md / .txt 按 prompt_based 处理。

    若开头含 yaml frontmatter（--- ... ---），提取作为 metadata，
    正文作为 prompt_text；否则整段作为 prompt_text。
    """
    text = text.strip()
    meta: dict[str, Any] = {}
    body = text

    m = _FRONTMATTER_RE.match(text)
    if m:
        try:
            parsed = yaml.safe_load(m.group(1)) or {}
            if isinstance(parsed, dict):
                meta = parsed
                body = m.group(2).strip()
        except yaml.YAMLError:
            # frontmatter 解析失败就忽略，整段当 prompt
            pass

    if not body:
        raise PersonaParseError("人设正文为空，无法作为 prompt_text 使用")

    return {
        "external_id": str(meta.get("id", "")) or None,
        "name": str(meta.get("name") or fallback_name).strip(),
        "source": meta.get("source") or "markdown_import",
        "tier": meta.get("tier"),
        "tags": list(meta.get("tags") or []),
        "locale": meta.get("locale") or "zh-CN",
        "format_type": "prompt_based",
        "prompt_text": body,
        "pressure_profile": _default_pressure(),
        "pressure_extracted": False,
    }


def parse_persona_payload(raw: Any, *, source_hint: str = "json_upload") -> list[dict[str, Any]]:
    """对已读入的 JSON / dict 数据做批量/单条分派。

    - dict 含 `personas` 数组 → 按 panel 批量
    - dict 含 `name` + `prompt` → 单条 panel 格式
    - dict 含 `name` + `personality` 等 structured 字段 → 单条 structured
    - 其他 → 报错
    """
    if isinstance(raw, dict) and isinstance(raw.get("personas"), list):
        out: list[dict[str, Any]] = []
        for i, item in enumerate(raw["personas"]):
            if not isinstance(item, dict):
                raise PersonaParseError(f"personas[{i}] 不是 dict")
            out.append(_normalize_panel_item(item))
        if not out:
            raise PersonaParseError("personas 数组为空")
        return out

    if isinstance(raw, dict):
        if "prompt" in raw and "name" in raw:
            return [_normalize_panel_item(raw)]
        if "name" in raw:
            return [_normalize_structured_yaml(raw)]

    raise PersonaParseError(
        f"无法识别的 persona 数据格式（source={source_hint}），"
        "支持：panel JSON（含 personas 数组）/ 单 panel persona / structured YAML dict"
    )


def parse_persona_file(path: PathLike) -> list[dict[str, Any]]:
    """根据文件后缀分派解析逻辑，返回标准化后的 persona 字典列表。"""
    p = Path(path)
    if not p.exists():
        raise PersonaParseError(f"文件不存在: {p}")
    if not p.is_file():
        raise PersonaParseError(f"路径不是文件: {p}")

    suffix = p.suffix.lower()
    try:
        # utf-8-sig 自动剥离 Windows / Excel / Notepad 产生的 BOM，
        # 同时仍兼容标准 UTF-8。
        text = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PersonaParseError(f"文件编码非 UTF-8: {p} ({exc})") from exc

    if suffix == ".json":
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PersonaParseError(f"JSON 解析失败 {p}: {exc}") from exc
        return parse_persona_payload(raw, source_hint=str(p))

    if suffix in {".yaml", ".yml"}:
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise PersonaParseError(f"YAML 解析失败 {p}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PersonaParseError(f"YAML 根节点必须是 dict: {p}")
        return [_normalize_structured_yaml(raw)]

    if suffix in {".md", ".txt"}:
        return [_normalize_markdown_prompt(text, fallback_name=p.stem)]

    raise PersonaParseError(
        f"暂不支持的文件格式 {suffix}（{p}）。支持: .json/.yaml/.yml/.md/.txt"
    )


def iter_panel_personas(personas: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """工具函数：把 panel personas 列表里每条转成统一格式。"""
    return [_normalize_panel_item(p) for p in personas]
