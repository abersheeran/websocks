import json
import time
import base64
import asyncio
import typing
import logging
from hashlib import md5
from random import randint
from socket import AF_INET, AF_INET6, inet_pton, inet_ntop

import aiodns
import websockets
from websockets import WebSocketClientProtocol
from socks5.types import AddressType
from socks5.values import Atyp
from socks5.utils import judge_atyp
from socks5.server import Socks5
from socks5.server.sessions import (
    ConnectSession as _ConnectSession,
    UDPSession as _UDPSession,
)

from .types import Socket
from .config import config, g, TCP, UDP
from .algorithm import AEAD
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


class Pool:
    def __init__(self, server_config: TCP, initsize: int = 7) -> None:
        self.get_credentials = lambda: "Basic " + base64.b64encode(
            f"{server_config.username}:{server_config.password}".encode("utf8")
        ).decode("utf8")
        self.server = server_config.protocol + "://" + server_config.url
        logger.info(
            f"Server: "
            + server_config.protocol
            + "://"
            + server_config.username
            + "@"
            + server_config.url
        )
        self.initsize = initsize
        self._freepool = set()
        self.create_timed_task()

    def create_timed_task(self) -> None:
        """
        定时清理池中的 WebSocket
        """

        async def timed_task() -> None:
            try:
                while True:
                    await asyncio.sleep(7)

                    for sock in tuple(self._freepool):
                        if sock.closed:
                            await sock.close()
                            self._freepool.remove(sock)

                    while len(self._freepool) > self.initsize * 2:
                        sock = self._freepool.pop()
                        await sock.close()

                    while len(self._freepool) < self.initsize:
                        await self._create()
            except IOError:
                pass

        _task = asyncio.get_event_loop().create_task(timed_task())
        _task.add_done_callback(lambda task: self.create_timed_task())

    async def acquire(self) -> WebSocketClientProtocol:
        """
        取出存活的 WebSocket 连接
        """
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
        """
        归还 WebSocket 连接
        """
        if not isinstance(sock, websockets.WebSocketClientProtocol):
            return
        if sock.closed:
            await sock.close()
            return
        self._freepool.add(sock)

    async def _create(self) -> None:
        """
        连接远端服务器
        """
        try:
            sock = await websockets.connect(
                self.server, extra_headers={"Authorization": self.get_credentials()}
            )
            self._freepool.add(sock)
        except websockets.exceptions.InvalidStatusCode as e:
            logger.error(str(e))
        except OSError:
            logger.error(f"IOError in connect {self.server}")


OPENED = "OPENED"
CLOSED = "CLOSED"


class WebSocket(Socket):
    def __init__(self, sock: WebSocketClientProtocol, pool: Pool):
        self.pool = pool
        self.sock = sock
        self.status = OPENED

    @classmethod
    async def create_connection(cls, host: str, port: int) -> "WebSocket":
        pool = g.pool
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


async def get_ipv4(domain: str) -> str:
    """
    获取域名的 DNS A 记录第一个值
    """
    from socket import gaierror

    try:
        _record = await g.resolver.query(domain, "A")
    except aiodns.error.DNSError:
        raise gaierror(11002, "getaddrinfo failed")
    if isinstance(_record, list) and _record:
        record = _record[0]
    else:
        record = _record
    return record.host


class ConnectSession(_ConnectSession):
    async def connect_remote(self, host: str, port: int) -> Socket:
        """
        connect remote and return Socket
        """
        if config.proxy_policy == "CHINA":
            if judge_atyp(host) == Atyp.DOMAIN:
                ipv4 = await get_ipv4(host)
            else:  # 这里暂时不考虑 IPv6 情况
                ipv4 = host
            need_proxy = not (rule.judge(ipv4) is False)
        else:
            need_proxy = rule.judge(host)
        if (
            need_proxy and config.proxy_policy != "DIRECT"
        ) or config.proxy_policy == "PROXY":
            remote = await WebSocket.create_connection(host, port)
        elif need_proxy is None and config.proxy_policy == "AUTO":
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


