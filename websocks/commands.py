import asyncio
import typing
import logging

import click

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
    "--policy",
    default="AUTO",
    type=click.Choice(["AUTO", "PROXY", "DIRECT", "GFW"]),
    help="AUTO: auto judge; PROXY: always proxy; DIRECT: always direct; GFW: use rule list",
)
@click.option(
    "-S",
    "--server-url",
    required=True,
    multiple=True,
    help="websocket url with username and password",
)
@click.option(
    "-R",
    "--rulefile",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="rule file absolute path",
)
@click.argument("address", type=click.Tuple([str, int]), default=("127.0.0.1", 3128))
def client(
    policy: str,
    rulefile: typing.List[str],
    server_url: typing.List[str],
    address: typing.Tuple[str, int],
):
    from .rule import FilterRule

    FilterRule(rulefile)

    from .client import Client, set_policy, Pools, Pool

    set_policy(policy)

    Pools(
        [
            Pool(
                "wss://" + s
                if not s.startswith("ws://") and not s.startswith("wss://")
                else s
            )
            for s in server_url
        ]
    )

    Client(address[0], address[1]).run()


@main.command(help="download rule file in local")
@click.argument(
    "namelist", nargs=-1, required=True, type=click.Choice(["gfw", "white"])
)
def download(namelist: typing.List[str]):
    from .rule import FilterRule

    for name in namelist:
        getattr(FilterRule, f"download_{name}list")()
        click.secho(f"Successfully downloaded {name}list", fg="green")


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
