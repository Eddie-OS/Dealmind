# DealMind · 产品开发主文档（Master Dev Spec）

> **定位**：本项目（华为线下零售销冠模拟与话术手册迭代系统）的**唯一权威开发文档**。
> 记录现有系统结构 + 历次迭代改动，目标是项目结束时成为"现有结构最完善的产品开发文档"。
> **维护规则**：任何架构/数据模型/链路改动，都必须同步写入本文档对应章节 + 末尾「变更记录」。
>
> | 版本 | 日期 | 摘要 |
> |------|------|------|
> | v2.0 | 2026-05-30 | 首版主文档：沉淀现有架构 + 锁定 V2 迭代（报告可解释性/80人设/演示映射/删板块/逐条迭代建议/优秀话术解耦）规格 |
> | v2.4 | 2026-05-30 | V2-② 80 人设重构落库：扩 locales 21 销售国 + LLM 生成 40 海外人设 + 删 4 CN + 9 维压力抽取（体检 80/0 CN 通过） |
> | v2.5 | 2026-05-30 | V2-① 报告可解释性：单一事实源 methodology.py（6 板块），前端弹窗 + HTML §00 + MD 同源；六项 V2 迭代全部完成 |
>
> 相关文档：`docs/handbook_analysis_dev_spec.md`（分析报告模块 v1.0 原始设计，本文档为其超集与现状校正版）。

---

## 第 0 部分 · 项目概述

### 0.1 一句话定位
为华为线下零售场景打造的**销冠话术模拟 + 复盘 + 手册迭代**系统：用多样化消费者人设与"销冠 Agent"进行多轮对话，事后从对话里归因分析话术质量、提炼优秀原声、反推产品手册（135910 结构）的迭代建议。

### 0.2 核心概念
- **135910 手册结构**：1 一句话定位 / 3 核心卖点 / 3 竞品对比 / 5 核心参数 / 9 FAQ / 10 演示动作 = 31 个知识标签（+ `other` 兜底）。
- **销冠 Agent**：扮演华为门店金牌销售，方法论（销售技巧）与产品知识（手册=数据）解耦。
- **消费者人设 Agent**：扮演真实顾客，带 9 维隐性压力参数 + 市场本地化（国别/货币/渠道）。
- **Coach / Judge**：Judge 逐轮打分驱动人设行为；Coach 会话末做定性复盘。
- **分析报告（analysis_job）**：跨多场对话的聚合分析，是手册迭代的主产出。

### 0.3 技术栈
- 后端：Python + FastAPI + SQLite（`src/`），LLM 走 DeepSeek 系（`src/llm.py`）。
- 前端：Vue 3 + Element Plus + ECharts + Pinia（`web/`），Vite 8 dev server（5173）。
- 后端服务：`uvicorn src.api.server:app`（127.0.0.1:8000）。

---

## 第 1 部分 · 系统架构总览

### 1.1 顶层目录
```
src/
├── api/                # FastAPI 路由（routes_*.py）+ server.py 入口
├── agents.py           # 销冠/人设 turn 生成、prompt 渲染、handbook 注入、content_guard 调用
├── session.py          # 单场对话编排（imperative loop）+ Judge/Coach 调用
├── coach.py            # Coach 复盘（13 维）
├── content_guard.py    # 销冠输出事实自查/改写（防编数字）
├── analyzers/          # 分析报告引擎（见 §4）
├── research/           # 市场预研（market_facts 缓存）
├── persona/            # 人设 seed/parser/loader
├── rag/                # 解析器/embedder/检索
├── storage/            # models.py(表结构) + db.py(CRUD)
├── cases/              # 销售案例抽取
└── locales.py          # 市场推断（国别/货币/渠道）
prompts/                # sales/persona/persona_v2/judge/coach/... .md 模板
data/product_handbooks/ # 手册源 JSON
训练文件/2.1 消费者人设.json  # 44 人设种子源
web/src/                # 前端
docs/                   # 开发文档（本文件）
```

