"""一次性脚本：从 PPTX 文件抽取 1/3/3/5/9/10 Handbook 结构。

用法：
    cd f:\\Langraph
    python scripts/extract_handbook_from_pptx.py

输出：
    data/product_handbooks/matepad_12x_handbook.json

这是 Sprint 1 之前的临时辅助脚本，等正式 HandbookManager.vue
开发完成后，这个能力会通过 UI 上传 → POST /api/handbooks/{id}/extract 实现。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# 必须在 src.* 导入前加载 .env
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from src.llm import call_llm_json
from src.rag.parsers import parse_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_handbook")


# ============================================================
# 配置
# ============================================================

PPTX_PATH = ROOT / "训练文件" / "5. Laurent_HUAWEI MatePad 12 X_Instore Training Guide.pptx"

OUTPUT_DIR = ROOT / "data" / "product_handbooks"
OUTPUT_FILE = OUTPUT_DIR / "matepad_12x_handbook.json"

PRODUCT_NAME = "华为 MatePad 12X / MatePad Air 2025"

# 单次喂给 LLM 的最大字符数（DeepSeek-Chat 上下文 64K，留余量给 prompt + 输出）
MAX_INPUT_CHARS = 30000


# ============================================================
# Prompt
# ============================================================

SYSTEM_PROMPT = """你是产品销售文档结构化专家。你的任务：从一份产品培训文档（PPT 提取的文本）中，
按照固定的 1/3/3/5/9/10 框架，抽取出标准化的销售话术 Handbook。

框架定义：
- 1 个一句话产品定位
- 3 个核心卖点（每个 50-150 字，含具体卖点名称 + 价值描述）
- 3 个竞品分析点（针对主要竞品做差异化对比，每个 80-200 字）
- 5 个核心参数（屏幕/处理器/内存存储/电池/重量厚度 等可量化硬指标）
- 9 个 FAQ 问答（客户最常问 + 销冠最难答 的 9 组）
- 10 个演示动作（在店内可让客户上手体验的具体动作序列）

输出严格 JSON，禁止 markdown 包裹。"""


USER_PROMPT_TEMPLATE = """产品名称：{product_name}

【产品文档原文】（PPT 各 Slide 内容拼接）
=========================================
{doc_text}
=========================================

请你基于以上文档原文，**严格按照** 1/3/3/5/9/10 框架，输出如下 JSON 结构：

{{
  "product_name": "{product_name}",
  "intro_1": {{
    "id": "intro_1",
    "label": "一句话定位",
    "text": "（一句话定位文本，30-80 字）",
    "source": "（来源 Slide 编号或主题，如 'Slide 3 · Product Positioning'）"
  }},
  "selling_points": [
    {{"id": "sell_1", "label": "卖点①·（简短名称）", "text": "（卖点完整描述，50-150 字）", "source": "..."}},
    {{"id": "sell_2", "label": "卖点②·...", "text": "...", "source": "..."}},
    {{"id": "sell_3", "label": "卖点③·...", "text": "...", "source": "..."}}
  ],
  "competitor_points": [
    {{"id": "comp_1", "label": "竞品①·vs （竞品名）", "vs": "（竞品全称，如 iPad Air）", "text": "（差异化对比 80-200 字，含具体维度）", "source": "..."}},
    {{"id": "comp_2", "label": "竞品②·vs ...", "vs": "...", "text": "...", "source": "..."}},
    {{"id": "comp_3", "label": "竞品③·vs ...", "vs": "...", "text": "...", "source": "..."}}
  ],
  "core_params": [
    {{"id": "param_1", "label": "参数①·屏幕", "text": "（具体规格数字）", "source": "..."}},
    {{"id": "param_2", "label": "参数②·处理器", "text": "...", "source": "..."}},
    {{"id": "param_3", "label": "参数③·内存存储", "text": "...", "source": "..."}},
    {{"id": "param_4", "label": "参数④·电池续航", "text": "...", "source": "..."}},
    {{"id": "param_5", "label": "参数⑤·重量厚度", "text": "...", "source": "..."}}
  ],
  "faq": [
    {{"id": "faq_1", "label": "FAQ①", "q": "（客户问题）", "a": "（标准答案 50-200 字）", "source": "..."}},
    ... (共 9 条)
  ],
  "demo_actions": [
    {{"id": "demo_1", "label": "演示①·（动作名）", "text": "（具体操作步骤 + 想让客户感受到什么，50-150 字）", "source": "..."}},
    ... (共 10 条)
  ]
}}

