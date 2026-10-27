# 12 测试、评测与代码质量

## 1. 测试版图

| 类型 | 现状 |
|---|---|
| 单元测试 `test_*.py` | **0** |
| pytest 配置 | `.gitignore` 预留 cache，无套件 |
| 集成 / 契约 / E2E | 无 |
| 性能 | `deploy/loadtest.sh` 只打 `/health` |
| 安全测试 | 无 |
| AI Evals / Golden | 无工程化评测集 |
| CI | 无 `.github/workflows` |

### Smoke（15+，手工）

| 脚本 | 是否打 LLM | 本次结果 |
|---|---|---|
| `smoke_test_perf_config.py` | 否 | PASS |
| `smoke_stage_quota.py` | 否 | PASS |
| `smoke_judge_prompt_render.py` | 否 | PASS |
| `smoke_persona_prompt_render.py` | 否 | 渲染成功，控制台 emoji 编码噪音 |
| `smoke_sales_prompt_render.py` | 否 | FAIL：Windows stdout closed |
| `smoke_test_content_guard_dedup.py` | 否 | PASS |
| `smoke_test_content_guard_handbook.py` | 否 | PASS |
| `smoke_test_analysis_pipeline.py` 等 | 部分可能需服务/LLM | 未跑 |
| `smoke_test_deepseek_thinking.py` | 是 | 未跑 |
| `smoke_truthfulness.py` / localization | 视实现 | 未跑 |

断言质量：content_guard 与 stage_quota **有真实断言**。多数 smoke 是渲染/打印。

## 2. 关键能力 × 测试缺口

| 能力 | 风险 | 现有 | 缺口 |
|---|---|---|---|
| run_session 终止/floor | 早停/死循环 | 无 | 应用 Judge 假对象的单元测试 |
| 阶段转移校验 | 跳阶段 | YAML+函数 | 缺 pytest |
| content_guard | 幻觉价格 | 2 个 smoke PASS | 应入 CI |
| 鉴权中间件 | 未授权访问 | 无 | 保护路径表测试 |
| batch WS token | 生产不可用 | 无 | 前端/契约测试 |
| persist_event | 丢轮 | 无 | 注入失败断言 |
| RAG 维度 | 0 命中 | 无 | embedder 维度测试 |
| API 创建会话 | 回归 | 无 | 用 TestClient + 临时 DB |
| Prompt 变更 | 质量回退 | 无 | 小黄金集 |

## 3. 静态质量

| 项 | 现状 |
|---|---|
| 类型 | Python 无 mypy 门禁；前端 `vue-tsc -b` 在 build 脚本，未验证 |
| Lint/format/pre-commit | 未发现 |
| TODO/FIXME | src/web 几乎无 |
| 超大文件 | AnalysisReport.vue 2767；db.py 2425；agents.py 1484 |
| 错误吞噬 | persist、preflight、多处 `except: log` |
| 隐式全局 | registry、client、embedder、active runners |
| 重复 | KB 产品/企业页薄包装；报告聚合巨大 |

技术债优先：拆 `db.py` / 大 Vue、补 TestClient 套件、锁定 Python 依赖。

## 4. 文档一致性

README 仍是 CLI MVP + v2 蓝图，与 FastAPI/Vue/RAG **严重过时**（见 `02`）。  
`docs/product_dev_master.md` 较接近现状，仍可能表数量落后（现 20+1）。

## 5. 修改影响面

改 `session.py` / `agents.py` / `schema.py` / `llm.py` 影响所有入口。  
改 `db.py` 影响几乎所有 API。  
改销冠 prompt（DB 或文件）无自动回归。
