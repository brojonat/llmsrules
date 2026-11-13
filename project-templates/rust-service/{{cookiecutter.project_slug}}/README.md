# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A JSON API on axum and Tokio, with its data in SQLite. One binary with two
subcommands: `serve` runs the server and `token` mints bearer tokens. JSON
logs with a request id on every line, `/healthz`, Prometheus `/metrics`,
graceful shutdown on SIGTERM, a 10 MB container image, and a one-pod
Kubernetes deployment.

## Quick start

```bash
mise run setup   # toolchain, crates, and .env from .env.example
mise run dev     # rebuild + restart on save, logs tee'd to logs/serve.log

curl localhost:{{cookiecutter.default_port}}/healthz
TOKEN=$(mise run token --sub you | jq -r .token)
curl -X POST localhost:{{cookiecutter.default_port}}/items \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name": "first"}'
curl localhost:{{cookiecutter.default_port}}/items
```

The first build compiles tokio, axum and sqlx (a minute or so); after that an
edit rebuilds and restarts in a few seconds.

## Commands

`mise tasks` lists everything.

| Task | Command |
| --- | --- |
| Dev server (hot reload) | `mise run dev` |
| Tests / lint / format | `mise run test` / `mise run lint` / `mise run fmt` |
| A token for curl | `mise run token --sub you` (JSON on stdout) |
| Release build, then run it | `mise run build` / `mise run serve` |
| Container image | `mise run docker-build` |
| Deploy to Kubernetes | `mise run deploy` (see Deployment) |
| Follow production logs | `mise run logs` |

Extra arguments go to the server: `mise run dev --log-level debug`.

## Configuration

Flags or environment variables (`.env` is loaded by mise).

| Flag | Env | Default |
| --- | --- | --- |
| `serve --addr` | `SERVER_ADDR` | `0.0.0.0:{{cookiecutter.default_port}}` |
| `serve --database-url` | `DATABASE_URL` | `sqlite://data/app.db` (file and directory created if missing) |
| `serve --auth-secret`, `token --auth-secret` | `AUTH_SECRET` | required; signs and verifies tokens |
| `--log-level` | `LOG_LEVEL` | `warn` (any `tracing` filter, e.g. `info,sqlx=warn`) |
| `--log-format` | `LOG_FORMAT` | `json` (`pretty` in `.env.example`) |

## API

| Route | Auth | Returns |
| --- | --- | --- |
| `GET /` | | `{"name": ..., "version": ...}` |
| `GET /healthz` | | `ok` |
| `GET /metrics` | | OpenMetrics: `http_requests_total` by method, route, status; `http_request_duration_seconds` by method, route |
| `GET /items?limit=&offset=` | | newest first, `limit` 1-100 (default 20) |
| `GET /items/{id}` | | the item, or 404 |
| `POST /items` `{"name": ...}` | bearer | 201 with the item; 400 if the name isn't 1-200 characters |
| `DELETE /items/{id}` | bearer | 204, or 404 |

Errors are `{"error": "..."}`. Server errors say only `internal error`; the
cause goes to the log. Every response carries `x-request-id`: the caller's if
it sent one, a fresh UUID otherwise, and the same id is on every log line for
that request.

## Layout

| File | Job |
| --- | --- |
| `src/main.rs` | Flags (clap), logging, wiring, shutdown. `anyhow` lives here. |
| `src/app.rs` | `AppState`, the router, request-id and metrics middleware |
| `src/items.rs` | An example resource: its SQL and its handlers. Copy it for each new one. |
| `src/auth.rs` | JWT keys and the `Claims` extractor |
| `src/error.rs` | `AppError`: one variant per kind of failure, each with its status |
| `src/db.rs` | Opens SQLite (WAL, busy timeout) and runs migrations |
| `migrations/` | The schema, embedded in the binary and applied at startup |
| `build.rs` | Rebuilds when a migration is added |

### Writing SQL

Queries are plain SQL strings through [sqlx](https://github.com/launchbadge/sqlx):

```rust
let item: Option<Item> =
    sqlx::query_as("SELECT id, name, created_by, created_at FROM items WHERE id = ?")
        .bind(id)
        .fetch_optional(&app.db)   // fetch_one, fetch_all, or .execute() for no rows
        .await?;
```

`#[derive(FromRow)]` maps columns onto fields by name. Queries are checked when
they run, not at compile time, so each one needs a test; the tests use an
in-memory database and take milliseconds. sqlx can check queries at compile
time with `query_as!`, at the cost of a database (or a committed `.sqlx/`
cache from `cargo sqlx prepare`) whenever you build. Worth it once the schema
settles.

To change the schema, add `migrations/0002_<what>.sql`. It runs on the next
start, here and in production.

### Auth

`Claims` is an axum extractor. A handler that takes `claims: Claims` rejects
requests without a valid `Authorization: Bearer <token>` with a 401, and gets
`claims.sub` otherwise. Tokens are HS256 JWTs signed with `AUTH_SECRET`; mint
them with the `token` subcommand.

## Deployment

The `Dockerfile` builds a static musl binary with cargo-chef (dependencies in
their own cached layer) and copies it onto an empty `scratch` image: about
10 MB, running as an unprivileged user, with no shell. The binary is PID 1 and
handles SIGTERM itself, so `docker stop` and pod deletion take milliseconds.

`k8s/prod` is a kustomize directory: deployment, service, ingress, and a
1 GiB volume for the database. **One replica, `Recreate` strategy**: SQLite
has one writer, and the volume can only be mounted by one pod. Scaling out
means moving to Postgres (sqlx's `postgres` feature, `$1` placeholders).

First time, create the secret the deployment reads:

```bash
kubectl -n {{cookiecutter.k8s_namespace}} create secret generic {{cookiecutter.project_slug}}-secrets \
  --from-literal=auth-secret="$(openssl rand -hex 32)"
```

Then `mise run deploy` builds and pushes `{{cookiecutter.docker_registry}}/{{cookiecutter.project_slug}}:<commit>`
(override with `DOCKER_REPO`), applies `k8s/prod` with that tag, and waits for
the rollout. It refuses to run with uncommitted changes, so a tag always names
the code it was built from. Set the ingress host in `k8s/prod/ingress.yaml`
first.

Backups are not set up: the database is a file on one volume. See `TODO.md`.