### 1.2 五个 Agent 角色与 prompt
| 角色 | 生成位置 | prompt 模板 | prompt 是否可在线编辑 |
|------|----------|------------|----------------------|
| 销冠 Sales | `agents.py:_generate_sales_turn_impl` | `prompts/sales_prompt.md` | ✅ 优先读 `agent_profiles.sales`（DB），空则读文件 |
| 人设 Persona（自由文本） | `agents.py:generate_persona_turn` | `prompts/persona_prompt_v2.md` | ❌ 仅文件（44 人设全走这条） |
| 人设 Persona（结构化） | 同上 | `prompts/persona_prompt.md` | ❌ 仅文件 |
| Judge | `session.py` | `prompts/judge_prompt.md` | ❌ 仅文件 |
| Coach | `coach.py` | `prompts/coach_prompt.md` | ❌ 仅文件（**V2 拟改为可配置，见 §5.1**） |

> **关键机制**：`agents.load_prompt(name)` 仅对 `sales_prompt` 走 DB 优先（`agent_profiles`），其余 prompt 永远从 `.md` 文件读，每轮重读（改文件即时生效，无需重启）；改 `.py` 代码需重启 uvicorn。

---

## 第 2 部分 · 数据模型（18 张表）

注册于 `src/storage/models.py` 的 `ALL_SCHEMAS`，启动时 `init_schema()` 建表。

| 表 | 用途 | 关键字段 |
|----|------|---------|
| `llm_providers` | LLM 供应商配置 | base_url, api_key, model |
| `personas` | 消费者人设 | format_type, prompt_text, pressure_json(9维), country_code, currency, market_domains_json |
| `knowledge_bases` / `knowledge_files` | 产品/企业 KB | RAG 检索源 |
| `sessions` | 单场对话 | persona_id, topic, config, outcome |
| `turns` | 对话轮 | session_id, idx, **role**(persona/sales), content, metadata_json |
| `evaluations` | Judge/Coach 评估 | evaluator_role(judge/coach), score_json, feedback_json |
| `sales_cases` | 销售案例库 | source(coach_auto…) |
| `batch_jobs` | 批量任务 | session_ids, config |
| `agent_profiles` | Agent 可编辑配置 | **目前仅 `sales` 一行**（V2 拟加 coach/analysis） |
| `agent_profile_versions` | 配置版本历史 | 回滚用 |
| `agent_skills_config` | 销冠工具开关 | web_search/MCP 等 |
| `product_handbooks` | 135910 手册主表 | structure_json |
| `handbook_files` | 手册源文件 | parsed_text |
| `analysis_jobs` | 分析任务 | summary_json（报告全量预聚合） |
| `turn_classifications` | 每句话分类+评分 | category_id, confidence, scores_json(6维), issues, suggestion, reference_text |
| `analysis_persona_insights` | 客户洞察缓存 | persona_cluster, top_concerns |
| `market_facts` | 市场事实缓存（V0.2.4） | 当地本品价/竞品价/促销，content_guard 证据源 |
| `brand_profiles` | 品牌定位+竞品 deny+兜底（V0.2.5） | 默认华为行 |

---

## 第 3 部分 · 核心链路

### 3.1 单场对话编排（`session.py`）
```
开场 → 循环(persona turn → judge 打分/指令 → sales turn → content_guard 改写) → 结束 → Coach 复盘
```
- 销冠 turn：RAG 检索 product/enterprise KB → 注入 handbook block（含十大演示动作）+ market_facts block + brand_profile block → LLM 出 JSON(`content` + `strategy`) → `content_guard.verify_and_rewrite` 改写未证实数字。
- content_guard 证据语料（V0.2.5 后）：handbook 全文 + market_facts + **KB 召回文本(product/enterprise hits)** + 本轮 tool_calls；命中任一即放行，否则中性降级（不再说"打开官网"）。

### 3.2 市场事实预研（`research/market_research.py` + `scripts/research_markets.py`）
对话前/批量前统一研究：从 handbook 抽产品/竞品名 → web_search（域名锁本地市场）→ LLM 蒸馏成 MarketFactSheet → 存 `market_facts`，供销冠注入 + content_guard 证据。

