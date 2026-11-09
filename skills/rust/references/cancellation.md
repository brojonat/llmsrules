# Cancellation in async Rust

## Futures are inert

The single most important fact: **a Rust future does nothing until it is
polled (awaited).** Unlike a JavaScript promise, creating it starts no work.
Rust is designed this way so async works on embedded targets, and the language
can't change it.

Because futures are inert, there is a universal way to cancel them: **drop
the future** (or just stop polling it). That means:

> Any future can be cancelled at any `.await` point.

That's a major strength, since cancellation is hard in synchronous code. It's
also the source of a whole class of bugs, for two reasons:

1. **Futures get dropped quietly** by ordinary code patterns (below).
2. **Cancellation propagates down.** Dropping a parent future drops every
   child future it owns. Whether a given `.await` can be interrupted depends on
   the parent, the grandparent, and so on up the chain. That's non-local
   reasoning, exactly what Rust otherwise lets you avoid.

### Which way to look

Cancellation *flows* down, so the direction you look depends on which end of
the chain your code is on:

- **You hold the cancel-unsafe operation → look up.** Whether your code is
  cancel-unsafe is local: read the function. Whether it ever *gets* cancelled
  is not. The cancellation starts in some ancestor (a `select!`, `timeout`,
  `try_join`, or a dropped HTTP handler) that may be several files away:

  ```rust
  // your function: looks fine locally
  async fn update_sled(shared: Arc<Mutex<State>>) { /* take(), .await, put back */ }

  // somewhere up the call chain, in code you never opened:
  let _ = timeout(Duration::from_secs(1), reconcile_all()).await; // drops update_sled mid-flight
  ```

- **You do the cancelling → look down.** If you're writing the `select!` or
  `timeout`, check everything beneath that point for cancel-unsafe operations,
  because dropping your future drops all of them.

Neither end can see the other, so no local check catches the bug. The fixes
split the same way: tasks and actors **cut the chain from above**, so ancestors
can't reach your code. Cancel-safe APIs make the **children harmless**, so
whoever cancels doesn't have to worry about what's below.

## Cancel safety vs. cancel correctness

- **Cancel safety** is a *local* property of one future: it can be
  dropped without side effects. `tokio::time::sleep` is cancel-safe;
  `mpsc::Sender::send` is not (dropping it loses the message). Tokio documents
  this per method under a "Cancel safety" heading.
- **Cancel correctness** is a *global* property: the system stays correct
  in the face of cancellations. A bug needs **all three**:
  1. a cancel-unsafe future exists,
  2. it actually gets cancelled,
  3. that cancellation breaks something: lost data, a broken invariant, or
     skipped cleanup.

Knock out any one of the three and there's no bug. Every pattern below
targets one of them.

## Where cancellations come from

**Forgetting `.await`.** The future is created, then dropped without ever
running. Easy to do when silencing an unused `Result`:

```rust
let _ = flush_metrics(); // BUG: never runs. Should be `flush_metrics().await`
```

Clippy's `let_underscore_future` lint catches this. Keep clippy on.

**Timeouts.** `tokio::time::timeout` drops the inner future when time runs out:

```rust
// BUG: when the timeout fires, the send future is dropped and `msg` is lost.
loop {
    let msg = next_message();
    match timeout(Duration::from_secs(5), tx.send(msg)).await {
        Ok(Ok(())) => {}
        Ok(Err(_closed)) => break,
        Err(_elapsed) => tracing::warn!("channel full"),
    }
}
```

**`try_join` / `try_join_all` / `try_collect`.** On the first error, every
other future is dropped mid-flight:

```rust
// BUG: if one service fails to stop, the rest never finish stopping.
try_join_all(services.iter().map(|s| s.stop())).await?;

// Fix: run all of them to completion, then report.
let results = join_all(services.iter().map(|s| s.stop())).await;
let errors: Vec<_> = results.into_iter().filter_map(Result::err).collect();
```

**`select!`.** Whichever branch completes first wins, and **every other branch's
future is dropped**. Select loops are especially prone to this. But removing
`select!` doesn't make you safe; the sources above are just as common.

**HTTP handlers.** When a client disconnects, hyper (and so axum) drops the
in-flight handler future. A flaky network on someone else's machine can stop
your handler halfway through. Long-lived SSE handlers (Datastar) are dropped
the same way: that's what you want for the stream itself, but don't do
must-finish work inside one.

## Invariants across `.await`: the Tokio mutex trap

The typical mutex use is to break an invariant temporarily while holding the
lock. If there's an `.await` inside that window, cancellation leaves the
invariant broken permanently:

```rust
let mut state = shared.lock().await;
let data = state.pending.take().expect("present");   // invariant broken: None
let data = enrich(data).await;                       // cancelled here →
state.pending = Some(data);                          // ...never restored
```

Rules:

