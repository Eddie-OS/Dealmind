"""V2-② 人设重构：LLM 逐条撰写 40 条全新海外消费者人设 → JSON。

输入：本文件内 ``SPEC``（40 条 spec：国家/城市/原型/层级/生态倾向/135910 关注点）。
输出：``训练文件/2.2 海外消费者人设_40.json``（list[persona]，结构对齐 apply 脚本）。

每条 persona 由 LLM 按 ``训练文件/2.1 消费者人设.json`` 同结构（# 角色 / 心理特征 /
消费行为 / 语言习惯 / 模拟指引）撰写中文 Markdown prompt，深度本地化（当地城市/货币/
电商平台/本地竞品/语言习惯），**围绕 135910 产品力而非纠缠砍价**，且禁含中国大陆地名/平台。

执行：
    python scripts/gen_overseas_personas.py
    python scripts/gen_overseas_personas.py --limit 3   # 先试跑 3 条
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from src.llm import call_llm_json  # noqa: E402
from src.locales import get_market  # noqa: E402

OUT_PATH = ROOT / "训练文件" / "2.2 海外消费者人设_40.json"

# 价位锚（与现有人设一致：MatePad 12 X 对标 550-900 美元价位段，仅作背景，不砍价）
USD_BAND = "550-900 美元"

# 中国大陆地名/平台黑名单：生成内容若命中则判失败重试
CN_BANNED = (
    "中国大陆", "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "大理",
    "小红书", "B站", "哔哩", "微博", "知乎", "京东", "天猫", "淘宝", "拼多多",
    "微信", "支付宝", "人民币", "RMB", "CNY", "vmall", "马来亚大学",
)

# 模拟指引等必须出现的小节标题
REQUIRED_SECTIONS = ("# 角色", "## 心理特征", "## 消费与行为", "## 语言表达", "## 模拟指引")

# ---------------------------------------------------------------------------
# 40 条 spec：欧洲 22 / 亚太 6 / 拉美 6 / 中东非 6（无 US，按销售国清单）
# 每条含独立本地姓名（避免并发生成重名），LLM 据此加中文音译。
# ---------------------------------------------------------------------------
SPEC: list[dict] = [
    # ---------- 欧洲 22（FR/GB/DE/IT/ES/PL/RO/NL/CZ/HU/AT × 2）----------
    {"cc": "FR", "city": "巴黎", "name": "Pierre", "archetype": "高净值职场顾问", "tier": 3, "eco": "苹果全家桶", "focus": "多屏协同与办公无缝衔接，对比 iPad Pro 生态"},
    {"cc": "FR", "city": "里昂", "name": "Camille", "archetype": "自由插画师", "tier": 2, "eco": "三星死忠/安卓开放派", "focus": "屏幕显色与手写笔延迟，对比 Galaxy Tab S 系列"},
    {"cc": "GB", "city": "曼彻斯特", "name": "Liam", "archetype": "务实大学生", "tier": 2, "eco": "华为好感/性价比", "focus": "网课笔记与 GMS 替代方案、键盘笔赠送"},
    {"cc": "GB", "city": "伦敦", "name": "James", "archetype": "金融业商务高管", "tier": 3, "eco": "苹果生态", "focus": "演示场景流畅度与跨设备协同，质疑安卓平板专业度"},
    {"cc": "DE", "city": "慕尼黑", "name": "Lukas", "archetype": "工程师/参数控极客", "tier": 2, "eco": "安卓极客", "focus": "芯片性能/刷新率/续航等硬参数，要求现场实测"},
    {"cc": "DE", "city": "柏林", "name": "Anna", "archetype": "二孩宝妈", "tier": 2, "eco": "中立务实", "focus": "儿童护眼模式与学习应用、家长管控等 FAQ"},
    {"cc": "IT", "city": "米兰", "name": "Giulia", "archetype": "平面设计师/创作者", "tier": 2, "eco": "创作驱动", "focus": "色域与手写体验、多任务分屏演示"},
    {"cc": "IT", "city": "罗马", "name": "Marco", "archetype": "小餐饮店主", "tier": 2, "eco": "务实", "focus": "性价比卖点与售后保修 FAQ、办公轻量化"},
    {"cc": "ES", "city": "马德里", "name": "Javier", "archetype": "传媒系大学生", "tier": 2, "eco": "性价比", "focus": "影音娱乐屏幕素质与笔记效率，竞品横评"},
    {"cc": "ES", "city": "巴塞罗那", "name": "Lucía", "archetype": "短视频内容创作者", "tier": 2, "eco": "安卓开放派", "focus": "拍摄剪辑性能与多屏协同演示"},
    {"cc": "PL", "city": "华沙", "name": "Kacper", "archetype": "硬核手游玩家", "tier": 2, "eco": "安卓极客", "focus": "高刷与散热性能、游戏实测演示"},
    {"cc": "PL", "city": "克拉科夫", "name": "Magda", "archetype": "外贸公司职员", "tier": 2, "eco": "务实", "focus": "办公多窗口与文档协同卖点、性价比"},
    {"cc": "RO", "city": "布加勒斯特", "name": "Andrei", "archetype": "IT 从业者/极客", "tier": 2, "eco": "安卓极客", "focus": "系统开放性与 GMS、参数对比演示"},
    {"cc": "RO", "city": "克卢日", "name": "Ioana", "archetype": "医学院学生", "tier": 1, "eco": "极致性价比", "focus": "重课本替代与笔记、键盘笔赠送 FAQ"},
    {"cc": "NL", "city": "阿姆斯特丹", "name": "Daan", "archetype": "咨询顾问", "tier": 3, "eco": "苹果生态", "focus": "跨设备办公协同，质疑安卓平板专业度"},
    {"cc": "NL", "city": "鹿特丹", "name": "Sanne", "archetype": "独立摄影师", "tier": 2, "eco": "创作驱动", "focus": "屏幕色准与修图性能、手写笔演示"},
    {"cc": "CZ", "city": "布拉格", "name": "Tomáš", "archetype": "游戏主播/极客", "tier": 2, "eco": "安卓极客", "focus": "性能散热与直播多窗、参数实测"},
    {"cc": "CZ", "city": "布尔诺", "name": "Petra", "archetype": "小学教师/家长", "tier": 2, "eco": "中立务实", "focus": "护眼与教学应用、家长管控 FAQ"},
    {"cc": "HU", "city": "布达佩斯", "name": "Bence", "archetype": "经济系大学生", "tier": 1, "eco": "性价比", "focus": "笔记网课与多屏协同、预算内最优解"},
    {"cc": "HU", "city": "德布勒森", "name": "Eszter", "archetype": "市场专员", "tier": 2, "eco": "务实", "focus": "办公演示流畅度与售后 FAQ"},
    {"cc": "AT", "city": "维也纳", "name": "Maximilian", "archetype": "高净值律师", "tier": 3, "eco": "苹果生态", "focus": "专业感与无缝衔接，演示场景体面度"},
    {"cc": "AT", "city": "格拉茨", "name": "Hannelore", "archetype": "退休银发用户", "tier": 1, "eco": "极简易用", "focus": "大字易用与视频通话、护眼等 FAQ 演示"},
    # ---------- 亚太新增 6（VN/JP/HK × 2）----------
    {"cc": "VN", "city": "胡志明市", "name": "Minh", "archetype": "务实大学生", "tier": 1, "eco": "华为好感/性价比", "focus": "学习笔记与键盘笔赠送、GMS 替代"},
    {"cc": "VN", "city": "河内", "name": "Tuấn", "archetype": "硬核手游玩家", "tier": 2, "eco": "安卓极客", "focus": "高刷散热性能、游戏实测演示"},
    {"cc": "JP", "city": "东京", "name": "Kenji", "archetype": "IT 企业职场人", "tier": 3, "eco": "苹果生态", "focus": "多设备协同与办公无缝，质疑安卓适配"},
    {"cc": "JP", "city": "大阪", "name": "Yuki", "archetype": "同人绘师/创作者", "tier": 2, "eco": "创作驱动", "focus": "手写笔延迟与色域、绘画演示"},
    {"cc": "HK", "city": "中环", "name": "Marcus", "archetype": "金融从业者", "tier": 3, "eco": "苹果生态", "focus": "跨设备办公与演示体面度、对比 iPad Pro"},
    {"cc": "HK", "city": "九龙", "name": "Karen", "archetype": "大专学生", "tier": 2, "eco": "性价比", "focus": "笔记影音与多屏协同、键盘笔"},
    # ---------- 拉美新增 6（PE×2 / CL×2 / CO×1 / BR×1）----------
    {"cc": "PE", "city": "利马", "name": "Diego", "archetype": "工程系大学生", "tier": 1, "eco": "性价比", "focus": "笔记网课与硬件参数、预算内最优"},
    {"cc": "PE", "city": "阿雷基帕", "name": "Rosa", "archetype": "小微电商店主", "tier": 2, "eco": "务实", "focus": "办公多窗口与性价比、售后 FAQ"},
    {"cc": "CL", "city": "圣地亚哥", "name": "Felipe", "archetype": "广告公司职员", "tier": 2, "eco": "中立务实", "focus": "办公演示与多屏协同卖点"},
    {"cc": "CL", "city": "瓦尔帕莱索", "name": "Camila", "archetype": "独立设计师", "tier": 2, "eco": "创作驱动", "focus": "屏幕色准与手写笔体验演示"},
    {"cc": "CO", "city": "波哥大", "name": "Andrés", "archetype": "短视频创作者", "tier": 2, "eco": "安卓开放派", "focus": "剪辑性能与多任务、拍摄协同演示"},
    {"cc": "BR", "city": "圣保罗", "name": "Lucas", "archetype": "硬核手游玩家", "tier": 2, "eco": "安卓极客", "focus": "性能散热与高刷、游戏实测演示"},
    # ---------- 中东非新增 6（EG×2 / QA×2 / KW×2）----------
    {"cc": "EG", "city": "开罗", "name": "Ahmed", "archetype": "工科大学生", "tier": 1, "eco": "极致性价比", "focus": "课本替代与笔记、键盘笔赠送 FAQ"},
    {"cc": "EG", "city": "亚历山大", "name": "Mostafa", "archetype": "小微企业主", "tier": 2, "eco": "务实", "focus": "办公协同与性价比、保修 FAQ"},
    {"cc": "QA", "city": "多哈", "name": "Khalid", "archetype": "高净值商务人士", "tier": 3, "eco": "苹果生态", "focus": "专业演示与跨设备协同、体面度"},
    {"cc": "QA", "city": "多哈", "name": "Fatima", "archetype": "全职宝妈", "tier": 2, "eco": "中立务实", "focus": "儿童学习护眼与家长管控 FAQ 演示"},
    {"cc": "KW", "city": "科威特城", "name": "Abdullah", "archetype": "高净值青年", "tier": 3, "eco": "苹果生态", "focus": "娱乐影音与多屏协同、对比 iPad Pro"},
    {"cc": "KW", "city": "哈瓦利", "name": "Yousef", "archetype": "外企职员", "tier": 2, "eco": "务实", "focus": "办公多窗口与演示流畅度卖点"},
]


_SYSTEM = (
    "你是华为平板（MatePad 12 X）海外市场的资深消费者画像专家。"
    "你要为一个销售陪练系统撰写【极度真实、深度本地化】的消费者人设，"
    "用于和销售 Agent 对话演练。人设必须像真人，有立场、有偏见、有具体生活细节。"
    "只输出 JSON。"
)


def _build_user(spec: dict) -> str:
    mkt = get_market(spec["cc"])
    return f"""请为以下消费者撰写一条人设，严格输出 JSON（字段：name, source, tags, prompt）。

