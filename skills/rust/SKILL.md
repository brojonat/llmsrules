---
name: rust
description: Write Rust services, CLIs, libraries, and browser apps. Covers async Rust (Tokio, axum), cancellation correctness, graceful shutdown and Unix signals, child processes, and Rust compiled to WebAssembly and bundled with Trunk. Use when writing or reviewing Rust code, especially anything with async/await, tokio::spawn, select!, timeouts, channels, mutexes, HTTP handlers, signal handling (Ctrl-C, SIGTERM, SIGPIPE), child processes, running as PID 1 in a container, or wasm32 / WebAssembly / wasm-bindgen / web-sys / Trunk / trunk serve / Ratzilla web frontends.
---

# Rust

Rust for services, data CLIs, native extensions, and the occasional browser
app. Same values as everywhere else: simple, explicit dependencies, compose
with pipes, JSON on stdout.

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
- **Server-rendered HTML first**: a web UI is plain HTML plus Datastar unless
  the client has to compute, render continuously, or reuse Rust code. Then
  Rust compiles to wasm and Trunk bundles it.
- **mise is the front door**: `cargo build`, `cargo test`, `cargo clippy`,
  and a `dev` task using `bacon` or `watchexec` (or `trunk serve` for a wasm
  frontend) that tees to `logs/`.

## References

Read only the ones the task touches.

| Read | When |
|---|---|
| [`references/async.md`](references/async.md) | Any async code. Tokio's execution model compared with Go, blocking calls, function coloring. Short. |
| [`references/cancellation.md`](references/cancellation.md) | Code with `.await` inside `select!`, `timeout`, `try_join*`, or an HTTP handler; Tokio mutexes; deciding between a task and an actor. Why any future can stop at any `.await`, and the fixes. |
| [`references/signals.md`](references/signals.md) | Ctrl-C, `SIGTERM`, graceful shutdown, exit status after a signal, PID 1 in a container, and `println!` panicking under `\| head`. |
| [`references/processes.md`](references/processes.md) | Spawning child processes: process groups, forwarding signals, `select!` loops over a child and a broadcast channel. |
| [`references/wasm.md`](references/wasm.md) | Rust running in a browser: when it's worth it, the wasm32 target, `std` calls that panic there (`Instant::now`), getrandom, panics, `spawn_local`, `requestAnimationFrame` loops, testing. |
| [`references/trunk.md`](references/trunk.md) | Building, serving and deploying a wasm app with Trunk: installing it via mise, wasm-opt and size, `Trunk.toml`, the `logs/` rebuild loop, the dev proxy, `--public-url`, serving `dist/` from axum. |
