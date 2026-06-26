# 多人设销冠压力测试引擎 — 最终版（Web 产品形态）

> 版本：v4（产品形态优先 + 真实对话 + 双格式人设 + 预填语料 + 进阶工具能力）  
> 起点：MVP 命令行引擎已跑通（src/agents.py, judge.py, memory.py, coach.py, session.py, runner.py, output_writer.py）  
> 目标：本地 Web 应用，4 大板块构成左侧导航，所有 MVP 能力升级为可视化操作；销冠 Agent 持续学习成为"世界级销售"  
> 原则：Karpathy Guidelines（先想后做、最小代码、外科手术式改动、目标驱动可验证）

---

## 0. 全局约束（每个阶段都适用）

1. **垂直切片交付**：每个阶段必须同时交付「前端可见 + 后端配套 + 现有引擎适配」，不接受"只做后端等以后补前端"
2. **MVP 引擎不重写**：`src/agents.py / judge.py / memory.py / coach.py / session.py / output_writer.py` 的核心业务逻辑保持不动，只通过新增模块包装 / 扩展
3. **验收命令必须可执行**：每个阶段验收都是"执行 X 操作，看到 Y 结果"，不接受"看起来能用"
4. **每个阶段 0.5~2 天**，超过就再拆
5. **失败有兜底**：新模块出错不能让 MVP 命令行引擎也跑不通
6. **中文 UI / 中文文档**：所有面向用户的文案、字段说明、提示信息都用中文
7. **Definition of Done**：每阶段完成 = 功能验收清单全部通过 + FastAPI 接口含 docstring（自动生成 /docs）。不强制单测和截图

---

## 1. 产品形态：4 大板块 × 13 阶段（+ 1 进阶阶段）

### 1.1 左侧导航（最终形态）

```
┌──────────────────┬────────────────────────────────────┐
│ 模拟运营         │  (主内容区根据左侧选中项切换)       │
│  · 首页总览      │                                    │
│  · 新建对话      │                                    │
│  · 对话现场      │                                    │
│  · 会话历史      │                                    │
│  · 会话复盘      │                                    │
│                  │                                    │
│ 规模化测试       │                                    │
│  · 批量测试      │                                    │
│  · 批量报告      │                                    │
│                  │                                    │
│ 知识与资产       │                                    │
│  · persona人设库 │                                    │
│  · 产品知识库    │                                    │
│  · 企业知识库    │                                    │
│  · 销售案例集    │                                    │
│                  │                                    │
│ 系统设置         │                                    │
│  · 模型设置      │                                    │
│  · 向量库管理    │                                    │
│  · 销冠技能配置  │  ← Stage 14 进阶                  │
│  · 运行状态      │                                    │
└──────────────────┴────────────────────────────────────┘
```

### 1.2 阶段总览

| # | 阶段 | 板块 | 估时 |
|---|------|-----|------|
| 0 | 项目骨架：Vite+Vue3+Element Plus 前端 + FastAPI 后端 + 左导航 13 空页 | 全局 | 1 天 |
| 1 | 基础设施：SQLite + 多 provider 配置表 + 日志 + /health | 后端 | 1 天 |
| 2 | **模型设置**（多 provider 管理：DeepSeek/OpenAI/通义/Moonshot/...） | 板块 4 | 1.5 天 |
| 3 | **persona 人设库**（**双格式**：prompt_based + structured，**44 个 panel 预填 + LLM 抽参**） | 板块 3 | 2.5 天 |
| 4 | **产品/企业知识库**（多格式上传 `.txt/.md/.pdf/.pptx/.docx/.xlsx` + 双 collection + **训练文件预填**） | 板块 3 | 2.5 天 |
| 5 | **向量库管理** | 板块 4 | 0.5 天 |
| 5.5 | ⭐ **渐进式对话引擎改造**（销售先开口 + 开场白模板 + 早结束机制 + 阶段比例重排 + 字数动态约束） | 引擎层 | 1 天 |
| 6a | **新建对话 + 简单对话现场**（WebSocket 实时推流 + 基础三栏布局） | 板块 1 | 1.5 天 |
| 6b | **双 KB 接入 + 实时画像可视化**（销冠 RAG 检索 + 右栏实时数据） | 板块 1 | 1 天 |
| 7 | **会话历史 + 复盘 + 导出**（4 tabs：对话/Coach/Judge/画像） | 板块 1 | 1.5 天 |
| 8 | **首页总览**（4 卡片：总会话数 / Persona 总数 / 平均质量分 / 成交率） | 板块 1 | 1 天 |
| 9 | **批量测试**（顺序串行 + 进度监控） | 板块 2 | 1.5 天 |
| 10 | **批量报告**（聚合图表 + Training Guide 导出） | 板块 2 | 1 天 |
| 11 | **销售案例集**（三轨入库 + **训练文件案例预填**） | 板块 3 | 1.5 天 |
| 12 | **运行状态** + 整体 UX 打磨 | 板块 4 | 1 天 |
| **14** | **销冠技能配置**（FunctionCall 改造 + RAG/WebSearch/MCP 工具，**进阶可选**） | 板块 4 | 3~5 天 |

主线 13 阶段约 **18 天**；Stage 14 是后续进阶，跑稳前面再说。

---

## 2. 关键技术决策汇总

### 2.1 基础选型（D1~D7）

| # | 决策 | 选定方案 |
|---|------|---------|
| D1 | persona LLM 辅助生成 | 双通道：① 上传 .json/.txt/.md ② 文本框输入 → LLM 按维度生成 |
| D2 | 文件上传支持格式 | **.txt / .md / .pdf / .pptx / .docx / .xlsx**（依赖：pypdf, python-pptx, python-docx, openpyxl） |
| D3 | 产品库 vs 企业库 | 两个独立 Chroma collection：`product_knowledge`、`enterprise_knowledge` |
| D4 | 销售案例集入库 | 三轨：A. Judge 综合分 ≥ 8.0 自动 + B. Coach 的 what_worked 自动 + C. 人工"收藏为案例" |
| D5 | 用户登录 | 不做，单人本地 |
| D6 | 模型设置 | 多 provider 配置中心，支持 6 种预设 + 自定义，可启用/禁用/设默认/连通性测试 |
| D7 | 批量测试 | 顺序串行 |

### 2.2 真实对话改造（R1~R3）

| # | 决策 | 选定方案 |
|---|------|---------|
| R1 | 默认 max_rounds | **50**（实际可在 8~50 之间动态结束，由 Persona 状态 / Judge 判定） |
| R2 | 销售开场白 | el-select 含 **5 个内置模板 + 「自定义」**（选自定义时切 textarea） |
| R3 | demo 模式 | **完全废弃**，统一渐进式真实对话 |

### 2.3 训练资产融合（N1~N5）

