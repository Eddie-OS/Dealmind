"""SQLite 表 schema 定义（CREATE TABLE 字符串）。

设计原则：
1. 一次性建 8 张表（schema 占位），避免后续 ALTER 滚雪球；
2. 字段一律 NULLABLE（除主键、name 等强约束），让后续 Stage 渐进填充；
3. 时间戳统一 TEXT ISO8601，便于跨平台与日志对齐；
4. 复杂结构（pressure_profile / tags / metadata 等）一律 JSON 文本字段
   命名为 *_json，避免在 Stage 1 就锁死结构；
5. 外键打开（db.get_connection 里 PRAGMA foreign_keys=ON）。

9 张表对应阶段：
    llm_providers     → Stage 1（本阶段启用）
    personas          → Stage 3
    knowledge_bases   → Stage 6
    knowledge_files   → Stage 6
    sessions          → Stage 4
    turns             → Stage 4
    evaluations       → Stage 4
    sales_cases       → Stage 11
    batch_jobs        → Stage 9
    agent_skills_config → Stage 14
    agent_profiles / agent_profile_versions → Stage 15a（销冠 Agent 配置中心）
"""

from __future__ import annotations


SCHEMA_LLM_PROVIDERS = """
CREATE TABLE IF NOT EXISTS llm_providers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL UNIQUE,
    provider_type       TEXT    NOT NULL,
    base_url            TEXT    NOT NULL,
    api_key             TEXT    NOT NULL,
    model_name          TEXT    NOT NULL,
    temperature         REAL    NOT NULL DEFAULT 0.7,
    max_retries         INTEGER NOT NULL DEFAULT 2,
    is_active           INTEGER NOT NULL DEFAULT 1,
    is_default          INTEGER NOT NULL DEFAULT 0,
    extra_config_json   TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
"""

SCHEMA_PERSONAS = """
CREATE TABLE IF NOT EXISTS personas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL,
    format_type         TEXT    NOT NULL CHECK (format_type IN ('prompt_based', 'structured')),
    profile_json        TEXT,
    pressure_json       TEXT,
    prompt_text         TEXT,
    source              TEXT,
    tags_json           TEXT,
    locale              TEXT    DEFAULT 'zh-CN',
    original_data_json  TEXT,
    pressure_extracted  INTEGER NOT NULL DEFAULT 0,
    avatar_key          TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
"""

SCHEMA_KNOWLEDGE_BASES = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    kb_type     TEXT    NOT NULL CHECK (kb_type IN ('product', 'enterprise', 'experience')),
    description TEXT,
    file_count  INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
"""

SCHEMA_KNOWLEDGE_FILES = """
CREATE TABLE IF NOT EXISTS knowledge_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kb_id       INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename    TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,
    file_type   TEXT,
    file_size   INTEGER,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'pending',
    error_msg   TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
"""

SCHEMA_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT    PRIMARY KEY,
    persona_id          INTEGER REFERENCES personas(id) ON DELETE SET NULL,
    product_kb_id       INTEGER REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    enterprise_kb_id    INTEGER REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    handbook_id         INTEGER REFERENCES product_handbooks(id) ON DELETE SET NULL,
    provider_id         INTEGER REFERENCES llm_providers(id) ON DELETE SET NULL,
    topic               TEXT,
    opening_line        TEXT,
    max_rounds          INTEGER NOT NULL DEFAULT 50,
    status              TEXT    NOT NULL DEFAULT 'pending',
    config_json         TEXT,
    summary_json        TEXT,
    started_at          TEXT,
    ended_at            TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
"""

SCHEMA_TURNS = """
CREATE TABLE IF NOT EXISTS turns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    idx          INTEGER NOT NULL,
    role         TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    stage        TEXT,
    metadata_json TEXT,
    created_at   TEXT    NOT NULL,
    UNIQUE (session_id, idx, role)
);
"""

