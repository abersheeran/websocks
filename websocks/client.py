import os
import re
import time
import base64
import socket
import signal
import random
import asyncio
import typing
import logging
import traceback
from functools import partial

import websockets
from websockets import WebSocketClientProtocol
from socks5.server.core import ConnectSession as _ConnectSession, Socks5
from socks5.utils import judge_atyp
from socks5.types import Socket

from .utils import Singleton, onlyfirst
from . import rule


logger: logging.Logger = logging.getLogger("websocks")


class WebsocksError(Exception):
    pass


class WebsocksImplementationError(WebsocksError):
    pass


class WebsocksClosed(ConnectionResetError):
    pass


class WebsocksRefused(ConnectionRefusedError):
    pass


################################################
# POLICY
################################################


__policy__ = "AUTO"


def set_policy(policy: str) -> None:
    global __policy__
    __policy__ = policy


def get_policy() -> str:
    return __policy__


################################################
# WEBSOCKET POOL
################################################


class ServerURL:
    def __init__(self, server_url: str) -> None:
        url_format = re.compile(
            r"(?P<protocol>(ws|wss))://(?P<username>.+?):(?P<password>.+?)@(?P<uri>.+?)"
        )
        match = url_format.match(server_url)
        self.protocol = match.group("protocol")
        self.username = match.group("username")
        self.password = match.group("password")
        self.uri = match.group("uri")

    def __str__(self) -> str:
        return f"{self.protocol}://{self.uri}"

    def __repr__(self) -> str:
        return self.__str__()


class Pool:
    def __init__(self, server: str, initsize: int = 7) -> None:
        server_url = ServerURL(server)
        self.get_credentials = lambda: "Basic " + base64.b64encode(
            f"{server_url.username}:{server_url.password}".encode("utf8")
        ).decode("utf8")
        self.server = str(server_url)

        self.initsize = initsize
        self._freepool = set()
        self.init(initsize)
        self.create_timed_task()

    def init(self, size: int) -> None:
        """初始化 Socket 池"""
        for _ in range(size):
            asyncio.get_event_loop().create_task(self._create())

    def create_timed_task(self) -> None:
        """定时清理池中的 Socket"""

        async def timed_task() -> None:
            while True:
                await asyncio.sleep(7)

                for sock in tuple(self._freepool):
                    if sock.closed:
                        self._freepool.remove(sock)

                while len(self._freepool) > self.initsize * 2:
                    sock = self._freepool.pop()
                    await sock.close()

        asyncio.get_event_loop().create_task(timed_task())

    async def acquire(self) -> WebSocketClientProtocol:
        while True:
            try:
                sock = self._freepool.pop()
                if sock.closed:
                    continue
                if self.initsize > len(self._freepool):
                    asyncio.create_task(self._create())
                return sock
            except KeyError:
                await self._create()

    async def release(self, sock: WebSocketClientProtocol) -> None:
        if isinstance(sock, websockets.WebSocketClientProtocol):
            if sock.closed:
                return
            self._freepool.add(sock)

    async def _create(self) -> None:
        sock = await websockets.connect(
            self.server, extra_headers={"Authorization": self.get_credentials()}
        )
        self._freepool.add(sock)


class Pools(metaclass=Singleton):
    def __init__(self, pools: typing.Sequence[Pool]) -> None:
        self.__pools = list(pools)

    def add(self, pool: Pool) -> None:
        self.__pools.append(pool)

    def all(self) -> typing.List[Pool]:
        return self.__pools

    def random(self) -> Pool:
        return random.choice(self.__pools)


class WebSocket(Socket):
    def __init__(self, sock: WebSocketClientProtocol, pool: Pool):
        self.pool = pool
        self.sock = sock
        self.status = "OPEN"

    @classmethod
    def create_connection(self) -> WebSocket:
        pool = Pools().random()
        _websocket = await pool.acquire()
        return WebSocket(_websocket, pool)

    async def recv(self, num: int = -1) -> bytes:
        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            self.status = "CLOSED"
            raise ConnectionResetError("Connection closed.")
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
            self.status = "CLOSED"
            raise ConnectionResetError("Connection closed.")
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

        await self.pool.release(self.sock)

    @property
    def closed(self) -> bool:
        return self.status == "CLOSED" or self.sock.closed


class ConnectSession(_ConnectSession):
    async def connect_remote(self, host: str, port: int) -> Socket:
        """
        connect remote and return Socket
        """
        start_time = time.time()
        need_proxy = rule.judge(addr)
        if need_proxy or self.policy == "PROXY":
            _remote = await self.pool.acquire()
            remote = await connect_server(_remote, addr, port)
            remote_type = PROXY
        elif need_proxy is None and self.policy == "AUTO":
            try:
                remote = await asyncio.wait_for(
                    create_connection(addr, port), timeout=2.3
                )
                remote_type = DIRECT
            except (
                OSError,
                ConnectionError,
                asyncio.TimeoutError,
            ):
                try:
                    _remote = await self.pool.acquire()
                    remote = await connect_server(_remote, addr, port)
                except websockets.exceptions.ConnectionClosed:
                    _remote = await self.pool.acquire()
                    remote = await connect_server(_remote, addr, port)
                remote_type = PROXY
                rule.add(addr)
        else:
            remote = await create_connection(addr, port)
            remote_type = DIRECT

        end_time = time.time()
        logger.info(f"{end_time - start_time:02.3f} {remote_type}: {addr}:{port}")


Client = partial(Socks5, connect_session_class=ConnectSession)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    Client().run()
