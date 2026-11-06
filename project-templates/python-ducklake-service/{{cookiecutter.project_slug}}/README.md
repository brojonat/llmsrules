# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐
│   Browser   │────▶│   FastAPI    │────▶│ DuckLake  │
│ (Datastar)  │◀────│   + Jinja2   │     │ (DuckDB)  │
└─────────────┘ SSE └──────┬───────┘     └─────┬─────┘
                           │                   │
                    ┌──────▼───────┐     ┌─────▼──────┐
                    │  PostgreSQL  │     │ S3 (Seaweed│
                    │  (app state) │     │ FS locally)│
                    └──────────────┘     └────────────┘
```

**Two databases, one application:**

- **DuckLake** (via DuckDB + Ibis): Analytics data lake with time travel, snapshots, and ACID transactions. Catalog metadata stored in PostgreSQL; Parquet data files stored in S3 (SeaweedFS for local dev).
- **PostgreSQL** (via psycopg2): Application state -- users, sessions, tags, entity associations, and migration tracking.

## Quick Start

```bash
cp .env.example .env    # then set JWT_SECRET: openssl rand -hex 32
mise run setup          # uv sync
mise run services       # Postgres + SeaweedFS in Docker, creates the bucket
mise run migrate        # lake + app migrations
mise run dev            # hot reload, tee to logs/server.log
```

Open http://localhost:8000. In dev mode (`DEV_MODE=true`), all requests are
auto-authenticated. The server refuses to start while `JWT_SECRET` is still the
`.env.example` placeholder.

Put some events in the lake and watch the dashboard update on its own:

```bash
curl -X POST localhost:8000/api/events -H 'content-type: application/json' \
  -d '[{"timestamp": "2026-01-01T12:00:00", "entity_id": "user/1", "event_type": "click"}]'
```

## Quick Reference

| Task | Command |
|------|---------|
| Install deps | `mise run setup` |
| Start / stop local services | `mise run services` / `mise run services:down` |
| Run dev server | `mise run dev` |
| Run migrations | `mise run migrate` |
| Run the CLI | `mise run cli lake snapshots` |
| Run tests | `mise run test` |
| Run linter | `mise run lint` |
| Format code | `mise run fmt` |
| Deploy to K8s | `mise run deploy` |

`mise tasks` lists everything.

## Frontend: Datastar

Pages are server-rendered Jinja2. [Datastar](https://data-star.dev) adds the
interactivity, and there is no build step: `templates/base.html` loads the
Datastar bundle (with Rocket) and d3 from a CDN through an import map.

- **The dashboard is live.** It opens one long-lived SSE stream
  (`/dashboard/stream`). `server/live.py` polls the lake's latest snapshot id,
  which changes on every write from any process, and re-renders the dashboard
  once per change for all viewers. Streams only copy the newest frame, and
  Datastar morphs it in. Writes (`POST /api/events`, an ingest job, anything
  that commits to the lake) never render anything themselves.
- **Search is a one-shot patch.** The entities search box binds a `search`
  signal and, debounced, `@get`s `/entities/rows`, which answers with the
  `#entity-list` rows.
- **Charts are d3 in Rocket web components** (`static/js/components.js`). The
  server renders `<chart-bars id="..." series='[...]'>` as part of the HTML;
  when a morph changes the attribute, d3 redraws with a transition. The
  component draws in an open shadow root, so morphs never touch the SVG.

The same partial (`templates/_dashboard.html`, `templates/_entity_rows.html`)
renders the first page load and every later patch.

## Project Structure

```
├── server/                  # FastAPI application
│   ├── main.py              # App + lifespan + middleware
│   ├── config.py            # Pydantic-settings ({{cookiecutter.package_name_upper}}_ prefix)
│   ├── deps.py              # DI: LakeDep, AppDbDep, SessionDep
│   ├── log_config.py        # structlog setup
│   ├── metrics.py           # Prometheus counters/histograms
│   ├── email.py             # SMTP magic link emails
│   ├── lake_admin.py        # Lake list/reset/S3 helpers
│   ├── auth/                # JWT, sessions, magic links
│   ├── data/                # LakeConnection (Ibis), AppDB (psycopg2)
│   ├── live.py              # Live views: snapshot poll -> render -> stream frames
│   └── routes/              # api.py, pages.py, tags.py
├── src/{{cookiecutter.package_name}}/  # Installable CLI package
│   └── cli.py               # Click: serve, migrate, lake, app
├── migrations/              # SQL + Python migration system
│   ├── runner.py            # Namespace-aware runner
│   ├── lake.py              # Lake DDL (events table)
│   └── app/                 # Numbered .up.sql / .down.sql files
├── templates/               # Jinja2 pages; _*.html partials are what streams patch
├── static/css/              # CSS with dark/light theme
├── static/js/components.js  # d3 charts as Datastar Rocket components
├── tests/                   # pytest suite
├── k8s/prod/                # Kustomize manifests
├── docker-compose.yml       # Local dev: Postgres + SeaweedFS (S3)
├── scripts/deploy.sh        # Build, push, kustomize apply
└── mise.toml                # All common tasks
```

