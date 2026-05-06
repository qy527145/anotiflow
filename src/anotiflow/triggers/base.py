"""Trigger 顶层抽象基类。

每个触发器实例对模板暴露两类信息：
  trigger.config[xxx]   — 原始 TOML 配置（任意字段），由 loader 注入
  trigger.fired_at      — 本次命中时刻（"YYYY-MM-DD HH:MM:SS"）
  trigger.payload[xxx]  — 业务载荷（事件 payload；定时触发为 {}）
  trigger.kind          — "interval" / "event" / 其它扩展类型

callback 签名: callback(trigger: Trigger, payload: dict) -> None
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable

RunCallback = Callable[["Trigger", dict], None]


class Trigger(ABC):
    """所有触发器的顶层基类。

    子类构造函数应当接受 **kwargs 形式吃掉所有未消费字段（保持配置开放，
    用户可在 TOML 里写任意字段，全部经 loader 进入 .config）。
    """

    kind: str = ""  # 子类填写，用于 trigger.kind 模板访问

    def __init__(self) -> None:
        # loader 在实例化后注入：
        self.config: dict = {}
        self.name: str = ""
        # 运行时元信息（由子类在每次命中时更新）：
        self.fired_at: str = ""
        self.payload: dict = {}

    @abstractmethod
    def bind(self, task_name: str, callback: RunCallback) -> None: ...

    @abstractmethod
    def unbind(self) -> None: ...

    def _record_fire(self, payload: dict | None) -> None:
        """子类在命中时调用，刷新 fired_at / payload。"""
        self.fired_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.payload = payload or {}

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
