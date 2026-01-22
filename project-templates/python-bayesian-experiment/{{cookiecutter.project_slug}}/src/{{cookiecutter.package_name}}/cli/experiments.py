"""CLI commands for managing experiments."""

import json

import click
import httpx


def get_api_url() -> str:
    """Get the API URL from environment or default."""
    import os

    return os.getenv("API_URL", "http://localhost:8000")


@click.group("experiments")
def experiments_cli():
    """Create, list, and manage experiments."""
    pass


@experiments_cli.command("list")
def list_experiments():
    """List all experiments."""
    try:
        response = httpx.get(f"{get_api_url()}/experiments")
        response.raise_for_status()
        click.echo(json.dumps(response.json(), indent=2))
    except httpx.HTTPStatusError as e:
        click.echo(json.dumps({"error": str(e)}, indent=2), err=True)
    except httpx.RequestError as e:
        click.echo(json.dumps({"error": f"Connection failed: {e}"}, indent=2), err=True)


@experiments_cli.command("create")
@click.option("--name", required=True, help="Unique name for the experiment.")
@click.option("--type", "exp_type", required=True, type=click.Choice(["bernoulli", "ab_test"]))
@click.option("--description", default="", help="Description of the experiment.")
def create_experiment(name: str, exp_type: str, description: str):
    """Create a new experiment."""
    try:
        response = httpx.post(
            f"{get_api_url()}/experiments",
            json={"name": name, "type": exp_type, "description": description},
        )
        response.raise_for_status()
        click.echo(json.dumps(response.json(), indent=2))
    except httpx.HTTPStatusError as e:
        try:
            error = e.response.json()
        except json.JSONDecodeError:
            error = {"error": e.response.text}
        click.echo(json.dumps(error, indent=2), err=True)
    except httpx.RequestError as e:
        click.echo(json.dumps({"error": f"Connection failed: {e}"}, indent=2), err=True)


@experiments_cli.command("delete")
@click.option("--name", required=True, help="Name of experiment to delete.")
def delete_experiment(name: str):
    """Delete an experiment."""
    try:
        response = httpx.delete(f"{get_api_url()}/experiments/{name}")
        response.raise_for_status()
        click.echo(json.dumps({"status": "deleted", "name": name}, indent=2))
    except httpx.HTTPStatusError as e:
        try:
            error = e.response.json()
        except json.JSONDecodeError:
            error = {"error": e.response.text}
        click.echo(json.dumps(error, indent=2), err=True)
    except httpx.RequestError as e:
        click.echo(json.dumps({"error": f"Connection failed: {e}"}, indent=2), err=True)


@experiments_cli.command("add-data")
@click.option("--name", required=True, help="Name of the experiment.")
@click.option("--file", "data_file", type=click.File("r"), default="-", help="JSON data file.")
def add_data(name: str, data_file):
    """Add data to an experiment."""
    try:
        data = json.load(data_file)
        response = httpx.post(f"{get_api_url()}/experiments/{name}/data", json=data)
        response.raise_for_status()
        click.echo(json.dumps(response.json(), indent=2))
    except json.JSONDecodeError as e:
        click.echo(json.dumps({"error": f"Invalid JSON: {e}"}, indent=2), err=True)
    except httpx.HTTPStatusError as e:
        try:
            error = e.response.json()
        except json.JSONDecodeError:
            error = {"error": e.response.text}
        click.echo(json.dumps(error, indent=2), err=True)
    except httpx.RequestError as e:
        click.echo(json.dumps({"error": f"Connection failed: {e}"}, indent=2), err=True)


@experiments_cli.command("posterior")
@click.option("--name", required=True, help="Name of the experiment.")
def get_posterior(name: str):
    """Get posterior summary for an experiment."""
    try:
        response = httpx.get(f"{get_api_url()}/experiments/{name}/posterior")
        response.raise_for_status()
        click.echo(json.dumps(response.json(), indent=2))
    except httpx.HTTPStatusError as e:
        try:
            error = e.response.json()
        except json.JSONDecodeError:
            error = {"error": e.response.text}
        click.echo(json.dumps(error, indent=2), err=True)
    except httpx.RequestError as e:
        click.echo(json.dumps({"error": f"Connection failed: {e}"}, indent=2), err=True)
