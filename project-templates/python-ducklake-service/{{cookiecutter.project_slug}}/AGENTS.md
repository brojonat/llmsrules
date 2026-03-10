# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Quick Reference

| Task | Command |
|------|---------|
| Install deps | `make install` |
| Run dev server | `make run-dev` |
| Run migrations | `make migrate` |
| Run tests | `make test` |
| Run linter | `make lint` |
| Format code | `make format` |
| Download JS libs | `make setup-js` |
| Deploy to K8s | `make deploy` |

## Logs

Dev server logs to `logs/server.log`. View with:

```bash
tail -f logs/server.log
jq 'select(.level == "error")' logs/server.log
```

## Architecture

**Two databases, one application:**

- **DuckLake** (via DuckDB/Ibis): Analytics data lake. Catalog metadata in PostgreSQL, Parquet data in S3/MinIO. Accessed via `server/data/lake.py` → `LakeConnection`.
- **PostgreSQL** (via psycopg2): Application state (users, sessions, tags). Accessed via `server/data/app_db.py` → `AppDB`.

**Key files:**

| File | Purpose |
|------|---------|
| `server/main.py` | FastAPI app, lifespan, middleware |
| `server/config.py` | Pydantic-settings (`{{cookiecutter.package_name_upper}}_` prefix) |
| `server/deps.py` | FastAPI DI: `LakeDep`, `AppDbDep`, `SessionDep` |
| `server/log_config.py` | structlog configuration |
| `server/metrics.py` | Prometheus metrics definitions |
| `server/email.py` | SMTP sender for magic links |
| `server/lake_admin.py` | Lake list/reset/S3 helpers |
| `server/auth/jwt.py` | JWT create/decode |
| `server/auth/session.py` | Session model + in-memory store |
| `server/auth/magic_link.py` | Magic link create/verify |
| `server/data/lake.py` | DuckLake connection (Ibis/DuckDB) |
| `server/data/app_db.py` | PostgreSQL connection (psycopg2) |
| `server/routes/api.py` | JSON API: events, entities, query |
| `server/routes/pages.py` | HTMX pages: auth, dashboard, list |
| `server/routes/tags.py` | Tag CRUD + entity tagging |
| `src/{{cookiecutter.package_name}}/cli.py` | Click CLI: serve, migrate, lake, app |
| `migrations/runner.py` | Namespace-aware migration runner |
| `migrations/lake.py` | Lake DDL (events table) |
| `migrations/app/*.sql` | Numbered app migration files |

## Conventions

### Dependency Injection

All FastAPI routes use typed dependencies:

```python
from server.deps import LakeDep, AppDbDep, SessionDep

@router.get("/example")
async def example(lake: LakeDep, db: AppDbDep, session: SessionDep):
    ...
```

- `LakeDep` → `LakeConnection` (DuckDB/Ibis)
- `AppDbDep` → `AppDB` (PostgreSQL)
- `SessionDep` → `Session` (requires auth; auto-auth in dev mode)
- `OptionalSessionDep` → `Session | None`
- `SettingsDep` → `Settings`
- `BaseUrlDep` → `str`

### Configuration

Environment variables use the `{{cookiecutter.package_name_upper}}_` prefix. Settings are validated by Pydantic at startup. See `server/config.py` for all options and `.env.example` for defaults.

### Structured Logging

```python
from server.log_config import get_logger
log = get_logger(__name__)
log.info("event_name", key="value")
```

JSON in production, colored console in development. Request context (request_id, path, method) is bound automatically by middleware.

### Migrations

- **App migrations**: Numbered SQL files in `migrations/app/` (e.g., `001_users_sessions.up.sql`)
- **Lake migrations**: Python definitions in `migrations/lake.py`
- Both tracked in `_migrations` table with namespace isolation
- Run with `make migrate` or `{{cookiecutter.project_slug}} migrate`

### Authentication

Magic link flow: email → JWT token → session cookie. In dev mode (`DEV_MODE=true`), all requests are auto-authenticated.

### Click CLI

Subcommand groups: `serve`, `migrate`, `lake {list,reset,snapshots}`, `app {reset}`.

### Adding New Features

1. **New API endpoint**: Add route in `server/routes/api.py` (or create a new router module and include it in `server/routes/__init__.py` + `server/main.py`)
2. **New lake table**: Add migration in `migrations/lake.py`
3. **New app table**: Create `migrations/app/NNN_description.up.sql` (and `.down.sql`)
4. **New HTMX page**: Add template in `templates/`, route in `server/routes/pages.py`
5. **New CLI command**: Add to `src/{{cookiecutter.package_name}}/cli.py`

## Development

```bash
# Install dependencies
uv sync --all-extras

# Start local services
docker compose up -d

# Configure environment
cp .env.example .env.server

# Run migrations
make migrate

# Run with hot reload
make run-dev

# Run CLI
uv run {{cookiecutter.project_slug}} lake list
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
