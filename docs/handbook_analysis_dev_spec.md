# 产品话术分析报告 · 开发文档

> **代号**：Handbook Analysis（HA）
> **版本**：v1.0 draft
> **日期**：2026-05-27
> **目标**：在「规模化测试」板块下新增「分析报告」模块，按产品文档的 **1/3/3/5/9/10 框架**对销冠对话做归因分类、内容评分、客户洞察与文档反推建议。

---

## 0. 背景与定位

### 0.1 痛点

当前 `BatchReport.vue`（规模化测试 → 批量报告）的所有指标都是**销售方法论维度**（SPIN、5 阶段 playbook、Outcome 分布、五维雷达），完全没有围绕**产品文档内容**做归因。无法回答：

- 销冠是否在认真使用产品文档？
- 哪些卖点/FAQ/演示动作被用得多/少/错？
- 客户最关心哪些维度？产品文档是否覆盖到？
- 销冠在「乱聊」（脱离文档）vs「准确引用」的占比？

### 0.2 模块定位

- **入口**：左侧栏「规模化测试」组，新增第 3 项「分析报告」（与「批量测试」「批量报告」平行）。
- **输入**：已完成的 batch + 用户上传的 Handbook 文档（PPT/PDF/Word/Markdown 等）。
- **输出**：覆盖矩阵、原声归因、客户洞察、文档改进建议、合规度等 9 大板块。
- **与现有模块的关系**：与 `BatchReport.vue` **并列**，不替换。Batch Report 看"销售方法论"层面，Handbook Analysis 看"产品话术内容"层面，两者互补。

---

## 1. 业务需求确认（来自用户决策）

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 一条发言能否归到多个类别 | ✅ **允许多标签**：同一条发言同时引用了"卖点②+参数③"则两个分类都计入，分别评分 |
| 2 | 评分维度数量 | **多维度**：6 个维度（详见 §4.2） |
| 3 | Handbook 数据来源 | **专门上传入口**，支持 .pptx / .pdf / .docx / .doc / .txt / .md / .xlsx 多格式，统一解析为结构化文本供销冠 / 分类器调用 |
| 4 | 模块挂载位置 | 「规模化测试」组下新增「分析报告」（`/batch/analysis`） |
| 5 | 防幻觉 | 本文档完整覆盖所有设计细节，所有 API/字段/路径基于现有真实代码 |

---

## 2. 1/3/3/5/9/10 知识框架定义

每个产品的 Handbook 都按以下固定结构组织：

| 序号 | 类别 | 数量 | 标签 ID 命名 |
|------|------|------|------------|
| 1 | 一句话定位 | 1 | `intro_1` |
| 2 | 核心卖点 | 3 | `sell_1`, `sell_2`, `sell_3` |
| 3 | 竞品分析点 | 3 | `comp_1`, `comp_2`, `comp_3` |
| 4 | 核心参数 | 5 | `param_1` ~ `param_5` |
| 5 | FAQ 问答 | 9 | `faq_1` ~ `faq_9` |
| 6 | 演示动作 | 10 | `demo_1` ~ `demo_10` |
| - | 其他（兜底） | - | `other`（非产品内容：寒暄/收尾等） |

**类别合计**：1+3+3+5+9+10 = **31 个知识标签** + `other` 兜底。

---

## 3. 数据模型设计

### 3.1 新增数据库表（5 张）

#### Table 1: `product_handbooks`（产品手册主表）

```sql
CREATE TABLE IF NOT EXISTS product_handbooks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,              -- "华为 MatePad 12X Handbook"
    product_kb_id   INTEGER REFERENCES knowledge_bases(id) ON DELETE SET NULL,
                                                          -- 关联产品 KB（同一产品复用）
    description     TEXT,
    structure_json  TEXT    NOT NULL DEFAULT '{}',        -- 完整 1/3/3/5/9/10 结构化文本
    source_files_json TEXT  NOT NULL DEFAULT '[]',        -- 来源文件清单
    status          TEXT    NOT NULL DEFAULT 'draft',     -- draft / extracting / ready / failed
    extraction_log  TEXT,                                 -- LLM 抽取日志
    version_no      INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
```

`structure_json` schema：

