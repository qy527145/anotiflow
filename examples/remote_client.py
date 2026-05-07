"""远程自定义动作客户端示例。

在一台有业务依赖的机器上（甚至与 anotiflow 宿主不同的 venv / 不同的 Python 版本）：

    pip install anotiflow                     # 仅依赖 websockets
    python examples/remote_client.py

宿主那边在 config.toml 里配好一个 custom-remote 动作 + token，
或者在 Web UI 里创建任务、把 token 粘过来。
"""

from __future__ import annotations

import os

from anotiflow import RemoteAction

SERVER = os.environ.get("ANOTIFLOW_SERVER", "ws://127.0.0.1:8765")
TOKEN = os.environ.get("ANOTIFLOW_TOKEN", "act_REPLACE_ME")

action = RemoteAction(SERVER, token=TOKEN)


@action.handler
def handle(ctx):
    """ctx 与本地 custom 动作的 context 等价：
        ctx.task.name / ctx.task.config
        ctx.trigger.name / ctx.trigger.kind / ctx.trigger.config
        ctx.trigger.fired_at / ctx.trigger.payload

    另外 SDK 还在 ctx 上提供：
        ctx.publish(event, payload=None)
            把事件反向广播回服务端 EventBus，订阅了同名事件的 event 触发器
            会立即触发其它任务（同步上下文里阻塞调用即可；async handler 里要 await）。
        ctx.raw
            原始 envelope dict，方便诊断。
    """
    print(
        f"[remote] task={ctx.task.name!r} "
        f"trigger={ctx.trigger.name!r} ({ctx.trigger.kind}) "
        f"fired_at={ctx.trigger.fired_at} "
        f"payload={ctx.trigger.payload!r}"
    )

    # 例：业务判断后反向广播一个事件，服务端的下游任务（type="event" 触发器订阅同名事件）
    # 会立刻接力执行。
    if ctx.trigger.payload.get("alert"):
        ctx.publish("alert.from_remote", {"reason": "demo", "from_task": ctx.task.name})

    return {"ok": True, "handled_by": "remote_client.py"}


if __name__ == "__main__":
    action.run()
