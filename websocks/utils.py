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
        return data

    async def send(self, data: bytes) -> int:
        self.w.write(data)
        await self.w.drain()
        return len(data)

    async def close(self):
        self.w.close()


class WebSocket(Socket):

    def __init__(self, sock: websockets.WebSocketCommonProtocol):
        self.sock = sock

    async def recv(self) -> bytes:
        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError('Websocket closed.')
        logger.debug(f"<<< {data}")
        return data

    async def send(self, data: bytes) -> int:
        try:
            await self.sock.send(data)
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError('Websocket closed.')
        logger.debug(f">>> {data}")
        return len(data)

    async def close(self):
        await self.sock.close()


async def create_connection(host: str, port: int) -> TCPSocket:
    """create a TCP socket"""
    r, w = await asyncio.open_connection(host=host, port=port)
    return TCPSocket(r, w)


async def connect_server(url: int, headers: typing.Mapping[str, str]) -> WebSocket:
    """connect to  websocket server"""
    sock = await websockets.connect(url, extra_headers=headers)
    return WebSocket(sock)


async def bridge(local: Socket, remote: Socket) -> None:

    async def _s(sender: Socket, receiver: Socket) -> None:
        try:
            while True:
                data = await sender.recv()
                if not data:
                    raise ConnectionResetError("")
                await receiver.send(data)
                logger.debug(f">=< {data}")
        except ConnectionResetError:
            await sender.close()
            await receiver.close()

    await asyncio.gather(
        _s(remote, local),
        _s(local, remote)
    )