```json
{
  "intro_1": {
    "id": "intro_1",
    "label": "一句话定位",
    "text": "MatePad 12X 是华为旗舰平板，主打...",
    "source": "page_3_of_pptx"
  },
  "selling_points": [
    {"id": "sell_1", "label": "卖点①·云晰柔光屏", "text": "...", "source": "..."},
    {"id": "sell_2", "label": "卖点②·全场景生产力", "text": "...", "source": "..."},
    {"id": "sell_3", "label": "卖点③·M-Pencil Pro", "text": "...", "source": "..."}
  ],
  "competitor_points": [
    {"id": "comp_1", "label": "竞品①·iPad Air 对比", "text": "...", "vs": "iPad Air"},
    {"id": "comp_2", "label": "竞品②·iPad Pro 对比", "text": "...", "vs": "iPad Pro"},
    {"id": "comp_3", "label": "竞品③·三星 Tab S9", "text": "...", "vs": "三星 Tab S9"}
  ],
  "core_params": [
    {"id": "param_1", "label": "参数①·屏幕", "text": "12 寸 / 3K / 144Hz / DCI-P3 100%"},
    {"id": "param_2", "label": "参数②·处理器", "text": "..."},
    {"id": "param_3", "label": "参数③·内存存储", "text": "..."},
    {"id": "param_4", "label": "参数④·电池", "text": "..."},
    {"id": "param_5", "label": "参数⑤·重量厚度", "text": "..."}
  ],
  "faq": [
    {"id": "faq_1", "label": "FAQ①", "q": "和华为手机如何联动？", "a": "..."},
    {"id": "faq_2", "label": "FAQ②", "q": "...", "a": "..."},
    ... (共 9 条)
  ],
  "demo_actions": [
    {"id": "demo_1", "label": "演示①·开机展示", "text": "邀请客户上手 → 演示..."},
    {"id": "demo_2", "label": "演示②·分屏多任务", "text": "..."},
    ... (共 10 条)
  ]
}
```

#### Table 2: `handbook_files`（Handbook 来源文件）

```sql
CREATE TABLE IF NOT EXISTS handbook_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    handbook_id  INTEGER NOT NULL REFERENCES product_handbooks(id) ON DELETE CASCADE,
    filename     TEXT    NOT NULL,
    file_path    TEXT    NOT NULL,
    file_type    TEXT,                                    -- pptx / pdf / docx / md / txt / xlsx
    file_size    INTEGER,
    parsed_text  TEXT,                                    -- parse_file 提取的全文（≤500KB 直接存表）
    status       TEXT    NOT NULL DEFAULT 'pending',      -- pending / parsing / parsed / failed
    error_msg    TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
```

> 复用 `src/rag/parsers.py` 的 `parse_file()`，所有支持的格式（.pptx/.pdf/.docx/.md/.txt/.xlsx）开箱即用。

#### Table 3: `analysis_jobs`（分析任务）

```sql
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        INTEGER NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
    handbook_id     INTEGER NOT NULL REFERENCES product_handbooks(id) ON DELETE CASCADE,
    status          TEXT    NOT NULL DEFAULT 'pending',   -- pending / running / completed / failed
    progress        REAL    NOT NULL DEFAULT 0.0,         -- 0.0 ~ 1.0
    total_turns     INTEGER NOT NULL DEFAULT 0,           -- 本次需分类的销冠 turn 总数
    classified_turns INTEGER NOT NULL DEFAULT 0,
    summary_json    TEXT,                                 -- 完整分析结果（含板块 1-9 数据）
    error_msg       TEXT,
    started_at      TEXT,
    ended_at        TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
```

#### Table 4: `turn_classifications`（每条 turn 的分类结果）

```sql
CREATE TABLE IF NOT EXISTS turn_classifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_job_id INTEGER NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    session_id      TEXT    NOT NULL,
    turn_idx        INTEGER NOT NULL,
    category_id     TEXT    NOT NULL,                     -- intro_1 / sell_1 / faq_3 / other ...
    confidence      REAL    NOT NULL DEFAULT 0.0,         -- 0.0 ~ 1.0
    scores_json     TEXT    NOT NULL DEFAULT '{}',        -- 6 维评分
    issues_json     TEXT    NOT NULL DEFAULT '[]',        -- 识别到的问题
    suggestion      TEXT    NOT NULL DEFAULT '',          -- 改进建议
    reference_text  TEXT    NOT NULL DEFAULT '',          -- 对照的 Handbook 原文片段
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turn_cls_job ON turn_classifications(analysis_job_id);
CREATE INDEX IF NOT EXISTS idx_turn_cls_category ON turn_classifications(analysis_job_id, category_id);
```

> **多标签实现**：一条 turn 可在本表插入多行（不同 category_id），用 `(session_id, turn_idx)` 关联回原 turn。

