"""FastAPI 应用入口。

Stage 1 仅暴露 /health；其他业务路由（providers / personas / sessions 等）
随各自 Stage 接入。

启动：
    uvicorn src.api.server:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

# Stage 15e Bugfix：Windows 控制台默认 GBK 编码，LLM 输出里只要含一个
# 非 GBK 字符（典型如德文 Ü / 西文 ñ / emoji），rich 的 console.print
# 就会抛 UnicodeEncodeError，并污染 sys.stdout 的状态，导致同进程后续
# 所有 console.print/console.rule 都崩——这是批量测试 9/10 失败的根因。
# 这里在 server 进程一启动就把 stdout/stderr 强制改为 utf-8 + replace 兜底。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# CRITICAL：必须在 import 任何业务模块（特别是 src.rag.embedder）之前 load .env。
# embedder/llm 等模块在 import 时会读取环境变量初始化默认值；如果 .env 还没加载，
# 会拿到 None → 走硬编码 fallback，导致 .env 里的配置完全失效（比如 RAG embedder
# 跑错模型，向量维度与历史 collection 不一致 → 全部查询 0 命中）。
from pathlib import Path as _Path  # noqa: E402

try:
    from dotenv import load_dotenv as _load_dotenv  # noqa: E402

    _PROJECT_ROOT = _Path(__file__).resolve().parent.parent.parent
    _ENV_FILE = _PROJECT_ROOT / ".env"
    if _ENV_FILE.exists():
        _load_dotenv(_ENV_FILE, override=False)
except Exception:  # noqa: BLE001
    pass

import os  # noqa: E402

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.auth import AuthMiddleware, router as auth_router
from src.api.routes_batch import router as batch_router
from src.api.routes_batch_report import router as batch_report_router
from src.api.routes_cases import router as cases_router
from src.api.routes_dashboard import router as dashboard_router
from src.api.routes_excellent_phrases import router as excellent_phrases_router
from src.api.routes_kb import router as kb_router
from src.api.routes_personas import router as personas_router
from src.api.routes_providers import router as providers_router
from src.api.routes_sessions import router as sessions_router
from src.api.routes_status import router as status_router
from src.api.routes_agent_skills import router as agent_skills_router
from src.api.routes_agent_profile import router as agent_profile_router
from src.api.routes_handbook import router as handbook_router
from src.api.routes_analysis import router as analysis_router
from src.api.routes_vector_admin import router as vector_admin_router
from src.api.ws_batch import router as ws_batch_router
from src.api.ws_session import router as ws_session_router
from src.cases.seed import seed_preset_cases_if_empty
from src.config import setup_logging
from src.persona.seed import seed_built_in_personas
from src.rag.seed import seed_default_kbs, start_indexer_thread
from src.storage.db import connection_scope, init_schema, list_pending_files
from src.storage.migrations import migrate_env_to_db


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子：启动时建 schema + 迁移 .env，关闭时无动作。"""
    log_file = setup_logging()
    logger.info("DealMind API starting · log_file=%s", log_file)

    with connection_scope() as conn:
        counts = init_schema(conn)
        logger.info("schema initialized · table_counts=%s", counts)

        if counts["llm_providers"] == 0:
            new_id = migrate_env_to_db(conn)
            if new_id:
                logger.info("migrated .env → llm_providers id=%d", new_id)
            else:
                logger.info(".env 无 OPENAI_API_KEY 或迁移条件未满足，跳过")

        if counts["personas"] == 0:
            seed_result = seed_built_in_personas(conn)
            logger.info("persona seed result: %s", seed_result)

        if counts["knowledge_bases"] == 0:
            kb_seed = seed_default_kbs(conn)
            logger.info("kb seed result: %s", kb_seed)

        # Stage 11：销售案例集 preset 预填（仅在 sales_cases 表为空时执行）
        try:
            case_inserted = seed_preset_cases_if_empty(conn)
            if case_inserted:
                logger.info("sales_cases preset 已导入 %d 条", case_inserted)
        except Exception as exc:  # noqa: BLE001
            logger.warning("preset cases seed 失败（跳过）: %s", exc)

        # 不论是否首启，只要有 pending/indexing 文件就启动后台索引线程
        pending = list_pending_files(conn)
        if pending:
            started = start_indexer_thread()
            logger.info("indexer thread requested · pending=%d started=%s",
                        len(pending), started)

    # 开机预加载 embedding 模型：把 500MB~1GB 的内存峰值挪到"启动时"（此刻整机最空），
    # 避免第一次有人跑会话/检索时才惰性加载，瞬间打满小内存机器导致整机卡死重启。
    # 可用 DM_PRELOAD_EMBEDDER=0 关闭（例如本地开发不想等模型加载）。
    if os.getenv("DM_PRELOAD_EMBEDDER", "1") == "1":
        try:
            from src.rag.embedder import get_embedder

            logger.info("preloading embedding model at startup ...")
            emb = get_embedder()
            emb.ensure_loaded()
            logger.info("embedding model preloaded · %s", emb.info())
        except Exception as exc:  # noqa: BLE001
            logger.warning("preload embedder failed (会后续惰性加载): %s", exc)

    yield
    logger.info("DealMind API stopping")


app = FastAPI(
    title="DealMind API",
    description="多人设销冠压力测试引擎后端",
    version="1.0.0",
    lifespan=lifespan,
)

# 鉴权中间件先加（内层）；CORS 后加（外层），保证 401 响应也带上 CORS 头，
# 否则浏览器在跨域场景会把 401 误报成 CORS 错误。
app.add_middleware(AuthMiddleware)

# 允许的前端来源：默认本地 dev；上线时可用 DM_CORS_ORIGINS 追加（逗号分隔）。
# 同源部署（Caddy 静态 + /api 同域）其实不触发 CORS，这里仅为保险。
_cors_origins = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]
_extra_origins = os.getenv("DM_CORS_ORIGINS", "")
_cors_origins += [o.strip() for o in _extra_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(providers_router)
app.include_router(personas_router)
app.include_router(kb_router)
app.include_router(vector_admin_router)
app.include_router(sessions_router)
app.include_router(ws_session_router)
app.include_router(dashboard_router)
app.include_router(batch_router)
app.include_router(batch_report_router)
app.include_router(ws_batch_router)
app.include_router(cases_router)
app.include_router(excellent_phrases_router)
app.include_router(status_router)
app.include_router(agent_skills_router)
app.include_router(agent_profile_router)
app.include_router(handbook_router)
app.include_router(analysis_router)


@app.get("/health")
def health() -> dict:
    """轻量健康检查；不查 DB，只确认进程在跑。"""
    return {
        "status": "ok",
        "service": "dealmind-api",
        "version": "1.0.0",
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