SCHEMA_EVALUATIONS = """
CREATE TABLE IF NOT EXISTS evaluations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_idx       INTEGER,
    evaluator_role TEXT    NOT NULL CHECK (evaluator_role IN ('judge', 'coach')),
    score_json     TEXT,
    feedback_json  TEXT,
    created_at     TEXT    NOT NULL
);
"""

# Stage 11：销售案例集。三轨自动入库 + 训练文件预填。
#   source: judge_auto    → session 整场质量 >= 8.0 自动沉淀
#           coach_auto    → Coach.what_worked 单条策略
#           manual        → 会话详情页人工收藏
#           preset        → startup 时从训练文件 .pptx 预填
#   dialogue_excerpt_json: list[{idx, role, content, stage}]，可空（preset / 整场 case）
#   raw_content:           整段文本（preset 用，便于全文搜索）
#   why_excellent:         为什么是好案例（coach_auto 来自 why_effective，manual 由用户写）
#   file_source:           preset 来源文件名
SCHEMA_SALES_CASES = """
CREATE TABLE IF NOT EXISTS sales_cases (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id            TEXT    REFERENCES sessions(id) ON DELETE SET NULL,
    source                TEXT    NOT NULL CHECK (source IN ('judge_auto', 'coach_auto', 'manual', 'preset')),
    title                 TEXT    NOT NULL,
    scene                 TEXT,
    persona_id            INTEGER REFERENCES personas(id) ON DELETE SET NULL,
    persona_tags_json     TEXT,
    dialogue_excerpt_json TEXT,
    raw_content           TEXT,
    why_excellent         TEXT,
    tags_json             TEXT,
    votes                 INTEGER NOT NULL DEFAULT 0,
    file_source           TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL
);
"""

# 优秀话术库：从分析报告的「优秀话术原声」（excellent_by_group）沉淀的**单条**优秀话术，
#   供「优秀话术库」页面浏览，并供销冠 Agent 在新会话中检索学习（search_excellent_phrases 工具）。
#   与 sales_cases（整段案例）区分：这里是细粒度、可直接复用的金句。
#   group_key: intro/sell/comp/param/faq/demo/off_handbook
#   source:    analysis_auto（分析自动沉淀）/ manual（人工收藏）
#   UNIQUE(session_id, turn_idx, handbook_label) 去重，重复分析同一会话只更新分值。
SCHEMA_EXCELLENT_PHRASES = """
CREATE TABLE IF NOT EXISTS excellent_phrases (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_job_id        INTEGER REFERENCES analysis_jobs(id) ON DELETE SET NULL,
    session_id             TEXT,
    handbook_id            INTEGER,
    turn_idx               INTEGER,
    group_key              TEXT,
    handbook_label         TEXT,
    persona_name           TEXT,
    customer_question      TEXT,
    sales_content          TEXT    NOT NULL,
    excellence_score       REAL    NOT NULL DEFAULT 0,
    purchase_signal_before REAL,
    purchase_signal_after  REAL,
    is_off_handbook        INTEGER NOT NULL DEFAULT 0,
    why_good_json          TEXT    NOT NULL DEFAULT '[]',
    source                 TEXT    NOT NULL DEFAULT 'analysis_auto',
    created_at             TEXT    NOT NULL,
    updated_at             TEXT    NOT NULL,
    UNIQUE(session_id, turn_idx, handbook_label)
);
"""

