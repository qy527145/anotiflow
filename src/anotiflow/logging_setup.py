"""loguru 日志初始化。"""

from __future__ import annotations

import sys

from loguru import logger


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "<level>{level: <7}</level> "
            "<cyan>{name}</cyan> - <level>{message}</level>"
        ),
        backtrace=True,
        diagnose=False,
    )
