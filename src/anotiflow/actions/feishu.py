"""飞书机器人通知行为，基于 ipush.Feishu。"""

from __future__ import annotations

from ipush import Feishu
from loguru import logger

from anotiflow.actions.notify_base import NotifyAction
from anotiflow.core.registry import register_action


@register_action("feishu")
class FeishuNotify(NotifyAction):
    def __init__(self, token: str, secret: str = "", message_template: str = "") -> None:
        super().__init__(message_template=message_template)
        self.name = "feishu"
        self._client = Feishu(token=token, secret=secret)

    def _send(self, message: str) -> None:
        logger.info(f"[feishu] sending: {message}")
        self._client.send(message)
