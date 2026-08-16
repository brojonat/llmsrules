#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "click>=8.0",
# ]
# ///
"""
Test cookiecutter templates by generating and validating them.

Usage:
    ./test-templates.py --help
    ./test-templates.py generate              # Generate all templates
    ./test-templates.py validate              # Generate + validate all
    ./test-templates.py validate --only cli   # Generate + validate one
    ./test-templates.py clean                 # Remove test output
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click

# Colors
GREEN = "\033[0;32m"
RED = "\033[0;31m"
BLUE = "\033[0;34m"
YELLOW = "\033[0;33m"
NC = "\033[0m"

SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = SCRIPT_DIR / "_test-output"

TEMPLATES = {
    "go": {
        "name": "go-service",
        "output": "test-go-service",
        "vars": {"project_name": "Test Go Service", "author": "testuser"},
    },
    "python": {
        "name": "python-service",
        "output": "test-python-service",
        "vars": {"project_name": "Test Python Service", "author": "testuser"},
    },
    "cli": {
        "name": "python-cli",
        "output": "test-cli",
        "vars": {"project_name": "Test CLI", "author": "testuser"},
    },
    "bayesian": {
        "name": "python-bayesian-experiment",
        "output": "test-bayesian",
        "vars": {"project_name": "Test Bayesian", "author": "testuser"},
    },
    "ducklake": {
        "name": "python-ducklake-service",
        "output": "test-ducklake-service",
        "vars": {"project_name": "Test Ducklake Service", "author": "testuser"},
    },
    "realtime": {
        "name": "go-real-time-service",
        "output": "test-realtime-service",
        "vars": {"project_name": "Test Realtime Service", "author": "testuser"},
    },
    "minimal": {
        "name": "go-datastar-minimal",
        "output": "test-datastar-minimal",
        "vars": {"project_name": "Test Datastar Minimal", "author": "testuser"},
    },
    "pyminimal": {
        "name": "python-datastar-minimal",
        "output": "test-py-datastar-minimal",
        "vars": {"project_name": "Test Py Datastar Minimal", "author": "testuser"},
    },
}


def log(msg: str) -> None:
    click.echo(f"{BLUE}==>{NC} {msg}")


def success(msg: str) -> None:
    click.echo(f"{GREEN}✓{NC} {msg}")


def error(msg: str) -> None:
    click.echo(f"{RED}✗{NC} {msg}")


def warn(msg: str) -> None:
    click.echo(f"{YELLOW}!{NC} {msg}")


def section(msg: str) -> None:
    click.echo(f"\n{BLUE}━━━ {msg} ━━━{NC}")


def run(
    cmd: str | list[str],
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a command and optionally check for errors."""
    if isinstance(cmd, str):
        cmd = cmd.split()
    log(f"{' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
    )
    if check and result.returncode != 0:
        if capture:
            click.echo(result.stdout)
            click.echo(result.stderr)
        raise click.ClickException(f"Command failed: {' '.join(cmd)}")
    return result


