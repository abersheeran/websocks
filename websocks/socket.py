from __future__ import annotations

import asyncio
from socket import socket as RawSocket

from .types import Socket


class TCPSocket(Socket):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.r = reader
        self.w = writer
        self.__socket = writer.get_extra_info("socket")

    @classmethod
    async def create_connection(cls, host: str, port: int) -> TCPSocket:
        """create a TCP socket"""
        r, w = await asyncio.open_connection(host=host, port=port)
        return TCPSocket(r, w)

    @property
    def socket(self) -> RawSocket:
        return self.__socket

    async def recv(self, num: int = 4096) -> bytes:
        data = await self.r.read(num)
        return data

    async def send(self, data: bytes) -> int:
        self.w.write(data)
        await self.w.drain()
        return len(data)

    async def close(self) -> None:
        self.w.close()
        try:
            await self.w.wait_closed()
        except ConnectionError:
            pass  # nothing to do

    @property
    def closed(self) -> bool:
        return self.w.is_closing()

    def __del__(self):
        self.w.close()
