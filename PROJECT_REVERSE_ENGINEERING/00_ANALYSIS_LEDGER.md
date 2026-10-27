# 00 分析台账

**项目**：DealMind（仓库目录名 `Langraph`，远程 `Eddie-OS/Dealmind`）  
**分析日期**：2026-09-01  
**分析深度**：生产级 / 全量  
**分析对象**：当前检出 `main` @ `e10f247798fe4836a3299380c6bd8d068673b956`  
**输出目录**：`PROJECT_REVERSE_ENGINEERING/`  
**原则**：只读产品代码；仅新增本目录文档；不打印 `.env` 真实值。

---

## 1. 版本基线

| 项 | 值 | 证据等级 |
|---|---|---|
| 仓库根 | `F:/Langraph` | [已证实] `git rev-parse --show-toplevel` |
| 当前分支 | `main`（跟踪 `origin/main`） | [已证实] `git status -sb` |
| HEAD | `e10f247` · `data: 纳入全部历史数据（会话输出、向量库、手册与数据库快照）` | [已证实] `git log -1` |
| 作者 / 时间 | ansonstudy29-design · 2026-08-14 11:40:51 +0800 | [已证实] |
| 工作区 | 干净，无未提交修改 | [已证实] `git status --porcelain` 为空 |
| 子模块 / LFS | 未发现 | [已证实] |
| 远程 | `git@github.com:Eddie-OS/Dealmind.git` | [已证实] `git remote -v` |
| 近期关键提交 | `a7b4def` 恢复默认登录密码 admin/789123；`24c019d` 项目名统一为 DealMind；`90efec8` 上线鉴权与部署 | [已证实] `git log -5` |
| 适用指令文件 | 无 `AGENTS.md` / `CLAUDE.md` / `CONTRIBUTING` | [已证实] 全仓搜索 0 命中 |
| 人类文档 | `README.md`（偏 CLI，过时）、`docs/product_dev_master.md`、`docs/handbook_analysis_dev_spec.md` | [已证实] 与代码存在漂移，见 `17_OPEN_QUESTIONS.md` |

---

## 2. 执行日志

| 时间 | 阶段 | 动作 | 结果 |
|---|---|---|---|
| T0 | 0 | Git 基线、目录盘点、`git ls-files` | 跟踪文件 2795；`outputs/` 占 2431 |
| T0 | 0 | 阅读 README / `.env.example` / `requirements.txt` / `web/package.json` | README 仍写 CLI-only 蓝图，代码已是 FastAPI+Vue 全栈 |
| T1 | 1–6 | 并行深挖后端 API、多智能体、前端+DB、基础设施/安全/测试 | 见各分报告 |
| T1 | 核验 | 抽读 `auth.py` / `server.py` / `session.py` / `models.py` / `agents.py` / `batch.ts` / `vite.config.ts` | 关键结论复核通过 |
| T2 | 11 | 安全动态验证（无外部副作用） | 见下节 |

---

## 3. 动态验证命令与结果

| 命令 | 目的 | 结果 | 耗时量级 |
|---|---|---|---|
| `python -m src.runner --help` | CLI 入口可导入 | 退出 0，参数与 `src/runner.py` 一致 | <2s |
| `python -c "from src.api.server import app; print(len(app.routes))"` | 路由可装载（不触发 lifespan） | `routes 112` | ~3s |
| `python scripts/smoke_test_perf_config.py` | 性能常量 | `OK`：并发默认 3/16/12，辅助模型 `deepseek-v4-flash` | <1s |
| `python scripts/smoke_stage_quota.py` | 阶段配额算法 | 全部断言通过 | <1s |
| `python scripts/smoke_judge_prompt_render.py` | Judge prompt 渲染 | 通过，写出 `logs/v03_judge_prompt_rendered.md`（14335 chars） | <1s |
| `python scripts/smoke_persona_prompt_render.py` | Persona prompt 渲染 | 渲染成功；Windows 控制台对 `✅` 报 NativeCommandError，脚本本身完成 | <1s |
| `python scripts/smoke_sales_prompt_render.py` | Sales prompt 渲染 | **失败**：`ValueError: I/O operation on closed file`（Windows 编码/stdout 关闭，非业务逻辑） | <1s |
| `python scripts/smoke_test_content_guard_dedup.py` | 事实护栏去重 | ALL ASSERTIONS PASSED | <1s |
| `python scripts/smoke_test_content_guard_handbook.py` | Handbook 证据放行 | ALL ASSERTIONS PASSED | <1s |
| `python -m src.runner --test-llm` | LLM 连通 | **未执行**（会调用真实付费模型） | — |
| `npm run build` / `vue-tsc` | 前端类型检查 | **未执行**（需安装 node_modules，本环境未确认） | — |
| 启动 uvicorn + 真实会话 | E2E | **未执行**（会预加载 embedding、可能打 LLM） | — |

