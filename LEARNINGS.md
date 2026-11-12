# Learnings

Pitfalls found the hard way while working on this repo. Each entry: what
happened, why it was surprising, how to avoid it.

## Brotli's default window costs megabytes per SSE connection

A Datastar stream keeps one Brotli encoder per connection. datastar-go's
`WithCompression()` uses quality 6 with the automatic window (lgwin 22), which
held about 15 MiB per open stream; lgwin 16 held about 1.8 MiB with identical
output size. Surprising because the frames are only tens of KB: the memory
follows the window, not the data. Set the window to about twice the largest
frame. Measure after a few hundred ticks; the ring buffer fills gradually, so
a three-frame test understates steady state badly. Details and numbers are in
the datastar skill's Gotchas.

## Rust's brotli crate is pathological at quality 5-6 with lgwin 16 or below

In brotli 9.1.1, quality 5-6 with lgwin <= 16 switches to hasher type 40 and
holds about 15 MiB per encoder, the opposite of what a smaller window should
do. Go's encoder at the same settings is fine. Use quality 5 at lgwin 17.

## tower-http won't compress SSE, and can't set the Brotli window anyway

`CompressionLayer`'s default predicate skips `text/event-stream`, and its
Brotli setting only takes a quality (the window stays at 22). The Rust
`datastar` crate doesn't compress either. Encode the stream by hand with the
`brotli` crate and flush after every event; `rust-datastar-minimal` does this.

## axum graceful shutdown hangs forever with an SSE stream open

`with_graceful_shutdown` waits for in-flight requests, and a Datastar read
stream never finishes. Give every stream a `CancellationToken` to select on
and cancel it from the shutdown future.

## `sqlx::migrate!()` misses new migrations unless cargo is told to rebuild

The macro embeds `migrations/` at compile time, but cargo doesn't watch that
directory, so a new `.sql` file with no Rust change ships without it. Add a
`build.rs` that prints `cargo:rerun-if-changed=migrations`.

## `sqlite::memory:` is a separate database per connection

A pool of in-memory connections runs migrations on one and queries another
("no such table"). Use `max_connections(1)` for in-memory test pools.

## Cookiecutter renders every file through Jinja

`{{`, `{%` and `{#` in template source are Jinja syntax, so Rust code like
`format!("{{...}}")` breaks generation. Avoid those sequences (the Rust
template's test builds JSON with `serde_json::json!`), or wrap the block in
`{% raw %}` as the Go templates do. Grep for them before committing a template.

## `go-real-time-service` doesn't build straight from generation

The template ships without `go.sum` and with templ sources only. A fresh
project needs `go mod tidy` and `templ generate` (at the templ version pinned
in `go.mod`; `@latest` generates code the pinned runtime can't compile) before
`go build`. Its Makefile handles this; plain `go build` doesn't.

## Shared working tree: other agents' staged changes ride along

Several agents work in this repo at once. `git commit` takes whatever is
staged, including another agent's work. Check `git diff --cached` before
committing, stage paths explicitly, and use `git restore --staged` to put
back anything that isn't yours. `git fetch` and rebase before pushing.

## `pgrep -f` / `pkill -f` match the shell running them

A pattern like `pkill -f target/debug/app` inside a `bash -c` also matches
that shell's own command line, so the script kills itself (exit 144). Use
`pgrep -x <name>` or the PID from `$!`.
