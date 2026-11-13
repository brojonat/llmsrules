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

## Brotli quality sets per-stream memory more than the window does

After shrinking the window, quality 5 at lgwin 17 still held about 1 MiB per
open stream in Rust (1,063 KiB on a running server with 300 streams). Quality
1 held 41 KiB, against 29 KiB uncompressed. Surprising because the window was
the advertised knob; the higher-quality hashers carry their own tables. The
cost is bandwidth at every frame size (1 KB: 267 vs 91 bytes per frame; 64
KB: 7.3 KB vs 4.6 KB), so measure before claiming quality 1 is free. Go's
encoder gains less (about 2x memory for about 2x bytes).

## Rust's brotli crate is pathological at quality 5-6 with lgwin 16 or below

In brotli 9.1.1, quality 5-6 with lgwin <= 16 switches to hasher type 40 and
holds about 15 MiB per encoder, the opposite of what a smaller window should
do. Go's encoder at the same settings is fine. Avoid quality 5-9 at lgwin
16 or below; the templates use quality 1 at lgwin 17.

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

## `go mod tidy` before templ codegen demotes templ to indirect

`go-real-time-service` ships `.templ` sources, not the generated `_templ.go`
files. Run `go mod tidy` before `templ generate` and tidy sees no import of
the templ runtime, so it marks templ `// indirect` (and a missing `go.sum`
made `docker build` fail outright). The template now ships `go.sum` and
setup runs `go mod download`; if you tidy, generate first. Generate with the
templ version pinned in `go.mod` (`go tool templ`): `@latest` emits code the
pinned runtime can't compile.

## Shared working tree: other agents' staged changes ride along

Several agents work in this repo at once. `git commit` takes whatever is
staged, including another agent's work. Check `git diff --cached` before
committing, stage paths explicitly, and use `git restore --staged` to put
back anything that isn't yours. `git fetch` and rebase before pushing.

## `pgrep -f` / `pkill -f` match the shell running them

A pattern like `pkill -f target/debug/app` inside a `bash -c` also matches
that shell's own command line, so the script kills itself (exit 144). Use
`pgrep -x <name>` or the PID from `$!`.

## Template validator ports can collide with unrelated processes

Port 18092 was held by a long-running process that has nothing to do with
this repo, so a validator bound to it failed with "address in use". Check
`ss -ltnp` before picking a port; `rsrealtime` uses 18093.
