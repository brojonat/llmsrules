---
name: pyproject-config
description: Configure Python projects with pyproject.toml including build system, console scripts, ruff linting, and pytest. Use when setting up a new Python project, configuring tooling, or adding entry points.
---

# pyproject.toml Configuration

Standard configuration for Python projects using setuptools, ruff, and pytest.

## Console Scripts

```toml
[project.scripts]
my-tool = "your_package.cli:main"
```

## Build System (src layout)

```toml
[build-system]
requires = ["setuptools>=68.0.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

This enables `uv pip install -e .` for editable installs with a `src/` layout.

## Ruff

```toml
[tool.ruff]
target-version = "py313"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I"]
ignore = ["E203", "W503"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
```

## Pytest

```toml
[tool.pytest.ini_options]
python_files = ["test_*.py", "*_test.py", "*_tests.py"]
```

## Project Layout

```
.
    pyproject.toml                  # project metadata, deps, tooling
    Makefile                        # common tasks (run, lint, test, build)
    .env.server                     # server env vars
    src/                            # application/CLI package (editable install)
        cli.py                      # Click CLI entrypoint
    server/                         # FastAPI app
        main.py                     # ASGI entrypoint
        templates/                  # Jinja2 templates
        static/                     # static assets
    data/                           # datasets and outputs
    plots/                          # generated figures
```

Keep a `src/` layout for packages so editable installs work cleanly. Use `.env.server` and `.env.client` for local development with `.env.example` files alongside code.
