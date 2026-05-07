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
    """
    print(
        f"[remote] task={ctx.task.name!r} "
        f"trigger={ctx.trigger.name!r} ({ctx.trigger.kind}) "
        f"fired_at={ctx.trigger.fired_at} "
        f"payload={ctx.trigger.payload!r}"
    )
    # 随意返回 JSON-friendly 数据；服务端可通过 publish_on_success 把它串入事件总线
    return {"ok": True, "handled_by": "remote_client.py"}


if __name__ == "__main__":
    action.run()
