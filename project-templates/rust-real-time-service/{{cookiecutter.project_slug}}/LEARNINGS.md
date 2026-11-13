# Learnings

Pitfalls found the hard way. Each entry: what happened, why it was
surprising, how to avoid it.

## Brotli quality sets per-stream memory, more than the window does

Each open stream keeps its own encoder. With the `brotli` crate, quality 5
held about 1 MiB per stream even for 1 KB frames; quality 1 held 41 KiB, for more
bytes on the wire (about 3x on 1 KB frames, 1.4x on 16 KB, 1.6x on 64 KB). Open streams are what a crowd multiplies, so
quality 1 is the default in `src/stream.rs`. Measure per-stream RSS after a
few hundred frames, not three; the encoder's buffers fill gradually.

## Graceful shutdown waits forever on SSE streams

axum's `with_graceful_shutdown` waits for open requests, and a stream never
finishes. Every stream selects on `AppState::shutdown`; the signal handler
cancels it.

## `sqlite::memory:` is a separate database per connection

A pool of in-memory connections runs migrations on one and queries another
("no such table"). `db::test_pool()` uses `max_connections(1)`.

## New migrations need a rebuild

`sqlx::migrate!()` embeds `migrations/` at compile time; `build.rs` tells
cargo to rebuild when the directory changes. Without it a new `.sql` file is
silently missing from the binary.

## `pgrep -x` misses long binary names

`/proc` truncates process names to 15 characters. `scripts/load.sh` finds the
server by its path with `pgrep -f` instead.
