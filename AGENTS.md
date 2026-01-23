# Development Guide for AI Coding Agents

This document provides guidance for AI coding agents (Claude Code, Cursor, GitHub Copilot, etc.) and human developers working on projects in this repository. Follow these practices to maintain code quality, consistency, and project health.

## Overview

This repository contains:

- **Project templates** (`project-templates/`): Cookiecutter templates for bootstrapping new projects
- **Agent rules** (`claude/`): Language and framework-specific development guidelines

When working on projects, refer to the relevant guidelines in the `claude/` directory:

- **[go.md](claude/go.md)**: Go development patterns and practices
- **[fastapi.md](claude/fastapi.md)**: FastAPI server patterns with JWT auth and structured logging
- **[python-cli.md](claude/python-cli.md)**: Python CLI structure with Click
- **[deployment.md](claude/deployment.md)**: Kubernetes deployment patterns
- **[project-layout.md](claude/project-layout.md)**: Project structure conventions
- **[pyproject.md](claude/pyproject.md)**: Python project configuration
- **[ibis.md](claude/ibis.md)**: Data interface patterns with Ibis
- **[scikit-learn.md](claude/scikit-learn.md)**: ML workflow patterns
- **[openai-agents.md](claude/openai-agents.md)**: OpenAI Agents/Assistants patterns
- **[openai-webhooks.md](claude/openai-webhooks.md)**: OpenAI webhook handlers

## Core Development Philosophy

These templates and guidelines encode specific opinions about how software should be built:

### Unix Philosophy

- **Do one thing well** - Each component has a single, well-defined responsibility
- **Write programs that compose** - Design for piping and standard interfaces
- **Be quiet by default** - Only output when there's something unexpected to report
- **Use JSON for stdout** - Machine-readable output enables composition

### Explicit Over Magic

- **No frameworks** - Use standard library patterns when possible
- **Explicit dependencies** - Pass dependencies as parameters, no globals or singletons
- **Simple over complex** - Plain JSON, environment variables, standard SQL

### Production-Ready Defaults

- Structured logging (slog for Go, structlog for Python)
- Prometheus metrics built-in
- JWT authentication patterns
- Health check endpoints
- Graceful shutdown handling

## Feature Development Workflow

### 1. Plan Before Coding

Before implementing any feature:

- **Understand the requirement**: Clarify the use case and acceptance criteria
- **Design the interface first**: What's the API surface? How will clients use this?
- **Consider dependencies**: What components need to interact? What can be mocked?
- **Identify edge cases**: What can go wrong? How should errors be handled?
- **Document the plan**: Write down the approach in comments or a design doc

### 2. Write Tests First (TDD)

Follow Test-Driven Development when appropriate:

**Benefits:**
- Tests document intended behavior
- Forces thinking about the interface
- Prevents untested code
- Makes refactoring safer

**Coverage goals:**
- Unit tests: 80%+ coverage
- Integration tests for all critical paths
- E2E tests for main workflows

### 3. Server + Client Development

**Rule**: Every new server feature should have a corresponding client method, ideally one that's accessible via a CLI (sub)command.

### 4. Use the Makefile

Put frequently used commands in the `Makefile` for consistency:

```makefile
.PHONY: help
help: ## Show available targets
	@awk -F ':.*?## ' '/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: test
test: ## Run tests
	# go test ./... -v -race OR uv run pytest

.PHONY: lint
lint: ## Run linter
	# golangci-lint run OR uv run ruff check

.PHONY: run-dev
run-dev: ## Run with hot reload (logs to logs/)
	@mkdir -p logs
	# air 2>&1 | tee logs/server.log OR uvicorn --reload 2>&1 | tee logs/server.log
```

### 5. Hot Reloading for Development

Use hot reload tools for rapid development:

