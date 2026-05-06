"""行为模块：顶层 Action 基类 + 通知基类 + 具体实现"""

from anotiflow.actions.base import Action, CallableAction
from anotiflow.actions.notify_base import NotifyAction
from anotiflow.actions.feishu import FeishuNotify
from anotiflow.actions.dingtalk import DingtalkNotify
from anotiflow.actions.publish_event import PublishEventAction

__all__ = [
    "Action",
    "CallableAction",
    "NotifyAction",
    "FeishuNotify",
    "DingtalkNotify",
    "PublishEventAction",
]
