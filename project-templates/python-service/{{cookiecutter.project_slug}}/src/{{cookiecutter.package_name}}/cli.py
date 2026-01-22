import click

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
def cli() -> None:
    """{{cookiecutter.description}}"""
    pass


@cli.command()
@click.option("--name", "-n", default="world", help="Who to greet.")
def hello(name: str) -> None:
    """Example subcommand."""
    click.echo(f"Hello, {name}!")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
