"""把上游 src/ 的引擎文件物理复制进 Agent/shared/vendor/。

为什么是"复制"而不是"import 上游"：
    Agent/ 目录必须能被整个搬走、扔到任何一台机器上直接跑，不依赖
    F:/Langraph/src 是否存在。所以这里做真实的文件复制，复制后
    Agent/shared/vendor/ 是一份完整可运行的引擎快照。

为什么复制时保留 src/ 包名：
    被复制的文件内部大量 `from src.xxx import yyy`。保留 `vendor/src/`
    的包结构后，把 vendor/ 加进 sys.path 即可让这些 import 原样成立，
    不需要改写任何一行 vendored 代码（改写 = 埋 bug）。

哪些文件**故意不复制**：
    storage/  rag/kb_store  api/  tools/  batch/  research/  cases/
    这些是 SQLite / Chroma / FastAPI 相关的重依赖。Agent 侧由
    shared/dbfakes.py 注入同名的文件后端假模块顶替，见该文件说明。

用法：
    python shared/vendor_sync.py            # 复制（覆盖）
    python shared/vendor_sync.py --check    # 只检查漂移，不写文件
    python shared/vendor_sync.py --src-root D:/other/repo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_ROOT = AGENT_ROOT / "shared" / "vendor"
MANIFEST_PATH = VENDOR_ROOT / "VENDOR_MANIFEST.json"

# ── 复制清单 ──────────────────────────────────────────────────────────
# 已逐个核对过模块级 import 闭包：下列文件互相之间自洽，
# 对 storage / rag.kb_store / research / tools 的引用全部是函数内惰性 import。

SRC_MODULES = [
    # 基础设施
    "schema.py",
    "utils.py",
    "lang.py",
    "locales.py",
    "safe_console.py",
    "config.py",
    "llm.py",
    "perf_config.py",
    # 业务阶段机
    "business_stages.py",
    "stage_quota.py",
    # 五个对练 agent 的实现体
    "agents.py",
    "judge.py",
    "memory.py",
    "coach.py",
    "session.py",
    # 事实护栏与产出
    "content_guard.py",
    "preflight.py",
    "output_writer.py",
    "loaders.py",
]

ANALYZER_MODULES = [
    "handbook_extractor.py",
    "handbook_classifier.py",
    "handbook_scorer.py",
    "handbook_turn_analyzer.py",
    "excellence_scorer.py",
    "methodology.py",
    "objection_cluster.py",
]

RAG_MODULES = ["parsers.py"]

PERSONA_MODULES = ["parser.py", "loader.py"]

# prompts/ 整个目录复制（含 business_stages.yaml）。
# vendored config.PROJECT_ROOT 会解析到 vendor/，所以 prompts 必须落在 vendor/prompts。
PROMPT_GLOBS = ["*.md", "*.yaml"]

# 包 __init__.py 用极简 stub 而非复制上游：
# 上游的 __init__ 会 re-export kb_store / generator 等带重依赖的符号。
PACKAGE_STUBS = {
    "src/__init__.py": '"""DealMind 引擎（vendored 快照，由 shared/vendor_sync.py 生成）。"""\n',
    "src/analyzers/__init__.py": '"""分析器（vendored 快照）。上游 __init__ 的 re-export 已裁掉。"""\n',
    "src/rag/__init__.py": '"""解析器（vendored 快照）。kb_store 由 shared/dbfakes.py 顶替。"""\n',
    "src/persona/__init__.py": '"""人设解析（vendored 快照）。"""\n',
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(src_root: Path) -> list[tuple[Path, Path]]:
    """返回 [(源文件, vendor 目标文件)] 清单。"""
    pairs: list[tuple[Path, Path]] = []
    for name in SRC_MODULES:
        pairs.append((src_root / "src" / name, VENDOR_ROOT / "src" / name))
    for name in ANALYZER_MODULES:
        pairs.append(
            (src_root / "src" / "analyzers" / name, VENDOR_ROOT / "src" / "analyzers" / name)
        )
    for name in RAG_MODULES:
        pairs.append((src_root / "src" / "rag" / name, VENDOR_ROOT / "src" / "rag" / name))
    for name in PERSONA_MODULES:
        pairs.append(
            (src_root / "src" / "persona" / name, VENDOR_ROOT / "src" / "persona" / name)
        )
    prompts_dir = src_root / "prompts"
    if prompts_dir.is_dir():
        for pattern in PROMPT_GLOBS:
            for p in sorted(prompts_dir.glob(pattern)):
                pairs.append((p, VENDOR_ROOT / "prompts" / p.name))
    return pairs


def sync(src_root: Path, *, check_only: bool = False) -> int:
    pairs = _plan(src_root)

    missing = [str(s) for s, _ in pairs if not s.is_file()]
    if missing:
        print(f"[vendor_sync] 源文件缺失 {len(missing)} 个，无法同步：")
        for m in missing[:10]:
            print(f"  - {m}")
        return 2

    if check_only:
        drift: list[str] = []
        for s, d in pairs:
            if not d.is_file():
                drift.append(f"缺失  {d.relative_to(VENDOR_ROOT)}")
            elif _sha256(s) != _sha256(d):
                drift.append(f"漂移  {d.relative_to(VENDOR_ROOT)}")
        if drift:
            print(f"[vendor_sync] 与上游有 {len(drift)} 处差异：")
            for line in drift:
                print(f"  {line}")
            return 1
        print(f"[vendor_sync] vendor 与上游一致（{len(pairs)} 个文件）。")
        return 0

    entries: list[dict] = []
    for s, d in pairs:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        entries.append(
            {
                "vendor_path": str(d.relative_to(VENDOR_ROOT)).replace("\\", "/"),
                "source_path": str(s).replace("\\", "/"),
                "sha256": _sha256(d),
                "bytes": d.stat().st_size,
            }
        )

    for rel, body in PACKAGE_STUBS.items():
        target = VENDOR_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        entries.append(
            {
                "vendor_path": rel,
                "source_path": "(stub generated by vendor_sync.py)",
                "sha256": _sha256(target),
                "bytes": target.stat().st_size,
            }
        )

    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source_root": str(src_root).replace("\\", "/"),
                "file_count": len(entries),
                "files": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[vendor_sync] 已复制 {len(entries)} 个文件到 {VENDOR_ROOT}")
    return 0


def ensure_vendored(src_root: Path | None = None) -> None:
    """被 bootstrap 调用：vendor 不存在时自动做一次复制。"""
    if (VENDOR_ROOT / "src" / "session.py").is_file():
        return
    root = src_root or AGENT_ROOT.parent
    if not (root / "src" / "session.py").is_file():
        raise RuntimeError(
            f"vendor/ 尚未生成，且在 {root} 找不到上游 src/。\n"
            f"请先在有上游仓库的机器上跑一次：python shared/vendor_sync.py"
        )
    sync(root)


def main() -> int:
    ap = argparse.ArgumentParser(description="同步上游 src/ 到 Agent/shared/vendor/")
    ap.add_argument("--src-root", default=str(AGENT_ROOT.parent), help="上游仓库根目录")
    ap.add_argument("--check", action="store_true", help="只检查漂移，不写文件")
    args = ap.parse_args()
    return sync(Path(args.src_root).resolve(), check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
