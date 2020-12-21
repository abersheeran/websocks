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
from .exceptions import WebSocksImplementationError, WebSocksRefused
from .utils import onlyfirst, set_proxy, get_proxy
from .config import config, g, TCP
from . import rule


logger: logging.Logger = logging.getLogger("websocks")


class Pool:
    def __init__(self, server_config: TCP, initsize: int = 7) -> None:
        self.get_credentials = lambda: "Basic " + base64.b64encode(
            f"{server_config.username}:{server_config.password}".encode("utf8")
        ).decode("utf8")
        self.server = server_config.protocol + "://" + server_config.url
        logger.info(
            "Remote Server: "
            + server_config.protocol
            + "://"
            + server_config.username
            + "@"
            + server_config.url
        )
        self.initsize = initsize
        self._freepool = set()
        asyncio.get_event_loop().create_task(self.clear_pool())

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


class WebSocket(Socket):
    def __init__(self, sock: WebSocketClientProtocol, pool: Pool):
        self.pool = pool
        self.sock = sock
        self.status = 1

    @classmethod
    async def create_connection(cls, host: str, port: int) -> "WebSocket":
        pool = g.pool
        while True:
            try:
                sock = await pool.acquire()
                # websocks shake hand
                await sock.send(json.dumps({"HOST": host, "PORT": port}))
                resp = await sock.recv()
                if not isinstance(resp, str):
                    raise WebSocksImplementationError()

                if not json.loads(resp)["ALLOW"]:
                    # websocks close
                    await sock.send(json.dumps({"STATUS": "CLOSED"}))
                    while True:
                        msg = await sock.recv()
                        if isinstance(msg, str):
                            break
                    if json.loads(msg)["STATUS"] != "CLOSED":
                        raise WebSocksImplementationError()

                    raise WebSocksRefused(
                        f"WebSocks server can't connect {host}:{port}"
                    )
                return WebSocket(sock, pool)
            except KeyError:
                raise WebSocksImplementationError()
            except websockets.exceptions.ConnectionClosedError:
                pass

    async def recv(self, num: int = -1) -> bytes:
        if self.status == 0:
            return b""

        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            self.status = 0
            return b""

        if isinstance(data, str):  # websocks
            if json.loads(data).get("STATUS") != "CLOSED":
                raise WebSocksImplementationError()
            self.status = 0
            return b""
        return data

    async def send(self, data: bytes) -> int:
        try:
            await self.sock.send(data)
        except websockets.exceptions.ConnectionClosed:
            self.status = 0
            raise ConnectionResetError("Connection closed.")

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
        return self.status == 0 or self.sock.closed


