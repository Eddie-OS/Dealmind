# 02 · 人设管理 Agent

决定本次全量对抗到底跑哪些客户，并保证每个人设都能被销冠正确"扮演对手"。
本次 run 里**只跑一次**。

## 输入

| 来源 | 说明 |
|------|------|
| `personas/*.yaml` | 结构化人设（9 维压力参数齐全） |
| `personas/*.json` | panel 格式或 structured 格式，走上游 `parse_persona_file` 归一化 |
| `config/pipeline.yaml → personas` | `include_tags` / `exclude_ids` / `limit` 三道筛子 |

`personas/` 是快照目录，不连数据库。要从上游 SQLite 把 94 个人设拉过来，
执行一次 `python tools/export_personas_from_db.py`，之后这个目录就是唯一真相。

## 输出

| 文件 | 内容 |
|------|------|
| `runs/<run_id>/02_personas/personas.json` | 本次参战人设的完整快照 |
| `runs/<run_id>/02_personas/personas.md` | 花名册：难度、预算、异议风格、压力画像 |
| `runs/<run_id>/steps/02_persona_curator/*.md` | 加载与筛选的逐步记录 |

`manifest.json` 里同时登记每个人设的初始状态为 `pending`，
断点续跑靠的就是这份登记。

## 校验规则

一个人设被判为**不可用**并跳过（不会中断全量）：

- YAML/JSON 解析失败，或缺 `id` / `name`
- 压力参数不在 0-1 之间（`PressureProfile` 会直接拒绝）
- `id` 与已加载的人设重复

跳过原因逐条写进 `personas.md` 的"被排除"小节，不会静默丢人。

## 与其他 agent 的关系

- `00_orchestrator`：拿这份名单决定跑几场、以及断点续跑补哪几场。
- `04_customer_agent`：每场从名单里取一个人设作为扮演对象。
- `11_report_composer`：横向对比报告的行就是这份名单。

## 单独运行

```bash
python 02_persona_curator/run.py            # 加载并生成花名册
python 02_persona_curator/run.py --list     # 只打印名单，不写文件
```
