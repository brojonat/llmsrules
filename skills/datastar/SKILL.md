---
name: datastar
description:
  Build real-time hypermedia web apps with Datastar — the backend owns state
  and pushes HTML down one long-lived SSE stream while writes are short-lived
  requests that render nothing. Use when working with `data-*` attributes,
  `datastar-patch-elements` / `datastar-patch-signals` SSE events, signals,
  `@get`/`@post` actions, or the `datastar-py` / `datastar-go` SDKs. Also use
  when a task calls for live-updating or multiplayer UI without a SPA.
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

- **The read stream never returns.** It renders, blocks, renders again.
- **Write handlers render nothing.** They mutate and answer `204`. The result
  reaches the screen on the stream, not in the write's response.

Every other browser watching the same state gets the same patch. Nothing in the
write handler knows how many clients exist — that is why it is multiplayer for
free.

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

---

# Deployment

- **Compress the stream.** Brotli on `text/event-stream` gets ratios around
  200:1 on repetitive fat-morph HTML. This is the single biggest win.
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

Two cookiecutter templates in this repo implement exactly the shape above, in
one file each:

- `project-templates/go-datastar-minimal` — Go, `datastar-go` + `html/template`,
  `go run .`
- `project-templates/python-datastar-minimal` — Python, PEP 723 deps,
  `datastar-py` + Starlette + Jinja2, `./main.py`

`project-templates/go-real-time-service` is the same architecture with templ,
an embedded NATS broker for per-session state, metrics, and k8s manifests.

# References

- Docs, single file for LLMs: <https://data-star.dev/docs.md>
- The Tao of Datastar: <https://data-star.dev/guide/the_tao_of_datastar>
- Attributes: <https://data-star.dev/reference/attributes>
- Actions: <https://data-star.dev/reference/actions>
- SSE events: <https://data-star.dev/reference/sse_events>
- Python SDK: <https://github.com/starfederation/datastar-python>
- Go SDK: <https://github.com/starfederation/datastar-go>
