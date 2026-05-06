"""Task 数据类：N 个触发器 + N 个行为。

任意一个触发器命中 → 顺序执行所有行为。
config 字段保留 TOML 中该 [[tasks]] 段的原始 dict，模板可通过 {task.config[xxx]} 访问任意字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from anotiflow.actions.base import Action
from anotiflow.triggers.base import Trigger


@dataclass
class Task:
    name: str
    triggers: list[Trigger]
    actions: list[Action] = field(default_factory=list)
    enabled: bool = True
    config: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"<Task name={self.name!r} enabled={self.enabled} "
            f"triggers={[t.name for t in self.triggers]} "
            f"actions={[a.name for a in self.actions]}>"
        )
