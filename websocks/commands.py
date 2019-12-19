import logging

import click

from .client import Socks5Server
from .server import WebsocksServer
from .rule import hostlist

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@click.group()
def main() -> None:
    pass


@main.command()
@click.option("-P", "--policy", default="AUTO", type=click.Choice(["AUTO", "PROXY"]))
@click.option("-S", "--server", required=True, help="USERNAME:PASSWORD@HOST:PORT")
@click.argument("address", type=click.Tuple([str, int]), default=("127.0.0.1", "3128"))
def client(policy, server, address):
    Socks5Server(address[0], address[1], policy=policy, server=server).run()


@main.command()
@click.argument("list", nargs=-1, type=click.Choice(["gfw", "white"]))
def download(list):
    for l in list:
        getattr(hostlist, f"download_{l}list")()
        click.secho(f"Successfully downloaded {l}list", fg="green")


@main.command()
@click.option(
    "-U", "--userpass", required=True, multiple=True, help="USERNAME:PASSWORD"
)
@click.argument("address", type=click.Tuple([str, int]), default=("0.0.0.0", "8765"))
def server(address, userpass):
    WebsocksServer(
        {_userpass.split(":")[0]: _userpass.split(":")[1] for _userpass in userpass},
        host=address[0],
        port=address[1],
    ).run()


if __name__ == "__main__":
    main()
