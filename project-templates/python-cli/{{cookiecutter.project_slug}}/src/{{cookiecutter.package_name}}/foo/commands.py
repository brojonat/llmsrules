"""Foo subcommand group implementation."""

import click


@click.group()
def cli() -> None:
    """Foo-related commands."""
    pass


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output.")
def do_something(verbose: bool) -> None:
    """Do something foo-related."""
    if verbose:
        click.echo("Doing something with verbose output...")
    click.echo("Foo: Done!")


@cli.command()
@click.argument("item")
def process(item: str) -> None:
    """Process an item."""
    click.echo(f"Foo: Processing '{item}'...")
