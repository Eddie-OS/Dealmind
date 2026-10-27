# 01 执行摘要

**一句话定义**：DealMind 是一套用高压力虚拟客户（Persona Agent）对销冠（Sales Agent）做多轮博弈、由 Judge/Memory/Coach 会中会后质控，并沉淀手册分析与培训报告的销售训练引擎。

**仓库身份**：本地目录叫 `Langraph`，代码与远程已统一为 **DealMind**（`src/api/server.py:138-140`，提交 `24c019d`）。README 仍把 LangGraph 写成 v2 蓝图，**当前代码没有 LangGraph 运行时**。

---

## 给决策者的结论

| 问题 | 结论 | 证据等级 |
|---|---|---|
| 解决什么业务问题？ | 用可复现的“难缠客户”压测一线销冠话术，自动打分、复盘、出培训材料 | [已证实] README + `run_session` + 分析报告模块 |
| 能不能当产品用？ | **内部可用 / 预生产**：Web 全链路已落地，有真实会话数据（616 sessions / 22118 turns） | [已证实] DB 计数；缺 CI、缺多租户、缺费用配额 |
| 明天公网上线最危险的 5 件事？ | 默认密码、MCP 任意命令、API Key 明文回传、批量 WS 鉴权缺口、LLM 费用失控 | [已证实] 见 `14_RISK_REGISTER.md` |
| 核心护城河在哪？ | 销售阶段机 + Handbook 注入 + content_guard 事实改写 + 批量/分析闭环 | [已证实] |
| 最大架构债？ | 超大单文件（`db.py` 2425 行、`AnalysisReport.vue` 2767 行）、无自动化测试、README 与实现脱节 | [已证实] |

---

## 系统画像

```
操作员 ──Vue SPA──► FastAPI(DealMind API)
                      │
                      ├─ SessionRunner ──► run_session（Persona↔Sales↔Judge/Memory→Coach）
                      ├─ BatchRunner   ──► N × run_session
                      ├─ AnalysisRunner──► 逐 turn 分类 / 洞察 / 优秀话术
                      ├─ SQLite conversations.db
                      └─ Chroma product_knowledge / enterprise_knowledge
                              │
                              └─ DeepSeek（OpenAI 兼容）+ 可选 Web Search / MCP
```

**可部署单元（真实存在）**

1. `dealmind-api`：uvicorn，绑定 `127.0.0.1:8001`（生产 systemd）
2. `web/dist`：Vite 构建的静态 SPA，由 Caddy 托管
3. 单文件 SQLite + 本地 Chroma 目录（与 API 同机）
4. CLI：`python -m src.runner`（仍可用，不是主路径）

**不是**微服务，**不是** LangGraph Cloud，**没有**独立 Worker 进程（后台任务是进程内 ThreadPool）。

---

## 核心价值（已实现）

1. **单场实时对练**：选人设 / KB / Handbook → 开会话 → WebSocket 看对话、阶段、Judge、RAG 命中。
2. **批量压测**：多人设并发跑场，出异议/雷达/剧本覆盖率与培训指南。
3. **手册分析**：按 Handbook 结构给历史会话打标签、聚类洞察、沉淀优秀话术。
4. **知识资产**：产品/企业向量库、案例库、销冠 Prompt 版本、工具开关。
5. **事实护栏**：`content_guard` 把无证据的价格/参数改写成店内兜底话术（smoke 已通过）。

---

## 最高优先级风险（P0）

| ID | 标题 | 为什么现在就要管 |
|---|---|---|
| R-SEC-01 | 默认账号 `admin/789123` 写在代码与 `.env.example` | 提交 `a7b4def` 明确“恢复”该密码；公网即裸奔 |
| R-SEC-02 | 已登录即可 `mcp/probe` + `mcp/call_tool` 启动任意命令 | 单管理员 = 远程命令执行面 |
| R-SEC-03 | `GET /api/providers` 返回完整 `api_key` | 任意持 token 浏览器即可拖走模型密钥 |
| R-SEC-04 | 无会话级 / 日级 LLM 配额 | 批量+分析+试跑均可烧钱 |
| R-BUG-01 | 批量进度 WebSocket **不带 token** | 生产鉴权开启后进度流会 1008 关闭 |

完整台账见 `14_RISK_REGISTER.md`。

---

## 生产可用性判断

| 维度 | 评级 | 说明 |
|---|---|---|
| 功能完整度 | 高 | 对练 / 批量 / 分析 / KB / Handbook 均有 UI 与 API |
| 安全 | 低 | 单用户、弱默认口令、密钥明文、OpenAPI 未鉴权 |
| 可观测性 | 中低 | 文件日志 + journald；无 metrics/trace/告警；token 不落库 |
| 可恢复性 | 中 | 有 `conversations.db.gz` 手工备份脚本；无自动备份/RPO |
| 可测试性 | 低 | 0 个 `test_*.py`，无 CI；仅 15 个手工 smoke |
| 运维手册 | 中 | `deploy/setup.sh` 可用；README 未覆盖 Web 启动 |

**结论**：适合内网或受控单机使用。在未完成 P0 修复前，**不建议对公网开放**。

---

## 阅读本分析的路径

1. 先读本页 + `FINAL_REPORT.md` 关键问答。
2. 改功能：`15_DEVELOPER_ONBOARDING.md`。
3. 改 Agent：`05` + `06`。
4. 改接口/页面：`07` + `08`。
5. 上线：`10` + `11` + `14`。
