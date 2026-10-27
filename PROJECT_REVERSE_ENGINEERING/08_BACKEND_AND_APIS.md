# 08 后端与接口

入口：`uvicorn src.api.server:app`。应用 `FastAPI` `server.py:137-142`。中间件内层 `AuthMiddleware`、外层 CORS（`144-163`）。无全局异常处理器、无请求级限流中间件。

鉴权见 `11_SECURITY_PRIVACY.md`。除 `/health` 与 `POST /api/auth/login` 外，`/api/*` `/ws/*` 需 token。**`/docs` `/redoc` `/openapi.json` 不在保护集。**

动态验证：`from src.api.server import app` → **112 routes**。

## 1. 分层

路由（`routes_*.py` / `ws_*.py`）→ Runner（session/batch/analysis）→ 引擎（`run_session` / analyzers）→ `storage.db` / Chroma / LLM。  
无独立 Domain 层；大量业务 SQL 写在 `db.py` 与路由里。

## 2. API 全量清单（按模块）

> 完整 108 条（含 2 WS）的逐字段表见分析过程记录；下表按前缀汇总。调用方均为 Vue `web/src/api/*`，除非注明未用。

### 2.1 系统

| 方法 | 路径 | 符号 | 副作用 |
|---|---|---|---|
| GET | `/health` | `health` `server.py:186` | 无，不鉴权 |
| POST | `/api/auth/login` | `login` `auth.py:58` | 发确定性 token |

### 2.2 Providers `/api/providers`

CRUD + `POST /{id}/default` + `POST /test`。读接口返回 **明文 api_key**（`routes_providers.py:69-97`）。test 消耗 LLM。

### 2.3 Personas `/api/personas`

list/get/create/generate/upload/extract_pressure/patch/delete。  
`GET /meta/dimensions` 前端未用；`GET /meta/countries` 有用。generate/extract 调 LLM。

### 2.4 KB `/api/kbs` + Vector `/api/vector`

KB CRUD、文件上传（启动 indexer）、query。  
Vector：list / rebuild / clear / embedder。rebuild/clear **破坏性**。

### 2.5 Sessions `/api/sessions` + WS

| 方法 | 路径 | 要点 |
|---|---|---|
| GET/POST | `/api/sessions` | 列表 / 建 pending |
| POST | `/{id}/start` | 占槽，满则 **429** |
| POST | `/{id}/cancel` | 需 runner 仍活着 |
| GET | `/{id}` `/{id}/detail` `/{id}/prompt_inspect` | 详情/复盘/handbook 预览 |
| GET/POST | `/{id}/export` `/bulk_export` | 导出 |
| DELETE | `/{id}` | 级联 + 删 outputs |
| POST | `/{id}/cases` | turn→案例 |
| WS | `/ws/session/{id}/live` | 事件流；pause/resume 仅此 |

### 2.6 Dashboard `/api/dashboard`

summary / trends / persona_difficulty / insights。只读聚合。

### 2.7 Batch `/api/batch` + WS

create 立即 `start_in_executor`。resume/cancel/delete。  
报告：overview/objections/persona_comparison/sales_radar/rag_stats/playbook_stats/export。  
WS `/ws/batch/{id}`。delete **不删**子 session。

### 2.8 Cases / Phrases

`/api/cases` CRUD + `POST /reseed_preset`（开发灌数）。  
`/api/excellent-phrases` list/groups/delete。

### 2.9 Status `/api/status`

system（路径/占用）、logs（app.log 最多 2000 行）、llm_stats、tasks。信息泄露面。

### 2.10 Agent Skills `/api/agent-skills`

tools / config / test_web_search / test_tool / mcp/probe / mcp/call_tool。  
后四者有外部或子进程副作用。

### 2.11 Agent Profile `/api/agent-profile`

sales CRUD + versions + restore + try + try_next + memory + effective_config。  
try* 直接 `generate_sales_turn`，耗 LLM+工具。

### 2.12 Handbook `/api/handbooks`

CRUD、文件（单文件 50MB，`routes_handbook.py:289-293`）、extract + extract_status 轮询。

### 2.13 Analysis `/api/analysis/jobs`

create（大量 LLM）、list/get/turns/persona_insights/cancel/delete/export。

## 3. 后台任务

| Runner | 文件 | 触发 | 并发 |
|---|---|---|---|
| SessionRunner | `session_runner_async.py` | start | 槽位 `DM_MAX_CONCURRENT_SESSIONS` 默认 3；线程池 8 |
| BatchRunner | `batch/runner.py` | POST /batch | 会话并发 `BATCH_SESSION_CONCURRENCY`（env 示例 8，代码默认 3） |
| AnalysisRunner | `analysis_runner.py` | POST /analysis/jobs | turn workers 16 |
| Indexer | `rag.seed` | 有 pending 文件 | 1 线程 |
| Handbook extract | extractor_runner | POST extract | 后台线程 |

## 4. 校验、错误、幂等

- 入参：Pydantic 模型（各路由）。
- 错误：分散 `HTTPException`；无统一 error schema。
- 幂等：`turns` UNIQUE(session_id,idx,role) `INSERT OR IGNORE`（`db.py:1108-1109`）。
- 分页：sessions/batch/cases/phrases 等有 limit；未统一标准。
- 接口版本：无 `/v1`，破坏性靠 SQLite 迁移注释。

## 5. 未使用 / 危险入口

| 项 | 说明 |
|---|---|
| `/docs` 等 | 未鉴权 |
| personas/meta/dimensions | 前端未用 |
| pause/resume | 无 REST |
| MCP / test_tool / providers.test / try | 高权限调试面 |
| reseed_preset / vector rebuild | 数据破坏 |

## 6. 与前端闭环

除 dimensions 与 batch WS token 外，页面与 API 基本闭环。后端有、前端弱使用：REST cancel（主路径走 WS）。
