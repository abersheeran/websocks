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
from .socket import TCPSocket
from .utils import onlyfirst
from .exceptions import WebSocksImplementationError

logger: logging.Logger = logging.getLogger(__name__)


async def bridge(alice: Socket, bob: Socket) -> None:
    async def _(sender: Socket, receiver: Socket) -> None:
        while True:
            data = await sender.recv()
            if not data:
                return
            await receiver.send(data)

    try:
        await onlyfirst(_(alice, bob), _(bob, alice))
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
                if not isinstance(data, str):
                    raise WebSocksImplementationError()
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
                    if json.loads(msg)["STATUS"] != "CLOSED":
                        raise WebSocksImplementationError()

        except (WebSocksImplementationError, KeyError):
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
        ):
            logger.info(f"WebSocks Server serving on {self.host}:{self.port}")

            def termina(signo, frame):
                logger.info("WebSocks Server has closed.")
                raise SystemExit(0)

            signal.signal(signal.SIGINT, termina)
            signal.signal(signal.SIGTERM, termina)

            while True:
                await asyncio.sleep(1)

    def run(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.run_server())
