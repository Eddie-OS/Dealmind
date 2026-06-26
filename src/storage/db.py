"""SQLite 连接与 providers CRUD。

约定：
- 数据库文件：`data/conversations.db`（项目根 / data 下，自动建目录）
- 连接默认 row_factory=sqlite3.Row，外键强制 ON
- 时间戳字段统一存 ISO8601 字符串（utcnow().isoformat()）
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from src.config import PROJECT_ROOT
from src.storage.models import ALL_SCHEMAS, SCHEMA_INDEXES


logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "conversations.db"


def _now_iso() -> str:
    """UTC ISO8601，秒级精度足够审计。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """建立 SQLite 连接。

    每次调用返回新连接（SQLite 在多线程下连接不能跨线程复用）。
    上层若需要事务，请用 with conn 或自行 commit。
    """
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：每个连接只在单请求内短暂使用，但 FastAPI
    # 的同步端点 + Depends(get_db) 模式可能让 dep 与 endpoint 分布在 anyio
    # 不同 worker 线程，触发 cross-thread error。安全前提：连接非全局共享。
    conn = sqlite3.connect(
        str(path), detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def connection_scope(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """便捷上下文：自动提交 / 异常回滚 / 关闭。"""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_legacy_sales_cases(conn: sqlite3.Connection) -> None:
    """Stage 11：旧 sales_cases 用 source_type / title / content 等字段，
    新 schema 完全不同。仅在表存在 + 行数为 0 + 缺新列（如 'scene'）时
    DROP 重建，保证零数据丢失风险。

    若表存在但已有数据，仅记录警告不做破坏性变更（让上层人工处理）。
    """
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sales_cases'"
    ).fetchone()
    if not exists:
        return
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sales_cases)").fetchall()}
    if "scene" in cols:  # 已经是新 schema
        return
    n = conn.execute("SELECT COUNT(*) AS n FROM sales_cases").fetchone()["n"]
    if n > 0:
        import logging
        logging.getLogger(__name__).warning(
            "legacy sales_cases table has %d rows; refusing auto-drop. "
            "请手动备份后清空：DROP TABLE sales_cases;", n,
        )
        return
    conn.execute("DROP TABLE sales_cases")
    conn.commit()


def _migrate_personas_avatar_key(conn: sqlite3.Connection) -> None:
    """Stage 15a：personas 表如缺 avatar_key 列就 ALTER 加上，并按 id 顺序
    回填 p01..p44 头像（仅对已存在且 avatar_key IS NULL 的行）。

    幂等：列已存在则跳过 ALTER；已有 avatar_key 的行不覆盖。
    """
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='personas'"
    ).fetchone()
    if not exists:
        return
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(personas)").fetchall()}
    if "avatar_key" not in cols:
        conn.execute("ALTER TABLE personas ADD COLUMN avatar_key TEXT")
        conn.commit()
    # 回填：取 avatar_key IS NULL 的行，按 id 升序逐个分配下一个未占用的 p?? 槽位
    used = {
        r["avatar_key"]
        for r in conn.execute(
            "SELECT DISTINCT avatar_key FROM personas WHERE avatar_key IS NOT NULL"
        ).fetchall()
    }
    rows = conn.execute(
        "SELECT id FROM personas WHERE avatar_key IS NULL ORDER BY id ASC"
    ).fetchall()
    if not rows:
        return
    next_slot = 1
    with conn:
        for r in rows:
            while next_slot <= 44 and f"p{next_slot:02d}" in used:
                next_slot += 1
            if next_slot > 44:
                # 超过预设头像数 → 用 id 取模兜底（保证总有一张可用头像）
                key = f"p{((int(r['id']) - 1) % 44) + 1:02d}"
            else:
                key = f"p{next_slot:02d}"
                used.add(key)
                next_slot += 1
            conn.execute(
                "UPDATE personas SET avatar_key = ? WHERE id = ?", (key, int(r["id"]))
            )


def _migrate_handbook_v2_fields(conn: sqlite3.Connection) -> None:
    """Handbook Analysis v2：

    1) sessions / batch_jobs 缺 handbook_id 时 ALTER ADD COLUMN（幂等）
    2) analysis_jobs 表 v1 设计 batch_id NOT NULL + handbook_id NOT NULL；
       v2 改为 (batch_id OR session_id) 二选一 + handbook_id 可空。
       由于本表是 Sprint 1 才上线、目前无数据，安全 DROP 让 init_schema 重建。

    幂等：列已存在 / 表已是新 schema 时直接 return。
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # ---- 1) sessions / batch_jobs ADD COLUMN handbook_id ----
    for tbl in ("sessions", "batch_jobs"):
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
        ).fetchone()
        if not exists:
            continue
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        if "handbook_id" not in cols:
            # SQLite ADD COLUMN 不支持 INLINE REFERENCES（FK），先 ADD 普通列；
            # 真实 FK 由 init_schema 的新建路径保证（旧库手动加列不带 FK，
            # 仅靠应用层校验，符合现有 product_kb_id/enterprise_kb_id 老库逻辑）
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN handbook_id INTEGER")
            conn.commit()
            _log.info("[migrate] %s.handbook_id ADD COLUMN done", tbl)

    # ---- 2) analysis_jobs v1 → v2 ----
    aj_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_jobs'"
    ).fetchone()
    if not aj_exists:
        return
    aj_info = list(conn.execute("PRAGMA table_info(analysis_jobs)").fetchall())
    cols = {r["name"]: r for r in aj_info}
    is_v2 = "session_id" in cols and cols.get("handbook_id") and cols["handbook_id"]["notnull"] == 0
    if is_v2:
        return
    n = conn.execute("SELECT COUNT(*) AS n FROM analysis_jobs").fetchone()["n"]
    if n > 0:
        _log.warning(
            "analysis_jobs has %d rows on v1 schema; "
            "refusing auto-migrate. 请手动备份后清空表。", n,
        )
        return
    conn.execute("DROP TABLE analysis_jobs")
    conn.commit()
    _log.info("[migrate] analysis_jobs v1 → v2 (DROP + recreate via init_schema)")


def _migrate_personas_market_fields(conn: sqlite3.Connection) -> None:
    """v0.2.1 真实性 / 地区一致性补丁：
    给 personas 表加 country_code / country_name / currency / market_domains_json 四列。

    幂等：列已存在则跳过 ALTER。**不在这里跑推断回填**——
    推断脚本 ``scripts/patch_persona_market.py`` 单独显式调用，让用户可以看到推断结果。
    """
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='personas'"
    ).fetchone()
    if not exists:
        return
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(personas)").fetchall()}
    added: list[str] = []
    if "country_code" not in cols:
        conn.execute("ALTER TABLE personas ADD COLUMN country_code TEXT")
        added.append("country_code")
    if "country_name" not in cols:
        conn.execute("ALTER TABLE personas ADD COLUMN country_name TEXT")
        added.append("country_name")
    if "currency" not in cols:
        conn.execute("ALTER TABLE personas ADD COLUMN currency TEXT")
        added.append("currency")
    if "market_domains_json" not in cols:
        conn.execute("ALTER TABLE personas ADD COLUMN market_domains_json TEXT")
        added.append("market_domains_json")
    if added:
        conn.commit()
        # storage/db.py 全模块未启用 logging，沿用现有 print 风格
        print(f"[migration] personas 表已加列：{', '.join(added)}")


def init_schema(conn: sqlite3.Connection) -> dict[str, int]:
    """创建全部表 + 索引（幂等）。

    Returns:
        各表当前行数（便于上层判断是否首启）。
    """
    _migrate_legacy_sales_cases(conn)  # Stage 11
    _migrate_handbook_v2_fields(conn)  # Handbook Analysis v2：handbook_id 列 + analysis_jobs 升版

    cur = conn.cursor()
    for _name, sql in ALL_SCHEMAS:
        cur.execute(sql)
    for idx_sql in SCHEMA_INDEXES:
        cur.execute(idx_sql)
    conn.commit()

    _migrate_personas_avatar_key(conn)  # Stage 15a Phase B-3
    _migrate_personas_market_fields(conn)  # v0.2.1 真实性补丁
    seed_default_brand_profile(conn)  # ③ 手册解耦：种子华为默认品牌人格

    counts: dict[str, int] = {}
    for name, _ in ALL_SCHEMAS:
        row = cur.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()
        counts[name] = row["n"]
    return counts


def _row_to_provider(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → 普通 dict（含 extra_config 解码、bool 还原）。"""
    if row is None:
        return {}
    d = dict(row)
    extra = d.get("extra_config_json")
    d["extra_config"] = json.loads(extra) if extra else {}
    d["is_active"] = bool(d.get("is_active"))
    d["is_default"] = bool(d.get("is_default"))
    return d


def list_providers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """全部 providers，按 is_default DESC, id ASC 排序。"""
    rows = conn.execute(
        "SELECT * FROM llm_providers ORDER BY is_default DESC, id ASC"
    ).fetchall()
    return [_row_to_provider(r) for r in rows]


def get_provider_by_id(
    conn: sqlite3.Connection, provider_id: int
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM llm_providers WHERE id = ?", (provider_id,)
    ).fetchone()
    return _row_to_provider(row) if row else None


