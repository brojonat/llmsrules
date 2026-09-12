# Learnings

Inherited from the template; keep adding to it.

## Embedded NATS and Datastar

- `server.Options{DontListen: true}` plus `nats.Connect("", nats.InProcessServer(srv))`
  gives JetStream with no TCP port. Set `ServerName`; JetStream wants one.
- `kv.WatchAll(ctx, jetstream.UpdatesOnly())` is the right shape for a read
  loop: render current state first, then block on `Updates()`. Without
  `UpdatesOnly` the watcher replays the bucket and sends a nil marker.
- `kv.ListKeys` on an empty bucket returns `jetstream.ErrNoKeysFound`.
- Every KV bucket is a stream (`KV_<name>`), so stream counts include them.
- JetStream `AccountInfo().Limits` reports unlimited for the default account
  even when the server was started with a max store; carry the configured
  ceiling from the bus.
- A textarea the user types into must be `data-ignore-morph`, or every
  re-render replaces what they are typing. Save with a debounced `@put` and
  let "saved 3s ago" come from the server.
- Wrapping `http.ResponseWriter` for logging breaks SSE unless the wrapper
  implements `http.Flusher`.
- Form inputs that carry values to the backend should submit as form fields
  (`{contentType: 'form'}`), not signals: a shared signal name makes every
  input on the page converge on the last typed value.
- `curl -sN -m 2 .../stream` exits 28. That is the stream working.
- `os.ReadDir("/dev/fd")` fails on macOS; count descriptors with
  `fcntl(F_GETFD)` probes instead.

## Air

- If Air is killed hard, its child keeps the port. `make stop` kills whatever
  listens there.
