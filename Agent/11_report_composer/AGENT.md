# 11 · 报告汇总 Agent

流水线最后一棒。把前面所有环节的产物收拢成三份给人看的文件。

## 输入

| 来源 | 用途 |
|------|------|
| `runs/<run_id>/sessions/*/session_log.json` | 每场的原始结果 |
| `runs/<run_id>/reports/quality_scores.json` | `10` 算好的指标，不重算 |
| `runs/<run_id>/reports/excellent_phrases.jsonl` | `09` 提炼的话术 |
| `runs/<run_id>/manifest.json` | 失败场次、续跑次数、耗时 |

指标一律**读 `10` 的结果**而不是自己重算，避免两份报告数字对不上。

## 输出

### `reports/cross_persona_comparison.md`

横向对比表：哪类客户最难搞、销冠在谁身上翻车、难度与成交的关系。
按质量分排序，同时标出难度评分，方便看出"是人设太难还是销冠太弱"。

### `reports/training_guide.md`

可以直接发给一线的培训手册：

1. 本产品最该讲的几件事（从手册结构 + 高信号话术反推）
2. 按异议类型组织的应对话术（来自 `09`）
3. 踩过的坑（来自各场 `what_failed` 的聚合）
4. 明令禁止（护栏改写记录里反复出现的编造类型）

### `EXEC_SUMMARY.md`（写在 run 根目录）

一页纸：跑了什么、花了多久、成了几场、最关键的三个结论、
以及所有产物文件的索引链接。**要看结果先看这一页。**

## 成本

**零额外模型调用**。纯汇总。

## 单独运行

```bash
python 11_report_composer/run.py
python 11_report_composer/run.py --run-id run_xxx
```
