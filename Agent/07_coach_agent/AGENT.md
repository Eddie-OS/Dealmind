# 07 · 复盘教练 Agent

一场对练结束后跑一次，把整场对话变成可复用的经验。
它是 `09` 优秀话术库和 `11` 培训手册的主要素材来源。

## 输入

整场完整历史 + 最终结果 + 全程裁判打分 + 最终客户画像。

## 输出

一个 `CoachReview`：

| 字段 | 说明 |
|------|------|
| `outcome_analysis` | 这场为什么成/为什么黄 |
| `what_worked` | 有效策略，带轮次和原文证据 |
| `what_failed` | 失效操作，带轮次和原文证据 |
| `persona_insight` | 对这类客户的新认识 |
| `key_lessons` | 可直接写进培训手册的经验条目 |
| `suggested_rebuttals` | **更优话术模板**（异议 → 应对） |
| `reusable_tactics` | 可复用策略（名称 / 触发条件 / 示例） |
| `difficulty_rating` | 1-10 的人设难度，横向对比时用来排序 |

`what_worked` / `what_failed` 都要求带 `evidence` 原文引用。
没有证据的复盘就是编故事，横向对比时会把结论带偏。

## 落盘

- 步骤 MD：`runs/<run_id>/sessions/<persona_id>/steps/07_coach_agent/`
- 结构化：每场的 `lessons_candidate.jsonl`（`key_lessons` / `reusable_tactics` /
  `suggested_rebuttals` 逐条一行，带 `status: candidate` 标记）
- 人类可读：每场的 `summary.md` 里的「Coach 复盘」小节

`status: candidate` 意味着**未经人工审核**。进 `09` 的优秀话术库之前，
它们只是候选。

## 失败处理

复盘失败不影响会话结果落盘 —— 对话数据已经拿到了，
复盘是增值步骤。失败时会话仍标记 `done`，`RUN_LOG.md` 里记一条 warn。

## 单独运行

```bash
python 07_coach_agent/run.py --selftest
python 07_coach_agent/run.py --session runs/<run_id>/sessions/<persona_id>   # 对已有会话重跑复盘
```
