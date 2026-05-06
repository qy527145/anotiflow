"""Task 数据类：N 个触发器 + N 个行为。

任意一个触发器满足 → 顺序执行所有行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from anotify.actions.base import Action
from anotify.triggers.base import Trigger


@dataclass
class Task:
    name: str
    triggers: list[Trigger]
    actions: list[Action] = field(default_factory=list)
    enabled: bool = True

    def __repr__(self) -> str:
        return (
            f"<Task name={self.name!r} enabled={self.enabled} "
            f"triggers={[t.name for t in self.triggers]} "
            f"actions={[a.name for a in self.actions]}>"
        )