未执行原因均符合提示词：禁止真实付费模型批量调用、禁止擅自安装全局依赖。

---

## 4. 覆盖进度

| 类别 | 跟踪文件约数 | 检查深度 | 状态 |
|---|---|---|---|
| `src/**/*.py` | 85 | 核心路径全文；其余重点 | 完成 |
| `web/src/**/*.{ts,vue}` | 53 | 路由/API/store 全文；大页面重点 | 完成 |
| `prompts/*` | 8 | 重点（模板变量与调用点） | 完成 |
| `personas/*.yaml` | 3 | 全文 | 完成 |
| `deploy/*` | 6 | 全文 | 完成 |
| `docs/*` | 3 | 重点 | 完成 |
| `scripts/*.py` | ~53 | smoke 重点；一次性诊断脚本分类 | 完成 |
| `.env.example` / `requirements.txt` / `README.md` | 根配置 | 全文 | 完成 |
| `outputs/**` | 2431 | 运行产物，抽样确认结构 | 识别为产物 |
| `data/chroma/**` / `*.bin` / `*.pickle` | 向量库 | 用途识别，不逐行 | 识别 |
| `data/conversations.db*` | 1+gzip | schema 对照，不 dump 内容 | 识别 |
| `web/node_modules` / `.venv` | 未跟踪 | 第三方 | 排除 |
| 中文产品/截图/训练 zip | 若干 | 文档/素材 | 与运行弱相关 |

**第一方源代码+配置覆盖率（按文件）**：约 **98%** 已至少重点检查。  
**全仓跟踪文件覆盖率（含 outputs 历史会话）**：关键代码 100% 分类；`outputs/` 按产物处理，不逐行阅读。

不得宣称“每一行 outputs JSON 都读过”——那是会话快照，不是源代码。

---

## 5. 已知 / 未知 / 阻塞

### 已知（有代码证据）

- 产品是「多人设销冠压力测试 + 复盘/分析」Web+CLI 系统，品牌 DealMind。
- 编排是自研 `run_session` 循环，**不是 LangGraph**（仓库名历史遗留）。
- 可达 Agent：Persona、Sales、Judge、Memory、Coach + 若干辅助 LLM。
- 单管理员鉴权，默认密码硬编码；MCP 管理接口可启任意子进程。
- 主库 SQLite `data/conversations.db` + Chroma `data/chroma/`。
- 生产部署：`/opt/dealmind` + systemd + Caddy，域名 `dealmind.top`。

### 未知 / 待验证

- 生产环境是否已改默认密码、是否仍对公网开放 `/docs`。
- 批量 WebSocket 在启用鉴权后是否实际不可用（代码路径缺 `?token=`）。
- 当前生产流量、LLM 单价、真实 SLA 达成率。
- `outputs/` 与 DB 中会话是否完全一致。
- 前端 `vue-tsc` / `vite build` 在本机是否通过。

### 阻塞

- 无 LLM Key 的安全测试环境 → 不能验证真实会话闭环。
- 未安装确认前端 node_modules → 未跑前端构建。
- 不读取 `.env` → 无法确认本机是否覆盖默认密码。

---

## 6. 阶段计划（已执行）

| 阶段 | 产物 | 状态 |
|---|---|---|
| 0 基线 | 本文件 + `02_REPOSITORY_ATLAS.md` | 完成 |
| 1 业务 | `03_BUSINESS_AND_DOMAIN.md` | 完成 |
| 2 架构 | `04_SYSTEM_ARCHITECTURE.md` | 完成 |
| 3 多智能体 | `05_MULTI_AGENT_SYSTEM.md` | 完成 |
| 4–6 前/后/库 | `07` `08` `09` | 完成 |
| 3.4–3.6 LLM/工具/RAG | `06_LLM_PROMPTS_TOOLS_RAG.md` | 完成 |
| 7–10 运维/安全/测试/成本 | `10`–`13` | 完成 |
| 风险与接手 | `14` `15` `16` `17` | 完成 |
| 总报告 | `FINAL_REPORT.md` | 完成 |
