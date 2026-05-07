"""RemoteActionProxy —— 框架侧的远程动作代理。

配置：
    [[tasks.actions]]
    type = "custom"
    remote = true
    token = "act_xxx"           # 缺省时 Engine 会自动签发
    wait = true                 # 是否等待客户端回包（默认 true）
    timeout_seconds = 30        # 等待超时
    offline_policy = "queue"    # queue | drop | error
    publish_on_success = "x.y"  # 客户端回包成功时向 EventBus 发的事件名（可选）

执行时：
  1. 把 task / trigger 信息序列化成 envelope
  2. 调 RemoteBroker 把 envelope 推给客户端
  3. 等回包；ok 则可选发事件；error 则上抛（被 Engine runner 捕获记日志）
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from anotiflow.actions.base import Action
from anotiflow.core.event_bus import bus
from anotiflow.core.remote_broker import broker


class RemoteActionProxy(Action):
    def __init__(
        self,
        token: str | None = None,
        wait: bool = True,
        timeout_seconds: float = 30.0,
        offline_policy: str = "queue",
        publish_on_success: Optional[str] = None,
        **_extra: Any,
    ) -> None:
        # _extra 吃掉 remote=true / 用户自定义字段
        self.token = token or ""
        self.wait = bool(wait)
        self.timeout_seconds = float(timeout_seconds)
        self.offline_policy = offline_policy
        self.publish_on_success = publish_on_success
        self.name = f"remote({self.token[:12]}…)" if self.token else "remote"

    def execute(self, context: dict) -> None:
        if not self.token:
            raise RuntimeError("RemoteActionProxy missing token")

        task = context["task"]
        trigger = context["trigger"]

        envelope = {
            "task": {"name": task.name, "config": task.config},
            "trigger": {
                "name": trigger.name,
                "kind": trigger.kind,
                "config": trigger.config,
                "fired_at": trigger.fired_at,
                "payload": trigger.payload,
            },
        }

        try:
            result = broker.dispatch_sync(
                self.token,
                envelope,
                wait=self.wait,
                timeout=self.timeout_seconds,
                offline_policy=self.offline_policy,
            )
        except TimeoutError as e:
            logger.warning(f"[{self.name}] {e}")
            return
        except Exception:
            logger.exception(f"[{self.name}] dispatch failed")
            raise

        if not self.wait or result is None:
            return

        if not result.get("ok"):
            err = result.get("error", "<no message>")
            logger.warning(f"[{self.name}] remote handler reported error: {err}")
            return

        value = result.get("value")
        if self.publish_on_success:
            bus.publish(self.publish_on_success, {"value": value, "from": self.name})
