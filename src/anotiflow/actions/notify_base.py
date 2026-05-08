"""通知行为基类。所有 IM / 邮件 / 短信等通知子类都继承它。"""

from __future__ import annotations

from abc import abstractmethod

from loguru import logger

from anotiflow.actions.base import Action


class NotifyAction(Action):
    """通知行为统一抽象：渲染消息模板 → 调用具体渠道发送。

    message_template 使用 str.format 语法，可引用 context 里的键，例如:
        "股价: {trigger.payload[symbol]} = {trigger.payload[price]}"
    """

    def __init__(self, message_template: str = "") -> None:
        self.message_template = message_template

    def _render(self, context: dict) -> str:
        if self.message_template:
            try:
                return self.message_template.format(**context)
            except (KeyError, IndexError) as e:
                logger.warning(f"{self.name}: template render missing key: {e}, fallback to raw template")
                return self.message_template

        # 没填模板时的兜底：尽量给一段非空文本（钉钉等渠道会拒绝空 content）
        trigger = context.get("trigger")
        task = context.get("task")
        if trigger is not None:
            payload = getattr(trigger, "payload", None) or {}
            if payload:
                return str(payload)
            task_name = getattr(task, "name", "") if task is not None else ""
            return f"[{task_name or self.name}] fired at {getattr(trigger, 'fired_at', '')}".strip()
        return f"[{self.name}] fired"

    def execute(self, context: dict) -> None:
        message = self._render(context)
        self._send(message)

    @abstractmethod
    def _send(self, message: str) -> None:
        """具体渠道发送实现。子类覆盖。"""
