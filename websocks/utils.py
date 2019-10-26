import typing
import asyncio
import logging

import websockets

from .types import Socket


logger: logging.Logger = logging.getLogger("websocks")


class TCPSocket(Socket):

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.r = reader
        self.w = writer

    async def recv(self) -> bytes:
        data = await self.r.read(4096)
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

    def __init__(self, sock: websockets.WebSocketCommonProtocol):
        self.sock = sock

    async def recv(self) -> bytes:
        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError('Websocket closed.')
        logger.debug(f"<<< {data}")
        if isinstance(data, str):
            raise TypeError()
        return data

    async def send(self, data: bytes) -> int:
        try:
            await self.sock.send(data)
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError('Websocket closed.')
        logger.debug(f">>> {data}")
        return len(data)

    async def close(self) -> None:
        await self.sock.close()

    @property
    def closed(self) -> bool:
        return self.sock.closed


async def create_connection(host: str, port: int) -> TCPSocket:
    """create a TCP socket"""
    r, w = await asyncio.open_connection(host=host, port=port)
    return TCPSocket(r, w)


async def bridge(local: Socket, remote: Socket) -> None:

    alive = True

    async def b(sender: Socket, receiver: Socket) -> None:
        nonlocal alive
        try:
            while alive:
                data = await sender.recv()
                if not data:
                    break
                await receiver.send(data)
                logger.debug(f">=< {data}")
        except TypeError:
            await sender.close()
        except (
            ConnectionAbortedError,
            ConnectionResetError
        ):
            pass

        alive = False

    task_0 = asyncio.run_coroutine_threadsafe(
        b(remote, local),
        asyncio.get_event_loop()
    )
    task_1 = asyncio.run_coroutine_threadsafe(
        b(local, remote),
        asyncio.get_event_loop()
    )
    while alive:
        await asyncio.sleep(0.7)

    task_0.cancel()
    task_1.cancel()

    while task_0.cancelled:
        await asyncio.sleep(0.5)

    while task_1.cancelled:
        await asyncio.sleep(0.5)
