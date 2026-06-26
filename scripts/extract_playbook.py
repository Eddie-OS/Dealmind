"""强制按 playbook_v1 抽取某本 Handbook 的结构（绕开 UI 写死的 135910 按钮）。

解决两件事：
1. UI 的「从文件抽取」按钮写死 doc_type=handbook_135910，无法触发 playbook 分路；
2. 一本 Handbook 可能挂了多份来源文件（如旧 12X PPTX + 新 Air PDF），混抽会串味。
   本脚本用 --only 只挑文件名包含该子串的来源文件（默认 "Global-0611"）。

抽出的 structure_json 内部自带 ``doc_type:"playbook_v1"``，下游 agents/分类器/聚合器
会据此自动走 playbook 分路，无需额外的 DB 列。

需要能连 LLM（抽取要调一次 LLM）。默认 dry-run，加 --apply 才落库。

执行：
    python scripts/extract_playbook.py --list                       # 先看有哪些 handbook / 文件
    python scripts/extract_playbook.py --handbook-id 1              # 预览（只读 Global-0611）
    python scripts/extract_playbook.py --handbook-id 1 --apply      # 落库（覆盖结构 + 版本号+1）
    python scripts/extract_playbook.py --handbook-id 1 --only "" --apply   # 不过滤、用全部来源文件
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from src.analyzers.handbook_extractor import extract_playbook_structure  # noqa: E402
from src.storage.db import (  # noqa: E402
    get_connection,
    get_handbook,
    list_handbook_files,
    list_handbooks,
    update_handbook,
)


def _print_handbooks(conn) -> None:
    hbs = list_handbooks(conn)
    print(f"共 {len(hbs)} 本 handbook：")
    for hb in hbs:
        files = list_handbook_files(conn, int(hb["id"]))
        print(f"  [id={hb['id']}] {hb['name']}  status={hb.get('status')} v{hb.get('version_no')}")
        for f in files:
            print(
                f"      - file id={f['id']} {f.get('filename')} "
                f"({f.get('file_type')}, status={f.get('status')}, "
                f"{len((f.get('parsed_text') or ''))} chars)"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="列出 handbook + 文件后退出")
    parser.add_argument("--handbook-id", type=int, default=0, help="目标 handbook id")
    parser.add_argument(
        "--only", type=str, default="Global-0611",
        help="只挑文件名包含该子串的来源文件（设为空串 '' 则用全部）",
    )
    parser.add_argument("--apply", action="store_true", help="真正写库（默认仅预览）")
    args = parser.parse_args()

    conn = get_connection()

    if args.list or not args.handbook_id:
        _print_handbooks(conn)
        if not args.handbook_id:
            print("\n指定 --handbook-id <id> 再跑抽取。")
        conn.close()
        return 0

    hb = get_handbook(conn, args.handbook_id)
    if not hb:
        print(f"handbook id={args.handbook_id} 不存在")
        conn.close()
        return 1

    files = list_handbook_files(conn, args.handbook_id)
    parsed = [
        f for f in files
        if (f.get("parsed_text") or "").strip() and f.get("status") == "parsed"
    ]
    if args.only:
        sub = args.only.lower()
        parsed = [f for f in parsed if sub in (f.get("filename") or "").lower()]

    if not parsed:
        print(
            f"没有匹配的来源文件（only='{args.only}'）。"
            f"可用 --list 查看，或用 --only '' 取全部。"
        )
        conn.close()
        return 1

    print(f"目标 handbook：[id={hb['id']}] {hb['name']}")
    print(f"用于抽取的来源文件（{len(parsed)} 份）：")
    for f in parsed:
        print(f"  - {f.get('filename')} ({len(f.get('parsed_text') or '')} chars)")

    text = "\n\n".join(
        f"===== {f.get('filename')} =====\n\n{(f.get('parsed_text') or '').strip()}"
        for f in parsed
    ).strip()

    print(f"\n调用 LLM 抽取 playbook_v1（{len(text)} chars）...")
    struct, warnings = extract_playbook_structure(
        parsed_text=text, product_name=hb.get("name") or "",
    )

    open_blk = struct.get("open") or {}
    say = struct.get("say") or []
    compete = struct.get("compete") or []
    respond = struct.get("respond") or []
    print("\n===== 抽取结果 =====")
    print(f"doc_type           : {struct.get('doc_type')}")
    print(f"open.persona_openers: {len(open_blk.get('persona_openers') or [])}")
    print(f"say（按人设分组）  : {len(say)} 组  人设={[b.get('persona') for b in say]}")
    print(f"compete（按竞品）  : {len(compete)} 组  竞品={[b.get('vs') for b in compete]}")
    print(f"respond（FAQ）     : {len(respond)} 条")
    if warnings:
        print("warnings:")
        for w in warnings:
            print(f"  - {w}")

    has_content = bool((open_blk.get("persona_openers")) or say)
    if not has_content:
        print("\n✗ 抽取无实质内容（开场/卖点为空），不落库。请检查来源文件是否正确。")
        conn.close()
        return 1

    if not args.apply:
        print("\n[dry-run] 未写库。确认结构无误后加 --apply 落库。")
        conn.close()
        return 0

    update_handbook(
        conn, args.handbook_id,
        structure=struct,
        status="ready",
        bump_version=True,
        extraction_log=f"playbook_v1 extracted via scripts/extract_playbook.py (only='{args.only}')",
    )
    after = get_handbook(conn, args.handbook_id)
    print(f"\n✓ 已落库。status={after.get('status')} version={after.get('version_no')}")
    print("  下游 agents/分类器/聚合器会自动按 playbook_v1 分路（结构内已带 doc_type）。")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
