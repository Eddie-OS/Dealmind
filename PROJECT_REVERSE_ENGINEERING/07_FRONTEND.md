# 07 前端全景

技术栈：Vue 3 + TS + Vue Router + Pinia + Element Plus + ECharts + Axios + Vite 8。入口 `web/src/main.ts`。壳：`App.vue`（login 无侧栏）+ `layouts/AppShell.vue`（四组导航）。

## 1. 路由清单（22）

来源：`web/src/router/index.ts:22-166`。

| 路径 | name | 页面 | 分组 |
|---|---|---|---|
| `/login` | login | LoginView | blank |
| `/` | home | HomeView | simulation |
| `/simulation/new` | simulation-new | NewSession | simulation |
| `/simulation/live` | — | redirect → new | simulation |
| `/simulation/live/:id` | simulation-live-detail | LiveSession | simulation |
| `/simulation/history` | simulation-history | SessionHistory | simulation |
| `/simulation/detail/:id` | simulation-detail | SessionDetail | simulation |
| `/simulation/review` | — | redirect → history | simulation |
| `/batch/run` | batch-run | BatchTest | batch |
| `/batch/report` | batch-report | BatchReport | batch |
| `/batch/analysis` | batch-analysis | AnalysisReport | batch |
| `/kb/personas` | kb-personas | PersonaLibrary | kb |
| `/kb/product` | kb-product | ProductKB | kb |
| `/kb/handbooks` | kb-handbooks | HandbookManager | kb |
| `/kb/enterprise` | kb-enterprise | EnterpriseKB | kb |
| `/kb/cases` | kb-cases | SalesCases | kb |
| `/kb/excellent-phrases` | kb-excellent-phrases | ExcellentPhrases | kb |
| `/kb/sales-agent` | kb-sales-agent | SalesAgent | kb |
| `/settings/model` | settings-model | ModelSettings | settings |
| `/settings/vector` | settings-vector | VectorAdmin | settings |
| `/settings/status` | settings-status | RunningStatus | settings |
| `/settings/skills` | settings-skills | AgentSkills | settings |
| `/*` | — | → `/` | — |

守卫：无 token → `/login`（`router/index.ts:173-182`）。token 在 `sessionStorage.dm_token`。

## 2. 页面 → API 映射

| 页面 | API |
|---|---|
| LoginView | `POST /api/auth/login` |
| HomeView | `/api/dashboard/summary|trends|insights|persona_difficulty` |
| NewSession | personas/kbs/handbooks + agent-profile + sessions create/start |
| LiveSession | sessions detail/fullDetail + **WS** `/ws/session/{id}/live` |
| SessionHistory | sessions list/del/export + analysis findBySession |
| SessionDetail | fullDetail/export/promptInspect + cases from session |
| BatchTest | batch CRUD + **WS** `/ws/batch/{id}`（**无 token**） |
| BatchReport | batch detail + `/report/*` |
| AnalysisReport | `/api/analysis/jobs*` + handbook/sessions/batch/personas |
| PersonaLibrary | `/api/personas*` |
| Product/Enterprise KB | `/api/kbs*` |
| HandbookManager | `/api/handbooks*` |
| SalesCases / ExcellentPhrases | 对应 REST |
| SalesAgent | agent-profile + skills + providers |
| ModelSettings | `/api/providers*` |
| VectorAdmin | `/api/vector*` |
| RunningStatus | `/api/status*` + `/health` |
| AgentSkills | `/api/agent-skills*` |
| AppShell 健康灯 | `/health` 每 10s |

## 3. 状态管理

| Store | 文件 | 职责 |
|---|---|---|
| `useLiveSessionStore` | `stores/liveSession.ts` | WS 事件→对话流/RAG/Judge/Memory/Coach |
| `usePersonasStore` | `stores/personas.ts` | 人设列表 |
| `useKBStore` | `stores/kb.ts` | KB + 索引轮询 2s |
| `useProvidersStore` | `stores/providers.ts` | 模型供应商 |

无 Vuex。URL 仅承担路由 id。本地：`sessionStorage` token。

HTTP：`web/src/api/http.ts` Axios 拦截器加 Bearer；401 清 token。超时/错误 ElMessage。导出 URL 用 `?token=`（`sessions.ts:225-228`）。

## 4. 流式 / Agent 在 UI 中的呈现

**无 SSE。** 协议：`src/session.py:79-88` 事件名。

1. `sales_turn` / `persona_turn` → `DialogueStream` 气泡；最新条打字机（`DialogueStream.vue:66-100`）。
2. `stage_change` → 阶段虚线。
3. `judge_feedback` → 深色 Judge 卡。
4. `memory_update` + `rag_hits` → `LiveInsightsPanel`。
5. 已结束：REST `fullDetail` 匀速回放（`liveSession.ts:285-366`）。

暂停/取消：WS 下行。**无**人工改下一句再继续。

## 5. 组件关系

```
AppShell
  ├ HomeView (ECharts)
  ├ NewSession → LiveSession
  │    ├ DialogueStream
  │    └ LiveInsightsPanel
  ├ SessionHistory → SessionDetail (SessionInsights)
  ├ BatchTest / BatchReport / AnalysisReport
  ├ PersonaLibrary / KBManager / HandbookManager / SalesAgent
  └ ModelSettings / VectorAdmin / RunningStatus / AgentSkills
```

## 6. 表单、上传、i18n、权限、测试

- 上传：KB/Handbook/Persona，后缀白名单在后端；前端无统一大小限制提示。
- i18n：会话 `language` 影响 Agent，UI 本身中文硬编码。
- 权限：登录即全部菜单。无特性开关框架。
- 空/加载/错误：Element Plus + `DmEmpty`；全局 Vue error 只 `console.error`（`main.ts:11-16`）。
- 无 Storybook、无前端单测、无 E2E、无埋点 SDK。
- a11y / 响应式：侧栏固定 220px，偏桌面后台；未发现系统化 a11y。
- Bundle：未跑 build，未分析 chunk。

## 7. 关键用户旅程

见 `03` 旅程 A/B/C。前端特有风险：

- [已证实] `batchWsUrl` 不附加 token（`web/src/api/batch.ts:185-203`），与 `ws.ts:52-57` 不一致。生产鉴权下批量进度必挂。
- Vite 注释仍写后端 8000（`ws.ts:5`），代理实际 8001。
