"""基于 schedule 库的定时触发器，保持 schedule 原生 API 的灵活性。

调度参数（同 schedule）:
  every:    int 或省略    - 间隔次数；省略时等价于 schedule.every()
  unit:     str           - 时间单位，支持单复数 second(s)/minute(s)/hour(s)/day(s)/week(s)，
                            以及具体星期 monday..sunday
  to:       int           - 配合 every 形成随机区间 [every, to]
  at:       str           - 精确时刻，例如 "10:30" / ":23"
  until:    str           - 截止时刻

构造函数额外接受 **kwargs，吃掉用户在 TOML 里写的任意自定义字段。
完整 TOML 子表（含 type/name/自定义字段）由 loader 注入到 self.config。
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
    kind = "interval"

    def __init__(
        self,
        unit: str,
        every: int | None = None,
        to: int | None = None,
        at: str | None = None,
        until: str | None = None,
        **_extra,
    ) -> None:
        super().__init__()
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
            raise ValueError(f"weekday unit {unit!r} cannot be combined with 'every'/'to'")

        self.unit = unit
        self.every = every
        self.to = to
        self.at = at
        self.until = until
        self._job: schedule.Job | None = None

    def bind(self, task_name: str, callback: RunCallback) -> None:
        job: schedule.Job = schedule.every(self.every) if self.every is not None else schedule.every()
        if self.to is not None:
            job = job.to(self.to)
        job = getattr(job, self.unit)
        if self.at:
            job = job.at(self.at)
        if self.until:
            job = job.until(self.until)
        self._job = job.do(self._wrap(task_name, callback))
        logger.debug(f"[trigger] bound {self.name} for task={task_name!r}")

    def unbind(self) -> None:
        if self._job is not None:
            schedule.cancel_job(self._job)
            self._job = None

    def _wrap(self, task_name: str, callback: RunCallback):
        def _run():
            self._record_fire({})
            logger.debug(f"[trigger] firing {self.name} for task={task_name!r}")
            callback(self, {})
        return _run
