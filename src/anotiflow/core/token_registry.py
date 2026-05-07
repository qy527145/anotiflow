"""TokenRegistry —— 统一令牌签发与校验。

Token 用于两类门面：
  - trigger: API 触发器的接入令牌（POST /trigger/{token}）
  - action:  远程自定义动作的 WebSocket 接入令牌（/ws/actions/{token}）
  - admin:   Web UI 管理入口

存储：<config_dir>/.anotiflow/tokens.json（与 config.toml 分离，避免污染用户视野）
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from loguru import logger

Scope = Literal["admin", "action", "trigger"]


@dataclass
class Token:
    id: str
    scope: Scope
    subject: str
    created_at: str
    label: str = ""
    revoked: bool = False
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class TokenRegistry:
    def __init__(self, storage_path: str | Path) -> None:
        self.path = Path(storage_path).expanduser().resolve()
        self._tokens: dict[str, Token] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for raw in data.get("tokens", []):
                t = Token(**raw)
                self._tokens[t.id] = t
            logger.info(f"loaded {len(self._tokens)} token(s) from {self.path}")
        except Exception:
            logger.exception(f"failed to load token store: {self.path}; starting empty")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tokens": [t.to_dict() for t in self._tokens.values()]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def issue(self, scope: Scope, subject: str, label: str = "") -> Token:
        prefix = {"admin": "adm", "action": "act", "trigger": "trg"}[scope]
        tid = f"{prefix}_{secrets.token_urlsafe(24)}"
        tok = Token(
            id=tid,
            scope=scope,
            subject=subject,
            label=label,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        with self._lock:
            self._tokens[tid] = tok
            self._save()
        return tok

    def verify(self, token_id: str, scope: Optional[Scope] = None) -> Optional[Token]:
        with self._lock:
            tok = self._tokens.get(token_id)
        if not tok or tok.revoked:
            return None
        if scope and tok.scope != scope:
            return None
        return tok

    def revoke(self, token_id: str) -> bool:
        with self._lock:
            tok = self._tokens.get(token_id)
            if not tok:
                return False
            tok.revoked = True
            self._save()
            return True

    def list_tokens(self, scope: Optional[Scope] = None, include_revoked: bool = False) -> list[Token]:
        with self._lock:
            out = list(self._tokens.values())
        if scope:
            out = [t for t in out if t.scope == scope]
        if not include_revoked:
            out = [t for t in out if not t.revoked]
        return out

    def get(self, token_id: str) -> Optional[Token]:
        with self._lock:
            return self._tokens.get(token_id)