### 3.3 分析报告 pipeline（`analyzers/`）
```
POST /api/analysis/jobs
 → AnalysisRunner._run（analysis_runner.py）
 → 拉 handbook + 全部 sales turns
 → 每 turn: handbook_turn_analyzer（关键词预筛 Top-K 候选 → LLM 多标签分类 + 6 维打分）
 → 写 turn_classifications
 → report_aggregator.aggregate_report → analysis_jobs.summary_json
 → 前端 AnalysisReport.vue / report_html.py(导出 HTML) / routes_analysis.py(导出 MD)
```
报告板块（现状）：封面KPI · §0.5销售健康度 · §1执行摘要(6维雷达+模块覆盖) · §2优秀话术 · §3问题话术 · §4覆盖热图 · §5短板 · §6强项 · §7Persona洞察 · §8客户原声 · §9手册修订建议 · §10关键数字。

### 3.4 Coach 复盘（`coach.py`，13 维）
13 维硬编码于 `prompts/coach_prompt.md`(40-73行)：outcome_analysis / what_worked / what_failed / scene_fit_review / tool_use_review / persona_insight / key_lessons / suggested_rebuttals / difficulty_rating / reusable_tactics / playbook_coverage_review / weight_balance_review / localization_review。
存 `evaluations.feedback_json`；前端 `SessionDetail.vue` 仅渲染 6/13 维。

---

## 第 4 部分 · 分析报告内部机制（与 V2 改动强相关）

### 4.1 135910 覆盖率算法（现状）
`report_aggregator._coverage_by_group`：覆盖率 = `turn_classifications` 里出现过的 `category_id` ∈ 31 条 / 31。**只看分类命中，不扫对话关键词。**

### 4.2 6 维评分（现状）
维度：accuracy(口径对齐手册) / specificity / delivery / alignment / customer_relevance / compliance。`dim_avg` = 全局平均。**驱动**：优秀话术排序(avg_quality)、短板诊断、全局维度迭代建议。

### 4.3 优秀话术判定（现状）
`avg_quality >= 6.5` 取 Top15（HTML 截 8）。`_why_good` 显式写"与 Handbook 原文一致"。**缺陷**：只有命中手册条目的 turn 才有分类→才可能"优秀"，手册外金句结构性进不了池。

### 4.4 手册迭代建议（现状）
`_build_revision_proposals`：未覆盖(≤10) + 短板(≤8) + 全局维度短板，**硬编码模板文案**（所以雷同重复），无 LLM 逐条生成，无 135910 顺序。

---

## 第 5 部分 · V2 迭代规格（本次改动，决策已锁定）

> 决策来源：用户 2026-05-30 明确答复。以下为实现依据。

### 5.1 改动①：分析报告"可解释性"面板（用户原称 coach）
**目标**：报告页加按钮 → 弹窗，展示"这份报告从哪些维度分析、如何判优秀话术、覆盖率口径"等，提升导出 HTML 报告的可解释性。
**决策**：
- **Phase 1（先做·MVP）**：内容**固定写死**但**完全透明**，由代码真实口径渲染（维度定义、评分点、优秀话术标准、覆盖率口径、迭代建议生成方式）。因为导出 HTML 排版固定。
- **Phase 2（后续）**：维度/阈值/评分点做成**可自定义/可选择**，分析流水线读配置，报告与 HTML 随之变化。
**落点**：
- 前端：`web/src/views/scale/AnalysisReport.vue` 顶部加「分析说明」按钮 + `el-dialog`/抽屉组件（新增 `components/HAExplain.vue`）。
- 内容数据：Phase 1 可前端静态常量（与后端口径一一对应，需加注释锚定 `report_aggregator` / `handbook_turn_analyzer`）；Phase 2 由后端 `/api/analysis/meta` 返回配置。
- HTML 导出：`report_html.py` 在报告头部加一段「分析方法说明」，与弹窗同源文案。
**已定**：这份"说明"同时嵌进导出 HTML 头部，保证可解释性随报告走（用户确认 Phase 1 = 固定但完全透明）。

