"""通知行为基类。所有 IM / 邮件 / 短信等通知子类都继承它。"""

from __future__ import annotations

from abc import abstractmethod

from loguru import logger

from anotify.actions.base import Action


class NotifyAction(Action):
    """通知行为统一抽象：渲染消息模板 → 调用具体渠道发送。

    message_template 使用 str.format 语法，可引用 context 里的键，例如:
        "股价: {trigger_payload[symbol]} = {trigger_payload[price]}"
    """

    def __init__(self, message_template: str = "") -> None:
        self.message_template = message_template

    def _render(self, context: dict) -> str:
        if not self.message_template:
            return str(context.get("trigger_payload", ""))
        try:
            return self.message_template.format(**context)
        except (KeyError, IndexError) as e:
            logger.warning(f"{self.name}: template render missing key: {e}, fallback to raw template")
            return self.message_template

    def execute(self, context: dict) -> None:
        message = self._render(context)
        self._send(message)

    @abstractmethod
    def _send(self, message: str) -> None:
        """具体渠道发送实现。子类覆盖。"""
