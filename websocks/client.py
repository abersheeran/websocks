import os
import json
import time
import base64
import signal
import asyncio
import typing
import logging
import traceback
from http import HTTPStatus

import websockets

from .utils import (
    TCPSocket,
    WebSocket,
    bridge,
    onlyfirst,
    create_connection,
    connect_server
)
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
        asyncio.create_task(self.init(initsize))
        self.timed_task()

    async def init(self, size: int) -> None:
        await asyncio.gather(*[self._create() for _ in range(size)])

    def timed_task(self) -> None:

        async def _timed_task() -> None:
            while True:
                await asyncio.sleep(7)

                for sock in self._freepool:
                    if sock.closed:
                        self._freepool.remove(sock)

                while len(self._freepool) > self.initsize * 2:
                    sock = self._freepool.pop()
                    await sock.close()

        asyncio.create_task(_timed_task())

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


class HTTPServer:
    """A http server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 3128) -> None:
        self.host = host
        self.port = port
        self.pool = Pool()

    async def dispatch(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        firstline = await reader.readline()
        for index, data in enumerate(firstline):
            reader._buffer.insert(index, data)
        method = firstline.decode("ASCII").split(" ")[0]
        if hasattr(self, method.lower()):
            await getattr(self, method.lower())(TCPSocket(reader, writer))

    async def connect(self, sock: TCPSocket) -> None:

        async def reply(status_code: HTTPStatus) -> None:
            await sock.send(
                (
                    f"HTTP/1.1 {status_code.value} {status_code.phrase}"
                    f"\r\nServer: O-O"
                    f"\r\n\r\n"
                ).encode("latin1")
            )

        # parse HTTP CONNECT
        raw_request = await sock.recv()
        method, hostport, version = raw_request.splitlines()[0].decode("ASCII").split(" ")
        host, port = hostport.split(":")

        try:
            start_time = time.time()
            need_proxy = rule.judge(host)
            if need_proxy:
                _remote = await self.pool.acquire()
                remote = await connect_server(_remote, host, port)
                remote_type = PROXY
            elif need_proxy is None:
                try:
                    remote = await asyncio.wait_for(
                        create_connection(host, port),
                        timeout=2.3
                    )
                    remote_type = DIRECT
                except asyncio.TimeoutError:
                    _remote = await self.pool.acquire()
                    remote = await connect_server(_remote, host, port)
                    remote_type = PROXY
                    rule.add(host)
            else:
                remote = await create_connection(host, port)
                remote_type = DIRECT
            end_time = time.time()

            logger.info(f"{end_time - start_time:02.3f} {remote_type}: {host}:{port}")

            await reply(HTTPStatus.OK)
            # forward data
            await bridge(sock, remote)

            if remote_type == PROXY:
                await self.pool.release(remote.sock)
            elif remote_type == DIRECT:
                await remote.close()

        except (asyncio.TimeoutError, ConnectionRefusedError):
            await reply(HTTPStatus.GATEWAY_TIMEOUT)
            logger.warning(f"Proxy Timeout: {host}:{port}")
        except websockets.exceptions.ConnectionClosed:
            await reply(HTTPStatus.BAD_GATEWAY)
            logger.error(f"Proxy Error: websocket closed")
        except asyncio.CancelledError as e:
            raise e  # keep CaneclledError
        except Exception:
            await reply(HTTPStatus.BAD_GATEWAY)
            logger.error(f"Unknown Error: {host}:{port}")
            traceback.print_exc()

        await sock.close()

    async def run_server(self) -> typing.NoReturn:
        server = await asyncio.start_server(
            self.dispatch, self.host, self.port
        )
        logger.info(f"HTTP Server serving on {server.sockets[0].getsockname()}")

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
    HTTPServer().run()
