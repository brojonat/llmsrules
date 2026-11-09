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
| `context.Context` cancellation (cooperative) | dropping the future (imposed from outside, see below) |
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

## Shutdown and Unix signals

Signals are cancellation that comes from outside the process. You will get
them: Kubernetes and `docker stop` send `SIGTERM` before killing a service, and
CLI users hit Ctrl-C whenever something feels slow. A program that only reads
can mostly ignore them. A program that writes data or coordinates external
work (downloads, a database, child processes) has to decide what happens.

| Signal | Sent by | Default | Catchable |
|---|---|---|---|
| `SIGINT` | Ctrl-C | terminate | yes |
| `SIGTERM` | `kill`, k8s, `docker stop` | terminate | yes |
| `SIGQUIT` | Ctrl-\ | terminate + core dump | yes |
| `SIGTSTP` / `SIGCONT` | Ctrl-Z / `fg`, `bg` | stop / continue | yes |
| `SIGKILL`, `SIGSTOP` | `kill -9`, `kill -STOP` | kill / stop | **no** |

### Never do real work in a signal handler

A signal handler can run between any two instructions of your program. If it
fires while you hold a lock and then takes the same lock, you deadlock. The
allocator takes locks, so a handler **can't allocate**: no `String`, no `Vec`,
no logging. Only functions listed as async-signal-safe (`man 7 signal-safety`)
are allowed, such as `write(2)` to a file descriptor. A second signal can also
arrive while the first handler is still running, so handlers interrupt each
other too. ("Async" there is unrelated to async Rust. It's the opposite: async
Rust can only be interrupted at `.await`, while a signal handler can interrupt
you anywhere.)

The standard workaround is the **self-pipe trick**: the handler writes one byte
to a pipe the process owns, and normal code reads the other end. Don't write
it by hand. `tokio::signal` (and `signal-hook` for sync code) does this for
you and hands you an ordinary async stream.

**Registering is permanent.** The first `signal(kind)` or `ctrl_c()` for a
signal replaces its default action for the rest of the process's life.
Dropping the stream doesn't restore it, so a `SIGINT` that arrives after the
listener is gone is silently swallowed and the process keeps running. Keep
the listener alive until you exit (or restore the default yourself, as
`die_by` below does), and never register signals from library code.

### Turn signals into messages

On the reading side, polling a flag in every loop doesn't scale, and stopping
everything with a mutex gets messy. Use **message passing**: the main task
receives signals and broadcasts a message, and each worker decides how to wind
down. This is cooperative cancellation, like Go's `ctx.Done()`. It sidesteps
the drop-cancellation problems above, because workers get to flush data and
record state instead of vanishing mid-`.await`.

```rust
use std::io::Write;

use nix::sys::signal::{self, SigHandler, Signal};
use tokio::{signal::unix::{signal, SignalKind}, sync::broadcast, task::JoinSet};

/// Runs the downloads; returns the signal that stopped them, if any.
async fn run(urls: Vec<String>) -> anyhow::Result<Option<Signal>> {
    let mut sigint = signal(SignalKind::interrupt())?;
    let mut sigterm = signal(SignalKind::terminate())?;
    let (tx, _) = broadcast::channel(8);

    let mut workers = JoinSet::new();
    for url in urls {
        workers.spawn(download(url, tx.subscribe()));
    }

    let mut stopped_by = None;
    loop {
        tokio::select! {
            res = workers.join_next() => match res {
                Some(Ok(Ok(()))) => {}
                Some(Ok(Err(e))) => tracing::error!(error = %e, "download failed"),
                Some(Err(e)) => tracing::error!(error = %e, "download task panicked"),
                None => return Ok(stopped_by), // every worker finished
            },
            _ = sigint.recv() => {
                if stopped_by == Some(Signal::SIGINT) {
                    die_by(Signal::SIGINT); // second Ctrl-C: cleanup is stuck, bail
                }
                stopped_by = Some(Signal::SIGINT);
                let _ = tx.send(Signal::SIGINT);
            }
            _ = sigterm.recv() => {
                stopped_by.get_or_insert(Signal::SIGTERM);
                let _ = tx.send(Signal::SIGTERM);
            }
        }
    }
}

async fn download(url: String, mut shutdown: broadcast::Receiver<Signal>) -> anyhow::Result<()> {
    tokio::select! {
        res = fetch_to_disk(&url) => res,
        _ = shutdown.recv() => {
            // The worker decides how to wind down. fetch_to_disk is dropped here,
            // so it must be cancel-safe (see above).
            flush_and_mark_interrupted(&url).await
        }
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    if let Some(sig) = run(std::env::args().skip(1).collect()).await? {
        die_by(sig); // cleaned up; now exit the way the signal would have
    }
    Ok(())
}

/// Exit the way the signal's default action would have, so the parent sees
/// "killed by SIGINT" rather than a normal exit.
fn die_by(sig: Signal) -> ! {
    let _ = std::io::stdout().flush();
    // SAFETY: nothing else is touching signal dispositions while we exit.
    let _ = unsafe { signal::signal(sig, SigHandler::SigDfl) };
    let _ = signal::raise(sig);
    std::process::exit(128 + sig as i32) // only reached if the signal is blocked
}
```

