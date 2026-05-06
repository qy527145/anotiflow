"""触发器/行为类型注册表，使用装饰器登记。"""

from __future__ import annotations

from typing import TypeVar

_action_registry: dict[str, type] = {}
_trigger_registry: dict[str, type] = {}

T = TypeVar("T", bound=type)


def register_action(type_name: str):
    def decorator(cls: T) -> T:
        if type_name in _action_registry:
            raise ValueError(f"action type already registered: {type_name}")
        _action_registry[type_name] = cls
        return cls
    return decorator


def register_trigger(type_name: str):
    def decorator(cls: T) -> T:
        if type_name in _trigger_registry:
            raise ValueError(f"trigger type already registered: {type_name}")
        _trigger_registry[type_name] = cls
        return cls
    return decorator


def get_action_class(type_name: str) -> type:
    if type_name not in _action_registry:
        raise KeyError(f"unknown action type: {type_name}. registered: {list(_action_registry)}")
    return _action_registry[type_name]


def get_trigger_class(type_name: str) -> type:
    if type_name not in _trigger_registry:
        raise KeyError(f"unknown trigger type: {type_name}. registered: {list(_trigger_registry)}")
    return _trigger_registry[type_name]
