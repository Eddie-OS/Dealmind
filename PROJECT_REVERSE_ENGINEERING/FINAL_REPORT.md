# DealMind 全景逆向工程 · 主报告

**版本基线**：`main` @ `e10f247`（2026-08-14）  
**仓库**：`F:/Langraph` → 远程 `Eddie-OS/Dealmind`  
**分析日**：2026-09-01  
**方法**：只读代码 + 无副作用命令；不修改产品代码。

分报告索引：`00` 台账 … `17` 未决。本页独立回答提示词第四节全部问题。

---

## 一页执行摘要

DealMind 是**模块化单体**销售训练引擎：Vue 管理台 + FastAPI + 自研 `run_session` 多 Agent 循环（Persona ↔ Sales，Judge/Memory 会中，Coach 会后）+ SQLite + 本地 Chroma。仓库目录名 Langraph 是历史，**运行时不是 LangGraph**。

功能上已超过 README：实时对练、批量压测、Handbook 分析、KB、销冠 Prompt 版本、工具开关均已上线，本机库内约 616 场 / 2.2 万轮。生产路径是单机 systemd + Caddy（`dealmind.top`）。

工程上未达生产公网标准：默认密码写进代码、MCP 可起任意进程、API Key 明文回传、无 LLM 日预算、无 CI、批量 WS 漏 token。内容护栏 `content_guard` 的 smoke 已通过，是质量亮点。

**下一步**：先做 `14` 的 P0，再补测试与 README，最后才谈平台化。

---

## 产品与业务

### 一句话定义

用高压力虚拟客户压测销冠 Agent，自动控场、复盘并沉淀培训资产。

### 主要用户与三条旅程

用户在实现上是**唯一管理员**。三条旅程：

1. 单场对练（NewSession → Live WS → 复盘）  
2. 批量压测 → BatchReport / Training Guide  
3. Handbook 分析 → 分类、洞察、优秀话术  

### 已可用 / Demo / 未完成

| 状态 | 项 |
|---|---|
| 已可用 | 对练、批量、分析、KB、Handbook、案例、话术、Dashboard、CLI |
| 部分 | MCP（仅管理端）、experience KB、市场研究 |
| Demo/示意 | `inventory_check` / `promotion_lookup` 数据 |
| 未做 | LangGraph、多租户、token 流式、人工审批、pytest/CI、自动备份 |

---

## 技术与架构

### 运行边界与部署单元

1. `dealmind-api`（uvicorn 127.0.0.1:8001）  
2. `web/dist`（Caddy）  
3. 同机 `data/conversations.db` + `data/chroma/`  
4. 可选 CLI `python -m src.runner`  

进程内线程承担 Session/Batch/Analysis/Indexer。

### 核心数据流与控制流

- **控制**：操作员 HTTP → Runner 线程 → `run_session` for 循环 → 条件 Judge/Memory → Coach。  
- **数据**：事件 →（WS 到 UI）+（persist 到 SQLite）+（结束写 outputs/）+（Sales 读 Chroma/Handbook）。

### 最关键的 10 个文件/符号

| # | 符号/文件 | 为什么 |
|---|---|---|
| 1 | `run_session` `session.py:234` | 编排唯一真相 |
| 2 | `generate_sales_turn` `agents.py:1149` | 被测对象 + 工具/RAG |
| 3 | `generate_persona_turn` `agents.py:1075` | 压力源 |
| 4 | `app` `server.py:137` | 组合根 |
| 5 | `AuthMiddleware` `auth.py:103` | 全站安全门 |
| 6 | `call_llm*` `llm.py` | 费用与失败 |
| 7 | `persist_event` `session_persistence.py:25` | 复盘能否对上 |
| 8 | `ALL_SCHEMAS` `models.py:416` | 数据契约 |
| 9 | `useLiveSessionStore` | 实时体验 |
| 10 | `verify_and_rewrite` | 事实可信度 |

### 最难替换 / 最强耦合 / 瓶颈

- 难替换：`agents.py` + 销冠 prompt + Handbook 结构（业务语言绑死）。  
- 强耦合：引擎读 SQLite profile/skills；`db.py` 巨石。  
- 瓶颈：LLM RT + `LLM_MAX_IN_FLIGHT`；小内存上的 embedder。

