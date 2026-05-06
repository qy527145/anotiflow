"""TOML 配置加载：读取 → 装配 Task 列表。

配置示例（一个任务，多个触发器 + 多个行为）：

    [[tasks]]
    name = "daily_report"
    enabled = true

    # 触发器可以写成数组（任一命中都会触发任务），也可以写成单个 table
    [[tasks.triggers]]
    type = "interval"
    unit = "day"
    at = "09:30"

    [[tasks.triggers]]
    type = "event"
    event = "manual.fire"

    [[tasks.actions]]
    type = "custom"
    path = "examples.user_actions.check_stock"

    [[tasks.actions]]
    type = "feishu"
    token = "xxx"
    message_template = "..."

行为执行时收到的 context 字段:
    task_name        任务名
    trigger_name     触发来源名（如 "interval(every 5 seconds)" / "event(stock.high)"）
    trigger_type     "interval" / "event"
    trigger_payload  业务载荷（事件 payload；定时触发为空 dict {}）
    fired_at         触发时刻字符串 "YYYY-MM-DD HH:MM:SS"
"""

from __future__ import annotations

import importlib
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

# 触发器/行为子模块的 import 副作用会向注册表登记类型，必须先 import
import anotiflow.actions  # noqa: F401
import anotiflow.triggers  # noqa: F401
from anotiflow.actions.base import Action, CallableAction
from anotiflow.core.registry import get_action_class, get_trigger_class
from anotiflow.task import Task
from anotiflow.triggers.base import Trigger


def load_tasks(config_path: str | Path) -> list[Task]:
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    for extra in (os.getcwd(), str(path.parent)):
        if extra not in sys.path:
            sys.path.insert(0, extra)

    with path.open("rb") as f:
        data = tomllib.load(f)

    raw_tasks = data.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise ValueError("config: 'tasks' must be an array of tables ([[tasks]])")

    return [_build_task(raw, i) for i, raw in enumerate(raw_tasks)]


def _build_task(raw: dict[str, Any], idx: int) -> Task:
    name = raw.get("name") or f"task_{idx}"
    enabled = bool(raw.get("enabled", True))

    triggers = _build_triggers(raw, name)
    actions_cfg = raw.get("actions") or []
    if not isinstance(actions_cfg, list) or not actions_cfg:
        raise ValueError(f"task {name!r}: at least one [[tasks.actions]] is required")
    actions = [_build_action(dict(c), name, i) for i, c in enumerate(actions_cfg)]

    return Task(name=name, triggers=triggers, actions=actions, enabled=enabled)


def _build_triggers(raw: dict[str, Any], task_name: str) -> list[Trigger]:
    # 允许两种写法：triggers（数组）或 trigger（单个 table）
    triggers_cfg = raw.get("triggers")
    single = raw.get("trigger")
    if triggers_cfg is None and single is None:
        raise ValueError(f"task {task_name!r}: missing [[tasks.triggers]] or [tasks.trigger]")
    if triggers_cfg is not None and single is not None:
        raise ValueError(f"task {task_name!r}: use either [[tasks.triggers]] or [tasks.trigger], not both")

    if single is not None:
        return [_build_trigger(dict(single))]

    if not isinstance(triggers_cfg, list) or not triggers_cfg:
        raise ValueError(f"task {task_name!r}: 'triggers' must be a non-empty array of tables")
    return [_build_trigger(dict(c)) for c in triggers_cfg]


def _build_trigger(cfg: dict[str, Any]) -> Trigger:
    type_name = cfg.pop("type", None)
    if not type_name:
        raise ValueError("trigger: 'type' is required")
    cls = get_trigger_class(type_name)
    return cls(**cfg)


def _build_action(cfg: dict[str, Any], task_name: str, idx: int) -> Action:
    type_name = cfg.pop("type", None)
    if not type_name:
        raise ValueError(f"task {task_name!r} action#{idx}: 'type' is required")

    if type_name == "custom":
        return _build_custom_action(cfg, task_name, idx)

    cls = get_action_class(type_name)
    return cls(**cfg)


def _build_custom_action(cfg: dict[str, Any], task_name: str, idx: int) -> Action:
    dotted = cfg.pop("path", None)
    if not dotted:
        raise ValueError(f"task {task_name!r} action#{idx}: custom action requires 'path'")
    if cfg:
        raise ValueError(
            f"task {task_name!r} action#{idx}: custom action does not accept extra keys: {list(cfg)}"
        )
    fn = _import_dotted(dotted)
    if not callable(fn):
        raise TypeError(f"custom action {dotted!r} is not callable")
    return CallableAction(fn=fn, name=dotted)


def _import_dotted(dotted: str):
    if "." not in dotted:
        raise ValueError(f"invalid dotted path: {dotted!r}, expected 'module.path.func'")
    module_name, attr = dotted.rsplit(".", 1)
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attr)
    except AttributeError as e:
        raise AttributeError(f"{dotted!r}: '{attr}' not found in module {module_name!r}") from e
