"""进程内事件总线，线程安全。"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Callable

from loguru import logger

EventHandler = Callable[[dict], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        with self._lock:
            self._subs[event_name].append(handler)
        logger.debug(f"event subscribed: {event_name} -> {handler!r}")

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        with self._lock:
            handlers = self._subs.get(event_name, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish(self, event_name: str, payload: dict | None = None) -> None:
        payload = payload or {}
        with self._lock:
            handlers = list(self._subs.get(event_name, []))
        logger.info(f"event published: {event_name} payload={payload} -> {len(handlers)} subscriber(s)")
        for h in handlers:
            try:
                h(payload)
            except Exception:
                logger.exception(f"event handler failed for {event_name}")


bus = EventBus()
