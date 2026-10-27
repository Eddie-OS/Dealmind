# 10 · 话术质量分析 Agent

回答一个问题：**这次全量对抗暴露出销冠最缺什么。**

## 两种模式

`config/pipeline.yaml → quality.mode` 切换。

### fast（默认，零额外模型调用）

聚合已经落盘的信号，算出每场和整体的画像：

| 指标 | 口径 |
|------|------|
| 5 维裁判分 | 响应度 / 具体性 / 证据使用 / 异议处理 / 推进度 |
| 手册引用率 | 销冠自报引用手册的轮次占比 |
| 编造率 | 被 `08_content_guard` 改写的轮次占比 |
| 阶段到达 | 最终停在 S1-S5 的哪一阶 |
| 信号轨迹 | 客户购买信号从开场到收尾的净变化 |
| 失效模式 | `07_coach_agent` 的 `what_failed` 聚合词频 |

### deep（每条销冠发言额外一次模型调用）

用上游的 6 维评分卡逐条打分：把发言先归到手册里的某个条目
（卖点几号 / FAQ 几号 / 演示动作几号），再按该条目的标准评
**是否覆盖 / 是否准确 / 是否有说服结构 / 是否有推进** 等 6 个维度，
并给出 issues 与一句改进建议。

deep 的成本是 `会话数 × 每场销冠轮数` 次调用。94 场 × 20 轮 ≈ 1880 次。
**跑之前先算清楚。** `deep_max_turns_per_session` 可以限制每场最多分析几轮。

## 输入

`runs/<run_id>/sessions/*/session_log.json`

## 输出

| 文件 | 内容 |
|------|------|
| `runs/<run_id>/reports/quality_report.md` | 主报告：整体画像 + 最弱维度 + 每场明细 |
| `runs/<run_id>/reports/quality_scores.json` | 机器可读的全部指标 |
| `runs/<run_id>/steps/10_quality_analyst/*.md` | 每场的分析步骤（deep 模式下含逐条打分） |

## 一个必须知道的口径问题

"手册引用率"来自销冠**自报**的 `used_handbook` 字段，不是客观校验。
模型有虚报倾向。要拿客观数据，把 `quality.mode` 切到 `deep`，
那里的归类是拿发言原文和手册条目做匹配的。

## 单独运行

```bash
python 10_quality_analyst/run.py                    # 按配置里的 mode
python 10_quality_analyst/run.py --mode deep        # 强制 deep
python 10_quality_analyst/run.py --run-id run_xxx
```
