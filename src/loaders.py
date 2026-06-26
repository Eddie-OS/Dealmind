"""输入文件加载与校验。

- load_text_file：通用 UTF-8 文本读取
- load_persona_yaml：读取 personas/*.yaml 并解析为 PersonaProfile
- validate_product_text：检查产品资料非空、长度合理
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml
from pydantic import ValidationError

from src.schema import PersonaProfile


PathLike = Union[str, Path]


class InputValidationError(RuntimeError):
    """输入文件校验失败时抛出，区别于 LLM 调用失败。"""


def _to_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def load_text_file(path: PathLike) -> str:
    """加载 UTF-8 文本文件。文件不存在或读取失败时抛出可读错误。"""
    p = _to_path(path)
    if not p.exists():
        raise InputValidationError(
            f"文件不存在: {p.resolve()}。请检查路径或先创建该文件。"
        )
    if not p.is_file():
        raise InputValidationError(f"路径不是文件: {p.resolve()}")
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InputValidationError(
            f"无法以 UTF-8 解码文件 {p.resolve()}: {exc}。请确认文件编码为 UTF-8。"
        ) from exc


def validate_product_text(text: str, min_chars: int = 200) -> None:
    """产品资料基础校验：非空 + 字数 ≥ min_chars。"""
    if not text or not text.strip():
        raise InputValidationError("产品资料为空，请检查 product.md 是否被正确写入。")
    if len(text) < min_chars:
        raise InputValidationError(
            f"产品资料过短（{len(text)} 字符 < {min_chars}）。"
            "至少应包含产品定位、核心卖点、价格、售后等基础信息。"
        )


def load_persona_yaml(path: PathLike) -> PersonaProfile:
    """读取 YAML 人设并解析为 PersonaProfile。

    校验失败时给出友好错误信息，列出缺失或非法字段。
    """
    p = _to_path(path)
    if not p.exists():
        raise InputValidationError(
            f"人设 YAML 不存在: {p.resolve()}。可参考 personas/ 下示例创建。"
        )
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise InputValidationError(
            f"YAML 解析失败 ({p.resolve()}): {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise InputValidationError(
            f"人设 YAML 根节点必须是 mapping/dict，当前类型: {type(raw).__name__}"
        )

    try:
        return PersonaProfile.model_validate(raw)
    except ValidationError as exc:
        missing = []
        invalid = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", []))
            etype = err.get("type", "")
            if etype.startswith("missing"):
                missing.append(loc)
            else:
                invalid.append(f"{loc}: {err.get('msg', '')}")
        details = []
        if missing:
            details.append("缺失字段: " + ", ".join(missing))
        if invalid:
            details.append("非法字段: " + "; ".join(invalid))
        raise InputValidationError(
            f"人设 YAML 校验失败 ({p.resolve()}):\n  - " + "\n  - ".join(details)
        ) from exc