**已实现（v2.5）**：
- **单一事实源（`src/analyzers/methodology.py`）**：`build_methodology()` 直接复用代码常量（6 维评分 `SCORE_DIMENSIONS`、优秀话术分组 `excellence_scorer.GROUP_LABEL/ORDER`、教练 13 维对齐 `coach_prompt.md`），输出结构化 6 大说明板块（手册 135910 覆盖口径 / 6 维质量评分 / 优秀话术解耦判定 / 31 条迭代建议 / 演示双保险 / 教练 13 维）。**前端弹窗、HTML、Markdown 三端同源消费，永不漂移**。
- **聚合注入**：`report_aggregator.aggregate_report` → `summary["methodology"] = build_methodology()`。
- **前端（`AnalysisReport.vue`）**：封面右侧加「分析方法说明」按钮 → `ElDialog` 渲染各板块（标题/说明/逐项 name+desc），底部标注方法版本与"后续支持自定义"。类型 `Methodology` 进 `analysis.ts`。
- **HTML（`report_html.py`）**：`_methodology()` 渲染为 §00 固定可视板块（紧随封面，无需重排其余 01-07 编号），含 `.mth-*` 样式。
- **Markdown（`routes_analysis.py`）**：新增「〇、分析方法说明」段，逐板块逐项输出。
- **验证**：`render_analysis_html` 含 §00、六维口径"口径对齐"、教练"localization_review"等关键串均命中。
- **注意**：旧分析任务的 summary 无 `methodology` 字段（三端均优雅跳过）；**重跑分析后**面板/HTML/MD 才会出现该板块。

### 5.2 改动②：人设重构（删 4 CN + 加 40 海外 = 共 80）
**决策**：总数 **80**。删除 CN 人设 DB id **32/35/39/40**（陈墨/林悦/阿强/苏苏）。**不要 US**（已确认去掉）。
**市场范围（华为实际有销售的国家，来自用户提供清单）**：

| 区域 | 国家（ISO） | 有官网商城（market_facts 取价源） |
|------|------------|----------------------------------|
| 亚太 | 马来西亚MY · 泰国TH · 菲律宾PH · 越南VN · 印尼ID · 日本JP · 香港HK | 除越南(建设中)外均有 |
| 拉美 | 秘鲁PE · 智利CL · 墨西哥MX · 哥伦比亚CO · 巴西BR | 巴西**无**官网商城，其余有 |
| 中东非 | 沙特SA · 阿联酋AE · 埃及EG · 南非ZA · 卡塔尔QA · 科威特KW | 沙特/阿联酋/埃及有；南非/卡塔尔/科威特**无** |
| 欧洲 | 法国FR · 英国GB · 德国DE · 意大利IT · 西班牙ES · 波兰PL · 土耳其TR · 罗马尼亚RO · 荷兰NL · 捷克CZ · 匈牙利HU · 奥地利AT | 均有 |
| 欧亚 | 俄罗斯RU | 有 |

> 共 31 个销售国。现有非 CN 人设已覆盖 10 个：MY/PH/ID/TH/AE/SA/ZA/TR/MX/RU。
> **官网商城信息用途**：`scripts/research_markets.py` 预研时，有官网商城的国家优先锁官网域名取价；无官网商城的（巴西/南非/卡塔尔/科威特）退回授权零售商/电商域名。

**40 个新人设市场分布（欧洲为主，铺满尚未覆盖的销售国）**：

| 区块 | 国家 | 数量 |
|------|------|------|
| 欧洲（主力） | FR · GB · DE · IT · ES · PL · RO · NL · CZ · HU · AT（11 国） | ~22 |
| 亚太新增 | VN · JP · HK | ~6 |
| 拉美新增 | PE · CL · CO · BR | ~6 |
| 中东非新增 | EG · QA · KW | ~6 |
| **合计新增** | | **40** |

