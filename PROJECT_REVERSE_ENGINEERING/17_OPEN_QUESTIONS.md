# 17 未决问题与验证计划

凡仓库无法单独回答的项。不要把猜测写成事实。

| ID | 问题 | 为何未知 | 建议验证 | 负责人类型 |
|---|---|---|---|---|
| Q1 | 生产 `dealmind.top` 是否仍使用默认密码？ | 未读生产 `.env`，不做探测 | 运维确认 env；登录应急演练在维护窗口 | 运维 |
| Q2 | 生产是否对公网开放 `/docs`？ | 未访问生产 | 维护窗口 curl /docs | 运维 |
| Q3 | 批量 WS 在现网是否已经“看起来能用”？ | 可能有人用旧前端或临时关鉴权 | 用现网构建复现 R-BUG-01 | 前端+运维 |
| Q4 | 本机 `.env` 是否覆盖默认账密与模型？ | 按规则不读 `.env` | 用户自己打开变量名核对 | 本地开发 |
| Q5 | 44 场/2h 与 745 turn/2h SLA 是否曾达标？ | 无监控历史 | 用 `_log_usage` + batch 时间戳回放 | 产品 |
| Q6 | `outputs/` 与 DB 会话是否一一对应？ | 双写且 persist 可失败 | 抽样 session_id 对 turns 数 | 数据 |
| Q7 | 前端 `vue-tsc` / `vite build` 是否绿？ | 未装依赖、未跑 | `cd web && npm ci && npm run build` | 前端 |
| Q8 | DialogueStream 是否 v-html 未转义？ | 未逐行审每一模板 | 审组件 + XSS fixture | 安全 |
| Q9 | 生产 LLM 供应商是否不仅 DeepSeek？ | DB 可能有多 provider，未 dump | 管理页目视（掩码后） | 运维 |
| Q10 | 历史会话是否含真实顾客 PII？ | 不 dump turns | 法务/业务抽查导出 | 业务 |
| Q11 | embedder 现网 collection 维度是否健康？ | 未启动 lifespan | VectorAdmin 统计 + 一次 query | RAG |
| Q12 | `smoke_sales_prompt_render.py` 是否仅 Windows 编码问题？ | 失败在 print | 重定向到文件再跑 | 工具体验 |
| Q13 | experience KB 是否计划做 UI？ | 仅 collection 预留 | 产品确认 | 产品 |
| Q14 | MCP 是否有计划接入 Sales？ | 代码停在管理端 | 安全评审后再做 | 架构 |
| Q15 | 域名 `47.236.78.0.sslip.io` 是否仍应保留？ | Caddyfile 有 | 收紧证书名 | 运维 |

## 文档 vs 代码冲突（已裁定）

| 冲突 | 裁定 |
|---|---|
| README：尚未做 Web/RAG/DB | **已做** |
| README：下一步才 LangGraph | **未做，且不是当前运行时** |
| server 注释 port 8000 | **运行用 8001** |
| batch 模块 docstring 串行 | **代码并发** |
| README 3 YAML 人设 | **DB 为主，YAML 是种子/CLI** |

## 对分析完整性的影响

Q1–Q3 影响“明天公网上线”的**现场**判断，不改变代码层 P0 成立。  
Q7 影响前端质量门禁结论（静态上无测试）。  
Q10 影响隐私合规级别。