## Data Model

### Lake: Events Table

Generic events table for analytics use cases:

```sql
CREATE TABLE lake.events (
    timestamp   TIMESTAMP NOT NULL,
    entity_id   VARCHAR NOT NULL,
    event_type  VARCHAR NOT NULL,
    value       DOUBLE,
    value_string VARCHAR,
    metadata    JSON,
    date        VARCHAR       -- partition column
);
```

### App DB: Users, Sessions, Tags

- **users** (id UUID, email UNIQUE, created_at, last_login_at)
- **sessions** (session_id UUID, user_id FK, created_at, expires_at)
- **tags** (id UUID, tag_type, key, value, description, created_by FK, UNIQUE(tag_type,key,value))
- **entity_tags** (id UUID, tag_id FK, entity_type, entity_id, created_by FK, UNIQUE(tag_id,entity_type,entity_id))

## Configuration

All environment variables use the `{{cookiecutter.package_name_upper}}_` prefix. See `.env.example` for the full list.

**Required:**
- `{{cookiecutter.package_name_upper}}_JWT_SECRET` - JWT signing key
- `{{cookiecutter.package_name_upper}}_S3_ENDPOINT` - S3 endpoint; an `http://` prefix turns TLS off (local SeaweedFS)
- `{{cookiecutter.package_name_upper}}_S3_BUCKET` - S3 bucket for data files
- `{{cookiecutter.package_name_upper}}_S3_ACCESS_KEY` / `S3_SECRET_KEY` - S3 credentials
- `{{cookiecutter.package_name_upper}}_APP_DB_DSN` - PostgreSQL connection string (libpq format)

**Optional:**
- `{{cookiecutter.package_name_upper}}_CATALOG_DSN` - DuckLake catalog location (default: local file)
- `{{cookiecutter.package_name_upper}}_DEV_MODE` - Auto-authenticate all requests
- `{{cookiecutter.package_name_upper}}_ENCRYPTION_ENABLED` - Encrypt Parquet files at rest

## CLI

The CLI imports the top-level `server/` and `migrations/` packages, so run it
from the project root through mise (`python -m`), not the installed script:

```bash
mise run migrate
mise run cli lake list
mise run cli lake snapshots
mise run cli lake reset --dry-run
mise run cli lake reset --confirm
mise run cli app reset --confirm
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |
| GET | `/dashboard` | Live dashboard (stream: `/dashboard/stream`) |
| GET | `/entities` | Entity search (rows patch: `/entities/rows`) |
| GET | `/entities/{id}` | One entity: events per day, recent events |
| POST | `/api/events` | Append a JSON list of events (one lake snapshot) |
| GET | `/api/events` | List events (filters: entity_id, event_type, start, end) |
| GET | `/api/entities` | List distinct entities |
| GET | `/api/events/stream` | Stream events as NDJSON |
| POST | `/api/query` | Execute raw DuckDB SQL |
| POST | `/api/tags` | Create a tag |
| GET | `/api/tags` | List tags |
| DELETE | `/api/tags/{id}` | Delete a tag |
| POST | `/api/entities/{type}/{id}/tags` | Tag an entity |
| GET | `/api/entities/{type}/{id}/tags` | Get entity tags |
| DELETE | `/api/entities/{type}/{id}/tags/{tag_id}` | Remove tag |

## Authentication

Magic link email flow:
1. User enters email at `/auth/magic-link`
2. Server creates JWT token and sends email with link
3. User clicks link (`/auth/verify?token=...`)
4. Server validates token, creates session, sets cookie
5. Subsequent requests use session cookie

In dev mode (`DEV_MODE=true`), all requests are auto-authenticated with a stable dev user.

## Adding Migrations

1. Create `migrations/app/NNN_description.up.sql` (and `.down.sql`)
2. For lake migrations, add a `Migration` entry in `migrations/lake.py`
3. Run `mise run migrate`

## Deployment

```bash
# Build and push Docker image, deploy to K8s (reads DOCKER_REGISTRY from .env.prod)
mise run deploy

# Create the secrets first:
kubectl create secret generic {{cookiecutter.project_slug}}-secrets \
  --from-literal=jwt-secret=YOUR_SECRET \
  --from-literal=s3-endpoint=YOUR_S3 \
  --from-literal=s3-bucket=YOUR_BUCKET \
  --from-literal=s3-access-key=YOUR_KEY \
  --from-literal=s3-secret-key=YOUR_SECRET_KEY \
  --from-literal=app-db-dsn='host=... dbname=... user=... password=...' \
  --from-literal=catalog-dsn='host=... dbname=... user=... password=...'
```