**最终 80 = 现有非 CN 40 + 新增 40**（欧洲占新增 ~55%）。
**实现步骤**：
1. 按 `训练文件/2.1 消费者人设.json` 同结构（`name/source(含当地社区平台)/tags/locale/prompt(长Markdown:角色-心理-消费行为-语言习惯-模拟指引)`）撰写 40 条，存为新 JSON。prompt 内嵌当地城市/货币/电商平台/本地竞品/语言习惯，**禁含 CN 关键词**。
2. `POST /api/personas/upload` 批量导入（或 `bulk_create_personas`）。
3. 删除 32/35/39/40。
4. 跑 `scripts/patch_persona_market.py` 推断 country_code/currency/market_domains。
5. 逐个 `extract_pressure` 抽 9 维参数。
6. 跑 `scripts/research_markets.py` 预热新市场 market_facts（按上表官网商城信息选域名）。

**已实现（v2.4）**：
- **前置：扩 `src/locales.COUNTRY_REGISTRY`**。原仅 10 个非 CN 市场，新增 **21 个销售国**（欧 FR/GB/DE/IT/ES/PL/RO/NL/CZ/HU/AT + 亚太 VN/JP/HK + 拉美 PE/CL/CO/BR + 中东非 EG/QA/KW），每国含 currency/符号/`market_domains`（无官网商城的 VN/BR/QA/KW 退授权零售域名）/infer_keywords。否则新人设全落 GLOBAL/USD，本地化与取价域名失效。
- **生成（`scripts/gen_overseas_personas.py`）**：内置 40 条 spec（国家/城市/独立本地姓名/原型/tier/生态倾向/135910 关注角），LLM(temp=0.9) 逐条按 2.1 同结构撰写中文 Markdown prompt，深度本地化、**围绕 135910 产品力而非砍价**；校验小节齐全 + CN 黑名单（含"深圳"/华为中国背景）+ tags/name 完整，失败重试 1 次；`--only` 支持单条补跑并入。产物 `训练文件/2.2 海外消费者人设_40.json`（40 条、无重名）。
- **落库（`scripts/apply_persona_restructure.py --apply`）**：`bulk_create_personas` 导入 40（新 id 46-85）→ `update_persona` 直写 country_code/currency/market_domains（用 spec 已知国家，比 infer 更准，**替代原步骤 4 的脚本**）→ 删 CN 32/35/39/40（`sessions` FK=ON DELETE SET NULL，12 条历史会话保留、persona 链置空）→ 并发 `extract_pressure_profile` 抽 9 维写回。默认 dry-run，`--apply` 落库。
- **体检通过**：persona 总数 **80**、CN 剩余 **0**、新 40 条市场字段与 9 维压力齐全；31 国分布（现有 10 市场×4 + 新 21 市场，无 US/CN）。
- **步骤 6（市场预研 `research_markets.py`）按用户决策留到下批运行前单独跑，护 Tavily 配额**。

### 5.3 改动③：演示覆盖率=0 修复 + 演示内容（）包裹【双保险】
**根因**：覆盖率只认 `demo_*` 分类；而演示句在关键词预筛阶段被卖点/参数挤出候选集（`handbook_classifier.shortlist_candidates`），且不在候选集的 category_id 被硬过滤丢弃（`handbook_turn_analyzer.py:131-160`）；turn 的 `metadata.playbook_action`("现场演示")根本不进分析。
**关键事实修正**：`turn.metadata.playbook_action` 是 **SPIN 方法论标签**（soft_hook / spin_need_payoff / reflection_paraphrase…），**不含演示信息**，无法用作演示信号。真正可靠信号在 **content 本身**（全角（）舞台指示 + 演示动词），历史与未来数据都适用。
**决策：双保险（均为 content 信号）**。
1. **生成侧**：`prompts/sales_prompt.md` 输出规则新增——**任何现场演示动作必须用全角（）包裹**（模型已偶发，固化为规则）。人工看对话一眼可辨。
2. **分析侧**（`has_demo_signal(content)`）：
   - 保险①：检测含动作词的全角（）舞台指示（如"（拿起样机演示）"）。
   - 保险②：检测演示动词（拿样机/上手/体验/试两笔/现场打开/给您看/演示…）。
   - 任一命中 → `shortlist_candidates(force_demo=True)` 把全部 `demo_*` 条目**保底放入候选集**，让 LLM 归到正确的 demo_x（解决 demo 被关键词预筛挤出候选的根因）。