class Client:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 3128,
        nameservers: typing.List[str] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.dns_resolver = aiodns.DNSResolver(nameservers=nameservers)
        if "tcp_server" not in config:
            raise RuntimeError("You need to specify a websocks server.")
        g.pool = Pool(config.tcp_server)

    async def dispatch(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        first_packet = await reader.read(2048)
        for index, data in enumerate(first_packet):
            reader._buffer.insert(index, data)

        if first_packet[0] == 4:  # Socks4
            handler = getattr(self, "socks4")
        elif first_packet[0] == 5:  # Socks5
            handler = getattr(self, "socks5")
        else:  # HTTP
            method = first_packet.split(b" ", maxsplit=1)[0].decode("ascii")
            handler = getattr(self, "http_" + method.lower(), self.http_default)

        try:
            tcp = TCPSocket(reader, writer)
            await handler(tcp)
        finally:
            await tcp.close()

    async def http_default(self, sock: TCPSocket) -> None:
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

        dsthost, dstport = splitport(netloc)
        if dstport is None:
            dstport = {"http": 80, "https": 443}[scheme]

        logger.debug(f"Request HTTP_{capwords(method)} ('{dsthost}', {dstport})")

        try:
            remote = await self.connect_remote(dsthost, int(dstport))
        except asyncio.TimeoutError:
            logger.info(f"HTTP_{capwords(method)} ('{dsthost}', {dstport}) × (timeout)")
        except OSError:
            logger.info(f"HTTP_{capwords(method)} ('{dsthost}', {dstport}) × (general)")
        else:
            logger.info(f"HTTP_{capwords(method)} ('{dsthost}', {dstport}) √")
            for index, data in enumerate(
                (" ".join([method, urlpath, version]) + "\r\n").encode("ascii")
            ):
                sock.r._buffer.insert(index, data)
            await self.bridge(remote, sock)
            await remote.close()

    async def http_connect(self, sock: TCPSocket) -> None:
        async def reply(http_version: str, status_code: HTTPStatus) -> None:
            await sock.send(
                (
                    f"{http_version} {status_code.value} {status_code.phrase}\r\n"
                    "Server: WebSocks created by Aber\r\n"
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
        dsthost, dstport = hostport.split(":")
        logger.debug(f"Request HTTP_Connect ('{dsthost}', {dstport})")

        try:
            remote = await self.connect_remote(dsthost, int(dstport))
        except asyncio.TimeoutError:
            await reply(version, HTTPStatus.GATEWAY_TIMEOUT)
            logger.info(f"HTTP_Connect ('{dsthost}', {dstport}) × (timeout)")
        except OSError:
            await reply(version, HTTPStatus.BAD_GATEWAY)
            logger.info(f"HTTP_Connect ('{dsthost}', {dstport}) × (general)")
        else:
            await reply(version, HTTPStatus.OK)
            logger.info(f"HTTP_Connect ('{dsthost}', {dstport}) √")
            await self.bridge(remote, sock)
            await remote.close()

    async def socks4(self, sock: TCPSocket) -> None:
        data = await sock.recv()
        if data[1] != 1:  # 仅支持 CONNECT 请求
            await sock.send(b"\x00\x91")
            await sock.send(data[2:8])
            return None
        dstport = int.from_bytes(data[2:4], "big")
        dsthost = ".".join([str(i) for i in data[4:8]])
        if sum([i for i in data[4:8]]) == data[7]:  # Socks4A
            while data.count(b"\x00") < 2:
                data += await sock.recv()
            userid, raw_dsthost = data[8:-1].split(b"\x00")
            dsthost = raw_dsthost.decode("ascii")
        logger.debug(f"Request Socks4_Connect ('{dsthost}', {dstport})")

        try:
            remote = await self.connect_remote(dsthost, dstport)
        except Exception:
            await sock.send(b"\x00\x91")
            await sock.send(data[2:8])
            logger.info(f"Socks4_Connect ('{dsthost}', {dstport}) ×")
        else:
            await sock.send(b"\x00\x90")
            await sock.send(data[2:8])
            logger.info(f"Socks4_Connect ('{dsthost}', {dstport}) √")
            await self.bridge(remote, sock)
            await remote.close()

    async def socks5(self, sock: TCPSocket) -> None:
        data = await sock.recv()
        method_count = data[2]
        while len(data) < method_count + 2:
            data += await sock.recv()
        if b"\x00" not in data[2:]:  # 仅允许无身份验证
            await sock.send(b"\x05\xFF")
            return None
        await sock.send(b"\x05\x00")
        data = await sock.recv()
        if data[1] != 1:  # 仅允许 CONNECT 请求
            await sock.send(b"\x05\x07\x00")
            await sock.send(data[3:])
            return
        if data[3] == 1:  # IPv4
            dsthost = ".".join([str(i) for i in data[4:8]])
            dstport = int.from_bytes(data[8:10], "big")
        elif data[3] == 3:  # domain
            dsthost = data[5 : 5 + data[4]].decode("ascii")
            dstport = int.from_bytes(data[5 + data[4] : 5 + data[4] + 2], "big")
        elif data[3] == 4:  # IPv6
            dsthost = ":".join([data[i : i + 2].hex() for i in range(4, 20, 2)])
            dstport = int.from_bytes(data[20:22], "big")
        else:  # 无效的 ATYP
            await sock.send(b"\x05\x08\x00")
            await sock.send(data[3:])
            return
        logger.debug(f"Request Socks5_Connect ('{dsthost}', {dstport})")

        try:
            remote = await self.connect_remote(dsthost, dstport)
        except Exception:
            await sock.send(b"\x05\x01\x00")
            await sock.send(data[3:])
            logger.info(f"Socks5_Connect ('{dsthost}', {dstport}) ×")
        else:
            await sock.send(b"\x05\x00\x00")
            await sock.send(data[3:])
            logger.info(f"Socks5_Connect ('{dsthost}', {dstport}) √")
            await self.bridge(remote, sock)
            await remote.close()

    async def query_ipv4(self, domain: str) -> typing.Optional[str]:
        """
        获取域名的 DNS A 记录
        """
        try:
            _record = await self.dns_resolver.query(domain, "A")
        except aiodns.error.DNSError:
            return None
        if _record == []:
            return None
        if isinstance(_record, list):
            record = _record[0]
        else:
            record = _record
        return record.host

    async def query_ipv6(self, domain: str) -> typing.Optional[str]:
        """
        获取域名 DNS AAAA 记录
        """
        try:
            _record = await self.dns_resolver.query(domain, "AAAA")
        except aiodns.error.DNSError:
            return None
        if _record == []:
            return None
        if isinstance(_record, list) and _record:
            record = _record[0]
        else:
            record = _record
        return record.host

    async def connect_remote(self, host: str, port: int) -> Socket:
        """
        connect remote and return Socket
        """
        try:
            need_proxy = (
                False if ipaddress.ip_address(host).is_private else rule.judge(host)
            )  # 如果 HOST 是 IP 地址且非私有域名则需要查名单
            ip = host
        except ValueError:
            ip = await self.query_ipv4(host) or await self.query_ipv6(host) or host
            # 如果域名既没有解析到 IPv4 也没有 IPv6 则认定需要代理
            need_proxy = True if ip == host else rule.judge(host)

        rule.logger.debug(f"{host} need proxy? {need_proxy}")

        if (
            need_proxy and config.proxy_policy != "DIRECT"
        ) or config.proxy_policy == "PROXY":
            remote = await WebSocket.create_connection(host, port)
        elif need_proxy is None and config.proxy_policy == "AUTO":
            try:
                remote: TCPSocket = await asyncio.wait_for(
                    TCPSocket.create_connection(ip, port), timeout=2.3
                )
                await asyncio.sleep(0.001)
                if remote.closed:  # 存在连接后立刻 reset 的情况
                    raise ConnectionResetError()
            except (OSError, asyncio.TimeoutError):
                remote = await WebSocket.create_connection(host, port)
        else:
            remote = await TCPSocket.create_connection(ip, port)
        return remote

    @staticmethod
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

    async def run_server(self) -> typing.NoReturn:
        logger.info("Used DNS: " + ", ".join(self.dns_resolver.nameservers))
        logger.info("Proxy Policy: " + config.proxy_policy)

        server = await asyncio.start_server(self.dispatch, self.host, self.port)
        server_address = server.sockets[0].getsockname()
        logger.info(f"HTTP/Socks Server serveing on {server_address}")

        _pre_proxy = get_proxy()
        set_proxy(True, f"http://127.0.0.1:{server_address[1]}")
        atexit.register(set_proxy, *_pre_proxy)
        logger.info(f"Seted system proxy: 127.0.0.1:{server_address[1]}")

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
