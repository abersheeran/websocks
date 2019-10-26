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

from .utils import TCPSocket, WebSocket, bridge, create_connection
from .rule import judge, add

logger: logging.Logger = logging.getLogger("websocks")


def get_credentials() -> str:
    username = os.environ['WEBSOCKS_USER']
    password = os.environ['WEBSOCKS_PASS']
    return "Basic " + base64.b64encode(f"{username}:{password}".encode("utf8")).decode("utf8")


class DirectException(Exception):
    pass


class Pool:

    def __init__(self, initsize: int = 7) -> None:
        self.initsize = initsize
        self._freepool = set()
        asyncio.run_coroutine_threadsafe(
            self.init(initsize),
            asyncio.get_event_loop()
        )
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

                sub = self.initsize - len(self._freepool)

                if sub > 0:
                    await self.init(sub)
                    continue

                while len(self._freepool) > self.initsize * 2:
                    sock = self._freepool.pop()
                    await sock.close()

        asyncio.run_coroutine_threadsafe(
            _timed_task(),
            asyncio.get_event_loop()
        )

    async def acquire(self) -> websockets.WebSocketClientProtocol:
        while True:
            try:
                sock = self._freepool.pop()
                if sock.closed:
                    continue
                return sock
            except KeyError:
                await self._create()

    async def release(self, sock: websockets.WebSocketClientProtocol) -> None:
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
            try:
                start_time = time.time()
                r = judge(host)
                if r:
                    raise DirectException(f"{host}")
                if r is None:
                    remote = await asyncio.wait_for(create_connection(host, port), timeout=2)
                else:
                    remote = await create_connection(host, port)
                logger.info(f"{time.time() - start_time:02.3f} Direct: {host}:{port}")
            except (asyncio.TimeoutError, DirectException) as e:
                remote = await self.pool.acquire()
                await remote.send(json.dumps({"HOST": host, "PORT": port}))
                resp = await remote.recv()
                assert isinstance(resp, str)
                if not json.loads(resp)['ALLOW']:
                    raise ConnectionRefusedError()
                if isinstance(e, asyncio.TimeoutError):
                    add(host)
                logger.info(f"{time.time() - start_time:02.3f} Proxy: {host}:{port}")
        except (asyncio.TimeoutError, ConnectionRefusedError):
            await reply(HTTPStatus.GATEWAY_TIMEOUT)
            await sock.close()
            logger.warning(f"Proxy Timeout: {host}:{port}")
            return
        except AssertionError:
            await reply(HTTPStatus.INTERNAL_SERVER_ERROR)
            await sock.close()
            logger.warning(f"Proxy Error: Non-standard implementation.")
            return
        except Exception:
            await reply(HTTPStatus.BAD_GATEWAY)
            await sock.close()
            logger.error(f"Unknown Error: {host}:{port}")
            traceback.print_exc()
            return
        else:
            await reply(HTTPStatus.OK)
            if isinstance(remote, websockets.WebSocketCommonProtocol):
                await bridge(sock, WebSocket(remote))
                await self.pool.release(remote)
            else:
                await bridge(sock, remote)
                await remote.close()
            if not sock.closed:
                await sock.close()

    async def run_server(self) -> typing.NoReturn:
        server = await asyncio.start_server(
            self.dispatch, self.host, self.port
        )
        logger.info(f"HTTP Server serveing on {server.sockets[0].getsockname()}")

        def termina(signo, frame):
            server.close()
            logger.info(f"HTTP Server has closed.")
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
