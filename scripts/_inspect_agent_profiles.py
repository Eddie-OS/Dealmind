import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)
from src.storage import db as sdb
with sdb.connection_scope() as conn:
    for r in conn.execute("PRAGMA table_info('agent_profiles')").fetchall():
        print(dict(r))
    print()
    for r in conn.execute("SELECT * FROM agent_profiles").fetchall():
        d = dict(r)
        d["system_prompt"] = (d.get("system_prompt") or "")[:50] + "..."
        print(d)
