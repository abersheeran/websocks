"""
websocks 协议封装
"""
import json
import asyncio
from enum import IntEnum

import websockets
from websockets import WebSocketClientProtocol, WebSocketCommonProtocol

from .types import Socket
from .utils import logger
from .exceptions import WebsocksImplementationError, WebsocksClosed, WebsocksRefused


class STATUS(IntEnum):
    OPEN = 1
    CLOSED = 0


async def connect_server(
    sock: WebSocketClientProtocol, host: str, port: int
) -> WebSocket:
    """connect websocks server"""
    await sock.send(json.dumps({"HOST": host, "PORT": port}))
    resp = await sock.recv()
    try:
        assert isinstance(resp, str), "must be str"
        if not json.loads(resp)["ALLOW"]:
            raise WebsocksRefused(f"websocks server can't connect {host}:{port}")
    except (AssertionError, KeyError):
        raise WebsocksImplementationError()
    return WebSocket(sock)
