"""按 playbook_v1 四类客户类型为全量 persona 补标签。

默认 dry-run，只打印预览；加 --apply 才写回 personas.tags_json。

四类口径来自产品手册 playbook_v1：
- A / Business Professional -> 类型A·商务
- B / Content Creator       -> 类型B·创作者
- C / Student               -> 类型C·学生
- D / Parent / Family       -> 类型D·家庭
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from src.storage.db import get_connection, list_personas, update_persona  # noqa: E402


TYPE_LABELS = {
    "A": "类型A·商务",
    "B": "类型B·创作者",
    "C": "类型C·学生",
    "D": "类型D·家庭",
}

_TYPE_RE = re.compile(r"^类型[A-D](?:·.*)?$")

# 当前库内 92 条 persona 的人工校准映射。
# 原因：prompt 里常出现“苹果全家桶”“学习工具”等上下文词，纯全文关键词会误伤。
# 新增 persona 若不在此表，仍走下方关键词兜底。
OVERRIDE_BY_ID: dict[int, str] = {
    1: "A", 2: "B", 3: "C", 4: "D",
    5: "C", 6: "B", 7: "D", 8: "C",
    9: "A", 10: "B", 11: "C", 12: "C",
    13: "D", 14: "B", 15: "A", 16: "D",
    17: "A", 18: "B", 19: "A", 20: "D",
    21: "B", 22: "D", 23: "C", 24: "D",
    25: "A", 26: "B", 27: "A", 28: "B",
    29: "C", 30: "A", 31: "D", 33: "B",
    34: "A", 36: "A", 37: "C", 38: "B",
    41: "C", 42: "C", 43: "D", 44: "A",
    46: "A", 47: "B", 48: "C", 49: "A",
    50: "B", 51: "D", 52: "B", 53: "A",
    54: "C", 55: "B", 56: "B", 57: "A",
    58: "B", 59: "C", 60: "A", 61: "B",
    62: "B", 63: "D", 64: "C", 65: "A",
    66: "A", 67: "D", 68: "C", 69: "B",
    70: "A", 71: "B", 72: "A", 73: "C",
    74: "C", 75: "A", 76: "A", 77: "B",
    78: "B", 79: "B", 80: "C", 81: "A",
    82: "A", 83: "D", 84: "A", 85: "A",
    86: "A", 87: "A", 88: "A", 89: "B",
    90: "B", 91: "B", 92: "C", 93: "C",
    94: "C", 95: "D", 96: "D", 97: "D",
}


def _text_of(row: dict[str, Any]) -> str:
    tags = " ".join(str(t) for t in (row.get("tags") or []))
    return " ".join([
        str(row.get("name") or ""),
        str(row.get("source") or ""),
        tags,
        str(row.get("prompt_text") or ""),
    ]).lower()


def _meta_text_of(row: dict[str, Any]) -> str:
    tags = " ".join(str(t) for t in (row.get("tags") or []))
    return " ".join([
        str(row.get("name") or ""),
        str(row.get("source") or ""),
        tags,
    ]).lower()


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(w.lower() in text for w in words)


def infer_type(row: dict[str, Any]) -> tuple[str, str]:
    """返回 (A/B/C/D, reason)，按强特征优先级判定。"""
    pid = int(row.get("id") or 0)
    if pid in OVERRIDE_BY_ID:
        return OVERRIDE_BY_ID[pid], "人工校准映射"

    text = _text_of(row)
    meta = _meta_text_of(row)

    # 已经按目标口径标过的，直接保留；D·家长等历史变体会在写回时规范成 D·家庭。
    for tag in row.get("tags") or []:
        s = str(tag)
        if s.startswith("类型A"):
            return "A", "已有类型A标签"
        if s.startswith("类型B"):
            return "B", "已有类型B标签"
        if s.startswith("类型C"):
            return "C", "已有类型C标签"
        if s.startswith("类型D"):
            return "D", "已有类型D标签"

    # C：真实学生本人优先于兴趣/创作身份。
    if _has_any(meta, (
        "家长", "家庭", "孩子", "小孩", "儿童", "女儿", "儿子", "宝妈",
        "妈妈", "母亲", "父亲", "爸爸", "全职太太", "家庭主妇",
        "family", "parent", "mom", "mother", "father", "kids", "children",
        "家长管控", "家庭共享", "二孩", "全家共用",
    )) or _has_any(text, (
        "育有一个", "育有两个", "有一个7岁", "有一个 7 岁", "有两个孩子",
        "有三个孩子", "给孩子", "孩子上网课", "孩子学习",
    )):
        return "D", "家长/家庭场景"

    # C：真实学生本人优先于兴趣/创作身份。尽量用身份强信号，避免“学习工具”误伤。
    if _has_any(meta, (
        "大学生", "学生", "研究生", "高中生", "大二", "大三", "法学院",
        "法律系", "医学院", "工程系", "计算机科学专业", "考研", "cpa考试",
        "学霸", "student", "university", "college", "lecture", "school notes",
        "网课笔记", "预算敏感学生", "工科大学生", "医学生", "设计生",
    )) or re.search(r"(就读于|读紧|读緊|主修).{0,18}(大学|学院|university|college)", text):
        return "C", "学生/学习场景"

    # B：内容创作、设计绘画、影音剪辑、数码极客/性能实测类。
    if _has_any(text, (
        "创作者", "内容创作", "内容创作者", "插画", "画师", "绘画", "设计师",
        "设计生", "摄影", "视频", "剪辑", "博主", "短视频", "社媒", "自媒体",
        "tiktok", "youtube", "instagram", "reels", "creator", "designer",
        "illustrator", "photographer", "gopaint", "adobe", "procreate",
        "色准", "手写笔", "压感", "笔触", "绘师", "游戏", "手游", "主播",
        "极客", "参数党", "跑分", "散热", "高刷", "安卓开放", "android geek",
    )):
        return "B", "创作/极客体验场景"

    # A：商务办公、管理、企业主、金融、法律、顾问等生产力场景。
    if _has_any(text, (
        "商务", "办公", "职场", "白领", "经理", "管理", "顾问", "咨询",
        "金融", "投行", "律师", "律所", "高管", "老板", "店主", "企业主",
        "小业主", "外贸", "hr", "项目经理", "市场专员", "销售支持", "广告",
        "提案", "合同", "报价", "excel", "ppt", "wps", "演示", "会议",
        "business", "professional", "office", "consultant", "manager",
        "finance", "lawyer", "executive",
    )):
        return "A", "商务/办公场景"

    # 保守兜底：没有明确家庭/学生/创作信号时，归为商务办公。
    return "A", "兜底到商务"


def normalized_tags(row: dict[str, Any], label: str) -> list[str]:
    old = [str(t) for t in (row.get("tags") or []) if str(t).strip()]
    cleaned = [t for t in old if not _TYPE_RE.match(t)]
    return [label, *cleaned]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写回数据库")
    parser.add_argument("--limit-print", type=int, default=120, help="最多打印多少条预览")
    args = parser.parse_args()

    conn = get_connection()
    rows = list_personas(conn)

    planned: list[dict[str, Any]] = []
    before = Counter()
    after = Counter()
    for row in rows:
        old_type = next((str(t) for t in row.get("tags") or [] if _TYPE_RE.match(str(t))), "(未标)")
        typ, reason = infer_type(row)
        label = TYPE_LABELS[typ]
        new_tags = normalized_tags(row, label)
        before[old_type] += 1
        after[label] += 1
        planned.append({
            "id": row["id"],
            "name": row["name"],
            "old_type": old_type,
            "new_type": label,
            "reason": reason,
            "changed": row.get("tags") != new_tags,
            "new_tags": new_tags,
        })

    changed = [p for p in planned if p["changed"]]
    print(f"persona 总数：{len(rows)}")
    print("写入前类型分布：", dict(sorted(before.items())))
    print("写入后类型分布：", dict(sorted(after.items())))
    print(f"需更新：{len(changed)} 条")
    print()

    for p in planned[: max(0, args.limit_print)]:
        mark = "*" if p["changed"] else " "
        print(f"{mark} #{p['id']:>3} {p['name']}  {p['old_type']} -> {p['new_type']}  ({p['reason']})")

    if not args.apply:
        print("\n[dry-run] 未写库；加 --apply 执行。")
        conn.close()
        return 0

    for p in changed:
        update_persona(conn, int(p["id"]), tags=p["new_tags"])
    print(f"\n[apply] 已写回 {len(changed)} 条 persona 类型标签。")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
