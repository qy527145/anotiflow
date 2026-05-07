"""ApiTriggerHub —— API 触发器的注册中心。

把 APITrigger 实例按 token 索引；HTTP 路由收到 POST /trigger/{token} 后
查到对应 trigger，调用其 _record_fire(payload) + 触发 callback。
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from loguru import logger

FireCallback = Callable[[dict], None]


class ApiTriggerHub:
    def __init__(self) -> None:
        self._registry: dict[str, tuple[object, FireCallback]] = {}
        self._lock = threading.RLock()

    def register(self, token: str, trigger: object, fire: FireCallback) -> None:
        if not token:
            raise ValueError("api trigger requires token")
        with self._lock:
            if token in self._registry:
                logger.warning(f"api trigger token already registered, replacing: {token}")
            self._registry[token] = (trigger, fire)

    def unregister(self, token: str) -> None:
        with self._lock:
            self._registry.pop(token, None)

    def fire(self, token: str, payload: dict) -> bool:
        """返回 True 表示有任务被触发；False 表示 token 未注册。"""
        with self._lock:
            entry = self._registry.get(token)
        if not entry:
            return False
        trigger, fire_cb = entry
        try:
            fire_cb(payload or {})
            return True
        except Exception:
            logger.exception(f"api trigger fire failed: token={token}")
            return False

    def has(self, token: str) -> bool:
        with self._lock:
            return token in self._registry


# 全局单例：trigger 在 bind 时拿到它，HTTP 路由也拿到它
hub = ApiTriggerHub()
