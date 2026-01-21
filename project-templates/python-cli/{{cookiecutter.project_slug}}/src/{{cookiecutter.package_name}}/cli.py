"""
Structured CLI with subcommand modules.

This CLI demonstrates the pattern of organizing subcommands into separate
modules under the package, then importing and registering them here.

Usage:
    {{cookiecutter.project_slug}} --help
    {{cookiecutter.project_slug}} foo do-something
    {{cookiecutter.project_slug}} bar do-other
"""

import click

from .bar.commands import cli as bar
from .foo.commands import cli as foo

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option()
def cli() -> None:
    """{{cookiecutter.description}}"""
    pass


@cli.command()
@click.option("--name", "-n", default="world", help="Who to greet.")
def hello(name: str) -> None:
    """Example top-level subcommand."""
    click.echo(f"Hello, {name}!")


# Register subcommand groups from modules
cli.add_command(foo, name="foo")
cli.add_command(bar, name="bar")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
