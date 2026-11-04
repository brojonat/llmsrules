# {{cookiecutter.project_name}}

{{cookiecutter.description}}

An axum web service: handlers as async functions, middleware as layers,
dependencies passed through `State`. One binary, JSON logs on stderr,
`/healthz`, Prometheus `/metrics`, graceful shutdown on SIGTERM.

## Quick start

```bash
mise run setup   # toolchain from rust-toolchain.toml, fetch crates
mise run dev     # rebuild + restart on save, pretty logs tee'd to logs/serve.log
curl localhost:{{cookiecutter.default_port}}/healthz
```

The first build compiles tokio, hyper and axum (tens of seconds); after that
an edit rebuilds in about a second.

## Commands

`mise tasks` lists everything.

| Task | Command |
| --- | --- |
| Dev server (hot reload) | `mise run dev` |
| Release build | `mise run build` |
| Run release build | `mise run serve` |
| Tests | `mise run test` |
| Lint | `mise run lint` / `mise run fmt` |

Extra arguments go to the server: `mise run dev --log-level debug`.

## Configuration

Flags or environment variables (`.env` is loaded by mise; see `.env.example`).

| Flag | Env | Default |
| --- | --- | --- |
| `--addr` | `SERVER_ADDR` | `0.0.0.0:{{cookiecutter.default_port}}` |
| `--log-level` | `LOG_LEVEL` | `warn` (any `tracing` filter, e.g. `info,hyper=warn`) |
| `--log-format` | `LOG_FORMAT` | `json` (`pretty` in `mise run dev`) |

## Endpoints

| Route | Returns |
| --- | --- |
| `GET /` | `{"name": ..., "version": ...}` |
| `GET /healthz` | `ok` |
| `GET /metrics` | OpenMetrics text: `http_requests_total` by method, route template, status |

## Layout

Everything is in `src/main.rs` until it earns a split:

- `Cli`: flags with env fallbacks (clap)
- `AppState`: what handlers share; add a DB pool here, not in a global
- `app()`: the router, built from state so tests can construct it
- `observe`: middleware that logs and counts each request
- `tests`: drive the router in-process with `tower::ServiceExt::oneshot`
