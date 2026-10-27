# DealMind Agent · 全量销售模拟对抗

上传一份产品手册，让**全部人设**轮流上阵和销冠对练一遍，
最后拿到对话全文、优秀话术库、质量分析报告和可直接下发的培训手册。

全过程的每一个环节都落成 markdown 文件。不需要数据库、不需要向量库、
不需要起服务，任何能打开 md 的软件都能看全过程。

## 30 秒上手

```bash
cd Agent
pip install -r requirements.txt

# 1. 先用假模型跑通全链路，确认产出正常（不花一分钱）
python run_all.py --dry-run

# 2. 看看产出对不对
#    runs/dryrun_xxx/EXEC_SUMMARY.md

# 3. 放一份产品手册进 inbox/，然后真实跑 2 个人设试水
python run_all.py --limit 2

# 4. 确认没问题，跑全量
python run_all.py
```

模型密钥从 `Agent/.env` 读，没有就退回上游仓库根目录的 `.env`。

## 人设从哪来

`personas/` 里已经有从上游数据库导出的 **94 个人设快照**，直接可用。
`personas/_examples/` 是 3 个示例（下划线开头的子目录不参与扫描）。

人设有变动时重新导出一次（**只读数据库**，是唯一会碰数据库的脚本）：

```bash
python tools/export_personas_from_db.py --clean
```

之后 `personas/` 就是唯一人设来源，执行链路不再碰数据库。
只想跑一部分不要删文件，改 `config/pipeline.yaml → personas`，
细节见 `personas/README.md`。

## 目录结构

```
Agent/
├── run_all.py              ← 从这里开始
├── config/pipeline.yaml    ← 唯一需要改的配置
├── inbox/                  ← 产品手册丢这里
├── personas/               ← 人设快照
├── knowledge/              ← 手册之外的补充资料（售后政策、活动等）
├── runs/                   ← 所有执行产物
│
├── 00_orchestrator/        统筹编排：谁在什么时候跑
├── 01_handbook_ingest/     手册解析：附件 → 结构化剧本
├── 02_persona_curator/     人设管理：加载、校验、筛选
├── 03_sales_agent/         销冠：被评估的那一方
├── 04_customer_agent/      客户：扮演对手
├── 05_judge_agent/         会中裁判：打分、推进阶段、防假成交
├── 06_memory_agent/        会话记忆：客户画像实时更新
├── 07_coach_agent/         复盘教练：把对话变成可复用经验
├── 08_content_guard/       事实护栏：拦掉编造的数字
├── 09_phrase_miner/        话术提炼：捞出真正管用的话
├── 10_quality_analyst/     质量分析：销冠最缺什么
├── 11_report_composer/     报告汇总：三份给人看的文件
│
├── shared/                 共享层（引导 / 追踪 / 脱库假模块）
│   └── vendor/             引擎快照，从上游 src/ 复制而来
└── tools/                  一次性工具（人设导出）
```

每个 agent 目录里都有一份 `AGENT.md`，写清它的输入、输出、判断依据和已知边界。
想改某个环节的行为，先读那份 md。

## 一次执行产出什么

```
runs/<run_id>/
├── EXEC_SUMMARY.md          ← 先看这个：一页纸讲清跑了什么、结论是什么
├── RUN_LOG.md               ← 执行时间线，跑的过程中可以一直开着看
├── manifest.json            断点账本
├── 01_handbook/
│   ├── handbook.md          手册解析结果（人类可读）
│   ├── handbook.json        结构化版本
│   └── raw_text.md          解析出的原始正文
├── 02_personas/
│   └── personas.md          参战人设花名册
├── sessions/<人设id>__<人设名>/
│   ├── dialogue.md          ← 该人设与销冠的完整对话
│   ├── summary.md           会话摘要 + 复盘
│   ├── dialogue.jsonl       机器可读的逐轮记录
│   ├── session_log.json     完整结构化记录
│   ├── lessons_candidate.jsonl  复盘提炼的经验候选
│   └── steps/               ← 该场每个 agent 每一步的输入输出
│       ├── 03_sales_agent/  每轮销冠：阶段、剧本动作、知识命中、护栏
│       ├── 04_customer_agent/  每轮客户：意图、态度、购买信号
│       ├── 05_judge_agent/  每次裁判：五维打分、阶段推进、给双方的指令
│       ├── 06_memory_agent/ 每次画像刷新
│       ├── 07_coach_agent/  会后复盘
│       └── 08_content_guard/   只在真的改写了才有文件
└── reports/
    ├── excellent_phrases.md          ← 优秀话术库
    ├── quality_report.md             ← 话术质量分析报告
    ├── cross_persona_comparison.md   ← 跨人设横向对比
    ├── training_guide.md             ← 可直接下发的培训手册
    ├── excellent_phrases.jsonl       机器可读
    └── quality_scores.json           机器可读
```

