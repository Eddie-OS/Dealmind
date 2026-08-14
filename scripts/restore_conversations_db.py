"""从仓库内的 conversations.db.gz 恢复 SQLite 数据库。

GitHub 单文件上限 100MB，历史 conversations.db（约 107MB）以 gzip 形式入库。
克隆/拉取后在本机或服务器执行：

    python scripts/restore_conversations_db.py
"""
from __future__ import annotations

import gzip
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GZ = ROOT / "data" / "conversations.db.gz"
DB = ROOT / "data" / "conversations.db"


def main() -> int:
    if not GZ.exists():
        print(f"未找到 {GZ}，无需恢复。")
        return 0
    if DB.exists() and DB.stat().st_size > 0:
        print(f"{DB} 已存在（{DB.stat().st_size // 1024 // 1024} MB），跳过。")
        return 0
    DB.parent.mkdir(parents=True, exist_ok=True)
    print(f"解压 {GZ.name} → {DB.name} …")
    with gzip.open(GZ, "rb") as f_in, open(DB, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    print(f"完成：{DB}（{DB.stat().st_size // 1024 // 1024} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
