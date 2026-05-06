"""Trigger 顶层抽象基类。

callback 签名: callback(trigger_meta: dict, trigger_payload: dict) -> None

  trigger_meta    框架元信息（trigger_name, trigger_type, fired_at, ...）
  trigger_payload 业务载荷（事件 payload；定时触发为空 dict）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

RunCallback = Callable[[dict, dict], None]


class Trigger(ABC):
    name: str = ""

    @abstractmethod
    def bind(self, task_name: str, callback: RunCallback) -> None: ...

    @abstractmethod
    def unbind(self) -> None: ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
