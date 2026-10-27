# 05 · 会中裁判 Agent

不参与对话，负责三件事：**打分**、**推进阶段**、**踩刹车**。
默认每 3 轮跑一次（`judge_interval`）。

## 输入

完整对话历史 + 当前阶段 + 客户画像 + 阶段机的通过条件。

## 输出

一个 `JudgeFeedback`：

| 字段 | 用途 |
|------|------|
| `sales_score` | 5 维打分：响应度 / 具体性 / 证据使用 / 异议处理 / 推进度 |
| `dialogue_quality_score` | 整体质量分，`09` 挑优秀话术时的初筛依据 |
| `next_stage` + `stage_transition` | 阶段推进 / 停留 / **倒退**，带可解释的失败信号 |
| `persona_instruction` | 下一轮客户往哪个方向施压 |
| `sales_instruction` | 下一轮销冠该补什么 |
| `end_status` | 非 `CONTINUE` 时终止会话 |

## 两个刹车

1. **阶段倒退**：销冠没满足当前阶段的通过条件就想往下推，裁判把阶段拉回去，
   `stage_transition.direction = regress`，并记下命中的失败信号。
2. **假成交拦截**：`max_rounds_floor` 之前的任何终止信号一律忽略。
   没有这道闸，模型倾向于三轮内宣布成交，跑出来的数据全是废的。

## 每次落盘

`runs/<run_id>/sessions/<persona_id>/steps/05_judge_agent/NNN_r<轮次>.md`
以及阶段变更单独一条 `stage_r<轮次>.md`。

## 下游依赖

- `09_phrase_miner` 用 `sales_score` 筛出高分回合作为优秀话术候选。
- `10_quality_analyst` 的 fast 模式主要就是聚合这份打分。

## 单独运行

```bash
python 05_judge_agent/run.py --selftest
```
