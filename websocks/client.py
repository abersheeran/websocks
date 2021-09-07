from __future__ import annotations

import sys
import json
import base64
import asyncio
import typing
import logging
import ipaddress
from string import capwords
from http import HTTPStatus
from urllib.parse import splitport

if sys.version_info[:2] < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal

import aiodns
import h11
import websockets
from websockets import WebSocketClientProtocol

from .types import Socket
from .socket import TCPSocket
from .exceptions import WebSocksImplementationError, WebSocksRefused
from .utils import onlyfirst
from .config import convert_tcp_url, TCP
from . import rule

logger: logging.Logger = logging.getLogger(__name__)


class Pool:
    def __init__(self, server_config: TCP, init_size: int = 7) -> None:
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
        self.init_size = init_size
        self._free_pool = set()
        asyncio.get_event_loop().create_task(self.clear_pool())

    async def clear_pool(self) -> None:
        """
        定时清理池中的 WebSocket
        """
        while True:
            await asyncio.sleep(7)

            for sock in tuple(self._free_pool):
                if sock.closed:
                    await sock.close()
                    self._free_pool.remove(sock)

            while len(self._free_pool) > self.init_size * 2:
                sock = self._free_pool.pop()
                await sock.close()

            while len(self._free_pool) < self.init_size:
                await self._create()

    async def acquire(self) -> WebSocketClientProtocol:
        """
        取出存活的 WebSocket 连接
        """
        while True:
            try:
                sock = self._free_pool.pop()
                if sock.closed:
                    await sock.close()
                    continue
                if self.init_size > len(self._free_pool):
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
        self._free_pool.add(sock)

    async def _create(self) -> None:
        """
        连接远端服务器
        """
        try:
            sock = await websockets.connect(
                self.server, extra_headers={"Authorization": self.get_credentials()}
            )
            self._free_pool.add(sock)
        except websockets.exceptions.InvalidStatusCode as e:
            logger.error(str(e))
        except IOError:
            logger.error(f"IOError in connect {self.server}")


class WebSocket(Socket):
    pool: Pool

    def __init__(self, sock: WebSocketClientProtocol):
        self.sock = sock
        self.status = 1

    @classmethod
    async def create_connection(cls, host: str, port: int) -> WebSocket:
        pool = cls.pool
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
                return WebSocket(sock)
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
        client_host: str,
        client_port: int,
        tcp_server: str,
        nameservers: typing.List[str] = None,
        proxy_policy: Literal["AUTO", "PROXY", "DIRECT", "BLACK", "WHITE"] = "AUTO",
    ) -> None:
        self.host = client_host
        self.port = client_port
        self.dns_resolver = aiodns.DNSResolver(nameservers=nameservers)
        self.proxy_policy = proxy_policy

        WebSocket.pool = Pool(TCP(**convert_tcp_url(tcp_server)))

    async def dispatch(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        first_packet = await reader.read(2048)
        for index, data in enumerate(first_packet):
            reader._buffer.insert(index, data)

        if not first_packet:
            writer.close()
            await writer.wait_closed()
            return
        elif first_packet[0] == 4:  # Socks4
            handler = getattr(self, "socks4")
        elif first_packet[0] == 5:  # Socks5
            handler = getattr(self, "socks5")
        else:  # HTTP
            try:
                method = first_packet.split(b" ", maxsplit=1)[0].decode("ascii")
            except UnicodeDecodeError:
                return await TCPSocket(reader, writer).close()
            handler = getattr(self, "http_" + method.lower(), self.http_default)

        try:
            tcp = TCPSocket(reader, writer)
            await handler(tcp)
        except ConnectionError:
            pass
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
            proxy_or_direct = "PROXY" if self.is_proxyed(remote) else "DIRECT"
            logger.info(
                f"HTTP_{capwords(method)} ('{dsthost}', {dstport}) {proxy_or_direct} √"
            )
            for index, data in enumerate(firstline):
                sock.r._buffer.insert(index, data)

            server = h11.Connection(our_role=h11.SERVER)
            client = h11.Connection(our_role=h11.CLIENT)
            try:

                async def server_task():
                    while True:
                        event = server.next_event()
                        logger.debug(f"HTTP Proxy Server: {event}")
                        if event is h11.NEED_DATA:
                            server.receive_data(await sock.recv())
                            continue
                        elif type(event) is h11.Request:
                            event.target = (
                                b"/"
                                + event.target.split(b"://", maxsplit=1)[1].split(
                                    b"/", maxsplit=1
                                )[1]
                            )
                            await remote.send(client.send(event))
                        elif type(event) is h11.Data:
                            await remote.send(client.send(event))
                        elif type(event) in (h11.EndOfMessage, h11.ConnectionClosed):
                            await remote.send(client.send(h11.EndOfMessage()))
                            break
                        else:
                            break

                async def client_task():
                    while True:
                        event = client.next_event()
                        logger.debug(f"HTTP Proxy Client: {event}")
                        if event is h11.NEED_DATA:
                            client.receive_data(await remote.recv())
                            continue
                        elif type(event) in (h11.Response, h11.Data):
                            await sock.send(server.send(event))
                        elif type(event) in (h11.EndOfMessage, h11.ConnectionClosed):
                            await sock.send(server.send(h11.EndOfMessage()))
                            break
                        else:
                            break

                await asyncio.gather(server_task(), client_task(), return_exceptions=True)
            finally:
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
            proxy_or_direct = "PROXY" if self.is_proxyed(remote) else "DIRECT"
            logger.info(f"HTTP_Connect ('{dsthost}', {dstport}) {proxy_or_direct} √")
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
            proxy_or_direct = "PROXY" if self.is_proxyed(remote) else "DIRECT"
            logger.info(f"Socks4_Connect ('{dsthost}', {dstport}) {proxy_or_direct} √")
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
            proxy_or_direct = "PROXY" if self.is_proxyed(remote) else "DIRECT"
            logger.info(f"Socks5_Connect ('{dsthost}', {dstport}) {proxy_or_direct} √")
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
        if self.proxy_policy not in ("PROXY", "DIRECT"):
            try:
                need_proxy = (
                    False if ipaddress.ip_address(host).is_private else rule.judge(host)
                )  # 如果 HOST 是 IP 地址且非私有域名则需要查名单
                ip = host
            except ValueError:
                ip = await self.query_ipv4(host) or await self.query_ipv6(host) or host
                # 如果域名既没有解析到 IPv4 也没有 IPv6 则认定需要代理
                need_proxy = True if ip == host else rule.judge(host)
            # 黑名单代理策略时: 未知均不代理
            # 白名单代理策略时: 未知均需代理
            if self.proxy_policy in ("BLACK", "WHITE"):
                need_proxy = (
                    self.proxy_policy == "WHITE" if need_proxy is None else need_proxy
                )
        else:
            need_proxy = self.proxy_policy == "PROXY"

        rule.logger.debug(f"{host} need proxy? {need_proxy}")

        if need_proxy:
            remote = await WebSocket.create_connection(host, port)
        elif need_proxy is None:
            try:
                remote: Socket = await asyncio.wait_for(
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

    def is_proxyed(self, connection: Socket) -> bool:
        return isinstance(connection, WebSocket)

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
        logger.info("Proxy Policy: " + self.proxy_policy)

        server = await asyncio.start_server(self.dispatch, self.host, self.port)
        server_address = server.sockets[0].getsockname()
        logger.info(f"HTTP/Socks Server serving on {server_address}")
        await server.serve_forever()

    def run(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.run_server())
        loop.stop()
