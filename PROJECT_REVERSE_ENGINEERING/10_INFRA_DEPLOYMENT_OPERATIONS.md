# 10 配置、部署与运维

## 1. 环境变量清单（值已脱敏）

来源：`.env.example` + 代码 `os.getenv`。**未读取 `.env`。**

| 名称 | 用途 | 必填 | 默认 | 敏感 | 环境 |
|---|---|---|---|---|---|
| OPENAI_API_KEY | LLM | 生产/本地要跑模型 | 无 | 是 | 全 |
| OPENAI_BASE_URL | LLM 网关 | 否 | DeepSeek | 否 | 全 |
| MODEL_NAME | 主模型 | 否 | 例 deepseek-v4-pro | 否 | 全 |
| TEMPERATURE | 默认温度 | 否 | 例 1.0 | 否 | 全 |
| MAX_RETRIES | LLM 重试 | 否 | 2 | 否 | 全 |
| AUX_MODEL_NAME | 辅助模型 | 否 | deepseek-v4-flash | 否 | 全 |
| DM_AUTH_USERNAME | 登录名 | 建议改 | admin | 中 | 全 |
| DM_AUTH_PASSWORD | 登录密码 | **必须改** | 789123 | 是 | 全 |
| DM_CORS_ORIGINS | 额外 CORS | 跨域才要 | 空 | 否 | 生产跨域 |
| DM_MAX_CONCURRENT_SESSIONS | 实时会话上限 | 否 | 3 | 否 | 小内存 |
| DM_PRELOAD_EMBEDDER | 启动预加载 | 否 | 1 | 否 | 生产 1 / 本地可 0 |
| BATCH_SESSION_CONCURRENCY | 批量并行 | 否 | 代码 3 / example 8 | 否 | 批量 |
| BATCH_JUDGE_INTERVAL | 批量 Judge | 否 | 6 | 否 | 批量 |
| BATCH_MEMORY_INTERVAL | 批量 Memory | 否 | 6 | 否 | 批量 |
| ANALYSIS_TURN_WORKERS | 分析线程 | 否 | 16 | 否 | 分析 |
| LLM_MAX_IN_FLIGHT | 全局 LLM 槽 | 否 | 12 | 否 | 全 |
| HF_HOME | 生产 embedding 缓存 | 否 | service 文件指定 | 否 | 生产 |

配置优先级：进程环境 > `.env`（`load_dotenv override=False`）> 代码默认。  
Feature flag：无独立系统，用 env 与 DB skills/profile。  
Secret：明文 `.env` + SQLite，无 vault。

## 2. 从空白机器到本地运行（命令来自仓库）

```bash
# 后端
pip install -r requirements.txt
cp .env.example .env   # 填 OPENAI_* 与务必改 DM_AUTH_*
python scripts/restore_conversations_db.py   # 若只有 .db.gz
python -m src.runner --help                  # [已证实] 可用
# 开发 API（与 Vite 对齐用 8001，不是注释里的 8000）
uvicorn src.api.server:app --reload --port 8001

# 前端
cd web
npm install
npm run dev          # :5173，代理 /api /health /ws → 8001
```

[待验证] 本分析未执行 `npm install` / 未长时间跑 lifespan（会下载/加载 embedding）。

CLI 单场：`python -m src.runner --persona personas/price_sensitive_student.yaml --max-rounds 6`（会打真实 LLM，未在本次执行）。

## 3. 生产发布路径

```bash
# 将整包放到 /opt/dealmind（含 data、web/dist、.env）
cd /opt/dealmind && bash deploy/setup.sh
# 可选
bash deploy/harden.sh
```

`setup.sh`：venv、pip、校验 `.env` 有 OPENAI_API_KEY、Caddy、systemd enable。  
单元：`deploy/dealmind-api.service` → `uvicorn ... --host 127.0.0.1 --port 8001`。  
Caddy：`dealmind.top` / `www` / `47.236.78.0.sslip.io`；静态 `web/dist`；反代 `/api` `/health` `/ws`。

**无 Docker / K8s / Helm / Terraform / CI。**  
回滚：靠 git 旧包 + 旧 `conversations.db`；无发布策略文档。  
DB 迁移：随进程启动 `init_schema`，无独立 migrate job。

## 4. 健康、日志、监控

| 能力 | 有无 | 证据 |
|---|---|---|
| /health | 有 | `server.py:186` |
| 压测脚本 | 有，只打 health | `deploy/loadtest.sh` |
| 文件日志 | logs/app.log 日滚 30 天 | `config.py:81-147` |
| journald | 有 | service + setup 提示 |
| Metrics/Trace/Alert/SLO | **无** | 全仓未找到 |
| 备份 cron | **无** | 仅 `restore_conversations_db.py` + 入库 gz |
| 优雅关闭 | **无** | lifespan 只打日志 |

On-call 线索：看 `journalctl -u dealmind-api -f` 与 RunningStatus 页日志。无 pager。

## 5. 容量与扩缩

垂直：调 `BATCH_*`、`LLM_MAX_IN_FLIGHT`、机器内存；2G 机器配 swap + MemoryMax 1400M（`harden.sh`）。  
水平：不支持（SQLite 文件锁 + 内存 runner 注册表）。

## 6. 本地 vs 生产差异

| 项 | 本地 | 生产 |
|---|---|---|
| 前端 | Vite 5173 + 代理 | Caddy 静态 |
| API 端口 | 8001（应为） | 127.0.0.1:8001 |
| CORS | 默认 localhost:5173 | 同源通常不触发 |
| Embed 预加载 | 可关 | 默认开 |
| TLS | 无 | Caddy LE |

## 7. 排障入口

1. `/health` 是否 200。
2. `.env` 是否在 import 前生效（embedder 维度）。
3. `DM_PRELOAD_EMBEDDER` 启动是否 OOM。
4. 429：实时会话槽满。
5. 批量 WS 1008：缺 token（见风险 R-BUG-01）。
6. RAG 0 命中：embedder 模型与 collection 维度不一致（`server.py:29-32` 注释）。
