"""RemoteBroker —— 远程动作的派发中枢。

每个 action token 对应一个 channel：
  - 服务端收到任务触发后，Engine 侧 RemoteActionProxy.execute(ctx) 会调用 broker.dispatch()
  - dispatch 把 envelope 交给对应 token 的 asyncio.Queue；WS handler 从队列里取出推给客户端
  - 客户端回包 → broker.deliver_result() → 唤醒 pending future

注意：Engine 跑在同步线程（schedule 主循环），WS 跑在 asyncio 线程（uvicorn）。
故 broker 提供两个 API：
  - dispatch_sync(token, envelope, wait, timeout) —— 给 Engine 侧用，内部 run_coroutine_threadsafe
  - dispatch_async(token, envelope, wait, timeout) —— 给 asyncio 侧用

运行前必须 attach_loop(loop)，把 uvicorn 的 event loop 注入。
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger


@dataclass
class _Client:
    ws: Any  # fastapi.WebSocket
    ready: asyncio.Event
    alive: bool = True


@dataclass
class _Channel:
    # round-robin 分发给多个客户端
    clients: list[_Client] = field(default_factory=list)
    # 离线时的堆积队列
    pending_offline: deque = field(default_factory=deque)
    rr_cursor: int = 0


class RemoteBroker:
    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = defaultdict(_Channel)
        self._results: dict[str, asyncio.Future] = {}
        self._lock = threading.RLock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ---- 客户端连接管理（WS 侧调用）----
    async def register_client(self, token: str, ws) -> _Client:
        client = _Client(ws=ws, ready=asyncio.Event())
        client.ready.set()
        with self._lock:
            ch = self._channels[token]
            ch.clients.append(client)
            # 清空 offline 堆积：把队列中的 envelope 丢给新连接（尽力而为）
            offline = list(ch.pending_offline)
            ch.pending_offline.clear()
        for env in offline:
            try:
                await ws.send_json({"op": "invoke", **env})
            except Exception:
                logger.exception("failed to flush offline envelope")
        logger.info(f"remote action client connected: token={token} (now {len(self._channels[token].clients)} client(s))")
        return client

    async def unregister_client(self, token: str, client: _Client) -> None:
        with self._lock:
            ch = self._channels.get(token)
            if ch and client in ch.clients:
                ch.clients.remove(client)
        client.alive = False
        logger.info(f"remote action client disconnected: token={token}")

    def deliver_result(self, invocation_id: str, result: dict) -> None:
        """WS 收到 client 回包时调用。"""
        fut = self._results.pop(invocation_id, None)
        if fut and not fut.done():
            fut.get_loop().call_soon_threadsafe(fut.set_result, result)

    # ---- 派发（Engine 同步线程侧调用）----
    def dispatch_sync(
        self,
        token: str,
        envelope: dict,
        *,
        wait: bool = True,
        timeout: float = 30.0,
        offline_policy: str = "queue",
    ) -> Optional[dict]:
        if self._loop is None:
            raise RuntimeError("broker event loop not attached; call attach_loop() first")
        fut = asyncio.run_coroutine_threadsafe(
            self._dispatch_async(token, envelope, wait=wait, timeout=timeout, offline_policy=offline_policy),
            self._loop,
        )
        try:
            return fut.result(timeout=timeout + 5)
        except Exception:
            raise

    async def _dispatch_async(
        self,
        token: str,
        envelope: dict,
        *,
        wait: bool,
        timeout: float,
        offline_policy: str,
    ) -> Optional[dict]:
        invocation_id = uuid.uuid4().hex
        payload = {"invocation_id": invocation_id, "envelope": envelope}

        with self._lock:
            ch = self._channels[token]
            client: Optional[_Client] = None
            if ch.clients:
                idx = ch.rr_cursor % len(ch.clients)
                client = ch.clients[idx]
                ch.rr_cursor += 1

        if client is None:
            # 无在线客户端
            if offline_policy == "error":
                raise RuntimeError(f"no online remote handler for token={token}")
            if offline_policy == "drop":
                logger.warning(f"remote action dropped (no handler online): token={token}")
                return None
            # queue：堆积起来等下一次客户端上线
            with self._lock:
                self._channels[token].pending_offline.append(payload)
            logger.warning(f"remote action queued (no handler online): token={token}")
            return None

        # 在线：准备 future，推送 invoke
        if wait:
            loop = asyncio.get_event_loop()
            future: asyncio.Future = loop.create_future()
            self._results[invocation_id] = future

        try:
            await client.ws.send_json({"op": "invoke", **payload})
        except Exception:
            self._results.pop(invocation_id, None)
            logger.exception(f"failed to send invoke to remote client: token={token}")
            raise

        if not wait:
            return None

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._results.pop(invocation_id, None)
            raise TimeoutError(f"remote action timed out after {timeout}s (token={token})")


broker = RemoteBroker()
