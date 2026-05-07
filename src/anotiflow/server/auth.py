"""admin 鉴权：UI / /api/** 都需要 admin token。
/trigger/** 和 /ws/** 走各自的 token，绕过 admin。
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from anotiflow.core.token_registry import TokenRegistry


def _extract_admin_token(req: Request) -> str | None:
    # 1. Authorization: Bearer xxx
    auth = req.headers.get("authorization") or req.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # 2. X-Admin-Token header
    h = req.headers.get("x-admin-token") or req.headers.get("X-Admin-Token")
    if h:
        return h.strip()
    # 3. query param
    q = req.query_params.get("admin_token")
    if q:
        return q.strip()
    # 4. cookie
    c = req.cookies.get("admin_token")
    if c:
        return c.strip()
    return None


def make_admin_guard(tokens: TokenRegistry):
    def _guard(req: Request) -> None:
        tid = _extract_admin_token(req)
        if not tid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin token required")
        tok = tokens.verify(tid, "admin")
        if not tok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid admin token")

    return _guard


def make_admin_dependency(tokens: TokenRegistry):
    """FastAPI 依赖项：用于 router 级或路由级 dependencies=[Depends(...)]。"""
    guard = make_admin_guard(tokens)

    def _dep(req: Request) -> None:
        guard(req)

    return Depends(_dep)
