# 16 证据索引

每条关键结论可反向落到代码或命令。格式：结论 → 位置。

## 身份与范围

| 结论 | 证据 |
|---|---|
| 根目录 F:/Langraph，分支 main，HEAD e10f247 | `git rev-parse` / `git log -1` |
| 工作区干净 | `git status --porcelain` 空 |
| 远程 Eddie-OS/Dealmind | `git remote -v` |
| 无 AGENTS.md | 全仓 Glob 0 |
| 跟踪文件约 2795，outputs 2431 | `git ls-files` 分组 |
| 产品名 DealMind | `src/api/server.py:138-140` |
| 非 LangGraph | `src/` 无 langgraph；README:187 仅蓝图 |

## 产品与业务

| 结论 | 证据 |
|---|---|
| 单管理员用户 | `auth.py:1-14`；AppShell 硬编码 admin |
| 核心旅程 create+start+WS | `routes_sessions.py`；`liveSession.ts` |
| S1–S5 阶段 | `prompts/business_stages.yaml`；`business_stages.py` |
| 6 段旧 STAGES 残留 | `session.py:46-53` |
| 能力已落地 Web/RAG/DB | `server.py` include_router；`rag/`；`storage/` |

## 架构

| 结论 | 证据 |
|---|---|
| 组合根 lifespan | `server.py:79-134` |
| CORS + Auth 顺序 | `server.py:144-163` |
| 生产 8001 + Caddy | `dealmind-api.service:10`；`Caddyfile`；`vite.config.ts:17` |
| 注释写 8000 | `server.py:7` |
| 线程池 Runner | `session_runner_async.py:39` |
| 无独立 worker | 全仓无 celery/rq |

## 多智能体

| 结论 | 证据 |
|---|---|
| run_session 编排 | `session.py:234` |
| Persona/Sales | `agents.py:1075` / `1149` |
| Judge/Memory/Coach | `judge.py:104`；`memory.py:22`；`coach.py:160` |
| 事件名 | `session.py:78-88` |
| 硬短路 | `session.py:71-75,183-216` |
| floor | `session.py:196-200,549-555` |
| 工具循环顶 8 | `agents.py:1423-1424` |
| thinking disabled | `agents.py:1166-1168` |
| MCP 未进 Sales | `tools/__init__.py:29-32` |
| 无 checkpoint | 无 langgraph；batch resume `batch/runner.py:372-382` |
| HITL 仅 pause/cancel | `ws_session.py:77-85` |

## LLM / Prompt / RAG

| 结论 | 证据 |
|---|---|
| Provider 优先级 | `llm.py:260-307` |
| 全局限流 12 | `llm.py:125-136`；`perf_config.py:26` |
| usage 不落库 | `llm.py:344-364` |
| 销冠 prompt DB 优先 | `agents.py:918-937` |
| 渲染 {key} | `agents.py:949-957` |
| Chroma 路径/集合 | `kb_store.py:26-32` |
| embedder 默认 | `embedder.py:25` |
| content_guard | `content_guard.py:372`；smoke PASS |

## 前端

| 结论 | 证据 |
|---|---|
| 路由表 | `web/src/router/index.ts:22-182` |
| 无 SSE | 全 web 无 EventSource |
| session WS 带 token | `ws.ts:52-57` |
| batch WS 不带 | `batch.ts:185-203` |
| Pinia 4 store | `stores/*` |
| 超大页 | AnalysisReport.vue 2767 行 |

## 后端 API

| 结论 | 证据 |
|---|---|
| 112 routes 可导入 | `python -c ... print(len(app.routes))` |
| 429 会话槽 | `session_runner_async.py:68-75`；`routes_sessions.py:286-292` |
| providers 回传 key | `routes_providers.py:95-97` |
| MCP API | `routes_agent_skills.py:303-375` |
| /docs 未保护 | `auth.py:73-76` vs FastAPI 默认 |

## 数据

| 结论 | 证据 |
|---|---|
| DB 路径 | `db.py:25` |
| WAL | `db.py:48-57` |
| ALL_SCHEMAS | `models.py:416-438` |
| persist 事件子集 | `session_persistence.py:8-11,25-76` |
| turns 幂等 | `db.py:1108-1109` |

## 运维

| 结论 | 证据 |
|---|---|
| 无 Docker/CI | Glob 0 |
| setup.sh 路径 | `deploy/setup.sh` |
| 域名 | `Caddyfile` |
| env 列表 | `.env.example` |

## 安全

| 结论 | 证据 |
|---|---|
| 默认密码 | `auth.py:28-33` |
| 确定性 token | `auth.py:36-39` |
| 提交恢复密码 | `a7b4def` |

## 动态验证

| 结论 | 证据 |
|---|---|
| CLI help OK | 本次命令退出 0 |
| perf smoke OK | 输出字典 3/16/12/flash |
| stage_quota OK | 脚本 ✅ |
| guard 两则 OK | ALL ASSERTIONS PASSED |
| sales prompt smoke FAIL | ValueError closed file |
| 未跑真实 LLM | 台账记录 |

## 文档冲突

| 冲突 | 以谁为准 |
|---|---|
| README CLI-only / LangGraph v2 | 代码 |
| 端口 8000 vs 8001 | Vite + systemd = 8001 |
| batch 注释“顺序串行” | `batch/runner.py` 实际并发 |
| README 3 人设 | DB ~94 |
