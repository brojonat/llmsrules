# Project Templates

A collection of cookiecutter templates for standardizing project scaffolding
across repositories.

## For Agents

This README contains everything needed to implement the cookiecutter templates.
For each template:

1. Create the directory structure shown in
   [Directory Structure](#directory-structure)
2. Implement files using patterns from
   [Implementation Reference](#implementation-reference)
3. Use the template variables from [Template Variables](#template-variables)
4. Test by running `cookiecutter path/to/template` and verifying the output

The TODO section has a checklist of all required files.

## Goals

- Provide consistent project structure across different project types
- Standardize common configurations (Makefiles, Kubernetes, environment
  management)
- Reduce boilerplate and setup time for new projects
- Enforce best practices and conventions

## Design Principles

These templates encode specific opinions about how software should be built:

### Unix Philosophy

- **Do one thing well** - Each component has a single, well-defined
  responsibility
- **Write programs that compose** - Design for piping and standard interfaces
- **Be quiet by default** - Only output when there's something unexpected to
  report
- **Use JSON for stdout** - Machine-readable output enables composition

### Explicit Over Magic

- **No frameworks** - Use standard library patterns (Go stdlib, FastAPI without
  magic)
- **Explicit dependencies** - Pass dependencies as parameters, no globals or
  singletons
- **Simple over complex** - Plain JSON, environment variables, standard SQL

### Production-Ready Defaults

- Structured logging (slog for Go, structlog for Python)
- Prometheus metrics built-in
- JWT authentication patterns
- Health check endpoints
- Graceful shutdown handling

## Planned Templates

### go-service

Go microservice following stdlib patterns:

- HTTP handlers as functions returning `http.Handler`
- Middleware composition with `adaptHandler` pattern
- CLI with `urfave/cli`
- Database access with `sqlc` (no ORM)
- Structured logging with `slog`
- Air for hot reloading in development

### python-service

Python service with modern tooling:

- FastAPI server with lifespan management
- Click CLI with subcommand structure
- `uv` for dependency management
- `structlog` for structured logging
- `src` layout for clean editable installs
- Ruff for linting/formatting

## Shared Components

Each template includes standardized versions of:

### Makefile

```makefile
# Environment loading pattern
define setup_env
    $(eval ENV_FILE := $(1))
    $(eval include $(1))
    $(eval export)
endef

# Standard targets
help:           ## Show available targets
build:          ## Build the project
test:           ## Run tests
lint:           ## Run linter
run-dev:        ## Run with hot reload (logs to logs/)
run:            ## Run production build
clean:          ## Clean build artifacts
deploy:         ## Deploy to Kubernetes (builds, pushes, applies)

# Dev targets use tee to write logs for agent visibility
run-dev:
    @mkdir -p logs
    $(call setup_env, .env.server)
    air 2>&1 | tee logs/server.log
```

### Kubernetes Configs

```
service/
└── k8s/
    └── prod/
        ├── kustomization.yaml
        ├── deployment.yaml
        └── ingress.yaml
```

- Kustomize overlays for environments (dev, staging, prod)
- Git SHA tagging for deployments
- Template variables for docker registry and image tags

### Environment Management

- `.env.example` files alongside code
- Separate env files per component: `.env.server`, `.env.worker`, `.env.client`
- Makefile `setup_env` pattern for loading env vars
- Never commit actual `.env` files

### Development Directories (gitignored)

#### logs/

Process logs for local development. The `run-dev` target uses `tee` to write
output to `logs/{process-name}.log` so coding agents can inspect logs:

```bash
# Makefile pattern
run-dev:
    @mkdir -p logs
    air 2>&1 | tee logs/server.log

run-worker:
    @mkdir -p logs
    go run ./cmd/worker 2>&1 | tee logs/worker.log
```

Agents can tail logs in real-time or parse JSON logs with `jq`:

```bash
tail -f logs/server.log
jq 'select(.level == "ERROR")' logs/server.log
```

#### data/

Local data dumps, database bootstrapping files, or test fixtures that shouldn't
be version controlled. Examples:

- `data/seed.sql` - Database seed data
- `data/fixtures.json` - Test fixtures
- `data/exports/` - Exported data dumps

### AGENTS.md

Each template includes an `AGENTS.md` file that provides context for AI coding
agents working on the project. This file describes:

- Project architecture and key patterns
- How to run tests and development servers
- Where logs are written and how to read them
- Important conventions and gotchas
- File locations for common tasks
- Instructions to update CHANGELOG.md when features are merged

### CHANGELOG.md

Each template includes a `CHANGELOG.md` following the
[Keep a Changelog](https://keepachangelog.com/) format:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

## [0.1.0] - YYYY-MM-DD

### Added

- Initial release
```

**Workflow:**

- Add entries to `[Unreleased]` as features are developed
- When releasing, move `[Unreleased]` items to a new version section
- Categories: Added, Changed, Deprecated, Removed, Fixed, Security

### Docker

Multi-stage builds:

```dockerfile
# Builder stage - compile with all tools
FROM golang:1.24-alpine AS builder
# ... build steps ...

# Final stage - minimal runtime image
FROM alpine:latest
COPY --from=builder /bin/app /app
```

### Logging

Structured JSON logging with configurable levels via `LOG_LEVEL` env var:

- Go: `slog` with JSON handler to stderr
- Python: `structlog` with JSON renderer

Default to WARN in production, DEBUG in development.

## Directory Structure

```
project-templates/
├── README.md
├── go-service/
│   ├── cookiecutter.json
│   └── {{cookiecutter.project_slug}}/
│       ├── .gitignore
│       ├── AGENTS.md
│       ├── CHANGELOG.md
│       ├── Makefile
│       ├── Dockerfile
│       ├── .air.toml
│       ├── .env.example
│       ├── cmd/
│       │   └── server/
│       │       └── main.go
│       ├── internal/
│       │   └── db/                   # sqlc generated code
│       ├── migrations/
│       ├── queries/                  # sqlc SQL files
│       ├── k8s/
│       │   └── prod/
│       ├── sqlc.yaml
│       ├── logs/                     # gitignored - dev logs
│       │   └── .gitkeep
│       └── data/                     # gitignored - local data
│           └── .gitkeep
└── python-service/
    ├── cookiecutter.json
    └── {{cookiecutter.project_slug}}/
        ├── .gitignore
        ├── AGENTS.md
        ├── CHANGELOG.md
        ├── Makefile
        ├── Dockerfile
        ├── pyproject.toml
        ├── .env.example
        ├── src/
        │   └── {{cookiecutter.package_name}}/
        │       ├── __init__.py
        │       └── cli.py
        ├── server/
        │   └── main.py
        ├── k8s/
        │   └── prod/
        ├── logs/                     # gitignored - dev logs
        │   └── .gitkeep
        └── data/                     # gitignored - local data
            └── .gitkeep
```

## Usage

```bash
# Install cookiecutter
uv tool install cookiecutter

# Create a new Go service
cookiecutter path/to/project-templates/go-service

# Create a new Python service
cookiecutter path/to/project-templates/python-service
```

## Template Variables

### Common Variables

| Variable          | Description                 | Example            |
| ----------------- | --------------------------- | ------------------ |
| `project_name`    | Human-readable project name | "My Service"       |
| `project_slug`    | Directory/package name      | "my-service"       |
| `description`     | Short project description   | "A service that…"  |
| `author`          | Author name                 | "Your Name"        |
| `docker_registry` | Container registry URL      | "ghcr.io/username" |
| `k8s_namespace`   | Kubernetes namespace        | "default"          |

### Go-specific Variables

| Variable | Description    | Example                |
| -------- | -------------- | ---------------------- |
| `go_mod` | Go module path | "github.com/user/repo" |

### Python-specific Variables

| Variable         | Description         | Example      |
| ---------------- | ------------------- | ------------ |
| `package_name`   | Python package name | "my_service" |
| `python_version` | Python version      | "3.13"       |

## Implementation Reference

### Go Makefile

```makefile
SHELL := /bin/bash

define setup_env
    $(eval ENV_FILE := $(1))
    $(eval include $(1))
    $(eval export)
endef

.PHONY: help
help: ## Show available targets
	@awk -F ':.*?## ' '/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: build
build: ## Build the binary
	go build -o bin/{{cookiecutter.project_slug}} ./cmd/server

.PHONY: test
test: ## Run tests
	go test ./... -v -race

.PHONY: lint
lint: ## Run linter
	golangci-lint run

.PHONY: run-dev
run-dev: ## Run with hot reload (logs to logs/)
	@mkdir -p logs
	$(call setup_env, .env.server)
	air 2>&1 | tee logs/server.log

.PHONY: run
run: build ## Run production binary
	$(call setup_env, .env.server)
	./bin/{{cookiecutter.project_slug}}

.PHONY: clean
clean: ## Clean build artifacts
	rm -rf bin/ tmp/ logs/*.log

.PHONY: sqlc
sqlc: ## Generate sqlc code
	sqlc generate

.PHONY: migrate
migrate: ## Run database migrations
	$(call setup_env, .env.server)
	migrate -path migrations -database "$$DATABASE_URL" up

.PHONY: deploy
deploy: ## Build, push, and deploy to Kubernetes
	$(call setup_env, .env.prod)
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	docker build -t $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH) .
	docker push $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH)
	kustomize build k8s/prod | \
		sed -e "s;{{DOCKER_REPO}};$(DOCKER_REGISTRY)/{{cookiecutter.project_slug}};g" \
		    -e "s;{{GIT_COMMIT_SHA}};$(GIT_HASH);g" | \
		kubectl apply -f -
```

### Python Makefile

```makefile
SHELL := /bin/bash

define setup_env
    $(eval ENV_FILE := $(1))
    $(eval include $(1))
    $(eval export)
endef

.PHONY: help
help: ## Show available targets
	@awk -F ':.*?## ' '/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: install
install: ## Install dependencies
	uv sync

.PHONY: test
test: ## Run tests
	uv run pytest

.PHONY: lint
lint: ## Run linter
	uv run ruff check src/ server/ tests/
	uv run ruff format --check src/ server/ tests/

.PHONY: format
format: ## Format code
	uv run ruff format src/ server/ tests/
	uv run ruff check --fix src/ server/ tests/

.PHONY: run-dev
run-dev: ## Run server with auto-reload (logs to logs/)
	@mkdir -p logs
	$(call setup_env, .env.server)
	uv run uvicorn server.main:app --reload --host 0.0.0.0 --port 8000 2>&1 | tee logs/server.log

.PHONY: run
run: ## Run production server
	$(call setup_env, .env.server)
	uv run uvicorn server.main:app --host 0.0.0.0 --port 8000

.PHONY: clean
clean: ## Clean build artifacts
	rm -rf .venv/ __pycache__/ .pytest_cache/ .ruff_cache/ logs/*.log dist/

.PHONY: deploy
deploy: ## Build, push, and deploy to Kubernetes
	$(call setup_env, .env.prod)
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	docker build -t $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH) .
	docker push $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH)
	kustomize build k8s/prod | \
		sed -e "s;{{DOCKER_REPO}};$(DOCKER_REGISTRY)/{{cookiecutter.project_slug}};g" \
		    -e "s;{{GIT_COMMIT_SHA}};$(GIT_HASH);g" | \
		kubectl apply -f -
```

### Go Patterns

#### HTTP Handler Pattern

Write functions that return `http.Handler` with explicit dependencies:

```go
func handleListItems(store Store, logger *slog.Logger) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        ctx := r.Context()
        items, err := store.ListItems(ctx)
        if err != nil {
            logger.ErrorContext(ctx, "failed to list items", "error", err)
            http.Error(w, "internal error", http.StatusInternalServerError)
            return
        }
        w.Header().Set("Content-Type", "application/json")
        json.NewEncoder(w).Encode(items)
    })
}
```

#### Middleware Adapter Pattern

```go
type adapter func(http.Handler) http.Handler

func adaptHandler(h http.Handler, adapters ...adapter) http.Handler {
    for i := len(adapters) - 1; i >= 0; i-- {
        h = adapters[i](h)
    }
    return h
}

// Usage
mux.Handle("GET /items", adaptHandler(
    handleListItems(store, logger),
    withRequestID(),
    withLogging(logger),
    withJWTAuth(jwtSecret),
))
```

#### Example Adapters

```go
func withLogging(logger *slog.Logger) adapter {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            start := time.Now()
            next.ServeHTTP(w, r)
            logger.InfoContext(r.Context(), "request",
                "method", r.Method,
                "path", r.URL.Path,
                "duration", time.Since(start),
            )
        })
    }
}

func withJWTAuth(secret []byte) adapter {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            authHeader := r.Header.Get("Authorization")
            tokenString := strings.TrimPrefix(authHeader, "Bearer ")
            token, err := jwt.Parse(tokenString, func(t *jwt.Token) (interface{}, error) {
                return secret, nil
            })
            if err != nil || !token.Valid {
                http.Error(w, "unauthorized", http.StatusUnauthorized)
                return
            }
            if claims, ok := token.Claims.(jwt.MapClaims); ok {
                ctx := context.WithValue(r.Context(), "claims", claims)
                next.ServeHTTP(w, r.WithContext(ctx))
                return
            }
            http.Error(w, "unauthorized", http.StatusUnauthorized)
        })
    }
}
```

#### CLI with urfave/cli

```go
func main() {
    app := &cli.App{
        Name:  "{{cookiecutter.project_slug}}",
        Usage: "{{cookiecutter.description}}",
        Commands: []*cli.Command{
            {
                Name:  "server",
                Usage: "Start the HTTP server",
                Flags: []cli.Flag{
                    &cli.StringFlag{
                        Name:    "addr",
                        Value:   ":8080",
                        EnvVars: []string{"SERVER_ADDR"},
                    },
                    &cli.StringFlag{
                        Name:    "log-level",
                        Value:   "warn",
                        EnvVars: []string{"LOG_LEVEL"},
                    },
                },
                Action: runServer,
            },
        },
    }
    if err := app.Run(os.Args); err != nil {
        log.Fatal(err)
    }
}
```

#### sqlc Configuration

```yaml
# sqlc.yaml
version: "2"
sql:
  - engine: "postgresql"
    queries: "queries/"
    schema: "migrations/"
    gen:
      go:
        package: "db"
        out: "internal/db"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_interface: true
```

#### Structured Logging Setup

```go
func setupLogger(levelStr string) *slog.Logger {
    var level slog.Level
    switch strings.ToUpper(levelStr) {
    case "DEBUG":
        level = slog.LevelDebug
    case "INFO":
        level = slog.LevelInfo
    case "WARN":
        level = slog.LevelWarn
    case "ERROR":
        level = slog.LevelError
    default:
        level = slog.LevelWarn
    }
    return slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: level}))
}
```

### Python Patterns

#### FastAPI Server with JWT Auth

```python
import os
from contextlib import asynccontextmanager
from typing import Dict

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from prometheus_fastapi_instrumentator import Instrumentator

# Logging
def configure_logging() -> None:
    import logging
    import sys
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "WARNING").upper())
    logging.basicConfig(level=log_level, stream=sys.stdout)
    processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
    )

configure_logging()
log = structlog.get_logger()

# Auth
JWT_SECRET = os.getenv("AUTH_SECRET", "change-me")
security = HTTPBearer(auto_error=True)

def require_claims(creds: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    try:
        return jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

# App
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("service.startup")
    yield
    log.info("service.shutdown")

app = FastAPI(title="{{cookiecutter.project_name}}", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/whoami")
def whoami(claims: Dict = Depends(require_claims)):
    return {"claims": claims}
```

#### Click CLI Structure

```python
# src/{{cookiecutter.package_name}}/cli.py
import click

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

@click.group(context_settings=CONTEXT_SETTINGS)
def cli() -> None:
    """{{cookiecutter.description}}"""
    pass

@cli.command()
@click.option("--name", "-n", default="world")
def hello(name: str) -> None:
    """Example subcommand."""
    click.echo(f"Hello, {name}!")

def main() -> None:
    cli()

if __name__ == "__main__":
    main()
```

#### pyproject.toml

```toml
[project]
name = "{{cookiecutter.project_slug}}"
version = "0.1.0"
description = "{{cookiecutter.description}}"
authors = [{name = "{{cookiecutter.author}}"}]
requires-python = ">={{cookiecutter.python_version}}"
dependencies = [
    "click>=8.0",
    "fastapi>=0.100",
    "uvicorn[standard]>=0.20",
    "python-jose[cryptography]>=3.3",
    "structlog>=23.0",
    "prometheus-fastapi-instrumentator>=6.0",
]

[project.scripts]
{{cookiecutter.project_slug}} = "{{cookiecutter.package_name}}.cli:main"

[build-system]
requires = ["setuptools>=68.0.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
target-version = "py313"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.pytest.ini_options]
python_files = ["test_*.py", "*_test.py"]
```

### Kubernetes Patterns

#### Deployment with Kustomize

```yaml
# k8s/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - ingress.yaml
```

```yaml
# k8s/prod/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: { { cookiecutter.project_slug } }
spec:
  replicas: 2
  selector:
    matchLabels:
      app: { { cookiecutter.project_slug } }
  template:
    metadata:
      labels:
        app: { { cookiecutter.project_slug } }
    spec:
      containers:
        - name: { { cookiecutter.project_slug } }
          image: "{{DOCKER_REPO}}:{{GIT_COMMIT_SHA}}"
          ports:
            - containerPort: 8080
          env:
            - name: LOG_LEVEL
              value: "warn"
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
```

#### Makefile Deploy Target

```makefile
deploy:
	$(call setup_env, .env.prod)
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	docker build -t $(DOCKER_REGISTRY)/$(PROJECT_SLUG):$(GIT_HASH) .
	docker push $(DOCKER_REGISTRY)/$(PROJECT_SLUG):$(GIT_HASH)
	kustomize build k8s/prod | \
		sed -e "s;{{DOCKER_REPO}};$(DOCKER_REGISTRY)/$(PROJECT_SLUG);g" \
		    -e "s;{{GIT_COMMIT_SHA}};$(GIT_HASH);g" | \
		kubectl apply -f -
```

### Go Dockerfile

```dockerfile
FROM golang:1.24-alpine AS builder
RUN apk add --no-cache git ca-certificates
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /bin/app ./cmd/server

FROM alpine:latest
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /bin/app /app
EXPOSE 8080
CMD ["/app"]
```

### Python Dockerfile

```dockerfile
FROM python:{{cookiecutter.python_version}}-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system .

FROM python:{{cookiecutter.python_version}}-slim
COPY --from=builder /usr/local/lib/python{{cookiecutter.python_version}}/site-packages /usr/local/lib/python{{cookiecutter.python_version}}/site-packages
COPY --from=builder /usr/local/bin/{{cookiecutter.project_slug}} /usr/local/bin/
COPY server/ server/
EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Go .gitignore

```gitignore
# Binaries
bin/
*.exe

# Build artifacts
tmp/

# Environment files
.env
.env.*
!.env.example

# Development
logs/
data/

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
```

### Python .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/
dist/
build/

# Environment files
.env
.env.*
!.env.example

# Development
logs/
data/

# Testing
.pytest_cache/
.coverage
htmlcov/

# Linting
.ruff_cache/

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
```

### Air Configuration (.air.toml)

```toml
root = "."
tmp_dir = "tmp"

[build]
bin = "./tmp/main"
cmd = "go build -o ./tmp/main ./cmd/server"
delay = 1000
exclude_dir = ["assets", "tmp", "vendor", "bin", "logs", "data", "k8s", "migrations"]
include_ext = ["go", "tpl", "tmpl", "html"]
exclude_regex = ["_test\\.go"]
kill_delay = "2s"

[log]
time = false

[misc]
clean_on_exit = true
```

### AGENTS.md Template

````markdown
# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Quick Reference

| Task           | Command        |
| -------------- | -------------- |
| Run dev server | `make run-dev` |
| Run tests      | `make test`    |
| Run linter     | `make lint`    |
| Build          | `make build`   |
| Deploy         | `make deploy`  |

## Logs

Dev server logs to `logs/server.log`. View with:

```bash
tail -f logs/server.log
jq 'select(.level == "ERROR")' logs/server.log
```
````

## Architecture

- HTTP handlers in `cmd/server/` (Go) or `server/` (Python)
- Business logic in `internal/` (Go) or `src/{{package}}/` (Python)
- Database queries in `queries/` (sqlc) or inline (Python)

## Conventions

- Handlers are functions returning `http.Handler` (Go) or FastAPI routes
  (Python)
- All dependencies passed explicitly (no globals)
- Structured JSON logging via slog/structlog
- JWT auth via Bearer token

## Changelog

When merging features, update `CHANGELOG.md`:

1. Add entry under `[Unreleased]` in the appropriate category
2. Use imperative mood: "Add feature" not "Added feature"
3. Reference issue numbers if applicable

Categories: Added, Changed, Deprecated, Removed, Fixed, Security

````

### cookiecutter.json

#### go-service

```json
{
  "project_name": "My Service",
  "project_slug": "{{ cookiecutter.project_name.lower().replace(' ', '-') }}",
  "description": "A Go microservice",
  "author": "Your Name",
  "go_mod": "github.com/{{ cookiecutter.author.lower().replace(' ', '') }}/{{ cookiecutter.project_slug }}",
  "docker_registry": "ghcr.io/{{ cookiecutter.author.lower().replace(' ', '') }}",
  "k8s_namespace": "default"
}
````

#### python-service

```json
{
  "project_name": "My Service",
  "project_slug": "{{ cookiecutter.project_name.lower().replace(' ', '-') }}",
  "package_name": "{{ cookiecutter.project_slug.replace('-', '_') }}",
  "description": "A Python microservice",
  "author": "Your Name",
  "python_version": "3.13",
  "docker_registry": "ghcr.io/{{ cookiecutter.author.lower().replace(' ', '') }}",
  "k8s_namespace": "default"
}
```

## Testing Templates

After implementing a template, verify it works:

```bash
# Test go-service template
cookiecutter go-service --no-input project_name="Test Service" project_slug="test-service"
cd test-service
make build    # Should compile
make test     # Should pass
make run-dev  # Should start server and log to logs/server.log

# Test python-service template
cookiecutter python-service --no-input project_name="Test Service" project_slug="test-service"
cd test-service
uv sync       # Should install deps
make test     # Should pass
make run-dev  # Should start server and log to logs/server.log
```

## TODO

- [ ] Define cookiecutter.json schema for each template
- [ ] Create go-service template
  - [ ] Makefile with standard targets (tee to logs/)
  - [ ] Multi-stage Dockerfile
  - [ ] HTTP server with handler pattern
  - [ ] sqlc configuration
  - [ ] Air hot reload config
  - [ ] K8s manifests with kustomize
  - [ ] .gitignore (logs/, data/, .env files, binaries)
  - [ ] AGENTS.md (with changelog instructions)
  - [ ] CHANGELOG.md
- [ ] Create python-service template
  - [ ] Makefile with standard targets (tee to logs/)
  - [ ] Multi-stage Dockerfile
  - [ ] FastAPI server with JWT auth
  - [ ] Click CLI scaffold
  - [ ] pyproject.toml with ruff/pytest config
  - [ ] K8s manifests with kustomize
  - [ ] .gitignore (logs/, data/, .env files, **pycache**, .venv)
  - [ ] AGENTS.md (with changelog instructions)
  - [ ] CHANGELOG.md
- [ ] Add GitHub Actions workflow templates
- [ ] Add pre-commit hook configurations
