"""把每个 agent 的每一步输入输出落成 MD。

这是"放在任何执行软件上都能看到各环节输出"的实现方式：不依赖任何
观测平台、不依赖数据库、不依赖前端，就是磁盘上一棵 MD 树。用记事本、
VS Code、Obsidian、GitHub 网页、手机上的任意 markdown 阅读器都能读。

两层输出：
    RUN_LOG.md   —— 主时间线，边跑边追加。想知道"现在跑到哪了"看这个。
    步骤 MD      —— 单步的完整输入输出。想知道"这一步为什么这样"看这个。

RUN_LOG 的追加带进程内锁：低并发跑批时多个会话线程会同时写。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from shared.runctx import RunContext, safe_name

_log_lock = Lock()


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def md_kv_table(data: dict[str, Any], *, limit: int = 400) -> str:
    """把扁平 dict 渲染成两列表格。值过长时截断并标注。"""
    if not data:
        return "_（无）_"
    lines = ["| 字段 | 值 |", "|------|-----|"]
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            text = json.dumps(v, ensure_ascii=False)
        else:
            text = str(v)
        text = text.replace("\n", " ").replace("|", "\\|")
        if len(text) > limit:
            text = text[:limit] + f"… _(共 {len(text)} 字，已截断)_"
        lines.append(f"| {k} | {text} |")
    return "\n".join(lines)


def md_json_block(data: Any, *, limit: int = 8000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    truncated = len(text) > limit
    if truncated:
        text = text[:limit] + "\n… (已截断)"
    return f"```json\n{text}\n```"


class Tracer:
    """一个 agent 在一次 run 里的 MD 追踪器。

    scope_dir 给定时（会话内 agent），步骤 MD 落在
    ``sessions/<persona>/steps/<agent_key>/``；否则落在 ``steps/<agent_key>/``。
    """

    def __init__(
        self,
        ctx: RunContext,
        agent_key: str,
        *,
        scope_dir: Optional[Path] = None,
    ) -> None:
        self.ctx = ctx
        self.agent_key = agent_key
        base = scope_dir if scope_dir is not None else ctx.steps_dir
        self.dir = base / "steps" / agent_key if scope_dir is not None else base / agent_key
        self.dir.mkdir(parents=True, exist_ok=True)
        self._seq = 0

    # ── 主时间线 ──────────────────────────────────────────────────────

    def log(self, message: str, *, level: str = "info") -> None:
        icon = {"info": "·", "ok": "✓", "warn": "!", "error": "×"}.get(level, "·")
        line = f"- `{_now()}` **{self.agent_key}** {icon} {message}\n"
        with _log_lock:
            with self.ctx.run_log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    # ── 单步 MD ───────────────────────────────────────────────────────

    def step(
        self,
        name: str,
        *,
        title: str = "",
        summary: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        output_md: str = "",
        output_json: Any = None,
        also_log: bool = False,
    ) -> Path:
        """写一份步骤 MD，返回路径。

        name 用于文件名（会被清洗），title 用于 MD 一级标题。
        """
        self._seq += 1
        fname = f"{self._seq:03d}_{safe_name(name)}.md"
        path = self.dir / fname

        parts: list[str] = [
            f"# {title or name}",
            "",
            md_kv_table(
                {
                    "agent": self.agent_key,
                    "step": name,
                    "run_id": self.ctx.run_id,
                    "dry_run": self.ctx.dry_run,
                    "写入时间": datetime.now().astimezone().isoformat(timespec="seconds"),
                    **(summary or {}),
                }
            ),
            "",
        ]
        if inputs:
            parts += ["## 输入", "", md_kv_table(inputs), ""]
        if output_md:
            parts += ["## 输出", "", output_md, ""]
        if output_json is not None:
            parts += ["## 输出（结构化）", "", md_json_block(output_json), ""]

        path.write_text("\n".join(parts), encoding="utf-8")
        if also_log:
            self.log(f"{title or name} → `{path.relative_to(self.ctx.root)}`")
        return path


def write_run_log_header(ctx: RunContext, env: dict[str, Any], config: dict[str, Any]) -> None:
    """RUN_LOG.md 的抬头。续跑时追加一条分隔而不是覆盖。"""
    exists = ctx.run_log_path.is_file()
    with _log_lock:
        with ctx.run_log_path.open("a", encoding="utf-8") as fh:
            if exists:
                fh.write(f"\n\n---\n\n## 续跑 · {datetime.now().astimezone():%Y-%m-%d %H:%M:%S}\n\n")
            else:
                fh.write(f"# 执行日志 · {ctx.run_id}\n\n")
                fh.write("> 本文件边跑边追加，可以一直开着看进度。\n\n")
                fh.write("## 运行环境\n\n")
                fh.write(md_kv_table(env) + "\n\n")
                fh.write("## 本次配置\n\n")
                fh.write(md_kv_table(config) + "\n\n")
                fh.write("## 时间线\n\n")
