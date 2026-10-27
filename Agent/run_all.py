"""一键入口：跑一次全量模拟对抗。

    python run_all.py --dry-run          先用假模型验证链路（强烈建议第一次这样跑）
    python run_all.py --limit 2          真实跑，但只跑 2 个人设试水
    python run_all.py                    真实跑全量（会先让你确认预估调用量）
    python run_all.py --resume run_xxx   补跑上次失败的场次

只是 00_orchestrator/run.py 的转发器，参数完全一致。
放一个根目录入口是因为"把这个文件夹给别人，他第一眼要看到从哪开始跑"。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _orchestrator():
    path = ROOT / "00_orchestrator" / "run.py"
    spec = importlib.util.spec_from_file_location("orchestrator", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    sys.exit(_orchestrator().main())
