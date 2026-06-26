"""持久层：SQLite 连接、schema、迁移。

不直接对外暴露 sqlite3 API；上层只使用 db.py 中的函数。
"""