# Stage 9：批量测试
#   - persona_ids_json: 选定参与的 persona id 数组（决定 total_count）
#   - session_ids_json: 已生成的 session_id 数组（顺序与 persona_ids 对齐）
#   - status: pending / running / completed / cancelled / failed
#   - summary_json: 全部跑完后写聚合（成交/流失/超时/异常分布等），由 Stage 10 报告页读
SCHEMA_BATCH_JOBS = """
CREATE TABLE IF NOT EXISTS batch_jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    persona_ids_json  TEXT    NOT NULL,
    product_kb_id     INTEGER REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    enterprise_kb_id  INTEGER REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    handbook_id       INTEGER REFERENCES product_handbooks(id) ON DELETE SET NULL,
    provider_id       INTEGER REFERENCES llm_providers(id) ON DELETE SET NULL,
    topic             TEXT,
    opening_line      TEXT,
    max_rounds        INTEGER NOT NULL DEFAULT 30,
    judge_interval    INTEGER NOT NULL DEFAULT 3,
    memory_interval   INTEGER NOT NULL DEFAULT 3,
    total_count       INTEGER NOT NULL DEFAULT 0,
    completed_count   INTEGER NOT NULL DEFAULT 0,
    failed_count      INTEGER NOT NULL DEFAULT 0,
    cancelled_count   INTEGER NOT NULL DEFAULT 0,
    current_index     INTEGER NOT NULL DEFAULT 0,
    current_session_id TEXT,
    session_ids_json  TEXT,
    status            TEXT    NOT NULL DEFAULT 'pending',
    config_json       TEXT,
    summary_json      TEXT,
    error_msg         TEXT,
    started_at        TEXT,
    ended_at          TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);
"""


SCHEMA_AGENT_PROFILES = """
CREATE TABLE IF NOT EXISTS agent_profiles (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        TEXT    NOT NULL UNIQUE,
    role_description            TEXT    NOT NULL DEFAULT '',
    system_prompt               TEXT    NOT NULL DEFAULT '',
    opening_lines_json          TEXT    NOT NULL DEFAULT '[]',
    default_session_params_json TEXT    NOT NULL DEFAULT '{}',
    model_override_json         TEXT    NOT NULL DEFAULT '{}',
    extra_json                  TEXT    NOT NULL DEFAULT '{}',
    created_at                  TEXT    NOT NULL,
    updated_at                  TEXT    NOT NULL
);
"""


SCHEMA_AGENT_PROFILE_VERSIONS = """
CREATE TABLE IF NOT EXISTS agent_profile_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id    INTEGER NOT NULL REFERENCES agent_profiles(id) ON DELETE CASCADE,
    version_no    INTEGER NOT NULL,
    snapshot_json TEXT    NOT NULL,
    comment       TEXT,
    created_at    TEXT    NOT NULL,
    UNIQUE (profile_id, version_no)
);
"""


SCHEMA_AGENT_SKILLS_CONFIG = """
CREATE TABLE IF NOT EXISTS agent_skills_config (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    enabled_tools_json    TEXT    NOT NULL DEFAULT '[]',
    max_tool_loops        INTEGER NOT NULL DEFAULT 3,
    tool_top_k_default    INTEGER NOT NULL DEFAULT 3,
    web_search_provider   TEXT    NOT NULL DEFAULT 'tavily',
    web_search_api_key    TEXT    NOT NULL DEFAULT '',
    mcp_servers_json      TEXT    NOT NULL DEFAULT '[]',
    extra_config_json     TEXT    NOT NULL DEFAULT '{}',
    updated_at            TEXT    NOT NULL
);
"""


# ============================================================
# Handbook Analysis（HA）模块 · 5 张表
# 设计文档：docs/handbook_analysis_dev_spec.md §3.1
# ============================================================

# 产品手册主表：一个 handbook 对应一份 1/3/3/5/9/10 结构化文本。
#   status: draft / extracting / ready / failed
#   structure_json: 完整 1/3/3/5/9/10 JSON（schema 见开发文档）
SCHEMA_PRODUCT_HANDBOOKS = """
CREATE TABLE IF NOT EXISTS product_handbooks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL UNIQUE,
    product_kb_id     INTEGER REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    description       TEXT,
    structure_json    TEXT    NOT NULL DEFAULT '{}',
    source_files_json TEXT    NOT NULL DEFAULT '[]',
    status            TEXT    NOT NULL DEFAULT 'draft',
    extraction_log    TEXT,
    version_no        INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);
"""

# Handbook 来源文件：复用 parsers.parse_file()，parsed_text ≤500KB 直接存表
SCHEMA_HANDBOOK_FILES = """
CREATE TABLE IF NOT EXISTS handbook_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    handbook_id  INTEGER NOT NULL REFERENCES product_handbooks(id) ON DELETE CASCADE,
    filename     TEXT    NOT NULL,
    file_path    TEXT    NOT NULL,
    file_type    TEXT,
    file_size    INTEGER,
    parsed_text  TEXT,
    status       TEXT    NOT NULL DEFAULT 'pending',
    error_msg    TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
"""