Notes:

- **Don't `?` out of the `join_next` loop.** Dropping a `JoinSet` aborts every
  task still in it. That's the `try_join` bug again, so log failures and keep
  draining.
- **Handle `SIGTERM` as well as `SIGINT`.** Services mostly get `SIGTERM`.
  `tokio::signal::ctrl_c()` alone misses it.
- **Double Ctrl-C:** the first one starts a clean shutdown; the second exits
  immediately, on the assumption that cleanup is stuck.
- **Die by the signal; don't just exit 130.** After a caught Ctrl-C, bash
  checks *how* the child ended. A child that exits normally, even with 130
  (128 + `SIGINT`), is assumed to have handled the interrupt, and the script
  carries on: `for f in *; do mytool "$f"; done` moves on to the next file
  instead of stopping. `die_by` restores the default action and re-raises the
  signal, so the parent sees a death by `SIGINT` and the loop stops. Both
  behaviors were checked by running the loop and sending `SIGINT` to its
  process group.
- If workers only need "stop now" and not *which* signal arrived,
  `tokio_util::sync::CancellationToken` is a lighter alternative to the
  broadcast channel.

### Child processes and process groups

Ctrl-C doesn't signal one process. It signals the terminal's foreground
**process group**, which children inherit. That's why one Ctrl-C stops
`cargo` and every `rustc` under it. You can signal a group yourself with a
negative PID: `kill -INT -<pgid>`.

`kill <pid>`, `docker stop` and Kubernetes don't do that: they signal **one**
process. So for children that share your group:

- Ctrl-C reaches them directly, at the same moment it reaches you. Don't also
  forward `SIGINT`: each child would get two, and a child with double-Ctrl-C
  handling bails immediately.
- `SIGTERM` reaches only you. Forward it, or the children carry on after you
  exit. (Checked: a child kept running after its parent was killed by PID,
  and died when the signal went to the group.)

If you spawn children that spawn their own children, put each in its own group
so you can signal the whole subtree at once. The catch: **process groups don't
nest.** Once a child is in its own group, the terminal's Ctrl-C no longer
reaches it. **You** now have to forward signals (`SIGINT`, `SIGTERM`,
`SIGQUIT`, and job control `SIGTSTP`/`SIGCONT`). The broadcast channel above is
the natural place: each worker forwards to the group it owns, and keeps
waiting until the child exits:

```rust
use anyhow::Context;
use nix::{sys::signal::{killpg, Signal}, unistd::Pid};
use tokio::sync::broadcast::{self, error::RecvError};

async fn run_child(
    mut cmd: tokio::process::Command,
    mut signals: broadcast::Receiver<Signal>,
) -> anyhow::Result<std::process::ExitStatus> {
    let mut child = cmd.process_group(0).spawn().context("spawning child")?; // group id = child pid
    let pgid = Pid::from_raw(child.id().context("child already reaped")? as i32);
    loop {
        tokio::select! {
            status = child.wait() => return Ok(status?),
            msg = signals.recv() => match msg {
                // Forward and keep waiting: the child decides when it's done.
                Ok(sig) => { let _ = killpg(pgid, sig); }
                Err(RecvError::Lagged(_)) => {}
                // The sender is gone. recv() would now return Closed
                // immediately on every call and spin this loop.
                Err(RecvError::Closed) => return Ok(child.wait().await?),
            },
        }
    }
}
```

Two things make this loop correct:

- **The select is in a loop, and the work survives it.** A signal is a
  message to act on, not an order to drop the work. `child.wait()` is
  cancel-safe, so making a fresh one each iteration is fine. A future that
  isn't (a download holding buffered data) must be created once before the
  loop and polled by reference, or every signal restarts it:
  `let op = fetch_to_disk(&url); tokio::pin!(op);` then `res = &mut op =>`.
- **`broadcast::Receiver::recv` errors are part of the protocol.** `Lagged`
  means messages were skipped; `Closed` means the sender is gone, and every
  later `recv()` returns at once. Matching `Err(_)` with a `continue` turns
  the loop into a busy spin.

