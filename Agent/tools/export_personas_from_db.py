"""把上游 SQLite 里的人设一次性导出成 Agent/personas/*.yaml。

跑一次就够。跑完之后 `Agent/personas/` 就是全量对抗的唯一人设来源，
执行链路不再碰数据库，整个 Agent/ 目录可以拷到任何机器上离线跑。

这是**唯一**会连数据库的脚本，而且只读。它故意不走 shared/bootstrap，
因为 bootstrap 会把 `src.storage.db` 换成文件后端的假模块 —— 那正是
这个脚本要绕开的东西。

用法：
    python tools/export_personas_from_db.py                 # 全量导出
    python tools/export_personas_from_db.py --tag 学生       # 只导某个标签
    python tools/export_personas_from_db.py --limit 5        # 先导 5 个看看
    python tools/export_personas_from_db.py --clean          # 导出前清空目标目录
    python tools/export_personas_from_db.py --db D:/x/conversations.db
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

AGENT_ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_ROOT = AGENT_ROOT.parent
PERSONAS_DIR = AGENT_ROOT / "personas"

_SAFE = str.maketrans({c: "_" for c in ':*?"<>|/\\ '})


def _safe_stem(text: str, limit: int = 48) -> str:
    return (text or "persona").translate(_SAFE).strip("_")[:limit] or "persona"


def _to_yaml_dict(p: Any, db_id: int) -> dict[str, Any]:
    """PersonaProfile → 干净的 YAML 结构。

    id 从上游的 `db:<n>` 改写成 `db_<n:04d>`：冒号在 Windows 上不能做文件名，
    而人设 id 会被用作会话目录名前缀；补零是为了目录列表按序号自然排序。
    """
    data: dict[str, Any] = {
        "id": f"db_{db_id:04d}",
        "name": p.name,
        "format_type": p.format_type,
    }
    for key in ("age", "occupation", "budget", "personality", "objection_style", "purchase_goal"):
        val = getattr(p, key, None)
        if val not in (None, ""):
            data[key] = val
    if p.pain_points:
        data["pain_points"] = list(p.pain_points)
    if p.prompt_text:
        data["prompt_text"] = p.prompt_text
    if p.tags:
        data["tags"] = list(p.tags)
    if p.locale:
        data["locale"] = p.locale
    if p.source:
        data["source"] = p.source
    for key in ("country_code", "country_name", "currency"):
        val = getattr(p, key, None)
        if val:
            data[key] = val
    if getattr(p, "market_domains", None):
        data["market_domains"] = list(p.market_domains)
    data["pressure_profile"] = p.pressure_profile.model_dump()
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="从上游 SQLite 一次性导出人设快照")
    ap.add_argument("--db", default=None, help="conversations.db 路径，缺省用上游默认位置")
    ap.add_argument("--tag", default=None, help="只导带该标签的人设")
    ap.add_argument("--format-type", choices=["structured", "prompt_based"], default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--clean", action="store_true", help="导出前清空 personas/ 里已有的 yaml")
    ap.add_argument("--out", default=str(PERSONAS_DIR), help="输出目录")
    args = ap.parse_args()

    if not (UPSTREAM_ROOT / "src" / "storage" / "db.py").is_file():
        print(f"找不到上游 src/storage/db.py（在 {UPSTREAM_ROOT}）。")
        print("这个脚本只能在有上游仓库的机器上跑。")
        return 2

    sys.path.insert(0, str(UPSTREAM_ROOT))
    import yaml

    from src.persona.loader import persona_from_db_row
    from src.storage import db as sdb

    conn = sdb.get_connection(Path(args.db) if args.db else None)
    try:
        rows = sdb.list_personas(
            conn, format_type=args.format_type, tag=args.tag, limit=args.limit
        )
    finally:
        conn.close()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.clean:
        removed = 0
        for old in out_dir.glob("*.yaml"):
            old.unlink()
            removed += 1
        print(f"已清空 {removed} 个旧 yaml")

    written, failed = 0, 0
    for row in rows:
        try:
            profile = persona_from_db_row(row)
            data = _to_yaml_dict(profile, int(row["id"]))
        except Exception as exc:  # noqa: BLE001
            print(f"  [跳过] id={row.get('id')} {row.get('name')}: {type(exc).__name__}: {exc}")
            failed += 1
            continue
        path = out_dir / f"db_{row['id']:04d}__{_safe_stem(profile.name)}.yaml"
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        written += 1

    print(f"\n导出完成：{written} 个人设 → {out_dir}")
    if failed:
        print(f"跳过 {failed} 个（原因见上方）")
    print("接下来：python run_all.py --dry-run --limit 2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
