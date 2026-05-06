"""钉钉机器人通知行为，基于 ipush.Dingtalk。"""

from __future__ import annotations

from ipush import Dingtalk
from loguru import logger

from anotiflow.actions.notify_base import NotifyAction
from anotiflow.core.registry import register_action


@register_action("dingtalk")
class DingtalkNotify(NotifyAction):
    def __init__(
        self,
        token: str,
        secret: str = "",
        message_template: str = "",
        title: str = "",
    ) -> None:
        super().__init__(message_template=message_template)
        self.name = "dingtalk"
        self.title = title
        self._client = Dingtalk(token=token, secret=secret)

    def _send(self, message: str) -> None:
        logger.info(f"[dingtalk] sending: {message}")
        self._client.send(message, title=self.title)
