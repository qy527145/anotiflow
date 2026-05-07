"""RemoteAction —— 远程自定义动作客户端 SDK。

使用：
    from anotiflow import RemoteAction

    action = RemoteAction("http://anotiflow-host:8765", token="act_xxx")

    @action.handler
    def handle(ctx):
        # ctx.task.name / ctx.task.config
        # ctx.trigger.name / ctx.trigger.kind / ctx.trigger.config
        # ctx.trigger.fired_at / ctx.trigger.payload
        return {"ok": True, "value": 42}   # 任意 JSON-friendly 返回值

    action.run()         # 阻塞，自动断线重连

也支持 async：
    async def main():
        await action.arun()

服务地址支持 http(s)://host:port 或 ws(s)://host:port，SDK 会自动转换为对应 ws 协议。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import traceback
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Optional, Union
from urllib.parse import urlparse, urlunparse

import websockets

logger = logging.getLogger("anotiflow.sdk")
if not logger.handlers:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [anotiflow.sdk] %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


Handler = Callable[[Any], Union[Any, Awaitable[Any]]]


def _to_ws_url(server_url: str, token: str, scope: str = "actions") -> str:
    """把 http://host:port 或 ws://host:port 标准化为 ws(s)://.../ws/{scope}/{token}"""
    p = urlparse(server_url)
    scheme = p.scheme.lower()
    if scheme in ("http", "ws"):
        scheme = "ws"
    elif scheme in ("https", "wss"):
        scheme = "wss"
    else:
        # 没有 scheme 时默认 ws
        scheme = "ws"
        if "://" not in server_url:
            p = urlparse("ws://" + server_url)
    path = f"/ws/{scope}/{token}"
    return urlunparse((scheme, p.netloc or p.path, path, "", "", ""))


class RemoteAction:
    def __init__(
        self,
        server_url: str,
        token: str,
        *,
        scope: str = "actions",
        reconnect_min: float = 1.0,
        reconnect_max: float = 30.0,
        ping_interval: float = 20.0,
    ) -> None:
        if not token:
            raise ValueError("RemoteAction: token is required")
        self.server_url = server_url
        self.token = token
        self.scope = scope
        self.reconnect_min = reconnect_min
        self.reconnect_max = reconnect_max
        self.ping_interval = ping_interval
        self._handler: Optional[Handler] = None
        self._ws_url = _to_ws_url(server_url, token, scope)
        self._stop = asyncio.Event() if False else None  # 在 arun 时创建
        self._thread: Optional[threading.Thread] = None

    def handler(self, fn: Handler) -> Handler:
        """注册 handler 装饰器。"""
        self._handler = fn
        return fn

    def set_handler(self, fn: Handler) -> None:
        self._handler = fn

    # ---- 同步入口 ----
    def run(self) -> None:
        """阻塞运行（适合脚本场景）。Ctrl+C 退出。"""
        try:
            asyncio.run(self.arun())
        except KeyboardInterrupt:
            logger.info("RemoteAction interrupted by user")

    def run_in_thread(self) -> threading.Thread:
        """后台线程运行（不阻塞）。返回线程对象。"""
        if self._thread and self._thread.is_alive():
            return self._thread
        self._thread = threading.Thread(target=self.run, name="anotiflow-remote-action", daemon=True)
        self._thread.start()
        return self._thread

    # ---- 异步入口 ----
    async def arun(self) -> None:
        if self._handler is None:
            raise RuntimeError("RemoteAction: handler not set; use @action.handler or set_handler()")
        backoff = self.reconnect_min
        while True:
            try:
                logger.info(f"connecting: {self._ws_url}")
                async with websockets.connect(self._ws_url, ping_interval=self.ping_interval) as ws:
                    logger.info("connected")
                    await ws.send(json.dumps({"op": "hello", "sdk": "anotiflow-py", "version": "0.3.0"}))
                    backoff = self.reconnect_min
                    await self._loop(ws)
            except (websockets.ConnectionClosed, OSError) as e:
                logger.warning(f"connection lost: {e}; reconnecting in {backoff:.1f}s")
            except Exception:
                logger.exception("unexpected error; reconnecting")
            await asyncio.sleep(backoff)
            backoff = min(self.reconnect_max, backoff * 2)

    async def _loop(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"received non-JSON frame, ignoring: {raw[:100]!r}")
                continue
            op = msg.get("op")
            if op == "invoke":
                asyncio.create_task(self._handle_invoke(ws, msg))
            elif op == "pong":
                pass
            elif op == "ping":
                await ws.send(json.dumps({"op": "pong"}))
            else:
                logger.warning(f"unknown op: {op}")

    async def _handle_invoke(self, ws, msg: dict) -> None:
        invocation_id = msg.get("invocation_id")
        envelope = msg.get("envelope") or {}
        ctx = self._build_ctx(envelope)
        try:
            result = self._handler(ctx)
            if asyncio.iscoroutine(result):
                result = await result
            reply = {"op": "result", "invocation_id": invocation_id, "ok": True, "value": result}
        except Exception as e:
            err = traceback.format_exc()
            logger.error(f"handler raised: {e}\n{err}")
            reply = {"op": "result", "invocation_id": invocation_id, "ok": False, "error": str(e)}
        try:
            await ws.send(json.dumps(reply, default=_json_default))
        except Exception:
            logger.exception("failed to send result back")

    @staticmethod
    def _build_ctx(envelope: dict) -> SimpleNamespace:
        """把 envelope 还原成与本地 CallableAction 同形的属性访问对象。"""
        task_d = envelope.get("task") or {}
        trig_d = envelope.get("trigger") or {}
        task = SimpleNamespace(
            name=task_d.get("name", ""),
            config=task_d.get("config") or {},
        )
        trigger = SimpleNamespace(
            name=trig_d.get("name", ""),
            kind=trig_d.get("kind", ""),
            config=trig_d.get("config") or {},
            fired_at=trig_d.get("fired_at", ""),
            payload=trig_d.get("payload") or {},
        )
        return SimpleNamespace(task=task, trigger=trigger, raw=envelope)


def _json_default(o: Any) -> Any:
    """fallback：把不可直接序列化的对象转成字符串。"""
    return repr(o)
