import re
import json
import base64
import random
import asyncio
import typing
import logging

import websockets
from websockets import WebSocketClientProtocol
from socks5.server import Socks5
from socks5.server.sessions import ConnectSession as _ConnectSession

from .types import Socket
from .utils import Singleton
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
            r"(?P<protocol>(ws|wss))://(?P<username>.+?):(?P<password>.+?)@(?P<uri>.+)"
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
                        await sock.close()
                        self._freepool.remove(sock)

                while len(self._freepool) > self.initsize * 2:
                    sock = self._freepool.pop()
                    await sock.close()

        _task = asyncio.get_event_loop().create_task(timed_task())
        _task.add_done_callback(lambda task: self.create_timed_task())

    async def acquire(self) -> WebSocketClientProtocol:
        while True:
            try:
                sock = self._freepool.pop()
                if sock.closed:
                    await sock.close()
                    continue
                if self.initsize > len(self._freepool):
                    asyncio.create_task(self._create())
                return sock
            except KeyError:
                await self._create()

    async def release(self, sock: WebSocketClientProtocol) -> None:
        if not isinstance(sock, websockets.WebSocketClientProtocol):
            return
        if sock.closed:
            await sock.close()
            return
        self._freepool.add(sock)

    async def _create(self) -> None:
        try:
            sock = await websockets.connect(
                self.server, extra_headers={"Authorization": self.get_credentials()}
            )
            self._freepool.add(sock)
        except websockets.exceptions.InvalidStatusCode as e:
            logger.error(str(e))


class Pools(metaclass=Singleton):
    def __init__(self, pools: typing.Sequence[Pool] = []) -> None:
        self.__pools = list(pools)

    def add(self, pool: Pool) -> None:
        self.__pools.append(pool)

    def all(self) -> typing.List[Pool]:
        return self.__pools

    def random(self) -> Pool:
        return random.choice(self.__pools)


OPENED = "OPENED"
CLOSED = "CLOSED"


class WebSocket(Socket):
    def __init__(self, sock: WebSocketClientProtocol, pool: Pool):
        self.pool = pool
        self.sock = sock
        self.status = OPENED

    @classmethod
    async def create_connection(cls, host: str, port: int) -> "WebSocket":
        pool = Pools().random()
        while True:
            try:
                sock = await pool.acquire()
                # websocks shake hand
                await sock.send(json.dumps({"HOST": host, "PORT": port}))
                resp = await sock.recv()
                assert isinstance(resp, str), "must be str"
                if not json.loads(resp)["ALLOW"]:
                    # websocks close
                    await sock.send(json.dumps({"STATUS": "CLOSED"}))
                    while True:
                        msg = await sock.recv()
                        if isinstance(msg, str):
                            break
                    assert json.loads(msg)["STATUS"] == CLOSED

                    raise WebsocksRefused(
                        f"Websocks server can't connect {host}:{port}"
                    )
            except (AssertionError, KeyError):
                raise WebsocksImplementationError()
            except websockets.exceptions.ConnectionClosedError:
                pass
            else:
                break
        return WebSocket(sock, pool)

    async def recv(self, num: int = -1) -> bytes:
        if self.status == CLOSED:
            return b""

        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            self.status = CLOSED
            return b""

        logger.debug(f"<<< {data}")

        if isinstance(data, str):  # websocks
            assert json.loads(data).get("STATUS") == CLOSED
            self.status = CLOSED
            return b""
        return data

    async def send(self, data: bytes) -> int:
        try:
            await self.sock.send(data)
        except websockets.exceptions.ConnectionClosed:
            self.status = CLOSED
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
        return self.status == CLOSED or self.sock.closed


class TCPSocket(Socket):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.r = reader
        self.w = writer

    @classmethod
    async def create_connection(cls, host: str, port: int) -> "TCPSocket":
        """create a TCP socket"""
        r, w = await asyncio.open_connection(host=host, port=port)
        return TCPSocket(r, w)

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
        try:
            await self.w.wait_closed()
        except ConnectionError:
            pass  # nothing to do

    @property
    def closed(self) -> bool:
        return self.w.is_closing()


class ConnectSession(_ConnectSession):
    async def connect_remote(self, host: str, port: int) -> Socket:
        """
        connect remote and return Socket
        """
        need_proxy = rule.judge(host)
        if (need_proxy and get_policy() != "DIRECT") or get_policy() == "PROXY":
            remote = await WebSocket.create_connection(host, port)
        elif need_proxy is None and get_policy() == "AUTO":
            try:
                remote = await asyncio.wait_for(
                    TCPSocket.create_connection(host, port), timeout=2.3
                )
            except (OSError, asyncio.TimeoutError):
                remote = await WebSocket.create_connection(host, port)
                rule.add(host)
        else:
            remote = await TCPSocket.create_connection(host, port)
        return remote


class Client(Socks5):
    def __init__(self, host: str = "0.0.0.0", port: int = 1080) -> None:
        super().__init__(host=host, port=port, connect_session_class=ConnectSession)
