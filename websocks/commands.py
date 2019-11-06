import logging

import click

from .client import Socks5Server
from .server import WebsocksServer
from .rule import hostlist

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)


@click.group()
def main() -> None:
    pass


@main.command()
@click.option('-p', '--policy', default='AUTO', type=click.Choice(['AUTO', 'PROXY']))
@click.option('-s', '--server', required=True)
@click.argument('address', type=click.Tuple([str, int]))
def client(policy, server, address):
    Socks5Server(
        address[0],
        address[1],
        policy=policy,
        server=server
    ).run()


@main.command()
@click.argument('list', nargs=-1, type=click.Choice(['gfw', 'white']))
def download(list):
    for l in list:
        getattr(hostlist, f'download_{l}list')()
        click.secho(f"Successfully downloaded {l}list", fg="green")


@main.command()
@click.option("-U", "--userpass", required=True)
@click.argument('address', type=click.Tuple([str, int]))
def server(address, userpass):
    WebsocksServer(
        userpass.split(":")[0],
        userpass.split(":")[1],
        host=address[0],
        port=address[1]
    ).run()


if __name__ == "__main__":
    main()
