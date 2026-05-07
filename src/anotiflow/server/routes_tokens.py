"""路由：token 管理（admin 下）。"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Body, HTTPException

from anotiflow.core.token_registry import TokenRegistry


def make_router(tokens: TokenRegistry) -> APIRouter:
    r = APIRouter(prefix="/api/tokens", tags=["tokens"])

    @r.get("")
    def list_tokens(scope: Optional[Literal["admin", "action", "trigger"]] = None, include_revoked: bool = False):
        return [t.to_dict() for t in tokens.list_tokens(scope=scope, include_revoked=include_revoked)]

    @r.post("")
    def create_token(payload: dict = Body(...)):
        scope = payload.get("scope")
        if scope not in ("admin", "action", "trigger"):
            raise HTTPException(status_code=400, detail="scope must be admin|action|trigger")
        subject = payload.get("subject", "") or ""
        label = payload.get("label", "") or ""
        return tokens.issue(scope, subject, label=label).to_dict()

    @r.delete("/{token_id}")
    def revoke_token(token_id: str):
        if not tokens.revoke(token_id):
            raise HTTPException(status_code=404, detail="token not found")
        return {"ok": True}

    return r
