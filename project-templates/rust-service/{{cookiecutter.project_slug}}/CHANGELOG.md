# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.1.0]

### Added

- axum server with `GET /`, `/healthz` and Prometheus `/metrics`
- Request logging + counting middleware, JSON or pretty `tracing` logs on stderr
- clap CLI with env fallbacks (`SERVER_ADDR`, `LOG_LEVEL`, `LOG_FORMAT`)
- Graceful shutdown on Ctrl-C / SIGTERM
- mise tasks: setup, build, dev (watchexec, tees `logs/`), serve, test, lint, fmt
