"""API 触发器：通过 HTTP POST /trigger/{token} 外部触发任务。

配置：
    [[tasks.triggers]]
    type = "api"
    token = "trg_xxx"       # 缺省时 Engine 会自动签发

服务端收到 POST body 作为 payload；trigger.payload 即 body。
"""

from __future__ import annotations

from loguru import logger

from anotiflow.core.api_trigger_hub import hub as _hub
from anotiflow.core.registry import register_trigger
from anotiflow.triggers.base import RunCallback, Trigger


@register_trigger("api")
class APITrigger(Trigger):
    kind = "api"

    def __init__(self, token: str | None = None, **_extra) -> None:
        super().__init__()
        # token 可能暂缺：loader 会在 build_tasks 阶段看到 None，但 Engine._mutate_for_tokens
        # 会在 build 前自动把 token 塞进 raw dict，再构造本类；所以正常路径不会是 None。
        self.token = token or ""

    def bind(self, task_name: str, callback: RunCallback) -> None:
        if not self.token:
            raise ValueError(f"api trigger of task {task_name!r} missing 'token'")

        def _fire(payload: dict) -> None:
            self._record_fire(payload)
            logger.debug(f"[trigger] api {self.name!r} firing: task={task_name!r} payload={payload!r}")
            callback(self, payload)

        _hub.register(self.token, self, _fire)
        logger.debug(f"[trigger] api registered: token={self.token} task={task_name!r}")

    def unbind(self) -> None:
        if self.token:
            _hub.unregister(self.token)
