#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">={{cookiecutter.python_version}}"
# dependencies = [
#     "click>=8.0",
# ]
# ///
"""
Dead simple CLI using PEP 723 inline script metadata.

Usage:
    ./simple.py --help
    ./simple.py hello --name "World"
"""

import click


@click.group()
def cli() -> None:
    """{{cookiecutter.description}}"""
    pass


@cli.command()
@click.option("--name", "-n", default="world", help="Who to greet.")
def hello(name: str) -> None:
    """Say hello."""
    click.echo(f"Hello, {name}!")


@cli.command()
@click.argument("x", type=float)
@click.argument("y", type=float)
def add(x: float, y: float) -> None:
    """Add two numbers."""
    click.echo(f"{x} + {y} = {x + y}")


if __name__ == "__main__":
    cli()
