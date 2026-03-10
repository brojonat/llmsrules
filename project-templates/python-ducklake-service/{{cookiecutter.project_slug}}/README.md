# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐
│   Browser   │────▶│   FastAPI     │────▶│ DuckLake  │
│  (HTMX)     │◀────│   + Jinja2   │     │ (DuckDB)  │
└─────────────┘     └──────┬───────┘     └─────┬─────┘
                           │                    │
                    ┌──────▼───────┐     ┌─────▼─────┐
                    │  PostgreSQL  │     │   MinIO    │
                    │  (app state) │     │   (S3)     │
                    └──────────────┘     └───────────┘
```

**Two databases, one application:**

- **DuckLake** (via DuckDB + Ibis): Analytics data lake with time travel, snapshots, and ACID transactions. Catalog metadata stored in PostgreSQL; Parquet data files stored in S3 (MinIO for local dev).
- **PostgreSQL** (via psycopg2): Application state -- users, sessions, tags, entity associations, and migration tracking.

## Quick Start

```bash
# Install dependencies
make install

# Download HTMX (and optionally Leaflet)
make setup-js

# Start Postgres + MinIO
docker compose up -d

# Configure environment
cp .env.example .env.server

# Run database migrations
make migrate

# Start dev server (auto-reload + logs to logs/)
make run-dev
```

Open http://localhost:8000. In dev mode (`DEV_MODE=true`), all requests are auto-authenticated.

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
│   └── routes/              # api.py, pages.py, tags.py
├── src/{{cookiecutter.package_name}}/  # Installable CLI package
│   └── cli.py               # Click: serve, migrate, lake, app
├── migrations/              # SQL + Python migration system
│   ├── runner.py            # Namespace-aware runner
│   ├── lake.py              # Lake DDL (events table)
│   └── app/                 # Numbered .up.sql / .down.sql files
├── templates/               # Jinja2 HTML (HTMX)
├── static/css/              # CSS with dark/light theme
├── tests/                   # pytest suite
├── k8s/prod/                # Kustomize manifests
├── docker-compose.yml       # Local dev: Postgres + MinIO
└── Makefile                 # All common tasks
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
- `{{cookiecutter.package_name_upper}}_S3_ENDPOINT` - S3/MinIO endpoint
- `{{cookiecutter.package_name_upper}}_S3_BUCKET` - S3 bucket for data files
- `{{cookiecutter.package_name_upper}}_S3_ACCESS_KEY` / `S3_SECRET_KEY` - S3 credentials
- `{{cookiecutter.package_name_upper}}_APP_DB_DSN` - PostgreSQL connection string (libpq format)

**Optional:**
- `{{cookiecutter.package_name_upper}}_CATALOG_DSN` - DuckLake catalog location (default: local file)
- `{{cookiecutter.package_name_upper}}_DEV_MODE` - Auto-authenticate all requests
- `{{cookiecutter.package_name_upper}}_ENCRYPTION_ENABLED` - Encrypt Parquet files at rest

## CLI

```bash
# Start server
{{cookiecutter.project_slug}} serve --host 0.0.0.0 --port 8000 --reload

# Run migrations
{{cookiecutter.project_slug}} migrate

# Lake admin
{{cookiecutter.project_slug}} lake list
{{cookiecutter.project_slug}} lake snapshots
{{cookiecutter.project_slug}} lake reset --dry-run
{{cookiecutter.project_slug}} lake reset --confirm

# App admin
{{cookiecutter.project_slug}} app reset --confirm
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |
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
3. Run `make migrate`

## Deployment

```bash
# Build and push Docker image, deploy to K8s
make deploy

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
