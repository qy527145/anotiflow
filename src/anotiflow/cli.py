"""anotiflow CLI 入口。

用法:
    uv run anotiflow --config config.toml
    uv run anotiflow -c config.toml --log-level DEBUG
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from anotiflow.core.loader import load_tasks
from anotiflow.core.scheduler import Scheduler
from anotiflow.logging_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anotiflow", description="可扩展任务调度通知框架")
    parser.add_argument("-c", "--config", required=True, help="TOML 配置文件路径")
    parser.add_argument("--log-level", default="INFO", help="日志级别 (DEBUG/INFO/WARNING/ERROR)")
    args = parser.parse_args(argv)

    setup_logging(level=args.log_level.upper())

    logger.info(f"loading config: {args.config}")
    try:
        tasks = load_tasks(args.config)
    except Exception:
        logger.exception("failed to load config")
        return 2

    if not tasks:
        logger.warning("no tasks found in config; nothing to do")
        return 0

    Scheduler(tasks).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
