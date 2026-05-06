"""基于 schedule 库的定时触发器，保持 schedule 原生 API 的灵活性。

支持的字段（全部可选，按需组合）:

  every:    int 或省略    - 间隔次数；省略时等价于 schedule.every()（每"1单位"）
  unit:     str           - 时间单位，支持单复数：
                            second/seconds, minute/minutes, hour/hours,
                            day/days, week/weeks,
                            以及具体星期：monday, tuesday, ..., sunday
  to:       int           - 配合 every 形成随机区间 [every, to]，对应 schedule.every(N).to(M)
  at:       str           - 精确时刻，例如 "10:30" / "10:30:42" / ":23"，对应 .at("HH:MM[:SS]")
  until:    str           - 截止时刻，例如 "18:30" / "2026-12-31 23:59"，对应 .until(...)

示例：
  ┌ 每 5 秒                                  → every=5, unit="seconds"
  ├ 每 5~10 秒随机                           → every=5, to=10, unit="seconds"
  ├ 每天 09:30                               → unit="day", at="09:30"
  ├ 每周一 13:15                             → unit="monday", at="13:15"
  ├ 每分钟的第 23 秒                          → unit="minute", at=":23"
  └ 每小时一次直到 18:30                      → unit="hour", until="18:30"
"""

from __future__ import annotations

import schedule
from loguru import logger

from anotiflow.core.registry import register_trigger
from anotiflow.triggers.base import RunCallback, Trigger

_SINGULAR_UNITS = {"second", "minute", "hour", "day", "week"}
_PLURAL_UNITS = {"seconds", "minutes", "hours", "days", "weeks"}
_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_VALID_UNITS = _SINGULAR_UNITS | _PLURAL_UNITS | _WEEKDAYS


@register_trigger("interval")
class IntervalTrigger(Trigger):
    def __init__(
        self,
        unit: str,
        every: int | None = None,
        to: int | None = None,
        at: str | None = None,
        until: str | None = None,
    ) -> None:
        if unit not in _VALID_UNITS:
            raise ValueError(
                f"invalid unit {unit!r}. valid: seconds/minutes/hours/days/weeks "
                f"(singular forms ok), or weekday names (monday..sunday)"
            )
        if every is not None and every < 1:
            raise ValueError(f"'every' must be >= 1, got {every}")
        if to is not None and (every is None or to < every):
            raise ValueError(f"'to' requires 'every' and must be >= every; got every={every}, to={to}")
        if unit in _WEEKDAYS and (every is not None or to is not None):
            # schedule 不允许 every(N).monday，weekday 只能配 .at/.until
            raise ValueError(f"weekday unit {unit!r} cannot be combined with 'every'/'to'")

        self.unit = unit
        self.every = every
        self.to = to
        self.at = at
        self.until = until
        self.name = self._make_name()
        self._job: schedule.Job | None = None

    def _make_name(self) -> str:
        parts = ["every"]
        if self.every is not None:
            parts.append(str(self.every))
            if self.to is not None:
                parts.append(f"to {self.to}")
        parts.append(self.unit)
        if self.at:
            parts.append(f"at {self.at}")
        if self.until:
            parts.append(f"until {self.until}")
        return "interval(" + " ".join(parts) + ")"

    def bind(self, task_name: str, callback: RunCallback) -> None:
        # 1) every(N) 或 every()
        job: schedule.Job = schedule.every(self.every) if self.every is not None else schedule.every()
        # 2) to(M) 可选
        if self.to is not None:
            job = job.to(self.to)
        # 3) 单位（单复数 / 星期），通过 getattr 与 schedule 原生属性一致
        job = getattr(job, self.unit)
        # 4) at / until
        if self.at:
            job = job.at(self.at)
        if self.until:
            job = job.until(self.until)
        # 5) 注册执行
        self._job = job.do(self._wrap(task_name, callback))
        logger.debug(f"[trigger] bound {self.name} for task={task_name!r}")

    def unbind(self) -> None:
        if self._job is not None:
            schedule.cancel_job(self._job)
            self._job = None

    def _wrap(self, task_name: str, callback: RunCallback):
        meta = {"trigger_name": self.name, "trigger_type": "interval"}

        def _run():
            logger.debug(f"[trigger] firing {self.name} for task={task_name!r}")
            callback(meta, {})
        return _run
