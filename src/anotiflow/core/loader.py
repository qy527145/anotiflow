"""TOML 配置加载：读取 → 装配 Task 列表。

每个 [[tasks]] / [[tasks.triggers]] 段的原始 dict 会原样保留到 Task.config / Trigger.config，
模板可通过 {task.config[xxx]} / {trigger.config[xxx]} 访问任意字段（包括 type/every/unit
等内置字段以及用户自定义字段）。

行为执行时收到的 ctx：
    {task}     —— Task 实例
                  常用：{task.config[name]} {task.name} {task.config[xxx]}
    {trigger}  —— 命中的那个 Trigger 实例
                  常用：{trigger.config[name]} {trigger.config[xxx]}
                       {trigger.fired_at} {trigger.payload[xxx]} {trigger.kind}
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

    # 原始 dict 全量保留（深拷贝一份避免运行期被意外修改）
    task_config = _deep_copy_config(raw)
    task_config.setdefault("name", name)
    return Task(name=name, triggers=triggers, actions=actions, enabled=enabled, config=task_config)


def _build_triggers(raw: dict[str, Any], task_name: str) -> list[Trigger]:
    # 允许两种写法：triggers（数组）或 trigger（单个 table）
    triggers_cfg = raw.get("triggers")
    single = raw.get("trigger")
    if triggers_cfg is None and single is None:
        raise ValueError(f"task {task_name!r}: missing [[tasks.triggers]] or [tasks.trigger]")
    if triggers_cfg is not None and single is not None:
        raise ValueError(f"task {task_name!r}: use either [[tasks.triggers]] or [tasks.trigger], not both")

    if single is not None:
        return [_build_trigger(dict(single), task_name, 0)]

    if not isinstance(triggers_cfg, list) or not triggers_cfg:
        raise ValueError(f"task {task_name!r}: 'triggers' must be a non-empty array of tables")
    return [_build_trigger(dict(c), task_name, i) for i, c in enumerate(triggers_cfg)]


def _build_trigger(cfg: dict[str, Any], task_name: str, idx: int) -> Trigger:
    type_name = cfg.get("type")
    if not type_name:
        raise ValueError(f"task {task_name!r} trigger#{idx}: 'type' is required")
    cls = get_trigger_class(type_name)

    # 内置已知字段交给类型自身的 __init__ 校验；其余字段由 **_extra 吃掉，
    # 完整 dict 全量保留到 trigger.config，供模板访问。
    init_kwargs = {k: v for k, v in cfg.items() if k != "type"}
    instance = cls(**init_kwargs)

    raw_config = _deep_copy_config(cfg)
    # 若用户没显式给 trigger 写 name，自动派生一个
    raw_config.setdefault("name", f"{type_name}#{idx}")
    instance.config = raw_config
    instance.name = str(raw_config["name"])
    return instance


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


def _deep_copy_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """轻量深拷贝（TOML 解析结果只含 dict/list/标量）。"""
    return {k: _deep_copy_value(v) for k, v in cfg.items()}


def _deep_copy_value(v: Any) -> Any:
    if isinstance(v, dict):
        return _deep_copy_config(v)
    if isinstance(v, list):
        return [_deep_copy_value(x) for x in v]
    return v
