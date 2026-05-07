"""Engine —— 运行时核心。

职责：
  - 持有 ConfigStore / TokenRegistry / RemoteBroker / ApiTriggerHub
  - 装配 Task[]，bind 全部触发器
  - reload(new_raw) 时：先校验（build_tasks 不抛 → 通过），再粗粒度全解绑+全重绑
  - 启动 schedule 主循环线程（用于 IntervalTrigger）

粗粒度 reload 策略：
  - 每次 apply 都先 build 出新的 Task 列表（校验）
  - 然后 unbind 旧的 → bind 新的
  - 这样保证语义正确；后续可以做 task name 级 diff 优化（避免重启所有 interval 计时器）
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Optional

import schedule
from loguru import logger

from anotiflow.core.loader import build_tasks
from anotiflow.task import Task
from anotiflow.triggers.base import Trigger

if TYPE_CHECKING:
    from anotiflow.core.api_trigger_hub import ApiTriggerHub
    from anotiflow.core.config_store import ConfigStore
    from anotiflow.core.remote_broker import RemoteBroker
    from anotiflow.core.token_registry import TokenRegistry


class Engine:
    def __init__(
        self,
        config_store: "ConfigStore",
        token_registry: "TokenRegistry",
        remote_broker: "RemoteBroker",
        api_hub: "ApiTriggerHub",
        tick_seconds: float = 1.0,
    ) -> None:
        self.config_store = config_store
        self.tokens = token_registry
        self.broker = remote_broker
        self.api_hub = api_hub
        self.tick_seconds = tick_seconds

        self._tasks: list[Task] = []
        self._stop = False
        self._loop_thread: Optional[threading.Thread] = None

    # ---- 生命周期 ----
    def start(self) -> None:
        # 注入 ConfigStore 的 hook：apply 时先 mutate（自动签发 token），再 build 校验 + rebind
        self.config_store.set_mutate_hook(self._mutate_for_tokens)
        self.config_store.set_apply_hook(self._on_config_apply)

        # 首次装配：load_initial 已经做了
        initial = self.config_store.current()
        # 把 token 自动签发也跑一遍（首次启动时配置里可能就缺 token）
        if self._mutate_for_tokens(initial):
            # 触发一次 system 路径回写
            self.config_store.apply(initial, source="system")
        else:
            self._rebind_from_raw(initial)

        # 启动 schedule 主循环
        self._stop = False
        self._loop_thread = threading.Thread(target=self._run_schedule_loop, name="anotiflow-schedule", daemon=True)
        self._loop_thread.start()

        # 启动文件 watcher
        self.config_store.start_watcher()
        logger.info(f"engine started, {sum(1 for t in self._tasks if t.enabled)} active task(s)")

    def stop(self) -> None:
        self._stop = True
        self.config_store.stop_watcher()
        if self._loop_thread:
            self._loop_thread.join(timeout=3)
            self._loop_thread = None
        self._unbind_all()
        logger.info("engine stopped")

    # ---- ConfigStore 注入的 hook ----
    def _mutate_for_tokens(self, new_raw: dict[str, Any]) -> bool:
        """给缺 token 的 api 触发器和 remote 自定义动作自动签发 token。返回是否有修改。"""
        mutated = False
        for ti, task in enumerate(new_raw.get("tasks", []) or []):
            task_name = task.get("name") or f"task_{ti}"
            for ki, trig in enumerate(task.get("triggers", []) or []):
                if trig.get("type") == "api" and not trig.get("token"):
                    tok = self.tokens.issue("trigger", subject=f"task:{task_name}/triggers/{ki}", label=f"{task_name}.triggers[{ki}]")
                    trig["token"] = tok.id
                    mutated = True
                    logger.info(f"auto-issued trigger token for task={task_name!r} trigger#{ki}: {tok.id}")
            for ai, act in enumerate(task.get("actions", []) or []):
                if act.get("type") == "custom" and act.get("remote") and not act.get("token"):
                    tok = self.tokens.issue("action", subject=f"task:{task_name}/actions/{ai}", label=f"{task_name}.actions[{ai}]")
                    act["token"] = tok.id
                    mutated = True
                    logger.info(f"auto-issued action token for task={task_name!r} action#{ai}: {tok.id}")
        # server.admin_token 也保证存在
        server = new_raw.setdefault("server", {})
        if not server.get("admin_token"):
            tok = self.tokens.issue("admin", subject="server", label="admin")
            server["admin_token"] = tok.id
            mutated = True
            logger.warning(f"auto-issued admin token: {tok.id}  (open Web UI with this in 'X-Admin-Token' header or '?admin_token=...')")
        return mutated

    def _on_config_apply(self, new_raw: dict[str, Any]) -> None:
        """ConfigStore 在落盘前回调；做校验 + rebind。"""
        # build_tasks 抛错就直接抛出，ConfigStore.apply 会让 UI 端拿到 400
        new_tasks = build_tasks(new_raw)
        # 校验 task name 唯一
        names = [t.name for t in new_tasks]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"duplicate task names: {dup}")
        # 校验通过 → 实际 rebind（这里如果失败属于运行期问题，ConfigStore 已经更新内存；
        # 因此先尝试 bind 新的再 unbind 旧的更安全。但为简化，先粗粒度全切换）
        self._unbind_all()
        self._tasks = new_tasks
        self._bind_all()

    def _rebind_from_raw(self, raw: dict[str, Any]) -> None:
        new_tasks = build_tasks(raw)
        self._unbind_all()
        self._tasks = new_tasks
        self._bind_all()

    # ---- bind / unbind ----
    def _bind_all(self) -> None:
        for task in self._tasks:
            if not task.enabled:
                logger.info(f"task disabled, skipping: {task.name!r}")
                continue
            runner = self._make_runner(task)
            for trigger in task.triggers:
                trigger.bind(task.name, runner)
            logger.info(f"task bound: {task!r}")

    def _unbind_all(self) -> None:
        for task in self._tasks:
            for trigger in task.triggers:
                try:
                    trigger.unbind()
                except Exception:
                    logger.exception(f"unbind failed: task={task.name!r} trigger={trigger.name!r}")
        self._tasks = []

    @staticmethod
    def _make_runner(task: Task):
        def _run(trigger: Trigger, _payload: dict) -> None:
            ctx = {"task": task, "trigger": trigger}
            logger.info(
                f"task firing: {task.name!r} via {trigger.name!r} "
                f"({len(task.actions)} action(s))"
            )
            for action in task.actions:
                try:
                    action.execute(ctx)
                except Exception:
                    logger.exception(f"action failed: task={task.name!r} action={action.name!r}")
        return _run

    # ---- 主循环 ----
    def _run_schedule_loop(self) -> None:
        while not self._stop:
            try:
                schedule.run_pending()
            except Exception:
                logger.exception("schedule.run_pending raised")
            time.sleep(self.tick_seconds)