#### Table 5: `analysis_persona_insights`（客户洞察缓存）

```sql
CREATE TABLE IF NOT EXISTS analysis_persona_insights (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_job_id INTEGER NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    persona_id      INTEGER REFERENCES personas(id) ON DELETE SET NULL,
    persona_cluster TEXT,                                 -- LLM 聚类标签："学生" / "办公族" / ...
    top_concerns_json TEXT  NOT NULL DEFAULT '[]',        -- 该 cluster 高频关注点
    sample_objections_json TEXT NOT NULL DEFAULT '[]',
    deal_rate       REAL,
    avg_quality     REAL,
    created_at      TEXT    NOT NULL
);
```

### 3.2 修改现有表

**无需修改**任何现有表。Handbook Analysis 通过外键关联 `batch_jobs / personas / sessions / turns / evaluations`，全部只读。

---

## 4. 分类器与评分设计

### 4.1 分类策略（双轨）

```
sales turn → 候选预筛（向量相似度） → LLM 精分类 → 多标签写库
```

**Step A：候选预筛（embedding-based）**

- 对 Handbook 的 31 个 chunk 预先生成向量（用现有 `Embedder` = `paraphrase-multilingual-MiniLM-L12-v2`）
- 对待分类的销冠 turn 文本生成向量
- 计算余弦相似度，**top-5** 候选类别送入 LLM 精分类
- 优势：减少 LLM 调用 token；筛掉显然无关的候选

**Step B：LLM 精分类（决定最终标签 + 评分）**

```text
prompt: 你是产品话术分类员。下面是销冠的一句话，请判断它是否属于以下候选类别中的任何一个/多个：

[销冠原声]
"这台你可以同时开 PPT、WPS 文档、微信和浏览器，4 个分屏完全不卡。"

[候选类别 Top-5（来自向量预筛）]
- sell_2 · 卖点②·全场景生产力：「搭配 NearLink 键盘可获接近笔记本的输入手感，分屏可同时打开 4 个应用...」
- param_3 · 参数③·内存存储：「12GB+256GB 内存配置...」
- faq_5 · FAQ⑤：「Q: 同时开多个 app 会不会卡？A: ...」
- demo_2 · 演示②·分屏多任务：「演示同时打开 4 个 app 的分屏操作...」
- other

请输出 JSON：
{
  "matched": [
    {"category_id": "sell_2", "confidence": 0.85},
    {"category_id": "demo_2", "confidence": 0.60}
  ],
  "scores": {
    "accuracy": 8,
    "specificity": 9,
    "delivery": 7,
    "alignment": 9,
    "customer_relevance": 8,
    "compliance": 10
  },
  "issues": ["未引用文档中的 NearLink 键盘"],
  "suggestion": "补充：搭配 NearLink 键盘可获接近笔记本输入手感"
}
```

### 4.2 6 个评分维度（每个 0~10）

| 维度 | 含义 | 用于诊断 |
|------|------|---------|
| `accuracy` | **准确性**：与 Handbook 原文事实是否吻合（数字/规格/政策） | 检测乱编规格 |
| `specificity` | **具体度**：是否给出具体数字/品名/型号（vs 模糊形容词） | 检测"品质更好"等空话 |
| `delivery` | **话术质量**：流畅度、说服力、是否结合客户上下文 | 检测话术功底 |
| `alignment` | **文档贴合度**：与 Handbook 原文表述方向是否一致 | 检测是否在引用文档 |
| `customer_relevance` | **客户契合度**：是否回应了客户本轮真实需求 | 检测答非所问 |
| `compliance` | **合规性**：是否说了 Handbook 明确否定/未授权的内容 | 检测越界承诺 |

**复合指标**（由这 6 维派生）：

- `overall_score` = 6 维加权平均（默认等权）
- `is_excellent` = `overall_score >= 8.5 AND accuracy >= 8`
- `is_failed` = `overall_score < 5 OR compliance < 6 OR accuracy < 5`

### 4.3 模型选型

| 任务 | 模型 | 理由 |
|------|------|------|
| 向量预筛 | `paraphrase-multilingual-MiniLM-L12-v2`（现有 Embedder） | 0 成本，已部署 |
| LLM 精分类 | 默认 `MODEL_NAME`（DeepSeek-Chat） | 复用现有 Provider；后续可配置专用模型 |

**Token 估算**：

- 单次 LLM 调用约 1.5K~2K tokens（prompt + 5 候选 + 销冠原文）
- 单场 30 轮对话 → 15 sales turns → 15 次 LLM 调用
- 120 场 batch → 约 1800 次 → DeepSeek 约 ¥3-5 / 批次

---

## 5. 后端 API 设计

### 5.1 模块文件清单

```
src/
├── api/
│   ├── routes_handbook.py            # Handbook CRUD + 上传 + 解析触发
│   └── routes_analysis_report.py     # 分析任务 CRUD + 9 个报告聚合接口
├── analyzers/
│   ├── __init__.py
│   ├── handbook_extractor.py         # 从 parsed_text → 1/3/3/5/9/10 结构提取（LLM）
│   ├── handbook_classifier.py        # turn 分类 + 评分核心引擎
│   ├── persona_clusterer.py          # 客户共性聚类
│   └── document_advisor.py           # 文档改进建议生成
└── storage/
    └── models.py                     # 追加 5 张表的 SCHEMA + ALL_SCHEMAS 注册
```

### 5.2 Handbook 管理 API（前缀 `/api/handbooks`）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/handbooks` | 列出所有 handbook |
| POST | `/api/handbooks` | 新建 handbook（仅 name + product_kb_id + description） |
| GET | `/api/handbooks/{id}` | 详情，含 `structure_json` |
| PUT | `/api/handbooks/{id}` | 修改 name / description / structure_json（人工校对后可手改） |
| DELETE | `/api/handbooks/{id}` | 删除 |
| POST | `/api/handbooks/{id}/files` | **上传文件（multipart）**，支持 .pptx/.pdf/.docx/.md/.txt/.xlsx |
| GET | `/api/handbooks/{id}/files` | 该 handbook 的文件列表 + 解析状态 |
| DELETE | `/api/handbooks/{id}/files/{file_id}` | 删除文件 |
| POST | `/api/handbooks/{id}/extract` | 触发 LLM 抽取 1/3/3/5/9/10 结构（后台任务） |
| GET | `/api/handbooks/{id}/extract_status` | 查询抽取进度 |

### 5.3 分析任务 API（前缀 `/api/analysis`）

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/analysis/jobs` | 新建分析任务（body: `{batch_id, handbook_id}`） |
| GET | `/api/analysis/jobs` | 列出所有分析任务 |
| GET | `/api/analysis/jobs/{id}` | 详情 + 进度 |
| DELETE | `/api/analysis/jobs/{id}` | 删除（级联清掉 turn_classifications） |
| POST | `/api/analysis/jobs/{id}/cancel` | 取消运行中的任务 |
| WS | `/ws/analysis/{job_id}` | 实时进度推送（可选，简单实现可用轮询） |

### 5.4 分析报告聚合 API（前缀 `/api/analysis/jobs/{job_id}/report`）

| Method | Path | 对应前端板块 |
|--------|------|-------------|
| GET | `/cover` | 板块 1：报告封面（量化指标） |
| GET | `/highlights` | 板块 2：精彩 TOP10 + 失效 + 高复用模板 + 禁用清单 |
| GET | `/coverage_matrix` | 板块 3：知识点矩阵（31 行） |
| GET | `/category/{category_id}` | 板块 3 子页：单个类别详情抽屉（原声 + 评分 + 改进） |
| GET | `/customer_insights` | 板块 4：共性 + 差异化 + 走人热力 |
| GET | `/document_advice` | 板块 5：文档改进建议 |
| GET | `/compliance` | 板块 6：合规度（乱聊检测） |
| GET | `/trend` | 板块 7：跨批次趋势对比 |
| GET | `/export?format=md\|pdf\|json` | 板块 9：导出报告 |

### 5.5 注册入口

在 `src/api/server.py` 追加：

```python
from src.api.routes_handbook import router as handbook_router
from src.api.routes_analysis_report import router as analysis_report_router

