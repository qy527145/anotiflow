"""钉钉机器人通知行为。

本实现直接调用钉钉群机器人 webhook，不再依赖 ipush.Dingtalk —— 因为 ipush 内部
硬编码了 payload 不带 ``at`` 字段，无法 @ 指定用户。改为自己拼 payload 后：

- 不带 @ 的旧用法（仅 token / secret / message_template / title）行为完全不变；
- 新增 ``at_mobiles`` / ``at_user_ids`` / ``at_all`` 三个可选字段支持 @；
- 新增 ``msgtype = "text" | "markdown"``，markdown 下 ``title`` 字段会作为面板标题。

模板渲染规则：
- ``message_template`` 仍由父类 NotifyAction._render(context) 处理；
- ``at_mobiles`` / ``at_user_ids`` 接受 list 或字符串：
    * list  → 每项独立 ``str.format(**ctx)`` 渲染，空串过滤
    * str   → 整体渲染后按 ``,`` ``;`` 空白拆分
  方便从 ``{trigger.payload[mobiles]}`` 这类字段动态取值。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
import urllib.parse
from typing import Any

import requests
from loguru import logger

from anotiflow.actions.notify_base import NotifyAction
from anotiflow.core.registry import register_action

_WEBHOOK = "https://oapi.dingtalk.com/robot/send"
_SPLIT_RE = re.compile(r"[,;\s]+")


@register_action("dingtalk")
class DingtalkNotify(NotifyAction):
    def __init__(
        self,
        token: str,
        secret: str = "",
        message_template: str = "",
        title: str = "",
        msgtype: str = "text",
        at_mobiles: Any = None,
        at_user_ids: Any = None,
        at_all: bool = False,
    ) -> None:
        super().__init__(message_template=message_template)
        self.name = "dingtalk"
        self.token = token
        self.secret = secret
        self.title = title
        self.msgtype = msgtype if msgtype in ("text", "markdown") else "text"
        self.at_mobiles = at_mobiles
        self.at_user_ids = at_user_ids
        self.at_all = bool(at_all)

    # NotifyAction.execute(context) 已经把 message_template 渲染好交给 _send；
    # 但 _send 拿不到 context，所以无法渲染 at_mobiles。这里直接 override execute。
    def execute(self, context: dict) -> None:
        message = self._render(context)
        at_mobiles = self._render_list(self.at_mobiles, context)
        at_user_ids = self._render_list(self.at_user_ids, context)
        title = self._render_simple(self.title, context) or "新消息"
        self._post(message, title=title, at_mobiles=at_mobiles, at_user_ids=at_user_ids)

    # 保留 _send 以兼容子类继承场景；普通调用走 execute。
    def _send(self, message: str) -> None:
        self._post(message, title=self.title or "新消息", at_mobiles=[], at_user_ids=[])

    # ---- helpers ----
    def _render_simple(self, tpl: str, context: dict) -> str:
        if not tpl:
            return ""
        try:
            return tpl.format(**context)
        except (KeyError, IndexError) as e:
            logger.warning(f"[dingtalk] title/text template missing key: {e}; using raw")
            return tpl

    def _render_list(self, value: Any, context: dict) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    if item:
                        out.append(str(item))
                    continue
                rendered = self._render_simple(item, context).strip()
                if rendered:
                    out.append(rendered)
            return out
        if isinstance(value, str):
            rendered = self._render_simple(value, context)
            return [s for s in _SPLIT_RE.split(rendered) if s]
        # 其它类型：尽力转字符串
        return [str(value)]

    def _signed_url(self) -> str:
        url = f"{_WEBHOOK}?access_token={self.token}"
        if not self.secret:
            return url
        ts = str(round(time.time() * 1000))
        code = hmac.new(
            self.secret.encode("utf-8"),
            f"{ts}\n{self.secret}".encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(code))
        return f"{url}&timestamp={ts}&sign={sign}"

    def _post(self, message: str, *, title: str, at_mobiles: list[str], at_user_ids: list[str]) -> None:
        # 钉钉拒绝空 content，给个保底
        if not message or not message.strip():
            logger.warning("[dingtalk] empty message, using placeholder to avoid 400202")
            message = title or "(empty notification)"

        at = {"isAtAll": self.at_all}
        if at_mobiles:
            at["atMobiles"] = at_mobiles
        if at_user_ids:
            at["atUserIds"] = at_user_ids

        if self.msgtype == "markdown":
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": title, "text": message},
                "at": at,
            }
        else:
            payload = {
                "msgtype": "text",
                "text": {"content": message},
                "at": at,
            }

        logger.info(
            f"[dingtalk] sending msgtype={self.msgtype} "
            f"at_mobiles={at_mobiles} at_user_ids={at_user_ids} at_all={self.at_all}"
        )
        try:
            resp = requests.post(self._signed_url(), json=payload, timeout=10)
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code != 200 or data.get("errcode", 0) != 0:
                logger.warning(f"[dingtalk] send failed: status={resp.status_code} body={resp.text[:200]}")
        except Exception:
            logger.exception("[dingtalk] send raised")
