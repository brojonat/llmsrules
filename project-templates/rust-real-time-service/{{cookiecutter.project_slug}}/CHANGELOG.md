# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.1.0]

### Added

- Tick-based frame renderer (`frames`): dirty-key coalescing, only watched
  views render, `watch` channel per view, sampled views (`every`), tick
  metrics and a windowed overrun log
- SSE streams with Brotli (quality 1, lgwin 17); open streams end on shutdown
- Demo features: per-session todos over SQLite, a shared sampled host
  monitor, one-shot signal patches
- Session cookie middleware, request counter, `/healthz`, `/metrics`
- maud layout, plain CSS, datastar.js pinned on a CDN
- Dockerfile (static musl on `scratch`), k8s/prod with a volume and
  SSE-safe ingress annotations, `deploy` script pinned to the commit
- mise tasks: setup, build, dev, serve, test, lint, fmt, load, docker-build,
  deploy, logs
