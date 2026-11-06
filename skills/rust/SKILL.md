---
name: rust
description: Write Rust services, CLIs, and libraries, with a focus on async Rust (Tokio, axum), cancellation correctness, and graceful shutdown. Use when writing or reviewing Rust code, especially anything with async/await, tokio::spawn, select!, timeouts, channels, mutexes, HTTP handlers, signal handling (Ctrl-C, SIGTERM), or child processes.
---

# Rust

Rust for services, data CLIs, and native extensions. Same values as everywhere
else: simple, explicit dependencies, compose with pipes, JSON on stdout.

## Core Principles

- **Explicit dependencies**: constructors take what they need; no global state,
  no `lazy_static`/`OnceLock` singletons for things like DB pools or clients.
- **Errors tell a story**: `thiserror` for library error types, `anyhow` with
  `.context("what was being attempted")` at application boundaries.
- **Tokio for services, threads for compute**: every web service starts on
  Tokio + axum from day one. Use threads or `rayon` for CPU-bound work:
  data-parallel transforms, batch jobs, CLIs with no network I/O. Inside a
  service, push blocking or CPU-heavy work to `spawn_blocking` (or a rayon
  pool) so it doesn't stall the runtime.
- **mise is the front door**: `cargo build`, `cargo test`, `cargo clippy`,
  and a `dev` task using `bacon` or `watchexec` that tees to `logs/`.

## References

- [`references/async.md`](references/async.md): Tokio's execution model,
  compared with Go, and **cancellation**: why any future can stop at any
  `.await`, the bugs that causes, and the patterns that prevent them. Read this
  before writing or reviewing async code.