**落点**：`prompts/sales_prompt.md`（输出格式段）、`analyzers/handbook_classifier.py`（新增 `has_demo_signal` + `shortlist_candidates(force_demo=)`）、`analyzers/handbook_turn_analyzer.py`（`analyze_turn_once` 算信号并传入）。

### 5.4 改动④：删除"六维话术评分"+"销售健康度"两个展示板块
**决策**：**只删展示板块**，**保留** turn 级 6 维打分作内部信号（继续驱动优秀话术/短板排序）。
**已实现（仅去展示，不动底层打分；后端 `dim_avg`/`engagement` 仍照常计算）**：
- 前端 `AnalysisReport.vue`：删 §0.5 销售健康度整段、§1 六维雷达卡（§1 改为仅"成交结果分布"+"6 大模块覆盖"，标题副标去掉"6 维评分雷达"）、封面"销冠 6 维总平均"块；连带移除孤儿 `radarOption`/`engagement`/`pctColor`/`overallSixDim` computed、`EngagementMetrics` 类型导入、`RadarChart` echarts 注册。每条话术内 6 维条**保留**（非"板块"，留给改动⑥重构）。
- HTML `report_html.py`：删 `_dimensions`/`_health` 函数与其在 `body_parts` 的调用、封面"手册提及率/推诿率"两个 KPI、孤儿 `_DIM_LABEL`；**章节重排连续**：01 覆盖率 / 02 手册迭代建议 / 03 强弱项 / 04 关键数字 / 05 客户原声 / 06 优秀话术 / 07 问题话术。
- MD `routes_analysis.py`：删 §二 6 维、§三 健康度；中文序号重排连续（一覆盖率 / 二弱项 / 三强项 / 四未覆盖 / 五优化建议 / 六关键数字 / 七优秀话术 / 八问题话术）。
- 验证：HTML 渲染 smoke 测试通过（无"六维话术评分"/"销售健康度"字样，迭代建议为 §02）。

### 5.5 改动⑤：手册迭代建议按 135910 逐条 LLM 生成（每条 + TOP3 话术）
**决策**：按 **31 个条目逐条** LLM 生成建议；**每个条目下再附 TOP3 命中话术原声**。即使表现好也必须给优化建议。去重。
**新逻辑**：
```
for cid in 31条(按 1→3→3→5→9→10 顺序):
    取该条 handbook 原文 + 命中它的所有 turn(含 issues/客户反应) + TOP3 高分原声
    → LLM 产出 {评估, 建议(保持/强化/补充/修正), top3_quotes}
报告按结构顺序逐条一卡渲染
```
**成本**：≤31 次 LLM/报告（可按 6 组批量），相对 745 turn 分析是小头，SLA 内。
**落点**：新增 `analyzers/handbook_revisor.py`（逐条 LLM）；`report_aggregator` 调用并写 `summary_json.revision_proposals`（重构为按结构分组）；前端 §9 + HTML §04 改为结构顺序渲染；**删除页脚重复摘要**（`AnalysisReport.vue` 2053-2064）与模板雷同文案。

