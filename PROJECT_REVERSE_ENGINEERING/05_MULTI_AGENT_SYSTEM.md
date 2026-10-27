# 05 多智能体系统

> 重点结论：[已证实] 编排是 `src/session.py:run_session` 自研 for 循环，**不是 LangGraph**。`src/` 无 `langgraph` 导入。

## 1. Agent 全量清单

| # | 名称 | 符号 | 位置 | 在 run_session？ | 可达 |
|---|---|---|---|---|---|
| 1 | Persona Agent | `generate_persona_turn` | `src/agents.py:1075` | 每轮 | 是 |
| 2 | Sales Champion | `generate_sales_turn` | `src/agents.py:1149` | 每轮 | 是 |
| 3 | Opening Line | `generate_opening_line` | `src/agents.py:1044` | 销售先开口时 | 是 |
| 4 | Judge | `judge_dialogue` | `src/judge.py:104` | 每 judge_interval | 是 |
| 5 | Session Memory | `update_session_memory` | `src/memory.py:22` | 每 memory_interval | 是 |
| 6 | Coach | `run_coach` | `src/coach.py:160` | 结束后 1 次 | 是 |
| 7 | Pressure Extractor | `extract_pressure_profile` | `src/persona/pressure_extractor.py:54` | 否（人设页） | 是 |
| 8 | Persona Generator | `src/persona/generator.py` | 人设 AI 生成 | 否 | 是 |
| 9 | Handbook Extractor/Revisor/Classifier/Scorer | `src/analyzers/*` | 分析/抽取任务 | 否 | 是 |
| 10 | Market research | `src/research/market_research.py` | preflight/市场事实 | 会前 | 是 |
| 11 | Content Guard | `verify_and_rewrite` | `src/content_guard.py:372` | Sales 出口，非 LLM | 是 |
| — | LangGraph 节点 Agent | — | — | — | **不存在** |

同名/遗留：无第二套并行 Agent 实现。CLI 与 Web 共用同一组函数。

---

## 2. 逐 Agent 档案

### 2.1 Persona Agent

- **职责**：扮演客户，输出可见话术 + `HiddenState`。
- **输入**：`DialogueState`（人设、历史滑窗、memory、judge 指令、阶段）。
- **输出**：`Turn(speaker=persona)`。
- **模型**：全局 default；`thinking_mode=disabled`；temperature `0.8`（`agents.py:1125-1127`）。
- **Prompt**：structured → `prompts/persona_prompt.md`；prompt_based → `persona_prompt_v2.md`。System 前缀硬编码（`1115-1118`）。
- **工具**：无。
- **失败**：`_make_fallback_turn`（`1128-1131`）。
- **终止权**：`WALK_AWAY`/`COMPLAINT` 硬停；`DEAL_DONE`/`FOLLOW_UP` 软停。

### 2.2 Sales Champion

- **职责**：销冠回复 + `SalesStrategy`；RAG 或 function-calling；出口 content_guard。
- **模型**：`agent_profiles.sales.model_override` 可覆盖；thinking **强制 disabled**（`1166-1168`，兼容 V4-Pro + tools）。
- **temperature**：普通路径 `0.6`。
- **Prompt**：`load_prompt("sales_prompt")`，**DB 在线稿优先于文件**（`918-937`）。
- **工具**：`enabled_tools` 白名单，见 `06`。
- **双路径**：有工具走 `_generate_sales_turn_with_tools`（`1504`）；异常降级预 RAG + `call_llm_json`（`1224-1227`）。
- **权限**：`playbook_action` 服务端校验（`902-915`）。

### 2.3 Judge

- **职责**：质量分、S1–S5 转移、双方下一轮指令、`avoid_repeating`、`end_status`。
- **模型**：`AUX_MODEL_NAME`（默认 flash），temp `0.2`（`judge.py:193-196`）。
- **Prompt**：`prompts/judge_prompt.md`。
- **校验**：`is_valid_transition` 拦截非法跳阶段（`218-224`）。
- **失败**：保留旧 `judge_feedback`。

### 2.4 Memory

- **职责**：提取异议、预算、情绪、`do_not_repeat`。
- **模型**：aux flash，temp `0.2`。
- **失败**：返回旧 memory。

### 2.5 Coach

- **职责**：整场复盘、有效/失效策略、话术模板、playbook 覆盖。
- **模型**：aux，temp `0.3`。
- **机检注入**：`_compute_playbook_stats` 等（`coach.py:29-117`）。

### 2.6 辅助

