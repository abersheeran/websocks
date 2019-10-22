import base64
import signal
import asyncio
import typing
import logging
import logging.config
from http import HTTPStatus

from .utils import TCPSocket, bridge, connect_server

logger: logging.Logger = logging.getLogger("websocks")


def get_credentials() -> str:
    username = "abersheeran"
    password = "websocks"
    return "Basic " + base64.b64encode(f"{username}:{password}".encode("utf8")).decode("utf8")


class HTTPServer:
    """A http server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 3128) -> None:
        self.host = host
        self.port = port

    async def dispatch(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        firstline = await reader.readline()
        for index, data in enumerate(firstline):
            reader._buffer.insert(index, data)
        method = firstline.decode("ASCII").split(" ")[0]
        if hasattr(self, method.lower()):
            await getattr(self, method.lower())(reader, writer)

    async def connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sock = TCPSocket(reader, writer)

        async def reply(status_code: HTTPStatus) -> None:
            await sock.send(f"HTTP/1.1 {status_code.value} {status_code.phrase}\r\n".encode("ASCII"))
            await sock.send(f"Server: {asyncio.get_event_loop_policy()}".encode("ASCII"))
            await sock.send(b"\r\n\r\n")

        # parse HTTP CONNECT
        raw_request = await sock.recv()
        method, hostport, version = raw_request.splitlines()[0].decode("ASCII").split(" ")
        host, port = hostport.split(":")
        try:
            remote = await connect_server("ws://127.0.0.1:8765", {
                "TARGET": host,
                "PORT": port,
                "Proxy-Authorization": get_credentials()
            })
        except asyncio.TimeoutError:
            await reply(HTTPStatus.GATEWAY_TIMEOUT)
            await sock.close()
        except Exception:
            await reply(HTTPStatus.BAD_GATEWAY)
            await sock.close()
        else:
            await reply(HTTPStatus.OK)
            await bridge(sock, remote)

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
