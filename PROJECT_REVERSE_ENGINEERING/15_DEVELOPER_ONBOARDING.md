# 15 新工程师上手

## 第一天

1. 读 `01_EXECUTIVE_OVERVIEW.md` 与本页。
2. 对照代码打开这 10 个文件（见下）。
3. `pip install -r requirements.txt`；`cp .env.example .env`（改密码，填 Key）。
4. `python -m src.runner --help` 确认环境。
5. `uvicorn src.api.server:app --port 8001` 与 `cd web && npm i && npm run dev`。
6. 浏览器登录（默认账密只用于本地，立刻改掉）。
7. `GET http://127.0.0.1:8001/health` 应返回 `dealmind-api`。

不要在未改密码时把端口映射到公网。

## 第一周

- 走通旅程 A：建人设或选内置 → 新建会话 → Live → 复盘。
- 读 `session.py` 主循环与 `agents.py` 销冠双路径。
- 读 `auth.py` 与 `session_persistence.py`。
- 跑：`scripts/smoke_test_content_guard_*.py`、`smoke_stage_quota.py`、`smoke_test_perf_config.py`。
- 对照 `08` 把前端 `web/src/api/*.ts` 与路由对一遍。
- 弄清 8001 不是 8000。

## 第一个月

- 给 `run_session` 终止条件补 pytest（假 LLM）。
- 修 R-BUG-01（batch WS token）。
- 把 README 改成 Web 主文档。
- 评估是否拆 `db.py`。
- 给 `_log_usage` 设计落库字段。

## 推荐阅读顺序

| 顺序 | 文件 | 为什么 |
|---|---|---|
| 1 | `src/api/server.py` | 组合根、生命周期 |
| 2 | `src/session.py` | 编排真相 |
| 3 | `src/schema.py` | 领域对象 |
| 4 | `src/agents.py` | 双 Agent + RAG + tools |
| 5 | `src/judge.py` `memory.py` `coach.py` | 质控三件套 |
| 6 | `src/llm.py` | 模型与限流 |
| 7 | `src/api/session_runner_async.py` `ws_session.py` | 实时桥 |
| 8 | `src/storage/models.py` `db.py` | 数据 |
| 9 | `web/src/router/index.ts` `stores/liveSession.ts` | UI 骨架 |
| 10 | `prompts/business_stages.yaml` `sales_prompt.md` | 业务规则与话术 |

## 本地启动（真实命令）

见 `10_INFRA_DEPLOYMENT_OPERATIONS.md` §2。  
恢复 DB：`python scripts/restore_conversations_db.py`。  
小内存：`.env` 设 `DM_PRELOAD_EMBEDDER=0`、`DM_MAX_CONCURRENT_SESSIONS=1`。

## 常见任务改哪里

### 新增一个普通页面功能（例如会话列表多一列）

1. `src/storage/db.py` 查询  
2. 对应 `routes_*.py` 响应模型  
3. `web/src/api/*.ts` 类型  
4. 目标 Vue  

验证：手点页面 + 如有 TestClient 则补一条。

### 新增一个销售工具

1. 在 `src/tools/` 用 `@tool` 注册（import 挂到 `__init__.py`）  
2. 默认是否进入 `enabled_tools`（DB `agent_skills_config`）  
3. 前端 AgentSkills 会自动列出 schema  
4. 评估 content_guard / 域名锁定  

验证：`POST /api/agent-skills/test_tool` + 一场 try_sales。**不要**把 MCP 任意 command 暴露给模型。

### 新增一个循环内 Agent（例如 Critic）

1. 新模块 + prompt 文件  
2. `run_session` 找插入点（轮后？会后？）  
3. 新 EVENT_* + `persist_event` + `liveSession.handleEvent` + DialogueStream  
4. schema 新模型  
5. 决定主模型还是 `aux_llm_override`  

验证：CLI `--one-turn-test` 不够；至少一轮完整 session（可用 mock）。

## 最高风险修改（必须配套验证）

| 文件 | 验证 |
|---|---|
| `session.py` 终止/floor | 单测所有 outcome + 一场实跑 |
| `agents.py` 工具循环 | 无工具降级、max loops、guard |
| `llm.py` 客户端 | --test-llm + 并发槽 |
| `auth.py` | 未登录 401、改密失效 |
| `db.py` 迁移 | 旧库启动不丢数据 |
| `embedder.py` | 查询仍能命中旧 collection |
| `content_guard.py` | 现有 2 个 smoke 必须绿 |
| `web/src/api/batch.ts` | 鉴权下 WS 连通 |

## 排障

| 现象 | 先看 |
|---|---|
| RAG 全 0 | `.env` 是否在 embedder import 前加载；模型名是否变 |
| 启动卡死/OOM | PRELOAD；harden 内存 |
| 401 满屏 | token、密码是否刚改 |
| 批量没进度 | R-BUG-01 |
| 429 | 会话槽 |
| 销冠乱报价格 | guard smoke；handbook 是否注入 |
| Windows 控制台乱码 | `server.py` utf-8 reconfigure；smoke 里 emoji |

## 调试

- 运行状态页：任务 / 日志 / llm_stats  
- `logs/app.log`  
- 会话 `prompt_inspect`  
- SalesAgent「试一试」不开会话  
- 不要在生产开 FastAPI `/docs`（当前未关）