# 分析任务：可对 batch 或单个 session 跑一次分类聚合
# v2 设计：
#   batch_id / session_id 二选一（互斥），handbook_id 改 nullable（创建时从源头反查 / 套默认）
SCHEMA_ANALYSIS_JOBS = """
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id         INTEGER REFERENCES batch_jobs(id) ON DELETE CASCADE,
    session_id       TEXT    REFERENCES sessions(id) ON DELETE CASCADE,
    handbook_id      INTEGER REFERENCES product_handbooks(id) ON DELETE SET NULL,
    status           TEXT    NOT NULL DEFAULT 'pending',
    progress         REAL    NOT NULL DEFAULT 0.0,
    total_turns      INTEGER NOT NULL DEFAULT 0,
    classified_turns INTEGER NOT NULL DEFAULT 0,
    summary_json     TEXT,
    error_msg        TEXT,
    started_at       TEXT,
    ended_at         TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    CHECK ((batch_id IS NOT NULL) OR (session_id IS NOT NULL))
);
"""

# 每条 turn 的分类结果：多标签写多行（同一 turn 可有多 category_id）
SCHEMA_TURN_CLASSIFICATIONS = """
CREATE TABLE IF NOT EXISTS turn_classifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_job_id INTEGER NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    session_id      TEXT    NOT NULL,
    turn_idx        INTEGER NOT NULL,
    category_id     TEXT    NOT NULL,
    confidence      REAL    NOT NULL DEFAULT 0.0,
    scores_json     TEXT    NOT NULL DEFAULT '{}',
    issues_json     TEXT    NOT NULL DEFAULT '[]',
    suggestion      TEXT    NOT NULL DEFAULT '',
    reference_text  TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL
);
"""

# 客户洞察缓存：聚类 + Top concerns，避免每次报告页都跑聚类
SCHEMA_ANALYSIS_PERSONA_INSIGHTS = """
CREATE TABLE IF NOT EXISTS analysis_persona_insights (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_job_id        INTEGER NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    persona_id             INTEGER REFERENCES personas(id) ON DELETE SET NULL,
    persona_cluster        TEXT,
    top_concerns_json      TEXT    NOT NULL DEFAULT '[]',
    sample_objections_json TEXT    NOT NULL DEFAULT '[]',
    deal_rate              REAL,
    avg_quality            REAL,
    created_at             TEXT    NOT NULL
);
"""


# 市场事实表缓存（② 深度研究节点）：按 handbook(产品) × country_code 缓存一份
#   研究产出（本品/竞品当地报价 + 促销分期 + 政策法规 + 本地化卖点）。
#   facts_json: MarketFactSheet 结构化 JSON；sources_json: 取证 URL 列表。
SCHEMA_MARKET_FACTS = """
CREATE TABLE IF NOT EXISTS market_facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    handbook_id   INTEGER REFERENCES product_handbooks(id) ON DELETE CASCADE,
    country_code  TEXT    NOT NULL,
    product_name  TEXT    NOT NULL DEFAULT '',
    facts_json    TEXT    NOT NULL DEFAULT '{}',
    sources_json  TEXT    NOT NULL DEFAULT '[]',
    model         TEXT,
    researched_at TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    UNIQUE(handbook_id, country_code)
);
"""


# 品牌人格表（③ 手册解耦）：把「产品无关的华为零售店身份 + 竞品 deny-list + 兜底话术」
#   抽成一张表（默认 1 行=华为），所有产品手册共用 —— 实现 销冠人格 ⊥ 产品知识。
#   identity_block: 直接注入 sales_prompt 的「销售身份与店铺范围」全文（产品无关）。
SCHEMA_BRAND_PROFILES = """
CREATE TABLE IF NOT EXISTS brand_profiles (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    NOT NULL UNIQUE,
    is_default           INTEGER NOT NULL DEFAULT 0,
    identity_block       TEXT    NOT NULL DEFAULT '',
    competitor_deny_json TEXT    NOT NULL DEFAULT '[]',
    notes                TEXT,
    created_at           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL
);
"""