- **Prefer `std::sync::Mutex`** for short critical sections. Its guard is
  `!Send`, so the compiler refuses to let you hold it across `.await` in a
  spawned task. "Don't await while an invariant is broken" becomes a compile
  error.
- **Avoid `tokio::sync::Mutex`.** If you must use it, never `.await` while an
  invariant is broken.
- **Prefer the actor pattern** for shared mutable state (below).

## Fixes, by condition

### 1. Make the future cancel-safe

**Split into a cancellable step and a step that can't fail.** Reserve a slot,
then send:

```rust
loop {
    let permit = match timeout(Duration::from_secs(5), tx.reserve()).await {
        Ok(Ok(permit)) => permit,
        Ok(Err(_closed)) => break,
        Err(_elapsed) => { tracing::warn!("channel full"); continue; }
    };
    permit.send(next_message()); // message is only produced once a slot is held
}
```

(Dropping `reserve()` still loses your place in the FIFO queue. See "resume
instead of recreating" if that matters.)

**Make progress visible to the caller.** `write_all(&data)` dropped midway
leaves you not knowing how much was written. `write_all_buf(&mut buf)` advances
the buffer as bytes go out, so calling it again resumes:

```rust
use bytes::{Buf, Bytes};

let mut buf = Bytes::from(data);
loop {
    match timeout(Duration::from_secs(5), w.write_all_buf(&mut buf)).await {
        Ok(res) => { res?; break; }
        Err(_elapsed) => tracing::warn!(remaining = buf.remaining(), "slow writer"),
    }
}
```

Apply the same idea to your own APIs: keep progress in caller-owned state, not
inside the future.

### 2. Don't cancel it

**Resume instead of recreating.** In a `select!` loop, create the future once,
pin it, and poll `&mut fut` each iteration, so losing a race doesn't drop it:

```rust
let reserve = tx.reserve();
tokio::pin!(reserve);
loop {
    tokio::select! {
        res = &mut reserve => {
            res?.send(msg);
            break; // a completed future must not be polled again
        }
        _ = ticker.tick() => tracing::debug!("still waiting for a slot"),
    }
}
```

**Use tasks for must-finish work.** A Tokio task is driven by the runtime, and
dropping its `JoinHandle` does **not** cancel it. Put cancel-unsafe work in a
task so the caller's cancellation can't reach it:

```rust
async fn create_order(
    State(app): State<AppState>,
    Json(req): Json<NewOrder>,
) -> Result<Json<Order>, AppError> {
    // The handler future is dropped if the client disconnects; the task is not.
    // AppError needs From<JoinError> and From<the store's error> for `??`.
    let order = tokio::spawn(async move { app.orders.create(req).await }).await??;
    Ok(Json(order))
}
```

Oxide's Dropshot HTTP server made this the default: each request runs as a
task to completion even if the connection closes.

### 3. Make cancellation harmless

**The actor pattern.** One task owns the mutable state, and everyone else sends
it messages. Callers can be cancelled freely: worst case, a reply goes unread.
The state lives in a spawned task nobody drops.

```rust
enum Cmd {
    Get { id: SledId, reply: oneshot::Sender<Option<Data>> },
    Put { id: SledId, data: Data },
}

async fn state_actor(mut rx: mpsc::Receiver<Cmd>) {
    let mut sleds: HashMap<SledId, Data> = HashMap::new();
    while let Some(cmd) = rx.recv().await {
        match cmd {
            Cmd::Get { id, reply } => { let _ = reply.send(sleds.get(&id).cloned()); }
            Cmd::Put { id, data } => { sleds.insert(id, data); }
        }
    }
}

// main: tokio::spawn(state_actor(rx)); hand clones of `tx` to whoever needs state.
```

Keep the actor's own loop free of `.await`s that happen while an invariant is
broken, for the same reason as the mutex rule.

## Review checklist

When writing or reviewing async code, ask at every `.await`:

- [ ] If execution stops right here, is any data lost or any invariant broken?
- [ ] Is this future (or an ancestor) inside `select!`, `timeout`, `try_join*`,
      or an HTTP handler? Then assume it **will** be cancelled.
- [ ] Is a `tokio::sync::Mutex` guard held across this point?
- [ ] Is every future actually awaited (clippy `let_underscore_future`)?
- [ ] Should must-finish work be a spawned task or an actor message instead?

## Further reading

- Rain (Oxide), "Cancelling Async Rust", RustConf 2025:
  [video](https://www.youtube.com/watch?v=zrv5Cy1R7r4),
  [written version](https://sunshowers-io.pages.dev/posts/cancelling-async-rust),
  and the `sunshowers/cancelling-async-rust` repo of links. The source of the
  cancel-correctness framework above.
- `cancel-safe-futures` crate: cancel-safe alternatives to common combinators,
  including a lock-and-update mutex that poisons itself if cancelled partway.
- Tokio docs: the "Cancel safety" section on each method, and the `select!`
  docs.
- Language proposals that might help someday: async drop, unforgettable
  types, undroppable types. None of them is ready today.