app.include_router(handbook_router)
app.include_router(analysis_report_router)
```

并在 lifespan 中追加表初始化：

```python
# 在现有 init_schema(conn) 之后，自动包含新增 5 张表
# （因为 ALL_SCHEMAS 已注册，无需额外代码）
```

---

## 6. 前端模块设计

### 6.1 路由与导航

**路由追加**（`web/src/router/index.ts`）：

```ts
{
  path: 'batch/analysis',
  name: 'batch-analysis',
  component: () => import('@/views/scale/AnalysisReport.vue'),
  meta: { title: '分析报告', group: 'batch' },
},
{
  path: 'batch/handbooks',
  name: 'batch-handbooks',
  component: () => import('@/views/scale/HandbookManager.vue'),
  meta: { title: '产品手册', group: 'batch' },
},
```

**侧边栏追加**（`web/src/layouts/AppShell.vue`）：

```ts
{
  id: 'batch',
  title: '规模化测试',
  items: [
    { to: '/batch/run', label: '批量测试', icon: Layers },
    { to: '/batch/report', label: '批量报告', icon: FileBarChart },
    { to: '/batch/analysis', label: '分析报告', icon: Microscope },    // ← 新增
    { to: '/batch/handbooks', label: '产品手册', icon: BookText },     // ← 新增
  ],
},
```

### 6.2 前端文件清单

```
web/src/
├── api/
│   ├── handbook.ts                    # Handbook CRUD + 上传
│   └── analysis_report.ts             # 分析任务 + 9 个报告接口
├── views/scale/
│   ├── HandbookManager.vue            # 产品手册管理（上传 + 校对结构）
│   ├── AnalysisReport.vue             # 分析报告主页（9 大板块容器）
│   └── components/
│       ├── HACover.vue                # 板块 1：封面
│       ├── HAHighlights.vue           # 板块 2：精彩话术四联屏
│       ├── HACoverageMatrix.vue       # 板块 3：知识点矩阵
│       ├── HACategoryDrawer.vue       # 板块 3 子抽屉：单类别详情
│       ├── HACustomerInsights.vue     # 板块 4：客户洞察
│       ├── HADocumentAdvice.vue       # 板块 5：文档改进
│       ├── HACompliance.vue           # 板块 6：合规度
│       ├── HATrend.vue                # 板块 7：跨批次趋势
│       └── HASessionLink.vue          # 通用：点击原声 → 跳 SessionDetail
```

### 6.3 上传 UI 设计（HandbookManager.vue）

复用现有 KB 上传组件 `ElUpload`，参数：

```vue
<ElUpload
  drag
  multiple
  :auto-upload="true"
  :http-request="customUpload"
  accept=".pptx,.pdf,.docx,.doc,.txt,.md,.xlsx"
  :before-upload="validateFile"
>
  <template #default>
    <div class="upload-hint">
      <UploadCloud :size="48" />
      <h3>拖拽或点击上传产品手册</h3>
      <p>支持 PPT / PDF / Word / Excel / Markdown / TXT，单文件 ≤ 50MB</p>
    </div>
  </template>
</ElUpload>
```

上传后流程：

```
文件落盘 (data/handbook_uploads/) → parse_file() → 文本入库 handbook_files.parsed_text
→ 用户点击「提取 1/3/3/5/9/10 结构」 → LLM 抽取 → 校对编辑器 → 保存
```

### 6.4 9 大板块布局（AnalysisReport.vue）

```
┌─────────────────────────────────────────────────────────────────┐
│ [选择批次 ▾] [选择 Handbook ▾] [▶ 开始分析] [⟳ 刷新] [📥 导出]    │
├─────────────────────────────────────────────────────────────────┤
│ 板块 1：报告封面                                                  │
│ ┌──────┬──────┬──────┬──────┬──────┐                            │
│ │ 44   │ 120  │ 22/31│ 71%  │ 7.8 │                             │
│ │ 人设 │ 场次 │ 覆盖 │ 准确 │ 综合│                             │
│ └──────┴──────┴──────┴──────┴──────┘                            │
│ [覆盖竞品标签云] [覆盖渠道] [覆盖市场] [Handbook 健康度仪表盘]    │
├─────────────────────────────────────────────────────────────────┤
│ 板块 2：话术总览四联屏                                            │
│ ┌────────────────┬────────────────┐                            │
│ │ 🌟 TOP10 精彩原声  │ ⚠ TOP10 失效话术 │                          │
│ ├────────────────┼────────────────┤                            │
│ │ ✅ 高复用模板话术 │ 🚫 禁用表达清单  │                          │
│ └────────────────┴────────────────┘                            │
├─────────────────────────────────────────────────────────────────┤
│ 板块 3：1/3/3/5/9/10 知识点矩阵                                  │
│ [一句话定位 ▸ 1/1]                                              │
│ [核心卖点  ▸ 3/3]  [展开看每个卖点]                              │
│ [竞品分析  ▸ 2/3]  [展开看每个竞品]   ← 缺 1 个                  │
│ [核心参数  ▸ 5/5]                                                │
│ [FAQ      ▸ 7/9]  [展开]              ← 缺 2 个                  │
│ [演示动作  ▸ 4/10] [展开]              ← 缺 6 个 ⚠               │
│                                                                  │
│ 点击某行 → 抽屉打开 HACategoryDrawer：                            │
│   - 该类别 Handbook 原文                                         │
│   - 命中的销冠原声（最多 20 条，按得分排）                        │
│   - 每条：6 维评分雷达 + 问题 + 改进建议 + 跳转 session            │
├─────────────────────────────────────────────────────────────────┤
│ 板块 4：客户洞察                                                  │
│ - 共性关注点 Top 10（横向条形图）                                 │
│ - 客户分桶（聚类）+ 各桶关注点对比                                │
│ - 走人原因 × 阶段热力图                                          │
├─────────────────────────────────────────────────────────────────┤
│ 板块 5：文档改进建议                                              │
│ - P0/P1/P2 三级建议清单                                          │
│ - 每条带证据链（频次、对比数据、推荐补充内容）                     │
├─────────────────────────────────────────────────────────────────┤
│ 板块 6：销冠合规度                                                │
│ - 引用准确/有偏差/乱编 三色饼图                                   │
│ - Top 10 高频"乱编"案例（提供给培训方）                          │
├─────────────────────────────────────────────────────────────────┤
│ 板块 7：跨批次趋势（最近 7 次）                                   │
│ - 覆盖率 / 准确率 / 成单率 三条折线                              │
├─────────────────────────────────────────────────────────────────┤
│ 板块 8：单场跳转（隐式，散落在所有原声里）                        │
│ 板块 9：导出（Markdown / PDF / JSON）                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 数据流总览

