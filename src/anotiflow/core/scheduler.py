"""主调度器：装配任务（多触发器）→ 启动主循环 → 优雅关闭。

每次任意一个触发器命中，调用 runner，按顺序执行所有 actions。
"""

from __future__ import annotations

import signal
import time
from datetime import datetime

import schedule
from loguru import logger

from anotiflow.task import Task


class Scheduler:
    def __init__(self, tasks: list[Task], tick_seconds: float = 1.0) -> None:
        self.tasks = tasks
        self.tick_seconds = tick_seconds
        self._stop = False

    def start(self) -> None:
        self._bind_all()
        self._install_signal_handlers()
        active = sum(1 for t in self.tasks if t.enabled)
        logger.info(f"scheduler started, {active} active task(s)")
        try:
            while not self._stop:
                schedule.run_pending()
                time.sleep(self.tick_seconds)
        finally:
            self._unbind_all()
            logger.info("scheduler stopped")

    def stop(self) -> None:
        self._stop = True

    def _bind_all(self) -> None:
        for task in self.tasks:
            if not task.enabled:
                logger.info(f"task disabled, skipping: {task.name!r}")
                continue
            runner = self._make_runner(task)
            for trigger in task.triggers:
                trigger.bind(task.name, runner)
            logger.info(f"task bound: {task!r}")

    def _unbind_all(self) -> None:
        for task in self.tasks:
            for trigger in task.triggers:
                try:
                    trigger.unbind()
                except Exception:
                    logger.exception(f"unbind failed: task={task.name!r} trigger={trigger.name!r}")

    @staticmethod
    def _make_runner(task: Task):
        def _run(trigger_meta: dict, trigger_payload: dict) -> None:
            ctx: dict = {
                "task_name": task.name,
                "trigger_name": trigger_meta.get("trigger_name", ""),
                "trigger_type": trigger_meta.get("trigger_type", ""),
                "trigger_payload": trigger_payload or {},
                "fired_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            logger.info(
                f"task firing: {task.name!r} via {ctx['trigger_name']!r} "
                f"({len(task.actions)} action(s))"
            )
            for action in task.actions:
                try:
                    action.execute(ctx)
                except Exception:
                    logger.exception(f"action failed: task={task.name!r} action={action.name!r}")
        return _run

    def _install_signal_handlers(self) -> None:
        def _handler(signum, frame):  # noqa: ARG001
            logger.warning(f"received signal {signum}, shutting down...")
            self.stop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass
