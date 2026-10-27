"""01 · 产品手册解析 Agent。契约见同目录 AGENT.md。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import bootstrap  # noqa: E402
from shared.runctx import RunContext  # noqa: E402
from shared.trace import Tracer, md_json_block  # noqa: E402

AGENT_KEY = "01_handbook_ingest"

_PARSABLE = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".markdown", ".txt"}


def _collect_inbox(inbox: Path) -> list[Path]:
    if not inbox.is_dir():
        return []
    return sorted(
        p
        for p in inbox.iterdir()
        if p.is_file() and (p.suffix.lower() in _PARSABLE or p.suffix.lower() == ".json")
    )


def _load_prebuilt(paths: list[Path]) -> dict[str, Any] | None:
    """inbox 里若已有结构化手册 JSON，直接用，跳过抽取。"""
    for p in paths:
        if p.suffix.lower() != ".json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        struct = data.get("structure_json") if "structure_json" in data else data
        if isinstance(struct, dict) and (
            struct.get("selling_points") or struct.get("doc_type") == "playbook_v1"
        ):
            return {
                "id": 1,
                "name": data.get("name") or struct.get("product_name") or p.stem,
                "version_no": int(data.get("version_no") or 1),
                "status": "ready",
                "structure_json": struct,
                "_source": str(p),
                "_prebuilt": True,
            }
    return None


def _parse_documents(paths: list[Path], tracer: Tracer) -> tuple[str, list[str]]:
    from src.rag.parsers import ParserError, parse_file

    texts: list[str] = []
    warnings: list[str] = []
    for p in paths:
        if p.suffix.lower() == ".json":
            continue
        try:
            chunks = parse_file(p)
        except ParserError as exc:
            warnings.append(f"{p.name}: 解析失败 {exc}")
            tracer.step(
                f"parse_{p.stem}",
                title=f"解析失败 · {p.name}",
                summary={"文件": p.name, "结果": "失败"},
                output_md=f"```\n{exc}\n```",
            )
            continue
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{p.name}: 解析异常 {type(exc).__name__}: {exc}")
            continue

        body = "\n\n".join(
            (f"## {c.get('section')}\n{c.get('text','')}" if c.get("section") else c.get("text", ""))
            for c in chunks
        ).strip()
        texts.append(f"# 来源文件：{p.name}\n\n{body}")
        tracer.step(
            f"parse_{p.stem}",
            title=f"解析 · {p.name}",
            summary={"文件": p.name, "切片数": len(chunks), "正文字数": len(body)},
            output_md=(body[:2000] + "\n\n… _(仅预览前 2000 字，完整正文见 raw_text.md)_")
            if len(body) > 2000
            else body,
        )
    return "\n\n---\n\n".join(texts), warnings


def _render_handbook_md(hb: dict[str, Any], warnings: list[str]) -> str:
    struct = hb.get("structure_json") or {}
    lines = [
        f"# 产品手册 · {hb.get('name')}",
        "",
        f"- 版本：v{hb.get('version_no')}　状态：{hb.get('status')}",
        f"- 来源：`{hb.get('_source', '(多文件合并)')}`",
        f"- 形态：{'playbook_v1' if struct.get('doc_type') == 'playbook_v1' else 'structured (1/3/3/5/9/10)'}",
        "",
    ]
    if warnings:
        lines += ["## 解析警告", ""] + [f"- {w}" for w in warnings] + [""]

    if struct.get("doc_type") == "playbook_v1":
        lines += ["## 结构化内容", "", md_json_block(struct)]
        return "\n".join(lines)

    intro = (struct.get("intro_1") or {}).get("text", "")
    if intro:
        lines += ["## 一句话定位", "", intro, ""]

    def _section(title: str, key: str, fmt) -> None:
        items = struct.get(key) or []
        lines.append(f"## {title}（{len(items)}）")
        lines.append("")
        if not items:
            lines.append("_（未抽取到）_")
        for i, it in enumerate(items, 1):
            lines.append(fmt(i, it))
        lines.append("")

    _section("核心卖点", "selling_points", lambda i, it: f"{i}. **{it.get('label','')}** — {it.get('text','')}")
    _section(
        "竞品差异",
        "competitor_points",
        lambda i, it: f"{i}. **{it.get('label','')}**"
        + (f"（vs {it.get('vs')}）" if it.get("vs") else "")
        + f" — {it.get('text','')}",
    )
    _section("核心参数", "core_params", lambda i, it: f"{i}. **{it.get('label','')}**：{it.get('text','')}")
    _section("常见问答", "faq", lambda i, it: f"{i}. **Q：{it.get('q','')}**\n   - A：{it.get('a','')}")
    _section("演示动作", "demo_actions", lambda i, it: f"{i}. **{it.get('label','')}** — {it.get('text','')}")
    return "\n".join(lines)


def ingest(ctx: RunContext, cfg: dict[str, Any]) -> dict[str, Any]:
    """主入口。返回 handbook dict，并挂载为本次 run 的激活手册。"""
    from shared import dbfakes

    tracer = Tracer(ctx, AGENT_KEY)
    hb_cfg = cfg.get("handbook") or {}
    inbox = Path(hb_cfg.get("inbox_dir") or "inbox")
    if not inbox.is_absolute():
        inbox = bootstrap.AGENT_ROOT / inbox

    paths = _collect_inbox(inbox)
    tracer.log(f"扫描 `{inbox.name}/`，发现 {len(paths)} 个文件", level="info")

    if not paths:
        tracer.log("inbox 为空，本次不绑定产品手册（销冠将按通用经验作答）", level="warn")
        ctx.set_stage(AGENT_KEY, "skipped", reason="inbox 为空")
        dbfakes.set_active_handbook(None)
        return {}

    prebuilt = _load_prebuilt(paths)
    if prebuilt is not None:
        handbook, warnings = prebuilt, []
        tracer.log(f"直接采用已结构化手册 `{Path(prebuilt['_source']).name}`，跳过抽取", level="ok")
    else:
        raw_text, warnings = _parse_documents(paths, tracer)
        (ctx.handbook_dir / "raw_text.md").write_text(
            f"# 手册原始正文\n\n共 {len(raw_text)} 字\n\n---\n\n{raw_text}", encoding="utf-8"
        )
        if not raw_text.strip():
            tracer.log("所有文件都没解析出正文，放弃绑定手册", level="error")
            ctx.set_stage(AGENT_KEY, "failed", reason="正文为空")
            dbfakes.set_active_handbook(None)
            return {}

        from src.analyzers.handbook_extractor import (
            extract_handbook_structure,
            extract_playbook_structure,
        )

        doc_type = str(hb_cfg.get("doc_type") or "auto").lower()
        product_name = str((cfg.get("run") or {}).get("topic") or "").strip()
        extractor = (
            extract_playbook_structure if doc_type == "playbook" else extract_handbook_structure
        )
        tracer.log(f"调用抽取器（doc_type={doc_type}，正文 {len(raw_text)} 字）")
        struct, warnings = extractor(parsed_text=raw_text, product_name=product_name)

        handbook = {
            "id": 1,
            "name": product_name or paths[0].stem,
            "version_no": 1,
            "status": "ready",
            "structure_json": struct,
            "_source": ", ".join(p.name for p in paths),
            "_prebuilt": False,
        }
        tracer.step(
            "extract",
            title="结构化抽取",
            summary={
                "抽取器": extractor.__name__,
                "警告数": len(warnings),
                "卖点": len(struct.get("selling_points") or []),
                "FAQ": len(struct.get("faq") or []),
            },
            inputs={"正文字数": len(raw_text), "product_name": product_name or "(未指定)"},
            output_json=struct,
        )

    (ctx.handbook_dir / "handbook.json").write_text(
        json.dumps(handbook, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ctx.handbook_dir / "handbook.md").write_text(
        _render_handbook_md(handbook, warnings), encoding="utf-8"
    )

    dbfakes.set_active_handbook(handbook)
    ctx.set_stage(
        AGENT_KEY,
        "done",
        handbook_name=handbook.get("name"),
        warnings=len(warnings),
        prebuilt=handbook.get("_prebuilt"),
    )
    tracer.log(f"手册就绪：**{handbook.get('name')}**（警告 {len(warnings)} 条）", level="ok")
    return handbook


def main() -> int:
    ap = argparse.ArgumentParser(description="解析 inbox/ 里的产品手册")
    ap.add_argument("--run-id", default=None, help="写入指定 run；缺省时用最近一次")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bootstrap.init(dry_run=args.dry_run or None)
    import yaml

    cfg = yaml.safe_load((bootstrap.AGENT_ROOT / "config" / "pipeline.yaml").read_text("utf-8"))
    rid = args.run_id or RunContext.latest_run_id()
    ctx = (
        RunContext.load(rid)
        if rid and (bootstrap.AGENT_ROOT / "runs" / rid / "manifest.json").is_file()
        else RunContext.create(dry_run=args.dry_run)
    )
    hb = ingest(ctx, cfg)
    print(f"[{AGENT_KEY}] run={ctx.run_id} handbook={hb.get('name') or '(未绑定)'}")
    print(f"  → {ctx.handbook_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
