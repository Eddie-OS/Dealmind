# 03 · 销冠 Agent

被对练的那一方。每场会话每一轮说一次话，是整个系统里唯一被评估的对象。

## 输入

每一轮由会话主循环组装，销冠自己不去取数：

| 注入块 | 来源 | 作用 |
|--------|------|------|
| 产品手册块 | `01_handbook_ingest` 的 `handbook.json` | 卖点 / 参数 / FAQ 的唯一口径 |
| 门店身份铁律 | `config/brand_profile.md` | 防止宣称店里有竞品样机这类硬伤 |
| 客户画像 | `06_memory_agent` 的最新画像 | 避免失忆、避免重复踩雷 |
| 裁判指令 | `05_judge_agent` 上一轮的 `sales_instruction` | 下一步该干什么 |
| 阶段剧本 | `prompts/business_stages.yaml` 当前阶段的 allowed actions | 约束这一轮能用哪些动作 |
| 知识补充 | `knowledge/` 关键词检索命中片段 | 手册没覆盖时的兜底材料 |

## 输出

一个 `Turn`：`content`（对客户说的话）+ `strategy`（本轮意图、是否引用手册、下一步动作）。

出口前**强制过一道 `08_content_guard`**：手册里没有依据的具体数字会被改写成模糊表述。
被改写时 `turn.metadata.content_guard` 里会留下改写记录。

## 每轮落盘

`runs/<run_id>/sessions/<persona_id>/steps/03_sales_agent/NNN_r<轮次>.md`

含：本轮阶段、剧本动作、是否引用手册、知识命中、护栏是否改写、以及原话。

## 模型设置

`config/sales_profile.yaml` 可覆盖模型、温度、系统提示词。
**thinking 模式被强制关闭**——上游模型的 thinking 与 function calling 互斥，
且 thinking 会要求历史消息携带 `reasoning_content`，多轮对话下必然 400。

## 单独运行

```bash
python 03_sales_agent/run.py --selftest             # 用固定上下文生成一轮销冠发言
python 03_sales_agent/run.py --selftest --dry-run   # 不调模型
```
