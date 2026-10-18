---
name: datastar
description:
  Build real-time hypermedia web apps with Datastar — the backend owns state
  and pushes HTML down one long-lived SSE stream while writes are short-lived
  requests that render nothing. Use when working with `data-*` attributes,
  `datastar-patch-elements` / `datastar-patch-signals` SSE events, signals,
  `@get`/`@post` actions, or the `datastar-py` / `datastar-go` SDKs. Also use
  when a task calls for live-updating or multiplayer UI without a SPA, or for
  immediate-mode / tick-based server rendering (fat morph, frames, render
  loops, streaming compression).
---

# Datastar

Datastar is a ~11KB hypermedia framework. The browser gets one script tag; the
server sends HTML. There is no client-side view layer, no build step, and no
JSON API for the UI to consume.

Two things make it work:

- **`data-*` attributes** on the HTML give elements reactivity and let them
  make backend requests.
- **SSE events** let one backend response patch the DOM and signals zero or
  more times, for as long as the connection stays open.

## When to use this skill

- Live-updating UI: dashboards, feeds, progress, chat, collaborative editing
- Anything "multiplayer" — several browsers looking at the same state
- Replacing a SPA + JSON API pair where the API exists only to feed the UI
- Working in a codebase that already has `data-on:`, `data-signals:`, or
  `datastar-patch-elements` in it

## When NOT to use this skill

- Offline-first or heavy client-side computation — the server is unreachable
  and Datastar has nothing to push
- A JSON API that non-browser clients consume — that is a normal API; build it
  normally and let Datastar sit alongside it
- Static content with no interactivity — plain HTML is fine

---

# The Tao of Datastar

These are the core team's opinions. They are not style preferences; the design
of the library assumes them, and fighting them produces code that is harder
than plain Datastar would have been.

**1. State in the right place.** Most state lives in the backend. The frontend
is exposed to the user and cannot be trusted as a source of truth.

**2. Start with the defaults.** Default options are the recommendation for the
majority of apps. Before changing one, work out why the default is wrong here.

**3. Patch elements and signals.** The backend drives the frontend by patching.
The frontend does not compute its next view.

**4. Use signals sparingly.** Reach for a signal only for user interactions
(toggling visibility) and for carrying new state to the backend (form inputs).
Signals holding data that the backend also knows is duplicated state, and it
will drift.

**5. In morph we trust.** Send big chunks of DOM — up to the `<html>` tag if you
like ("fat morph"). Morphing touches only what actually differs and preserves
focus, scroll, event listeners, and CSS transitions. Do not hand-roll
fine-grained updates. Use `data-ignore-morph` on the rare element that must be
left alone.

**6. SSE responses.** One response can carry 0..N events. There is no benefit
to a content type other than `text/event-stream`.

**7. Compress the stream.** Fat morph plus repetitive HTML compresses
extraordinarily well — Brotli ratios around 200:1 on SSE streams are normal.
The compressor keeps one context per connection, so each frame is compressed
against the frames before it and only the delta ships. That is what makes
resending the whole view every time affordable.

**8. Backend templating.** The backend generates the HTML, so use its
templating language to keep things DRY. The same template renders the first
page load and every subsequent fragment.

**9. Page navigation and history are solved.** Use `<a href>` and let the
browser manage history. Each page is a resource.

**10. CQRS.** Segregate commands (writes) from requests (reads): a single
long-lived request receives updates, and many short-lived requests send
commands. This is the pattern that makes real-time collaboration fall out for
free.

**11. No optimistic updates.** Do not show success before the backend confirms
it. Use a loading indicator instead and let the truth arrive on the stream.

**12. Accessibility is yours.** Datastar stays out of the way. Semantic HTML,
ARIA via `data-attr:`, keyboard and screen reader support are your job.

## The CQRS loop

This is the shape almost every Datastar app takes:

```
browser                                  server
   |  GET /               ------------->  render whole page
   |  <-------------------------------    HTML (includes the live region)
   |
   |  GET /updates (data-init) --------->  register watcher   [openWhenHidden: true]
   |  <-------------------------------    event: datastar-patch-elements   (initial)
   |                                        ... blocks on state change ...
   |  POST /add           ------------->  mutate state, wake all watchers
   |  <-------------------------------    204 No Content, empty body
   |  <-------------------------------    event: datastar-patch-elements   (on the open stream)
```

Two rules follow, and they are the ones people break:

- **The read stream never returns.** It sends, blocks, sends again.
- **Write handlers render nothing.** They mutate and answer `204`. The result
  reaches the screen on the stream, not in the write's response.

Every other browser watching the same state gets the same patch. Nothing in the
write handler knows how many clients exist — that is why it is multiplayer for
free.

The simplest server side for this loop wakes every stream on every write, and
each stream renders for itself. The minimal templates do that, and it is the
right first version. It costs viewers × writes renders, though, and the fix is
the next section: render on a tick, once per view, and let streams copy bytes.

---

# Immediate-mode rendering

