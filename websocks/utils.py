import json
import asyncio
import logging
from typing import Set
from asyncio import Future, Task, CancelledError

import websockets
from websockets import WebSocketClientProtocol, WebSocketCommonProtocol

from .types import Socket
from .exceptions import WebsocksImplementationError, WebsocksClosed, WebsocksRefused


logger: logging.Logger = logging.getLogger("websocks")


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
        self.status = "OPEN"

    async def recv(self, num: int = -1) -> bytes:
        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError("websocket closed.")
        logger.debug(f"<<< {data}")
        if isinstance(data, str):  # websocks
            _data = json.loads(data)
            if _data.get("STATUS") == "CLOSED":
                self.status = "CLOSED"
                raise WebsocksClosed("websocks closed.")
        return data

    async def send(self, data: bytes) -> int:
        try:
            await self.sock.send(data)
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError("websocket closed.")
        logger.debug(f">>> {data}")
        return len(data)

    async def close(self) -> None:
        await self.sock.close()

    @property
    def closed(self) -> bool:
        return self.sock.closed

    async def reset(self) -> None:
        try:
            await self.sock.send(json.dumps({"STATUS": "CLOSED"}))
        except websockets.exceptions.ConnectionClosed:
            pass


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


def onlyfirst(*coros, loop=None):
    """
    并发执行多个 coroutine, 仅返回第一个执行完成的结果

    当有一个完成时, 将取消其他 coroutine 的执行
    """
    loop = loop or asyncio.get_running_loop()
    tasks: Set[Task] = set()
    finished, result, _future = 0, loop.create_future(), None

    def _done_callback(fut: Future) -> None:
        try:
            fut.result()  # try raise exception
        except CancelledError:
            fut.cancel()

        nonlocal finished, result, _future

        finished += 1

        if _future is None:
            _future = fut

        for task in tasks:
            if task.done() or task.cancelled():
                continue
            task.cancel()

        if finished == len(tasks):
            result.set_result(_future.result())

    for coro in coros:
        task = loop.create_task(coro)
        task.add_done_callback(_done_callback)
        tasks.add(task)

    return result


async def bridge(local: Socket, remote: Socket) -> None:

    if isinstance(local, WebSocket):
        _websocks = local
    elif isinstance(remote, WebSocket):
        _websocks = remote
    else:
        _websocks = None

    async def forward(sender: Socket, receiver: Socket) -> None:
        try:
            while True:
                data = await sender.recv()
                if not data:
                    break
                await receiver.send(data)
                logger.debug(f">=< {data}")
        except WebsocksClosed:  # WebSocket
            await sender.reset()
        except (ConnectionAbortedError, ConnectionResetError):
            pass

    await onlyfirst(forward(local, remote), forward(remote, local))

    if _websocks is None or _websocks.closed:
        return

    if _websocks.status == "CLOSED":
        return

    await _websocks.reset()
    try:
        while True:
            await _websocks.recv()
    except WebsocksClosed:
        pass
