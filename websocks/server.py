import os
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

from .utils import create_connection, TCPSocket, WebSocket, bridge

logger: logging.Logger = logging.getLogger("websocks")


class WebsocksServer:

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.freepool: typing.Dict[str, TCPSocket] = {}

    @staticmethod
    def get_target(headers: Headers) -> typing.Tuple[str, int]:
        host = headers.get("TARGET")
        port = headers.get("PORT")
        return host, port

    async def connect(self, host: str, port: int) -> None:
        key = f"{host}:{port}"
        remote_socket = await create_connection(host, port)
        if key not in self.freepool:
            self.freepool[key] = [remote_socket]
        else:
            self.freepool[key].append(remote_socket)

    def get_connection(self, host: str, port: int) -> None:
        key = f"{host}:{port}"
        return self.freepool[key].pop()

    async def _link(self, sock: WebSocketServerProtocol, path: str):
        host, port = self.get_target(sock.request_headers)
        remote = self.get_connection(host, port)
        await bridge(WebSocket(sock), remote)

    async def handshake(
        self, path: str, request_headers: Headers
    ) -> typing.Optional[HTTPResponse]:
        # parse credentials
        _type, _credentials = request_headers.get('Proxy-Authorization').split(" ")
        username, password = base64.b64decode(_credentials).decode("utf8").split(":")
        if not (
                username == os.environ['WEBSOCKS_USER'] or
                password == os.environ['WEBSOCKS_PASS']
        ):
            return http.HTTPStatus.NOT_FOUND, {}, b""
        # parse target host & port
        host, port = self.get_target(request_headers)
        if not(host and port):
            return http.HTTPStatus.NOT_FOUND, {}, b""
        try:
            await self.connect(host, port)
        except Exception:
            return http.HTTPStatus.GATEWAY_TIMEOUT, {}, b""
        return None

    async def run_server(self) -> typing.NoReturn:
        async with websockets.serve(
            self._link,
            host=self.host,
            port=self.port,
            process_request=self.handshake
        ) as server:
            logger.info(f"Websocks Server serveing on {self.host}:{self.port}")

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
        loop.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    WebsocksServer().run()