Think `view = f(state)`, run on the server. A **frame** is the full HTML of a
view, up to `<html>` if you like. On every **tick** the server computes the
frames that may have changed, and each stream sends the latest frame for its
view. Morph keeps the DOM churn small and per-connection compression keeps the
wire small: an unchanged 50KB frame is a few bytes on the wire, and a 31KB
dashboard redraw where a few numbers moved measured 480 bytes. There is no
diffing, no per-field patching, and no client state.

This is the design to reach for once more than a handful of people share a
view, or once writes arrive faster than a person types.

## Ticks bound the work

Rendering on every write is accidentally quadratic. If 1,000 viewers each make
one write per second and every write re-renders for every viewer, that is
1,000,000 renders per second. On a 1-second tick it is 1,000, however many
writes arrive.

- **Renders per second ≤ distinct views × tick rate.** Never viewers × writes.
- **Tick length is a product decision.** 100ms (10 fps) feels live for
  multiplayer and interactive views; 250ms–1s is plenty for dashboards. Start
  slow and tighten only if it feels laggy.

## Backpressure

Backpressure means the slow part of a system pushes back on the fast part,
instead of the work in between piling up in a queue that grows until something
falls over. A tick-based renderer has three places work could pile up, and
each one is bounded by design:

| If…                                   | then…                                                                      |
| ------------------------------------- | -------------------------------------------------------------------------- |
| writes arrive faster than renders     | writes only mark views dirty, in a set; N writes in one tick are one render |
| a tick takes longer than its budget   | the missed ticks are dropped (Go's `time.Ticker` does this for you); frame rate falls, latency and memory do not grow |
| a client reads slower than frames arrive | its one frame slot is overwritten; when its socket frees up it sends the newest frame |

The renderer never waits on a client, and a client never waits on another
client.

**This only works because every frame is the whole view.** A frame is state,
not a delta, so dropping any frame loses nothing the next one does not carry.
An event-driven design (push each change to each subscriber) has no safe way
to shed load: a slow consumer either blocks the producer (one phone on bad wifi
stalls everyone), buffers without bound (memory grows, stale views replay), or
drops events, which corrupts any client applying deltas. Immediate mode turns
lossy delivery into correct delivery.

Two things follow:

- **Never queue frames per connection.** One slot, latest wins.
- **Overruns are a signal, not a failure.** A sustained overrun means the
  frame rate has quietly dropped. Log it (below) so somebody notices.

Writes need their own bound only once they go through a queue (rung 4 of the
escalation ladder): make it bounded, and answer `503` when it is full rather
than accepting work the tick cannot drain.

## Choose the render key

What a frame depends on decides the key, and the renderer renders each dirty
key once per tick no matter how many streams watch it.

- **Shared view: `view = f(URL)`.** Everyone on `/markets/X` sees the same
  thing, so the key is the path. Cost scales with the number of pages, not with
  viewers, and two tabs on one page send identical bytes. Most dashboards,
  boards, and feeds are this.
- **Personal view: `view = f(session, URL)`.** Per-user boards, selections,
  filters. Key by session (`todos/<session id>`), so a user's tabs still share
  a render. If frames differ per tab, key per connection.
- **Lots of personal views over shared data.** The frames in one tick overlap
  heavily, so get the sharing back with a fragment cache keyed by component and
  arguments (content-addressed: same inputs, same bytes). Use frequency-based
  admission (TinyLFU, e.g. Go's `ristretto`) so one-off fragments never evict
  the hot ones. Reach for this only when the overrun log asks for it.

## Size for the worst case, then optimize

Assume every view changes every tick and make sure that fits the budget. Only
then add dirty tracking: writes record which views they touched, and the
renderer redraws only those. That is a sound optimization *because* the tick
still bounds the worst case. One market dashboard dropped from 8.6% of a core
redrawing everything to 0.7% redrawing what changed, but the 8.6% is the number
to size against. When you cannot tell which views a write touches, mark
everything dirty; the tick bounds it.

**Never let a cache's freshness depend on who is watching.** Keeping a shared
page cache and rendering only pages with a viewer refcount above zero goes
wrong: the next visitor of an abandoned page gets stale HTML, and any URL can
allocate a cache entry (a memory leak anyone can address by typing
`/markets/garbage`). Two designs avoid it:

- **Render everything by change.** Pre-render every real view at startup,
  re-render on change, 404 unknown keys in the page handler. Good for a small,
  known set of pages.
- **Render only what is subscribed, and let frames live with subscribers.**
  Subscribing marks the key dirty, so a new viewer always gets a fresh render;
  a key with no subscribers is skipped and holds no frame; unknown keys fail to
  subscribe. Good when keys are open-ended (sessions). This is what the Go
  template does.

## The shape in Go

`project-templates/go-real-time-service/.../internal/frames` is the reference
implementation (about 350 lines, plus tests). Three parts with one job each:

- **Writes** mutate state, call `renderer.MarkDirty(key)` (or let a store
  watcher do it), and return `204`.
- **The renderer** is one goroutine on a `time.Ticker`. Each tick it renders
  every dirty key that has a subscriber, once, and drops the bytes into each
  subscriber's slot. It knows nothing about HTTP.
- **Streams** subscribe to a key and send whatever is in their slot. They
  render nothing.

```go
// Wiring, once per app. The caller owns the goroutine.
renderer := frames.New(100*time.Millisecond, logger, registry)
renderer.Handle("todos/", svc.Render)                          // func(ctx, key) ([]byte, error)
renderer.Handle("monitor", renderMonitor, frames.Every(500*time.Millisecond)) // sampled, not written
eg.Go(func() error { return renderer.Run(ctx) })
```

```go
// The stream handler, all of it.
sub, err := renderer.Subscribe("todos/" + sessionID)
if err != nil { ... }
defer sub.Close()

sse := datastar.NewSSE(w, r, datastar.WithCompression())
err = sub.Stream(r.Context(), func(html []byte) error {
    return sse.PatchElements(string(html))
})
```

The core of it is a one-slot mailbox per subscriber:

```go
// set runs on the renderer goroutine. It never blocks.
func (s *Sub) set(html []byte) {
    s.mu.Lock()
    s.html, s.version = html, s.version+1
    s.mu.Unlock()
    select {
    case s.wake <- struct{}{}: // cap 1
    default: // a wake-up is already pending; the stream will read the newest frame
    }
}

// Stream runs on the request goroutine.
func (s *Sub) Stream(ctx context.Context, send func([]byte) error) error {
    var sent uint64
    for {
        if html, version := s.Latest(); html != nil && version != sent {
            if err := send(html); err != nil {
                return err
            }
            sent = version
        }
        select {
        case <-ctx.Done():
            return nil
        case <-s.wake:
        }
    }
}
```

Once a slow client's socket buffer fills, `send` blocks while the renderer
keeps overwriting the slot. When `send` returns, the loop reads the newest
frame and skips the rest. The version check skips a frame already sent:
compression would shrink a duplicate to almost nothing anyway, but skipping it
also spares the browser a no-op morph of the whole view.

## The shape in Python

Same three parts. Rendering runs on the event loop, so render time is time no
stream is being served. Rendering once per view, not once per connection, is
what keeps Python viable here.

```python
class Pages:
    """Latest frame per view; `_next` is set and replaced on every publish."""

    def __init__(self) -> None:
        self._frames: dict[str, tuple[int, str]] = {}
        self._next = asyncio.Event()

    def current(self, key: str) -> tuple[int, str | None, asyncio.Event]:
        version, html = self._frames.get(key, (0, None))
        return version, html, self._next

    def publish(self, rendered: dict[str, str]) -> None:
        for key, html in rendered.items():
            version, _ = self._frames.get(key, (0, None))
            self._frames[key] = (version + 1, html)
        self._next.set()
        self._next = asyncio.Event()


async def run_renderer(store: Store, pages: Pages, tick: float = 0.1) -> None:
    loop = asyncio.get_running_loop()
    next_tick = loop.time()
    while True:
        next_tick += tick
        if dirty := store.take_dirty():
            pages.publish({key: render_view(store, key) for key in dirty})
        delay = next_tick - loop.time()
        if delay < 0:
            log.warning("tick overrun by %.0fms", -delay * 1000)
            next_tick = loop.time()  # drop missed ticks, do not burst to catch up
        await asyncio.sleep(max(delay, 0))  # always yield, even on overrun


@datastar_response
async def stream(request: Request):
    pages: Pages = request.app.state.pages
    key = request.path_params["page"]
    sent = 0
    while True:
        version, html, next_frame = pages.current(key)
        if html is not None and version != sent:
            yield SSE.patch_elements(html)
            sent = version
        await next_frame.wait()
```

Start `run_renderer` from the Starlette lifespan and cancel it on shutdown.
Once a slow client's socket buffer fills, uvicorn stops pulling its generator,
so it reads `current` late and skips frames, as in Go.

## Measure with overrun logging

A tick loop has a built-in benchmark: the tick budget. Log every overrun, and
under sustained overrun log a window summary (count, p50, p95, p99, max of tick
durations over ~20s) instead of one line per tick. Then load testing is: open
connections, watch the log.

## Escalation ladder

Take these in order, and only when the overrun log says the current rung is
not enough. Each one keeps the tick, so backpressure and overrun tracking stay.

1. **Dirty tracking** (above).
2. **Render workers.** Split a tick's renders across N workers with a
   `sync.WaitGroup` as the per-tick barrier. Each worker owns its buffer, and,
   with SQLite, its own read connection with **one read transaction per
   batch**. Without it every query is its own implicit transaction and takes
   the WAL lock separately: thousands of connections × several queries × 10
   ticks a second adds up to millions of lock acquisitions. Per-worker buffers
   also bound memory: one 64KB buffer per worker instead of per connection
   (10,000 connections × 64KB = 640MB).
3. **Shared work queue, not pinned assignment.** Put every connection on a
   shared queue each tick and let workers pull until it is empty. Round-robin
   assignment at connect time drifts as users leave, so one worker gets the
   cheap pages and the rest get the expensive ones. On an extreme skew test the
   shared queue cut p50 tick time by about 43%; with 1,000+ users expect a few
   percent on average and a better tail.
4. **Single writer.** Write handlers enqueue commands and return `204`; the
   tick drains the queue and applies the whole batch in one transaction, then
   renders. One writer with batched transactions goes a long way on SQLite.
5. **Pipeline writes and renders.** Lockstep (write, then render) costs
   `max(tick, write + render)` per tick; overlapping them costs
   `max(tick, write, render)`. With 90ms writes and 100ms renders on a 100ms
   tick, that is 190ms against 100ms. Renders must read a consistent snapshot
   while the next batch is being written: a SQLite read transaction, or an
   immutable state value swapped in with `atomic.Pointer`. Both phases still
   meet at the tick barrier. In one benchmark slow writes pushed lockstep p95
   tick time to ~1s while the pipeline held at 100ms.

---

# The wire protocol

Two event types. That is the entire protocol.

## `datastar-patch-elements`

```
event: datastar-patch-elements
data: elements <div id="foo">Hello world!</div>

```

Every event ends with a blank line. Multi-line HTML needs one
`data: elements ` line per line of HTML:

```
event: datastar-patch-elements
data: elements <main id="board">
data: elements   <h1>Messages</h1>
data: elements </main>

```

Default mode is `outer`: the element is morphed into the DOM element with the
matching **id**. Put ids on top-level morph targets, and on anything inside
them whose state must survive (listeners, transitions).

Optional `data:` lines, all before `data: elements`:

| Line                                   | Effect                                                                              |
| -------------------------------------- | ----------------------------------------------------------------------------------- |
| `data: selector #foo`                  | CSS selector for the target. Not needed for `outer`/`replace`                       |
| `data: mode outer`                     | Morph outer HTML (default, recommended)                                             |
| `data: mode inner`                     | Morph inner HTML                                                                    |
| `data: mode replace`                   | Replace outer HTML without morphing                                                 |
| `data: mode prepend` / `append`        | Insert as first/last child of the target                                            |
| `data: mode before` / `after`          | Insert as a sibling                                                                 |
| `data: mode remove`                    | Remove the target. Needs `selector`, sends no elements                              |
| `data: namespace svg` / `mathml`       | Patch into a non-HTML namespace                                                     |
| `data: useViewTransition true`         | Wrap the patch in a view transition                                                 |
| `data: viewTransitionSelector #main`   | Scope the view transition                                                           |

Removing an element:

```
event: datastar-patch-elements
data: selector #foo
data: mode remove

```

## `datastar-patch-signals`

```
event: datastar-patch-signals
data: signals {foo: 1, bar: 2}

```

Set a signal to `null` to remove it. `data: onlyIfMissing true` patches only
signals that do not yet exist.

## Non-SSE responses

An action's response may also be `text/html` (patched with optional
`datastar-selector` / `datastar-mode` / `datastar-use-view-transition`
headers), `application/json` (signals to patch), `text/javascript` (script to
execute), or an empty `204`. `text/event-stream` is the one to reach for; the
others exist for endpoints that only ever do one thing.

---

# Attributes

Only ~15 matter in practice.

| Attribute                 | What it does                                                                 |
| ------------------------- | ---------------------------------------------------------------------------- |
| `data-init="expr"`        | Run an expression when the attribute enters the DOM. Where the read stream starts |
| `data-on:click="expr"`    | Event listener. `evt` and `el` are in scope                                  |
| `data-bind:name`          | Two-way bind an input to a signal                                            |
| `data-signals:name="v"`   | Declare a signal with an initial value                                       |
| `data-text="$expr"`       | Set text content reactively                                                  |
| `data-show="$expr"`       | Toggle visibility                                                            |
| `data-class:active="$e"`  | Toggle a class                                                               |
| `data-attr:disabled="$e"` | Set any HTML attribute reactively — this is how you do ARIA                  |
| `data-computed:n="expr"`  | Read-only derived signal                                                     |
| `data-effect="expr"`      | Run an expression whenever its signal dependencies change                    |
| `data-indicator:fetching` | Signal that is `true` while a request from this element is in flight         |
| `data-ref:name`           | Signal referencing the element itself                                        |
| `data-ignore`             | Tell Datastar to skip this element's `data-*` attributes                     |
| `data-ignore-morph`       | Never morph this element                                                     |
| `data-preserve-attr="x"`  | Keep client-side state of listed attributes through a morph (e.g. `open`)    |
| `data-json-signals`       | Dump all signals as text. Debugging only                                     |

## Casing

`data-*` attributes are case-insensitive per the HTML spec, so Datastar has
rules:

- Keys of **signal-defining** attributes (`data-bind:`, `data-signals:`,
  `data-computed:`, `data-indicator:`) become **camelCase**.
  `data-signals:my-signal` defines `$mySignal`.
- Keys of **everything else** become **kebab-case**.
  `data-class:text-blue-700` toggles `text-blue-700`; `data-on:rocket-launched`
  listens for `rocket-launched`.
- `__case.camel` / `.kebab` / `.snake` / `.pascal` overrides that. Listening for
  a `widgetLoaded` event: `data-on:widget-loaded__case.camel`.

Signal names can go in the key or the value — `data-bind:foo` and
`data-bind="foo"` are the same. Use whichever your template language makes
cleaner.

## Common `data-on` modifiers

`__prevent` `__stop` `__once` `__passive` `__capture` `__window` `__document`
`__outside` `__viewtransition`, plus `__debounce.500ms[.leading|.notrailing]`,
`__throttle.500ms[.noleading|.trailing]`, `__delay.500ms`.

```html
<input data-bind:query data-on:input__debounce.300ms="@get('/search')">
```

`data-on:submit` already calls `preventDefault()` on forms. `__prevent` there
is harmless but redundant.

## Evaluation order

Attributes apply in DOM order, depth-first. This matters exactly once, and it
bites everyone: an indicator signal must be created before the fetch that uses
it.

```html
<!-- correct: indicator first -->
<div data-indicator:fetching data-init="@get('/endpoint')"></div>
```

## Expressions

Datastar expressions are JavaScript with `$name` interpolated to signal values.
`el` is the current element; `evt` is the event in `data-on:`. Actions are
prefixed `@` — only `@`-prefixed helpers can run, which is what keeps arbitrary
JS out of attributes.

Signals whose names begin with `_` are **local**: they are never sent to the
backend. Use them for pure UI state like `$_menuOpen`.

---

# Actions

`@get(uri, opts)` `@post` `@put` `@patch` `@delete` all behave identically apart
from the method.

Every request carries:

- a `Datastar-Request: true` header
- **all** signals except `_`-prefixed ones — as a `?datastar=` **query param**
  on `GET`/`DELETE`, as a **JSON body** otherwise

Sending all signals every time is deliberate: the backend gets the complete
frontend state. Filtering is possible via `filterSignals` but is not
recommended.

Options worth knowing:

| Option                 | Default                        | Notes                                                                 |
| ---------------------- | ------------------------------ | --------------------------------------------------------------------- |
| `openWhenHidden`       | `false` for GET, `true` others | GET streams **close when the tab is hidden**. Set `true` — see below   |
| `requestCancellation`  | `'auto'`                       | Cancels in-flight requests to the same URL+method                      |
| `contentType`          | `'json'`                       | `'form'` submits the closest form instead of signals                  |
| `headers`              | `{}`                           | CSRF tokens go here                                                   |
| `retry`                | `'auto'`                       | Network errors only. `'error'`, `'always'`, `'never'` also valid      |
| `retryInterval`        | `1000`                         | Scaled by `retryScaler` (2), capped at `retryMaxWait` (30s)           |
| `retryMaxCount`        | `10`                           |                                                                       |

## Keep the read stream open when the tab is hidden

**Pass `{openWhenHidden: true}` on the long-lived read by default.**

```html
<body data-init="@get('/updates', {openWhenHidden: true})">
```

The default for `@get` is `false`: Datastar closes the stream when the tab is
backgrounded and reopens it when the tab becomes visible again. For a live view
that is the wrong behavior. A backgrounded tab silently stops receiving
patches, so it shows stale state, and every tab switch costs a reconnect — a
new render of the full live region, and a fresh watcher registration on the
server. In a multiplayer app the user comes back to a view that was wrong for
however long they were away.

This is the one default worth overriding as a matter of course. The cost is a
held connection and some battery on mobile; the benefit is that the view is
always current, which is the entire point of the stream. Leave the default in
place only when the page genuinely does not matter while hidden and you are
optimizing for battery.

The `false` default only applies to `@get`. Writes (`@post`, `@put`, `@patch`,
`@delete`) already default to `true`, so a command in flight is not cancelled
by a tab switch.

Signal helpers: `@peek(fn)` reads signals without creating a dependency;
`@setAll(value, filter)` and `@toggleAll(filter)` operate on matching signals.

Fetch lifecycle events fire as `datastar-fetch` with
`evt.detail.type` in `started` / `finished` / `error` / `retrying` /
`retries-failed`.

---

# Backends

## Python — `datastar-py`

```bash
uv add datastar-py    # or add it to a PEP 723 script block
```

Framework helpers live in `datastar_py.<framework>`: `starlette`, `fastapi`,
`django`, `quart`, `sanic`, `litestar`, `fasthtml`. The FastAPI module
re-exports the Starlette one and adds a `ReadSignals` dependency.

```python
from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse, datastar_response, read_signals
```

The long-lived read — an async generator, one `yield` per event:

```python
@datastar_response
async def updates(request):
    store = request.app.state.store
    with store.watch() as changed:
        while True:
            yield SSE.patch_elements(render_board(store))
            await changed.wait()
            changed.clear()
```

The write — mutate, render nothing:

```python
async def add(request):
    signals = await read_signals(request) or {}
    message = str(signals.get("message", "")).strip()
    if message:
        request.app.state.store.add(message)
    return DatastarResponse()          # empty content -> 204
```

Event constructors:

```python
SSE.patch_elements(html, selector=None, mode=None, use_view_transition=None)
SSE.remove_elements("#foo")
SSE.patch_signals({"count": 3}, only_if_missing=False)
SSE.execute_script("console.log('hi')")
SSE.redirect("/somewhere")
```

`DatastarResponse` accepts one event, a list, or an async iterable, and sets
`Content-Type: text/event-stream`, `Cache-Control: no-cache`, and
`X-Accel-Buffering: no`. Anything implementing `__html__` (htpy, fasttags) can
be passed straight to `patch_elements`.

`datastar_py.attributes.attribute_generator` builds attributes with type
checking, if you would rather not hand-write them:

```python
from datastar_py import attribute_generator as data
data.on("click", "@post('/add')").debounce(500)   # data-on:click__debounce.500ms__case.kebab="..."
```

`datastar-py` does not compress. Starlette's `GZipMiddleware` skips
`text/event-stream` by default; pass an `exclude_content_types` tuple without it
and the middleware sync-flushes after every event, so the stream keeps
working. gzip only dedupes frames under ~32KB, though (see Gotchas). For bigger
live regions, compress with zstd (`compression.zstd` is in the stdlib from
Python 3.14) or Brotli in a small ASGI middleware, flushing after every event.

FastAPI variant of signal reading:

```python
from datastar_py.fastapi import ReadSignals

@app.post("/add")
async def add(signals: ReadSignals) -> DatastarResponse: ...
```

## Go — `datastar-go`

```bash
go get github.com/starfederation/datastar-go
```

`NewSSE` writes the SSE headers (including `X-Accel-Buffering: no`) and flushes
every event as it is sent. The stream stays open until the context is cancelled
or the handler returns — so the handler *is* the event loop.

```go
import "github.com/starfederation/datastar-go/datastar"

func handleUpdates(s *store) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        sse := datastar.NewSSE(w, r)     // add datastar.WithCompression() for Brotli/gzip

        changed, stop := s.watch()
        defer stop()

        for {
            if err := sse.PatchElements(renderBoard(s)); err != nil {
                return // client went away
            }
            select {
            case <-sse.Context().Done():
                return
            case <-changed:
            }
        }
    })
}
```

The write side. `ReadSignals` takes a JSON body on writes and the `?datastar=`
query parameter on `GET`/`DELETE`:

```go
func handleAdd(s *store) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        var signals struct {
            Message string `json:"message"`
        }
        if err := datastar.ReadSignals(r, &signals); err != nil {
            http.Error(w, "bad signals", http.StatusBadRequest)
            return
        }
        s.add(signals.Message)
        w.WriteHeader(http.StatusNoContent)
    })
}
```

Useful methods on the generator:

```go
sse.PatchElements(html, datastar.WithModeInner(), datastar.WithNamespaceSVG())
sse.PatchElementTempl(component)         // templ integration
sse.RemoveElementByID("row-7")
sse.PatchSignals([]byte(`{"count":3}`))
sse.MarshalAndPatchSignals(struct{ Count int `json:"count"` }{3})
sse.ExecuteScript("console.log('hi')")
sse.Redirect("/somewhere")
sse.IsClosed()                           // cheap check before expensive work
```

`datastar.WithCompression()` on `NewSSE` is worth taking: it negotiates
Brotli/gzip/zstd from the client's `Accept-Encoding`, and fat-morph HTML
compresses at ratios around 200:1. `curl` sends no `Accept-Encoding` by default,
so the stream stays readable by hand while browsers get compression.

## No SDK at all

The protocol is small enough to write by hand when a dependency is not worth it:

```go
func patchElements(w io.Writer, html string) {
    fmt.Fprint(w, "event: datastar-patch-elements\n")
    for _, line := range strings.Split(strings.TrimRight(html, "\n"), "\n") {
        fmt.Fprintf(w, "data: elements %s\n", line)
    }
    fmt.Fprint(w, "\n")
}
```

Plus signal reading: JSON-decode `r.URL.Query().Get("datastar")` on GET, the
body otherwise, and remember to flush after every event. Prefer the SDK — it is
one direct dependency and it gets you compression, signal patching, script
execution, redirects, and correct flushing for free.

---

# Patterns

## Broadcast to every watcher

The read handler needs to block on "something changed". Coalescing is correct —
a watcher re-reads current state when it wakes, so a dropped duplicate wake is
never a lost update.

This is the minimal version, where each stream renders for itself on every
wake. It is fine while viewers × writes per second stays small. Past that, move
rendering into a tick loop (see Immediate-mode rendering) and keep the same
wake-up idea for streams waiting on new frames.

```python
class Store:
    def __init__(self):
        self._watchers: set[asyncio.Event] = set()

    @contextlib.contextmanager
    def watch(self):
        changed = asyncio.Event()
        self._watchers.add(changed)
        try:
            yield changed
        finally:
            self._watchers.discard(changed)

    def _notify(self):
        for changed in self._watchers:
            changed.set()
```

In Go, a `map[chan struct{}]struct{}` with a non-blocking `select` send does the
same job. For state that must survive a restart or span processes, put it in
SQLite, Postgres `LISTEN/NOTIFY`, or NATS and watch that instead.

## One template, two callers

The live region template renders both the first page load and every subsequent
patch. This is Tao #8, and it is what keeps markup in one place.

```html
<body data-init="@get('/updates', {openWhenHidden: true})">
  {% include "board.html" %}     <!-- first paint -->
</body>
```

```python
yield SSE.patch_elements(render("board.html"))   # every update
```

## Loading indicators

The signal form works for isolated requests:

```html
<button data-indicator:fetching data-on:click="@post('/do')"
        data-attr:disabled="$fetching">Go</button>
<span data-show="$fetching">Loading…</span>
```

Under CQRS the write returns `204` immediately, so `$fetching` flips back
before the stream has repainted. Set the indicator manually and let the
incoming patch clear it:

```html
<button data-on:click="el.classList.add('loading'); @post('/do')">Go</button>
```

## Forms

```html
<form data-on:submit="@post('/add'); $message = ''">
  <input data-bind:message name="message" autocomplete="off">
  <button type="submit">Send</button>
</form>
```

Clearing the signal after the `@post` is fine — the action has already captured
the signals. For file uploads, either bind the input (`data-bind:files`
base64-encodes into a signal) or use a real form with
`enctype="multipart/form-data"` and `{contentType: 'form'}`.

## Per-session state

One global store means every browser sees the same thing, which is the point
for a shared board and wrong for a per-user view. Key the store by session,
read the session id in both the stream and the write handlers, and notify only
that session's watchers. Everything else in the shape is unchanged.

---

# Gotchas

**`datastar-py`'s `read_signals()` returns `None` without the
`Datastar-Request` header.** It checks for the header before parsing anything.
`datastar.js` always sends it; your `curl` does not. (The Go SDK does *not*
check — `datastar.ReadSignals` parses whatever arrives, so a hand-rolled `curl`
against a Go backend works without the header and the same `curl` against a
Python backend silently does nothing.) Testing a write by hand:

```bash
curl -X POST -H 'Datastar-Request: true' -H 'Content-Type: application/json' \
     -d '{"message":"hi"}' http://localhost:8000/add
```

Without those two headers a Python handler silently sees no signals — no error,
no log line, just nothing happening.

**In Go, call `ReadSignals` before `NewSSE`.** Upgrading the response first
closes the request body out from under it. The SDK's error message says so
outright ("are you sure you created the SSE ***AFTER*** the ReadSignals?"), but
only once you are already reading errors.

**Never wait for `networkidle`.** The SSE stream is a request that never
completes, so the network is never idle. Playwright:

```python
page.goto(url, wait_until="domcontentloaded")
page.wait_for_selector("li:has-text('expected')")
```

**No write timeout on the server.** Anything that reaps a long-open connection
severs the stream mid-flight: Go's `http.Server.WriteTimeout`, nginx
`proxy_read_timeout`, ingress idle timeouts, load balancer idle timeouts.

**Proxy buffering swallows the stream.** The SDKs set `X-Accel-Buffering: no`
for nginx. Behind other proxies, disable response buffering explicitly, or
patches arrive in a lump when the connection closes.

**GET streams close when the tab is hidden.** That is the default
(`openWhenHidden: false`). Override it on the read stream by default:
`@get('/updates', {openWhenHidden: true})`. Otherwise a backgrounded tab stops
receiving patches and comes back stale.

**Request cancellation is per URL+method.** Two elements both calling
`@post('/add')` will cancel each other by default. Different endpoints, or
`{requestCancellation: 'disabled'}`.

**Morph targets need ids.** `outer` mode matches top-level elements by id. A
fragment without one has nothing to morph into and will not appear.

**Signals prefixed with `_` never reach the backend.** Intentional, and a
five-minute debugging session if you forget.

**Do not render from a write handler.** If a `POST` handler is producing HTML,
the pattern has been left behind. Mutate, return `204`, let the stream paint.

**Do not duplicate backend state in signals.** Signals are for user
interactions and for carrying input up. Anything the backend also knows will
drift.

**Rendering per stream per write is quadratic.** It works in the demo and
falls over with a crowd. Render on a tick, once per distinct view.

**Do not queue frames per connection.** Keep only the latest frame; a slow
client should skip frames, not buffer them.

**Do not tie a shared cache's freshness to viewer counts.** It serves stale
pages to the next visitor and lets arbitrary URLs allocate cache entries.
Render everything by change, or render only subscribed keys and have
subscribing force a fresh render.

**gzip cannot see across frames bigger than 32KB.** Deflate's window is 32KB,
so it only finds the previous frame if the frame fits in the window. Measured
with `zlib` sync-flushing each frame: a 15KB frame compressed to 213 bytes per
tick, a 62KB frame to 11.6KB per tick. zstd stayed at 473 bytes for the 62KB
frame. Use Brotli or zstd for big frames, or keep gzip'd live regions small.

---

# Testing

The stream is testable with `curl` alone:

```bash
# first paint
curl -s http://localhost:8000/ | grep 'id="board"'

# write, then confirm it lands on the read stream
curl -s -X POST -H 'Datastar-Request: true' -H 'Content-Type: application/json' \
     -d '{"message":"from curl"}' http://localhost:8000/add
curl -sN -m 3 http://localhost:8000/updates      # exits 28 on timeout; that is correct
```

`curl -sN -m N` on a stream always ends in exit code 28. The stream is supposed
to never end.

For the attributes themselves, two browser contexts against one server proves
the multiplayer property end to end:

```python
a, b = ctx.new_page(), ctx.new_page()
a.goto(url, wait_until="domcontentloaded")
b.goto(url, wait_until="domcontentloaded")
a.fill("input[name=message]", "hello")
a.click("button[type=submit]")
b.wait_for_selector("li:has-text('hello')")     # b never talked to a
```

## Load testing a tick loop

Keep it simple: run the server, open a few hundred streams with `curl -N` in a
loop (plus some writes, if the view has them), and read the overrun log and
`/metrics`. p50/p95/p99 of tick time under load is the benchmark. No harness,
no separate load-generation box.

Running the load on the same machine is fine for this. Know its one
distortion: the curls compete for CPU, and because slow clients make the server
skip frames, a load generator that falls behind quietly lowers the load. If the
numbers look too good, that is the first thing to suspect.

---

# Deployment

- **Compress the stream.** Brotli on `text/event-stream` gets ratios around
  200:1 on repetitive fat-morph HTML. This is the single biggest win. Each
  connection holds its own compression context, so measure memory per open
  stream with compression on.
- **No idle or read timeouts** anywhere on the path — server, ingress, LB.
- **Disable proxy buffering** (`X-Accel-Buffering: no`, or the equivalent).
- **Budget one open connection per browser tab.** A long-lived request per
  viewer is the cost of the model; size worker/connection pools accordingly and
  prefer async runtimes over thread-per-request. With `openWhenHidden: true`
  (the recommended default) background tabs hold their connections too, so
  budget for every open tab, not every active one.
- **Sticky sessions or shared state.** With more than one replica, a client's
  stream lands on one instance while its writes may land on another. Either
  pin sessions or broadcast changes through shared infrastructure (Postgres
  `LISTEN/NOTIFY`, NATS, Redis) so every replica's watchers wake.
- **Pin the CDN URL to a release tag**, and keep it in step with the SDK
  version:

```html
<script type="module"
        src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.2/bundles/datastar.js"></script>
```

# Starting points

Two cookiecutter templates in this repo implement the CQRS loop in one file
each:

- `project-templates/go-datastar-minimal` — Go, `datastar-go` + `html/template`,
  `go run .`
- `project-templates/python-datastar-minimal` — Python, PEP 723 deps,
  `datastar-py` + Starlette + Jinja2, `./main.py`

Both wake every stream on every write and render inside the stream: the right
first version, and the one to outgrow.

`project-templates/go-real-time-service` is the **tick-based reference**:
`internal/frames` renders every live view on one tick loop, streams send the
newest frame, and overruns are logged and exported to Prometheus. It shows a
per-session view (todos, fed by a NATS KV bucket watcher) and a shared sampled
view (monitor, `frames.Every`), with templ, metrics, and k8s manifests.

# References

- Docs, single file for LLMs: <https://data-star.dev/docs.md>
- The Tao of Datastar: <https://data-star.dev/guide/the_tao_of_datastar>
- Attributes: <https://data-star.dev/reference/attributes>
- Actions: <https://data-star.dev/reference/actions>
- SSE events: <https://data-star.dev/reference/sse_events>
- Python SDK: <https://github.com/starfederation/datastar-python>
- Go SDK: <https://github.com/starfederation/datastar-go>
- Shared-view frame loop, measured in production (Go):
  <https://brojonat.com/posts/datastar-kalshi/>
- Ticks, barriers, fragment caching:
  <https://andersmurphy.com/2026/09/29/faster-streaming-html-with-batches-and-aggregates.html>
- Overrun logging, load testing, render queues:
  <https://andersmurphy.com/2026/10/05/discrete-time-based-systems-are-simple-to-benchmark.html>
- Lockstep to pipeline:
  <https://andersmurphy.com/2026/10/12/lockstep-to-pipeline-in-one-line.html>