---

## 多智能体

### 有多少真实可达 Agent？

循环内 **6** 个：Persona、Sales、Opening（条件）、Judge、Memory、Coach。  
循环外：Pressure Extractor、Persona Generator、Handbook 分析链、Market research、规则型 content_guard。  
配置/遗留：MCP 非运行时 Agent；LangGraph **0**。

### 谁决定调用谁？

`run_session` 硬编码顺序 + interval；不是模型路由。

### 如何通信与共享状态？

共享 `DialogueState`；事件 dict 上抛。无消息总线。DB 是事后镜像。

### 结束、失败、防死循环、费用

`max_rounds`、floor、Persona/Judge 终态、cancel。工具 3/8。LLM 信号量。**无 token 硬预算**。失败多 fallback/保留旧状态。persist 失败不中断。

### 信任边界

管理员 Prompt/KB 默认信任；工具结果低信任；guard 只管数字。无完整 Replay（缺模型/prompt 版本绑定）。

---

## 前端、后端与数据库

闭环基本成立。例外：

- 前端有批量进度，生产鉴权下 WS **可能连不上**（缺 token）。  
- 后端 `personas/meta/dimensions` 无人调用。  
- experience collection 无页面。  
- MCP UI 与 Sales 运行时断开（有意或未完成）。

一致性：SQLite 事务 + turns 唯一键；persist 吞错造成 **WS 与 DB 可能分叉**。无跨 outputs/DB 事务。

---

## 生产可用性

### 新环境能否启动？

能：pip + .env +（可选 restore db）+ uvicorn 8001 + npm dev。生产：`deploy/setup.sh`。[待验证] 前端 build 与 embedding 下载。

### 缺什么？

强制改密、密钥掩码、MCP 锁、LLM 配额、CI、监控告警、自动备份、优雅关闭、与代码同步的 README。

### 明天上线最可能的五个故障

1. 默认密码被登入。  
2. 批量进度 WS 1008。  
3. 2G 机器 embedder OOM。  
4. 误触发分析/批量把账单打爆。  
5. embedder 配置漂移 → RAG 全空 → 销冠胡编（guard 能挡部分数字）。

### 到“生产可用”的最短路径

1. 去掉默认密码，缺 env 拒启。  
2. 掩码 API Key；生产关 /docs；MCP 白名单或关闭。  
3. 修 batch WS token。  
4. job 级 LLM 上限。  
5. content_guard + auth + stage 的 pytest 进最简 CI。  
6. 重写 README（8001、Web 主路径）。  
7. 备份 cron + usage 落库。

---

## 接手与改造

见 `15_DEVELOPER_ONBOARDING.md`。摘要：

- 第一天：10 个核心文件 + 本地双进程。  
- 第一周：走通一场会话 + 跑 guard/quota smoke。  
- 普通功能：路由 + db + api.ts + vue。  
- 新 Agent：session 插入点 + EVENT + persist + liveSession。  
- 最高风险文件：`session.py` `agents.py` `llm.py` `auth.py` `db.py` `content_guard.py`。

---

## 动态验证摘要

| 项 | 结果 |
|---|---|
| CLI help | 通过 |
| import app | 112 routes |
| perf/quota/judge render/guard×2 | 通过 |
| sales prompt render | Windows I/O 失败 |
| 真实 LLM / 前端 build / 起服务 | 未执行（副作用/依赖） |

---

## 覆盖与完成标准

- 版本、指令、入口、部署单元：已确认。  
- 第一方源码已分类；关键文件已全文或重点检查。  
- 页面–API–Agent–表矩阵：见 `03`/`07`/`08`。  
- 每个循环内 Agent 有档案：`05`。  
- Prompt/Tool/RAG/状态：`06`。  
- 核心时序：`04`。  
- Schema/迁移/生命周期：`09`。  
- 配置/部署/监控：`10`。  
- 安全/测试/成本：`11`–`13`。  
- 可行验证已跑并记录。  
- 未知项：`17`。  
- 证据可回指：`16`。

未完成（已解释）：生产现场探测、付费 LLM 闭环、`npm run build`、逐行阅读 2431 个 outputs 快照。

---

## 建议阅读顺序（交付）

`01` → 本页 → `14` → `05` → `15` → 其余分册。