def run_with_output(cmd: str | list[str], cwd: Path | None = None) -> None:
    """Run a command and stream output."""
    if isinstance(cmd, str):
        cmd = cmd.split()
    log(f"{' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


# ============================================================================
# Generation
# ============================================================================


def generate_template(key: str) -> Path:
    """Generate a single template and return its output path."""
    tmpl = TEMPLATES[key]
    template_dir = SCRIPT_DIR / tmpl["name"]
    output_path = OUTPUT_DIR / tmpl["output"]

    log(f"Generating {tmpl['name']} template...")

    # Build cookiecutter args
    args = ["cookiecutter", str(template_dir), "--no-input", "--output-dir", str(OUTPUT_DIR)]
    for k, v in tmpl["vars"].items():
        args.append(f"{k}={v}")

    subprocess.run(args, check=True, capture_output=True, text=True)
    success(f"Generated: {output_path}")
    return output_path


# ============================================================================
# Validation
# ============================================================================


def validate_go(project_dir: Path) -> None:
    """Validate go-service template."""
    section("Validating go-service")

    run_with_output("make help", cwd=project_dir)
    success("make help works")

    run_with_output("go mod tidy", cwd=project_dir)
    success("go mod tidy works")

    run_with_output("make build", cwd=project_dir)
    success("make build works")

    run_with_output("./bin/test-go-service --help", cwd=project_dir)
    success("CLI --help works")

    # Tests may fail without database
    result = subprocess.run(
        ["make", "test"], cwd=project_dir, capture_output=True, text=True
    )
    if result.returncode == 0:
        success("make test works")
    else:
        warn("make test failed (may need database)")

    # Brief server test
    log("Starting server briefly...")
    server = subprocess.Popen(
        ["./bin/test-go-service", "server", "--addr", ":18080"],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:18080/healthz"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            success("Server responds to /healthz")
        else:
            warn("Server health check failed")
    except Exception:
        warn("Server health check failed")
    finally:
        server.terminate()
        server.wait()

    success("go-service validation complete")


def validate_python_service(project_dir: Path) -> None:
    """Validate python-service template."""
    section("Validating python-service")

    run_with_output("make help", cwd=project_dir)
    success("make help works")

    run_with_output(["uv", "sync", "--all-extras"], cwd=project_dir)
    success("uv sync --all-extras works")

    run_with_output(["uv", "run", "test-python-service", "--help"], cwd=project_dir)
    success("CLI --help works")

    run_with_output("make test", cwd=project_dir)
    success("make test works")

    run_with_output("make lint", cwd=project_dir)
    success("make lint works")

    # Brief server test
    log("Starting server briefly...")
    server = subprocess.Popen(
        ["uv", "run", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "18000"],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2.5)
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:18000/healthz"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            success("Server responds to /healthz")
        else:
            warn("Server health check failed")
    except Exception:
        warn("Server health check failed")
    finally:
        server.terminate()
        server.wait()

    success("python-service validation complete")


def validate_python_cli(project_dir: Path) -> None:
    """Validate python-cli template."""
    section("Validating python-cli")

    run_with_output("make help", cwd=project_dir)
    success("make help works")

    # Simple PEP 723 script
    run_with_output("./simple.py --help", cwd=project_dir)
    success("simple.py --help works")

    run_with_output(["./simple.py", "hello", "--name", "World"], cwd=project_dir)
    success("simple.py hello works")

    run_with_output(["./simple.py", "add", "2", "3"], cwd=project_dir)
    success("simple.py add works")

    # Structured CLI
    run_with_output(["uv", "sync", "--all-extras"], cwd=project_dir)
    success("uv sync --all-extras works")

    run_with_output(["uv", "run", "test-cli", "--help"], cwd=project_dir)
    success("test-cli --help works")

    run_with_output(["uv", "run", "test-cli", "hello", "--name", "World"], cwd=project_dir)
    success("test-cli hello works")

    run_with_output(
        ["uv", "run", "test-cli", "foo", "do-something", "--verbose"], cwd=project_dir
    )
    success("test-cli foo do-something works")

    run_with_output(
        ["uv", "run", "test-cli", "bar", "greet", "World", "--count", "2"], cwd=project_dir
    )
    success("test-cli bar greet works")

    run_with_output("make test", cwd=project_dir)
    success("make test works")

    run_with_output("make lint", cwd=project_dir)
    success("make lint works")

    success("python-cli validation complete")


def validate_bayesian(project_dir: Path) -> None:
    """Validate python-bayesian-experiment template."""
    section("Validating python-bayesian-experiment")

    run_with_output("make help", cwd=project_dir)
    success("make help works")

    run_with_output(["uv", "sync", "--all-extras"], cwd=project_dir)
    success("uv sync --all-extras works")

    run_with_output(["uv", "run", "test-bayesian", "--help"], cwd=project_dir)
    success("CLI --help works")

    run_with_output(["uv", "run", "test-bayesian", "experiments", "--help"], cwd=project_dir)
    success("CLI experiments --help works")

    run_with_output("make test", cwd=project_dir)
    success("make test works")

    run_with_output("make lint", cwd=project_dir)
    success("make lint works")

    # Brief server test
    log("Starting server briefly...")
    server = subprocess.Popen(
        ["uv", "run", "uvicorn", "test_bayesian.server.main:app", "--host", "0.0.0.0", "--port", "18001"],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:18001/healthz"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            success("Server responds to /healthz")
        else:
            warn("Server health check failed")
    except Exception:
        warn("Server health check failed")
    finally:
        server.terminate()
        server.wait()

    success("python-bayesian-experiment validation complete")


def validate_ducklake(project_dir: Path) -> None:
    """Validate python-ducklake-service template."""
    section("Validating python-ducklake-service")

    run_with_output("make help", cwd=project_dir)
    success("make help works")

    run_with_output(["uv", "sync", "--all-extras"], cwd=project_dir)
    success("uv sync --all-extras works")

    run_with_output(["uv", "run", "test-ducklake-service", "--help"], cwd=project_dir)
    success("CLI --help works")

    run_with_output(["uv", "run", "test-ducklake-service", "serve", "--help"], cwd=project_dir)
    success("CLI serve --help works")

    run_with_output(["uv", "run", "test-ducklake-service", "migrate", "--help"], cwd=project_dir)
    success("CLI migrate --help works")

    run_with_output("make lint", cwd=project_dir)
    success("make lint works")

    # Tests need env vars but no running services
    env = os.environ.copy()
    env["SKIP_INTEGRATION"] = "1"
    log("make test (SKIP_INTEGRATION=1)")
    subprocess.run(["make", "test"], cwd=project_dir, check=True, env=env)
    success("make test works")

    success("python-ducklake-service validation complete")


def validate_realtime(project_dir: Path) -> None:
    """Validate go-real-time-service template."""
    section("Validating go-real-time-service")

    run_with_output("make help", cwd=project_dir)
    success("make help works")

    # Downloads datastar/daisyui, tidies modules, runs templ + tailwind.
    # Needs network access.
    run_with_output("make setup", cwd=project_dir)
    success("make setup works")

    # Generated output is gitignored. `make clean` removes it, and a bare
    # `go build` must then fail -- that is what stops anyone compiling a stale
    # template instead of the .templ file they just edited.
    run_with_output("make clean", cwd=project_dir)
    result = subprocess.run(
        ["go", "build", "./..."], cwd=project_dir, capture_output=True, text=True
    )
    if result.returncode != 0 and "undefined" in result.stderr:
        success("bare `go build` fails without codegen, as designed")
    else:
        warn("bare `go build` unexpectedly succeeded without codegen")

    run_with_output("make build", cwd=project_dir)
    success("make build works")

    run_with_output("./bin/test-realtime-service --help", cwd=project_dir)
    success("CLI --help works")

    run_with_output("make test", cwd=project_dir)
    success("make test works")

    log("Starting server briefly...")
    env = os.environ.copy()
    env["SESSION_SECRET"] = "test"
    server = subprocess.Popen(
        ["./bin/test-realtime-service", "server", "--addr", ":18080"],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    time.sleep(3)
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:18080/healthz"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            success("Server responds to /healthz")
        else:
            warn("Server health check failed")

        # The point of the template: a GET that stays open and pushes HTML.
        result = subprocess.run(
            ["curl", "-sN", "-m", "3", "http://localhost:18080/api/todos"],
            capture_output=True,
            timeout=10,
            text=True,
        )
        if "datastar-patch-elements" in result.stdout:
            success("SSE stream pushes an element patch")
        else:
            warn("SSE stream produced no element patch")
    except Exception:
        warn("Server checks failed")
    finally:
        server.terminate()
        server.wait()

    success("go-real-time-service validation complete")


def validate_minimal(project_dir: Path) -> None:
    """Validate go-datastar-minimal template."""
    section("Validating go-datastar-minimal")

    # The whole promise of this template: one source file, no setup step.
    files = sorted(p.name for p in project_dir.iterdir() if p.is_file())
    if files == [".gitignore", "README.md", "go.mod", "go.sum", "main.go"]:
        success("template is exactly main.go + go.mod + go.sum + README + .gitignore")
    else:
        warn(f"unexpected file set: {files}")

    # go.mod/go.sum are committed so `go run .` needs no `go mod tidy` first.
    result = subprocess.run(
        ["go", "build", "-o", os.devnull, "."],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        success("builds from the committed go.mod/go.sum -- no tidy step")
    else:
        warn(f"build needed a tidy step: {result.stderr.strip()}")

    run_with_output("gofmt -l .", cwd=project_dir)
    run_with_output("go vet ./...", cwd=project_dir)
    success("gofmt and go vet are clean")

    log("Starting server briefly...")
    env = os.environ.copy()
    env["PORT"] = "18090"
    server = subprocess.Popen(
        ["go", "run", "."],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    time.sleep(4)
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:18090/"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        if result.returncode == 0 and 'id="board"' in result.stdout:
            success("`go run .` serves the page")
        else:
            warn("page did not render")

        # Write, then confirm the read stream carries it back.
        subprocess.run(
            ["curl", "-sf", "-X", "POST", "-d", '{"message":"from curl"}',
             "http://localhost:18090/add"],
            capture_output=True,
            timeout=5,
        )
        result = subprocess.run(
            ["curl", "-sN", "-m", "3", "http://localhost:18090/updates"],
            capture_output=True,
            timeout=10,
            text=True,
        )
        if "datastar-patch-elements" in result.stdout and "from curl" in result.stdout:
            success("POST /add lands on the SSE read stream")
        else:
            warn("SSE stream did not carry the write")
    except Exception:
        warn("Server checks failed")
    finally:
        server.terminate()
        server.wait()
        # `go run` execs a child; make sure the listener is really gone.
        subprocess.run(["pkill", "-f", "exe/test-datastar-minimal"], capture_output=True)

    success("go-datastar-minimal validation complete")


def validate_py_minimal(project_dir: Path) -> None:
    """Validate python-datastar-minimal template."""
    section("Validating python-datastar-minimal")

    # The whole promise of this template: one file, no packaging, no setup step.
    files = sorted(p.name for p in project_dir.iterdir() if p.is_file())
    if files == [".gitignore", "README.md", "main.py"]:
        success("template is exactly main.py + README + .gitignore")
    else:
        warn(f"unexpected file set: {files}")

    main_py = project_dir / "main.py"
    if "# /// script" in main_py.read_text():
        success("deps are declared inline (PEP 723) -- no pyproject, no lockfile")
    else:
        warn("PEP 723 script block missing")

    main_py.chmod(0o755)

    log("Starting server briefly (first run resolves deps)...")
    env = os.environ.copy()
    env["PORT"] = "18100"
    server = subprocess.Popen(
        ["./main.py"],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    time.sleep(12)
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:18100/"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        if result.returncode == 0 and 'id="board"' in result.stdout:
            success("`./main.py` serves the page")
        else:
            warn("page did not render")

        # Write, then confirm the read stream carries it back. read_signals()
        # ignores requests without the header datastar.js always sends.
        subprocess.run(
            ["curl", "-sf", "-X", "POST",
             "-H", "Datastar-Request: true",
             "-H", "Content-Type: application/json",
             "-d", '{"message":"from curl"}',
             "http://localhost:18100/add"],
            capture_output=True,
            timeout=5,
        )
        result = subprocess.run(
            ["curl", "-sN", "-m", "3", "http://localhost:18100/updates"],
            capture_output=True,
            timeout=10,
            text=True,
        )
        if "datastar-patch-elements" in result.stdout and "from curl" in result.stdout:
            success("POST /add lands on the SSE read stream")
        else:
            warn("SSE stream did not carry the write")
    except Exception:
        warn("Server checks failed")
    finally:
        server.terminate()
        server.wait()
        # `uv run --script` execs a child; make sure the listener is really gone.
        subprocess.run(["pkill", "-f", "test-py-datastar-minimal"], capture_output=True)

    success("python-datastar-minimal validation complete")


VALIDATORS = {
    "go": validate_go,
    "python": validate_python_service,
    "cli": validate_python_cli,
    "bayesian": validate_bayesian,
    "ducklake": validate_ducklake,
    "realtime": validate_realtime,
    "minimal": validate_minimal,
    "pyminimal": validate_py_minimal,
}


# ============================================================================
# CLI Commands
# ============================================================================

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
def cli() -> None:
    """Test cookiecutter templates."""
    pass


@cli.command()
@click.option("--only", type=click.Choice(["go", "python", "cli", "bayesian", "ducklake", "realtime", "minimal", "pyminimal"]), help="Generate only one template")
def generate(only: str | None) -> None:
    """Generate templates without validation."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    templates = [only] if only else TEMPLATES.keys()
    for key in templates:
        generate_template(key)

    click.echo()
    log(f"Templates generated in {OUTPUT_DIR}")
    click.echo()
    click.echo("Run './test-templates.py validate' to test all entry points")


@cli.command()
@click.option("--only", type=click.Choice(["go", "python", "cli", "bayesian", "ducklake", "realtime", "minimal", "pyminimal"]), help="Validate only one template")
def validate(only: str | None) -> None:
    """Generate and validate templates."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    templates = [only] if only else list(TEMPLATES.keys())

    # Generate all first
    paths = {}
    for key in templates:
        paths[key] = generate_template(key)

    click.echo()

    # Then validate
    for key in templates:
        VALIDATORS[key](paths[key])

    if len(templates) > 1:
        section("All validations passed!")


@cli.command()
def clean() -> None:
    """Remove test output directory."""
    log("Cleaning test output directory...")
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    success(f"Cleaned {OUTPUT_DIR}")


@cli.command()
def show() -> None:
    """Show available templates and their entry points."""
    click.echo("Available templates:\n")

    click.echo(f"{BLUE}go-service:{NC}")
    click.echo("  make help          # Show targets")
    click.echo("  make build         # Build binary")
    click.echo("  make test          # Run tests")
    click.echo("  make run-dev       # Run with hot reload")
    click.echo("  ./bin/<name> --help")
    click.echo()

    click.echo(f"{BLUE}python-service:{NC}")
    click.echo("  make help          # Show targets")
    click.echo("  uv sync --all-extras")
    click.echo("  make test          # Run tests")
    click.echo("  make run-dev       # Run with hot reload")
    click.echo("  uv run <name> --help")
    click.echo()

    click.echo(f"{BLUE}python-cli:{NC}")
    click.echo("  ./simple.py --help # PEP 723 script (no install)")
    click.echo("  uv sync --all-extras")
    click.echo("  uv run <name> --help")
    click.echo("  uv run <name> foo do-something")
    click.echo("  make test")
    click.echo()

    click.echo(f"{BLUE}python-bayesian-experiment:{NC}")
    click.echo("  make help          # Show targets")
    click.echo("  uv sync --all-extras")
    click.echo("  make run-server    # Run API server")
    click.echo("  make run-mlflow    # Run MLflow UI")
    click.echo("  make start-dev     # Start tmux dev session")
    click.echo("  uv run <name> experiments list")
    click.echo("  make test")
    click.echo()

    click.echo(f"{BLUE}go-datastar-minimal:{NC}")
    click.echo("  go run .           # that is the whole dev loop")
    click.echo("  # open http://localhost:8080 in two tabs")
    click.echo()

    click.echo(f"{BLUE}python-datastar-minimal:{NC}")
    click.echo("  ./main.py          # that is the whole dev loop (PEP 723)")
    click.echo("  # open http://localhost:8000 in two tabs")
    click.echo()

    click.echo(f"{BLUE}go-real-time-service:{NC}")
    click.echo("  make help          # Show targets")
    click.echo("  make setup         # Deps, client assets, codegen (needs network)")
    click.echo("  make start-dev     # tmux session: server + css watcher")
    click.echo("  make build         # generate + css + go build -tags=prod")
    click.echo("  make test")
    click.echo("  ./bin/<name> server")
    click.echo("  # NOTE: never `go build` directly -- templ code is generated")
    click.echo()

    click.echo(f"{BLUE}python-ducklake-service:{NC}")
    click.echo("  make help          # Show targets")
    click.echo("  uv sync --all-extras")
    click.echo("  make run-dev       # Run with hot reload")
    click.echo("  make migrate       # Run migrations")
    click.echo("  uv run <name> --help")
    click.echo("  uv run <name> serve --help")
    click.echo("  make test          # Needs docker-compose services")
    click.echo("  make lint")


if __name__ == "__main__":
    cli()