# 目标消费者
- 所在国家/地区：{mkt.name_cn}（{mkt.name_en}，{spec['cc']}），城市：{spec['city']}
- 当地货币：{mkt.currency}（符号 {mkt.currency_symbol}）；价位背景约 {USD_BAND}（请折算成当地货币写进 prompt，仅作背景，**不要纠缠砍价**）
- 当地主流电商/社区参考：{', '.join(mkt.market_domains)}
- 人物原型：{spec['archetype']}；消费层级 tier={spec['tier']}（1=预算敏感, 2=进阶, 3=高净值）
- 生态倾向：{spec['eco']}
- 核心关注点（必须围绕产品力，落在以下方向，而非价格）：{spec['focus']}

# 字段要求
- name：必须使用本地名「{spec['name']}」+ 中文音译，格式形如「皮埃尔 Pierre」（中文音译在前、本地名在后）。
- source：当地真实社区/平台 + 城市，形如「Frandroid & 巴黎数码论坛」。
- tags：3-4 个简短中文标签（生态/职业/关注点）。
- prompt：一段中文 Markdown 长文（≥500 字），严格包含且仅用这些小节标题：
  「# 角色：<name>」「## 心理特征与价值观」「## 消费与行为特征」「## 语言表达习惯」「## 模拟指引」。
  内容要求：
  * 开头交代城市/年龄/职业/生态倾向 + 当地货币价位背景。
  * 「消费与行为特征」用 *购买决策 / 使用场景 / 换机周期* 三条要点，引用当地电商/社区。
  * 「语言表达习惯」体现当地语言夹杂（code-switching，如法/德/西/日/英等当地语 + 中文），给 2-3 个常用词与一句口头禅。
  * 围绕「{spec['focus']}」展开对产品力（屏幕/手写笔/性能/多屏协同/GMS/护眼/演示等 135910 维度）的真实关注与质疑，**不要把对话焦点放在砍价**。
  * **严禁出现任何中国大陆地名或平台**（如北京/上海/深圳/小红书/B站/微博/京东/淘宝/微信/人民币等），**也不要提及华为的中国/深圳总部背景**；货币与平台必须是 {mkt.name_cn} 当地的。

