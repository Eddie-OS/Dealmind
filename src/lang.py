"""对话语言注入工具（Stage 15c）。

所有 Agent（persona / sales / judge / memory / coach）在拼 system_prompt
时统一调用 :func:`lang_instruction` 追加一段"请严格用 {语言} 进行回应"。

设计原则：
- 不改 Markdown prompt 模板（兼容旧版本）；
- 不要求 user_prompt 重写；
- **所有受支持语言都返回非空、强约束的指令**（包括 zh-CN）；
  原因：persona 的人设 prompt 里常有强烈语言倾向（例如马来西亚学生人设
  会让模型默认讲 Bahasa Melayu）；只对非默认语言加约束会让 zh-CN 场景
  反而被人设带跑——这是 Stage 15c 第一版的真实 bug；
- 不认识的 code 一律回退 zh-CN（不会抛错）。
"""

from __future__ import annotations

from typing import Optional

# 第一版支持的 5 种"覆盖面最广"的语言（按全球使用人数排序）。
# 若需扩展，仅在此处加 entry 即可；前后端的下拉也需同步。
# 第二项为该语言"母语自称"，用于在指令里给模型一个 in-language anchor。
LANGUAGE_NAMES: dict[str, tuple[str, str]] = {
    "zh-CN": ("普通话（简体中文）", "中文"),
    "en-US": ("English (US)",       "English"),
    "es-ES": ("Español",            "español"),
    "ar-SA": ("العربية",            "اللغة العربية"),
    "id-ID": ("Bahasa Indonesia",   "Bahasa Indonesia"),
}

DEFAULT_LANGUAGE = "zh-CN"

# 主语言子标签 → 代表性完整码（让裸 "en" / "es" / "zh" 等也能命中，
# 而不是静默回退到中文 —— 这曾导致 language="en" 的批次跑出中文对话）。
_PRIMARY_SUBTAG: dict[str, str] = {
    "zh": "zh-CN",
    "en": "en-US",
    "es": "es-ES",
    "ar": "ar-SA",
    "id": "id-ID",
}


def normalize(code: Optional[str]) -> str:
    """把 ``code`` 规范化为受支持语言；不识别一律回退 zh-CN。

    匹配顺序：精确码（大小写不敏感）→ 主语言子标签（如 "en" / "en-GB" → en-US）
    → 回退 DEFAULT_LANGUAGE。
    """
    if not code:
        return DEFAULT_LANGUAGE
    raw = code.strip()
    if not raw:
        return DEFAULT_LANGUAGE
    # 1) 精确匹配（忽略大小写：en-us → en-US）
    lower = raw.lower()
    for key in LANGUAGE_NAMES:
        if key.lower() == lower:
            return key
    # 2) 主语言子标签匹配（en / en_GB / en-GB → en-US）
    primary = lower.replace("_", "-").split("-", 1)[0]
    return _PRIMARY_SUBTAG.get(primary, DEFAULT_LANGUAGE)


def lang_instruction(code: Optional[str], *, role: str = "agent") -> str:
    """生成追加到 system_prompt 末尾的语言指令字符串。

    无论是否默认语言（zh-CN）都会返回**显式约束**，避免被人设 prompt
    的隐含语言倾向带跑。JSON schema 的 key / enum 保持英文不变。

    Args:
        code: BCP-47 子集，五种之一。
        role: 仅用于让指令读起来更自然（"persona" / "sales" / "judge" ...）。
    """
    norm = normalize(code)
    display, native = LANGUAGE_NAMES[norm]

    return (
        f"\n\n## ⚠️ 对话语言强约束（Conversation language constraint）\n"
        f"本场对话的语言被锁定为：**{display}** ({norm})。\n"
        f"- 你输出的所有自然语言文本字段（如 `content` / `reason` / `feedback` "
        f"等的值，以及任何叙述）**必须**全部使用 {native}。\n"
        f"- 即使客户人设的画像或知识库 / 产品资料是用别的语言写的，你也要"
        f"把它**翻译**成 {native} 后再呈现；绝不要混用第二种语言。\n"
        f"- JSON 的 key 和 enum 值（如 intent 词表）**保持英文/原值不变**，"
        f"只约束自然语内容。\n"
    )
