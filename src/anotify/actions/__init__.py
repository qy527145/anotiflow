"""行为模块：顶层 Action 基类 + 通知基类 + 具体实现"""

from anotify.actions.base import Action, CallableAction
from anotify.actions.notify_base import NotifyAction
from anotify.actions.feishu import FeishuNotify
from anotify.actions.dingtalk import DingtalkNotify
from anotify.actions.publish_event import PublishEventAction

__all__ = [
    "Action",
    "CallableAction",
    "NotifyAction",
    "FeishuNotify",
    "DingtalkNotify",
    "PublishEventAction",
]
