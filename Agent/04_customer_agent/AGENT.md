# 04 · 客户人设 Agent

扮演对手。全量对抗里有多少个人设，这个 agent 就被实例化多少次，
每次带着完全不同的性格、预算和议价强度去压销冠。

## 输入

| 注入块 | 来源 |
|--------|------|
| 人设档案 | `02_persona_curator` 选中的 `PersonaProfile` |
| 9 维压力参数 | 人设自带，直接决定它有多难缠 |
| 裁判指令 | `05_judge_agent` 的 `persona_instruction`（这一轮该往哪个方向施压） |
| 对话历史 | 最近若干轮原文 |

它**看不到产品手册**。客户本来就不该知道销冠的剧本，
让它看见会导致对话变成两个人对答案。

## 输出

一个 `Turn`：`content`（说给销冠听的话）+ `hidden_state`：

| 字段 | 含义 |
|------|------|
| `intent` / `attitude` | 本轮意图与态度 |
| `purchase_signal` | 0-1 的购买意向，会话结束判定的主要依据之一 |
| `status` | `CONTINUE` / `DEAL_DONE` / `WALK_AWAY` / `COMPLAINT` 等 |
| `walk_away_reason` | 掉头就走时的原因，复盘时这条最值钱 |

`status` 非 `CONTINUE` 会触发提前结束，但在 `max_rounds_floor` 之前的
早退信号会被忽略——防止模型第二轮就"我买了"这种假成交。

## 每轮落盘

`runs/<run_id>/sessions/<persona_id>/steps/04_customer_agent/NNN_r<轮次>.md`

## 单独运行

```bash
python 04_customer_agent/run.py --selftest
```
