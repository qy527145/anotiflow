"""anotiflow CLI 入口。

用法:
    anotiflow                         # 当前目录 ./config.toml；不存在则自动生成空模板
    anotiflow --config my.toml        # 指定配置文件
    anotiflow --no-web                # 仅跑调度，不起 Web 服务（兼容老用法）
    anotiflow --host 0.0.0.0 --port 9000   # 覆盖配置里的 server.host / server.port
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

import uvicorn
from loguru import logger

from anotiflow.core.api_trigger_hub import hub as _api_hub
from anotiflow.core.config_store import ConfigStore
from anotiflow.core.engine import Engine
from anotiflow.core.remote_broker import broker as _broker
from anotiflow.core.token_registry import TokenRegistry
from anotiflow.logging_setup import setup_logging
from anotiflow.server.app import build_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anotiflow", description="可扩展任务调度通知框架 + Web 控制台")
    parser.add_argument("-c", "--config", default="config.toml", help="TOML 配置文件路径（默认: ./config.toml；不存在则自动生成）")
    parser.add_argument("--log-level", default="INFO", help="日志级别 (DEBUG/INFO/WARNING/ERROR)")
    parser.add_argument("--no-web", action="store_true", help="仅启动调度引擎，不启动 Web 服务")
    parser.add_argument("--host", default=None, help="覆盖 server.host")
    parser.add_argument("--port", type=int, default=None, help="覆盖 server.port")
    args = parser.parse_args(argv)

    setup_logging(level=args.log_level.upper())

    config_path = Path(args.config).expanduser().resolve()
    config_store = ConfigStore(config_path)

    # token 存储与 config 同目录的隐藏子目录
    token_path = config_path.parent / ".anotiflow" / "tokens.json"
    tokens = TokenRegistry(token_path)

    # 加载配置（不存在则生成空模板）
    try:
        config_store.load_initial()
    except Exception:
        logger.exception("failed to load config")
        return 2

    engine = Engine(
        config_store=config_store,
        token_registry=tokens,
        remote_broker=_broker,
        api_hub=_api_hub,
    )

    # 启动 engine（含首次装配 + 自动签发 token）
    try:
        engine.start()
    except Exception:
        logger.exception("engine start failed")
        return 3

    # 信号处理 → 全局停机
    stop_event = threading.Event()

    def _on_signal(signum, frame):  # noqa: ARG001
        logger.warning(f"received signal {signum}, shutting down...")
        stop_event.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    if args.no_web:
        logger.info("running in --no-web mode (engine only)")
        try:
            stop_event.wait()
        finally:
            engine.stop()
        return 0

    # 启动 Web 服务
    server_cfg = config_store.server_config()
    host = args.host or server_cfg.get("host", "127.0.0.1")
    port = args.port or int(server_cfg.get("port", 8765))

    app = build_app(
        config_store=config_store,
        tokens=tokens,
        api_hub=_api_hub,
        broker=_broker,
        engine=engine,
    )

    logger.info(f"web server starting at http://{host}:{port}  (open this URL in browser)")
    # 把 admin_token + 登录 URL 醒目地打印出来；user 不会错过
    server_cfg2 = config_store.server_config()
    admin_tok = server_cfg2.get("admin_token", "")
    if admin_tok:
        bar = "═" * 70
        logger.info(f"\n{bar}\n  Web UI: http://{host}:{port}\n  Admin token (paste in login page): {admin_tok}\n  Direct link: http://{host}:{port}/login\n{bar}")
    config = uvicorn.Config(app, host=host, port=port, log_level=args.log_level.lower(), lifespan="on")
    server = uvicorn.Server(config)

    # uvicorn 自带 SIGINT/SIGTERM 处理；我们额外把 engine 关掉
    try:
        server.run()
    finally:
        engine.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
