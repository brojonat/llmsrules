"""Bar subcommand group implementation."""

import click


@click.group()
def cli() -> None:
    """Bar-related commands."""
    pass


@cli.command()
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be done.")
def do_other(dry_run: bool) -> None:
    """Do something bar-related."""
    if dry_run:
        click.echo("Bar: Would do something (dry run)")
    else:
        click.echo("Bar: Done!")


@cli.command()
@click.argument("name")
@click.option("--count", "-c", default=1, help="Number of times to greet.")
def greet(name: str, count: int) -> None:
    """Greet someone multiple times."""
    for _ in range(count):
        click.echo(f"Bar: Hello, {name}!")
