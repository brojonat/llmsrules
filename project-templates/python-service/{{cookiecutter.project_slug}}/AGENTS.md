# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Quick Reference

| Task | Command |
|------|---------|
| Run dev server | `make run-dev` |
| Run tests | `make test` |
| Run linter | `make lint` |
| Format code | `make format` |
| Deploy | `make deploy` |

## Logs

Dev server logs to `logs/server.log`. View with:

```bash
tail -f logs/server.log
jq 'select(.level == "error")' logs/server.log
```

## Architecture

- FastAPI server in `server/main.py`
- CLI commands in `src/{{cookiecutter.package_name}}/cli.py`
- Business logic in `src/{{cookiecutter.package_name}}/`

## Conventions

- FastAPI routes with dependency injection
- All dependencies passed explicitly (no globals)
- Structured JSON logging via structlog
- JWT auth via Bearer token
- Click CLI with subcommand structure

## Development

```bash
# Install dependencies
uv sync

# Copy env file
cp .env.example .env.server

# Run with hot reload
make run-dev

# Run CLI
uv run {{cookiecutter.project_slug}} hello --name "World"
```

## Testing

```bash
# Run tests
make test

# Run linter
make lint

# Format code
make format
```

## Changelog

When merging features, update `CHANGELOG.md`:

1. Add entry under `[Unreleased]` in the appropriate category
2. Use imperative mood: "Add feature" not "Added feature"
3. Reference issue numbers if applicable

Categories: Added, Changed, Deprecated, Removed, Fixed, Security
