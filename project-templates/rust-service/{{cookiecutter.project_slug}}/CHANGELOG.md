# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.1.0]

### Added

- axum server: `GET /`, `/healthz`, Prometheus `/metrics` (request counter and
  latency histogram by route template)
- `/items` example resource: SQLite via sqlx, plain SQL, migrations embedded
  and applied at startup
- JWT bearer auth as an extractor (`Claims`); `token` subcommand mints tokens
- `AppError` with a status per variant and JSON error bodies
- Request ids (`x-request-id`) on every response and every log line
- clap CLI (`serve`, `token`) with env fallbacks; JSON or pretty `tracing` logs
- Graceful shutdown on Ctrl-C / SIGTERM
- Dockerfile (cargo-chef, static musl binary on `scratch`), k8s/prod with a
  volume for the database, `deploy` script pinned to the commit
- mise tasks: setup, build, dev (watchexec, tees `logs/`), serve, token,
  test, lint, fmt, docker-build, deploy, logs
