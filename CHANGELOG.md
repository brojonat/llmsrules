# Changelog

Notable changes to the skills, templates and `AGENTS.md`, newest first. The
format follows [Keep a Changelog](https://keepachangelog.com/). This file
starts on 2026-10-29; earlier history is in `git log`.

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