Forwarding job control lets you do something most tools don't: on `SIGTSTP`
pause your timeout clocks, and on `SIGCONT` resume them, so a suspended run
doesn't time out. (Once you catch `SIGTSTP`, the default stop no longer
happens. After forwarding it, stop yourself with `SIGSTOP`, which can't be
caught.)

### Containers: PID 1 ignores signals it doesn't handle

In a container your binary is usually PID 1, and the kernel doesn't apply
default actions to PID 1: a signal with no handler is simply dropped. A
binary that never registers `SIGTERM` therefore ignores `docker stop` and
Kubernetes until they `SIGKILL` it after the grace period (10s in Docker, 30s
by default in Kubernetes), with no cleanup at all. Measured: `docker stop` on a
plain `sleep` took 10.3s; with `--init` it took 0.2s. Handle `SIGTERM` as
above, or run under an init (`docker run --init`, `tini`), which also reaps
zombie children.

### Pipes: SIGPIPE is ignored, so `println!` panics

Rust starts every program with `SIGPIPE` ignored. When the reader of a pipe
exits early, as in `mytool | head -1`, writes fail with `BrokenPipe` instead
of quietly killing the process, and `println!` turns that into a panic
(`failed printing to stdout: Broken pipe`, exit 101). CLIs that print JSON
for pipelines hit this constantly. Write through a locked stdout and treat a
broken pipe as a normal exit:

```rust
use std::io::Write;

use anyhow::Context;

fn print_rows(rows: &[serde_json::Value]) -> anyhow::Result<()> {
    let mut out = std::io::stdout().lock();
    for row in rows {
        writeln!(out, "{row}").context("writing to stdout")?;
    }
    Ok(())
}

fn is_broken_pipe(e: &anyhow::Error) -> bool {
    e.root_cause()
        .downcast_ref::<std::io::Error>()
        .is_some_and(|e| e.kind() == std::io::ErrorKind::BrokenPipe)
}

// in main: Err(e) if is_broken_pipe(&e) => return ExitCode::SUCCESS,
```

Restoring the default with `signal(Signal::SIGPIPE, SigHandler::SigDfl)` at the
top of `main` also works for a pure CLI. Never do it in a service: writing to a
socket whose peer has gone would then kill the whole server.

## Review checklist

When writing or reviewing async code, ask at every `.await`:

- [ ] If execution stops right here, is any data lost or any invariant broken?
- [ ] Is this future (or an ancestor) inside `select!`, `timeout`, `try_join*`,
      or an HTTP handler? Then assume it **will** be cancelled.
- [ ] Is a `tokio::sync::Mutex` guard held across this point?
- [ ] Is a blocking call (sync DB, `std::fs`, CPU-heavy loop) running on the
      runtime instead of in `spawn_blocking`?
- [ ] Is every future actually awaited (clippy `let_underscore_future`)?
- [ ] Should must-finish work be a spawned task or an actor message instead?
- [ ] Are `SIGTERM` and `SIGINT` handled by messaging workers to wind down,
      not by dropping them?
- [ ] If children run in their own process groups, are signals forwarded?
      If they share yours, is `SIGTERM` forwarded (and `SIGINT` not)?
- [ ] After a signal-driven shutdown, does the process die by the signal
      (`die_by`) rather than exit normally?
- [ ] Does a `select!` loop over `broadcast::recv` handle `Closed`?
- [ ] Does a CLI that writes to stdout survive `| head -1`?

## Further reading

- Rain (Oxide), "Cancelling Async Rust", RustConf 2025:
  [video](https://www.youtube.com/watch?v=zrv5Cy1R7r4),
  [written version](https://sunshowers-io.pages.dev/posts/cancelling-async-rust),
  and the `sunshowers/cancelling-async-rust` repo of links. The source of the
  cancel-correctness framework above.
- Rain, "Beyond Ctrl-C: the dark corners of Unix signal handling", RustConf
  2023: [video](https://www.youtube.com/watch?v=zhbkp_Fzqoo). The source of
  the signals section. The talk links a download-manager demo repo with
  exercises. The exit-status, PID 1 and SIGPIPE notes go beyond the talk and
  were checked by experiment.
- Martin Cracauer, "Proper handling of SIGINT/SIGQUIT": why a program that
  catches `SIGINT` must re-raise it after cleanup.
- `cancel-safe-futures` crate: cancel-safe alternatives to common combinators,
  including a lock-and-update mutex that poisons itself if cancelled partway.
- Tokio docs: the "Cancel safety" section on each method, and the `select!`
  docs.
- Language proposals that might help someday: async drop, unforgettable
  types, undroppable types. None of them is ready today.
