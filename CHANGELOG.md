# Changelog

Notable changes to the skills, templates and `AGENTS.md`, newest first. The
format follows [Keep a Changelog](https://keepachangelog.com/). This file
starts on 2026-10-29; earlier history is in `git log`.

## 2026-11-12

### Added

- `project-templates/rust-real-time-service`: the Rust counterpart of
  `go-real-time-service`. A tick loop renders each dirty, watched view once and
  publishes it on a `tokio::sync::watch` channel (slow clients skip to the
  newest frame; closed tabs unsubscribe by dropping the receiver). Demo
  features: per-session todos on SQLite, a sampled host monitor that counts
  its viewers, one-shot signal patches. Brotli at quality 1, session cookie
  middleware, tick metrics with a windowed overrun summary, `mise run load`,
  scratch image, k8s with SSE ingress settings.
- `rust-service`: a real service rather than a stub. `serve` and `token`
  subcommands, an `/items` JSON API on SQLite through plain sqlx with
  migrations, an HS256 `Claims` extractor that makes a route require a token,
  a thiserror `AppError` with JSON bodies, request IDs on responses and log
  spans, a request duration histogram, a cargo-chef Dockerfile (9.5 MB scratch
  image), k8s (one replica, PVC), a deploy script, `install-skills.sh`.
- `test-templates.py validate --only rsrealtime`; the `rust` validator now
  covers the `serve`/`token` CLI, auth on writes and the histogram.
- `go-real-time-service` ships `go.sum`.

### Changed

- datastar skill: Brotli quality matters more than the window. Per open
  stream on a running server, quality 5 held 1,063 KiB, quality 1 41 KiB,
  uncompressed 29 KiB. Quality 1 costs bandwidth at every frame size (64 KB
  frames: 7.3 KB vs 4.6 KB per frame). Tables for Rust and Go; the advice is
  to start at quality 1. Lists both Rust Datastar templates.
- `rust-datastar-minimal`: Brotli quality 5 to quality 1.
- `go-real-time-service`: `mise run setup` runs `go mod download`, not
  `go mod tidy`, which demoted templ to an indirect dependency when run before
  codegen.
- Generated `rust-service` `AGENTS.md` points at the rust skill's async,
  cancellation, signals and CLI references.
- README: template table rows for the Rust templates; the task-runner note
  lists every mise template.

### Fixed

- LEARNINGS.md said `go-real-time-service` used a Makefile; it uses mise. The
  entry is rewritten now that `go.sum` ships.

## 2026-11-11

### Added

- `project-templates/rust-datastar-minimal`: the Datastar CQRS loop in one
  Rust file. axum, the `datastar` crate, maud templates, state in SQLite
  through plain sqlx queries (migrations, `query_as` / `query_scalar`, a
  transaction), a `watch` version counter to wake streams, spawned writes for
  cancel correctness, Brotli on the stream at lgwin 17, graceful shutdown that
  ends open streams, in-process tests, mise dev loop.
- `test-templates.py validate --only rsminimal`: builds with `--locked`, runs
  tests, clippy and rustfmt, round-trips a write onto the compressed stream,
  and checks SIGTERM exits 0 with a stream open.

### Changed

- datastar skill: "Starting points" lists the Rust minimal template.

## 2026-11-09

### Added

- rust skill: references sharded by topic; wasm, Trunk, CLI, TUI, tachyonfx,
  Ratzilla, release and presenterm references.

## 2026-11-08

### Changed

- datastar skill: Brotli window findings. The default window (lgwin 22) held
  about 15 MiB per open SSE stream in datastar-go; lgwin 16 holds about
  1.8 MiB at the same bytes per tick. Measurements for Go and Rust, the
  rule of thumb (window at least twice the largest frame), and Rust specifics.
- Go templates (`go-real-time-service`, `go-local-app`) compress with
  `WithBrotli(WithBrotliLGWin(16))` plus gzip; `go-datastar-minimal`'s comment
  says the same.
- `python-ducklake-service` and `python-bayesian-experiment`: Garage for S3;
  the Bayesian template moved from a Makefile to mise.
- rust skill: signal-handling gotchas, checked by experiment.

## 2026-11-06

### Added

- rust skill, with an async reference: Tokio compared with Go, cancellation
  (cancel safety vs cancel correctness, which way to look, the Tokio mutex
  trap, fixes), shutdown, Unix signals and process groups. Examples compile.

### Changed

- `python-ducklake-service`: HTMX replaced by Datastar (live dashboard, Rocket
  d3 charts), a real `server/data/` layer, bound SQL parameters, mise.

## 2026-11-03

### Added

- `project-templates/rust-service`: a stub axum service (clap, tracing,
  `/healthz`, `/metrics`, graceful shutdown, mise).

## 2026-10-29

### Changed

- `AGENTS.md`: prefer Datastar over HTMX ("Plain HTML (with a sprinkle of
  Datastar) over heavy frontend stacks").
