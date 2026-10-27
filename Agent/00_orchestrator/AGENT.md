# 00 · 统筹编排 Agent

唯一的总控。它决定谁在什么时候跑、拿谁的输出当输入、失败了怎么办。
其余 11 个 agent 都不知道彼此存在，只认自己的输入输出契约。

## 执行顺序

```
01 手册解析  ──┐
               ├─→  每个人设一场对练（03/04/05/06/07/08 在这里循环）
02 人设加载  ──┘         │
                         ↓
              09 话术提炼 → 10 质量分析 → 11 报告汇总
```

01 和 02 互不依赖，但都必须先于对练完成：手册是销冠的事实来源，
人设名单决定跑几场。09 依赖全部对练结束，10 依赖 09 之外的会话数据，
11 读 09 和 10 的结果做汇总。

## 一场对练内部的调度

主循环由 `shared/vendor/src/session.py` 的 `run_session` 驱动，编排 agent
挂一个事件监听在上面，把每个事件路由到对应 agent 的 MD 追踪器：

| 事件 | 路由到 | 落盘位置 |
|------|--------|----------|
| `sales_turn` | 03 销冠 + 08 护栏 | `sessions/<人设>/steps/03_*`、`08_*` |
| `persona_turn` | 04 客户 | `sessions/<人设>/steps/04_*` |
| `judge_feedback` / `stage_change` | 05 裁判 | `sessions/<人设>/steps/05_*` |
| `memory_update` | 06 记忆 | `sessions/<人设>/steps/06_*` |
| `coach_review` | 07 教练 | `sessions/<人设>/steps/07_*` |

一个事件可以路由给多个 agent（`sales_turn` 同时喂 03 和 08），
agent 的 `render()` 返回 `None` 时不落文件——这就是护栏"只在改写时才有文件"的实现。

## 失败处理

单场失败**不中断全量**。失败的人设在 `manifest.json` 里标 `failed` 并记错误，
其余继续。全量结束后 `EXEC_SUMMARY.md` 会列出失败清单和续跑命令。

续跑判定单位是"一个人设一场会话"，只补 `status != done` 的。
不做半场续跑——断在第 7 轮的上下文没法可靠恢复，硬续会产出
看起来完整实则断裂的对话。

## 成本闸

真实执行（非 dry-run）前会：

1. 按 `人设数 × (轮数 × 2 + 裁判次数 + 记忆刷新次数 + 复盘 1 次)` 估算模型调用量
2. 对照 `config/pipeline.yaml → budget` 的三道硬上限，超了直接拒绝启动
3. 打印预估并**等你回车确认**（`--yes` 跳过，`confirm_before_real_run: false` 永久关闭）

## 输入

- `config/pipeline.yaml`：全部运行参数
- `inbox/`：产品手册
- `personas/`：人设快照

## 输出

一整棵 `runs/<run_id>/`，结构见根目录 `README.md`。

## 单独运行

一般通过根目录的 `run_all.py` 调用，也可以直接跑：

```bash
python 00_orchestrator/run.py --dry-run          # 假模型跑通全链路
python 00_orchestrator/run.py                    # 真实执行（会先要确认）
python 00_orchestrator/run.py --resume run_xxx   # 续跑未完成的场次
python 00_orchestrator/run.py --limit 2          # 只跑前 2 个人设试水
```
