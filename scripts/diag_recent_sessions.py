"""诊断脚本：拉最近 5 个销售对话样本，逐句打印 customer / sales 内容,
帮助定位"销售像傻子"的根因。

同时统计:
  - Handbook 提及率（每场销售 turn 中含 Handbook 关键词的比例）
  - 重复率（相同/极相似 sales 句子出现次数）
  - "查官网/在线查/价格请咨询" 之类的兜底词使用率
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.storage import db as sdb  # noqa: E402


PUNT_KEYWORDS = [
    "官网", "官方网站", "在线查", "稍后回复", "需要查询", "我会查",
    "可以查询", "请查看", "建议您查", "官方渠道", "请咨询",
    "稍后告诉", "等我确认", "需要确认",
]


def extract_handbook_keywords(struct: dict) -> list[str]:
    """从 handbook structure 中提取关键 token —— 卖点/参数/竞品/FAQ 短语。"""
    kws: list[str] = []
    intro = struct.get("intro_1") or {}
    if intro.get("text"):
        kws.append(intro["text"][:30])
    for key in ("selling_points", "competitor_points", "core_params",
                "faq", "demo_actions"):
        for it in struct.get(key) or []:
            label = (it.get("label") or "").strip()
            text = (it.get("text") or "").strip()
            if label and len(label) >= 2:
                kws.append(label)
            if text:
                # 把 text 切成短句也加入
                for seg in text.replace("、", "/").replace("，", "/").split("/"):
                    seg = seg.strip()
                    if 2 <= len(seg) <= 12:
                        kws.append(seg)
    # 去重，过滤泛词
    blacklist = {"卖点", "竞品", "FAQ", "演示", "参数", "客户", "问题", "回答",
                 "建议", "可选", "默认"}
    out = []
    seen = set()
    for k in kws:
        if k in blacklist or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def main() -> None:
    with sdb.connection_scope() as conn:
        rows = list(conn.execute("""
            SELECT s.id, s.persona_id, s.handbook_id, s.created_at,
                   json_extract(s.summary_json, '$.outcome') AS outcome,
                   json_extract(s.summary_json, '$.total_rounds') AS rounds,
                   p.name AS pname, p.format_type AS pcluster
            FROM sessions s LEFT JOIN personas p ON s.persona_id = p.id
            WHERE s.id IN (
                SELECT session_id FROM turns
                WHERE role='sales' GROUP BY session_id HAVING COUNT(*) >= 4
            )
            ORDER BY s.created_at DESC LIMIT 5
        """).fetchall())

    if not rows:
        print("ERROR: 没有可用 session")
        return

    # 读 handbook 关键词（取第一场会话用到的）
    hb_kws_cache: dict[int, list[str]] = {}

    def get_kws(hb_id):
        if hb_id in hb_kws_cache:
            return hb_kws_cache[hb_id]
        with sdb.connection_scope() as conn:
            hb = sdb.get_handbook(conn, hb_id) if hb_id else None
        if not hb:
            return []
        kws = extract_handbook_keywords(hb.get("structure_json") or {})
        hb_kws_cache[hb_id] = kws
        return kws

    overall = {
        "sales_turns": 0,
        "sales_with_hb_hit": 0,
        "sales_with_punt": 0,
        "repeat_pairs": 0,
        "all_sales_lines": [],
    }

    for sess_idx, srow in enumerate(rows, 1):
        sid = srow["id"]
        print("=" * 100)
        print(f"[{sess_idx}] session={sid}")
        print(f"    persona={srow['pname']} ({srow['pcluster']})  "
              f"hb={srow['handbook_id']}  outcome={srow['outcome']}  "
              f"rounds={srow['rounds']}")
        print()

        with sdb.connection_scope() as conn:
            turns = list(conn.execute(
                "SELECT idx, role, content, metadata_json FROM turns "
                "WHERE session_id = ? ORDER BY idx ASC",
                (sid,),
            ).fetchall())

        kws = get_kws(srow["handbook_id"])
        sales_lines: list[str] = []
        sess_hits = 0
        sess_punts = 0
        for t in turns:
            role = t["role"]
            content = (t["content"] or "").strip()
            meta = {}
            if t["metadata_json"]:
                try:
                    meta = json.loads(t["metadata_json"])
                except Exception:
                    pass
            tag = "客户" if role == "customer" else (
                "销售" if role == "sales" else role
            )
            extra = []
            if role == "sales":
                overall["sales_turns"] += 1
                sales_lines.append(content)
                # Handbook 命中
                hb_hits = [k for k in kws if k and k in content]
                if hb_hits:
                    sess_hits += 1
                    overall["sales_with_hb_hit"] += 1
                    extra.append(f"hb_hit={hb_hits[:4]}")
                # 兜底词
                punts = [w for w in PUNT_KEYWORDS if w in content]
                if punts:
                    sess_punts += 1
                    overall["sales_with_punt"] += 1
                    extra.append(f"PUNT={punts}")
                # RAG / 注入 meta
                if isinstance(meta, dict):
                    rag = meta.get("rag") or meta.get("retrieval")
                    if rag:
                        if isinstance(rag, dict):
                            cnt = rag.get("hits_count") or len(
                                rag.get("results") or []
                            )
                            extra.append(f"rag_hits={cnt}")
                    hb_meta = meta.get("handbook_inject")
                    if hb_meta:
                        extra.append(
                            f"hb_inj=len{hb_meta.get('length')}"
                        )
            extra_s = ("  " + " ".join(extra)) if extra else ""
            print(f"  #{t['idx']:>2} {tag}: {content[:200]}{extra_s}")

        # 该 session 重复检测
        c = Counter(sales_lines)
        dups = [(line, n) for line, n in c.items() if n >= 2 and len(line) >= 10]
        if dups:
            print()
            print(f"    !!! 重复销售句 {len(dups)} 条:")
            for line, n in dups[:5]:
                print(f"        x{n}  {line[:100]}")
            overall["repeat_pairs"] += sum(n for _, n in dups)

        # 近似相似（前 25 字相同）
        prefix_buckets = defaultdict(list)
        for line in sales_lines:
            if len(line) >= 25:
                prefix_buckets[line[:25]].append(line)
        sim = [b for b in prefix_buckets.values() if len(b) >= 2]
        if sim:
            print(f"    !!! 句首近似重复簇 {len(sim)} 组:")
            for cluster in sim[:3]:
                print(f"        ({len(cluster)} 条同前缀) {cluster[0][:80]}…")

        sl_total = len([t for t in turns if t["role"] == "sales"])
        if sl_total > 0:
            print()
            print(f"    SUMMARY: hb_hit={sess_hits}/{sl_total} "
                  f"({100*sess_hits/sl_total:.0f}%) "
                  f"punt={sess_punts}/{sl_total} "
                  f"({100*sess_punts/sl_total:.0f}%)")
        overall["all_sales_lines"].extend(sales_lines)
        print()

    print("=" * 100)
    print("OVERALL")
    tot = overall["sales_turns"]
    print(f"  total sales turns: {tot}")
    if tot:
        print(f"  hb mention rate : {overall['sales_with_hb_hit']}/{tot} "
              f"({100*overall['sales_with_hb_hit']/tot:.1f}%)")
        print(f"  punt rate       : {overall['sales_with_punt']}/{tot} "
              f"({100*overall['sales_with_punt']/tot:.1f}%)")
        print(f"  repeat lines    : {overall['repeat_pairs']}")
    # 全局高频销售短语
    all_c = Counter()
    for line in overall["all_sales_lines"]:
        # 取前 30 字符
        if len(line) >= 15:
            all_c[line[:30]] += 1
    top = [(k, n) for k, n in all_c.most_common(10) if n >= 2]
    if top:
        print()
        print("  跨场最高频销售前 30 字:")
        for k, n in top:
            print(f"    x{n}  {k}")


if __name__ == "__main__":
    main()
