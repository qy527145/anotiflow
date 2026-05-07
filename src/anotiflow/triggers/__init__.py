"""触发器模块：定时（间隔）+ 事件 + API 触发。"""

from anotiflow.triggers.base import Trigger
from anotiflow.triggers.interval import IntervalTrigger
from anotiflow.triggers.event import EventTrigger
from anotiflow.triggers.api import APITrigger

__all__ = ["Trigger", "IntervalTrigger", "EventTrigger", "APITrigger"]
