"""WebSocket 路由：/ws/{scope}/{token}

scope 当前仅支持 "actions"（远程动作）；未来 MCP/Skill 走相同路径模板。
连接成功后客户端协议（JSON 文本帧）：
  client → server 首帧（可选）：{"op":"hello","sdk":"anotiflow-py","version":"x"}
  server → client 派发任务： {"op":"invoke","invocation_id":"...","envelope":{...}}
  client → server 回包：    {"op":"result","invocation_id":"...","ok":true,"value":{...}}
                          或 {"op":"result","invocation_id":"...","ok":false,"error":"..."}
  双向心跳 ping/pong（可选）
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from anotiflow.core.event_bus import bus
from anotiflow.core.remote_broker import RemoteBroker
from anotiflow.core.token_index import TokenIndex


def make_router(broker: RemoteBroker, tokens: TokenIndex) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/{scope}/{token}")
    async def ws(websocket: WebSocket, scope: str, token: str):
        if scope not in ("actions",):
            await websocket.close(code=1008)  # policy violation
            return
        if not tokens.verify(token, "action"):
            await websocket.close(code=4401)  # custom: unauthorized
            return

        await websocket.accept()
        client = await broker.register_client(token, websocket)
        try:
            while True:
                msg = await websocket.receive_json()
                op = msg.get("op")
                if op == "hello":
                    logger.debug(f"[ws] hello from token={token}: {msg}")
                elif op == "result":
                    invocation_id = msg.get("invocation_id")
                    if not invocation_id:
                        continue
                    broker.deliver_result(invocation_id, msg)
                elif op == "publish":
                    # 客户端 handler 通过 ctx.publish(event, payload) 反向广播事件。
                    # 服务端 EventBus 立刻分发；订阅了同名事件的 event 触发器会触发其它任务。
                    event = msg.get("event")
                    payload = msg.get("payload") or {}
                    if not event:
                        logger.warning(f"[ws] publish without event from token={token}")
                        continue
                    logger.info(f"[ws] remote publish: event={event!r} payload={payload!r} from token={token}")
                    bus.publish(event, payload)
                elif op == "ping":
                    await websocket.send_json({"op": "pong"})
                elif op == "pong":
                    pass
                else:
                    logger.warning(f"[ws] unknown op: {op}")
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception(f"[ws] handler crashed: token={token}")
        finally:
            await broker.unregister_client(token, client)

    return r
