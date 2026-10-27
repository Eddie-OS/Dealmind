"""02 · 人设管理 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402
from shared.runctx import RunContext  # noqa: E402
from shared.trace import Tracer  # noqa: E402

AGENT_KEY = "02_persona_curator"


def _load_one(path: Path) -> tuple[list[Any], list[str]]:
    """返回 (PersonaProfile 列表, 错误说明列表)。一个文件可能含多个人设。"""
    from src.loaders import load_persona_yaml
    from src.schema import PersonaProfile

    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            return [load_persona_yaml(path)], []
        if suffix == ".json":
            from src.persona.parser import parse_persona_file

            rows = parse_persona_file(path)
            out, errs = [], []
            for row in rows:
                try:
                    out.append(PersonaProfile.model_validate(row))
                except Exception as exc:  # noqa: BLE001
                    errs.append(f"{path.name} 内一条人设校验失败：{exc}")
            return out, errs
    except Exception as exc:  # noqa: BLE001
        return [], [f"{path.name}: {type(exc).__name__}: {exc}"]
    return [], [f"{path.name}: 不支持的后缀 {suffix}"]


def _passes_filters(p: Any, filters: dict[str, Any]) -> tuple[bool, str]:
    include_tags = [t for t in (filters.get("include_tags") or []) if t]
    exclude_ids = set(filters.get("exclude_ids") or [])
    if p.id in exclude_ids:
        return False, "命中 exclude_ids"
    if include_tags and not (set(getattr(p, "tags", []) or []) & set(include_tags)):
        return False, f"标签不含 {include_tags}"
    return True, ""


def _render_md(selected: list[Any], excluded: list[tuple[str, str]], source_dir: Path) -> str:
    lines = [
        "# 本次参战人设花名册",
        "",
        f"- 来源目录：`{source_dir}`",
        f"- 参战：**{len(selected)}** 个　排除：{len(excluded)} 个",
        "",
        "## 参战名单",
        "",
        "| # | id | 姓名 | 年龄 | 职业 | 预算 | 异议风格 | 价格敏感 | 议价强度 | 耐心 |",
        "|---|----|------|------|------|------|----------|----------|----------|------|",
    ]
    for i, p in enumerate(selected, 1):
        pp = p.pressure_profile
        lines.append(
            f"| {i} | `{p.id}` | {p.name} | {p.age or '-'} | {p.occupation or '-'} | "
            f"{p.budget or '-'} | {(p.objection_style or '-')[:30]} | "
            f"{pp.price_sensitivity} | {pp.bargaining_aggressiveness} | {pp.patience} |"
        )
    lines.append("")

    if excluded:
        lines += ["## 被排除", "", "| 人设 | 原因 |", "|------|------|"]
        lines += [f"| `{pid}` | {reason} |" for pid, reason in excluded]
        lines.append("")

    lines += ["## 压力画像明细", ""]
    for p in selected:
        lines.append(f"### {p.name}（`{p.id}`）")
        lines.append("")
        lines.append(f"- 痛点：{'；'.join(p.pain_points) if p.pain_points else '（未填）'}")
        lines.append(f"- 购买目标：{p.purchase_goal or '（未填）'}")
        lines.append(f"- 性格：{p.personality or '（未填）'}")
        lines.append(f"- 压力参数：`{p.pressure_profile.summary()}`")
        lines.append("")
    return "\n".join(lines)


def curate(ctx: RunContext, cfg: dict[str, Any]) -> list[Any]:
    """主入口。返回本次参战的 PersonaProfile 列表，并登记进 manifest。"""
    tracer = Tracer(ctx, AGENT_KEY)
    pcfg = cfg.get("personas") or {}
    source_dir = Path(pcfg.get("source_dir") or "personas")
    if not source_dir.is_absolute():
        source_dir = bootstrap.AGENT_ROOT / source_dir

    files = sorted(
        p
        for p in (source_dir.iterdir() if source_dir.is_dir() else [])
        if p.is_file() and p.suffix.lower() in {".yaml", ".yml", ".json"}
    )
    tracer.log(f"扫描 `{source_dir.name}/`，发现 {len(files)} 个人设文件")

    loaded: list[Any] = []
    excluded: list[tuple[str, str]] = []
    seen: set[str] = set()

    for path in files:
        profiles, errs = _load_one(path)
        for msg in errs:
            excluded.append((path.name, msg))
        for p in profiles:
            if p.id in seen:
                excluded.append((p.id, f"id 重复（来自 {path.name}）"))
                continue
            seen.add(p.id)
            loaded.append(p)

    selected: list[Any] = []
    for p in loaded:
        ok, reason = _passes_filters(p, pcfg)
        (selected if ok else excluded).append(p if ok else (p.id, reason))

    limit = pcfg.get("limit")
    if limit:
        cut = selected[int(limit) :]
        selected = selected[: int(limit)]
        excluded += [(p.id, f"超出 limit={limit}") for p in cut]

    tracer.step(
        "curate",
        title="人设加载与筛选",
        summary={
            "扫描文件": len(files),
            "解析成功": len(loaded),
            "参战": len(selected),
            "排除": len(excluded),
        },
        inputs={
            "source_dir": str(source_dir),
            "include_tags": pcfg.get("include_tags") or [],
            "exclude_ids": pcfg.get("exclude_ids") or [],
            "limit": pcfg.get("limit"),
        },
        output_md="\n".join(f"- `{p.id}` {p.name}" for p in selected) or "_（无）_",
    )

    (ctx.personas_dir / "personas.json").write_text(
        json.dumps([p.model_dump() for p in selected], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ctx.personas_dir / "personas.md").write_text(
        _render_md(selected, excluded, source_dir), encoding="utf-8"
    )

    ctx.register_personas([p.id for p in selected])
    ctx.set_stage(AGENT_KEY, "done", selected=len(selected), excluded=len(excluded))
    tracer.log(f"参战 **{len(selected)}** 个人设，排除 {len(excluded)} 个", level="ok")
    return selected


def main() -> int:
    ap = argparse.ArgumentParser(description="加载并筛选本次参战人设")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--list", action="store_true", help="只打印名单，不落文件")
    args = ap.parse_args()

    bootstrap.init()
    import yaml

    cfg = yaml.safe_load((bootstrap.AGENT_ROOT / "config" / "pipeline.yaml").read_text("utf-8"))

    if args.list:
        pcfg = cfg.get("personas") or {}
        d = bootstrap.AGENT_ROOT / (pcfg.get("source_dir") or "personas")
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in {".yaml", ".yml", ".json"})
        for path in files:
            profiles, errs = _load_one(path)
            for p in profiles:
                print(f"  {p.id:<32} {p.name}")
            for e in errs:
                print(f"  [跳过] {e}")
        print(f"合计 {len(files)} 个文件")
        return 0

    rid = args.run_id or RunContext.latest_run_id()
    ctx = (
        RunContext.load(rid)
        if rid and (bootstrap.AGENT_ROOT / "runs" / rid / "manifest.json").is_file()
        else RunContext.create()
    )
    selected = curate(ctx, cfg)
    print(f"[{AGENT_KEY}] run={ctx.run_id} 参战 {len(selected)} 个人设")
    print(f"  → {ctx.personas_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
