"""TokenIndex —— 从 config.toml 派生的只读令牌索引。

设计原则：config.toml 是令牌的唯一事实源；内存索引只负责 O(1) 校验。
没有独立的 tokens.json 文件，也不提供吊销 API —— 轮换/吊销等于直接在 config
中把对应字段改/清空（下一次 apply 时会由 Engine 自动补发新 token）。

三类令牌及其在 config 中的位置：
  - admin:   server.admin_token
  - trigger: [[tasks.triggers]] type="api" 的 token 字段
  - action:  [[tasks.actions]] type="custom" remote=true 的 token 字段
"""

from __future__ import annotations

import secrets
import threading
from typing import Literal, Optional

Scope = Literal["admin", "action", "trigger"]

_PREFIX: dict[Scope, str] = {"admin": "adm", "action": "act", "trigger": "trg"}


def generate(scope: Scope) -> str:
    """生成一个新 token（纯字符串）。不落盘、不入索引，由调用者负责写入 config。"""
    return f"{_PREFIX[scope]}_{secrets.token_urlsafe(24)}"


class TokenIndex:
    """运行时从 config raw dict 派生的令牌索引。线程安全，可被多个路由共享。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[str, Scope] = {}

    def rebuild(self, raw: dict) -> None:
        """根据 raw config 重建索引。应在每次 config apply 后调用。"""
        new_map: dict[str, Scope] = {}

        server = raw.get("server") or {}
        admin = str(server.get("admin_token") or "").strip()
        if admin:
            new_map[admin] = "admin"

        for task in raw.get("tasks") or []:
            for trig in task.get("triggers") or []:
                if trig.get("type") == "api":
                    tid = str(trig.get("token") or "").strip()
                    if tid:
                        new_map[tid] = "trigger"
            for act in task.get("actions") or []:
                if act.get("type") == "custom" and act.get("remote"):
                    tid = str(act.get("token") or "").strip()
                    if tid:
                        new_map[tid] = "action"

        with self._lock:
            self._tokens = new_map

    def verify(self, token_id: str, scope: Optional[Scope] = None) -> bool:
        """返回给定 token 是否存在且（如指定）scope 匹配。"""
        if not token_id:
            return False
        with self._lock:
            s = self._tokens.get(token_id)
        if s is None:
            return False
        if scope is not None and s != scope:
            return False
        return True
