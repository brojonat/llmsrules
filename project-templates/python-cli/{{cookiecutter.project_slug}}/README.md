# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Quick Start

This template provides two CLI patterns:

### 1. Simple PEP 723 Script

For quick, standalone scripts with inline dependencies:

```bash
# Run directly (no install needed, uv handles deps)
./simple.py hello --name "World"
./simple.py add 1 2
```

### 2. Structured CLI Package

For more complex CLIs with subcommand modules:

```bash
# Install
uv sync

# Run via installed entrypoint
{{cookiecutter.project_slug}} hello --name "World"
{{cookiecutter.project_slug}} foo do-something --verbose
{{cookiecutter.project_slug}} bar greet "World" --count 3

# Or via uv run
uv run {{cookiecutter.project_slug}} --help
```

## Project Structure

```
.
├── simple.py                    # PEP 723 standalone script
├── pyproject.toml               # Package metadata
├── src/
│   └── {{cookiecutter.package_name}}/
│       ├── __init__.py
│       ├── cli.py               # Main CLI entrypoint
│       ├── foo/
│       │   ├── __init__.py
│       │   └── commands.py      # Foo subcommand group
│       └── bar/
│           ├── __init__.py
│           └── commands.py      # Bar subcommand group
└── tests/
    └── test_cli.py
```

## Development

```bash
# Install dev dependencies
uv sync --all-extras

# Run tests
make test

# Lint and format
make lint
make format
```

## Adding Subcommands

1. Create a new module directory under `src/{{cookiecutter.package_name}}/`:
   ```
   mkdir -p src/{{cookiecutter.package_name}}/newcmd
   touch src/{{cookiecutter.package_name}}/newcmd/__init__.py
   ```

2. Create `commands.py` with a Click group:
   ```python
   import click

   @click.group()
   def cli() -> None:
       """Newcmd-related commands."""
       pass

   @cli.command()
   def example() -> None:
       """Example command."""
       click.echo("Done!")
   ```

3. Register in `cli.py`:
   ```python
   from .newcmd.commands import cli as newcmd
   cli.add_command(newcmd, name="newcmd")
   ```
