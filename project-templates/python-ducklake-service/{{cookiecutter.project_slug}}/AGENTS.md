# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Quick Reference

| Task | Command |
|------|---------|
| Install deps | `mise run setup` |
| Local services | `mise run services` |
| Run dev server | `mise run dev` |
| Run migrations | `mise run migrate` |
| Run the CLI | `mise run cli ...` |
| Run tests | `mise run test` |
| Run linter | `mise run lint` |
| Format code | `mise run fmt` |
| Deploy to K8s | `mise run deploy` |

`mise tasks` lists everything.

## Logs

Dev server logs to `logs/server.log`. View with:

```bash
tail -f logs/server.log
jq 'select(.level == "error")' logs/server.log
```

## Architecture

**Two databases, one application:**

- **DuckLake** (via DuckDB/Ibis): Analytics data lake. Catalog metadata in PostgreSQL, Parquet data in S3 (Garage locally). Accessed via `server/data/__init__.py` → `LakeConnection`.
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
| `server/data/__init__.py` | DuckLake connection (Ibis/DuckDB), `query()` with bound params |
| `server/live.py` | Live views: snapshot poll → render once → frames to every stream |
| `server/data/app_db.py` | PostgreSQL connection (psycopg2) |
| `server/routes/api.py` | JSON API: events, entities, query |
| `server/routes/pages.py` | Datastar pages: auth, live dashboard, entity search, entity detail |
| `static/js/components.js` | d3 charts as Datastar Rocket web components |
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

### SQL: bind every value

Never format a value into SQL. Lake: `lake.query(sql, [params])` with `?`
placeholders. App DB: `db.raw_sql(sql, (params,))` with `%s` placeholders.
Only identifiers you control (table names in migrations) may be formatted in.

### Frontend: Datastar

- **One long-lived read per live page.** Set `stream_url` in the page context;
  `base.html` opens it with `@get(..., {openWhenHidden: true})`. Add a live
  view to `VIEWS` in `server/live.py`: the renderer draws it once per lake
  snapshot and streams copy the frame. Stream handlers never render.
- **Writes never render.** They change the lake (or the app DB) and return
  data or nothing; the next frame shows the result.
- **One partial per live region**, with a stable `id` on its root element. The
  same partial renders the page load and every patch.
- **Charts are Rocket components**: render `<chart-bars id="..." series='{% raw %}{{ rows|tojson }}{% endraw %}'>`
  in the partial. Use single quotes around `tojson` (it escapes `'`, not `"`).
  Chart data lives in attributes, never in signals.
- **Signals only for UI state and form inputs** (the search box). Anything the
  server knows belongs in the HTML it sends.
- Inputs keep `font-size: 16px` or iOS Safari zooms on focus.

### Migrations

- **App migrations**: Numbered SQL files in `migrations/app/` (e.g., `001_users_sessions.up.sql`)
- **Lake migrations**: Python definitions in `migrations/lake.py`
- Both tracked in `_migrations` table with namespace isolation
- Lake migrations run in DuckDB but are tracked in the app database (namespace `lake`); `lake reset --confirm` clears that history
- Run with `mise run migrate`

### Authentication

Magic link flow: email → JWT token → session cookie. In dev mode (`DEV_MODE=true`), all requests are auto-authenticated.

### Click CLI

Subcommand groups: `serve`, `migrate`, `lake {list,reset,snapshots}`, `app {reset}`.

### Adding New Features

1. **New API endpoint**: Add route in `server/routes/api.py` (or create a new router module and include it in `server/routes/__init__.py` + `server/main.py`)
2. **New lake table**: Add migration in `migrations/lake.py`
3. **New app table**: Create `migrations/app/NNN_description.up.sql` (and `.down.sql`)
4. **New page**: Add template in `templates/`, route in `server/routes/pages.py`. Live? Put the region in a `_partial.html`, add it to `VIEWS` in `server/live.py`, and add a stream route like `/dashboard/stream`
5. **New CLI command**: Add to `src/{{cookiecutter.package_name}}/cli.py`

## Development

```bash
cp .env.example .env    # set JWT_SECRET (openssl rand -hex 32)
mise run setup
mise run services       # Postgres + Garage (S3) with the bucket
mise run migrate
mise run dev            # tees to logs/server.log
mise run cli lake list
```

The CLI must run from the project root via `mise run cli` (`python -m`): it
imports the top-level `server/` and `migrations/` packages, which the installed
console script cannot see.

## Testing

```bash
mise run test     # tests/test_health.py needs services; SKIP_INTEGRATION=1 skips it
mise run lint
mise run fmt
```

## Changelog

When merging features, update `CHANGELOG.md`:

1. Add entry under `[Unreleased]` in the appropriate category
2. Use imperative mood: "Add feature" not "Added feature"
3. Reference issue numbers if applicable

Categories: Added, Changed, Deprecated, Removed, Fixed, Security