| # | 决策 | 选定方案 |
|---|------|---------|
| N1 | persona 格式 | **同时支持两种**：每个 persona 既有 prompt 文本，也有量化 pressure_profile。导入 prompt_based 时**自动用 LLM 抽取量化参数**，详情页可手动调 |
| N2 | .xlsx 支持 | **支持**（openpyxl，按行/sheet 切片） |
| N3 | 44 个 panel persona 预填 | **启动时若 personas 表空，自动批量导入并 LLM 抽取量化参数** |
| N4 | 训练文件销售语料 | **启动时若知识库为空，自动按规则分类导入到产品库/企业库/案例集**；后期 Web 持续上传 |
| N5 | MVP 虚构「智学Pro」 | **删除**，data/product.md 和 personas/*.yaml 全部删，换华为 MatePad |

### 2.4 选型补充

| 项 | 选定 | 理由 |
|----|------|------|
| Embedding | bge-small-zh-v1.5（本地 ~100MB） | 离线、中文质量足够 |
| 向量库 | Chroma（PersistentClient） | 内置持久化 |
| 数据库 | SQLite | 单文件、`sqlite3` 直接查 |
| 前端 | Vue3 + Vite + Pinia + Element Plus + ECharts | 已选 Vue |
| 后端 | FastAPI + Uvicorn + WebSocket | Python 生态 |
| 文件解析 | pypdf / python-pptx / python-docx / openpyxl | 标准方案 |
| WebSocket | FastAPI 内置 | 无需 |
| 后台任务 | 线程池 + asyncio.Queue（避免 Celery 重量级） | 单机 |

---

## 3. 资产清单（启动时自动导入）

### 3.1 Persona 库

| 来源 | 数量 | 格式 |
|------|------|------|
| `训练文件/2.1 消费者人设.json`（panel 63556） | 44 | prompt_based → 启动时 LLM 抽参 |

### 3.2 产品知识库（默认 KB 名"华为 MatePad 12X"）

| 文件 | 类型 |
|------|------|
| 1.2 HUAWEI Tablet Products Introductory Course.pptx | 产品介绍 |
| 2. Sales Talk & Demo Guide.pptx | 销售话术 + Demo |
| 7. FAQ.xlsx | 产品 FAQ |

### 3.3 企业知识库（默认 KB 名"销售方法论"）

| 文件 | 类型 |
|------|------|
| 4.1 The Retail Doctors Guide.pdf | 零售经营书 |
| 4.2 The Presentation Secrets of Steve Jobs.pdf | 演讲秘诀书 |
| 5. Instore Training Guide.pptx | 店内培训指南 |

### 3.4 销售案例集（预填）

| 文件 | 类型 |
|------|------|
| Country R_Arman Grigorian_MatePad 12X.pptx | 各国案例 |
| LATAM_MEXICO_MATEPAD 12X_ALBERTO DANIEL CRUZ.pptx | 各国案例 |
| MEA - UAE - Matepad 12X - Jeofrey B Mendviel.pptx | 各国案例 |
| MEA - UAE - Matepad 12X - Yassin Ahmed.pptx | 各国案例 |

---

# Stage 0：项目骨架（前端 + 后端 + 左导航占位）

**Delta**：
- 新增：`web/`（Vite 项目）、`src/api/`（FastAPI）
- 修改：`requirements.txt` 追加 fastapi/uvicorn
- 不动：所有 MVP 业务模块

**主要任务**：
1. `web/` 用 `npm create vite@latest` 初始化 Vue3 + Pinia + vue-router + Element Plus + axios + echarts
2. 左侧导航 + 4 板块 14 子菜单（每个对应空页面显示「WIP」）—— Stage 14 的「销冠技能配置」可先放占位
3. `src/api/server.py`：FastAPI 启动，`/health` 返回 ok，CORS 允许 `http://localhost:5173`
4. 顶部 Header：项目名"销冠压力测试引擎" + 右上角静态绿点

**验收清单**：
- [ ] `cd web && npm run dev` → 浏览器 `http://localhost:5173` 能看到左导航
- [ ] 点击 14 个子菜单都能切换路由（页面显示 WIP）
- [ ] `uvicorn src.api.server:app --port 8000` 后 `curl localhost:8000/health` 返回 `{"status":"ok"}`
- [ ] MVP CLI `python -m src.runner --persona personas/price_sensitive_student.yaml --max-rounds 2` 仍能跑通

**Vibe Coding 提示词**：
> 你正在为现有 MVP 命令行系统搭建 Web 产品骨架。**绝对不要改任何 src/ 现有业务模块**。
>
> **后端**：
> 1. `requirements.txt` 追加：`fastapi>=0.110`、`uvicorn[standard]>=0.27`、`python-multipart>=0.0.9`
> 2. `src/api/__init__.py`（空）
> 3. `src/api/server.py`：FastAPI app + CORSMiddleware(`http://localhost:5173`) + `GET /health` 返回 `{"status":"ok","version":"0.2.0"}`
>
> **前端**：
> 1. 项目根：`npm create vite@latest web -- --template vue`
> 2. 进入 web 安装：`pinia vue-router@4 element-plus @element-plus/icons-vue axios echarts vue-echarts`
> 3. `web/src/main.js`：注册 ElementPlus（中文 locale）、Pinia、Router、全局 Element Icons
> 4. `web/src/router/index.js`：定义 14 条路由，父路由 `/` 用 `Layout.vue` 包裹
> 5. `web/src/layouts/Layout.vue`：el-container + 左 el-menu 折叠 + el-main + el-header（项目名 + 静态绿点）
> 6. 左导航分组：模拟运营、规模化测试、知识与资产、系统设置
> 7. 14 个空 view 组件分布在 `web/src/views/{simulation|scale|assets|system}/*.vue`，每个用 el-empty 显示 WIP + 当前路由名
> 8. `web/src/api/client.js`：axios 实例 baseURL=`http://localhost:8000`
>
> 验收：（后端 + 前端都启动）`curl localhost:8000/health` ok；浏览器 14 个菜单可切换；MVP CLI 跑通。

---

# Stage 1：基础设施（SQLite + 多 provider 配置表 + 日志）

**Delta**：
- 新增：`src/storage/models.py / db.py / migrations.py`
- 修改：`src/config.py` 增加日志；`src/llm.py` 改造为"优先 DB 读 active provider，fallback `.env`"
- 不动：Agent / Coach / Judge / Session 业务逻辑

**主要任务**：
1. 设计 8 张表：`llm_providers`、`personas`、`knowledge_bases`、`knowledge_files`、`sessions`、`turns`、`evaluations`、`sales_cases`（其他表后续阶段按需加）
2. **personas 表关键字段**：
   - `id, name, format_type ('prompt_based'|'structured'), profile_json, pressure_json, prompt_text, source, tags_json, locale, original_data_json, created_at, updated_at`
   - `format_type='prompt_based'` 时，`prompt_text` 必填；`pressure_json` 可以由 LLM 抽取（Stage 3 实现）
   - `format_type='structured'` 时，按现有 PersonaProfile schema 存
3. `llm_providers` 字段：`id, name, provider_type, base_url, api_key, model_name, temperature, max_retries, is_active, is_default, extra_config_json, created_at, updated_at`
4. 初始化时若 `.env` 有 OPENAI_API_KEY 且 DB 表为空，自动迁移一条 default 记录
5. `src/llm.py` 改造：调用前先查 DB 取 `is_default=True` 的 provider，没有则回退 `.env`
6. 全局日志：rotating file handler 写 `logs/YYYYMMDD.log`

**验收清单**：
- [ ] `python -c "from src.storage.db import init_schema, get_connection; init_schema(get_connection())"` 不报错
- [ ] `sqlite3 data/conversations.db ".tables"` 列出 8 张表
- [ ] `sqlite3 data/conversations.db "SELECT name, is_default FROM llm_providers;"` ≥ 1 条
- [ ] MVP CLI 仍能跑通（验证从 DB 读 provider 兼容性）
- [ ] `logs/<今日>.log` 文件生成且含调用记录

**Vibe Coding 提示词**：
> 铺基础设施层。**不要碰任何 Agent / Coach / Judge / Session 业务逻辑**。
>
> 1. `src/storage/models.py`：8 张表的 CREATE TABLE IF NOT EXISTS SQL 字符串。personas 表必须有 format_type / prompt_text 字段（NULLABLE）。
> 2. `src/storage/db.py`：`get_connection()`（设 `row_factory=sqlite3.Row`、`PRAGMA foreign_keys=ON`）、`init_schema()`、providers CRUD 函数
> 3. `src/storage/migrations.py`：`migrate_env_to_db()`：检查 .env 是否有 OPENAI_API_KEY 且 llm_providers 表空，则 INSERT 一条 `name="default"`（provider_type 按 base_url 推断）
> 4. 修改 `src/llm.py` 的 `_get_client_and_settings()`：优先从 DB 取 default provider，失败 fallback 到现有 `load_settings()`。保持 `reset_client_for_test()` 接口
> 5. 修改 `src/config.py` 增加 `setup_logging()`：rotating file handler（保留 30 天）+ rich 控制台并存
> 6. `src/api/server.py` startup 事件中调 `init_schema()` + `migrate_env_to_db()` + `setup_logging()`
>
> 验收：按清单。

---

# Stage 2：模型设置（多 provider 管理中心）

**Delta**：
- 新增：`src/api/routes_providers.py`、`web/src/views/system/ModelSettings.vue`、`web/src/stores/providers.js`
- 不动：Agent / Coach 等

**主要任务**：
1. 后端 6 接口：list / create / update / delete / set_default / test
2. 前端表格 + 新增/编辑 dialog（provider_type 下拉自动填 base_url 模板）+ 「测试连通」按钮
3. 6 种预设：DeepSeek / OpenAI / 通义千问 / Moonshot / 智谱 GLM / 自定义
4. api_key 列表中脱敏（`sk-***xxxx`）+ 编辑时 password 类型输入
5. 「设为默认」立即调 `src.llm.reset_client_for_test()` 热生效

**验收清单**：
- [ ] 进入页面看到从 .env 迁移的默认 provider
- [ ] 点「新增」填入配置 → 保存 → 列表出现新记录
- [ ] 点「测试」→ 显示「连通成功，响应 800ms，回复：Hello!」
- [ ] 点「设为默认」→ 默认标记切换
- [ ] CLI 跑一场会话使用的是新默认 provider
- [ ] 重启后端，默认 provider 保持

**Vibe Coding 提示词**：
> 做模型设置中心。
>
> 1. `src/api/routes_providers.py`：6 个接口。test 接口实现：临时构造 `OpenAI(base_url, api_key)` 客户端发 `[{"role":"user","content":"ping"}]` max_tokens=10，返回 `{ok, latency_ms, reply, error}`
> 2. set_default 接口：UPDATE 重置后调 `src.llm.reset_client_for_test()`
> 3. 前端 ModelSettings.vue：
>    - 顶部「+ 新增」按钮
>    - el-table 列：名称、类型（el-tag）、模型名、base_url（截断）、api_key（脱敏）、是否默认、是否启用、操作
>    - 操作：测试 / 编辑 / 删除 / 设为默认
>    - dialog 中 provider_type 切换时自动填 base_url：
>      - deepseek→`https://api.deepseek.com`
>      - openai→`https://api.openai.com/v1`
>      - qwen→`https://dashscope.aliyuncs.com/compatible-mode/v1`
>      - moonshot→`https://api.moonshot.cn/v1`
>      - zhipu→`https://open.bigmodel.cn/api/paas/v4`
>    - api_key 用 `<el-input type="password" show-password>`
>    - temperature el-slider 0~1 步长 0.1
>
> 验收：按清单。

---

# Stage 3：persona 人设库（双格式 + 44 预填 + LLM 抽参）

**Delta**：
- 新增：`src/api/routes_personas.py`、`src/persona/parser.py`、`src/persona/generator.py`、`src/persona/pressure_extractor.py`
- 新增：`prompts/persona_generator_prompt.md`、`prompts/pressure_extractor_prompt.md`
- 新增前端：`web/src/views/assets/PersonaLibrary.vue`、`web/src/stores/personas.js`
- 修改：`src/runner.py` 支持从 DB 读 persona；`src/agents.py` 的 `generate_persona_turn` 支持 prompt_based 格式（按 format_type 走不同 prompt 渲染）
- 不动：Persona/Sales Agent 的 schema 和 LLM 调用接口

**主要任务**：
1. **后端接口**（8 个）：
   - `GET /api/personas?format=&tag=&search=` 列表（含筛选）
   - `GET /api/personas/{id}` 详情
   - `POST /api/personas` 手动创建（structured 或 prompt_based）
   - `POST /api/personas/upload` 上传 .json/.txt/.md 文件（**支持 panel JSON 批量**）
   - `POST /api/personas/generate` 文本框 → LLM 生成新 persona（structured + prompt_text 都生成）
   - `POST /api/personas/{id}/extract_pressure` 对 prompt_based persona 调 LLM 抽取量化参数
   - `PATCH /api/personas/{id}` 编辑（可单独改 prompt_text 或 pressure_json）
   - `DELETE /api/personas/{id}`
2. **44 预填**：startup 时若 personas 表空，自动导入 `训练文件/2.1 消费者人设.json`（44 个 prompt_based persona），同时对每个调 LLM 抽取 pressure_profile（异步任务，状态字段 `pressure_extracted: bool`）
3. **Persona Agent 双路径渲染**：修改 `src/agents.py`：
   - `format_type='structured'`：用现有 `persona_prompt.md`
   - `format_type='prompt_based'`：用新 `persona_prompt_v2.md`（结构：注入 persona.prompt_text 作为 system role + 注入 pressure_profile 作为行为约束 + 注入历史/Judge 指令）
4. **量化参数抽取**：`src/persona/pressure_extractor.py`：传入 prompt 文本 → LLM 输出 9 个 0-1 浮点（pressure_profile 全字段）
5. **前端页面**：
   - 顶部三按钮：「+ 手动创建」「↑ 上传文件」「✨ LLM 生成」
   - 列表用 el-card 卡片网格（每行 3 个），显示 name、tags、format_type 角标、压力雷达图缩略图
   - 顶部筛选条：format_type / tag 多选 / 关键字搜索
   - 卡片点击打开 el-drawer 详情：
     - 头部：name、tags、source
     - tabs：「人设描述」（prompt 全文，可编辑） / 「量化参数」（9 个 el-slider 可调） / 「行为偏好」（occupation、budget 等字段）
     - 底部：「重新抽取参数」「保存」按钮
   - 「LLM 生成」dialog：左侧 textarea 让用户输入想法（占位提示「如：30岁宝妈，注重性价比，对教育产品感兴趣，犹豫不决」），右侧实时显示生成预览 + 「生成」「保存」按钮
6. **批量导入支持 panel JSON**：parser 检测到顶层 `personas` 数组时按 panel 格式处理；单 persona 上传保持兼容

**验收清单**：
- [ ] 首次启动（personas 表空）→ 后端自动导入 44 个 panel persona，列表能看到
- [ ] 每个 persona 详情页能看到完整 prompt 文本 + 9 个抽取出的量化参数
- [ ] 调整某 persona 的 price_sensitivity 滑块保存 → 数据库更新
- [ ] 上传一份单 persona JSON 文件成功导入
- [ ] LLM 生成：输入「30 岁宝妈，注重性价比」→ 5~15 秒后生成完整 persona（含 prompt + 量化参数）
- [ ] 用 prompt_based persona 跑一场 CLI 会话能正常生成 turn
- [ ] 用 structured persona 跑也能正常生成
- [ ] MVP 原 yaml 人设删除后系统仍正常（personas 表已从 panel 预填）

**Vibe Coding 提示词**：
> ⭐ 这是 Stage 3，最复杂的素材准备阶段。重点：**双格式 + 44 预填 + LLM 双向抽参**。
>
> 1. `src/persona/parser.py`：
>    - `parse_persona_file(path) -> list[dict]`：根据后缀分派
>    - JSON 顶层若有 `personas` 数组 → panel 格式，遍历返回多个
>    - JSON 顶层是 dict → 单 persona
>    - YAML 文件 → structured 格式
>    - .md 含 yaml frontmatter → 提取 frontmatter + 正文作 prompt_text
>    - 解析失败抛 PersonaParseError 含详细原因
> 2. `src/persona/pressure_extractor.py`：
>    - `extract_pressure_profile(prompt_text: str) -> dict`：调 LLM 输出 9 个 0-1 浮点
>    - prompt 模板 `prompts/pressure_extractor_prompt.md`：明确列出 9 个维度（price_sensitivity / trust_threshold / patience / competitor_awareness / decision_power / emotion_volatility / need_urgency / skepticism / bargaining_aggressiveness）和定义，要求输出严格 JSON
>    - 用 `call_llm_json` 调用，失败返回所有维度=0.5 的默认值并打 warning
> 3. `src/persona/generator.py`：
>    - `generate_persona_from_text(user_input: str) -> dict`：调 LLM 同时生成 prompt_text + structured 字段 + pressure_profile
>    - prompt 模板 `prompts/persona_generator_prompt.md`：含字段说明 + 3 个示例（从 panel 取）
> 4. `src/persona/__init__.py` 提供 `seed_built_in_personas(conn)`：检查 personas 表空就读取 `训练文件/2.1 消费者人设.json` 批量 INSERT（pressure_extracted=False），然后后台任务对每条调 extract_pressure_profile 更新 pressure_json
> 5. `src/api/server.py` startup 调 `seed_built_in_personas`
> 6. 修改 `src/agents.py`：
>    - `generate_persona_turn` 开头检查 `state.persona_profile.format_type`
>    - 若 prompt_based：加载 `persona_prompt_v2.md`，把 persona.prompt_text 作为 system 主体，pressure_profile 用一段简短约束追加
>    - 若 structured：走原路径
>    - **不要改 sales_turn / judge / coach / memory**
> 7. 新增 `prompts/persona_prompt_v2.md`：模板要求 LLM 完全按注入的角色 prompt 扮演，同时输出和 v1 相同的 JSON（content + hidden_state）
> 8. 修改 `src/runner.py`：`--persona` 参数先尝试当 DB id 查，查到用 DB 的（构造 PersonaProfile），否则按文件路径处理
> 9. 修改 `src/schema.py` 的 PersonaProfile：增加 `format_type: str = "structured"`、`prompt_text: Optional[str] = None`、`tags: List[str] = []`、`locale: str = "zh-CN"` 字段
> 10. 前端 PersonaLibrary.vue：
>     - 顶部 el-row 三按钮 + 筛选条
>     - 卡片网格用 el-row + el-col span=8，卡片含 name / tags / format_type 角标（structured 蓝色 / prompt_based 紫色）/ 量化雷达图（用 9 个 el-progress 简化亦可）
>     - 详情 el-drawer 宽度 50%，三 tab
>     - 量化参数 tab：9 个 el-slider，每个旁边显示维度说明 tooltip
>     - 重新抽取按钮带 confirm（会调 LLM 覆盖现有参数）
> 11. **重要**：`personas/*.yaml` 三个文件删除，`data/product.md` 删除
>
> 验收：按清单。LLM 抽取参数对所有 44 个 panel persona 都要成功（允许个别 fallback 到 0.5 默认）。

---

# Stage 4：产品/企业知识库（多格式 + 双 collection + 训练文件预填）

**Delta**：
- 新增：`src/rag/embedder.py / kb_store.py / parsers.py`、`src/api/routes_kb.py`
- 新增前端：`web/src/views/assets/ProductKB.vue / EnterpriseKB.vue`、`web/src/components/KBManager.vue`
- 新增依赖：chromadb、sentence-transformers、pypdf、python-pptx、python-docx、**openpyxl**
- 不动：Agent（Stage 6b 才接入 Sales）

**主要任务**：
1. 多格式解析：
   - .txt / .md：直接读，按二级标题切
   - .pdf：pypdf 按页提取
   - .docx：python-docx 按段落
   - .pptx：python-pptx 按幻灯片（含 title + content）
   - **.xlsx：openpyxl 按 sheet + 行**（每行作为一个 chunk，header 作为 metadata.column_names）
2. 切片：按章节/段落/行优先 + 滑动窗口（chunk_size=400, overlap=80）
3. 双 collection：`product_knowledge`、`enterprise_knowledge`，metadata 含 `kb_id, kb_type, file_id, filename, section`
4. **训练文件预填**：startup 时若 knowledge_bases 表空：
   - 创建 KB「华为 MatePad 12X」(product)，导入 `1.2 HUAWEI Tablet Products Introductory Course.pptx`、`2. Laurent_HUAWEI MatePad 12 X_Sales Talk & Demo Guide.pptx`、`7. Laurent_HUAWEI MatePad 12 X_FAQ.xlsx`
   - 创建 KB「销售方法论」(enterprise)，导入 `4.1 Retail Doctors.pdf`、`4.2 Steve Jobs Presentation.pdf`、`5. Instore Training Guide.pptx`
   - 异步索引（状态字段实时更新）
5. 后端 7 接口：list / create_kb / delete_kb / upload_files / list_files / delete_file / query
6. 前端：抽公共组件 `KBManager.vue` props.type，ProductKB/EnterpriseKB 各传 type

**验收清单**：
- [ ] 首次启动 → 产品库出现「华为 MatePad 12X」KB，文件状态从 pending → indexed
- [ ] 首次启动 → 企业库出现「销售方法论」KB，3 个文件全部 indexed
- [ ] 「检索测试」框输入「华为 MatePad 12X 价格」→ 命中产品 KB 中相关 chunks
- [ ] 「检索测试」框输入「如何开场白吸引顾客」→ 命中企业 KB 中相关 chunks
- [ ] 上传一个 .xlsx 文件成功索引（按行切片，metadata 含 column_names）
- [ ] 双 collection 隔离验证：产品库检索结果不包含企业库内容
- [ ] 删除某文件后再检索，该文件 chunks 不再出现

**Vibe Coding 提示词**：
> Stage 4：知识库 + 多格式解析 + 自动预填。**核心是 xlsx 解析和训练文件分类导入**。
>
> 1. `requirements.txt` 追加：`chromadb>=0.4.0`、`sentence-transformers>=2.2.0`、`pypdf>=4.0.0`、`python-pptx>=0.6.21`、`python-docx>=1.1.0`、`openpyxl>=3.1.0`
> 2. `src/rag/embedder.py`：`Embedder` 单例类（懒加载 BAAI/bge-small-zh-v1.5）
> 3. `src/rag/parsers.py`：
>    - `parse_file(path) -> list[dict]` 按后缀分派
>    - .md/.txt：按 `^## ` 切，无标题就整体一段
>    - .pdf：每页一段，section=`Page {n}`
>    - .docx：每 5 段合并为一段，section=`Paragraph {i}`
>    - .pptx：每幻灯片一段，含 title + 全部文本框内容，section=`Slide {n}: {title}`
>    - **.xlsx**：用 openpyxl 遍历每个 sheet 的每行，header 行（第 1 行）作为 column_names 存 metadata，每行一段，section=`{sheet_name} Row {n}`
> 4. `src/rag/kb_store.py`：`KBStore(collection_name)` 类，PersistentClient(path="data/chroma")。方法：`add_file / delete_file / query(query, top_k=3, kb_id=None) / reset_collection`
> 5. `src/api/routes_kb.py`：7 接口。upload 接口 BackgroundTasks 异步索引，knowledge_files 表 status 从 pending → indexed/failed
> 6. **自动预填**：`src/rag/seed.py` 提供 `seed_default_kbs(conn)`：检查 knowledge_bases 表空就执行预填逻辑（创建 KB + 异步索引训练文件）。在 `src/api/server.py` startup 调用
> 7. 前端 KBManager.vue（公共组件）：
>    - 布局：el-row gutter=20，左 8（KB 列表 + 新建按钮），右 16（选中 KB 后内容）
>    - 右上方文件表格（含状态 el-tag：pending 灰 / indexed 绿 / failed 红 + 错误 tooltip）
>    - 右下方「检索测试」区：el-input + 「检索」按钮 + 结果区（top-3 含 score / section / text 截断）
>    - 上传 el-upload drag=true accept=".txt,.md,.pdf,.docx,.pptx,.xlsx"
>    - 上传后定时（每 2s）刷新文件列表直到所有 pending 消失
> 8. ProductKB.vue / EnterpriseKB.vue 都引 KBManager 并 props.type
>
> 验收：按清单。重点确认 xlsx 解析和训练文件预填。

---

# Stage 5：向量库管理

**Delta**：
- 新增：`src/api/routes_vector_admin.py`、`web/src/views/system/VectorAdmin.vue`
- 复用：Stage 4 的 KBStore

**主要任务**：
1. 列出所有 Chroma collection（含统计：文档数、chunk 数、占用空间估算）
2. 重建索引（按 knowledge_files 重新索引）
3. 清空 collection（二次确认）
4. Embedding 模型信息卡片

**验收清单**：
- [ ] 页面展示至少 2 个 collection 含统计
- [ ] 对某 collection 点「重建索引」→ reset + 异步重新索引 → 完成后统计刷新
- [ ] 点「清空」→ 二次确认 → 执行后该 collection 为空

**Vibe Coding 提示词**：
> 简单的向量库管理。
>
> 1. `routes_vector_admin.py`：4 接口（list collections / rebuild / clear / embedding_info）
> 2. VectorAdmin.vue：顶部 embedding 模型信息 el-card + el-table（操作列「重建」「清空」按钮，clear 用 el-popconfirm）
>
> 验收：按清单。

---

# Stage 5.5：⭐ 渐进式对话引擎改造

**Delta**：
- 修改：`prompts/persona_prompt.md`、`prompts/persona_prompt_v2.md`、`prompts/sales_prompt.md`、`prompts/judge_prompt.md`
- 修改：`src/session.py` 增加 `who_speaks_first / opening_line` 参数 + 早结束机制 + 阶段比例重排
- 修改：`src/agents.py` Sales Agent 按阶段动态注入"挖掘期不报价"约束 + 字数约束
- 修改：`src/schema.py` Persona hidden_state 增加 `walk_away_reason` 字段；DialogueState 增加 `who_speaks_first / opening_line / max_rounds_floor` 字段
- **不动**：DB / KB / Web 任何东西

**主要任务**：
1. **阶段比例重排**（修改 `get_stage_by_round`）：
   - 开场与需求探索 0~15%
   - **核心需求挖掘 15%~50%**（占最大比重）
   - 方案匹配与价值锚定 50%~70%
   - 强压测试 70%~85%
   - 成交推进或失败退出 85%~100%
2. **销售先开口**：`run_session` 新增 `who_speaks_first: Literal["sales","persona"] = "sales"` 参数，"sales" 时首轮直接把 `opening_line` 写入 history（不调 LLM），然后从 Persona 第一句回应开始正常流程
3. **5 个开场白模板**（写入 `src/session.py` 常量）：
   ```python
   OPENING_TEMPLATES = [
     "您好，欢迎光临，请问今天想看点什么？",
     "Hi，需要我帮您介绍一下吗？",
     "您好，随便看看也没关系，有需要随时叫我～",
     "欢迎光临！这边有刚到的新品，要不要看一下？",
     "您好，这边有什么我可以帮您的吗？",
   ]
   ```
4. **Persona prompt 改造**（v1 和 v2 都改）：
   - 明确"渐进式信息披露"规则：默认含糊，每轮只透露 1 个信息维度（用途/预算/品牌/痛点之一），且只在销售针对性提问时才透露
   - 第 1~3 轮禁止主动说预算或品类细节
   - 明确字数约束：开场/挖掘阶段每句 **20~50 字**；异议/强压阶段 50~150 字
   - 新增 `walk_away_triggers` 检测：销售在前 5 轮直接推荐产品/型号 → 可标 `WALK_AWAY` reason="过早推销"；客户说"自己看看"后销售继续推 → `WALK_AWAY` reason="不被尊重"；销售言语不当 → `COMPLAINT` reason="服务态度差"
5. **Sales prompt 改造**：
   - 开场/挖掘阶段（前 50% 轮次）**禁止报价、禁止推荐具体型号**，只能开放式提问
   - 提供问题模板：用途场景探问 / 使用人探问 / 预算暗示探问（"您之前用过类似的吗"而非"您预算多少"）
   - strategy.intent 词表新增：`open_question / narrow_question / probe_pain_point / probe_competitor / probe_budget_indirect`
   - 字数约束同上
6. **Judge prompt 改造（成熟度护栏）**：
   - 在 `round_idx < max_rounds * 0.3` 时，强制 `should_continue=True` 且 `end_status="CONTINUE"`（防过早成交）
   - 检测到 Sales 在前 5 轮提到具体价格/型号时 sales_score.specificity -2 且 sales_instruction 加警告"过早推销"
   - 检测到 Persona 在前 60% 轮 purchase_signal > 0.6 时 dialogue_quality -1 且 persona_instruction 加"保持观望"
7. **早结束机制**：`run_session` 主循环中检测到 persona turn metadata.status ∈ {WALK_AWAY, DEAL_DONE, COMPLAINT, FOLLOW_UP} 立即 break

**验收清单**：
- [ ] CLI：`python -m src.runner --persona <某 panel id> --max-rounds 50` 启动后**销售先开口**（用第 1 个模板）
- [ ] 前 10 轮全部是「销售开放式提问 + Persona 含糊简短回答」格式
- [ ] Persona 第 1 轮回答不超过 50 字（不能再出现"我是学生预算 2500 想买学习平板"这种一口气全说的）
- [ ] 至少跑 3 场会话验证不同结束方式：
  - [ ] 一场跑满 50 轮（正常拉锯）
  - [ ] 一场 Persona 早期 WALK_AWAY（销售过早推销）
  - [ ] 一场 Persona DEAL_DONE 在 30+ 轮（正常成交）
- [ ] Judge 在前 15 轮（30%）时返回的 end_status 必须是 CONTINUE
- [ ] outputs 中复盘文件正常输出

**Vibe Coding 提示词**：
> ⭐ Stage 5.5：渐进式对话引擎改造。**这是引擎层的精细化升级，所有改动都在 prompts/ 和 src/session.py + src/agents.py 内**，不改 DB / KB / Web。
>
> 1. 重写 `prompts/persona_prompt.md` 和 `prompts/persona_prompt_v2.md`（v1 给 structured persona / v2 给 prompt_based persona）：核心规则在文档体内详细描述。两版都加：
>    - 渐进式披露规则（默认含糊、每轮只透露 1 维度、需销售针对性提问）
>    - 字数约束（按阶段动态）
>    - walk_away / complaint 触发条件（明确列出 3 类）
> 2. 重写 `prompts/sales_prompt.md`：
>    - 前 50% 轮严禁报价/推荐具体型号
>    - 提供问题分类（探用途/探使用人/暗示性探预算/探竞品/探痛点）
>    - 字数约束按阶段
>    - strategy.intent 词表扩充
> 3. 重写 `prompts/judge_prompt.md`：
>    - 成熟度护栏明文规则
>    - 检测过早推销 / 过早成交并在 instruction 中明确指出
> 4. 修改 `src/session.py`：
>    - `STAGES` 常量不变，但 `get_stage_by_round` 比例调整（如上）
>    - `OPENING_TEMPLATES` 常量定义 5 个模板
>    - `run_session` 新增 `who_speaks_first / opening_line / max_rounds_floor` 参数
>    - who_speaks_first="sales" 时第 1 轮：用 opening_line 构造 Turn(idx=0, speaker="sales", content=opening_line, metadata={"is_opening": True, "stage": stages[0]}) 直接 append；然后从 Persona 第 1 轮开始正常循环
>    - 早结束检测加入 COMPLAINT 状态
> 5. 修改 `src/agents.py`：
>    - `_render_sales_prompt` 中根据当前阶段（state.current_stage）和 round_idx/max_rounds 比例动态注入"挖掘期 / 异议期"约束段
>    - 字数约束作为变量传入模板（render 时填入）
> 6. 修改 `src/schema.py`：
>    - HiddenState 增加 `walk_away_reason: Optional[str] = None`
>    - DialogueState 增加 `who_speaks_first: str = "sales"`、`opening_line: str = ""`
>    - 新增 status "COMPLAINT"
>
> 验收：按清单。重点跑 3 种不同结束方式的会话。

---

# Stage 6a：新建对话 + 简单对话现场

**Delta**：
- 新增：`src/api/routes_sessions.py`、`src/api/ws_session.py`、`src/api/session_runner_async.py`
- 修改：`src/session.py` 增加 `on_event / cancel_flag` 参数（默认 None 保持 CLI 兼容）
- 新增前端：`web/src/views/simulation/NewSession.vue`、`web/src/views/simulation/LiveSession.vue`、`web/src/stores/liveSession.js`、`web/src/components/DialogueStream.vue`

**主要任务**：
1. **新建对话表单**：
   - 选 persona（el-select 含搜索，按 tag 筛选）
   - 选产品 KB（可选）+ 选企业 KB（可选）
   - topic 输入
   - max_rounds 滑块（8~50，默认 50）
   - judge_interval / memory_interval 数字输入（默认 3）
   - **销售开场白**：el-select 含 5 个模板 + 「自定义」选项（选自定义切换 textarea）
   - 「开始对话」按钮 → 创建 session → 跳到对话现场
2. **WebSocket** `/ws/session/{session_id}/live`：事件 `session_start / stage_change / persona_turn / sales_turn / memory_update / judge_feedback / coach_review / session_end`
3. **对话现场页 v1**（简单三栏）：
   - 左 6：会话信息（persona 卡片 + 产品/企业 KB + 当前阶段 + 轮次 + 「中断」按钮）
   - 中 12：滚动对话流（DialogueStream 组件）persona 蓝靠左 / sales 绿靠右，stage 切换插分隔线
   - 右 6：占位"实时数据"区域（Stage 6b 填充）
4. 会话结束 → el-result 提示 + 「查看复盘」按钮（跳到 `/simulation/history/{id}`，Stage 7 实现）

**验收清单**：
- [ ] 新建对话页选 persona + 产品 KB + 开场白模板 + max_rounds=20 → 「开始」→ 跳转对话现场
- [ ] 第 0 轮显示销售开场白（绿色卡片）"您好，欢迎光临..."
- [ ] 第 1 轮 Persona 简短回应（蓝色卡片）
- [ ] 对话持续推流到结束
- [ ] 中断按钮能正常停止
- [ ] sessions 表新增记录

**Vibe Coding 提示词**：
> Stage 6a：核心交付物之一，新建对话 + 对话现场基础版。**重点是 WebSocket 推流不能丢事件**。
>
> 1. 修改 `src/session.py`：增加 `on_event: Optional[Callable[[dict], None]] = None`、`cancel_flag: Optional[threading.Event] = None` 两个参数（默认 None 不影响 CLI）。在所有关键点（session_start / 每轮 persona/sales 生成后 / memory 更新 / judge / coach / session_end）调 `on_event({"type":..., "data":...})`。每轮循环开头检查 cancel_flag.is_set() → break
> 2. `src/api/session_runner_async.py`：`SessionRunner` 类管理一场 session 的 asyncio.Queue 和 cancel_flag。`start_in_executor(params)` 把 `run_session` 放线程池跑，on_event 用 `loop.call_soon_threadsafe(queue.put_nowait, event)`。`stream_events(websocket)` 主协程从 queue 取事件 send_json。全局 `_active_runners: dict[session_id, SessionRunner]`
> 3. `src/api/routes_sessions.py`：
>    - `POST /api/sessions` 创建（参数完整含 opening_line / who_speaks_first），返回 session_id
>    - `POST /api/sessions/{id}/start` 触发 SessionRunner
>    - `POST /api/sessions/{id}/cancel` set cancel_flag
>    - `GET /api/sessions/{id}` 基本信息
> 4. `src/api/ws_session.py`：`@router.websocket("/ws/session/{id}/live")` 端点，取 _active_runners 调 stream_events
> 5. 前端：
>    - `api/sessions.js` + `api/ws.js`（WebSocket 封装：自动重连 + 事件总线）
>    - `stores/liveSession.js`：turns, currentStage, sessionInfo, status
>    - `NewSession.vue` 表单 → 创建 → start → router.push(`/simulation/live/${id}`)
>    - `LiveSession.vue` mounted 连 WS 分发到 store，三栏布局（左 6 / 中 12 / 右 6）
>    - `DialogueStream.vue` 公共组件：props.turns，transition-group 动画
>    - 销售开场白 el-select：5 个内置模板 + 「自定义」（监听 value 切换 textarea）
>
> 验收：按清单。

---

# Stage 6b：双 KB 接入 + 实时画像可视化

**Delta**：
- 修改：`src/agents.py` 的 `generate_sales_turn` 接入 product/enterprise KB 检索
- 修改：`prompts/sales_prompt.md` 新增 `{product_hits} / {enterprise_hits}` 占位
- 修改：`src/schema.py` DialogueState 增加 `product_kb_id / enterprise_kb_id`
- 修改：`web/src/views/simulation/LiveSession.vue` 右栏填充实时数据
- 新增前端：`web/src/components/SessionInsights.vue`

**主要任务**：
1. **Sales Agent RAG 检索**：发言前用「最近 2 条 turn content + session_memory.main_objections」拼接 query
   - 调 `product_kb.query(query, kb_id=state.product_kb_id, top_k=3)`
   - 调 `enterprise_kb.query(query, kb_id=state.enterprise_kb_id, top_k=2)`
   - 双库检索结果分别注入 prompt 不同占位
   - turn metadata 写入 `used_product_kb / used_enterprise_kb`（list of chunk_id）
   - KB 不存在或为空时 fallback（不报错）
2. **WebSocket 事件扩展**：sales_turn 事件 data 中带 `rag_hits: {product: [...], enterprise: [...]}`
3. **右栏实时数据可视化** SessionInsights.vue：
   - el-tabs 三个：「实时画像」「Judge 提示」「RAG 命中」
   - 「实时画像」：current_need / main_objections / budget_boundary / emotional_state / do_not_repeat / next_best_action 字段卡片
   - 「Judge 提示」：sales_score 雷达图 + 最新 sales_instruction / persona_instruction 卡片
   - 「RAG 命中」：每条 sales turn 命中的 chunks 列表（含 score、section、text 截断）

**验收清单**：
- [ ] 在新建对话页选产品 KB「华为 MatePad 12X」+ 企业 KB「销售方法论」开启会话
- [ ] 销冠每轮对话产生时，右栏「RAG 命中」实时刷新命中的 chunks
- [ ] 右栏「实时画像」每次 memory_update 事件后更新
- [ ] 右栏「Judge 提示」每次 judge_feedback 事件后更新雷达图
- [ ] sales turn metadata 中 used_product_kb / used_enterprise_kb 非空
- [ ] 不选 KB 也能正常对话（fallback OK）

**Vibe Coding 提示词**：
> Stage 6b：双 KB 接入 + 实时画像可视化。**只改 src/agents.py 的 generate_sales_turn 和前端右栏，不动其他**。
>
> 1. 修改 `src/agents.py` 的 `generate_sales_turn`：
>    - 在 LLM 调用前：用 `_build_rag_query(state)` 生成 query
>    - 调 `get_product_kb().query(query, kb_id=state.product_kb_id, top_k=3)`（state.product_kb_id 为 None 时跳过返回空 list）
>    - 调 `get_enterprise_kb().query(query, kb_id=state.enterprise_kb_id, top_k=2)`
>    - 渲染 prompt 时分别填入 `{product_hits}` 和 `{enterprise_hits}` 占位
>    - 生成的 Turn metadata 包含 `used_product_kb: [hit.id...] / used_enterprise_kb: [hit.id...]`
>    - 这些 hits 也通过 on_event 上抛
> 2. 修改 `prompts/sales_prompt.md`：在原 `{product_text}` 位置换为 `{product_hits}` + 新增 `{enterprise_hits}` 段说明（"以下是相关销售方法论参考"）
> 3. 修改 `src/schema.py` DialogueState 增加 `product_kb_id: Optional[str] = None`、`enterprise_kb_id: Optional[str] = None`
> 4. 修改 `src/api/session_runner_async.py`：on_event 在 sales_turn 事件中附带 rag_hits 数据
> 5. 前端 `SessionInsights.vue`：三 tab，雷达图用 vue-echarts
> 6. `LiveSession.vue` 右栏替换占位为 SessionInsights 组件
>
> 验收：按清单。

---

# Stage 7：会话历史 + 复盘 + 导出

**Delta**：
- 修改：`src/api/routes_sessions.py` 增加 list / detail / export 接口
- 新增前端：`web/src/views/simulation/SessionHistory.vue / SessionDetail.vue`

**主要任务**：
1. 后端：
   - `GET /api/sessions?persona_id=&outcome=&page=&size=`
   - `GET /api/sessions/{id}/detail` 含 turns + coach_review + judge_feedback + session_memory + metrics
   - `GET /api/sessions/{id}/export?format=json|md|jsonl` 流式返回
   - `DELETE /api/sessions/{id}` 同步删除 outputs/ 目录
2. 历史页：el-table + 筛选 + 分页
3. 详情页：4 tabs（对话 / Coach / Judge / 画像），导出下拉

**验收清单**：
- [ ] 历史页能筛选 persona + outcome 分页正常
- [ ] 详情页 4 tab 全部渲染
- [ ] Judge tab 雷达图正确（5 项 sales_score）
- [ ] 导出 Markdown 下载得到含完整复盘的文件
- [ ] 删除会话同步清理 outputs

**Vibe Coding 提示词**：
> Stage 7：历史 + 复盘可视化。
>
> 1. `routes_sessions.py` 追加 list / detail / export / delete 接口。export 实现：json 全量、md 拼装、jsonl 逐 turn
> 2. `SessionHistory.vue`：el-table（id、persona、产品、topic、outcome 着色 tag、轮数、质量分、开始时间、操作）+ 筛选
> 3. `SessionDetail.vue` el-tabs 4：
>    - 对话：DialogueStream 组件 props.turns
>    - Coach：el-collapse 6 panel（outcome_analysis / what_worked / what_failed / key_lessons / suggested_rebuttals / reusable_tactics）
>    - Judge：v-chart 雷达 + 文字 reason + 历次 sales_score 时序图
>    - 画像：字段卡片
> 4. 顶部 el-dropdown「导出 ▼」
>
> 验收：按清单。

---

# Stage 8：首页总览（数据看板）

**Delta**：
- 新增：`src/api/routes_dashboard.py`、`web/src/views/simulation/Dashboard.vue`

**主要任务**：
1. 后端聚合接口：
   - `GET /api/dashboard/summary` 返回 4 个核心指标：**总会话数 / Persona 总数 / 平均质量分 / 成交率**
   - `GET /api/dashboard/trends?days=30` 近 30 天每日会话数 + 平均质量分曲线
   - `GET /api/dashboard/persona_difficulty` 各 persona 平均难度评分
2. 前端布局：
   - 顶部 4 张大数字卡（el-statistic）
   - 中部 2 张图：30 天趋势折线 + outcome 分布饼图
   - 下部 1 张图：persona 难度横向条形图（按 tag 分组）

**验收清单**：
- [ ] 跑过至少 5 场会话后首页 4 个核心指标都不为 0
- [ ] 趋势图能渲染
- [ ] outcome 饼图各色块比例正确
- [ ] persona 难度图按难度降序

**Vibe Coding 提示词**：
> 数据看板。3 接口纯 SQL 聚合 + ECharts 渲染。空数据时 el-empty 占位。
>
> 验收：按清单。

---

# Stage 9：批量测试

**Delta**：
- 修改：`src/storage/models.py` 追加 `batch_jobs` 表
- 新增：`src/batch/runner.py`、`src/api/routes_batch.py`、`src/api/ws_batch.py`
- 新增前端：`web/src/views/scale/BatchTest.vue`

**主要任务**：
1. `batch_jobs` 表：id, name, persona_ids_json, product_kb_id, enterprise_kb_id, max_rounds, opening_line, total_count, completed_count, failed_count, status, started_at, ended_at, summary_json
2. 后端 5 接口 + WS `/ws/batch/{id}`
3. 前端：任务列表 + 创建 dialog（多选 persona）+ 详情抽屉（实时进度 + 已完成 session 列表可点进）
4. 顺序串行，每场失败不影响下一场

**验收清单**：
- [ ] 创建 3 persona × 1 产品 KB 的批量任务启动后进度 0/3 → 3/3
- [ ] 任务进行中可中断
- [ ] 某场失败 failed_count +1，其他继续
- [ ] 详情页可点进单场会话看复盘

**Vibe Coding 提示词**：
> 批量测试。顺序串行禁止并发。
>
> 1. batch_jobs 表 + CRUD
> 2. `src/batch/runner.py`：`BatchRunner` 顺序遍历 personas，每场创建 session + start，等完成后下一场。维护 cancel_flag，每场状态变化 on_progress
> 3. routes_batch + ws_batch（推送进度变化）
> 4. 前端 BatchTest.vue：列表 + 创建 dialog（多选 persona 用 el-checkbox-group）+ 详情抽屉
>
> 验收：按清单。

---

# Stage 10：批量报告

**Delta**：
- 新增：`src/api/routes_batch_report.py`、`web/src/views/scale/BatchReport.vue`

**主要任务**：
1. 聚合接口：概览 / 异议排行 Top 20 / persona 表现对比 / 销冠雷达 / RAG 命中率
2. 「导出 Training Guide」→ 9 章节 Markdown
3. 前端 6+ 图表 + 表格混排

**验收清单**：
- [ ] 选某已完成批量任务展示 6+ 图
- [ ] 异议排行有实际数据
- [ ] Training Guide 下载得到含 9 章节的 markdown

**Vibe Coding 提示词**：
> 批量报告。Training Guide 模板按蓝图第 20 章 9 节结构（用户类型/典型心智/高频异议/推荐策略/标准话术/FAQ/错误示范/教练点评/禁用表达清单）。
>
> 验收：按清单。

---

# Stage 11：销售案例集（三轨入库 + 训练文件预填）

**Delta**：
- 修改：`src/storage/models.py` 追加 `sales_cases` 表
- 新增：`src/cases/extractor.py / seed.py`、`src/api/routes_cases.py`
- 修改：`src/session.py` coach_review 生成后调用 `auto_extract_cases`
- 修改：`src/api/routes_sessions.py` 增加「收藏为案例」接口
- 新增前端：`web/src/views/assets/SalesCases.vue`

**主要任务**：
1. `sales_cases` 表字段：id, session_id (可空，预填案例没有), source ('judge_auto' | 'coach_auto' | 'manual' | 'preset'), title, scene, persona_id (可空), persona_tags_json, dialogue_excerpt_json, raw_content, why_excellent, tags_json, votes, file_source (预填时来源文件), created_at
2. **三轨自动入库**：
   - A. session 结束时若 `judge.dialogue_quality_score >= 8.0` → 整场对话存为 1 条 case（source='judge_auto'）
   - B. 遍历 `coach_review.what_worked`，按 round 字段定位对应 turns → 每条存 1 case（source='coach_auto'）
   - C. 会话详情页人工「收藏为案例」（source='manual'）
3. **预填案例**（startup）：
   - 解析 4 个 .pptx（Country R / LATAM / MEA × 2）
   - 每个 ppt 作为 1~多条案例（按幻灯片或场景划分）source='preset'
4. 前端：卡片网格 + 筛选（source / tag / persona）+ 详情抽屉（含完整对话片段 + why_excellent）

**验收清单**：
- [ ] startup 后案例集页面已有 4+ 条预填案例
- [ ] 跑完一场高分会话（质量 ≥ 8.0）→ 自动新增 judge_auto 案例
- [ ] 同场 Coach 标记的每条 what_worked → 自动新增 coach_auto 案例
- [ ] 会话详情某 sales turn 上点「收藏为案例」→ 新增 manual 案例
- [ ] 案例集可按 source 筛选
- [ ] 删除某案例

**Vibe Coding 提示词**：
> Stage 11：案例集。三轨入库 + 训练文件预填。
>
> 1. sales_cases 表 + CRUD
> 2. `src/cases/extractor.py`：
>    - `extract_judge_auto(state)`：质量 ≥ 8.0 时整场存
>    - `extract_coach_auto(state, coach_review)`：遍历 what_worked 按 round 取 turns
>    - try/except 包裹不阻塞会话
> 3. `src/cases/seed.py`：startup 时若 sales_cases 表空，扫描 `训练文件/Country R*.pptx / LATAM*.pptx / MEA*.pptx`，每个 ppt 用 pptx parser 提取后存为预填案例
> 4. 修改 `src/session.py`：coach_review 生成后调 extract_judge_auto + extract_coach_auto
> 5. `routes_sessions.py` 增加 `POST /api/sessions/{session_id}/cases` 手动收藏（body：turn_idx_range, title, why_excellent, tags）
> 6. `routes_cases.py`：list / get / update / delete
> 7. 前端 SalesCases.vue：卡片网格 + 筛选 + 详情抽屉
> 8. SessionDetail.vue 对话 tab 增加「收藏为案例」按钮（选中某轮后弹 dialog）
>
> 验收：按清单。

---

# Stage 12：运行状态 + UX 打磨

**Delta**：
- 新增：`src/api/routes_status.py`、`web/src/views/system/RunningStatus.vue`
- 整体调整：响应式、loading、错误提示、空状态

**主要任务**：
1. 运行状态页：
   - 系统信息（Python 版本、依赖版本、磁盘、Chroma 大小、DB 大小、日志大小）
   - 实时日志查看器（最近 200 行 + 刷新）
   - LLM 调用统计（今日次数、平均延迟、token 估算）
   - 后台任务列表（正在跑的 session / batch）
2. UX 打磨：
   - 所有列表加 skeleton loader
   - 所有 axios 错误拦截弹 el-message
   - 所有空状态 el-empty
   - Header 右上角绿点改真实健康检查（每 10s 轮询 /health）
   - 左侧导航高亮当前路由

**验收清单**：
- [ ] 运行状态页 4 块信息齐全
- [ ] 实时日志能滚动刷新
- [ ] 关闭后端时 Header 绿点变红
- [ ] 列表加载有 skeleton
- [ ] 网络错误有明显提示

**Vibe Coding 提示词**：
> Stage 12 收尾。
>
> 1. routes_status.py：4 接口
> 2. RunningStatus.vue：4 el-card
> 3. 全局 axios 拦截器 + Layout 健康检查轮询
> 4. 所有列表加 v-loading + el-empty
>
> 验收：按清单 + 主观体验流畅。

---

# Stage 14：⭐ 销冠技能配置（进阶 - FunctionCall + RAG/WebSearch/MCP）

> ⚠️ 此阶段**主线 13 阶段全部稳定后**才启动，因为它涉及销冠 Agent 的底层重构。预计 3~5 天。

**Delta**：
- 改造：`src/agents.py` 的 `generate_sales_turn` 从单轮 chat 改为多轮 tool_use 循环（OpenAI function calling）
- 新增：`src/tools/` 目录（registry / rag_search / web_search / mcp_client）
- 新增：`src/api/routes_agent_skills.py`、`web/src/views/system/AgentSkills.vue`
- 修改：`src/storage/models.py` 追加 `agent_skills_config` 表

**主要任务**：
1. **工具注册框架** `src/tools/registry.py`：装饰器 `@tool(name, description, schema)` 注册，提供 `get_enabled_tools()` 返回 OpenAI function 格式
2. **5 个内置工具**：
   - `search_product_kb(query, top_k)` → 检索产品库
   - `search_enterprise_kb(query, top_k)` → 检索企业库
   - `search_sales_cases(query, top_k)` → 检索历史案例
   - `web_search(query, top_k)` → Tavily / SerpAPI 网络检索（需要额外 API key）
   - `get_competitor_price(product_name)` → 基于 web_search 的高级封装
3. **Sales Agent 改造**：
   - 调用 LLM 时传入 `tools=[...enabled tools]`
   - 循环：response 含 tool_calls → 执行工具 → 把结果 append 到 messages → 再调 LLM → 直到无 tool_calls 或达到最大工具调用轮数（默认 5）
   - 所有工具调用记录到 turn metadata.tool_calls 用于复盘
4. **MCP 集成**：基础 MCP client 支持 stdio 连接 + 工具自动注册到 registry（具体 MCP server 由用户配置）
5. **配置 UI**：
   - 工具列表（5 个内置 + 已加载的 MCP 工具），可单独启用/禁用
   - 全局参数：最大工具调用轮数、超时
   - WebSearch API key 配置
   - MCP server 配置（每条：name / command / args / env）+ 「测试连接」按钮
6. **可视化**：会话现场右栏「RAG 命中」tab 升级为「工具调用」tab，展示销冠每轮调用的工具序列（含输入输出）

**验收清单**：
- [ ] 在 AgentSkills 页启用 search_product_kb / search_enterprise_kb 两个工具
- [ ] 启动一场会话，sales 第 1 轮主动调用 search_product_kb 检索
- [ ] turn metadata.tool_calls 含调用记录
- [ ] 配置一个 Tavily API key 启用 web_search → 销冠在合适时机主动调用
- [ ] 配置一个 MCP server（如 filesystem）→ 工具自动注册可用
- [ ] 会话现场右栏「工具调用」tab 实时展示调用序列

**Vibe Coding 提示词**（仅在前 13 阶段稳定后启动）：
> ⭐ Stage 14：进阶销冠技能配置。**这是销冠 Agent 的底层重构，会改变调用模式**。
>
> 1. agent_skills_config 表 + CRUD
> 2. `src/tools/registry.py`：装饰器框架 + get_enabled_tools()
> 3. `src/tools/rag_search.py`、`web_search.py`：5 个内置工具
> 4. `src/tools/mcp_client.py`：基础 MCP stdio client
> 5. 改造 `src/agents.py` 的 `generate_sales_turn` 为 tool_use 循环
> 6. `routes_agent_skills.py` + `AgentSkills.vue` 配置页
> 7. 升级会话现场右栏增加「工具调用」tab
>
> 验收：按清单。验证销冠能"主动思考 → 调用工具 → 整合结果"的完整链路。

---

## 4. 通用约束（每阶段开头打勾）

- [ ] 我已读过 final_version_vibe_prompts.md 对应阶段的 Delta 段落
- [ ] 我已知道哪些文件不能改（MVP 业务模块 + 跨阶段约定）
- [ ] 我准备的验收命令已写好（动手前）
- [ ] 我准备的失败兜底方案已想好
- [ ] 我没有在本阶段之外做"顺手优化"
- [ ] 中文 UI / 中文文案已就位
- [ ] FastAPI 接口加了 docstring（自动出 /docs）

---

## 5. 最终上线形态自检

13 阶段（不含 Stage 14）跑完后用户应能：
1. 浏览器打开 `http://localhost:5173`
2. 在「模型设置」配置一个 LLM 厂商（如 DeepSeek）并测试连通
3. 在「persona 人设库」看到 44 个 panel 内置人设（含量化参数）
4. 在「产品知识库」看到「华为 MatePad 12X」已预填（含产品手册 + 销售指南 + FAQ）
5. 在「企业知识库」看到「销售方法论」已预填（含零售书 + 演讲秘诀 + 培训指南）
6. 在「销售案例集」看到 4+ 条预填案例
7. 「新建对话」选人设 + 产品 + 企业 KB + 销售开场白模板 → 开始
8. 「对话现场」看销售先开口 + 顾客逐步透露需求 + 多轮挖掘到成交/流失
9. 会话结束在「会话复盘」看 Coach 提炼
10. 「批量测试」创建 5 人设 × 1 产品的批量任务
11. 「批量报告」看汇总图表 + 导出 Training Guide
12. 「首页总览」看核心数据
13. 「销售案例集」看新沉淀的高分案例
14. 「向量库管理」管理 Chroma collection
15. 「运行状态」看系统健康
