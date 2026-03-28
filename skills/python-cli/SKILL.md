---
name: python-cli
description: Build Python CLIs with Click using subcommand groups. Use when creating or modifying a Python command-line interface, adding subcommands, or structuring a CLI package.
---

# Python CLI with Click

Structure Python CLIs using Click with composable subcommand groups.

## Project Structure

```
.
├── pyproject.toml              # console_script points to `your_package.cli:main`
└── your_package/
    ├── __init__.py
    ├── cli.py                  # root Click group; imports and registers subcommands
    ├── foo/
    │   ├── __init__.py
    │   └── commands.py         # exposes a Click group named `cli`
    └── bar/
        ├── __init__.py
        └── commands.py         # exposes a Click group named `cli`
```

## Root CLI Entry Point

```python
import click

from .foo.commands import cli as foo
from .bar.commands import cli as bar

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
def cli() -> None:
    """Project command line interface."""
    pass


@cli.command()
@click.option("--name", "-n", default="world", help="Who to greet.")
def hello(name: str) -> None:
    """Example subcommand."""
    click.echo(f"Hello, {name}!")


def main() -> None:
    cli()

# Register imported subcommand groups with explicit names
cli.add_command(foo, name="foo")
cli.add_command(bar, name="bar")


if __name__ == "__main__":
    main()
```

## Subcommand Module (`foo/commands.py`)

```python
import click


@click.group()
def cli() -> None:
    """Foo subcommands."""
    pass


@cli.command()
@click.argument("item")
def process(item: str) -> None:
    """Process a single item."""
    click.echo(f"Processing: {item}")
```

## pyproject.toml Entry Point

```toml
[project.scripts]
my-tool = "your_package.cli:main"
```

## Key Patterns

- **One group per module**: Each subcommand directory exports a Click group named `cli`
- **Explicit registration**: Use `cli.add_command(group, name="name")` in the root CLI
- **Context settings**: Always set `help_option_names = ["-h", "--help"]`
- **Console scripts**: Wire up the entry point in `pyproject.toml` for `uv pip install -e .`

## Bookkeeping

After modifying the CLI, update the adjacent README.md to reflect the current command surface.
