"""事件触发器：订阅 EventBus 上的指定事件名。"""

from __future__ import annotations

from loguru import logger

from anotiflow.core.event_bus import bus
from anotiflow.core.registry import register_trigger
from anotiflow.triggers.base import RunCallback, Trigger


@register_trigger("event")
class EventTrigger(Trigger):
    kind = "event"

    def __init__(self, event: str, **_extra) -> None:
        super().__init__()
        if not event:
            raise ValueError("event name is required")
        self.event = event
        self._handler = None

    def bind(self, task_name: str, callback: RunCallback) -> None:
        def _handler(payload: dict) -> None:
            self._record_fire(payload)
            logger.debug(f"[trigger] event {self.event!r} firing: task={task_name!r}")
            callback(self, payload)

        self._handler = _handler
        bus.subscribe(self.event, _handler)
        logger.debug(f"[trigger] bound event subscription: {self.event!r} for task={task_name!r}")

    def unbind(self) -> None:
        if self._handler is not None:
            bus.unsubscribe(self.event, self._handler)
            self._handler = None
