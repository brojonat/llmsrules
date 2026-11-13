# Learnings

Pitfalls found the hard way. Each entry: what happened, why it was
surprising, how to avoid it.

## rust-analyzer "is installed" but isn't

`~/.cargo/bin/rust-analyzer` exists after installing rustup, but it's only a
proxy; running it fails with `Unknown binary 'rust-analyzer' in official
toolchain` until the component is added. Editors then show no diagnostics
with no obvious error. `rust-toolchain.toml` lists the component, so any
cargo command in this repo installs it.

## rustaceanvim needs a recent Neovim

Current rustaceanvim refuses to load on Neovim 0.11 ("requires Neovim 0.12
or above"), which looks like rust-analyzer silently not attaching. Use
Neovim 0.12+.

## `sqlite::memory:` is a separate database per connection

A pool of in-memory connections runs migrations on one and queries another
("no such table"). `db::test_pool()` uses `max_connections(1)` for this reason.

## New migrations need a rebuild

`sqlx::migrate!()` embeds `migrations/` at compile time, and cargo doesn't
watch that directory on its own; `build.rs` tells it to. Without it, a new
`.sql` file is silently missing from the binary.

## Graceful shutdown waits for every open request

axum's `with_graceful_shutdown` stops accepting and then waits. A request that
never finishes (an SSE stream, a long poll) holds shutdown open until the
orchestrator kills the pod. Give such handlers a cancellation token to select
on, and cancel it from the shutdown future.
