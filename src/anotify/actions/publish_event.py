"""PublishEventAction：将事件广播到 EventBus。

可在 TOML 中直接使用，无需用户写 Python 代码即可串联事件链路。
payload 支持引用 context 中的字段（{trigger_payload[xx]} 等）。
"""

from __future__ import annotations

from loguru import logger

from anotify.actions.base import Action
from anotify.core.event_bus import bus
from anotify.core.registry import register_action


@register_action("publish_event")
class PublishEventAction(Action):
    def __init__(self, event: str, payload: dict | None = None) -> None:
        self.name = f"publish_event({event})"
        self.event = event
        self.payload = payload or {}

    def execute(self, context: dict) -> None:
        rendered = self._render_payload(context)
        logger.debug(f"[{self.name}] publishing payload={rendered}")
        bus.publish(self.event, rendered)

    def _render_payload(self, context: dict) -> dict:
        out: dict = {}
        for k, v in self.payload.items():
            if isinstance(v, str):
                try:
                    out[k] = v.format(**context)
                except (KeyError, IndexError):
                    out[k] = v
            else:
                out[k] = v
        return out
