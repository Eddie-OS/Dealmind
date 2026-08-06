"""最小化登录鉴权（单管理员账号）。

设计目标：上线到公网后，保护所有 /api/* 与 /ws/* 接口，避免任何人裸调
后端、消耗 LLM 额度或读写数据。

机制：
- 账号密码默认 admin / 789123，可用环境变量覆盖：
    DM_AUTH_USERNAME / DM_AUTH_PASSWORD
- 登录成功后返回一个 token（由账号密码确定性派生，无需服务端存储；
  改密码后旧 token 自动失效）。
- HTTP 请求带 `Authorization: Bearer <token>`；
  WebSocket 因浏览器无法设置 header，改用查询参数 `?token=<token>`。
- 中间件统一校验，OPTIONS 预检与 /health、/api/auth/login 放行。
"""

from __future__ import annotations

import hashlib
import os
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def _username() -> str:
    return os.getenv("DM_AUTH_USERNAME", "admin")


def _password() -> str:
    return os.getenv("DM_AUTH_PASSWORD", "789123")


def compute_token() -> str:
    """由账号密码确定性派生 token（改密码后旧 token 立即失效）。"""
    raw = f"{_username()}:{_password()}:dealmind-auth-v1"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 登录接口
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn) -> LoginOut:
    if body.username != _username() or body.password != _password():
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return LoginOut(token=compute_token())


# ---------------------------------------------------------------------------
# 鉴权中间件（纯 ASGI，能同时拦截 http 与 websocket）
# ---------------------------------------------------------------------------

# 完全放行（不需要 token）的精确路径
_PUBLIC_EXACT = {"/api/auth/login"}


def _is_protected(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return False
    return path.startswith("/api") or path.startswith("/ws")


def _extract_token(scope: Scope) -> str | None:
    # 1) HTTP：Authorization: Bearer <token>
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization")
    if auth:
        try:
            val = auth.decode("latin-1")
        except Exception:  # noqa: BLE001
            val = ""
        if val.lower().startswith("bearer "):
            return val[7:].strip()
    # 2) WebSocket / 兜底：查询参数 ?token=<token>
    qs = scope.get("query_string") or b""
    if qs:
        try:
            parsed = parse_qs(qs.decode("latin-1"))
        except Exception:  # noqa: BLE001
            parsed = {}
        vals = parsed.get("token")
        if vals:
            return vals[0]
    return None


class AuthMiddleware:
    """保护 /api/* 与 /ws/*；其余路径（/health、静态资源等）放行。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # CORS 预检请求放行（同源部署其实用不到，这里兜底，避免误拦）
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _is_protected(path):
            await self.app(scope, receive, send)
            return

        if _extract_token(scope) != compute_token():
            if scope["type"] == "websocket":
                # 握手阶段直接关闭（1008 = policy violation）
                await send({"type": "websocket.close", "code": 1008})
            else:
                resp = JSONResponse({"detail": "未授权，请先登录"}, status_code=401)
                await resp(scope, receive, send)
            return

        await self.app(scope, receive, send)
