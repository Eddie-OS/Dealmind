# DealMind Agent · 系统契约

把整套系统当成**一个 agent** 来看时，它的对外契约。
面向的是要把它接进某个执行环境（CLI / 调度器 / 别的 agent 框架）的人。
想知道怎么用请看 `README.md`；想改某个环节请看该目录下的 `AGENT.md`。

## 能力

给定一份产品手册和一批客户人设，产出**经过对抗验证的销售话术资产**。

不是"让模型写几段销售话术"——那不需要这套东西。这里的每一条话术都是
在多轮博弈里说出来、被客户的购买信号验证过、并被事实护栏确认没有编造的。

## 接口

### 输入

| 位置 | 必需 | 说明 |
|------|------|------|
| `inbox/` | 否 | 产品手册文件。缺省时销冠按通用经验作答 |
| `personas/*.yaml` | **是** | 人设快照，至少一个 |
| `knowledge/*.md` | 否 | 补充资料 |
| `config/pipeline.yaml` | 是（有默认值） | 全部运行参数 |
| `.env` | **是** | `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME`。dry-run 时不需要 |

### 调用

```bash
python run_all.py [--dry-run] [--limit N] [--resume RUN_ID] [--yes] [--quality-mode fast|deep]
```

退出码：

| 码 | 含义 |
|----|------|
| 0 | 正常结束（含"部分场次失败但全量跑完"） |
| 2 | 前置条件不满足（没有可用人设） |
| 3 | 被预算闸拦截 |

### 输出

一棵 `runs/<run_id>/` 目录树。结构见 `README.md`。
机器读取的入口是 `manifest.json`（状态账本）、`reports/*.json` 与 `*.jsonl`；
人读取的入口是 `EXEC_SUMMARY.md`。

## 不变量

这几条是设计约束，改代码时不要破坏：

1. **单场失败不中断全量。** 任何一个人设炸了，其余继续，错误记进 manifest。
2. **续跑只补 `status != done` 的场次。** 不做半场恢复。
3. **执行链路零数据库、零向量库。** 唯一碰数据库的是 `tools/export_personas_from_db.py`，
   它是一次性的、只读的、不在执行链路上。
4. **vendored 代码不改。** 要改上游行为，改 `shared/dbfakes.py` 里的数据源，
   或改 `config/`，不要直接编辑 `shared/vendor/`（下次同步会被覆盖）。
5. **销冠每一轮都过事实护栏。** 不提供关闭开关。
6. **dry-run 产出必须自我标注。** 所有 md 头部带 `dry_run: true`，
   避免占位数据被当成结论。

## 内部编排

```
                 ┌── 01 手册解析 ──┐
   config ───────┤                 ├──→ 每人设一场对练 ──→ 09 话术提炼
                 └── 02 人设加载 ──┘         ↑                    ↓
                                    03/04/05/06/07/08      10 质量分析
                                       循环协作                  ↓
                                                          11 报告汇总
```

会话内 6 个 agent 由 `shared/vendor/src/session.py` 的主循环驱动，
`00_orchestrator` 挂事件监听把每一步路由到对应 agent 的 MD 追踪器。
详见 `00_orchestrator/AGENT.md`。

## 可观测性

不依赖任何观测平台。两层文件：

- `RUN_LOG.md` —— 主时间线，边跑边追加，`tail -f` 可用
- `sessions/<人设>/steps/<agent>/*.md` —— 单步完整输入输出

一个 agent 的 `render()` 返回 `None` 时不落文件，所以
`08_content_guard/` 的文件数就是编造次数，不需要额外统计。

## 移植

整个 `Agent/` 目录可以拷到任何有 Python 3.11+ 的机器上。
拷之前确保 `shared/vendor/` 已生成（`python shared/vendor_sync.py`），
它默认不进版本库。

到了新机器上只需要：`pip install -r requirements.txt`、放一份 `.env`、
放人设和手册，然后 `python run_all.py`。