`08_content_guard/` 目录里的文件数直接就是"销冠这场编了几次数字"。

## 常用操作

| 想做什么 | 命令 |
|----------|------|
| 不花钱验证链路 | `python run_all.py --dry-run` |
| 只跑前 2 个人设 | `python run_all.py --limit 2` |
| 补跑上次失败的场次 | `python run_all.py --resume run_xxx` |
| 只重出某场的复盘 | `python 07_coach_agent/run.py --session runs/xxx/sessions/db_0001__阿明_Ah_Ming` |
| 跳过执行前确认 | `python run_all.py --yes` |
| 开启逐条深度质量分析 | `python run_all.py --quality-mode deep` |
| 单独看销冠会怎么说 | `python 03_sales_agent/run.py --selftest` |
| 单独测事实护栏 | `python 08_content_guard/run.py --text "续航 18 小时"` |
| 只重新出报告 | `python 11_report_composer/run.py` |
| 检查引擎快照是否落后上游 | `python shared/vendor_sync.py --check` |

## 成本控制

真实执行前会按 `人设数 × (轮数×2 + 裁判次数 + 记忆刷新次数 + 复盘)` 估算调用量，
打印出来等你确认。`config/pipeline.yaml → budget` 里有三道硬闸
（人设数、轮数、总调用数），超了直接拒绝启动而不是跑到一半才发现。

94 个人设 × 20 轮大约是 **4500 次模型调用**。跑之前先 `--limit 2` 试水。

## 和上游仓库的关系

`shared/vendor/` 是从 `../src/` 物理复制来的引擎快照，包含对练主循环、
五个 agent 的实现、事实护栏、手册抽取器和全部 prompt 模板。
复制而不是引用，是为了让这个目录能整个搬走。

上游改了引擎之后同步过来：

```bash
python shared/vendor_sync.py --check   # 先看差在哪
python shared/vendor_sync.py           # 覆盖更新
```

vendored 代码**一行都没改**。它对数据库和向量库的依赖，是靠
`shared/dbfakes.py` 在 import 之前往 `sys.modules` 里塞同名的文件后端
假模块顶替掉的 —— 顶替数据源而不是改逻辑，这样上游改了渲染格式，
同步一次就能跟上，不会出现两份真相。

## 已知边界

- **没有语义检索**。`knowledge/` 走关键词匹配，同义表达召不回。换来的是
  零模型下载、可离线、结果可解释。
- **手册解析质量决定护栏表现**。手册里写了但没被抽取出来的数字，会被
  护栏当成编造改掉，销冠话术会变空洞。出现这种情况先看 `handbook.md` 漏抽了什么。
- **"手册引用率"是销冠自报的**，不是客观校验，模型有虚报倾向。要客观数据用
  `--quality-mode deep`。
- **续跑的粒度是整场**。断在第 7 轮的会话会整场重跑，不做半场恢复。
  续跑会从 `manifest.json` 继承原 run 的 dry-run 标记，不会把假数据和真数据
  混进同一棵目录树。
- **dry-run 的内容没有分析价值**，它只验证文件产出链路，所有产出 md 都会
  在头部标注 dry-run。