严格要求：
1. selling_points 必须恰好 3 条，competitor_points 必须 3 条，core_params 必须 5 条，
   faq 必须 9 条，demo_actions 必须 10 条；不够时**基于文档合理推断补齐**，宁可保守也别遗漏数量。
2. 所有 text/a 字段**禁止凭空编造**——必须能在文档原文中找到依据；找不到时坦诚标注 "（文档未明确提及，建议补充）"。
3. source 字段尽量带 Slide 编号（如 "Slide 8"），方便人工对照原 PPT 校验。
4. faq 中的 Q 要选**客户最常问 + 最关键** 的 9 个（如价格 / 续航 / 竞品 / 售后 / 兼容 / 使用人群等）。
5. demo_actions 必须是**店内可立即演示** 的具体动作（如"分屏演示"、"M-Pencil 写字"），不是抽象建议。
6. 输出**严格 JSON**，所有字符串用双引号，禁止 markdown 代码块。
"""


# ============================================================
# 主流程
# ============================================================

def main() -> None:
    if not PPTX_PATH.exists():
        logger.error("PPTX 不存在: %s", PPTX_PATH)
        sys.exit(1)

    logger.info("Step 1: 解析 PPTX...")
    chunks = parse_file(PPTX_PATH)
    logger.info("  解析到 %d 个 chunks", len(chunks))

    # 拼成"Slide N: title\n正文"格式，方便 LLM 引用 source
    full_parts: list[str] = []
    for c in chunks:
        section = c.get("section") or ""
        text = c.get("text") or ""
        if not text.strip():
            continue
        full_parts.append(f"[{section}]\n{text}")
    full_text = "\n\n".join(full_parts)
    logger.info("  全文总字符数: %d", len(full_text))

    # 截断（如果超长）
    if len(full_text) > MAX_INPUT_CHARS:
        logger.warning("  全文超 %d 字符，截断（前 %d）", MAX_INPUT_CHARS, MAX_INPUT_CHARS)
        full_text = full_text[:MAX_INPUT_CHARS] + "\n\n...（后续 Slide 因长度截断）"

    logger.info("Step 2: 调用 LLM 抽取 1/3/3/5/9/10 结构...")
    user_prompt = USER_PROMPT_TEMPLATE.format(
        product_name=PRODUCT_NAME,
        doc_text=full_text,
    )
    try:
        result = call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.3)
    except Exception as exc:
        logger.exception("LLM 调用失败: %s", exc)
        sys.exit(2)

    # 简单校验数量
    checks = [
        ("intro_1", lambda r: isinstance(r.get("intro_1"), dict)),
        ("selling_points x3", lambda r: len(r.get("selling_points") or []) == 3),
        ("competitor_points x3", lambda r: len(r.get("competitor_points") or []) == 3),
        ("core_params x5", lambda r: len(r.get("core_params") or []) == 5),
        ("faq x9", lambda r: len(r.get("faq") or []) == 9),
        ("demo_actions x10", lambda r: len(r.get("demo_actions") or []) == 10),
    ]
    logger.info("Step 3: 校验结构...")
    all_pass = True
    for name, fn in checks:
        ok = fn(result)
        logger.info("  %s %s", "OK" if ok else "MISS", name)
        if not ok:
            all_pass = False
    if not all_pass:
        logger.warning("  部分项未达标，已照常输出，请人工校对")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Step 4: 已写入 %s", OUTPUT_FILE)
    logger.info("=== 抽取完成 ===")


if __name__ == "__main__":
    main()
