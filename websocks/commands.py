import click


@click.group()
def main() -> None:
    pass


@main.command()
def client():
    pass


@main.command()
def server():
    pass