**已实现（v2.3）**：
- 新增 `analyzers/handbook_revisor.py`：`_iter_categories` 铺平结构得**有序 31 条**（1→3→3→5→9→10），逐条汇总覆盖（命中/场次/非accuracy均分）+ TOP3 命中原声（按非accuracy维度排序，与⑥解耦理念一致）+ **批量分片 LLM**（每片 5 条）产出 `{status(保持/强化/补充/修正/新增), assessment, suggestion}`；**即使表现好也给增强点**；LLM 失败回退确定性模板。
- `report_aggregator` 新增 `summary.handbook_revisions`（保留旧 `revision_proposals` 向后兼容）。
- 三端展示：前端 `AnalysisReport.vue` §9 改"按 135910 分组 + 逐条卡片（status 徽标 + 覆盖 + 评估 + 建议 + TOP3 原声）"，移除旧 `revisionProposals`/`REVISION_KIND_*`/`SEVERITY_*` 孤儿；HTML `_proposals`（§02）改分组逐条 + TOP3；MD §五同步。
- 验证：真实会话 `use_llm=False` 跑出**恰好 31 条**、结构顺序正确、覆盖条目带 TOP3 原声、status 分布合理（新增/保持/强化）；HTML §02 smoke 渲染含分组头 + status 徽标 + TOP3。
- **成本**：≤31 条 LLM（分片后约 7 次调用/报告），相对 745 turn 分析是小头，SLA 内。

### 5.6 改动⑥：优秀话术——解耦手册一致性 + 按 135910 归类 + 数量/折叠
**决策：(c) 两者结合**——优秀 = **LLM 判定"是否优秀销售话术(不论手册有无)" + 行为信号(客户下一轮 purchase_signal 上升 / attitude 转正 / 异议化解 / judge 高分)**。
**核心架构改动**：优秀话术判定**不再以手册一致性(accuracy)为门槛**。
- 需对**所有 sales turn**（不只命中手册的）做"有效性"评估，否则手册外金句进不了池。
- 新增"有效性分"：行为信号 + 独立 LLM 优秀度评分，二者结合排序。
**展示**：按 135910 归类——**一句话(开场) / 3卖点 / 竞品 / FAQ / 演示** 各一组优秀原声，**外加一组"手册外精彩话术"**（手册没有但很好，直接喂给改动⑤做手册迭代）。每组更多条 + 折叠展开；去掉后端 15 条硬上限。
**落点**：新增 `analyzers/excellence_scorer.py`（行为信号 + LLM 优秀度，覆盖全 sales turn）；`report_aggregator._build_turn_highlights` 重构（解耦 accuracy，按组归类，加"手册外"组）；前端 §2 改分组 + 折叠；修正空文案阈值 drift（1498 写 7.5 vs 后端 6.5）。

**已实现（v2.2）**：
- **关键 bug 修复**：`_load_turn_index` 原把 turn 按 `(session_id, idx)` 入 dict，而 **persona 与 sales 同轮共享 idx**（每轮：persona 先说→sales 同 idx 应答），dict 键碰撞导致 persona 轮被 sales 覆盖、purchase_signal 全丢。改为额外返回 `turns_by_session`（无损全量有序列表），行为信号据此取邻居。
- **行为信号（免费）**：sales@idx i 的效果 = persona@idx i+1 的 `purchase_signal` 相对 persona@idx i 的涨幅（归一化）+ attitude 正向度 + WALK_AWAY/COMPLAINT 惩罚。`_behavioral_score = 0.45·ps_after + 0.30·Δnorm + 0.25·attitude_pos`，流失×0.3、投诉×0.15。
- **候选池（有界，控成本）**：命中手册 top36（按 0.5·behavioral+0.5·非accuracy维度均分）∪ 未命中手册且 behavioral≥6 的 top16 → 封顶 ~52 条。
- **LLM 优秀度（解耦 accuracy）**：对候选池分片（每片 10 条）批量打 0-10 优秀度 + why_good，**绝不以是否照搬手册为门槛**；失败分片静默回退到行为信号合成的 why。`final = 0.5·behavioral + 0.5·llm`。
- **分组**：命中手册→按主标签 135910 组；未命中→`off_handbook`。输出 `summary.excellent_by_group = {groups:[{key,label,count,items}], total}`，每组上限 20、去掉旧 15 条全局硬上限。
- **三端展示**：前端 `AnalysisReport.vue` §2 改"按手册结构分组 + 每组折叠（默认 3 条）"，新增 `exc-*` 卡片样式 + `ExcellentGroup/ExcellentTurn` 类型；HTML `report_html.py` 新增 `_excellent_groups`（§06，off_handbook 橙色徽标）；MD `routes_analysis.py` §七 改分组渲染。
- **验证**：真实会话（job 18）`use_llm=False` 跑通——ps 0.4→0.7 的演示句得 behavioral 8.5 / excellence 8.4，why_good 正确给出"购买信号上升/态度转 interested"；HTML smoke 渲染含 §06 + 手册外橙标。