Opening Line、Pressure Extractor、Handbook 分析链、Market research：均 LLM 或规则，不进入对练循环的“对等 Agent”。

---

## 3. 编排与协作拓扑

```mermaid
flowchart TB
  PF[preflight fact card] --> LOOP
  subgraph LOOP [run_session for round]
    P[Persona] --> S[Sales]
    S --> M{memory_interval?}
    M -->|yes| MEM[Memory]
    S --> J{judge_interval?}
    J -->|yes| JUD[Judge]
    JUD -->|stage_transition| LOOP
  end
  LOOP --> C[Coach]
  P -->|WALK_AWAY/COMPLAINT| X[硬停]
  S -->|峰终| Y[软停]
```

- **模式**：自研 Supervisor=主循环，不是 Swarm/Graph。
- **谁选 Agent**：硬编码顺序，不是模型路由。
- **拆解**：无 Planner；Judge 只调阶段与指令。
- **并行**：单场内 Persona/Sales **串行**；Batch 多场并行。
- **消息协议**：Pydantic 模型 + `on_event` dict；无跨 Agent 消息总线。
- **关联 ID**：`session_id`；无独立 Trace ID。
- **HITL**：WS `pause`/`resume`/`cancel`（`ws_session.py:77-85`）；无输出审批。
- **预算**：`max_rounds`；工具循环默认 3、硬顶 8；`LLM_MAX_IN_FLIGHT`；**无 token 硬预算**。

### 任务状态机

见 `03` 的 outcome 图。Judge `end_status != CONTINUE` 也会停，但受 `max_rounds_floor` 约束（`session.py:548-561`）。

### 协作时序（一轮）

Persona JSON → persist+WS →（非硬停）Sales（RAG/tools/guard）→ persist+WS → 条件 Memory/Judge → 检查终止。

---

## 4. 状态、上下文、记忆

| 层级 | 载体 | 生命周期 |
|---|---|---|
| 请求/轮次 | `Turn` + metadata | 写入 `turns` |
| 会话 | `DialogueState`：full_history + recent_history(10) + memory + judge | 内存；部分 persist |
| 用户 | 无（单管理员） | — |
| 工作流 | batch_jobs / analysis_jobs | DB |
| 全局 | agent_profiles、skills、providers、KB | DB + Chroma |

记忆类型：

- 短期：`recent_history` 10 条（`session.py:44`）。
- 情景：`SessionMemory` 周期性覆盖。
- 语义：Chroma RAG + 案例 LIKE 搜索。
- 摘要：`sessions.summary_json`（含 latest_memory）；CoachReview。
- 长期：excellent_phrases / sales_cases / outputs 文件。

**无** Blackboard 并发写；单线程跑一场。  
**无** LangGraph checkpoint；Batch 可跳过已完成 persona 续跑（`batch/runner.py:372-382`）。  
**多租户串扰**：单用户；RAG `scope_kb_only` 按 kb_id 过滤（`kb_store.py:164-211`）。不同会话若选同一 KB 则共享知识——这是设计，不是 bug。人设 prompt 注入可能把恶意指令带进 Persona（见安全）。

序列化：Pydantic + JSON 列。进程重启不能 resume 单场。

---

## 5. 失败恢复与确定性

| 场景 | 行为 |
|---|---|
| LLM 网络错误 | `max_retries`，间隔 2s（`llm.py:417-474`） |
| JSON 坏 | 再试 1 次后 fallback turn |
| 工具异常 | `{ok:false}` 回填模型 |
| persist 失败 | 吞掉，会话继续（`session_persistence.py:74-76`） |
| WS 断线 | 会话继续（`ws_session.py:90-93`） |
| 进程被杀 | running 残留；batch 可 resume |
| Replay | 无模型/prompt/工具版本绑定到 turn；不能科学重放 |

**无** DLQ、无幂等键（turns 有 UNIQUE session+idx+role）、无 circuit breaker。

---

## 6. 质量评测

- 无 Golden Dataset / LLM-as-Judge 回归套件进入 CI。
- Coach 与 Analysis 是**业务内**评测，不是工程门禁。
- content_guard 有可重复 smoke（已跑通）。
- Prompt 变更无自动回归。

---

## 7. 入口对照

| 入口 | 是否注入 Judge+Memory |
|---|---|
| CLI `src.runner` | 是 |
| Web SessionRunner | 是 |
| BatchRunner | 是（interval 用 BATCH_* 更大） |
| `POST /agent-profile/sales/try` | 只跑 Sales，不跑完整博弈 |
