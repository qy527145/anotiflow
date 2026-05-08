"""FastAPI 应用装配。

与 Engine / ConfigStore / TokenIndex / Broker / ApiTriggerHub 解耦，
所有依赖通过 build_app() 参数注入。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger

from anotiflow.core.api_trigger_hub import ApiTriggerHub
from anotiflow.core.config_store import ConfigStore
from anotiflow.core.remote_broker import RemoteBroker
from anotiflow.core.token_index import TokenIndex
from anotiflow.server.auth import make_admin_dependency
from anotiflow.server.routes_config import make_router as make_config_router
from anotiflow.server.routes_trigger_api import make_router as make_trigger_router
from anotiflow.server.ws_remote_action import make_router as make_ws_router

if TYPE_CHECKING:
    from anotiflow.core.engine import Engine

UI_DIR = Path(__file__).parent / "ui"


def build_app(
    *,
    config_store: ConfigStore,
    tokens: TokenIndex,
    api_hub: ApiTriggerHub,
    broker: RemoteBroker,
    engine: "Engine",
) -> FastAPI:
    app = FastAPI(title="anotiflow", version="0.3.0")

    # 生命周期：把 uvicorn 的事件循环挂到 broker 上
    @app.on_event("startup")
    async def _on_startup():
        broker.attach_loop(asyncio.get_running_loop())
        logger.info("broker attached to asyncio event loop")

    # admin 保护的路由组
    admin_dep = make_admin_dependency(tokens)
    admin_protected = [admin_dep]

    app.include_router(make_config_router(config_store), dependencies=admin_protected)

    # token-only 路由（不走 admin）
    app.include_router(make_trigger_router(api_hub, tokens))
    app.include_router(make_ws_router(broker, tokens))

    # UI 单文件：不鉴权（静态资源），由前端 JS 根据 cookie 自动跳 /login。
    # 这样浏览器输入根 URL 不会拿到裸 JSON 错误。
    @app.get("/", response_class=HTMLResponse)
    def index():
        return FileResponse(UI_DIR / "index.html")

    # 免鉴权的极简登录页
    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        return FileResponse(UI_DIR / "login.html")

    # health
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
