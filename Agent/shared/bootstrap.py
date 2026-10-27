"""每个 agent 的第一行都调 bootstrap.init()。

它保证四件事按正确顺序发生，顺序错了就会踩坑：

    1. Agent/ 进 sys.path      —— 让 `import shared.xxx` 成立
    2. vendor/ 就位并进 sys.path —— 让 `import src.xxx` 命中快照而非上游
    3. 假模块注册               —— 必须早于任何 vendored 模块被 import，
                                  否则 Python 会先去找真的 src.storage 然后失败
    4. .env 载入                —— 必须早于 vendored config/llm 读取环境变量

第 3 步和第 4 步都是"晚一步就无效"的操作，所以统一收在这里，
各 agent 不要自己去 import src.*。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_ROOT = AGENT_ROOT / "shared" / "vendor"
UPSTREAM_ROOT = AGENT_ROOT.parent

_initialized = False


def _load_env() -> str | None:
    """按优先级找 .env：Agent 自带 > 上游仓库根。返回实际载入的路径。"""
    from dotenv import load_dotenv

    for candidate in (AGENT_ROOT / ".env", UPSTREAM_ROOT / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return str(candidate)
    return None


def init(*, dry_run: bool | None = None) -> dict[str, object]:
    """幂等初始化。返回一份环境摘要，供各 agent 打进 MD 头部便于复核。

    dry_run 为 None 时读环境变量 AGENT_DRY_RUN（1/true/yes 视为开）。
    """
    global _initialized

    if str(AGENT_ROOT) not in sys.path:
        sys.path.insert(0, str(AGENT_ROOT))

    if not _initialized:
        from shared.vendor_sync import ensure_vendored

        ensure_vendored(UPSTREAM_ROOT)

    if str(VENDOR_ROOT) not in sys.path:
        sys.path.insert(0, str(VENDOR_ROOT))

    if not _initialized:
        from shared import dbfakes

        dbfakes.install()

    env_path = _load_env() if not _initialized else os.environ.get("_AGENT_ENV_FILE")
    if env_path:
        os.environ.setdefault("_AGENT_ENV_FILE", env_path)

    if dry_run is None:
        dry_run = str(os.environ.get("AGENT_DRY_RUN", "")).lower() in {"1", "true", "yes"}
    if dry_run:
        from shared import fake_llm

        fake_llm.install()
        os.environ["AGENT_DRY_RUN"] = "1"

    _initialized = True

    return {
        "agent_root": str(AGENT_ROOT),
        "vendor_root": str(VENDOR_ROOT),
        "env_file": env_path or "(未找到 .env，将完全依赖进程环境变量)",
        "dry_run": bool(dry_run),
        "python": sys.version.split()[0],
    }


def is_dry_run() -> bool:
    return str(os.environ.get("AGENT_DRY_RUN", "")).lower() in {"1", "true", "yes"}
