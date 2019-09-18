import sys
import time
import json
import socket
import asyncio
import typing
import logging
import logging.config
import threading

import websockets
from websockets import WebSocketClientProtocol

logger: logging.Logger = logging.getLogger("websocks")

# use IOCP in windows
if sys.platform == 'win32' and (sys.version_info.major >= 3 and sys.version_info.minor >= 7):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
# try to use uvloop
try:
    import uvloop
    uvloop.install()
except ImportError:
    pass


#########################
# Error
#########################

class Socks5Error(Exception):
    pass


class WebSocksError(Exception):
    pass


class AuthenticationError(Socks5Error):
    pass


NetworkError = (
    TimeoutError,
    ConnectionError,
    ConnectionAbortedError,
    ConnectionRefusedError,
    ConnectionResetError,
    socket.error
)

#########################
# Constant
#########################

# Empty byte
EMPTY = b''
# Socks5 Response Type
SUCCEEDED = 0
GENERAL_SOCKS_SERVER_FAILURE = 1
CONNECTION_NOT_ALLOWED_BY_RULESET = 2
NETWORK_UNREACHABLE = 3
HOST_UNREACHABLE = 4
CONNECTION_REFUSED = 5
TTL_EXPIRED = 6
COMMAND_NOT_SUPPORTED = 7
ADDRESS_TYPE_NOT_SUPPORTED = 8

#########################
# Client
#########################


class Socket:

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.r = reader
        self.w = writer
        self.__socket = writer.get_extra_info('socket')
        self.__address = writer.get_extra_info('peername')

    @property
    def address(self):
        return self.__address

    @property
    def socket(self):
        return self.__socket

    async def recv(self, num: int) -> bytes:
        data = await self.r.read(num)
        return data

    async def send(self, data: bytes) -> int:
        self.w.write(data)
        await self.w.drain()
        return len(data)

    def close(self):
        self.w.close()


class WebsocksClient:

    def __init__(self, sock: WebSocketClientProtocol):
        self.sock = sock
        self.IPV4 = None
        self.IPV6 = None
        self.TCP = None
        self.UDP = None

    async def recv(self, num: int = 0) -> bytes:
        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError('Websocket closed.')
        logger.debug(f"<<< {data}")
        return data

    async def send(self, data: websockets.typing.Data) -> int:
        try:
            await self.sock.send(data)
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError('Websocket closed.')
        logger.debug(f">>> {data}")
        return len(data)

    def close(self) -> None:
        asyncio.run_coroutine_threadsafe(
            self.sock.close(),
            asyncio.get_event_loop()
        )

    async def negotiate(self, username: str, password: str, host: str, port: int, CMD: str = "TCP") -> bool:
        await self.send(json.dumps({
            "VERSION": 1,
            "USERNAME": username,
            "PASSWORD": password
        }))

        data = json.loads(await self.recv())
        try:
            self.IPV4 = data["IPV4"]
            self.IPV6 = data["IPV6"]
            self.TCP = data["TCP"]
            self.UDP = data["UDP"]
        except KeyError:
            raise WebSocksError("Failed to login")

        await self.send(json.dumps({
            "VERSION": 1,
            "CMD": CMD,
            "ADDR": host,
            "PORT": port
        }))
        data = json.loads(await self.recv())
        if data.get("STATUS") != "SUCCESS":
            raise WebSocksError("Failed to connect")


class BaseAuthentication:

    def __init__(self, sock: Socket):
        self.sock = sock

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
        return {"abersheeran": "password123"}

    def getMethod(self, methods: set) -> int:
        if 2 in methods:
            return 2
        return 255

    async def authenticate(self):
        VER = await self.sock.recv(1)
        if VER != b'\x01':
            await self.sock.send(b"\x01\x01")
            raise Socks5Error("Unsupported version!")
        ULEN = int.from_bytes(await self.sock.recv(1), 'big')
        UNAME = (await self.sock.recv(ULEN)).decode("ASCII")
        PLEN = int.from_bytes(await self.sock.recv(1), 'big')
        PASSWD = (await self.sock.recv(PLEN)).decode("ASCII")
        if self._getUser().get(UNAME) and self._getUser().get(UNAME) == PASSWD:
            await self.sock.send(b"\x01\x00")
        else:
            await self.sock.send(b"\x01\x01")
            raise AuthenticationError("USERNAME or PASSWORD ERROR")


