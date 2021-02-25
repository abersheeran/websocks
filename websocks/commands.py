import sys
import asyncio
import typing
import logging

if sys.version_info[:2] < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal

import click

from .rule import FilterRule, judge
from .client import Client
from .server import Server
from .utils import get_proxy, set_proxy

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@click.group(name="websocks", help="A websocket-based proxy.")
@click.option("--debug/--no-debug", default=False, help="enable loop debug mode")
def main(debug: bool = False) -> None:
    if debug is True:
        asyncio.get_event_loop().set_debug(debug)
        logging.getLogger("websocks").setLevel(logging.DEBUG)


@main.command(help="Create a http server as websocks client")
@click.option(
    "-P",
    "--proxy-policy",
    default="AUTO",
    type=click.Choice(["AUTO", "PROXY", "DIRECT", "BLACK", "WHITE"]),
    help=(
        "AUTO: auto judge; PROXY: always proxy; DIRECT: always direct;"
        " BLACK: only proxy black rules; WHITE: only direct white rules;"
    ),
    show_default=True,
)
@click.option(
    "-T",
    "--tcp-server",
    help="websocket url with username and password",
    required=True,
)
@click.option(
    "-R",
    "--rulefile",
    "rulefiles",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="rule file absolute path",
)
@click.option(
    "-NS", "--nameserver", "nameservers", multiple=True, help="set dns servers"
)
@click.argument("address", type=click.Tuple([str, int]), default=("127.0.0.1", 3128))
def client(
    proxy_policy: Literal["AUTO", "PROXY", "DIRECT", "BLACK", "WHITE"],
    rulefiles: typing.List[str],
    tcp_server: str,
    nameservers: typing.List[str],
    address: typing.Tuple[str, int],
):
    FilterRule(rulefiles)
    Client(
        client_host=address[0],
        client_port=address[1],
        tcp_server=tcp_server,
        nameservers=nameservers,
        proxy_policy=proxy_policy,
    ).run()


@main.command(help="Download rule file in local")
@click.argument(
    "namelist", nargs=-1, required=True, type=click.Choice(["gfw", "white"])
)
def download(namelist: typing.List[str]):
    for name in namelist:
        getattr(FilterRule, f"download_{name}list")()
        click.secho(f"Successfully downloaded {name}list", fg="green")


@main.command(help="Check whether the host needs pass proxy")
@click.option(
    "-R",
    "--rulefile",
    "rulefiles",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="rule file absolute path",
)
@click.argument("host")
def check(rulefiles: typing.List[str], host: str):
    FilterRule(rulefiles)

    need_proxy = judge(host)
    if need_proxy is True:
        click.secho("Need proxy.", fg="red")
    elif need_proxy is None:
        click.secho("Don't know.")
    elif need_proxy is False:
        click.secho("Don't need proxy.", fg="green")


@click.group(help="Manage system proxy settings")
def proxy():
    pass


@proxy.command(help="Set system proxy settings")
@click.argument("address")
def set(address: str):
    set_proxy(True, address)


@proxy.command(help="Display system proxy settings")
def get():
    enable, address = get_proxy()
    if address:
        click.secho(f"System proxy: {address} {'√' if enable else 'X'}")
    else:
        click.secho("No system proxy")


@proxy.command(help="Clear system proxy settings")
def clear():
    set_proxy(False, "")


main.add_command(proxy)


@main.command(help="Create websocks server")
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
