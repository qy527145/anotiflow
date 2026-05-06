"""触发器模块：定时（间隔）+ 事件，预留手动触发扩展点。"""

from anotiflow.triggers.base import Trigger
from anotiflow.triggers.interval import IntervalTrigger
from anotiflow.triggers.event import EventTrigger

__all__ = ["Trigger", "IntervalTrigger", "EventTrigger"]
