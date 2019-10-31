import os
import time
import base64
import signal
import asyncio
import typing
import logging
import traceback
import socket
from socket import inet_aton, inet_ntoa, inet_ntop, inet_pton, AF_INET6

import websockets

from .utils import (
    TCPSocket,
    bridge,
    create_connection,
    connect_server
)
from .exceptions import WebsocksRefused

from . import rule

DIRECT = "Direct"
PROXY = "Proxy"

logger: logging.Logger = logging.getLogger("websocks")


def get_credentials() -> str:
    username = os.environ['WEBSOCKS_USER']
    password = os.environ['WEBSOCKS_PASS']
    return "Basic " + base64.b64encode(f"{username}:{password}".encode("utf8")).decode("utf8")


class Pool:

    def __init__(self, initsize: int = 7) -> None:
        self.initsize = initsize
        self._freepool = set()
        asyncio.get_event_loop().create_task(
            self.init(initsize)
        )
        self.timed_task()

    async def init(self, size: int) -> None:
        await asyncio.gather(*[self._create() for _ in range(size)])

    def timed_task(self) -> None:

        async def _timed_task() -> None:
            while True:
                await asyncio.sleep(7)

                for sock in tuple(self._freepool):
                    if sock.closed:
                        self._freepool.remove(sock)

                while len(self._freepool) > self.initsize * 2:
                    sock = self._freepool.pop()
                    await sock.close()

        asyncio.get_event_loop().create_task(_timed_task())

    async def acquire(self) -> websockets.WebSocketClientProtocol:
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

    async def release(self, sock: websockets.WebSocketClientProtocol) -> None:
        if isinstance(sock, websockets.WebSocketClientProtocol):
            if sock.closed:
                return
            self._freepool.add(sock)

    async def _create(self):
        sock = await websockets.connect(
            os.environ['WEBSOCKS_SERVER'],
            extra_headers={
                "Proxy-Authorization": get_credentials()
            }
        )
        self._freepool.add(sock)


class Socks5Error(Exception):
    pass


class AuthenticationError(Socks5Error):
    pass


# Empty byte
EMPTY = b''
# Response Type
SUCCEEDED = 0
GENERAL_SOCKS_SERVER_FAILURE = 1
CONNECTION_NOT_ALLOWED_BY_RULESET = 2
NETWORK_UNREACHABLE = 3
HOST_UNREACHABLE = 4
CONNECTION_REFUSED = 5
TTL_EXPIRED = 6
COMMAND_NOT_SUPPORTED = 7
ADDRESS_TYPE_NOT_SUPPORTED = 8


class BaseAuthentication:

    def __init__(self, socket: TCPSocket):
        self.socket = socket

    def getMethod(self, methods: set) -> int:
        """
        Return a allowed authentication method or 255
        Must be overwrited.
        """
        return 255

    async def authenticate(self):
        """
        Authenticate user
        Must be overwrited.
        """
        raise AuthenticationError()


class NoAuthentication(BaseAuthentication):
    """ NO AUTHENTICATION REQUIRED """

    def getMethod(self, methods: set) -> int:
        if 0 in methods:
            return 0
        return 255

    async def authenticate(self):
        pass


class PasswordAuthentication(BaseAuthentication):
    """ USERNAME/PASSWORD """

    def _getUser(self) -> dict:
        return {"abersheeran": "password"}

    def getMethod(self, methods: set) -> int:
        if 2 in methods:
            return 2
        return 255

    async def authenticate(self):
        VER = await self.socket.recv(1)
        if VER != b'\x01':
            await self.socket.send(b"\x01\x01")
            raise Socks5Error("Unsupported version!")
        ULEN = int.from_bytes(await self.socket.recv(1), 'big')
        UNAME = (await self.socket.recv(ULEN)).decode("ASCII")
        PLEN = int.from_bytes(await self.socket.recv(1), 'big')
        PASSWD = (await self.socket.recv(PLEN)).decode("ASCII")
        if self._getUser().get(UNAME) and self._getUser().get(UNAME) == PASSWD:
            await self.socket.send(b"\x01\x00")
        else:
            await self.socket.send(b"\x01\x01")
            raise AuthenticationError("USERNAME or PASSWORD ERROR")