ALL_SCHEMAS: list[tuple[str, str]] = [
    ("llm_providers", SCHEMA_LLM_PROVIDERS),
    ("personas", SCHEMA_PERSONAS),
    ("knowledge_bases", SCHEMA_KNOWLEDGE_BASES),
    ("knowledge_files", SCHEMA_KNOWLEDGE_FILES),
    ("sessions", SCHEMA_SESSIONS),
    ("turns", SCHEMA_TURNS),
    ("evaluations", SCHEMA_EVALUATIONS),
    ("sales_cases", SCHEMA_SALES_CASES),
    ("batch_jobs", SCHEMA_BATCH_JOBS),
    ("agent_skills_config", SCHEMA_AGENT_SKILLS_CONFIG),
    ("agent_profiles", SCHEMA_AGENT_PROFILES),
    ("agent_profile_versions", SCHEMA_AGENT_PROFILE_VERSIONS),
    # Handbook Analysis（HA）模块
    ("product_handbooks", SCHEMA_PRODUCT_HANDBOOKS),
    ("handbook_files", SCHEMA_HANDBOOK_FILES),
    ("analysis_jobs", SCHEMA_ANALYSIS_JOBS),
    ("turn_classifications", SCHEMA_TURN_CLASSIFICATIONS),
    ("analysis_persona_insights", SCHEMA_ANALYSIS_PERSONA_INSIGHTS),
    ("market_facts", SCHEMA_MARKET_FACTS),
    ("brand_profiles", SCHEMA_BRAND_PROFILES),
    ("excellent_phrases", SCHEMA_EXCELLENT_PHRASES),
]


SCHEMA_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_personas_format_type ON personas(format_type);",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_files_kb_id ON knowledge_files(kb_id);",
    "CREATE INDEX IF NOT EXISTS idx_turns_session_id ON turns(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_evaluations_session_id ON evaluations(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_sales_cases_source ON sales_cases(source);",
    "CREATE INDEX IF NOT EXISTS idx_sales_cases_persona_id ON sales_cases(persona_id);",
    "CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_jobs(status);",
    "CREATE INDEX IF NOT EXISTS idx_agent_profile_versions_profile_id "
    "ON agent_profile_versions(profile_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_providers_default "
    "ON llm_providers(is_default) WHERE is_default = 1;",
    # Handbook Analysis 模块索引
    "CREATE INDEX IF NOT EXISTS idx_handbook_files_handbook_id "
    "ON handbook_files(handbook_id);",
    "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_batch_id "
    "ON analysis_jobs(batch_id);",
    "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_session_id "
    "ON analysis_jobs(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_handbook_id "
    "ON analysis_jobs(handbook_id);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_handbook_id "
    "ON sessions(handbook_id);",
    "CREATE INDEX IF NOT EXISTS idx_batch_jobs_handbook_id "
    "ON batch_jobs(handbook_id);",
    "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_status "
    "ON analysis_jobs(status);",
    "CREATE INDEX IF NOT EXISTS idx_turn_cls_job "
    "ON turn_classifications(analysis_job_id);",
    "CREATE INDEX IF NOT EXISTS idx_turn_cls_job_category "
    "ON turn_classifications(analysis_job_id, category_id);",
    "CREATE INDEX IF NOT EXISTS idx_turn_cls_session_turn "
    "ON turn_classifications(session_id, turn_idx);",
    "CREATE INDEX IF NOT EXISTS idx_ha_persona_insights_job "
    "ON analysis_persona_insights(analysis_job_id);",
    "CREATE INDEX IF NOT EXISTS idx_excellent_phrases_group "
    "ON excellent_phrases(group_key);",
    "CREATE INDEX IF NOT EXISTS idx_excellent_phrases_score "
    "ON excellent_phrases(excellence_score DESC);",
]
