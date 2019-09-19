import sys
import json
import logging
import asyncio
import threading
import time
from socket import error

import websockets
from websockets import WebSocketServerProtocol

logger: logging.Logger = logging.getLogger("websocks")

if sys.platform == 'win32': # use IOCP in windows
    if sys.version_info.major >= 3 and sys.version_info.minor >= 7:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    else:
        asyncio.set_event_loop(asyncio.ProactorEventLoop())
else: # try to use uvloop
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass


class WebSocksError(Exception):
    pass


class AuthError(WebSocksError):
    pass


NetworkError = (TimeoutError, ConnectionError, ConnectionAbortedError, ConnectionRefusedError, ConnectionResetError, error)


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


class Websocket:

    def __init__(self, sock: WebSocketServerProtocol):
        self.sock = sock

    @property
    def address(self):
        return self.sock.local_address

    async def recv(self, num: int = 0):
        try:
            data = await self.sock.recv()
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError('Websocket closed.')
        logger.debug(f"<<< {data}")
        return data

    async def send(self, data: websockets.typing.Data):
        try:
            await self.sock.send(data)
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionResetError('Websocket closed.')
        logger.debug(f">>> {data}")
        return len(data)

    def close(self):
        asyncio.run_coroutine_threadsafe(
            self.sock.close(),
            asyncio.get_event_loop()
        )


class Authentication:

    def __init__(self, sock: Websocket) -> None:
        self.sock = sock

    def judge(self, username: str, password: str) -> bool:
        """账号密码验证"""
        if username == "abersheeran" and password == "password":
            return True
        return False

    async def authenticate(self) -> None:
        """身份验证"""
        try:
            try:
                data = json.loads(await self.sock.recv())
            except json.JSONDecodeError:
                raise AuthError("身份解析错误, 可能在被试探")

            if data.get("PASSWORD") is None or data.get("PASSWORD") is None or \
                    (not self.judge(data["USERNAME"], data["PASSWORD"])):
                raise AuthError("身份验证错误, 可能在被试探")
        except AuthError as e:
            await self.sock.send(json.dumps({
                "VERSION": 1,
                "MESSAGE": "用户名或密码错误",
                "STATUS": "ERROR"
            }))
            raise e from None

        await self.sock.send(json.dumps({
            "VERSION": 1,
            "IPV4": True,
            "IPV6": False,
            "TCP": True,
            "UDP": False
        }))


class Session:

    def __init__(self, sock: Websocket):
        self.sock = sock
        self.auth = Authentication(sock)

    async def start(self):
        try:
            await self.negotiate()
        except WebSocksError as e:
            logger.warning(e)
            self.sock.close()
        except NetworkError as e:
            logger.debug(e)
            self.sock.close()
        logger.debug(f"Connection {self.sock.address} closed")

    async def negotiate(self):
        """握手"""
        await self.auth.authenticate()
        data = json.loads(await self.sock.recv())
        try:
            assert data.get("ADDR") is not None, "Invalid ADDR"
            assert data.get("PORT") is not None, "Invalid PORT"
        except AssertionError as e:
            raise WebSocksError(str(e)) from None

        if data["CMD"] == "TCP":
            await self.tcp(data)
        elif data["CMD"] == "UDP":
            await self.udp()

    async def tcp(self, data: dict):

        async def bridge(sender, receiver):
            while True:
                data = await sender.recv(8192)
                if not data:
                    sender.close()
                    receiver.close()
                    return
                await receiver.send(data)
                logger.debug(f">=< {data}")

        try:
            logger.debug(f"Connecting {data['ADDR']}:{data['PORT']}")
            r, w = await asyncio.open_connection(data['ADDR'], data['PORT'])
            logger.info(f"Successfully connect {data['ADDR']}:{data['PORT']}")
        except NetworkError:
            logger.warning(f"Failing connect {data['ADDR']}:{data['PORT']}")
            await self.sock.send(json.dumps({
                "VERSION": 1,
                "STATUS": "ERROR"
            }))
            return
        await self.sock.send(json.dumps({
            "VERSION": 1,
            "STATUS": "SUCCESS"
        }))
        remote = Socket(r, w)
        await asyncio.gather(
            bridge(remote, self.sock),
            bridge(self.sock, remote)
        )

    async def udp(self):
        await self.sock.sock.close()


class WebsocksServer:

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        logger.info(f"Websocks Server serveing on {host}:{port}")
        asyncio.get_event_loop().run_until_complete(websockets.serve(self._link, host, port))

    async def _link(self, sock: WebSocketServerProtocol, path: str):
        await Session(Websocket(sock)).start()

    def run(self):
        threading.Thread(target=asyncio.get_event_loop().run_forever, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    WebsocksServer().run()
