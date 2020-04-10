import os
import asyncio
import typing
import logging

import click

from .rule import FilterRule
from .client import Client, Pool
from .server import Server
from .config import config, g


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@click.group(name="websocks", help="A websocket-based socks5 proxy.")
@click.option("--debug/--no-debug", default=False, help="enable loop debug mode")
def main(debug: bool = False) -> None:
    if debug is True:
        asyncio.get_event_loop().set_debug(debug)
        logging.getLogger("websocks").setLevel(logging.DEBUG)


@main.command(help="run a socks5 server as websocks client")
@click.argument(
    "configuration",
    type=click.Path(exists=True, dir_okay=False),
    default=os.path.join(os.environ["HOME"], ".websocks", "config.yml"),
)
def client(configuration: str):
    if configuration.endswith(".json"):
        config.from_json_file(configuration)
    else:
        config.from_yaml_file(configuration)

    FilterRule(config.rulefiles)

    g.pool = Pool(config.servers[config.server_index])

    Client().run()


@main.command(help="download rule file in local")
@click.argument(
    "namelist", nargs=-1, required=True, type=click.Choice(["gfw", "white"])
)
def download(namelist: typing.List[str]):
    for name in namelist:
        getattr(FilterRule, f"download_{name}list")()
        click.secho(f"Successfully downloaded {name}list", fg="green")


@main.command()
@click.option(
    "-U", "--userpass", required=True, multiple=True, help="USERNAME:PASSWORD"
)
@click.argument("address", type=click.Tuple([str, int]), default=("0.0.0.0", 8765))
def server(address: typing.Tuple[str, int], userpass: typing.List[str]):
    Server(
        {_userpass.split(":")[0]: _userpass.split(":")[1] for _userpass in userpass},
        host=address[0],
        port=address[1],
    ).run()


if __name__ == "__main__":
    main()
