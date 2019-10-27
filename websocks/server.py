import os
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

from .utils import create_connection, TCPSocket, WebSocket, bridge

logger: logging.Logger = logging.getLogger("websocks")


class WebsocksServer:

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port

    async def _link(self, sock: WebSocketServerProtocol, path: str):
        logger.info(f"Connect from {sock.remote_address}")
        try:
            while True:
                data = await sock.recv()
                assert isinstance(data, str)
                request = json.loads(data)
                try:
                    remote = await create_connection(
                        request['HOST'],
                        request['PORT']
                    )
                    await sock.send(json.dumps({"ALLOW": True}))
                except (
                    ConnectionRefusedError,
                    asyncio.TimeoutError,
                    TimeoutError
                ):
                    await sock.send(json.dumps({"ALLOW": False}))
                    continue
                await bridge(WebSocket(sock), remote)
                # 清理连接
                if not remote.closed:
                    await remote.close()
                await sock.send(json.dumps({"STATUS": "CLOSED"}))
        except AssertionError:
            await sock.close()
        except KeyError:
            await sock.close()
        except websockets.exceptions.ConnectionClosedError:
            pass

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
            logger.warning(f"Authorization Error: {username}:{password}")
            return http.HTTPStatus.NOT_FOUND, {}, b""

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
