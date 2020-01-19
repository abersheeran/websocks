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


class TCPSocket(Socket):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.r = reader
        self.w = writer

    async def recv(self, num: int = 4096) -> bytes:
        data = await self.r.read(num)
        logger.debug(f"<<< {data}")
        return data

    async def send(self, data: bytes) -> int:
        self.w.write(data)
        await self.w.drain()
        logger.debug(f">>> {data}")
        return len(data)

    async def close(self) -> None:
        self.w.close()

    @property
    def closed(self) -> bool:
        return self.w.is_closing()


class WebSocket(Socket):
    def __init__(self, sock: WebSocketCommonProtocol):
        self.sock = sock
        self.status = STATUS.OPEN

    async def recv(self, num: int = -1) -> bytes:
        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            self.status = STATUS.CLOSED
            raise ConnectionResetError("websocket closed.")
        logger.debug(f"<<< {data}")
        if isinstance(data, str):  # websocks
            _data = json.loads(data)
            if _data.get("STATUS") == "CLOSED":
                self.status = STATUS.CLOSED
                raise WebsocksClosed("websocks closed.")
        return data

    async def send(self, data: bytes) -> int:
        try:
            await self.sock.send(data)
        except websockets.exceptions.ConnectionClosed:
            self.status = STATUS.CLOSED
            raise ConnectionResetError("websocket closed.")
        logger.debug(f">>> {data}")
        return len(data)

    async def close(self) -> None:
        try:
            await self.sock.send(json.dumps({"STATUS": "CLOSED"}))
        except websockets.exceptions.ConnectionClosed:
            return

        try:  # websocks close
            while not self.closed:
                _ = await self.recv()
        except ConnectionResetError:
            pass

    @property
    def closed(self) -> bool:
        return self.status == STATUS.CLOSED


async def create_connection(host: str, port: int) -> TCPSocket:
    """create a TCP socket"""
    r, w = await asyncio.open_connection(host=host, port=port)
    return TCPSocket(r, w)


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
