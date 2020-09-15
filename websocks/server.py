import json
import http
import signal
import typing
import logging
import asyncio
import base64

import websockets
from websockets import WebSocketServerProtocol
from websockets.server import HTTPResponse
from websockets.http import Headers

from .types import Socket
from .utils import onlyfirst

logger: logging.Logger = logging.getLogger("websocks")


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
        return data

    async def send(self, data: bytes) -> int:
        self.w.write(data)
        await self.w.drain()
        return len(data)

    async def close(self) -> None:
        self.w.close()
        try:
            await self.w.wait_closed()
        except ConnectionError:
            pass

    @property
    def closed(self) -> bool:
        return self.w.is_closing()


async def bridge(alice: Socket, bob: Socket) -> None:
    async def _bridge(sender: Socket, receiver: Socket) -> None:
        while True:
            data = await sender.recv()
            if not data:
                return
            await receiver.send(data)

    try:
        await onlyfirst(_bridge(alice, bob), _bridge(bob, alice))
    except OSError:
        pass


class Server:
    def __init__(
        self,
        userlist: typing.Dict[str, str],
        *,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        self.userlist = userlist
        self.host = host
        self.port = port

    async def _link(self, sock: WebSocketServerProtocol, path: str):
        try:
            logger.debug(f"Connect from {sock.remote_address}")
            while True:
                websocks_has_closed = False

                data = await sock.recv()
                assert isinstance(data, str)
                request = json.loads(data)
                try:
                    remote = await TCPSocket.create_connection(
                        request["HOST"], request["PORT"]
                    )
                    await sock.send(json.dumps({"ALLOW": True}))
                except (OSError, asyncio.TimeoutError):
                    await sock.send(json.dumps({"ALLOW": False}))
                else:
                    try:
                        await bridge(sock, remote)
                    except TypeError:  # websocks closed
                        await sock.send(json.dumps({"STATUS": "CLOSED"}))
                        websocks_has_closed = True
                    finally:
                        await remote.close()
                        if sock.closed:
                            raise websockets.exceptions.ConnectionClosed(
                                sock.close_code, sock.close_reason
                            )

                if not websocks_has_closed:
                    await sock.send(json.dumps({"STATUS": "CLOSED"}))
                    while True:
                        msg = await sock.recv()
                        if isinstance(msg, str):
                            break
                    assert json.loads(msg)["STATUS"] == "CLOSED"

        except (AssertionError, KeyError):
            ...  # websocks implemented error
        except websockets.exceptions.ConnectionClosed:
            ...
        finally:
            await sock.close()
            logger.debug(f"Disconnect to {sock.remote_address}")

    async def handshake(
        self, path: str, request_headers: Headers
    ) -> typing.Optional[HTTPResponse]:
        if not request_headers.get("Authorization"):
            return http.HTTPStatus.UNAUTHORIZED, {}, b""
        # parse credentials
        _type, _credentials = request_headers.get("Authorization").split(" ")
        username, password = base64.b64decode(_credentials).decode("utf8").split(":")
        if not (username in self.userlist and password == self.userlist[username]):
            logger.warning(f"Authorization Error: {username}:{password}")
            return http.HTTPStatus.UNAUTHORIZED, {}, b""

    async def run_server(self) -> typing.NoReturn:
        async with websockets.serve(
            self._link, host=self.host, port=self.port, process_request=self.handshake
        ) as server:
            logger.info(f"Websocks Server serving on {self.host}:{self.port}")

            def termina(signo, frame):
                logger.info(f"Websocks Server has closed.")
                raise SystemExit(0)

            signal.signal(signal.SIGINT, termina)
            signal.signal(signal.SIGTERM, termina)

            while True:
                await asyncio.sleep(1)

    def run(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.run_server())
