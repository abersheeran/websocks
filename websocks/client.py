import json
import base64
import asyncio
import typing
import logging
import signal
import atexit
import ipaddress
from string import capwords
from http import HTTPStatus
from urllib.parse import splitport

import aiodns
import websockets
from websockets import WebSocketClientProtocol

from .types import Socket
from .socket import TCPSocket
from .utils import onlyfirst, create_task, set_proxy, get_proxy
from .config import config, g, TCP
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
            "Server: "
            + server_config.protocol
            + "://"
            + server_config.username
            + "@"
            + server_config.url
        )
        self.initsize = initsize
        self._freepool = set()
        create_task(asyncio.get_event_loop(), self.clear_pool())

    async def clear_pool(self) -> None:
        """
        定时清理池中的 WebSocket
        """
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
                assert isinstance(resp, str)
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

        # logger.debug(f"<<< {data}")

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
        # logger.debug(f">>> {data}")
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


async def query_ipv4(domain: str) -> typing.Optional[str]:
    """
    获取域名的 DNS A 记录
    """
    try:
        _record = await g.resolver.query(domain, "A")
    except aiodns.error.DNSError:
        return None
    if isinstance(_record, list) and _record:
        record = _record[0]
    else:
        record = _record
    return record.host


async def query_ipv6(domain: str) -> typing.Optional[str]:
    """
    获取域名 DNS AAAA 记录
    """
    try:
        _record = await g.resolver.query(domain, "AAAA")
    except aiodns.error.DNSError:
        return None
    if isinstance(_record, list) and _record:
        record = _record[0]
    else:
        record = _record
    return record.host


async def connect_remote(host: str, port: int) -> Socket:
    """
    connect remote and return Socket
    """

    try:
        ip = host
        need_proxy = (
            False if ipaddress.ip_address(host).is_private else rule.judge(host)
        )
    except ValueError:
        ip = await query_ipv4(host) or await query_ipv6(host) or host
        need_proxy = rule.judge(host)

    rule.logger.debug(f"{host} need proxy? {need_proxy}")

    if (
        need_proxy and config.proxy_policy != "DIRECT"
    ) or config.proxy_policy == "PROXY":
        remote = await WebSocket.create_connection(host, port)
    elif need_proxy is None and config.proxy_policy == "AUTO":
        try:
            remote = await asyncio.wait_for(
                TCPSocket.create_connection(ip, port), timeout=2.3
            )
        except (OSError, asyncio.TimeoutError):
            remote = await WebSocket.create_connection(host, port)
    else:
        remote = await TCPSocket.create_connection(ip, port)
    return remote


async def bridge(s0: Socket, s1: Socket) -> None:
    async def _(sender: Socket, receiver: Socket):
        try:
            while True:
                data = await sender.recv(8192)
                if not data:
                    break
                await receiver.send(data)
        except OSError:
            pass

    await onlyfirst(_(s0, s1), _(s1, s0))


class Client:
    def __init__(self, host: str = "0.0.0.0", port: int = 3128) -> None:
        self.host = host
        self.port = port
        if "tcp_server" not in config:
            raise RuntimeError("You need to specify a websocks server.")
        g.pool = Pool(config.tcp_server)

    async def dispatch(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        firstline = await reader.readline()
        for index, data in enumerate(firstline):
            reader._buffer.insert(index, data)
        method = firstline.decode("ascii").split(" ", maxsplit=1)[0]
        sock = TCPSocket(reader, writer)
        try:
            await getattr(self, method.lower(), self.default)(sock)
        finally:
            await sock.close()

    async def default(self, sock: TCPSocket) -> None:
        firstline = await sock.r.readline()
        if firstline == b"":
            return

        method, url, version = firstline.decode("ascii").strip().split(" ")

        scheme = url.split("://")[0]
        if "/" in url.split("://")[1]:
            netloc, urlpath = url.split("://")[1].split("/", 1)
        else:
            netloc = url.split("://")[1]
            urlpath = ""
        urlpath = "/" + urlpath

        host, port = splitport(netloc)
        if port is None:
            port = {"http": 80, "https": 443}[scheme]

        logger.info(f"{capwords(method)} request to ('{host}', {port})")
        try:
            remote = await connect_remote(host, int(port))
        except Exception:
            return

        for index, data in enumerate(
            (" ".join([method, urlpath, version]) + "\r\n").encode("ascii")
        ):
            sock.r._buffer.insert(index, data)
        await bridge(remote, sock)
        await remote.close()

    async def connect(self, sock: TCPSocket) -> None:
        async def reply(http_version: str, status_code: HTTPStatus) -> None:
            await sock.send(
                (
                    f"{http_version} {status_code.value} {status_code.phrase}\r\n"
                    "Server: O-O\r\n"
                    "Content-Length: 0\r\n"
                    "\r\n"
                ).encode("ascii")
            )

        # parse HTTP CONNECT
        raw_request = b""
        while True:
            raw_request += await sock.recv(8192)
            if raw_request.endswith(b"\r\n\r\n"):
                break
        method, hostport, version = (
            raw_request.splitlines()[0].decode("ascii").split(" ")
        )
        host, port = hostport.split(":")
        logger.info(f"Connect request to ('{host}', {port})")

        try:
            remote = await connect_remote(host, int(port))
        except asyncio.TimeoutError:
            await reply(version, HTTPStatus.GATEWAY_TIMEOUT)
        except OSError:
            await reply(version, HTTPStatus.BAD_GATEWAY)
        else:
            await reply(version, HTTPStatus.OK)
            await bridge(remote, sock)
            await remote.close()

    async def run_server(self) -> typing.NoReturn:
        server = await asyncio.start_server(self.dispatch, self.host, self.port)

        _pre_proxy = get_proxy()
        set_proxy(True, f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
        atexit.register(set_proxy, *_pre_proxy)

        logger.info(f"Proxy Policy: {config.proxy_policy}")
        logger.info(f"HTTP Server serveing on {server.sockets[0].getsockname()}")
        logger.info(
            f"Seted system proxy: http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        )

        def termina(signo, frame):
            server.close()
            logger.info("HTTP Server has closed.")
            raise SystemExit(0)

        signal.signal(signal.SIGINT, termina)
        signal.signal(signal.SIGTERM, termina)

        while True:
            await asyncio.sleep(1)

    def run(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.run_server())
        loop.stop()
