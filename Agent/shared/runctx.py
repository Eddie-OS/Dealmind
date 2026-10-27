"""一次执行（run）的目录布局与断点续跑账本。

目录长这样，所有中间态和结果都是文件，没有任何隐藏状态：

    runs/<run_id>/
      RUN_LOG.md                  主时间线，边跑边追加，可以 tail 着看
      EXEC_SUMMARY.md             一页执行摘要（收尾时写）
      manifest.json               断点账本，决定重跑时补哪几场
      01_handbook/                手册解析产物
      02_personas/                本次参战人设清单
      sessions/<persona_id>/      每个人设一场对练的全部产物
        steps/<agent_key>/*.md    会话内每个 agent 每一步的输入输出
      steps/<agent_key>/*.md      会话外 agent（解析/提炼/分析/汇总）的每一步
      reports/                    跨人设的最终报告

断点续跑的判定单位是"一个人设一场会话"。manifest 里每个人设只有
done / failed / pending 三态；重跑同一个 run_id 时只补非 done 的。
不做更细粒度（比如续跑到第 7 轮）—— 半场会话的上下文没法可靠恢复，
硬续只会产出看起来完整实则断裂的对话。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Optional

AGENT_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = AGENT_ROOT / "runs"

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+")


def safe_name(text: str, *, fallback: str = "unnamed", limit: int = 60) -> str:
    """把任意字符串压成可做文件名的形式（保留中文）。"""
    cleaned = _SAFE_NAME_RE.sub("_", (text or "").strip()).strip("_")
    return (cleaned or fallback)[:limit]


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class RunContext:
    run_id: str
    root: Path
    dry_run: bool = False
    manifest: dict[str, Any] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    # ── 目录 ──────────────────────────────────────────────────────────

    @property
    def handbook_dir(self) -> Path:
        return self._ensure(self.root / "01_handbook")

    @property
    def personas_dir(self) -> Path:
        return self._ensure(self.root / "02_personas")

    @property
    def sessions_dir(self) -> Path:
        return self._ensure(self.root / "sessions")

    @property
    def reports_dir(self) -> Path:
        return self._ensure(self.root / "reports")

    @property
    def steps_dir(self) -> Path:
        return self._ensure(self.root / "steps")

    @property
    def run_log_path(self) -> Path:
        return self.root / "RUN_LOG.md"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def session_dir(self, persona_id: str, label: str | None = None) -> Path:
        """会话目录 = `<persona_id>__<人设名>`。

        id 在前保证唯一和续跑时可复现，名字在后是为了人能直接翻目录找到人。
        续跑匹配走 manifest 里的 persona_id，不依赖目录名。
        """
        name = safe_name(persona_id, limit=40)
        if label:
            name = f"{name}__{safe_name(label, limit=30)}"
        return self._ensure(self.sessions_dir / name)

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ── 生命周期 ──────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        *,
        run_id: Optional[str] = None,
        dry_run: bool = False,
        topic: str = "",
        source_handbook: str = "",
    ) -> "RunContext":
        rid = run_id or new_run_id("dryrun" if dry_run else "run")
        root = RUNS_ROOT / rid
        root.mkdir(parents=True, exist_ok=True)
        ctx = cls(run_id=rid, root=root, dry_run=dry_run)

        if ctx.manifest_path.is_file():
            ctx.manifest = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
            ctx.manifest["resumed_at"] = _now()
            ctx.manifest["resume_count"] = int(ctx.manifest.get("resume_count", 0)) + 1
        else:
            ctx.manifest = {
                "run_id": rid,
                "created_at": _now(),
                "dry_run": dry_run,
                "topic": topic,
                "source_handbook": source_handbook,
                "resume_count": 0,
                "stages": {},
                "personas": {},
            }
        ctx.save_manifest()
        return ctx

    @classmethod
    def load(cls, run_id: str) -> "RunContext":
        root = RUNS_ROOT / run_id
        if not (root / "manifest.json").is_file():
            raise FileNotFoundError(f"找不到 run：{root}")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        return cls(
            run_id=run_id,
            root=root,
            dry_run=bool(manifest.get("dry_run")),
            manifest=manifest,
        )

    @staticmethod
    def latest_run_id() -> Optional[str]:
        if not RUNS_ROOT.is_dir():
            return None
        candidates = [
            p.name for p in RUNS_ROOT.iterdir() if (p / "manifest.json").is_file()
        ]
        return sorted(candidates)[-1] if candidates else None

    # ── 账本 ──────────────────────────────────────────────────────────

    def save_manifest(self) -> None:
        """先写临时文件再替换，避免中断时留下半截 JSON 导致续跑失败。"""
        with self._lock:
            tmp = self.manifest_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, self.manifest_path)

    def set_stage(self, key: str, status: str, **extra: Any) -> None:
        self.manifest.setdefault("stages", {})[key] = {
            "status": status,
            "updated_at": _now(),
            **extra,
        }
        self.save_manifest()

    def stage_status(self, key: str) -> str:
        return (self.manifest.get("stages", {}).get(key) or {}).get("status", "pending")

    def register_personas(self, persona_ids: list[str]) -> None:
        book = self.manifest.setdefault("personas", {})
        for pid in persona_ids:
            book.setdefault(pid, {"status": "pending"})
        self.save_manifest()

    def mark_persona(self, persona_id: str, status: str, **extra: Any) -> None:
        book = self.manifest.setdefault("personas", {})
        entry = book.setdefault(persona_id, {})
        entry.update({"status": status, "updated_at": _now(), **extra})
        self.save_manifest()

    def persona_status(self, persona_id: str) -> str:
        return (self.manifest.get("personas", {}).get(persona_id) or {}).get(
            "status", "pending"
        )

    def pending_personas(self, all_ids: list[str]) -> list[str]:
        return [pid for pid in all_ids if self.persona_status(pid) != "done"]

    def done_personas(self) -> list[str]:
        return [
            pid
            for pid, e in (self.manifest.get("personas") or {}).items()
            if e.get("status") == "done"
        ]

    def failed_personas(self) -> list[tuple[str, str]]:
        return [
            (pid, str(e.get("error") or ""))
            for pid, e in (self.manifest.get("personas") or {}).items()
            if e.get("status") == "failed"
        ]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
