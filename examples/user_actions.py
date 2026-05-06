"""示例：用户自定义业务条件检查行为。

在 config.toml 中通过 dotted path 引用：
    [[tasks.actions]]
    type = "custom"
    path = "examples.user_actions.check_stock_price"

约定的函数签名: fn(context: dict) -> None
context 字段见框架文档 / loader.py 顶部说明。
"""

from __future__ import annotations

import random

from loguru import logger

from anotify.core.event_bus import bus


def check_stock_price(context: dict) -> None:
    """模拟股价检查：随机生成一个价格，超过阈值就广播 stock.high 事件。

    演示了如何读取 context 字段 + 通过 EventBus 串联事件。
    """
    task_name = context["task_name"]
    fired_at = context["fired_at"]
    price = round(random.uniform(95.0, 110.0), 2)
    threshold = 100.0
    logger.info(f"[user] ({task_name} @ {fired_at}) check_stock_price: AAPL={price} (threshold={threshold})")
    if price > threshold:
        bus.publish(
            "stock.high",
            {"symbol": "AAPL", "price": price, "threshold": threshold, "checked_at": fired_at},
        )


def print_context(context: dict) -> None:
    """调试用：打印所有 context 字段，直观展示行为能拿到哪些信息。"""
    logger.info(f"[user] print_context: {context!r}")