只输出 JSON 对象。"""


def _valid(rec: dict) -> tuple[bool, str]:
    prompt = (rec.get("prompt") or "")
    if len(prompt) < 300:
        return False, f"prompt 过短({len(prompt)})"
    for sec in REQUIRED_SECTIONS:
        if sec not in prompt:
            return False, f"缺小节 {sec}"
    for bad in CN_BANNED:
        if bad in prompt:
            return False, f"命中 CN 黑名单词「{bad}」"
    if not rec.get("name") or not rec.get("source"):
        return False, "缺 name/source"
    if not isinstance(rec.get("tags"), list) or not rec["tags"]:
        return False, "tags 非法"
    return True, ""


def _gen_one(idx: int, spec: dict) -> dict:
    mkt = get_market(spec["cc"])
    last_err = ""
    for attempt in (1, 2):
        try:
            rec = call_llm_json(_SYSTEM, _build_user(spec), temperature=0.9)
        except Exception as exc:  # noqa: BLE001
            last_err = f"LLM 调用异常: {exc}"
            continue
        if not isinstance(rec, dict):
            last_err = "返回非 dict"
            continue
        ok, why = _valid(rec)
        if ok:
            return {
                "name": rec["name"].strip(),
                "source": rec["source"].strip(),
                "tier": spec["tier"],
                "tags": [str(t).strip() for t in rec["tags"]][:4],
                "locale": "zh-CN",
                "prompt": rec["prompt"].strip(),
                "country_code": spec["cc"],
                "country_name": mkt.name_cn,
                "currency": mkt.currency,
            }
        last_err = why
    raise RuntimeError(f"#{idx} {spec['cc']}/{spec['archetype']} 生成失败: {last_err}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只生成前 N 条（试跑）")
    parser.add_argument("--only", type=str, default="", help="只生成指定下标（逗号分隔），结果并入已有 JSON")
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()

    only_idx = [int(x) for x in args.only.split(",") if x.strip() != ""] if args.only else []
    if only_idx:
        target = [(i, SPEC[i]) for i in only_idx]
    elif args.limit > 0:
        target = list(enumerate(SPEC[: args.limit]))
    else:
        target = list(enumerate(SPEC))
    print(f"开始生成 {len(target)} 条海外人设（workers={args.workers}）...\n")

    # --only 模式：先载入已有 JSON，按 country_code+name 去重后并入
    existing: list[dict] = []
    if only_idx and OUT_PATH.exists():
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    results: dict[int, dict] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_gen_one, i, s): i for i, s in target}
        for fut in as_completed(futs):
            i = futs[fut]
            s = SPEC[i]
            try:
                rec = fut.result()
                results[i] = rec
                print(f"  ✓ #{i:>2} {s['cc']:<3} {rec['name']}  [{','.join(rec['tags'])}]")
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
                print(f"  ✗ #{i:>2} {s['cc']:<3} {exc}")

    if only_idx:
        new_recs = [results[i] for i in sorted(results)]
        seen = {(r["country_code"], r["name"]) for r in new_recs}
        merged = [r for r in existing if (r["country_code"], r["name"]) not in seen]
        merged.extend(new_recs)
        ordered = merged
    else:
        ordered = [results[i] for i in sorted(results)]
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 分布统计
    dist: dict[str, int] = {}
    for r in ordered:
        dist[r["country_code"]] = dist.get(r["country_code"], 0) + 1
    print(f"\n成功 {len(ordered)} 条，失败 {len(errors)} 条 → {OUT_PATH}")
    print("国家分布：", dict(sorted(dist.items())))
    if errors:
        print("\n失败明细：")
        for e in errors:
            print("  -", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
