---
name: rust
description: Write Rust services, CLIs, terminal UIs, and browser apps. Covers async Rust (Tokio, axum), cancellation, shutdown and Unix signals, child processes, command-line tools (clap, JSON output, completions), Ratatui TUIs and tachyonfx effects in Orhun Parmaksız's style, releases with git-cliff / release-plz / cargo-dist, presenterm slide decks, and WebAssembly apps bundled with Trunk. Use when writing or reviewing Rust code, especially async/await, tokio::spawn, select!, timeouts, channels, mutexes, HTTP handlers, Ctrl-C / SIGTERM / SIGPIPE, PID 1 in containers, clap arguments, stdout vs stderr, ratatui / crossterm / TestBackend / insta snapshots, tachyonfx / exabind animations, presenterm slides or talks in the terminal, changelogs and release automation, or wasm32 / wasm-bindgen / web-sys / Trunk / Ratzilla frontends.
---

# Rust

Rust for services, CLIs and terminal UIs, native extensions, and the
occasional browser app. Same values as everywhere else: simple, explicit
dependencies, compose with pipes, JSON on stdout.

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
- **One binary, two faces**: a tool is a TUI when stdout is a terminal and a
  filter printing JSON lines when it isn't.
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
| [`references/cli.md`](references/cli.md) | Any command-line tool: crate layout, clap derive and env vars (the `$PATH` trap), exit codes, JSON on stdout vs logs on stderr, completions and man pages, config files. |
| [`references/tui.md`](references/tui.md) | Interactive terminal UIs with Ratatui: terminal setup and panic hooks, Orhun's app shape (state + `Command` + one event channel), rendering and theming, logging, testing with `TestBackend` + insta, driving the app in tmux. |
| [`references/tachyonfx.md`](references/tachyonfx.md) | Animations and effects in a Ratatui app: the effect loop, `EffectManager` and unique keys, composing effects, exabind's patterns, color pitfalls. |
| [`references/release.md`](references/release.md) | Shipping a CLI: conventional commits, git-cliff changelogs, release-plz, cargo-dist installers, `--locked`, distro packages, VHS demo GIFs. |
| [`references/presenterm.md`](references/presenterm.md) | Writing or checking a markdown slide deck for presenterm, in Orhun's style: talk repo layout, slide patterns, highlighted code walkthroughs, live TUI demos, headless lint. |
| [`references/ratzilla.md`](references/ratzilla.md) | Ratatui in the browser with Ratzilla: one core crate shared by a terminal and a web frontend, `draw_web` and key callbacks, choosing DOM / Canvas / WebGL2, tachyonfx on the web, and 0.3.1 bugs (link errors, focus, a DOM crash). |
| [`references/wasm.md`](references/wasm.md) | Rust running in a browser: when it's worth it, the wasm32 target, `std` calls that panic there (`Instant::now`), getrandom, panics, `spawn_local`, `requestAnimationFrame` loops, testing. |
| [`references/trunk.md`](references/trunk.md) | Building, serving and deploying a wasm app with Trunk: installing it via mise, wasm-opt and size, `Trunk.toml`, the `logs/` rebuild loop, the dev proxy, `--public-url`, serving `dist/` from axum. |