### 5.7 联动关系（实现顺序建议）
1. 改动③（）包裹先行 → 改动⑥演示类优秀原声 + 演示覆盖率都依赖它。
2. 改动④保留底层打分 → 改动⑥仍可用 avg_quality 辅助，但主判定换"有效性"。
3. 改动⑥产出的"手册外精彩话术" → 喂改动⑤逐条迭代建议。
4. 改动①可解释性面板最后做（待②~⑥口径定稿后，说明文案才准）。

---

## 第 6 部分 · 路线图 & 待办

- [x] V2-① 报告可解释性面板（Phase 1 固定透明）✅ 单一事实源 methodology.py，前端弹窗 + HTML §00 + MD 同源
- [x] V2-② 80 人设重构（删4 CN + 40 海外，欧洲为主，按销售国清单，**无 US**）✅ 已落库并体检（80/0 CN/市场字段+9维压力齐全）；步骤6市场预研留到下批前单独跑
- [x] V2-③ 演示（）包裹 + 双保险映射 ✅ 已实现并单测验证
- [x] V2-④ 删两个展示板块（保留内部打分）✅ 已实现并 smoke 验证
- [x] V2-⑤ 逐条(31)迭代建议 + 每条 TOP3 原声 ✅ 已实现并真实数据验证
- [x] V2-⑥ 优秀话术解耦手册一致性 + 135910 归类 + 折叠 ✅ 已实现并真实数据验证
- [ ] （Phase 2）报告维度/阈值可配置化

---

## 第 7 部分 · 变更记录
| 日期 | 版本 | 改动 | 备注 |
|------|------|------|------|
| 2026-05-27 | v1.0 | 分析报告模块原始设计 | 见 `handbook_analysis_dev_spec.md` |
| 2026-05-29 | v1.x | 市场事实缓存 / 品牌解耦 / content_guard KB 放行 / HTML 导出 | 已上线（运行时验证） |
| 2026-05-30 | v2.0 | 本主文档建立；锁定 V2 六项迭代规格 | 待实现 |
| 2026-05-30 | v2.1 | 实现 ③ 演示双保险（sales_prompt（）规则 + `has_demo_signal` + `shortlist_candidates(force_demo=)`）；单测：演示句拿全 10 个 demo 候选、价格句 0 个 | 分析侧改动需重启后端才对新分析任务生效；（）规则对新对话即时生效 |
| 2026-05-30 | v2.1 | 实现 ④ 删两展示板块（前端 Vue / HTML / MD 三端），章节重排连续，保留内部打分 | HTML smoke 测试通过 |
| 2026-05-30 | v2.2 | 实现 ⑥ 优秀话术解耦：新增 `excellence_scorer.py`（行为信号⊕LLM，解耦 accuracy，135910+手册外分组）；修复 `_load_turn_index` persona/sales 同 idx 键碰撞丢 purchase_signal 的 bug；前端 §2 分组折叠 + HTML §06 + MD §七 | 真实数据(job18) use_llm=False 验证通过；分析侧改动需重启后端对新任务生效 |
| 2026-05-30 | v2.3 | 实现 ⑤ 逐条迭代建议：新增 `handbook_revisor.py`（有序31条 + 批量分片LLM + 每条TOP3原声 + 回退）；`summary.handbook_revisions`；前端 §9 / HTML §02 / MD §五 改按 135910 逐条渲染 | 真实数据 use_llm=False 验证：恰好31条、顺序对、带TOP3 |
