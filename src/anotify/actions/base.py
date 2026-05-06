"""Action 顶层抽象基类 + 将用户自定义函数包装为 Action 的适配器。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class Action(ABC):
    """所有行为的顶层基类。子类必须实现 execute。"""

    name: str = ""

    @abstractmethod
    def execute(self, context: dict) -> None:
        """执行行为。

        context 至少包含:
          - task_name: 所属任务名
          - trigger_payload: 触发器传入的载荷（事件 payload 或定时任务的空 dict）
        """

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


class CallableAction(Action):
    """把用户自定义函数（dotted-path 加载）包装成 Action。

    函数签名约定: fn(context: dict) -> None
    """

    def __init__(self, fn: Callable[[dict], None], name: str = "") -> None:
        self._fn = fn
        self.name = name or getattr(fn, "__qualname__", repr(fn))

    def execute(self, context: dict) -> None:
        self._fn(context)
