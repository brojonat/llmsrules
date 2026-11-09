# Child processes and process groups

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
`SIGQUIT`, and job control `SIGTSTP`/`SIGCONT`). The broadcast channel from
[`signals.md`](signals.md) is the natural place: each worker forwards to the
group it owns, and keeps waiting until the child exits:

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

## Review checklist

- [ ] If children run in their own process groups, are signals forwarded?
      If they share yours, is `SIGTERM` forwarded (and `SIGINT` not)?
- [ ] Does a `select!` loop over `broadcast::recv` handle `Closed`?
- [ ] Is a non-cancel-safe future in a `select!` loop created once, pinned,
      and polled by reference?