class UDPSession(_UDPSession):
    def __init__(self, *args, **kwargs) -> None:
        self.algorithm = AEAD[config.udp_server.algorithm](
            md5(
                (config.udp_server.username + config.udp_server.password).encode(
                    "ascii"
                )
            ).hexdigest()
        )
        super().__init__(*args, **kwargs)

    @staticmethod
    def nonce() -> bytes:
        return md5(
            str(int(time.time()) // 1000) + ":" + config.udp_server.password
        ).digest()

    def pack(self, data: bytes, address: AddressType) -> bytes:
        MASKING = b"".join(map(lambda x: randint(0, 255).to_bytes(1, "big"), range(4)))

        ATYP = judge_atyp(address[0])
        if ATYP == Atyp.IPV4:
            DST_ADDR = inet_pton(AF_INET, address[0])
        elif ATYP == Atyp.IPV6:
            DST_ADDR = inet_pton(AF_INET6, address[0])
        elif ATYP == Atyp.DOMAIN:
            DST_ADDR = len(address[0]).to_bytes(1, "big") + address[0].encode("UTF-8")
        ATYP = ATYP.to_bytes(1, "big")
        DST_PORT = address[1].to_bytes(2, "big")

        USERNAME = config.udp_server.username
        ULEN = len(USERNAME)
        USERDATA = ULEN.to_bytes(1, "big") + USERNAME.encode("ascii")

        TARGET_DATA = self.algorithm.encrypt(
            self.nonce(), ATYP + DST_ADDR + DST_PORT + data, None
        )

        DATA = USERDATA + TARGET_DATA

        return MASKING + b"".join(
            map(
                lambda d: (MASKING[d[0] % 4] ^ d[1]).to_bytes(1, "big"), enumerate(DATA)
            ),
        )

    def unpack(self, data: bytes) -> typing.Tuple[bytes, AddressType]:
        MASKING = data[:4]
        DATA = b"".join(
            map(
                lambda d: (MASKING[d[0] % 4] ^ d[1]).to_bytes(1, "big"),
                enumerate(data[4:]),
            ),
        )
        USERNAME = DATA[1 : DATA[0] + 1]
        assert config.udp_server.username == USERNAME
        TARGET_DATA = self.algorithm.encrypt(self.nonce(), DATA[DATA[0] + 1 :], None)
        ATYP = TARGET_DATA[0]
        if ATYP == Atyp.IPV4:
            DST_ADDR = inet_ntop(AF_INET, TARGET_DATA[1:5])
            DST_PORT = int.from_bytes(TARGET_DATA[5:7], "big")
            data = TARGET_DATA[7:]
        elif ATYP == Atyp.IPV6:
            DST_ADDR = inet_ntop(AF_INET6, TARGET_DATA[1:17])
            DST_PORT = int.from_bytes(TARGET_DATA[17:19], "big")
            data = TARGET_DATA[19:]
        elif ATYP == Atyp.DOMAIN:
            DST_ADDR = TARGET_DATA[2 : TARGET_DATA[2] + 2].encode("UTF-8")
            DST_PORT = int.from_bytes(
                TARGET_DATA[TARGET_DATA[2] + 2 : TARGET_DATA[2] + 4], "big"
            )
            data = TARGET_DATA[TARGET_DATA[2] + 4]
        return data, (DST_ADDR, DST_PORT)

    def from_remote(
        self, message: bytes, address: AddressType
    ) -> typing.Tuple[bytes, AddressType]:
        return self.unpack(message)

    def from_local(
        self, message: bytes, address: AddressType
    ) -> typing.Tuple[bytes, AddressType]:
        return self.pack(message, address)


class Client:
    def __init__(self) -> None:
        self.server = Socks5(
            config.host, config.port, connect_session_class=ConnectSession
        )
        g.pool = Pool(config.tcp_server)

    def run(self) -> typing.NoReturn:
        logger.info(f"Proxy Policy: {config.proxy_policy}")
        self.server.run()
