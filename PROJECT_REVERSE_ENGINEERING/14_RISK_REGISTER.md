# 14 风险台账

严重度：Critical / High / Medium / Low。优先级：P0 立即 / P1 短期 / P2 中期 / P3 长期。

---

### R-SEC-01 默认弱口令

- **领域**：安全
- **严重度**：Critical
- **证据等级**：[已证实]
- **代码证据**：`src/api/auth.py:28-33`；`.env.example:8-9`；`git show a7b4def`
- **现状**：代码 fallback `admin/789123`，提交明确恢复该密码
- **触发**：公网部署未改 env
- **影响**：数据与 LLM 额度被接管
- **建议**：删除代码默认值，缺 env 则拒绝启动；强制首次改密
- **影响范围**：`auth.py`、部署文档
- **验证**：无 env 时进程不监听；默认账密 401
- **修复优先级**：P0

### R-SEC-02 MCP 任意命令

- **领域**：安全
- **严重度**：Critical
- **证据等级**：[已证实]
- **代码证据**：`src/api/routes_agent_skills.py:303-375`；`src/tools/mcp_client.py:36-57`
- **现状**：已登录可 probe/call 任意 command
- **触发**：token 泄漏或内部误用
- **影响**：主机 RCE
- **建议**：生产禁用或命令白名单；与 Sales 运行时隔离已存在，保持
- **影响范围**：agent-skills 路由、mcp_client
- **验证**：非白名单 command 被拒
- **修复优先级**：P0

### R-SEC-03 API Key 明文回传

- **领域**：安全
- **严重度**：High
- **证据等级**：[已证实]
- **代码证据**：`src/api/routes_providers.py:69-97`；`models.py` api_key 列
- **现状**：列表接口返回完整密钥
- **触发**：任一已登录浏览器、XSS、截屏
- **影响**：模型账号被盗用
- **建议**：列表掩码；仅创建时写；落库加密
- **影响范围**：providers 路由、前端 ModelSettings
- **验证**：GET 响应无完整 key
- **修复优先级**：P0

### R-SEC-04 无 LLM 配额

- **领域**：成本 / 稳定
- **严重度**：High
- **证据等级**：[已证实]
- **代码证据**：batch/analysis/try 均可触发 LLM；仅 semaphore
- **触发**：误点批量/分析或撞库后刷接口
- **影响**：费用失控、打满供应商限流
- **建议**：日预算、job 级 max_calls、管理接口独立开关
- **影响范围**：llm.py、runners、auth
- **验证**：超预算 429 且不调用供应商
- **修复优先级**：P0

### R-BUG-01 批量 WS 缺 token

- **领域**：可用性
- **严重度**：High
- **证据等级**：[已证实] 代码；[待验证] 生产是否已绕过
- **代码证据**：`web/src/api/batch.ts:185-203` vs `web/src/api/ws.ts:52-57`
- **现状**：`new WebSocket(batchWsUrl)` 无 `?token=`
- **触发**：AuthMiddleware 开启（生产默认）
- **影响**：批量进度/取消不可用
- **建议**：复用 `WsClient` 或同样附加 token
- **影响范围**：`batch.ts`、BatchTest.vue
- **验证**：登录后 batch WS readyState=OPEN
- **修复优先级**：P0

### R-SEC-05 OpenAPI 与日志接口

- **领域**：安全
- **严重度**：Medium
- **证据**：`auth.py:73-76`；`routes_status.py` logs/system
- **建议**：生产 `docs_url=None`；日志接口脱敏
- **优先级**：P1

### R-SEC-06 Token 查询串

- **领域**：安全
- **严重度**：Medium
- **证据**：WS 与 export URL
- **建议**：短时 ticket
- **优先级**：P1

### R-SEC-07 上传无上限 / RAG 投毒

- **领域**：安全 / 稳定
- **严重度**：Medium–High
- **证据**：`routes_kb.py:168-190`；解析进 Chroma
- **建议**：大小限制 + 病毒/内容策略
- **优先级**：P1

### R-SEC-08 依赖未锁定

- **领域**：供应链
- **严重度**：Medium
- **证据**：`requirements.txt` 仅 `>=`
- **建议**：pip-tools / poetry lock + audit
- **优先级**：P2

### R-REL-01 persist 吞异常

- **领域**：一致性
- **严重度**：High
- **证据**：`session_persistence.py:74-76`
- **影响**：WS 有对话、复盘缺轮
- **建议**：失败计数 + session error 标记
- **优先级**：P1

### R-REL-02 无单场 checkpoint

- **领域**：可靠
- **严重度**：Medium
- **证据**：进程杀后 running 残留
- **建议**：标 stale + 可选从 turns 续跑
- **优先级**：P2

### R-REL-03 优雅关闭缺失

- **领域**：运维
- **严重度**：Medium
- **证据**：`server.py:133-134`
- **建议**：lifespan 取消 runner 并等待
- **优先级**：P1

### R-DOC-01 README 过时 / 端口 8000 vs 8001

- **领域**：可维护
- **严重度**：Medium
- **证据**：`README.md`；`server.py:7` vs `vite.config.ts:17`
- **建议**：README 改为 Web 主路径，统一 8001
- **优先级**：P1

### R-QA-01 无 CI 与单元测试

- **领域**：质量
- **严重度**：High
- **证据**：0 test_*.py，无 workflows
- **建议**：先把 content_guard + auth + stage 迁 pytest 并进 CI
- **优先级**：P1

### R-MAINT-01 超大文件

- **领域**：可维护
- **严重度**：Medium
- **证据**：db.py 2425；AnalysisReport.vue 2767
- **建议**：按表/按报告章节拆分
- **优先级**：P2

### R-AI-01 Prompt 注入与无评测门禁

- **领域**：AI 安全/质量
- **严重度**：High
- **证据**：用户 persona/KB 进上下文；无 eval CI
- **建议**：不可信内容分栏；小黄金集
- **优先级**：P1–P2

### R-OBS-01 Token 不落库 / 无监控

- **领域**：成本/SRE
- **严重度**：Medium
- **证据**：`llm.py:344-364`；无 metrics
- **建议**：usage 表 + 告警
- **优先级**：P1

### R-PRIV-01 明文 PII 与密钥

- **领域**：隐私
- **严重度**：High
- **证据**：turns.content；llm_providers.api_key
- **建议**：密钥加密；对话保留策略
- **优先级**：P1

---

## 修复波次

**立即（P0）**：R-SEC-01/02/03/04，R-BUG-01  
**短期（P1）**：测试门禁、persist 可见失败、文档端口、docs 关闭、usage 落库、上传限制  
**中期（P2）**：拆大文件、checkpoint、锁依赖  
**长期（P3）**：多租户、评测平台、水平扩展
