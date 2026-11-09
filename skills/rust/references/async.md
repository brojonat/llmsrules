# Async Rust

## The model, compared with Go

Rust has no green threads (they were removed before 1.0). Instead:

- The compiler turns each `async fn` into a **state machine**: a struct holding
  exactly the variables that live across `.await` points. No per-task stack.
- A **runtime library** (Tokio) supplies the event loop (epoll/kqueue/io_uring)
  and a work-stealing thread pool that polls those state machines.

| Go | Tokio |
|---|---|
| `go f()` | `tokio::spawn(f())` |
| `chan T` | `tokio::sync::mpsc` / `oneshot` / `broadcast` / `watch` |
| `select` | `tokio::select!` |
| `context.Context` cancellation (cooperative) | dropping the future (imposed from outside, see [`cancellation.md`](cancellation.md)) |
| runtime parks blocking syscalls for you | you must use `spawn_blocking` |
| preemptive scheduling | cooperative: a task only yields at `.await` |

Practical consequences:

- **Blocking calls stall a worker thread.** Wrap synchronous I/O (`rusqlite`,
  `duckdb`, `std::fs`) and heavy CPU work in `tokio::task::spawn_blocking`.
- **A loop with no `.await` holds its thread** until it finishes.
- **Function coloring**: async code can only be awaited from async code.
  Services are async end to end. Keep pure compute and data-transform code
  synchronous so it can be called from either world, including from
  `spawn_blocking`.

In the browser there is no Tokio runtime: the page's event loop polls your
futures, and `wasm_bindgen_futures::spawn_local` takes the place of
`tokio::spawn`. See [`wasm.md`](wasm.md).

## Review checklist

- [ ] Is a blocking call (sync DB, `std::fs`, CPU-heavy loop) running on the
      runtime instead of in `spawn_blocking`?
- [ ] Is pure compute kept synchronous, so it works from sync code, async
      code, `spawn_blocking`, and wasm alike?
- [ ] Every `.await` is a point where the future can be cancelled: run the
      checklist in [`cancellation.md`](cancellation.md).
