# 06 · 会话记忆 Agent

在对话过程中持续维护一份客户画像，专门解决销冠"失忆"和"重复踩雷"。
默认每 2 轮刷新一次（`memory_interval`）。

## 输入

最近若干轮对话 + 上一版画像。它做的是**增量更新**而不是重新总结，
所以客户在第 3 轮说过的预算，到第 15 轮依然在。

## 输出

一个 `SessionMemory`：

| 字段 | 作用 |
|------|------|
| `current_need` | 客户真正想要什么（可能和一开始说的不一样） |
| `main_objections` | 当前未解决的异议清单 |
| `budget_boundary` | 已暴露的预算边界 |
| `emotional_state` | 情绪，销冠据此调整推进力度 |
| `mentioned_competitors` | 提过的竞品 |
| `decision_constraints` | 需要和谁商量、什么时候要 |
| `do_not_repeat` | **已经讲过的内容，销冠不许再讲一遍** |
| `next_best_action` | 建议的下一步 |

`do_not_repeat` 是这个 agent 存在的主要理由。没有它，多轮对话里销冠
会把同一个卖点讲三遍，客户耐心掉光后走人，跑出来的数据没有分析价值。

## 每次落盘

`runs/<run_id>/sessions/<persona_id>/steps/06_memory_agent/NNN_r<轮次>.md`
记录本次刷新后的完整画像，可以直接对比前后两版看画像是怎么演化的。

## 下游依赖

- `03_sales_agent` 每轮读最新画像。
- `05_judge_agent` 用 `current_need` 等字段做阶段推进的前置检查。

## 单独运行

```bash
python 06_memory_agent/run.py --selftest
```
