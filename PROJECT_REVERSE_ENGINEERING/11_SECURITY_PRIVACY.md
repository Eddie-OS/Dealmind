# 11 安全与隐私

审查方式：静态代码 + 配置。**未**对生产主机做利用或导出数据。

## 1. 认证与会话

| 项 | 现状 | 证据 |
|---|---|---|
| 模型 | 单管理员，无 SSO/OAuth/RBAC | `src/api/auth.py:1-14` |
| 默认口令 | `admin` / `789123` | `auth.py:28-33`；`.env.example:8-9`；提交 `a7b4def` |
| Token | SHA256(`user:pass:dealmind-auth-v1`)，无过期/吊销/刷新 | `auth.py:36-39` |
| HTTP | Bearer | `auth.py:79-89` |
| WS / 导出 | `?token=` | `auth.py:90-99`；`web/src/api/ws.ts:52-57` |
| 存储 | 浏览器 sessionStorage | `router/index.ts:3-20` |
| 暴力破解 | 无锁定、无速率限制 | 登录接口裸露 |
| 密钥轮换 | 改密码即全部失效（确定性派生） | 设计如此 |

保护范围：`/api` `/ws`。放行：login、OPTIONS、以及一切非该前缀（含 `/docs`、`/health`）。

## 2. 授权

登录即超级管理员：可删库级向量、读全部对话、读 API Key、启 MCP。无对象级 ACL、无租户。

## 3. OWASP 与 AI 风险条目

### R 路径：默认凭据公网暴露

- **证据**：硬编码 fallback + example。
- **路径**：扫描到 `dealmind.top` → `/api/auth/login` → 默认账密。
- **影响**：全部数据与 LLM 额度。
- **条件**：未改 env。
- **严重度**：Critical。

### OpenAPI 未鉴权

- **证据**：`_is_protected` 只匹配 `/api` `/ws`（`auth.py:73-76`）。
- **影响**：接口枚举。
- **严重度**：Medium。

### Provider / WebSearch Key 明文

- **证据**：`models.py` api_key 列；`GET /api/providers` 原样返回（`routes_providers.py:95-97`）；skills config 返回 web key。
- **影响**：密钥被 XSS/共用电报泄露。
- **严重度**：High。

### MCP / test_tool = 命令执行面

- **证据**：`routes_agent_skills.py:303-375`；`mcp_client.py:36-57` 任意 command + 合并 environ。
- **影响**：持 token 者 RCE（单用户下即管理员自己，但 token 泄漏=主机沦陷）。
- **严重度**：Critical。
- **模型单方面**：Sales **不能**调 MCP；只能调 registry 白名单。库存/促销为示意数据，非真实下单。

### 批量 WS 无 token

- **证据**：`web/src/api/batch.ts:185-203` 直连无 query。
- **攻击/失败**：生产更可能是 **拒绝服务式功能损坏**（1008），不是未授权订阅（连不上）。
- **严重度**：High（可用性）。

### Token 进 URL

- **影响**：Caddy/access log、Referer、浏览器历史。
- **严重度**：Medium。

### SSRF

- web_search 只打固定 provider URL，8s 超时（`web_search.py:29,96-100`）。销冠路径锁域名。管理端 test_web_search **不锁域名**但仍走 provider，不是任意 URL fetch。
- **严重度**：Low–Medium。未发现通用 URL 抓取器。

### 上传

- UUID 重命名 + 后缀白名单（`routes_kb.py:168-190`）。路径穿越未发现。
- KB **无大小上限**（Handbook 50MB）。
- **严重度**：Medium（磁盘/解析 DoS）。
- RAG 投毒：上传即进检索，无内容消毒。High（完整性）。

### Prompt Injection

- Persona `prompt_text`、KB 网页结果进入上下文。
- Judge/Persona 靠自然语言护栏，无隔离层。
- content_guard 只管数字型号（smoke 已证实有效）。
- **严重度**：High（完整性/越狱），不直接 RCE（除非管理员去配 MCP）。

### XSS / CSRF

- 前端展示对话 Markdown/HTML 是否转义：[待验证] 需审 DialogueStream 渲染。Element Plus 默认文本节点较安全。
- CSRF：Bearer（非 Cookie）降低风险；CORS 白名单 + credentials。

### 日志泄漏

- `/api/status/logs` 可读 app.log；LLM usage 不含 key（`Settings.redacted`）。对话可能进日志。
- **严重度**：Medium。

### 供应链

- Python 依赖 `>=` 无 lock。前端有 package-lock。
- 无 CI 漏洞扫描、无 SBOM。
- **严重度**：Medium。

## 4. 安全控制是否只在前端？

否。鉴权在 ASGI 中间件，后端强制。前端守卫只是体验。  
工具白名单在后端 registry。playbook_action 服务端校验。  
**但是**：一旦通过登录，后端不再做细粒度授权。

## 5. 隐私

- 对话、人设、手册全文、案例均明文 SQLite。
- 无字段加密、无 retention、无删除权流程、无 audit log。
- 备份 gz 含全库。
- 模拟对话仍可能含真实客户话术（若从门店导入）。

## 6. 建议验证（不要在生产利用）

1. 本地改掉默认密码后确认旧 token 失效。
2. 未登录访问 `/docs`、`/api/sessions`。
3. 登录后确认 providers 响应是否含完整 key。
4. 浏览器连 `/ws/batch/1` 无 token，期望 1008。
5. 依赖 `pip audit` / `npm audit`（本次未跑，避免网络安装）。
