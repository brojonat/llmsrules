# Shutdown and Unix signals

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

## Never do real work in a signal handler

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

## Turn signals into messages

On the reading side, polling a flag in every loop doesn't scale, and stopping
everything with a mutex gets messy. Use **message passing**: the main task
receives signals and broadcasts a message, and each worker decides how to wind
down. This is cooperative cancellation, like Go's `ctx.Done()`. It sidesteps
the drop-cancellation problems in [`cancellation.md`](cancellation.md), because workers get to flush data and
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
            // so it must be cancel-safe (see cancellation.md).
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
  task still in it. That's the `try_join` bug from [`cancellation.md`](cancellation.md) again, so log failures and keep
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

## Containers: PID 1 ignores signals it doesn't handle

In a container your binary is usually PID 1, and the kernel doesn't apply
default actions to PID 1: a signal with no handler is simply dropped. A
binary that never registers `SIGTERM` therefore ignores `docker stop` and
Kubernetes until they `SIGKILL` it after the grace period (10s in Docker, 30s
by default in Kubernetes), with no cleanup at all. Measured: `docker stop` on a
plain `sleep` took 10.3s; with `--init` it took 0.2s. Handle `SIGTERM` as
above, or run under an init (`docker run --init`, `tini`), which also reaps
zombie children.

## Pipes: SIGPIPE is ignored, so `println!` panics

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

- [ ] Are `SIGTERM` and `SIGINT` handled by messaging workers to wind down,
      not by dropping them?
- [ ] After a signal-driven shutdown, does the process die by the signal
      (`die_by`) rather than exit normally?
- [ ] Is every signal listener kept alive until exit, and none registered
      from library code?
- [ ] In a container, does the binary handle `SIGTERM` or run under an init?
- [ ] Does a CLI that writes to stdout survive `| head -1`?
- [ ] Spawning children? Read [`processes.md`](processes.md).

## Further reading

- Rain, "Beyond Ctrl-C: the dark corners of Unix signal handling", RustConf
  2023: [video](https://www.youtube.com/watch?v=zhbkp_Fzqoo). The source of
  this doc. The talk links a download-manager demo repo with exercises. The
  exit-status, PID 1 and SIGPIPE notes go beyond the talk and were checked by
  experiment.
- Martin Cracauer, "Proper handling of SIGINT/SIGQUIT": why a program that
  catches `SIGINT` must re-raise it after cleanup.