```
─────────────────────────────────────────────────────────
阶段 A：Handbook 准备（一次性）
─────────────────────────────────────────────────────────
用户上传 PPT/PDF/Word
   ↓
parse_file() 解析 → handbook_files.parsed_text
   ↓
点击「提取结构」→ LLM 一次性抽取 1/3/3/5/9/10
   ↓
product_handbooks.structure_json
   ↓
（可选）人工校对编辑器修正

─────────────────────────────────────────────────────────
阶段 B：销冠运行时（沿用现有 RAG，无变化）
─────────────────────────────────────────────────────────
销冠对话 → turns 表

─────────────────────────────────────────────────────────
阶段 C：批量结束后，触发分析任务
─────────────────────────────────────────────────────────
POST /api/analysis/jobs {batch_id, handbook_id}
   ↓
拉取 batch 的所有 sales turns（已有 src/api/routes_batch_report.py:_load_bundle）
   ↓
循环每条 sales turn：
   ├─ 向量预筛 → top-5 候选类别
   ├─ LLM 精分类 → 多标签 + 6 维评分
   └─ 写入 turn_classifications
   ↓
全部分类完成后，跑聚合：
   ├─ persona_clusterer.py → analysis_persona_insights
   ├─ document_advisor.py  → summary_json.document_advice
   └─ 9 大板块预聚合 → summary_json

─────────────────────────────────────────────────────────
阶段 D：前端拉报告
─────────────────────────────────────────────────────────
GET /api/analysis/jobs/{id}/report/*
   ↓
9 大板块渲染
```

---

## 8. 算法核心：分类器伪代码

```python
# src/analyzers/handbook_classifier.py

from src.rag.embedder import get_embedder
from src.llm import call_llm_json

def classify_turn(
    turn_content: str,
    turn_context: str,           # 上下文：上一轮 persona 发言
    handbook_structure: dict,    # 1/3/3/5/9/10 JSON
    handbook_embeddings: dict,   # 预计算的 {category_id: vector}
    topk: int = 5,
) -> dict:
    """对单条 sales turn 做多标签分类 + 6 维评分。"""
    # Step 1: 向量预筛
    emb = get_embedder()
    query_vec = emb.embed([turn_content])[0]
    sims = []
    for cid, hv in handbook_embeddings.items():
        sims.append((cid, cosine(query_vec, hv)))
    candidates = sorted(sims, key=lambda x: -x[1])[:topk]

    # 若所有相似度 < 0.3 → 直接判为 other，跳过 LLM 调用
    if candidates[0][1] < 0.3:
        return {
            "matched": [{"category_id": "other", "confidence": 1.0}],
            "scores": _default_scores_for_other(turn_content),
            "issues": [],
            "suggestion": "",
        }

    # Step 2: LLM 精分类
    cand_texts = []
    for cid, _ in candidates:
        node = _lookup_category(handbook_structure, cid)
        cand_texts.append(f"- {cid} · {node['label']}: {node['text'][:200]}")

    prompt = _CLASSIFIER_PROMPT.format(
        turn=turn_content,
        context=turn_context,
        candidates="\n".join(cand_texts),
    )
    result = call_llm_json(_SYSTEM_PROMPT, prompt)

    # Step 3: 校验 + 兜底
    matched = result.get("matched", [])
    if not matched:
        matched = [{"category_id": "other", "confidence": 0.5}]
    return {
        "matched": matched,
        "scores": result.get("scores", _empty_scores()),
        "issues": result.get("issues", []),
        "suggestion": result.get("suggestion", ""),
    }
```

