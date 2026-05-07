"""ConfigStore —— 配置单一事实源。

职责：
  - 维护内存中的 raw 配置 dict（保真 TOML 结构）
  - 首次启动时若文件不存在，自动生成空模板
  - apply(new_raw, source=...) 统一处理 UI / watcher / init 三路写入
  - 原子落盘（tempfile + os.replace）
  - 通过 watchdog 监听文件变更，hash 抑制双向回环
  - 写入前回调 on_apply_hook，允许 Engine 试装配校验 + rebind

source 语义：
  "init"    首次启动时从文件加载；不再回写
  "ui"      来自 HTTP / UI；校验 → rebind → 原子落盘
  "file"    来自文件 watcher；校验 → rebind；不回写（文件已是最新）
  "system"  Token 自动回写等内部路径；校验 → rebind → 原子落盘
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import tomli_w
from loguru import logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from anotiflow.core.loader import parse_raw

ApplyHook = Callable[[dict], None]  # 抛异常表示拒绝
Source = Literal["init", "ui", "file", "system"]

_EMPTY_TEMPLATE = """# anotiflow config
# 首次启动自动生成。可以直接通过 Web UI 增删任务，或手改本文件——两路等价。
# 详细说明：https://github.com/qy527145/anotiflow

[server]
host = "127.0.0.1"
port = 8765
# admin_token 会在首次启动自动填充（打印到日志）。留空表示首次运行时生成。
admin_token = ""
# 远程动作调度默认参数
action_timeout_seconds = 30
offline_policy = "queue"   # queue | drop | error

# 下面是任务定义示例（默认为空）。
# [[tasks]]
# name = "my_first_task"
# enabled = true
#
# [[tasks.triggers]]
# type = "interval"
# every = 10
# unit = "seconds"
#
# [[tasks.actions]]
# type = "publish_event"
# event = "hello"
"""


class ConfigStore:
    def __init__(self, path: str | Path) -> None:
        self.path: Path = Path(path).expanduser().resolve()
        self._raw: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._last_hash: str = ""
        self._observer: Optional[Observer] = None
        self._apply_hook: Optional[ApplyHook] = None
        self._mutate_hook: Optional[Callable[[dict], bool]] = None

    # ---- hook 注入 ----
    def set_apply_hook(self, hook: ApplyHook) -> None:
        """hook(new_raw) 抛异常表示校验失败；会在写盘前被调用。"""
        self._apply_hook = hook

    def set_mutate_hook(self, hook: Callable[[dict], bool]) -> None:
        """hook(new_raw) -> mutated: 可以修改 new_raw（比如补发 token），返回 True 表示已修改。"""
        self._mutate_hook = hook

    # ---- 初始化 / 读取 ----
    def load_initial(self) -> dict[str, Any]:
        """读取（或生成）配置文件到内存。返回当前 raw（深拷贝）。"""
        with self._lock:
            if not self.path.exists():
                logger.warning(f"config not found, creating empty template at: {self.path}")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(_EMPTY_TEMPLATE, encoding="utf-8")
            self._raw = parse_raw(self.path)
            self._last_hash = self._hash_of_file()
            logger.info(f"config loaded: {self.path} ({len(self._raw.get('tasks', []) or [])} task(s))")
            return _deep_copy(self._raw)

    def current(self) -> dict[str, Any]:
        with self._lock:
            return _deep_copy(self._raw)

    def server_config(self) -> dict[str, Any]:
        with self._lock:
            return _deep_copy(self._raw.get("server", {}) or {})

    # ---- 写入路径（统一入口）----
    def apply(self, new_raw: dict[str, Any], *, source: Source) -> None:
        with self._lock:
            # 1. mutate（可能给 action/trigger 补 token，然后再校验）
            if self._mutate_hook:
                try:
                    self._mutate_hook(new_raw)
                except Exception:
                    logger.exception("config mutate hook failed")
                    raise

            # 2. 校验 + rebind（由 Engine 注入的 hook 做）
            if self._apply_hook:
                self._apply_hook(new_raw)  # 抛异常则拒绝

            # 3. 更新内存
            self._raw = _deep_copy(new_raw)

            # 4. 落盘（init/file 不回写，避免死循环或覆盖用户最新内容）
            if source in ("ui", "system"):
                self._write_atomic(new_raw)
                self._last_hash = self._hash_of_file()
            logger.info(f"config applied from source={source}")

    # ---- watcher ----
    def start_watcher(self) -> None:
        if self._observer is not None:
            return

        store = self

        class _H(FileSystemEventHandler):
            def on_modified(self, event: FileSystemEvent) -> None:
                if event.is_directory:
                    return
                if Path(event.src_path).resolve() != store.path:
                    return
                store._on_file_changed()

            def on_created(self, event: FileSystemEvent) -> None:
                self.on_modified(event)

            def on_moved(self, event: FileSystemEvent) -> None:
                # 编辑器常见的"写入 tempfile + rename"会触发这个
                if event.is_directory:
                    return
                dest = getattr(event, "dest_path", None)
                if dest and Path(dest).resolve() == store.path:
                    store._on_file_changed()
                elif Path(event.src_path).resolve() == store.path:
                    store._on_file_changed()

        self._observer = Observer()
        self._observer.schedule(_H(), str(self.path.parent), recursive=False)
        self._observer.start()
        logger.info(f"config watcher started on: {self.path.parent}")

    def stop_watcher(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None

    def _on_file_changed(self) -> None:
        try:
            new_hash = self._hash_of_file()
        except FileNotFoundError:
            logger.warning(f"config file disappeared: {self.path}")
            return
        if new_hash == self._last_hash:
            return  # UI 刚刚写下的，无需再回环
        logger.info(f"config file changed on disk: {self.path}")
        try:
            new_raw = parse_raw(self.path)
            self.apply(new_raw, source="file")
            self._last_hash = new_hash
        except Exception:
            logger.exception("reload from file failed; keeping last-known-good config")

    # ---- 内部工具 ----
    def _write_atomic(self, raw: dict[str, Any]) -> None:
        data = tomli_w.dumps(raw).encode("utf-8")
        tmp_dir = str(self.path.parent)
        fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".toml.tmp", dir=tmp_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _hash_of_file(self) -> str:
        h = hashlib.sha256()
        with self.path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()


def _deep_copy(cfg: Any) -> Any:
    if isinstance(cfg, dict):
        return {k: _deep_copy(v) for k, v in cfg.items()}
    if isinstance(cfg, list):
        return [_deep_copy(v) for v in cfg]
    return cfg