class BaseSessoin:
    """
    Client session
    """

    def __init__(self, sock: Socket):
        self.sock = sock
        self.auth = BaseAuthentication(self.sock)

    async def recv(self, num: int) -> bytes:
        data = await self.sock.recv(num)
        logger.debug(f"<<< {data}")
        if data == EMPTY:
            raise ConnectionError("Recv a empty bytes that may FIN or RST")
        return data

    async def send(self, data: bytes) -> int:
        length = await self.sock.send(data)
        logger.debug(f">>> {data}")
        return length

    async def start(self):
        try:
            await self.negotiate()
        except Socks5Error as e:
            logger.warning(e)
            self.sock.close()
        except NetworkError as e:
            logger.debug(e)
            self.sock.close()
        logger.debug(f"Connection {self.sock.address} closed")

    async def negotiate(self):
        data = await self.recv(2)
        VER, NMETHODS = data
        if VER != 5:
            await self.send(b"\x05\xff")
            raise Socks5Error("Unsupported version!")
        METHODS = set(await self.recv(NMETHODS))
        METHOD = self.auth.getMethod(METHODS)
        reply = b'\x05' + METHOD.to_bytes(1, 'big')
        await self.send(reply)
        if METHOD == 255:
            raise Socks5Error("No methods available")
        await self.auth.authenticate()
        data = await self.recv(4)
        VER, CMD, RSV, ATYP = data
        if VER != 5:
            await self.reply(GENERAL_SOCKS_SERVER_FAILURE)
            raise Socks5Error("Unsupported version!")
        # Parse target address
        if ATYP == 1:  # IPV4
            ipv4 = await self.recv(4)
            DST_ADDR = socket.inet_ntoa(ipv4)
        elif ATYP == 3:  # Domain
            addr_len = int.from_bytes(await self.recv(1), byteorder='big')
            DST_ADDR = (await self.recv(addr_len)).decode()
        elif ATYP == 4:  # IPV6
            ipv6 = await self.recv(16)
            DST_ADDR = socket.inet_ntop(socket.AF_INET6, ipv6)
        else:
            await self.reply(ADDRESS_TYPE_NOT_SUPPORTED)
            raise Socks5Error(f"Unsupported ATYP value: {ATYP}")
        DST_PORT = int.from_bytes(await self.recv(2), 'big')
        if CMD == 1:
            await self.socks5_connect(ATYP, DST_ADDR, DST_PORT)
        elif CMD == 2:
            await self.socks5_bind(ATYP, DST_ADDR, DST_PORT)
        elif CMD == 3:
            await self.socks5_udp_associate(ATYP, DST_ADDR, DST_PORT)
        else:
            await self.reply(COMMAND_NOT_SUPPORTED)
            raise Socks5Error(f"Unsupported CMD value: {CMD}")

    async def reply(self, REP: int, ATYP: int = 1, IP: str = "127.0.0.1", port: int = 1080):
        VER, RSV = b'\x05', b'\x00'
        if ATYP == 1:
            BND_ADDR = socket.inet_aton(IP)
        elif ATYP == 4:
            BND_ADDR = socket.inet_pton(socket.AF_INET6, IP)
        elif ATYP == 3:
            BND_ADDR = len(IP).to_bytes(2, 'big') + IP.encode("UTF-8")
        else:
            raise Socks5Error(f"Reply: unsupported ATYP value {ATYP}")
        REP = REP.to_bytes(1, 'big')
        ATYP = ATYP.to_bytes(1, 'big')
        BND_PORT = int(port).to_bytes(2, 'big')
        reply = VER + REP + RSV + ATYP + BND_ADDR + BND_PORT
        await self.send(reply)

    async def socks5_connect(self, ATYP: int, addr: str, port: int):
        """ must be overwrited """
        await self.reply(GENERAL_SOCKS_SERVER_FAILURE, ATYP, addr, port)
        self.sock.close()

    async def socks5_bind(self, ATYP: int, addr: str, port: int):
        """ must be overwrited """
        await self.reply(GENERAL_SOCKS_SERVER_FAILURE, ATYP, addr, port)
        self.sock.close()

    async def socks5_udp_associate(self, ATYP: int, addr: str, port: int):
        """ must be overwrited """
        await self.reply(GENERAL_SOCKS_SERVER_FAILURE, ATYP, addr, port)
        self.sock.close()


class Session(BaseSessoin):
    """ NO AUTHENTICATION REQUIRED Session"""

    def __init__(self, sock: Socket):
        super().__init__(sock)
        self.auth = NoAuthentication(sock)

    async def socks5_connect(self, ATYP: int, addr: str, port: int):

        async def bridge(sender: Socket, receiver: Socket):
            while True:
                data = await sender.recv(8192)
                if not data:
                    sender.close()
                    receiver.close()
                    return
                await receiver.send(data)
                logger.debug(f">=< {data}")
        try:
            logger.debug(f"Connecting {addr}:{port}")
            remote = await connect(addr, port)
            logger.info(f"Successfully connect {addr}:{port}")
        except NetworkError:
            await self.reply(CONNECTION_REFUSED)
            logger.warning(f"Failing connect {addr}:{port}")
            self.sock.close()
            return

        await self.reply(SUCCEEDED)
        await asyncio.gather(
            bridge(remote, self.sock),
            bridge(self.sock, remote)
        )


class SocksServer:
    """A socks5 server"""

    def __init__(self, session: BaseSessoin, ip: str = "0.0.0.0", port: int = 1080):
        self.session = session
        self.server = asyncio.get_event_loop().run_until_complete(
            asyncio.start_server(
                self._link, ip, port
            )
        )
        logger.info(f"Socks5 Server serveing on {self.server.sockets[0].getsockname()}")

    def __del__(self):
        self.server.close()
        logger.info(f"Socks5 Server has closed.")

    async def _link(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        sock = Socket(reader, writer)
        session = self.session(sock)
        logger.debug(f"Connection from {sock.address}")
        await session.start()

    def run(self):
        threading.Thread(target=asyncio.get_event_loop().run_forever, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


async def connect(host: str, port: int, CMD: str = "TCP") -> typing.Union[Socket, WebsocksClient]:
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection(host=host, port=port),
            2
        )
        return Socket(r, w)
    except NetworkError:
        pass
    except asyncio.TimeoutError:
        pass

    server = "ws://localhost:8765"
    username = "abersheeran"
    password = "password"
    try:
        sock = await websockets.connect(server)
        client = WebsocksClient(sock)
        await client.negotiate(username, password, host, port, CMD)
        return client
    except websockets.exceptions.WebSocketException as e:
        logger.error(e)
        raise ConnectionResetError("Websocket Error")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    SocksServer(port=8080, session=Session).run()
