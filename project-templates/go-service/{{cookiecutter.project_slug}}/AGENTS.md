# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Quick Reference

| Task | Command |
|------|---------|
| Run dev server | `make run-dev` |
| Run tests | `make test` |
| Run linter | `make lint` |
| Build | `make build` |
| Deploy | `make deploy` |

## Logs

Dev server logs to `logs/server.log`. View with:

```bash
tail -f logs/server.log
jq 'select(.level == "ERROR")' logs/server.log
```

## Architecture

- HTTP handlers in `cmd/server/main.go`
- Business logic in `internal/`
- Database queries in `queries/` (sqlc)
- Generated DB code in `internal/db/`

## Conventions

- Handlers are functions returning `http.Handler`
- All dependencies passed explicitly (no globals)
- Structured JSON logging via slog
- JWT auth via Bearer token
- Middleware composed with `adaptHandler` pattern

## Development

```bash
# Install dependencies
go mod download

# Install dev tools
go install github.com/cosmtrek/air@latest
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest

# Copy env file
cp .env.example .env.server

# Run with hot reload
make run-dev
```

## Database

```bash
# Generate sqlc code after schema changes
make sqlc

# Run migrations
make migrate
```

## Changelog

When merging features, update `CHANGELOG.md`:

1. Add entry under `[Unreleased]` in the appropriate category
2. Use imperative mood: "Add feature" not "Added feature"
3. Reference issue numbers if applicable

Categories: Added, Changed, Deprecated, Removed, Fixed, Security
