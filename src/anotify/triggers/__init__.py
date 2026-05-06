"""触发器模块：定时（间隔）+ 事件，预留手动触发扩展点。"""

from anotify.triggers.base import Trigger
from anotify.triggers.interval import IntervalTrigger
from anotify.triggers.event import EventTrigger

__all__ = ["Trigger", "IntervalTrigger", "EventTrigger"]