def get_default_provider(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
    """取 is_default=1 且 is_active=1 的 provider，否则返回 None。"""
    row = conn.execute(
        "SELECT * FROM llm_providers "
        "WHERE is_default = 1 AND is_active = 1 "
        "LIMIT 1"
    ).fetchone()
    return _row_to_provider(row) if row else None


def create_provider(
    conn: sqlite3.Connection,
    *,
    name: str,
    provider_type: str,
    base_url: str,
    api_key: str,
    model_name: str,
    temperature: float = 0.7,
    max_retries: int = 2,
    is_active: bool = True,
    is_default: bool = False,
    extra_config: Optional[dict[str, Any]] = None,
) -> int:
    """新增 provider，返回主键 id。

    若 is_default=True，会先把其他 provider 的 is_default 清零，
    保证 (is_default=1) 全表唯一。
    """
    now = _now_iso()
    extra_json = json.dumps(extra_config, ensure_ascii=False) if extra_config else None

    with conn:
        if is_default:
            conn.execute("UPDATE llm_providers SET is_default = 0 WHERE is_default = 1")
        cur = conn.execute(
            """
            INSERT INTO llm_providers (
                name, provider_type, base_url, api_key, model_name,
                temperature, max_retries, is_active, is_default,
                extra_config_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                provider_type,
                base_url,
                api_key,
                model_name,
                temperature,
                max_retries,
                1 if is_active else 0,
                1 if is_default else 0,
                extra_json,
                now,
                now,
            ),
        )
    return int(cur.lastrowid)


_UPDATABLE_FIELDS = {
    "name",
    "provider_type",
    "base_url",
    "api_key",
    "model_name",
    "temperature",
    "max_retries",
    "is_active",
}


def update_provider(
    conn: sqlite3.Connection,
    provider_id: int,
    **fields: Any,
) -> bool:
    """按字段名更新；忽略未知字段。

    is_default 切换请走 set_default_provider，确保互斥。
    Returns: 是否实际更新。
    """
    extra_config = fields.pop("extra_config", None)
    valid = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
    if not valid and extra_config is None:
        return False

    set_parts = []
    params: list[Any] = []
    for k, v in valid.items():
        set_parts.append(f"{k} = ?")
        params.append(int(v) if isinstance(v, bool) else v)
    if extra_config is not None:
        set_parts.append("extra_config_json = ?")
        params.append(json.dumps(extra_config, ensure_ascii=False))
    set_parts.append("updated_at = ?")
    params.append(_now_iso())
    params.append(provider_id)

    with conn:
        cur = conn.execute(
            f"UPDATE llm_providers SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
    return cur.rowcount > 0


def set_default_provider(conn: sqlite3.Connection, provider_id: int) -> bool:
    """把指定 provider 设为唯一 default。

    Returns: 是否找到并设置成功。
    """
    row = conn.execute(
        "SELECT id FROM llm_providers WHERE id = ?", (provider_id,)
    ).fetchone()
    if row is None:
        return False
    now = _now_iso()
    with conn:
        conn.execute("UPDATE llm_providers SET is_default = 0 WHERE is_default = 1")
        conn.execute(
            "UPDATE llm_providers SET is_default = 1, updated_at = ? WHERE id = ?",
            (now, provider_id),
        )
    return True


def delete_provider(conn: sqlite3.Connection, provider_id: int) -> bool:
    """删除 provider。Returns: 是否实际删除一行。"""
    with conn:
        cur = conn.execute("DELETE FROM llm_providers WHERE id = ?", (provider_id,))
    return cur.rowcount > 0


# ============================================================
# personas CRUD（Stage 3）
# ============================================================

def _row_to_persona(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → dict，JSON 列解码 + 布尔还原。"""
    if row is None:
        return {}
    d = dict(row)
    for col in ("profile_json", "pressure_json", "tags_json", "original_data_json"):
        raw = d.pop(col, None)
        key = col.replace("_json", "")
        try:
            d[key] = json.loads(raw) if raw else (
                [] if key == "tags" else (None if key in ("original_data",) else {})
            )
        except json.JSONDecodeError:
            d[key] = [] if key == "tags" else (None if key == "original_data" else {})
    d["pressure_extracted"] = bool(d.get("pressure_extracted"))
    # Stage 15a：旧库可能没 avatar_key 列，这里安全兜底
    d.setdefault("avatar_key", None)

    # v0.2.1：market_domains_json → list[str]；其余三个直接透传（旧库可能没列）
    md_raw = d.pop("market_domains_json", None)
    try:
        d["market_domains"] = json.loads(md_raw) if md_raw else []
    except json.JSONDecodeError:
        d["market_domains"] = []
    d.setdefault("country_code", None)
    d.setdefault("country_name", None)
    d.setdefault("currency", None)
    return d


def list_personas(
    conn: sqlite3.Connection,
    *,
    format_type: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """列出全部 personas，支持按 format_type/tag/关键字筛选。

    tag 用 LIKE 在 tags_json 上做粗略命中（生产规模可换 FTS5，MVP 够用）。
    search 在 name / source / prompt_text 上做 LIKE。
    """
    where: list[str] = []
    params: list[Any] = []
    if format_type:
        where.append("format_type = ?")
        params.append(format_type)
    if tag:
        where.append("tags_json LIKE ?")
        params.append(f'%"{tag}"%')
    if search:
        where.append("(name LIKE ? OR source LIKE ? OR prompt_text LIKE ?)")
        q = f"%{search}%"
        params.extend([q, q, q])
    sql = "SELECT * FROM personas"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_persona(r) for r in rows]


def get_persona_by_id(
    conn: sqlite3.Connection, persona_id: int
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM personas WHERE id = ?", (persona_id,)
    ).fetchone()
    return _row_to_persona(row) if row else None


def count_personas(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM personas").fetchone()
    return int(row["n"]) if row else 0


def create_persona(
    conn: sqlite3.Connection,
    *,
    name: str,
    format_type: str,
    prompt_text: Optional[str] = None,
    profile: Optional[dict[str, Any]] = None,
    pressure: Optional[dict[str, float]] = None,
    source: Optional[str] = None,
    tags: Optional[list[str]] = None,
    locale: str = "zh-CN",
    original_data: Optional[dict[str, Any]] = None,
    pressure_extracted: bool = False,
    avatar_key: Optional[str] = None,
) -> int:
    """新增 persona，返回主键 id。

    ``avatar_key``：notion 风格头像 key（如 ``"p07"``）。留空则在写入后
    根据 id 取模兜底分配（``p((id-1)%44 + 1)``），保证前端总能渲染头像。
    """
    if format_type not in ("structured", "prompt_based"):
        raise ValueError(f"非法 format_type: {format_type}")
    now = _now_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO personas (
                name, format_type, profile_json, pressure_json, prompt_text,
                source, tags_json, locale, original_data_json,
                pressure_extracted, avatar_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                format_type,
                json.dumps(profile, ensure_ascii=False) if profile else None,
                json.dumps(pressure, ensure_ascii=False) if pressure else None,
                prompt_text,
                source,
                json.dumps(tags or [], ensure_ascii=False),
                locale,
                json.dumps(original_data, ensure_ascii=False) if original_data else None,
                1 if pressure_extracted else 0,
                avatar_key,
                now,
                now,
            ),
        )
        new_id = int(cur.lastrowid)
        # 没指定 avatar_key → 用 id 取模分配一个稳定的预设头像
        if not avatar_key:
            fallback = f"p{((new_id - 1) % 44) + 1:02d}"
            conn.execute(
                "UPDATE personas SET avatar_key = ? WHERE id = ? AND avatar_key IS NULL",
                (fallback, new_id),
            )
    return new_id


def bulk_create_personas(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
) -> list[int]:
    """批量插入 personas（同一事务）。返回插入后的 id 列表。

    items 字段对齐 parser 输出：name/format_type/prompt_text/source/tags/
    locale/pressure_profile/pressure_extracted + 可选 structured 字段。
    """
    ids: list[int] = []
    now = _now_iso()
    with conn:
        for it in items:
            fmt = it.get("format_type", "prompt_based")
            if fmt not in ("structured", "prompt_based"):
                fmt = "prompt_based"
            # structured 字段（age/occupation/...）打包进 profile_json
            profile = {
                k: it.get(k)
                for k in (
                    "age", "occupation", "budget", "personality",
                    "pain_points", "objection_style", "purchase_goal",
                )
                if it.get(k) is not None
            }
            cur = conn.execute(
                """
                INSERT INTO personas (
                    name, format_type, profile_json, pressure_json, prompt_text,
                    source, tags_json, locale, original_data_json,
                    pressure_extracted, avatar_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it["name"],
                    fmt,
                    json.dumps(profile, ensure_ascii=False) if profile else None,
                    json.dumps(it.get("pressure_profile") or {}, ensure_ascii=False),
                    it.get("prompt_text"),
                    it.get("source"),
                    json.dumps(it.get("tags") or [], ensure_ascii=False),
                    it.get("locale") or "zh-CN",
                    json.dumps({"external_id": it.get("external_id")}, ensure_ascii=False)
                    if it.get("external_id") else None,
                    1 if it.get("pressure_extracted") else 0,
                    it.get("avatar_key"),
                    now,
                    now,
                ),
            )
            new_id = int(cur.lastrowid)
            ids.append(new_id)
            if not it.get("avatar_key"):
                fallback = f"p{((new_id - 1) % 44) + 1:02d}"
                conn.execute(
                    "UPDATE personas SET avatar_key = ? WHERE id = ? AND avatar_key IS NULL",
                    (fallback, new_id),
                )
    return ids


_PERSONA_DIRECT_FIELDS = {
    "name", "format_type", "prompt_text", "source", "locale", "avatar_key",
    # v0.2.1 真实性补丁：市场地区字段（market_domains 单独转 JSON，下方有特殊处理）
    "country_code", "country_name", "currency",
}


def update_persona(
    conn: sqlite3.Connection,
    persona_id: int,
    **fields: Any,
) -> bool:
    """部分字段更新。

    支持的 fields：
    - name / format_type / prompt_text / source / locale（直接列）
    - profile（dict → profile_json）
    - pressure（dict → pressure_json）
    - tags（list → tags_json）
    - pressure_extracted（bool → INTEGER）
    """
    direct = {k: v for k, v in fields.items() if k in _PERSONA_DIRECT_FIELDS}
    profile = fields.get("profile")
    pressure = fields.get("pressure")
    tags = fields.get("tags")
    pressure_extracted = fields.get("pressure_extracted")
    # v0.2.1：market_domains 单独走 JSON 列
    market_domains = fields.get("market_domains")

    set_parts: list[str] = []
    params: list[Any] = []
    for k, v in direct.items():
        set_parts.append(f"{k} = ?")
        params.append(v)
    if profile is not None:
        set_parts.append("profile_json = ?")
        params.append(json.dumps(profile, ensure_ascii=False))
    if pressure is not None:
        set_parts.append("pressure_json = ?")
        params.append(json.dumps(pressure, ensure_ascii=False))
    if tags is not None:
        set_parts.append("tags_json = ?")
        params.append(json.dumps(tags, ensure_ascii=False))
    if pressure_extracted is not None:
        set_parts.append("pressure_extracted = ?")
        params.append(1 if pressure_extracted else 0)
    if market_domains is not None:
        set_parts.append("market_domains_json = ?")
        params.append(json.dumps(list(market_domains), ensure_ascii=False))

    if not set_parts:
        return False

    set_parts.append("updated_at = ?")
    params.append(_now_iso())
    params.append(persona_id)

    with conn:
        cur = conn.execute(
            f"UPDATE personas SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
    return cur.rowcount > 0


def delete_persona(conn: sqlite3.Connection, persona_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
    return cur.rowcount > 0


# ============================================================
# knowledge_bases / knowledge_files CRUD（Stage 4）
# ============================================================


def list_kbs(
    conn: sqlite3.Connection,
    *,
    kb_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """列出所有 KB，可按 kb_type 过滤。"""
    if kb_type:
        rows = conn.execute(
            "SELECT * FROM knowledge_bases WHERE kb_type = ? ORDER BY id ASC",
            (kb_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM knowledge_bases ORDER BY id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_kb_by_id(conn: sqlite3.Connection, kb_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)
    ).fetchone()
    return dict(row) if row else None


def get_kb_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM knowledge_bases WHERE name = ?", (name,)
    ).fetchone()
    return dict(row) if row else None


def count_kbs(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM knowledge_bases").fetchone()
    return int(row["n"]) if row else 0


def create_kb(
    conn: sqlite3.Connection,
    *,
    name: str,
    kb_type: str,
    description: Optional[str] = None,
) -> int:
    if kb_type not in ("product", "enterprise", "experience"):
        raise ValueError(f"非法 kb_type: {kb_type}")
    now = _now_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_bases (name, kb_type, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, kb_type, description, now, now),
        )
    return int(cur.lastrowid)


def delete_kb(conn: sqlite3.Connection, kb_id: int) -> bool:
    """删除 KB（连带 files 表 ON DELETE CASCADE）。

    向量库 collection 中的 chunks 由上层 KBStore 在 endpoint 中负责清理。
    """
    with conn:
        cur = conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
    return cur.rowcount > 0


def update_kb_stats(
    conn: sqlite3.Connection,
    kb_id: int,
    *,
    file_count: Optional[int] = None,
    chunk_count: Optional[int] = None,
) -> None:
    """更新 KB 的文件数/chunk 数统计字段。"""
    sets: list[str] = []
    params: list[Any] = []
    if file_count is not None:
        sets.append("file_count = ?")
        params.append(int(file_count))
    if chunk_count is not None:
        sets.append("chunk_count = ?")
        params.append(int(chunk_count))
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(kb_id)
    with conn:
        conn.execute(
            f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id = ?",
            params,
        )


def recompute_kb_stats(conn: sqlite3.Connection, kb_id: int) -> None:
    """从 knowledge_files 重算 file_count / chunk_count 并写回 KB 行。"""
    row = conn.execute(
        """
        SELECT COUNT(*) AS files, COALESCE(SUM(chunk_count), 0) AS chunks
          FROM knowledge_files WHERE kb_id = ? AND status = 'indexed'
        """,
        (kb_id,),
    ).fetchone()
    update_kb_stats(
        conn,
        kb_id,
        file_count=int(row["files"]) if row else 0,
        chunk_count=int(row["chunks"]) if row else 0,
    )


def list_kb_files(
    conn: sqlite3.Connection,
    kb_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM knowledge_files WHERE kb_id = ? ORDER BY id ASC",
        (kb_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_kb_file(conn: sqlite3.Connection, file_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM knowledge_files WHERE id = ?", (file_id,)
    ).fetchone()
    return dict(row) if row else None


def create_kb_file(
    conn: sqlite3.Connection,
    *,
    kb_id: int,
    filename: str,
    file_path: str,
    file_type: Optional[str] = None,
    file_size: Optional[int] = None,
    status: str = "pending",
) -> int:
    now = _now_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_files (
                kb_id, filename, file_path, file_type, file_size,
                chunk_count, status, error_msg, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, NULL, ?, ?)
            """,
            (kb_id, filename, file_path, file_type, file_size, status, now, now),
        )
    return int(cur.lastrowid)


def update_kb_file_status(
    conn: sqlite3.Connection,
    file_id: int,
    *,
    status: Optional[str] = None,
    chunk_count: Optional[int] = None,
    error_msg: Optional[str] = None,
) -> None:
    """更新文件索引状态（pending / indexing / indexed / failed）。"""
    sets: list[str] = []
    params: list[Any] = []
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if chunk_count is not None:
        sets.append("chunk_count = ?")
        params.append(int(chunk_count))
    if error_msg is not None:
        sets.append("error_msg = ?")
        params.append(error_msg)
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(file_id)
    with conn:
        conn.execute(
            f"UPDATE knowledge_files SET {', '.join(sets)} WHERE id = ?",
            params,
        )


def delete_kb_file(conn: sqlite3.Connection, file_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
    return cur.rowcount > 0


def list_pending_files(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """列出所有 pending 状态的 file（用于 startup 自动续接索引）。"""
    rows = conn.execute(
        "SELECT * FROM knowledge_files WHERE status IN ('pending', 'indexing') ORDER BY id ASC"
    ).fetchall()
    return [dict(r) for r in rows]


# ============================================================
# Stage 6a：sessions CRUD
# ============================================================
# sessions 表已在 Stage 1 schema 中预留全部字段（含 product_kb_id / enterprise_kb_id /
# opening_line / config_json / summary_json）。这里补 CRUD。
#
# status 取值约定：
#   pending   刚创建未启动
#   running   引擎已启动
#   done      正常结束（含 TIMEOUT / DEAL_DONE / WALK_AWAY 等）
#   cancelled 用户主动中断
#   failed    引擎异常退出


def _row_to_session(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    """sqlite3.Row → dict，含 config_json / summary_json 解码。"""
    if row is None:
        return {}
    d = dict(row)
    for key in ("config_json", "summary_json"):
        raw = d.get(key)
        d[key.replace("_json", "")] = json.loads(raw) if raw else {}
    return d


def create_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    persona_id: Optional[int],
    product_kb_id: Optional[int],
    enterprise_kb_id: Optional[int],
    provider_id: Optional[int],
    topic: str,
    opening_line: str,
    max_rounds: int,
    handbook_id: Optional[int] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """创建一条 sessions 记录，status='pending'。

    config 推荐包含：who_speaks_first / judge_interval / memory_interval /
    max_rounds_floor / first_speaker / opening_template_idx。

    handbook_id：可选，绑定到本场会话的产品手册（Handbook Analysis v2）。
    """
    now = _now_iso()
    cfg_json = json.dumps(config or {}, ensure_ascii=False)
    with conn:
        conn.execute(
            """
            INSERT INTO sessions (
                id, persona_id, product_kb_id, enterprise_kb_id, handbook_id, provider_id,
                topic, opening_line, max_rounds, status,
                config_json, summary_json,
                started_at, ended_at, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, 'pending',
                ?, NULL,
                NULL, NULL, ?, ?
            )
            """,
            (
                session_id, persona_id, product_kb_id, enterprise_kb_id, handbook_id, provider_id,
                topic, opening_line, int(max_rounds),
                cfg_json,
                now, now,
            ),
        )
    return get_session_by_id(conn, session_id) or {}


def get_session_by_id(
    conn: sqlite3.Connection, session_id: str
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_session(row) if row else None


def update_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    status: Optional[str] = None,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    summary: Optional[dict[str, Any]] = None,
) -> None:
    """部分更新 sessions 行。summary 直接覆盖 summary_json。"""
    sets: list[str] = []
    params: list[Any] = []
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if started_at is not None:
        sets.append("started_at = ?")
        params.append(started_at)
    if ended_at is not None:
        sets.append("ended_at = ?")
        params.append(ended_at)
    if summary is not None:
        sets.append("summary_json = ?")
        params.append(json.dumps(summary, ensure_ascii=False))
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(session_id)
    with conn:
        conn.execute(
            f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?",
            params,
        )


def list_sessions(
    conn: sqlite3.Connection,
    *,
    persona_id: Optional[int] = None,
    status: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """筛选 + 分页列表 sessions，返回 (items, total)。

    outcome 不是表字段，存于 summary_json.outcome；走 SQL JSON 函数过滤。
    """
    where_clauses: list[str] = []
    params: list[Any] = []
    if persona_id is not None:
        where_clauses.append("persona_id = ?")
        params.append(persona_id)
    if status is not None:
        where_clauses.append("status = ?")
        params.append(status)
    if outcome is not None:
        where_clauses.append("json_extract(summary_json, '$.outcome') = ?")
        params.append(outcome)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    total_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM sessions {where_sql}", params
    ).fetchone()
    total = int(total_row["n"]) if total_row else 0

    rows = conn.execute(
        f"SELECT * FROM sessions {where_sql} "
        f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [int(limit), int(offset)],
    ).fetchall()
    return [_row_to_session(r) for r in rows], total


def delete_session(conn: sqlite3.Connection, session_id: str) -> bool:
    """删除 session（turns / evaluations ON DELETE CASCADE 自动清理）。"""
    with conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return cur.rowcount > 0


# ============================================================
# turns CRUD（Stage 7）
# ============================================================
#
# 实时持久化策略：
#   - SessionRunner.on_event 每次收到 persona_turn / sales_turn 立刻调 create_turn
#   - UNIQUE (session_id, idx, role) 防止网络重试 / 二次回放导致重复
#   - metadata_json 存 Turn.metadata 原样（含 strategy / hidden_state / rag_hits）


def _row_to_turn(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    raw = d.get("metadata_json")
    d["metadata"] = json.loads(raw) if raw else {}
    d.pop("metadata_json", None)
    return d


def create_turn(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    idx: int,
    role: str,
    content: str,
    stage: Optional[str],
    metadata: Optional[dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> None:
    """插入一条 turn 记录。

    role 取 'persona' 或 'sales'（与 schema.Turn.speaker 对齐）。
    UNIQUE 冲突时 INSERT OR IGNORE，让重试操作幂等。
    """
    ts = created_at or _now_iso()
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    with conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO turns
                (session_id, idx, role, content, stage, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, int(idx), role, content, stage, meta_json, ts),
        )


def list_turns(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict[str, Any]]:
    """按 (idx, role) 全量取一个 session 的所有 turns。

    排序：先按 idx 升序，再按 role（persona 在前 sales 在后，符合自然对话节奏）。
    """
    rows = conn.execute(
        """
        SELECT * FROM turns
        WHERE session_id = ?
        ORDER BY idx ASC,
                 CASE role WHEN 'persona' THEN 0 WHEN 'sales' THEN 1 ELSE 2 END,
                 id ASC
        """,
        (session_id,),
    ).fetchall()
    return [_row_to_turn(r) for r in rows]


# ============================================================
# evaluations CRUD（Stage 7）
# ============================================================
#
# evaluator_role: 'judge' | 'coach'（schema CHECK 约束）
#   - judge: 每个 judge_interval 一条，score_json = sales_score、feedback_json = 完整 JudgeFeedback
#   - coach: 会话末尾固定一条，score_json = None、feedback_json = 完整 CoachReview


def _row_to_evaluation(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    for k in ("score_json", "feedback_json"):
        raw = d.get(k)
        d[k.replace("_json", "")] = json.loads(raw) if raw else None
        d.pop(k, None)
    return d


def create_evaluation(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    evaluator_role: str,
    turn_idx: Optional[int],
    score: Optional[dict[str, Any]] = None,
    feedback: Optional[dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> int:
    """插入一条评估记录，返回新 id。"""
    if evaluator_role not in ("judge", "coach"):
        raise ValueError(f"evaluator_role 必须是 judge|coach: {evaluator_role}")
    ts = created_at or _now_iso()
    score_json = json.dumps(score, ensure_ascii=False) if score is not None else None
    feedback_json = (
        json.dumps(feedback, ensure_ascii=False) if feedback is not None else None
    )
    with conn:
        cur = conn.execute(
            """
            INSERT INTO evaluations
                (session_id, turn_idx, evaluator_role, score_json,
                 feedback_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, turn_idx, evaluator_role, score_json, feedback_json, ts),
        )
    return int(cur.lastrowid)


def list_evaluations(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    evaluator_role: Optional[str] = None,
) -> list[dict[str, Any]]:
    """取一个 session 的全部评估，按 (turn_idx, id) 升序。

    evaluator_role 可选过滤 'judge' / 'coach'。
    """
    where = "WHERE session_id = ?"
    params: list[Any] = [session_id]
    if evaluator_role is not None:
        where += " AND evaluator_role = ?"
        params.append(evaluator_role)
    rows = conn.execute(
        f"SELECT * FROM evaluations {where} "
        f"ORDER BY COALESCE(turn_idx, 0) ASC, id ASC",
        params,
    ).fetchall()
    return [_row_to_evaluation(r) for r in rows]


def get_latest_evaluation(
    conn: sqlite3.Connection,
    session_id: str,
    evaluator_role: str,
) -> dict[str, Any]:
    """取最新一条评估（Coach 通常只有一条，Judge 取最后一次）。"""
    row = conn.execute(
        """
        SELECT * FROM evaluations
        WHERE session_id = ? AND evaluator_role = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id, evaluator_role),
    ).fetchone()
    return _row_to_evaluation(row)


# ============================================================
# Stage 9：batch_jobs CRUD
# ============================================================


def _row_to_batch(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    for fld in ("persona_ids_json", "session_ids_json",
                "config_json", "summary_json"):
        raw = d.pop(fld, None)
        key = fld[:-5]  # 剥掉 _json
        try:
            d[key] = json.loads(raw) if raw else (
                [] if "ids" in fld else {}
            )
        except (json.JSONDecodeError, TypeError):
            d[key] = [] if "ids" in fld else {}
    return d


def create_batch_job(
    conn: sqlite3.Connection,
    *,
    name: str,
    persona_ids: list[int],
    product_kb_id: Optional[int] = None,
    enterprise_kb_id: Optional[int] = None,
    handbook_id: Optional[int] = None,
    provider_id: Optional[int] = None,
    topic: Optional[str] = None,
    opening_line: Optional[str] = None,
    max_rounds: int = 30,
    judge_interval: int = 3,
    memory_interval: int = 3,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """新建一条 batch_jobs 行（status=pending）。

    handbook_id：可选，绑定到本批次的产品手册（Handbook Analysis v2）。
    """
    now = _now_iso()
    cur = conn.execute(
        """
        INSERT INTO batch_jobs (
            name, persona_ids_json, product_kb_id, enterprise_kb_id, handbook_id,
            provider_id, topic, opening_line,
            max_rounds, judge_interval, memory_interval,
            total_count, completed_count, failed_count, cancelled_count,
            current_index, current_session_id, session_ids_json,
            status, config_json, summary_json, error_msg,
            started_at, ended_at, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, 0, 0, 0,
            0, NULL, ?,
            'pending', ?, NULL, NULL,
            NULL, NULL, ?, ?
        )
        """,
        (
            name,
            json.dumps(persona_ids, ensure_ascii=False),
            product_kb_id, enterprise_kb_id, handbook_id,
            provider_id, topic, opening_line,
            max_rounds, judge_interval, memory_interval,
            len(persona_ids),
            json.dumps([], ensure_ascii=False),
            json.dumps(config or {}, ensure_ascii=False),
            now, now,
        ),
    )
    bid = cur.lastrowid
    return get_batch_job(conn, bid)


def get_batch_job(
    conn: sqlite3.Connection, batch_id: int
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM batch_jobs WHERE id = ?", (batch_id,)
    ).fetchone()
    return _row_to_batch(row)


def list_batch_jobs(
    conn: sqlite3.Connection,
    *,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """分页：返回 (items, total)。"""
    where = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM batch_jobs {where_sql}", tuple(params)
    ).fetchone()["n"]

    rows = conn.execute(
        f"SELECT * FROM batch_jobs {where_sql} "
        f"ORDER BY id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_row_to_batch(r) for r in rows], int(total)


def update_batch_job(
    conn: sqlite3.Connection,
    batch_id: int,
    **fields: Any,
) -> dict[str, Any]:
    """部分更新；遇到 dict/list 自动 json.dumps 到对应 *_json 列。

    支持字段：
        status, started_at, ended_at, current_index, current_session_id,
        completed_count, failed_count, cancelled_count,
        error_msg, session_ids(list), summary(dict), config(dict)
    """
    if not fields:
        return get_batch_job(conn, batch_id)

    set_parts: list[str] = []
    params: list[Any] = []
    for k, v in fields.items():
        if k in ("session_ids", "summary", "config"):
            col = f"{k}_json" if k != "session_ids" else "session_ids_json"
            set_parts.append(f"{col} = ?")
            params.append(json.dumps(v, ensure_ascii=False))
        else:
            set_parts.append(f"{k} = ?")
            params.append(v)

    set_parts.append("updated_at = ?")
    params.append(_now_iso())
    params.append(batch_id)

    conn.execute(
        f"UPDATE batch_jobs SET {', '.join(set_parts)} WHERE id = ?",
        tuple(params),
    )
    return get_batch_job(conn, batch_id)


def delete_batch_job(conn: sqlite3.Connection, batch_id: int) -> bool:
    """删 batch_jobs 行本身（不级联删 sessions；上层若需可单独清）。"""
    cur = conn.execute(
        "DELETE FROM batch_jobs WHERE id = ?", (batch_id,)
    )
    return cur.rowcount > 0


# ============================================================
# Stage 11：sales_cases CRUD（销售案例集，三轨入库 + 预填）
# ============================================================

_CASE_JSON_FIELDS = ("dialogue_excerpt", "persona_tags", "tags")


def _row_to_case(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    for fld in _CASE_JSON_FIELDS:
        col = f"{fld}_json"
        raw = d.pop(col, None)
        try:
            d[fld] = json.loads(raw) if raw else (
                [] if fld in ("persona_tags", "tags") else None
            )
        except (json.JSONDecodeError, TypeError):
            d[fld] = [] if fld in ("persona_tags", "tags") else None
    return d


def create_sales_case(
    conn: sqlite3.Connection,
    *,
    source: str,
    title: str,
    session_id: Optional[str] = None,
    scene: Optional[str] = None,
    persona_id: Optional[int] = None,
    persona_tags: Optional[list[str]] = None,
    dialogue_excerpt: Optional[list[dict[str, Any]]] = None,
    raw_content: Optional[str] = None,
    why_excellent: Optional[str] = None,
    tags: Optional[list[str]] = None,
    file_source: Optional[str] = None,
) -> dict[str, Any]:
    """新建一条销售案例。source 必须 ∈ judge_auto/coach_auto/manual/preset。"""
    now = _now_iso()
    cur = conn.execute(
        """
        INSERT INTO sales_cases (
            session_id, source, title, scene, persona_id,
            persona_tags_json, dialogue_excerpt_json, raw_content,
            why_excellent, tags_json, votes, file_source,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            session_id, source, title, scene, persona_id,
            json.dumps(persona_tags or [], ensure_ascii=False),
            json.dumps(dialogue_excerpt or [], ensure_ascii=False)
                if dialogue_excerpt is not None else None,
            raw_content,
            why_excellent,
            json.dumps(tags or [], ensure_ascii=False),
            file_source,
            now, now,
        ),
    )
    return get_sales_case(conn, cur.lastrowid)


def get_sales_case(conn: sqlite3.Connection, case_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM sales_cases WHERE id = ?", (case_id,)
    ).fetchone()
    return _row_to_case(row)


def list_sales_cases(
    conn: sqlite3.Connection,
    *,
    source: Optional[str] = None,
    persona_id: Optional[int] = None,
    session_id: Optional[str] = None,
    tag: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """分页列表：返回 (items, total)。

    - tag 用 JSON 子串匹配（tags_json LIKE %"tag"%），够 MVP 用。
    - keyword 在 title / scene / raw_content / why_excellent 上 OR LIKE。
    """
    where: list[str] = []
    params: list[Any] = []
    if source:
        where.append("source = ?")
        params.append(source)
    if persona_id is not None:
        where.append("persona_id = ?")
        params.append(persona_id)
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if tag:
        where.append("(tags_json LIKE ? OR persona_tags_json LIKE ?)")
        like = f'%"{tag}"%'
        params.extend([like, like])
    if keyword:
        kw = f"%{keyword}%"
        where.append(
            "(title LIKE ? OR scene LIKE ? OR "
            "raw_content LIKE ? OR why_excellent LIKE ?)"
        )
        params.extend([kw, kw, kw, kw])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM sales_cases {where_sql}",
        tuple(params),
    ).fetchone()["n"]

    rows = conn.execute(
        f"SELECT * FROM sales_cases {where_sql} "
        f"ORDER BY id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_row_to_case(r) for r in rows], int(total)


def count_sales_cases(
    conn: sqlite3.Connection, *, source: Optional[str] = None,
) -> int:
    if source:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sales_cases WHERE source = ?",
            (source,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sales_cases"
        ).fetchone()
    return int(row["n"])


def update_sales_case(
    conn: sqlite3.Connection,
    case_id: int,
    **fields: Any,
) -> dict[str, Any]:
    """部分更新；list/dict 字段自动 JSON 编码。

    支持：title, scene, why_excellent, tags, persona_tags,
          dialogue_excerpt, votes, raw_content
    """
    if not fields:
        return get_sales_case(conn, case_id)
    set_parts: list[str] = []
    params: list[Any] = []
    for k, v in fields.items():
        if k in ("tags", "persona_tags", "dialogue_excerpt"):
            set_parts.append(f"{k}_json = ?")
            params.append(json.dumps(v, ensure_ascii=False))
        else:
            set_parts.append(f"{k} = ?")
            params.append(v)
    set_parts.append("updated_at = ?")
    params.append(_now_iso())
    params.append(case_id)
    conn.execute(
        f"UPDATE sales_cases SET {', '.join(set_parts)} WHERE id = ?",
        tuple(params),
    )
    return get_sales_case(conn, case_id)


def delete_sales_case(conn: sqlite3.Connection, case_id: int) -> bool:
    cur = conn.execute("DELETE FROM sales_cases WHERE id = ?", (case_id,))
    return cur.rowcount > 0


# ============================================================
# 优秀话术库 CRUD（excellent_phrases，单条优秀话术沉淀）
# ============================================================

def _row_to_phrase(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    raw = d.pop("why_good_json", None)
    try:
        d["why_good"] = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        d["why_good"] = []
    d["is_off_handbook"] = bool(d.get("is_off_handbook"))
    return d


def upsert_excellent_phrase(
    conn: sqlite3.Connection,
    *,
    sales_content: str,
    analysis_job_id: Optional[int] = None,
    session_id: Optional[str] = None,
    handbook_id: Optional[int] = None,
    turn_idx: Optional[int] = None,
    group_key: Optional[str] = None,
    handbook_label: Optional[str] = None,
    persona_name: Optional[str] = None,
    customer_question: Optional[str] = None,
    excellence_score: float = 0.0,
    purchase_signal_before: Optional[float] = None,
    purchase_signal_after: Optional[float] = None,
    is_off_handbook: bool = False,
    why_good: Optional[list[str]] = None,
    source: str = "analysis_auto",
) -> dict[str, Any]:
    """插入或更新一条优秀话术（按 session_id+turn_idx+handbook_label 去重）。"""
    now = _now_iso()
    cur = conn.execute(
        """
        INSERT INTO excellent_phrases (
            analysis_job_id, session_id, handbook_id, turn_idx, group_key,
            handbook_label, persona_name, customer_question, sales_content,
            excellence_score, purchase_signal_before, purchase_signal_after,
            is_off_handbook, why_good_json, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id, turn_idx, handbook_label) DO UPDATE SET
            analysis_job_id = excluded.analysis_job_id,
            handbook_id = excluded.handbook_id,
            group_key = excluded.group_key,
            persona_name = excluded.persona_name,
            customer_question = excluded.customer_question,
            sales_content = excluded.sales_content,
            excellence_score = excluded.excellence_score,
            purchase_signal_before = excluded.purchase_signal_before,
            purchase_signal_after = excluded.purchase_signal_after,
            is_off_handbook = excluded.is_off_handbook,
            why_good_json = excluded.why_good_json,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (
            analysis_job_id, session_id, handbook_id, turn_idx, group_key,
            handbook_label, persona_name, customer_question, sales_content,
            float(excellence_score or 0.0), purchase_signal_before, purchase_signal_after,
            1 if is_off_handbook else 0,
            json.dumps(why_good or [], ensure_ascii=False),
            source, now, now,
        ),
    )
    row = conn.execute(
        "SELECT * FROM excellent_phrases WHERE rowid = ?", (cur.lastrowid,)
    ).fetchone()
    if row is None and session_id is not None:
        row = conn.execute(
            "SELECT * FROM excellent_phrases WHERE session_id = ? AND turn_idx IS ? "
            "AND handbook_label IS ?",
            (session_id, turn_idx, handbook_label),
        ).fetchone()
    return _row_to_phrase(row)


def list_excellent_phrases(
    conn: sqlite3.Connection,
    *,
    group_key: Optional[str] = None,
    keyword: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """分页列表：返回 (items, total)，默认按优秀度倒序。"""
    where: list[str] = []
    params: list[Any] = []
    if group_key:
        where.append("group_key = ?")
        params.append(group_key)
    if min_score is not None:
        where.append("excellence_score >= ?")
        params.append(float(min_score))
    if keyword:
        kw = f"%{keyword}%"
        where.append(
            "(sales_content LIKE ? OR customer_question LIKE ? OR "
            "handbook_label LIKE ? OR persona_name LIKE ?)"
        )
        params.extend([kw, kw, kw, kw])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM excellent_phrases {where_sql}",
        tuple(params),
    ).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM excellent_phrases {where_sql} "
        f"ORDER BY excellence_score DESC, id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_row_to_phrase(r) for r in rows], int(total)


def count_excellent_phrases_by_group(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT group_key, COUNT(*) AS n FROM excellent_phrases GROUP BY group_key"
    ).fetchall()
    return {(r["group_key"] or "unknown"): int(r["n"]) for r in rows}


def delete_excellent_phrase(conn: sqlite3.Connection, phrase_id: int) -> bool:
    cur = conn.execute("DELETE FROM excellent_phrases WHERE id = ?", (phrase_id,))
    return cur.rowcount > 0


def persist_excellent_phrases_from_summary(
    conn: sqlite3.Connection,
    *,
    analysis_job_id: int,
    handbook_id: Optional[int],
    excellent_by_group: dict[str, Any],
    per_group_cap: int = 10,
    min_score: float = 6.5,
) -> int:
    """把分析报告的 excellent_by_group 沉淀进优秀话术库。返回写入条数。"""
    groups = (excellent_by_group or {}).get("groups") or []
    written = 0
    for g in groups:
        gkey = g.get("key")
        for it in (g.get("items") or [])[:per_group_cap]:
            content = (it.get("sales_content") or "").strip()
            score = float(it.get("excellence_score") or 0.0)
            if not content or score < min_score:
                continue
            try:
                upsert_excellent_phrase(
                    conn,
                    analysis_job_id=analysis_job_id,
                    session_id=it.get("session_id"),
                    handbook_id=handbook_id,
                    turn_idx=it.get("turn_idx"),
                    group_key=gkey,
                    handbook_label=it.get("handbook_label") or g.get("label"),
                    persona_name=it.get("persona_name"),
                    customer_question=it.get("customer_question"),
                    sales_content=content,
                    excellence_score=score,
                    purchase_signal_before=it.get("purchase_signal_before"),
                    purchase_signal_after=it.get("purchase_signal_after"),
                    is_off_handbook=bool(it.get("is_off_handbook")),
                    why_good=it.get("why_good") or [],
                    source="analysis_auto",
                )
                written += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("[excellent_phrases] 写入失败 sess=%s idx=%s: %s",
                               it.get("session_id"), it.get("turn_idx"), exc)
    return written


# ===========================================================================
# Stage 14: agent_skills_config（销冠技能配置·单行表 id=1）
# ===========================================================================


_AGENT_SKILLS_DEFAULTS = {
    "enabled_tools": [],         # 启用的工具 name 列表
    "max_tool_loops": 3,         # tool_use 循环最大轮数
    "tool_top_k_default": 3,     # 工具默认 top_k
    "web_search_provider": "tavily",
    "web_search_api_key": "",
    "mcp_servers": [],           # 预留：[{name, command, args, enabled}, ...]
    "extra_config": {},
}


def _row_to_agent_skills(row: sqlite3.Row) -> dict[str, Any]:
    if row is None:
        return dict(_AGENT_SKILLS_DEFAULTS)
    d = dict(row)
    try:
        d["enabled_tools"] = json.loads(d.get("enabled_tools_json") or "[]")
    except Exception:
        d["enabled_tools"] = []
    try:
        d["mcp_servers"] = json.loads(d.get("mcp_servers_json") or "[]")
    except Exception:
        d["mcp_servers"] = []
    try:
        d["extra_config"] = json.loads(d.get("extra_config_json") or "{}")
    except Exception:
        d["extra_config"] = {}
    return d


def get_agent_skills_config(conn: sqlite3.Connection) -> dict[str, Any]:
    """读取销冠技能配置；不存在则插入默认行后返回默认值。"""
    row = conn.execute(
        "SELECT * FROM agent_skills_config WHERE id = 1"
    ).fetchone()
    if row is None:
        now = _now_iso()
        with conn:
            conn.execute(
                """
                INSERT INTO agent_skills_config (
                    id, enabled_tools_json, max_tool_loops, tool_top_k_default,
                    web_search_provider, web_search_api_key,
                    mcp_servers_json, extra_config_json, updated_at
                ) VALUES (1, '[]', 3, 3, 'tavily', '', '[]', '{}', ?)
                """,
                (now,),
            )
        row = conn.execute(
            "SELECT * FROM agent_skills_config WHERE id = 1"
        ).fetchone()
    return _row_to_agent_skills(row)


def update_agent_skills_config(
    conn: sqlite3.Connection,
    **fields: Any,
) -> dict[str, Any]:
    """部分更新销冠技能配置。

    支持字段：enabled_tools(list[str]), max_tool_loops(int), tool_top_k_default(int),
    web_search_provider(str), web_search_api_key(str), mcp_servers(list[dict]),
    extra_config(dict)。
    """
    get_agent_skills_config(conn)  # 确保行存在

    set_parts: list[str] = []
    params: list[Any] = []

    if "enabled_tools" in fields:
        set_parts.append("enabled_tools_json = ?")
        params.append(json.dumps(fields["enabled_tools"] or [], ensure_ascii=False))
    if "max_tool_loops" in fields:
        v = int(fields["max_tool_loops"])
        if v < 0:
            v = 0
        if v > 10:
            v = 10
        set_parts.append("max_tool_loops = ?")
        params.append(v)
    if "tool_top_k_default" in fields:
        v = int(fields["tool_top_k_default"])
        if v < 1:
            v = 1
        if v > 20:
            v = 20
        set_parts.append("tool_top_k_default = ?")
        params.append(v)
    if "web_search_provider" in fields:
        set_parts.append("web_search_provider = ?")
        params.append(str(fields["web_search_provider"] or "tavily"))
    if "web_search_api_key" in fields:
        set_parts.append("web_search_api_key = ?")
        params.append(str(fields["web_search_api_key"] or ""))
    if "mcp_servers" in fields:
        set_parts.append("mcp_servers_json = ?")
        params.append(json.dumps(fields["mcp_servers"] or [], ensure_ascii=False))
    if "extra_config" in fields:
        set_parts.append("extra_config_json = ?")
        params.append(json.dumps(fields["extra_config"] or {}, ensure_ascii=False))

    if set_parts:
        set_parts.append("updated_at = ?")
        params.append(_now_iso())
        with conn:
            conn.execute(
                f"UPDATE agent_skills_config SET {', '.join(set_parts)} WHERE id = 1",
                tuple(params),
            )
    return get_agent_skills_config(conn)


# ===========================================================================
# Stage 15a: agent_profiles + agent_profile_versions（销冠 Agent 配置中心）
# ===========================================================================


_AGENT_PROFILE_FIELDS_JSON = {
    "opening_lines": "opening_lines_json",
    "default_session_params": "default_session_params_json",
    "model_override": "model_override_json",
    "extra": "extra_json",
}


def _row_to_agent_profile(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    for k, col in _AGENT_PROFILE_FIELDS_JSON.items():
        raw = d.get(col)
        try:
            d[k] = json.loads(raw) if raw else (None if k == "model_override" else ([] if k == "opening_lines" else {}))
        except Exception:
            d[k] = [] if k == "opening_lines" else {}
    return d


def _seed_sales_profile(conn: sqlite3.Connection) -> None:
    """首次创建 sales 行：system_prompt 取自 prompts/sales_prompt.md（如果存在）。"""
    row = conn.execute(
        "SELECT id FROM agent_profiles WHERE name = ?", ("sales",)
    ).fetchone()
    if row:
        return

    # 默认 prompt 来自 prompts/sales_prompt.md（兜底：内置一段最小可用 prompt）
    default_prompt = ""
    try:
        from src.agents import _PROMPTS_DIR  # 复用既有常量
        p = _PROMPTS_DIR / "sales_prompt.md"
        if p.exists():
            default_prompt = p.read_text(encoding="utf-8")
    except Exception:
        default_prompt = ""
    if not default_prompt.strip():
        default_prompt = (
            "你是销售模拟系统中的销冠 Agent。请按 JSON 输出："
            '{"content": "...", "strategy": {...}}。'
        )

    default_role_desc = "华为终端销冠：擅长在不同人设面前快速建立信任、挖掘真实需求、克服核心异议、稳健推进成交。"
    default_openings = [
        "您好，欢迎到店！您今天主要想看哪一类产品？",
        "您是自己用还是给家人挑？",
        "您之前用过类似的产品吗？感觉哪些点最在意？",
        "我帮您快速过一下当前主推的几款，您看看哪款方向更贴近？",
    ]
    default_session_params = {
        "max_rounds": 30,
        "max_rounds_floor": 6,
        "judge_interval": 3,
        "memory_interval": 3,
        "temperature": 0.6,
    }

    now = _now_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO agent_profiles (
                name, role_description, system_prompt,
                opening_lines_json, default_session_params_json,
                model_override_json, extra_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sales",
                default_role_desc,
                default_prompt,
                json.dumps(default_openings, ensure_ascii=False),
                json.dumps(default_session_params, ensure_ascii=False),
                "{}",
                "{}",
                now,
                now,
            ),
        )
        pid = int(cur.lastrowid)
        # 同时记录 v1 快照
        conn.execute(
            """
            INSERT INTO agent_profile_versions (
                profile_id, version_no, snapshot_json, comment, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                pid,
                1,
                json.dumps({
                    "role_description": default_role_desc,
                    "system_prompt": default_prompt,
                    "opening_lines": default_openings,
                    "default_session_params": default_session_params,
                    "model_override": {},
                }, ensure_ascii=False),
                "初始化（从 prompts/sales_prompt.md seed）",
                now,
            ),
        )


def get_agent_profile(conn: sqlite3.Connection, name: str) -> Optional[dict[str, Any]]:
    """按 name 取 profile；name='sales' 时若不存在则自动 seed 后再返回。"""
    if name == "sales":
        _seed_sales_profile(conn)
    row = conn.execute(
        "SELECT * FROM agent_profiles WHERE name = ?", (name,)
    ).fetchone()
    return _row_to_agent_profile(row)


def _snapshot_of_profile(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "role_description": p.get("role_description") or "",
        "system_prompt": p.get("system_prompt") or "",
        "opening_lines": p.get("opening_lines") or [],
        "default_session_params": p.get("default_session_params") or {},
        "model_override": p.get("model_override") or {},
    }


def update_agent_profile(
    conn: sqlite3.Connection,
    name: str,
    *,
    role_description: Optional[str] = None,
    system_prompt: Optional[str] = None,
    opening_lines: Optional[list[str]] = None,
    default_session_params: Optional[dict[str, Any]] = None,
    model_override: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    bump_version: bool = True,
    version_comment: Optional[str] = None,
) -> dict[str, Any]:
    """部分更新一个 agent profile；默认每次更新都 bump 一个新版本快照。

    Returns:
        更新后的 profile dict。
    """
    current = get_agent_profile(conn, name)
    if current is None:
        raise ValueError(f"agent_profile '{name}' 不存在")

    set_parts: list[str] = []
    params: list[Any] = []

    if role_description is not None:
        set_parts.append("role_description = ?")
        params.append(str(role_description))
    if system_prompt is not None:
        set_parts.append("system_prompt = ?")
        params.append(str(system_prompt))
    if opening_lines is not None:
        set_parts.append("opening_lines_json = ?")
        params.append(json.dumps(list(opening_lines), ensure_ascii=False))
    if default_session_params is not None:
        set_parts.append("default_session_params_json = ?")
        params.append(json.dumps(dict(default_session_params), ensure_ascii=False))
    if model_override is not None:
        set_parts.append("model_override_json = ?")
        params.append(json.dumps(dict(model_override), ensure_ascii=False))
    if extra is not None:
        set_parts.append("extra_json = ?")
        params.append(json.dumps(dict(extra), ensure_ascii=False))

    if not set_parts:
        return current

    set_parts.append("updated_at = ?")
    params.append(_now_iso())
    params.append(current["id"])

    with conn:
        conn.execute(
            f"UPDATE agent_profiles SET {', '.join(set_parts)} WHERE id = ?",
            tuple(params),
        )

    new_profile = get_agent_profile(conn, name)
    if bump_version and new_profile is not None:
        _append_profile_version(conn, new_profile, version_comment)
    return new_profile


def _append_profile_version(
    conn: sqlite3.Connection,
    profile: dict[str, Any],
    comment: Optional[str],
) -> int:
    """对当前 profile 状态打一个版本快照（自动递增 version_no）。"""
    row = conn.execute(
        "SELECT COALESCE(MAX(version_no), 0) AS mx FROM agent_profile_versions "
        "WHERE profile_id = ?",
        (profile["id"],),
    ).fetchone()
    next_no = int(row["mx"] or 0) + 1
    snapshot = _snapshot_of_profile(profile)
    with conn:
        cur = conn.execute(
            """
            INSERT INTO agent_profile_versions (
                profile_id, version_no, snapshot_json, comment, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                profile["id"],
                next_no,
                json.dumps(snapshot, ensure_ascii=False),
                comment,
                _now_iso(),
            ),
        )
    return int(cur.lastrowid)


def list_agent_profile_versions(
    conn: sqlite3.Connection,
    name: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    profile = get_agent_profile(conn, name)
    if profile is None:
        return []
    rows = conn.execute(
        """
        SELECT id, version_no, snapshot_json, comment, created_at
        FROM agent_profile_versions
        WHERE profile_id = ?
        ORDER BY version_no DESC
        LIMIT ?
        """,
        (profile["id"], int(limit)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            d["snapshot"] = json.loads(d.pop("snapshot_json") or "{}")
        except Exception:
            d["snapshot"] = {}
        out.append(d)
    return out


def restore_agent_profile_version(
    conn: sqlite3.Connection,
    name: str,
    version_no: int,
) -> dict[str, Any]:
    """把指定版本的快照回写为当前 profile 主表内容，并新建一个版本记录 'restore from vN'。"""
    profile = get_agent_profile(conn, name)
    if profile is None:
        raise ValueError(f"agent_profile '{name}' 不存在")
    row = conn.execute(
        """
        SELECT snapshot_json FROM agent_profile_versions
        WHERE profile_id = ? AND version_no = ?
        """,
        (profile["id"], int(version_no)),
    ).fetchone()
    if row is None:
        raise ValueError(f"版本 v{version_no} 不存在")
    try:
        snap = json.loads(row["snapshot_json"] or "{}")
    except Exception:
        snap = {}
    return update_agent_profile(
        conn,
        name,
        role_description=snap.get("role_description"),
        system_prompt=snap.get("system_prompt"),
        opening_lines=snap.get("opening_lines"),
        default_session_params=snap.get("default_session_params"),
        model_override=snap.get("model_override"),
        bump_version=True,
        version_comment=f"restore from v{version_no}",
    )


# ============================================================
# Handbook Analysis（HA）模块 · CRUD
# 设计文档：docs/handbook_analysis_dev_spec.md
# ============================================================

_HANDBOOK_STATUS = {"draft", "extracting", "ready", "failed"}
_HANDBOOK_FILE_STATUS = {"pending", "parsing", "parsed", "failed"}
_ANALYSIS_JOB_STATUS = {"pending", "running", "completed", "failed", "cancelled"}


def _row_to_handbook(row: sqlite3.Row) -> dict[str, Any]:
    """把 sqlite Row 转为 dict 并把 JSON 字段反序列化（便于上层直接用）。"""
    d = dict(row)
    for key in ("structure_json", "source_files_json"):
        raw = d.get(key)
        try:
            d[key] = json.loads(raw) if raw else ({} if key.endswith("structure_json") else [])
        except Exception:
            d[key] = {} if key.endswith("structure_json") else []
    return d


def list_handbooks(
    conn: sqlite3.Connection,
    *,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    """列出所有 handbook，按 id 倒序（新建在前）。

    可选按 status 过滤（例如 status='ready' 只看可用的）。
    """
    if status:
        rows = conn.execute(
            "SELECT * FROM product_handbooks WHERE status = ? ORDER BY id DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM product_handbooks ORDER BY id DESC"
        ).fetchall()
    return [_row_to_handbook(r) for r in rows]


def resolve_default_handbook_id(conn: sqlite3.Connection) -> Optional[int]:
    """决策 4：分析报告/老 session 兜底——若全库只有一份 ready Handbook，
    自动套用；多份或一份都没有时返回 None。

    用法：上层（分析报告创建任务时 / 老 session 注入 Handbook 时）
    先看 session.handbook_id，为空则调本函数。
    """
    rows = conn.execute(
        "SELECT id FROM product_handbooks WHERE status = 'ready' ORDER BY id ASC"
    ).fetchall()
    if len(rows) == 1:
        return int(rows[0]["id"])
    return None


def set_session_handbook(
    conn: sqlite3.Connection, session_id: str, handbook_id: Optional[int],
) -> None:
    """老 session 补绑 Handbook（分析报告页用）。"""
    with conn:
        conn.execute(
            "UPDATE sessions SET handbook_id = ?, updated_at = ? WHERE id = ?",
            (handbook_id, _now_iso(), session_id),
        )


def set_batch_handbook(
    conn: sqlite3.Connection, batch_id: int, handbook_id: Optional[int],
) -> None:
    """老 batch 补绑 Handbook。"""
    with conn:
        conn.execute(
            "UPDATE batch_jobs SET handbook_id = ?, updated_at = ? WHERE id = ?",
            (handbook_id, _now_iso(), int(batch_id)),
        )


def get_handbook(
    conn: sqlite3.Connection, handbook_id: int
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM product_handbooks WHERE id = ?", (handbook_id,)
    ).fetchone()
    return _row_to_handbook(row) if row else None


def get_handbook_by_name(
    conn: sqlite3.Connection, name: str
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM product_handbooks WHERE name = ?", (name,)
    ).fetchone()
    return _row_to_handbook(row) if row else None


# ============================================================
# 品牌人格（③ 手册解耦）：产品无关的华为零售店身份，所有手册共用
# ============================================================

# 默认华为品牌人格的「销售身份与店铺范围」铁律全文（产品无关版本：
# 不写死任何具体型号，主打型号一律指向当场 Handbook）。
_DEFAULT_HUAWEI_IDENTITY_BLOCK = (
    "- **你的身份**：**华为授权旗舰零售店**的店员销售（线下店，非客服热线、非官网客服）。\n"
    "- **店内只卖华为及华为子品牌产品**。本店不卖 Apple iPad、不卖 Samsung Galaxy Tab、"
    "不卖小米 / OPPO / vivo / 联想 / 微软 Surface 等任何**非华为**产品。\n"
    "- **客户问“你们有 iPad / 三星 / Surface 吗？” 时**，**唯一**正确回应是：\n"
    "  > “我们这是华为旗舰店，只卖华为产品。不过您要比较的话，我可以直接告诉您华为对 "
    "iPad / 三星 的关键差异点 ……”\n"
    "  - **绝对不可以**说“iPad 和三星我们都有样机”、“您可以直接上手对比”——**店里根本没有**，"
    "胡说就是欺骗客户。\n"
    "- **只能推 Handbook 里出现过的华为型号**。本场主打型号见下方 `📘 产品手册`，"
    "**禁止脑补型号**（Handbook 里没出现过的型号一律不主动提；客户主动问其他华为型号时，"
    "只能说“那款我这边没有详细资料，今天我给您讲透本场主推型号，您看看是不是更合适”）。\n"
    "- 推荐的型号名必须**与 Handbook 完全一致**。客户要看其他型号 → **不许编**，"
    "直接说“那款不在我今天主推范围”。"
)

_DEFAULT_HUAWEI_COMPETITOR_DENY = [
    "Apple iPad", "Samsung Galaxy Tab", "小米", "OPPO", "vivo", "联想", "微软 Surface",
]


def _row_to_brand_profile(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    d["is_default"] = bool(d.get("is_default"))
    d["competitor_deny"] = json.loads(d.get("competitor_deny_json") or "[]")
    return d


def seed_default_brand_profile(conn: sqlite3.Connection) -> None:
    """幂等：brand_profiles 表无任何行时，插入华为默认品牌人格。"""
    row = conn.execute("SELECT COUNT(*) AS n FROM brand_profiles").fetchone()
    if row and row["n"] > 0:
        return
    now = _now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO brand_profiles (
                name, is_default, identity_block, competitor_deny_json,
                notes, created_at, updated_at
            ) VALUES (?, 1, ?, ?, ?, ?, ?)
            """,
            (
                "华为",
                _DEFAULT_HUAWEI_IDENTITY_BLOCK,
                json.dumps(_DEFAULT_HUAWEI_COMPETITOR_DENY, ensure_ascii=False),
                "默认品牌人格（产品无关），所有产品手册共用。",
                now, now,
            ),
        )


def get_default_brand_profile(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
    """取默认品牌人格：优先 is_default=1，否则 id 最小那行。"""
    row = conn.execute(
        "SELECT * FROM brand_profiles ORDER BY is_default DESC, id ASC LIMIT 1"
    ).fetchone()
    return _row_to_brand_profile(row)


# ============================================================
# 市场事实表缓存（② 深度研究节点）
# ============================================================


def _row_to_market_facts(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    d["facts"] = json.loads(d.get("facts_json") or "{}")
    d["sources"] = json.loads(d.get("sources_json") or "[]")
    return d


def get_market_facts(
    conn: sqlite3.Connection,
    *,
    handbook_id: Optional[int],
    country_code: str,
) -> Optional[dict[str, Any]]:
    """读一份缓存的市场事实表；未命中返回 None。"""
    row = conn.execute(
        "SELECT * FROM market_facts WHERE handbook_id IS ? AND country_code = ?",
        (handbook_id, (country_code or "").upper()),
    ).fetchone()
    return _row_to_market_facts(row)


def upsert_market_facts(
    conn: sqlite3.Connection,
    *,
    handbook_id: Optional[int],
    country_code: str,
    product_name: str,
    facts: dict[str, Any],
    sources: list[Any],
    model: Optional[str] = None,
) -> dict[str, Any]:
    """按 (handbook_id, country_code) 覆盖写入一份市场事实表。"""
    now = _now_iso()
    cc = (country_code or "").upper()
    facts_str = json.dumps(facts or {}, ensure_ascii=False)
    sources_str = json.dumps(sources or [], ensure_ascii=False)
    with conn:
        conn.execute(
            """
            INSERT INTO market_facts (
                handbook_id, country_code, product_name, facts_json, sources_json,
                model, researched_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(handbook_id, country_code) DO UPDATE SET
                product_name  = excluded.product_name,
                facts_json    = excluded.facts_json,
                sources_json  = excluded.sources_json,
                model         = excluded.model,
                researched_at = excluded.researched_at,
                updated_at    = excluded.updated_at
            """,
            (handbook_id, cc, product_name, facts_str, sources_str, model, now, now, now),
        )
    return get_market_facts(conn, handbook_id=handbook_id, country_code=cc)


def create_handbook(
    conn: sqlite3.Connection,
    *,
    name: str,
    product_kb_id: Optional[int] = None,
    description: Optional[str] = None,
    structure: Optional[dict[str, Any]] = None,
    status: str = "draft",
) -> int:
    """新建一个 handbook。structure 给了就直接 ready。"""
    if status not in _HANDBOOK_STATUS:
        raise ValueError(f"非法 handbook status: {status}")
    now = _now_iso()
    structure_str = json.dumps(structure or {}, ensure_ascii=False)
    with conn:
        cur = conn.execute(
            """
            INSERT INTO product_handbooks (
                name, product_kb_id, description, structure_json, source_files_json,
                status, extraction_log, version_no, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '[]', ?, NULL, 1, ?, ?)
            """,
            (name, product_kb_id, description, structure_str, status, now, now),
        )
    return int(cur.lastrowid)


def update_handbook(
    conn: sqlite3.Connection,
    handbook_id: int,
    *,
    name: Optional[str] = None,
    product_kb_id: Optional[int] = None,
    description: Optional[str] = None,
    structure: Optional[dict[str, Any]] = None,
    status: Optional[str] = None,
    extraction_log: Optional[str] = None,
    bump_version: bool = False,
) -> Optional[dict[str, Any]]:
    """部分更新；任何字段 None 表示不变。bump_version=True 时 version_no+1。"""
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if product_kb_id is not None:
        sets.append("product_kb_id = ?")
        params.append(int(product_kb_id))
    if description is not None:
        sets.append("description = ?")
        params.append(description)
    if structure is not None:
        sets.append("structure_json = ?")
        params.append(json.dumps(structure, ensure_ascii=False))
    if status is not None:
        if status not in _HANDBOOK_STATUS:
            raise ValueError(f"非法 handbook status: {status}")
        sets.append("status = ?")
        params.append(status)
    if extraction_log is not None:
        sets.append("extraction_log = ?")
        params.append(extraction_log)
    if bump_version:
        sets.append("version_no = version_no + 1")
    if not sets:
        return get_handbook(conn, handbook_id)
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(handbook_id)
    with conn:
        conn.execute(
            f"UPDATE product_handbooks SET {', '.join(sets)} WHERE id = ?",
            params,
        )
    return get_handbook(conn, handbook_id)


def delete_handbook(conn: sqlite3.Connection, handbook_id: int) -> bool:
    """删除 handbook（级联 handbook_files / analysis_jobs / turn_classifications）。"""
    with conn:
        cur = conn.execute(
            "DELETE FROM product_handbooks WHERE id = ?", (handbook_id,)
        )
    return cur.rowcount > 0


def list_handbook_files(
    conn: sqlite3.Connection, handbook_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM handbook_files WHERE handbook_id = ? ORDER BY id ASC",
        (handbook_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_handbook_file(
    conn: sqlite3.Connection, file_id: int
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM handbook_files WHERE id = ?", (file_id,)
    ).fetchone()
    return dict(row) if row else None


def create_handbook_file(
    conn: sqlite3.Connection,
    *,
    handbook_id: int,
    filename: str,
    file_path: str,
    file_type: Optional[str] = None,
    file_size: Optional[int] = None,
    parsed_text: Optional[str] = None,
    status: str = "pending",
) -> int:
    if status not in _HANDBOOK_FILE_STATUS:
        raise ValueError(f"非法 handbook_file status: {status}")
    now = _now_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO handbook_files (
                handbook_id, filename, file_path, file_type, file_size,
                parsed_text, status, error_msg, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (handbook_id, filename, file_path, file_type, file_size,
             parsed_text, status, now, now),
        )
    return int(cur.lastrowid)


def update_handbook_file(
    conn: sqlite3.Connection,
    file_id: int,
    *,
    parsed_text: Optional[str] = None,
    status: Optional[str] = None,
    error_msg: Optional[str] = None,
) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if parsed_text is not None:
        sets.append("parsed_text = ?")
        params.append(parsed_text)
    if status is not None:
        if status not in _HANDBOOK_FILE_STATUS:
            raise ValueError(f"非法 handbook_file status: {status}")
        sets.append("status = ?")
        params.append(status)
    if error_msg is not None:
        sets.append("error_msg = ?")
        params.append(error_msg)
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(file_id)
    with conn:
        conn.execute(
            f"UPDATE handbook_files SET {', '.join(sets)} WHERE id = ?",
            params,
        )


def delete_handbook_file(conn: sqlite3.Connection, file_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM handbook_files WHERE id = ?", (file_id,))
    return cur.rowcount > 0


# ---------- analysis_jobs CRUD（Sprint 1 仅占位最小版，Sprint 2 完善） ----------

def create_analysis_job(
    conn: sqlite3.Connection,
    *,
    batch_id: Optional[int] = None,
    session_id: Optional[str] = None,
    handbook_id: Optional[int] = None,
) -> int:
    """创建分析任务（v2：batch / session 二选一，handbook 可空，自动套默认）。"""
    if not batch_id and not session_id:
        raise ValueError("create_analysis_job: 必须提供 batch_id 或 session_id 之一")
    if batch_id and session_id:
        raise ValueError("create_analysis_job: batch_id 与 session_id 互斥")
    if handbook_id is None:
        # 兜底：尝试套用默认 ready Handbook（用户决策 4 自动套用）
        try:
            handbook_id = resolve_default_handbook_id(conn)
        except Exception:
            handbook_id = None
    now = _now_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO analysis_jobs (
                batch_id, session_id, handbook_id, status, progress, total_turns,
                classified_turns, summary_json, error_msg,
                started_at, ended_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'pending', 0.0, 0, 0, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (batch_id, session_id, handbook_id, now, now),
        )
    return int(cur.lastrowid)


def get_analysis_job(
    conn: sqlite3.Connection, job_id: int
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return dict(row) if row else None


def list_analysis_jobs(
    conn: sqlite3.Connection,
    *,
    batch_id: Optional[int] = None,
    session_id: Optional[str] = None,
    handbook_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if batch_id is not None:
        where.append("batch_id = ?")
        params.append(int(batch_id))
    if session_id is not None:
        where.append("session_id = ?")
        params.append(session_id)
    if handbook_id is not None:
        where.append("handbook_id = ?")
        params.append(int(handbook_id))
    if status is not None:
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM analysis_jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_analysis_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    total_turns: Optional[int] = None,
    classified_turns: Optional[int] = None,
    summary: Optional[dict[str, Any]] = None,
    error_msg: Optional[str] = None,
    mark_started: bool = False,
    mark_ended: bool = False,
) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if status is not None:
        if status not in _ANALYSIS_JOB_STATUS:
            raise ValueError(f"非法 analysis_job status: {status}")
        sets.append("status = ?")
        params.append(status)
    if progress is not None:
        sets.append("progress = ?")
        params.append(float(max(0.0, min(1.0, progress))))
    if total_turns is not None:
        sets.append("total_turns = ?")
        params.append(int(total_turns))
    if classified_turns is not None:
        sets.append("classified_turns = ?")
        params.append(int(classified_turns))
    if summary is not None:
        sets.append("summary_json = ?")
        params.append(json.dumps(summary, ensure_ascii=False))
    if error_msg is not None:
        sets.append("error_msg = ?")
        params.append(error_msg)
    if mark_started:
        sets.append("started_at = ?")
        params.append(_now_iso())
    if mark_ended:
        sets.append("ended_at = ?")
        params.append(_now_iso())
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(job_id)
    with conn:
        conn.execute(
            f"UPDATE analysis_jobs SET {', '.join(sets)} WHERE id = ?",
            params,
        )


def delete_analysis_job(conn: sqlite3.Connection, job_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM analysis_jobs WHERE id = ?", (job_id,))
    return cur.rowcount > 0


# ---------- turn_classifications CRUD（Sprint 2 主用） ----------

def insert_turn_classifications(
    conn: sqlite3.Connection,
    job_id: int,
    rows: list[dict[str, Any]],
) -> int:
    """批量插入分类结果（多标签每条 turn 可能多行）。

    rows 每条形如:
      {
        "session_id": "sess_xxx",
        "turn_idx": 5,
        "category_id": "sell_2",
        "confidence": 0.85,
        "scores": {"spec_veracity": 8, ...},
        "issues": ["未引用 NearLink 键盘"],
        "suggestion": "...",
        "reference_text": "...",
      }
    """
    if not rows:
        return 0
    now = _now_iso()
    payload = [
        (
            job_id,
            r["session_id"],
            int(r["turn_idx"]),
            r["category_id"],
            float(r.get("confidence") or 0.0),
            json.dumps(r.get("scores") or {}, ensure_ascii=False),
            json.dumps(r.get("issues") or [], ensure_ascii=False),
            r.get("suggestion") or "",
            r.get("reference_text") or "",
            now,
        )
        for r in rows
    ]
    with conn:
        conn.executemany(
            """
            INSERT INTO turn_classifications (
                analysis_job_id, session_id, turn_idx, category_id, confidence,
                scores_json, issues_json, suggestion, reference_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    return len(payload)


def list_turn_classifications(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    category_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM turn_classifications WHERE analysis_job_id = ?"
    params: list[Any] = [job_id]
    if category_id:
        sql += " AND category_id = ?"
        params.append(category_id)
    sql += " ORDER BY confidence DESC, id ASC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def delete_turn_classifications(
    conn: sqlite3.Connection, job_id: int
) -> int:
    """重跑前清空旧记录。"""
    with conn:
        cur = conn.execute(
            "DELETE FROM turn_classifications WHERE analysis_job_id = ?",
            (job_id,),
        )
    return cur.rowcount


# ---------- analysis_persona_insights CRUD（Sprint 2 报告聚合用） ----------

def insert_analysis_persona_insights(
    conn: sqlite3.Connection,
    job_id: int,
    rows: list[dict[str, Any]],
) -> int:
    """批量写入 persona 维度洞察。
    每条 row:
      {
        "persona_id": int | None,
        "persona_cluster": str | None,
        "top_concerns": [str, ...],
        "sample_objections": [str, ...],
        "deal_rate": float | None,
        "avg_quality": float | None,
      }
    """
    if not rows:
        return 0
    now = _now_iso()
    payload = [
        (
            job_id,
            r.get("persona_id"),
            r.get("persona_cluster"),
            json.dumps(r.get("top_concerns") or [], ensure_ascii=False),
            json.dumps(r.get("sample_objections") or [], ensure_ascii=False),
            r.get("deal_rate"),
            r.get("avg_quality"),
            now,
        )
        for r in rows
    ]
    with conn:
        conn.executemany(
            """
            INSERT INTO analysis_persona_insights (
                analysis_job_id, persona_id, persona_cluster,
                top_concerns_json, sample_objections_json,
                deal_rate, avg_quality, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    return len(payload)


def list_analysis_persona_insights(
    conn: sqlite3.Connection, job_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM analysis_persona_insights "
        "WHERE analysis_job_id = ? ORDER BY id ASC",
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_analysis_persona_insights(
    conn: sqlite3.Connection, job_id: int
) -> int:
    with conn:
        cur = conn.execute(
            "DELETE FROM analysis_persona_insights WHERE analysis_job_id = ?",
            (job_id,),
        )
    return cur.rowcount