---

## 9. 实施计划（4 个 Sprint）

### Sprint 1（数据基础 · 3 天）

- [ ] DB schema 追加 5 张表 + 注册到 `ALL_SCHEMAS`
- [ ] `src/storage/db.py` 追加 CRUD 函数
- [ ] `routes_handbook.py` 基础 CRUD + 上传 + parse
- [ ] `HandbookManager.vue` 上传 + 列表 UI
- [ ] **验收**：能上传 PPT/PDF/Word，能看到解析后的纯文本

### Sprint 2（结构提取 + 分类引擎 · 4 天）

- [ ] `handbook_extractor.py` LLM 抽取 1/3/3/5/9/10
- [ ] `HandbookManager.vue` 增加「结构校对」抽屉
- [ ] `handbook_classifier.py` 双轨分类（向量预筛 + LLM 精分类）
- [ ] `routes_analysis_report.py` 创建分析任务 + 进度查询
- [ ] **验收**：对已完成 batch 跑一次分析，能看到 turn_classifications 表有数据

### Sprint 3（报告前端 · 5 天）

- [ ] 板块 1：HACover.vue
- [ ] 板块 2：HAHighlights.vue
- [ ] 板块 3：HACoverageMatrix.vue + HACategoryDrawer.vue（最核心）
- [ ] 板块 4：HACustomerInsights.vue（含聚类）
- [ ] 板块 5：HADocumentAdvice.vue
- [ ] **验收**：完整可看的分析报告页面，能跳转到 session 详情

### Sprint 4（增强 + 导出 · 3 天）

- [ ] 板块 6：HACompliance.vue
- [ ] 板块 7：HATrend.vue
- [ ] 板块 9：导出 Markdown / PDF / JSON
- [ ] WebSocket 实时进度（可选，先用 5s 轮询）
- [ ] 性能优化：1800 turn 分类要 ≤ 5 分钟跑完（并发 + 缓存）
- [ ] **验收**：完整 E2E 演示

---

## 10. 与现有代码的复用清单

| 复用项 | 来源 | 用途 |
|-------|------|------|
| `parse_file()` | `src/rag/parsers.py` | Handbook 多格式文件解析 |
| `get_embedder()` | `src/rag/embedder.py` | 向量预筛 |
| `call_llm_json()` | `src/llm.py` | LLM 精分类 / 结构抽取 |
| `_load_bundle()` 思路 | `src/api/routes_batch_report.py` | 批量数据加载模式 |
| `connection_scope()` | `src/storage/db.py` | DB 连接管理 |
| `ElUpload` | element-plus | 上传 UI |
| `vue-echarts` | 现有依赖 | 图表渲染 |
| `PersonaAvatar` | `web/src/components/` | 客户头像 |
| `DmPageHeader` | `web/src/components/` | 页面标题栏 |

**无需引入任何新依赖**。

---

## 11. 安全 / 性能 / 边界

### 11.1 安全

- 上传文件大小限制：单文件 50MB（在 `routes_handbook.py` 校验）
- 文件类型白名单：与 `SUPPORTED_SUFFIXES` 一致（pptx/pdf/docx/md/txt/xlsx）
- 上传文件 UUID 重命名落盘，避免路径注入

### 11.2 性能

- 向量预筛降低 LLM 调用 token：单条 turn ≤ 2K tokens
- 批量分类用 `ThreadPoolExecutor`，并发 4-8（避免 LLM rate limit）
- `analysis_jobs.summary_json` 预聚合所有板块数据，前端无需多次查 turn_classifications
- 历史 batch 重复分析直接读 `summary_json`，不重跑

### 11.3 边界与降级

| 场景 | 处理 |
|------|------|
| Handbook 未上传任何文件 | 上传按钮高亮提示 |
| Handbook 已上传但结构未提取 | 分析任务创建时拒绝（提示先提取） |
| 销冠 turn 完全无产品内容 | 分类为 `other`，不消耗 LLM |
| 批次中无 sales turn | 分析任务直接 completed，summary 标记"无可分析数据" |
| LLM 调用失败 | 该 turn 标 `classification_failed`，整体不中断 |
| Handbook 结构 JSON 损坏 | 任务 fail，前端引导用户重新提取 |

