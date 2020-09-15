import os
import sys
import asyncio
import typing
import logging

if sys.version_info[:2] < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal

import click

from .rule import FilterRule
from .client import Client
from .server import Server
from .config import config


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
@click.option(
    "-P",
    "--proxy-policy",
    default="AUTO",
    type=click.Choice(["AUTO", "PROXY", "DIRECT", "GFW"]),
    help="AUTO: auto judge; PROXY: always proxy; DIRECT: always direct; GFW: use rule list",
)
@click.option(
    "-S", "--server-url", help="websocket url with username and password",
)
@click.option(
    "-R",
    "--rulefile",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="rule file absolute path",
)
@click.option(
    "-c",
    "--configuration",
    default=os.path.join(os.environ["HOME"], ".websocks", "config.yml"),
)
@click.argument("address", type=click.Tuple([str, int]), default=("127.0.0.1", 3128))
def client(
    proxy_policy: Literal["AUTO", "PROXY", "DIRECT", "GFW"],
    rulefile: typing.List[str],
    server_url: str,
    address: typing.Tuple[str, int],
    configuration: str,
):
    if os.path.isfile(configuration):
        if configuration.endswith(".json"):
            config.from_json_file(configuration)
        else:
            config.from_yaml_file(configuration)
    else:
        logging.warning(f"The file that don't exist: {configuration}")

    new_config = {}
    if address != ("127.0.0.1", 3128):
        new_config["host"] = address[0]
        new_config["port"] = address[1]
    if proxy_policy != "AUTO":
        new_config["proxy_policy"] = proxy_policy
    if rulefile:
        new_config["rulefiles"] = rulefile
    if server_url:
        new_config["servers"] = [server_url]
    config._update(new_config)

    FilterRule(config.rulefiles)

    Client(config.host, config.port).run()


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
