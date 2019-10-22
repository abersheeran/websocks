import sys
import json
import socket
import asyncio
import typing
import signal
import logging
import logging.config
from http import HTTPStatus

import websockets
from websockets import WebSocketClientProtocol

logger: logging.Logger = logging.getLogger("websocks")


if sys.platform == 'win32':  # use IOCP in windows
    if sys.version_info.major >= 3 and sys.version_info.minor >= 7:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    else:
        asyncio.set_event_loop(asyncio.ProactorEventLoop())
else:  # try to use uvloop
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass


class WebSocksError(Exception):
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
# Client
#########################


class Socket:

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        self.r = reader
        self.w = writer
        self.__socket = writer.get_extra_info('socket')
        self.__address = writer.get_extra_info('peername')

    @property
    def address(self) -> typing.Tuple[str, int]:
        return self.__address

    async def recv(self, num: int) -> bytes:
        data = await self.r.read(num)
        return data

    async def send(self, data: bytes) -> int:
        self.w.write(data)
        await self.w.drain()
        return len(data)

    def close(self) -> None:
        self.w.close()


class WebsocksClient:

    def __init__(self, sock: WebSocketClientProtocol) -> None:
        self.sock = sock

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

    server = "wss://websocks.abersheeran.com"
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
    except WebSocksError:
        raise ConnectionRefusedError("Websocks Error")


class HTTPServer:
    """A http server"""

    def __init__(self, ip: str = "0.0.0.0", port: int = 3128) -> None:
        self.ip = ip
        self.port = port

    async def dispatch(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        firstline = await reader.readline()
        for index, data in enumerate(firstline):
            reader._buffer.insert(index, data)
        method = firstline.decode("ASCII").split(" ")[0]
        if hasattr(self, method.lower()):
            await getattr(self, method.lower())(reader, writer)

    async def connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def bridge(sender: Socket, receiver: Socket) -> None:
            try:
                while True:
                    data = await sender.recv(8192)
                    if not data:
                        break
                    await receiver.send(data)
                    logger.debug(f">=< {data}")
            except NetworkError:
                receiver.close()
                sender.close()

        sock = Socket(reader, writer)

        async def reply(status_code: HTTPStatus) -> None:
            await sock.send(f"HTTP/1.1 {status_code.value} {status_code.phrase}\r\n".encode("ASCII"))
            await sock.send(f"Server: {asyncio.get_event_loop_policy()}".encode("ASCII"))
            await sock.send(b"\r\n\r\n")

        # parse HTTP CONNECT
        raw_request = await sock.recv(1024)
        method, hostport, _ = raw_request.splitlines()[0].decode("ASCII").split(" ")
        host, port = hostport.split(":")
        logger.info(f"Connection from {sock.address}. Request to ('{host}', {port})")

        try:
            remote = await connect(host, int(port))
            # r, w = await asyncio.wait_for(asyncio.open_connection(
            #     host, int(port), loop=asyncio.get_event_loop()
            # ), 2)
            # remote = Socket(r, w)
        except asyncio.TimeoutError:
            await reply(HTTPStatus.GATEWAY_TIMEOUT)
            sock.close()
        except NetworkError:
            await reply(HTTPStatus.BAD_GATEWAY)
            sock.close()
        else:
            await reply(HTTPStatus.OK)
            await asyncio.gather(
                bridge(remote, sock),
                bridge(sock, remote),
                return_exceptions=True
            )

    async def run_server(self) -> typing.NoReturn:
        server = await asyncio.start_server(
            self.dispatch, self.ip, self.port
        )
        logger.info(f"HTTP Server serveing on {server.sockets[0].getsockname()}")

        def exit(_, __):
            server.close()
            logger.info(f"HTTP Server has closed.")
            raise SystemExit(0)

        signal.signal(signal.SIGINT, exit)
        signal.signal(signal.SIGTERM, exit)

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
    HTTPServer().run()