---

## 12. 验收标准

### 12.1 功能验收

- [ ] 能上传 PPT/PDF/Word/Excel/Markdown/TXT 6 种格式并自动解析
- [ ] 能 LLM 抽取 1/3/3/5/9/10 结构并人工校对
- [ ] 能选择 batch + handbook 启动分析任务
- [ ] 能实时看到分析进度
- [ ] 9 大板块全部渲染，无空数据时显示 `ElEmpty`
- [ ] 每条原声能跳转到对应 session 详情
- [ ] 能导出 Markdown / JSON

### 12.2 数据正确性验收

- [ ] 多标签：人工挑 10 条 turn，验证至少 80% 的多标签结果合理
- [ ] 6 维评分：人工挑 20 条 turn，评分误差 ≤ 2 分
- [ ] 客户聚类：44 人设至少分成 4 个有意义的桶
- [ ] 文档改进建议 P0 项：至少 1 条经业务确认有价值

### 12.3 性能验收

- 120 场 batch（≈1800 sales turns）分析耗时 ≤ 5 分钟
- 报告页打开首屏 ≤ 2 秒（summary_json 已预聚合）
- 上传 50MB PDF 解析 ≤ 30 秒

---

## 13. 风险与待定项

| # | 风险/疑问 | 处理建议 |
|---|----------|---------|
| R1 | LLM 抽取 1/3/3/5/9/10 结构准确性 | 必须保留人工校对编辑器；后续可训练专用 prompt |
| R2 | 同一 turn 多标签的"主标签"如何定 | 用最高 confidence 那个；前端排序也按 confidence |
| R3 | 客户聚类算法选择 | 先用 LLM 直接给 cluster 标签（不跑 kmeans），后期可换 |
| R4 | "其他"类别占比过高怎么办 | 板块 6 合规度专门曝光，让业务方关注 |
| R5 | Handbook 多版本管理 | v1.0 用 `version_no` 字段标记，UI 暂只显示最新版 |
| R6 | 大量历史 batch 是否回填 | v1.0 不自动回填，用户手动选 batch 跑分析 |

---

## 14. 附录

### 14.1 涉及的现有文件（仅参考，不直接修改）

```
src/api/routes_batch_report.py     # _load_bundle 数据加载模式参考
src/api/routes_kb.py               # 上传 API 模式参考
src/rag/parsers.py                 # 文件解析
src/rag/embedder.py                # 向量
src/storage/models.py              # 在 ALL_SCHEMAS 追加
src/storage/db.py                  # 追加 CRUD
src/api/server.py                  # 注册新路由
web/src/router/index.ts            # 追加 2 个路由
web/src/layouts/AppShell.vue       # 追加 2 个侧栏项
```

### 14.2 新增文件清单

```
后端：
src/api/routes_handbook.py
src/api/routes_analysis_report.py
src/analyzers/__init__.py
src/analyzers/handbook_extractor.py
src/analyzers/handbook_classifier.py
src/analyzers/persona_clusterer.py
src/analyzers/document_advisor.py

前端：
web/src/api/handbook.ts
web/src/api/analysis_report.ts
web/src/views/scale/HandbookManager.vue
web/src/views/scale/AnalysisReport.vue
web/src/views/scale/components/HACover.vue
web/src/views/scale/components/HAHighlights.vue
web/src/views/scale/components/HACoverageMatrix.vue
web/src/views/scale/components/HACategoryDrawer.vue
web/src/views/scale/components/HACustomerInsights.vue
web/src/views/scale/components/HADocumentAdvice.vue
web/src/views/scale/components/HACompliance.vue
web/src/views/scale/components/HATrend.vue
web/src/views/scale/components/HASessionLink.vue

数据：
data/handbook_uploads/         # 上传文件存放目录
```

### 14.3 配置项（可选写入 .env）

```bash
# 分析器配置（可选，未来加）
HA_LLM_MODEL=deepseek-chat
HA_CLASSIFIER_TOPK=5
HA_CLASSIFIER_THRESHOLD=0.3
HA_CONCURRENT_WORKERS=4
HA_MAX_FILE_SIZE_MB=50
```

---

## 15. 变更记录

| 日期 | 版本 | 修改 | 作者 |
|------|------|------|------|
| 2026-05-27 | v1.0 draft | 首版完整设计 | AI Assistant |