- **Go**: [Air](https://github.com/cosmtrek/air)
- **Python**: uvicorn with `--reload` flag

Configure to write logs to `logs/` directory for agent visibility.

### 6. Leverage tmux for Development

Use tmux to manage multiple terminal sessions efficiently (server, tests, logs, etc.).

## Git Workflow

### Branch Strategy

- **main**: Production-ready code, always stable
- **Feature branches**: `feature/wallet-polling`, `feature/nats-rpc`
- **Bug fixes**: `fix/jetstream-reconnect`
- **Experiments**: `experiment/new-approach`

### Commit Messages

Write comprehensive, descriptive commit messages that focus on the "why" rather than the "what".

**Format:**
```
[type]: Short summary (50 chars or less)

Detailed explanation of what changed and why. Wrap at 72 characters.
Include motivation, context, and any breaking changes.

- Bullet points for key changes
- Reference issues/PRs: Closes #123, Refs #456
- Note breaking changes: BREAKING: Changed API signature
```

**Types:** feat, fix, docs, refactor, test, chore, perf

## Documentation

### Always Update

When making changes, update relevant documentation:

1. **README.md**: Architecture, usage examples, getting started
2. **CHANGELOG.md**: User-facing changes
3. **Code comments**: Complex logic, public APIs, configuration options
4. **Examples**: Add/update examples in `examples/` directory

Use [Keep a Changelog](https://keepachangelog.com/) format for CHANGELOG.md.

## Code Quality

### Error Handling

**Always handle errors:**

```go
// Bad
txns, _ := client.GetTransactions(ctx)

// Good
txns, err := client.GetTransactions(ctx)
if err != nil {
    return fmt.Errorf("failed to get transactions: %w", err)
}
```

```python
# Bad
result = risky_operation()  # Might raise exception

# Good
try:
    result = risky_operation()
except SpecificError as e:
    logger.error("operation failed", error=str(e))
    raise
```

### Linting

Use strict linting and fix all warnings before committing:

- **Go**: `golangci-lint`
- **Python**: `ruff` for linting and formatting

## Design Patterns

### Make Dependencies Explicit

Following the dependency injection pattern, all dependencies should be explicit and passed as parameters. Never hide dependencies in global state, singletons, or package-level variables.

**Bad:**
```go
var db *sql.DB

func SaveTransaction(txn *Transaction) error {
    _, err := db.Exec("INSERT INTO transactions ...")
    return err
}
```

**Good:**
```go
type TransactionStore interface {
    Save(ctx context.Context, txn *Transaction) error
}

type PostgresStore struct {
    db *sql.DB
}

func NewPostgresStore(db *sql.DB) *PostgresStore {
    return &PostgresStore{db: db}
}

// Usage: Dependencies are clear at construction time
store := NewPostgresStore(db)
```

**Benefits:**
- **Testability**: Easy to mock dependencies
- **Clarity**: You can see exactly what a component needs
- **Flexibility**: Swap implementations (e.g., Postgres → SQLite for tests)
- **No hidden coupling**: Dependencies are visible in type signatures

### Avoid Frameworks, Embrace Standards

See language-specific guides for details:
- **Go**: Use stdlib `http.Handler` pattern with middleware composition (see [go.md](claude/go.md))
- **Python**: Use FastAPI with explicit dependency injection (see [fastapi.md](claude/fastapi.md))

## Structured Logging

Use structured logging with configurable levels via `LOG_LEVEL` env var:

- **Go**: `slog` with JSON handler to stderr
- **Python**: `structlog` with JSON renderer

Default to WARN in production, DEBUG in development.

### Development: Logging to Files

For local development, use `tee` to write logs to both stderr and files in `logs/`:

```bash
# Create logs directory
mkdir -p logs

# Run with tee to log to file
./server 2>&1 | tee -a logs/server.log

# Python example
uv run uvicorn server.main:app --reload 2>&1 | tee logs/server.log
```

This allows agents to tail logs to monitor system state:

```bash
# Find all errors
jq 'select(.level == "ERROR")' logs/server.log

# Monitor logs in real-time
tail -f logs/server.log | jq 'select(.level == "ERROR" or .level == "WARN")'
```

## Standard Project Structure

Templates follow these conventions:

### Common Elements

All templates include:
- **Makefile** with standard targets (build, test, lint, run-dev)
- **Dockerfile** with multi-stage builds
- **Kubernetes manifests** with Kustomize overlays
- **AGENTS.md** - context for AI coding agents
- **CHANGELOG.md** - Keep a Changelog format
- **logs/** and **data/** directories (gitignored for development)

### Go Projects

```
.
├── cmd/                # Entry points
│   ├── server/
│   └── client/
├── internal/           # Internal packages
├── migrations/         # SQL schema migrations
├── queries/            # SQL queries for sqlc
├── Makefile
├── .air.toml          # Air configuration
├── sqlc.yaml          # sqlc configuration
└── AGENTS.md
```

See [go.md](claude/go.md) for detailed Go patterns.

### Python Projects

```
.
├── src/               # Application package (editable install)
│   └── package/
│       ├── cli.py
│       └── ...
├── server/            # FastAPI app
│   └── main.py
├── tests/
├── pyproject.toml
├── Makefile
└── AGENTS.md
```

See [python-cli.md](claude/python-cli.md) and [fastapi.md](claude/fastapi.md) for detailed Python patterns.

## Security

- **Secrets Management**: Never commit credentials; use environment variables
- **NEVER commit `.env` files** to version control
- Always use `.env.example` as templates

## Common Tasks

### Environment Setup

Projects use separate env files per component:
- `.env.server` - Server environment
- `.env.client` - Client environment
- `.env.worker` - Worker environment

Load via Makefile pattern:

```makefile
define setup_env
    $(eval ENV_FILE := $(1))
    $(eval include $(1))
    $(eval export)
endef

run-server:
    $(call setup_env, .env.server)
    # run server command
```

### Database Migrations

For projects with databases:

```bash
# Create migration
migrate create -ext sql -dir migrations -seq add_feature

# Run migrations
make db-migrate

# Reset database (development only)
make db-reset
```

### Deployment

See [deployment.md](claude/deployment.md) for Kubernetes deployment patterns.

Standard pattern:
1. Build Docker image tagged with git hash
2. Push to registry
3. Apply Kustomize overlay with sed substitution
4. Image tag change triggers automatic rollout

## Language-Specific Guidelines

For detailed language and framework-specific patterns, see:

- **[Go Development](claude/go.md)**: Handler patterns, sqlc, urfave/cli, middleware composition
- **[FastAPI Servers](claude/fastapi.md)**: JWT auth, Prometheus, structlog, lifespan management
- **[Python CLI](claude/python-cli.md)**: Click structure, subcommand modules
- **[Data with Ibis](claude/ibis.md)**: Database-agnostic data interface patterns
- **[Machine Learning](claude/scikit-learn.md)**: scikit-learn pipelines, MLflow tracking
- **[OpenAI Agents](claude/openai-agents.md)**: Agents/Assistants workflows in Python and Go

## Project Templates

Use the templates in `project-templates/` to bootstrap new projects:

```bash
# Install cookiecutter
uv tool install cookiecutter

# Create a new project from template
cookiecutter project-templates/go-service
cookiecutter project-templates/python-service
cookiecutter project-templates/python-cli
cookiecutter project-templates/python-bayesian-experiment

# Validate templates
./project-templates/test-templates.py validate
```

See [project-templates/README.md](project-templates/README.md) for complete documentation.

## Questions?

When in doubt:

- Check existing code for patterns
- Refer to language-specific guides in `claude/`
- Review project templates for examples
- Ask for clarification rather than guessing
- Document decisions in commit messages

## Summary

These principles make systems:

- **Debuggable**: JSON logs are easily parsed and analyzed
- **Composable**: Outputs become inputs for other tools
- **Scriptable**: Predictable behavior enables automation
- **Maintainable**: Simple components are easier to understand and modify
- **Resilient**: Single-purpose tools fail independently

When in doubt, ask: "Does this add essential value, or does it just add complexity?"