class Socks5Server:
    """A socks5 server"""

    Authentication = NoAuthentication

    def __init__(self, host: str = "0.0.0.0", port: int = 3128) -> None:
        self.host = host
        self.port = port
        self.pool = Pool()

    async def dispatch(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sock = TCPSocket(reader, writer)
        authentication = self.Authentication(sock)
        try:
            data = await sock.recv(2)
            VER, NMETHODS = data
            if VER != 5:
                await sock.send(b"\x05\xff")
                raise Socks5Error("Unsupported version!")
            METHODS = set(await sock.recv(NMETHODS))
            METHOD = authentication.getMethod(METHODS)
            reply = b'\x05' + METHOD.to_bytes(1, 'big')
            await sock.send(reply)
            if METHOD == 255:
                raise Socks5Error("No methods available")
            await authentication.authenticate()
            data = await sock.recv(4)
            VER, CMD, RSV, ATYP = data
            if VER != 5:
                await sock.send(self.reply(GENERAL_SOCKS_SERVER_FAILURE))
                raise Socks5Error("Unsupported version!")
            # Parse target address
            if ATYP == 1:  # IPV4
                ipv4 = await sock.recv(4)
                DST_ADDR = inet_ntoa(ipv4)
            elif ATYP == 3:  # Domain
                addr_len = int.from_bytes(await sock.recv(1), byteorder='big')
                DST_ADDR = (await sock.recv(addr_len)).decode()
            elif ATYP == 4:  # IPV6
                ipv6 = await sock.recv(16)
                DST_ADDR = inet_ntop(AF_INET6, ipv6)
            else:
                await sock.send(self.reply(ADDRESS_TYPE_NOT_SUPPORTED))
                raise Socks5Error(f"Unsupported ATYP value: {ATYP}")
            DST_PORT = int.from_bytes(await sock.recv(2), 'big')
            if CMD == 1:
                await self.socks5_connect(sock, DST_ADDR, DST_PORT)
            elif CMD == 2:
                await self.socks5_bind(sock, DST_ADDR, DST_PORT)
            elif CMD == 3:
                await self.socks5_udp_associate(sock, DST_ADDR, DST_PORT)
            else:
                await sock.send(self.reply(COMMAND_NOT_SUPPORTED))
                raise Socks5Error(f"Unsupported CMD value: {CMD}")
        except Socks5Error as e:
            logger.warning(str(e))
        except (
            ConnectionResetError,
            ConnectionAbortedError
        ):
            logger.error(f"Unknown Error: ")
            traceback.print_exc()
        finally:
            await sock.close()

    @staticmethod
    def reply(REP: int, IP: str = "127.0.0.1", port: int = 1080) -> bytes:
        """构造响应值"""
        VER, RSV = b'\x05', b'\x00'
        try:
            BND_ADDR = inet_aton(IP)
            ATYP = 1
        except OSError:
            try:
                BND_ADDR = inet_pton(AF_INET6, IP)
                ATYP = 4
            except OSError:
                BND_ADDR = len(IP).to_bytes(2, 'big') + IP.encode("UTF-8")
                ATYP = 3
        REP = REP.to_bytes(1, 'big')
        ATYP = ATYP.to_bytes(1, 'big')
        BND_PORT = int(port).to_bytes(2, 'big')
        return VER + REP + RSV + ATYP + BND_ADDR + BND_PORT

    async def socks5_connect(self, sock: TCPSocket, addr: str, port: int):
        try:
            start_time = time.time()
            need_proxy = rule.judge(addr)
            if need_proxy:
                _remote = await self.pool.acquire()
                remote = await connect_server(_remote, addr, port)
                remote_type = PROXY
            elif need_proxy is None:
                try:
                    remote = await asyncio.wait_for(
                        create_connection(addr, port),
                        timeout=2.3
                    )
                    remote_type = DIRECT
                except (asyncio.TimeoutError, socket.gaierror):
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

            await sock.send(self.reply(SUCCEEDED))
        except WebsocksRefused:
            await sock.send(self.reply(CONNECTION_REFUSED))
            logger.error(f"Proxy Refused: {addr}:{port}")
        except socket.gaierror:
            await sock.send(self.reply(CONNECTION_REFUSED))
            logger.error(f"Network error: Can't connect to {addr}:{port}")
        except Exception:
            await sock.send(self.reply(GENERAL_SOCKS_SERVER_FAILURE, addr, port))
            logger.error(f"Unknown Error: ")
            traceback.print_exc()
        else:
            # forward data
            await bridge(sock, remote)

            if remote_type == PROXY:
                await self.pool.release(remote.sock)
            elif remote_type == DIRECT:
                await remote.close()

    async def socks5_bind(self, sock: TCPSocket, addr: str, port: int):
        """ 不支持 bind """
        await sock.send(self.reply(GENERAL_SOCKS_SERVER_FAILURE, addr, port))

    async def socks5_udp_associate(self, sock: TCPSocket, addr: str, port: int):
        """ 不支持 UDP """
        await sock.send(self.reply(GENERAL_SOCKS_SERVER_FAILURE, addr, port))

    async def run_server(self) -> typing.NoReturn:
        server = await asyncio.start_server(
            self.dispatch, self.host, self.port
        )
        logger.info(f"Socks5 Server serving on {server.sockets[0].getsockname()}")

        def termina(signo, frame):
            logger.info(f"Socks5 Server has closed.")
            raise SystemExit(0)

        signal.signal(signal.SIGINT, termina)
        signal.signal(signal.SIGTERM, termina)

        while True:
            await asyncio.sleep(1)

    def run(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.run_server())
        loop.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    Socks5Server().run()
