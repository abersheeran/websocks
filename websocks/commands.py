import typing
import logging
from os import path

import click

from .rule import FilterRule

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@click.group(name="websocks", help="A websocket-based socks5 proxy.")
def main() -> None:
    pass


@main.command(help="run a socks5 server as websocks client")
@click.option("-P", "--policy", default="AUTO", type=click.Choice(["AUTO", "PROXY"]))
@click.option("-S", "--server", required=True, help="USERNAME:PASSWORD@HOST:PORT")
@click.option("-R", "--rulefile", help="rule file absolute path")
@click.argument("address", type=click.Tuple([str, int]), default=("127.0.0.1", 3128))
def client(policy: str, rulefile: str, server: str, address: typing.Tuple[str, int]):
    if rulefile:
        if path.exists(rulefile):
            FilterRule(rulefile)
        else:
            raise FileNotFoundError(rulefile)

    from .client import Client, set_policy, Pools, Pool

    set_policy(policy)

    if not server.startswith("ws://") and not server.startswith("wss://"):
        server = "wss://" + server

    Pools([Pool(server)])

    Client(address[0], address[1]).run()


@main.command(help="download rule file in local")
@click.argument("list", nargs=-1, type=click.Choice(["gfw", "white"]))
def download(list: typing.List[str]):
    for l in list:
        getattr(FilterRule, f"download_{l}list")()
        click.secho(f"Successfully downloaded {l}list", fg="green")


@main.command()
@click.option(
    "-U", "--userpass", required=True, multiple=True, help="USERNAME:PASSWORD"
)
@click.argument("address", type=click.Tuple([str, int]), default=("0.0.0.0", 8765))
def server(address: typing.Tuple[str, int], userpass: typing.List[str]):
    from .server import Server

    Server(
        {_userpass.split(":")[0]: _userpass.split(":")[1] for _userpass in userpass},
        host=address[0],
        port=address[1],
    ).run()


if __name__ == "__main__":
    main()
