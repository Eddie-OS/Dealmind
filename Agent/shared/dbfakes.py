"""用文件后端顶替 SQLite / Chroma，让 vendored 引擎代码一行不改地跑起来。

做法：在 import 任何 vendored 模块之前，往 sys.modules 里塞进三个同名假模块

    src.storage.db            -> 本文件里的文件后端实现
    src.rag.kb_store          -> KeywordKnowledgeStore 包装
    src.research.market_research -> 只保留渲染函数

于是 vendored agents.py 里那些 `from src.storage import db` / `KBStore(...)`
会原样命中假模块，走的仍是它自己的原始代码路径（含 handbook 渲染、
playbook_v1 分支、品牌铁律注入、RAG 命中格式化）。

为什么不直接 monkeypatch agents 里的函数：
    那需要把 _build_handbook_block_with_meta 的近百行渲染逻辑抄一遍。
    抄一遍就意味着上游改了渲染格式而这边不知道。顶替数据源而不是顶替
    逻辑，是这里唯一不制造第二份真相的做法。

只实现 vendored 代码真正调用到的那几个函数，其余一律不提供 —— 调用方
全部包在 try/except 里，缺失即优雅降级，这正是我们要的行为。
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import yaml

AGENT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = AGENT_ROOT / "config"
KNOWLEDGE_DIR = AGENT_ROOT / "knowledge"

_FALLBACK_IDENTITY_BLOCK = (
    "- **你的身份**：门店销售，只卖本场产品手册里出现过的型号。\n"
    "- **禁止脑补型号**：手册里没出现过的型号一律不主动提。\n"
    "- **禁止宣称店内有竞品样机**：客户要对比时，只讲差异点，不谎称有货。"
)


# ── 运行期可变状态：由 orchestrator / 01_handbook_ingest 写入 ──────────

_active_handbook: Optional[dict[str, Any]] = None


def set_active_handbook(handbook: Optional[dict[str, Any]]) -> None:
    """把本次 run 解析好的产品手册挂上，之后所有会话都读它。

    handbook 形状与上游 product_handbooks 行一致：
        {"id", "name", "version_no", "status", "structure_json"}
    """
    global _active_handbook
    _active_handbook = handbook


def get_active_handbook() -> Optional[dict[str, Any]]:
    return _active_handbook


# ── 配置读取 ──────────────────────────────────────────────────────────


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _identity_block() -> str:
    path = CONFIG_DIR / "brand_profile.md"
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return _FALLBACK_IDENTITY_BLOCK


# ── 假 src.storage.db ─────────────────────────────────────────────────


class _NoDBConnection:
    """占位连接。vendored 代码只把它当句柄传递，从不真的执行 SQL。"""

    def close(self) -> None:
        return None

    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(
            "Agent 运行在无数据库模式；此处不应发生真实 SQL。"
            "若触发说明用到了 dbfakes 未覆盖的 DB 函数，请补实现。"
        )


def _build_storage_db_module() -> types.ModuleType:
    mod = types.ModuleType("src.storage.db")

    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def get_connection(db_path: Any = None) -> _NoDBConnection:
        del db_path
        return _NoDBConnection()

    @contextmanager
    def connection_scope(db_path: Any = None) -> Iterator[_NoDBConnection]:
        del db_path
        yield _NoDBConnection()

    # —— 产品手册 ——
    def resolve_default_handbook_id(conn: Any) -> Optional[int]:
        del conn
        if _active_handbook is None:
            return None
        return int(_active_handbook.get("id") or 1)

    def get_handbook(conn: Any, handbook_id: int) -> Optional[dict[str, Any]]:
        del conn, handbook_id
        return _active_handbook

    # —— 品牌铁律 ——
    def get_default_brand_profile(conn: Any) -> dict[str, Any]:
        del conn
        return {"identity_block": _identity_block(), "is_default": True}

    # —— 市场事实表：Agent 侧不做联网预研，永远未命中 ——
    def get_market_facts(
        conn: Any, *, handbook_id: Optional[int] = None, country_code: str = ""
    ) -> None:
        del conn, handbook_id, country_code
        return None

    # —— 销冠 profile（在线编辑覆盖）——
    def get_agent_profile(conn: Any, name: str) -> Optional[dict[str, Any]]:
        del conn
        cfg = _read_yaml(CONFIG_DIR / "sales_profile.yaml")
        if name != "sales":
            return None
        system_prompt = ""
        prompt_file = cfg.get("system_prompt_file")
        if prompt_file:
            p = Path(prompt_file)
            if not p.is_absolute():
                p = AGENT_ROOT / p
            if p.is_file():
                system_prompt = p.read_text(encoding="utf-8")
        return {
            "name": "sales",
            # 空字符串 → vendored load_prompt 回落到 vendor/prompts/sales_prompt.md
            "system_prompt": system_prompt,
            "model_override": cfg.get("model_override") or {},
        }

    # —— 工具技能：默认全关，Agent 侧不联网、不查库 ——
    def get_agent_skills_config(conn: Any) -> dict[str, Any]:
        del conn
        cfg = _read_yaml(CONFIG_DIR / "sales_profile.yaml").get("skills") or {}
        return {
            "enabled_tools": list(cfg.get("enabled_tools") or []),
            "max_tool_loops": int(cfg.get("max_tool_loops") or 0),
            "tool_top_k_default": int(cfg.get("tool_top_k_default") or 3),
        }

    # —— LLM provider：一律返回 None，逼 vendored llm.py 回落到 .env ——
    def get_provider_by_id(conn: Any, provider_id: int) -> None:
        del conn, provider_id
        return None

    def get_default_provider(conn: Any) -> None:
        del conn
        return None

    mod._now_iso = _now_iso
    mod.get_connection = get_connection
    mod.connection_scope = connection_scope
    mod.resolve_default_handbook_id = resolve_default_handbook_id
    mod.get_handbook = get_handbook
    mod.get_default_brand_profile = get_default_brand_profile
    mod.get_market_facts = get_market_facts
    mod.get_agent_profile = get_agent_profile
    mod.get_agent_skills_config = get_agent_skills_config
    mod.get_provider_by_id = get_provider_by_id
    mod.get_default_provider = get_default_provider
    mod._DEFAULT_HUAWEI_IDENTITY_BLOCK = _identity_block()
    mod.__doc__ = "文件后端的 src.storage.db 顶替品（Agent/shared/dbfakes.py 注入）"
    return mod


# ── 假 src.rag.kb_store ───────────────────────────────────────────────


def _build_kb_store_module() -> types.ModuleType:
    from shared.knowledge_store import KeywordKnowledgeStore

    mod = types.ModuleType("src.rag.kb_store")
    _shared_store = KeywordKnowledgeStore(KNOWLEDGE_DIR)

    class KBStore:
        """签名对齐上游 KBStore(kb_id, kb_type)，实际读 Agent/knowledge/。"""

        def __init__(self, kb_id: int, kb_type: str = "product") -> None:
            self.kb_id = kb_id
            self.kb_type = kb_type
            self._store = _shared_store

        def query(
            self, query: str, top_k: int = 3, scope_kb_only: bool = True
        ) -> list[dict[str, Any]]:
            return self._store.query(query, top_k=top_k, scope_kb_only=scope_kb_only)

    mod.KBStore = KBStore
    mod.__doc__ = "关键词检索顶替 Chroma（Agent/shared/dbfakes.py 注入）"
    return mod


# ── 假 src.research.market_research ───────────────────────────────────


def _build_market_research_module() -> types.ModuleType:
    mod = types.ModuleType("src.research.market_research")

    def render_market_facts_block(row: Optional[dict[str, Any]]) -> str:
        """与上游同名函数的"无数据"分支逐字一致，保证 prompt 不产生差异。"""
        del row
        return (
            "**市场事实表：未研究**\n\n"
            "本场未预研当地市场实价。涉及当地价格 / 竞品报价时，"
            "按上方信息优先级处理；确无来源时才当场查官网（整场最多 1 次）。"
        )

    mod.render_market_facts_block = render_market_facts_block
    mod.__doc__ = "市场预研在 Agent 侧关闭（Agent/shared/dbfakes.py 注入）"
    return mod


# ── 安装 ──────────────────────────────────────────────────────────────

_installed = False


def install() -> None:
    """把假模块注册进 sys.modules。必须在 import 任何 vendored 模块之前调用。"""
    global _installed
    if _installed:
        return

    storage_pkg = types.ModuleType("src.storage")
    storage_pkg.__path__ = []  # 声明为包，允许 src.storage.db 子模块
    db_mod = _build_storage_db_module()
    storage_pkg.db = db_mod

    research_pkg = types.ModuleType("src.research")
    research_pkg.__path__ = []
    mr_mod = _build_market_research_module()
    research_pkg.market_research = mr_mod

    sys.modules["src.storage"] = storage_pkg
    sys.modules["src.storage.db"] = db_mod
    sys.modules["src.rag.kb_store"] = _build_kb_store_module()
    sys.modules["src.research"] = research_pkg
    sys.modules["src.research.market_research"] = mr_mod

    _installed = True
