"""路由：API 触发。
POST /trigger/{token}  body 即 payload，转交给 ApiTriggerHub。
不走 admin auth，由 token 自身鉴权。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from anotiflow.core.api_trigger_hub import ApiTriggerHub
from anotiflow.core.token_registry import TokenRegistry


def make_router(hub: ApiTriggerHub, tokens: TokenRegistry) -> APIRouter:
    r = APIRouter(tags=["trigger"])

    @r.post("/trigger/{token}")
    def fire(token: str, payload: dict = Body(default={})):
        tok = tokens.verify(token, "trigger")
        if not tok:
            raise HTTPException(status_code=403, detail="invalid trigger token")
        if not hub.has(token):
            raise HTTPException(status_code=404, detail="trigger not bound (task may be disabled or removed)")
        ok = hub.fire(token, payload or {})
        if not ok:
            raise HTTPException(status_code=500, detail="fire failed")
        return {"ok": True, "fired_with_payload_keys": list((payload or {}).keys())}

    return r
