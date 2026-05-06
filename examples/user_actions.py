"""示例：用户自定义业务条件检查行为。

在 config.toml 中通过 dotted path 引用：
    [[tasks.actions]]
    type = "custom"
    path = "examples.user_actions.check_stock_price"

函数签名: fn(context: dict) -> None
其中 context 提供两个命名空间根对象（详见 loader.py 顶部说明）:
    context["task"]     当前 Task 实例   - .name / .config[xxx]
    context["trigger"]  命中触发器实例    - .config[xxx] / .fired_at / .payload[xxx] / .kind
"""

from __future__ import annotations

import random

from loguru import logger

from anotiflow.core.event_bus import bus


def check_stock_price(context: dict) -> None:
    """模拟股价检查：从 task.config 读业务参数（symbol/threshold），超过阈值就广播事件。"""
    task = context["task"]
    trigger = context["trigger"]
    symbol = task.config.get("symbol", "AAPL")
    threshold = float(task.config.get("threshold", 100.0))

    price = round(random.uniform(95.0, 110.0), 2)
    logger.info(
        f"[user] ({task.name} via {trigger.config['name']} @ {trigger.fired_at}) "
        f"{symbol}={price} threshold={threshold}"
    )
    if price > threshold:
        bus.publish(
            "stock.high",
            {"symbol": symbol, "price": price, "threshold": threshold, "checked_at": trigger.fired_at},
        )


def print_context(context: dict) -> None:
    """调试用：直观展示行为能拿到哪些信息。"""
    task = context["task"]
    trigger = context["trigger"]
    logger.info(
        f"[user] print_context: task={task.name!r} task.config={task.config!r} "
        f"trigger={trigger.config['name']!r} trigger.config={trigger.config!r} "
        f"fired_at={trigger.fired_at!r} payload={trigger.payload!r}"
    )
