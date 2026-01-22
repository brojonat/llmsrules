# ruff: noqa: E402
"""Main CLI command group."""

import warnings

# Suppress PyMC/Numba warnings that aren't relevant
warnings.filterwarnings(
    "ignore",
    message=".*FNV hashing is not implemented in Numba.*",
    category=UserWarning,
    module="numba.cpython.hashing",
)

import click

from {{cookiecutter.package_name}}.cli.experiments import experiments_cli

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option()
def cli():
    """{{cookiecutter.description}}"""
    pass


cli.add_command(experiments_cli)


def main():
    """CLI entrypoint."""
    cli()


if __name__ == "__main__":
    main()
