# Learnings

Hard-won knowledge. Each entry: what happened, why it was surprising, how to
avoid it. Most of these were learned building the project this template was
extracted from; keep adding your own.

## Datastar and Rocket

**Use an open shadow root for anything d3 draws.** Datastar's morph syncs a
host element's attributes and then morphs its *light-DOM* children toward the
server's markup. The server sends an empty `<chart-bars ...></chart-bars>`,
so in Rocket's `light` mode every patch would morph away d3's SVG. In
`mode: 'open'` the chart lives in the shadow root and the morph only updates
attributes, which flow through the prop codec to `observeProps` and d3. Also:
put an `id` on every component host (the morph then keeps the same element
instance, so transitions run), and set `renderOnPropChange: false`
(otherwise Rocket re-runs `render()` and replaces the skeleton d3 draws
into).

**`datastar-rocket.js` is a complete Datastar bundle plus Rocket**, not an
add-on. Load it instead of `datastar.js`, never both.

**Rocket's `emit(type, 'CA')` sends no detail.** A string second argument is
treated as another event name, so it dispatches two detail-less events.
Always emit an object: `emit('chart-state', { state: 'CA' })`.

**Emit JSON attributes with Jinja's `tojson` inside single-quoted
attributes.** `tojson` escapes `'` but not `"`.

**Clearing a form after `@post` is racy unless you use `payload`.** With
`{contentType: 'form'}` the FormData is built inside the action's async flow,
so `el.reset()` right after can empty it first. `{payload: {...}}` is
evaluated synchronously. Pair it with `data-ignore-morph` on inputs so
stream re-renders never touch what the user is typing.

**Keep a chat log scrolled to the bottom with CSS:** `flex-direction:
column-reverse` on the scroll container, the messages in one normal-order
child. No scroll code survives morphs as well.

**One page stream, several regions: send only what changed.** Chat tokens
wake the same session stream as filter changes. Re-rendering every region is
cheap when the expensive one is cached; *sending* them all isn't. Compare
each region's HTML with what was last sent.

**A tool call is just another command source.** Because the dashboard's
state is server-side, letting the LLM drive the UI took no client code: the
tool calls the same `update_filter` and `hub.notify(sid)` as the form's
POST. If a feature seems to need "the server pushing UI actions to the
browser", check whether it's really "the server changing state the browser
already renders".

**A first paint is not a snapshot.** `GET /` renders its regions one after
another and awaits DuckDB in between, so a chat reply that lands mid-render
can show up in the chat region while the builder above it was rendered
before the reply's tool call. In the browser the stream repaints both at
once; in tests, fetch the page again after the reply finishes (see
`tests/test_chat.py::wait_for`).

## Starlette and serving

**`GZipMiddleware` skips `text/event-stream`** on purpose, so SSE goes out
uncompressed unless you compress it yourself (`stream.sse`, one flush per
event).

**Per-stream compressors are paid per connected client.** A Brotli encoder
at quality 5 / `lgwin=22` holds ~1.5 MB; 1000 streams were 2.2 GB RSS.
q3/`lgwin=18` is ~350 KB and still shrinks a repeat 16 KB render to ~14 bytes.
Measure encoder settings in separate processes (the allocator reuses freed
memory and skews in-process comparisons) and re-run the load test after
touching them.

**`request.form()` needs `python-multipart`,** even for urlencoded bodies;
without it Starlette 500s with an assertion.

**Jinja autoescape escapes a pre-rendered region.** Wrap pre-rendered HTML in
`markupsafe.Markup` before passing it to another template, or the page
renders the region as text and still returns 200.

**`StrictUndefined` makes `dict.missing_key` an error, which is what you
want.** A typo'd variable rendering as "" made buttons silently vanish.
Test membership explicitly: `"key" in d`.

**`trim_blocks` eats the space between sentences** built from Jinja `if`
blocks. Build multi-sentence text as a list and `join(" ")`.

**Starlette's `TestClient` can't read an infinite SSE response.** It waits
for the body to finish, so a test that opens `/stream` hangs forever. Test
the stream against a real server (`curl -sN -m 3 .../stream`; exit 28 is the
stream working).

**Hot reload can outrun `build`.** Code expecting new read models reloads
before the build that writes them finishes. `Warehouse.reload_if_changed`
checks for every required file and keeps serving the previous build (or
"not ready") instead of crashing startup.

## DuckDB and SQLite

**DuckDB sizes its thread pool and memory to the node, not the pod.** In a
2-CPU pod on a 4-core node it ran 4 threads per query and sat at its CPU
limit; `SET threads = 2` (`DUCKDB_THREADS`) cut CPU p50 at 300 clients from
190% to 27%. Same for anything that reads `os.cpu_count()`.

**Personal filters kill whole-result caching; memoize queries instead.** A
cache keyed on the whole filter hit ~0% once every user built their own
dataset. Memoizing on `(sql, params)` works because one edit changes one
dimension and every query that ignores it is unchanged. Then notice that
different panels ask the same question (the year chart *is* the years
picker's counts), and don't compute what nobody's looking at (closed
pickers).

**Coarse rollups beat in-memory tables.** Rollups at exactly the grain of the
dashboard's filters halved query time for ~0 memory; in-memory tables cost
hundreds of MB for less. Before adding memory or caches, check whether the
read model's grain is finer than any question asks.

**Never bind large Python lists as DuckDB parameters.** A 34K-element list
took ~2.5 s to convert, every query. Pass one comma-joined string and
`unnest(string_split(?, ','))` into a temp table (~17 ms).

**Substring search needs an index, not a different database.** `ILIKE` over
millions of rows takes seconds; SQLite FTS5 answers a phrase in
milliseconds with stemming and `NEAR`. FTS5 finds ids; DuckDB aggregates
them.

**`any_value(text)` in a GROUP BY can't spill.** Under a 768 MB cap it held
a gigabyte of text in aggregate state and died. Aggregate small values and
join the text back; joins stream. Likewise `fetchall()` of a whole text
column: stream with `fetchmany`.

**Test the build under the production limits** (`systemd-run --user --scope
-p MemoryMax=... -p CPUQuota=...` locally) before the node does it for you.

**`SET enable_progress_bar = false`** on every connection, or DuckDB draws
progress bars on stderr for long queries, even in a server. In-memory
connections reject it as a `config=` option; run it as a statement.

**`sqlite3.executescript` commits before it runs.** `BEGIN` followed by
`executescript(migration)` isn't atomic. Put `BEGIN; ... PRAGMA
user_version = N; COMMIT;` inside the script (`AppDB._migrate`).

## Data

**A source can publish a truncated file with perfect checksums.** Hashes only
prove you got what they published. A daily dataset never legitimately loses
2% of its rows or moves its latest date backwards: the build refuses, and
the site keeps serving yesterday's data.

**An ordinal axis silently closes gaps.** A band scale over the returned
years put 2009 next to 2011. Zero-fill continuous domains on the server
(`_year_series`), or fill with null where "no data" isn't zero.

**A choropleth of raw counts is a population map.** Default to rates or a
self-normalizing index, and hatch low-n states instead of coloring them.

## The assistant

**A model will describe a chart it can't see.** Return enough for it to
describe what was drawn: stats per panel and series (first, last, min, max,
total), the table when small, and a prompt rule to describe charts only
from those.

**Charts from the model: take SQL, not numbers.** The server plots what the
query returns, so a chart can't show an invented number, and the SQL is
visible in the chip.

**Never make the model re-derive server state it can be handed.** Rebuilding
the user's dataset from the view's fields quietly dropped a dimension. Hand
it `sql_filter`, built by the same `Filter.where()` as the dashboard, and
test that it reproduces the dashboard's totals.

**Give facts the model doesn't have to derive.** "The current year is
partial" led to the wrong year being called partial; "Partial year: 2026.
Last full year: 2025" didn't.

**Tell the model how to remove a filter**, with phrasing-to-argument
examples ("all products" → `products: []`). And grep the prompt's examples
when you add a rule: the model copies examples over rules.

**Write the methodology for a literal reader.** A small model "helpfully"
contradicted a correct but easy-to-misread sentence. After editing it,
re-ask the tricky questions against the real model.

**Evals: one run is a noisy sample.** The same battery went 17 → 19 → 18 of
23 with no relevant change. Use `--repeat` and compare pass rates; what's
stable is the *kind* of failure. Compute truths by SQL at run time (the data
grows), and allow several acceptable answers for ambiguous questions.

**Reasoning shares `max_tokens` on OpenRouter**, so send `max_tokens = reply
cap + budget`, and pass the turn's `reasoning_details` back during a tool
loop. Judges need room too: a judge with 1024 tokens sometimes spent it all
reasoning and answered nothing.

**Sum usage across tool rounds.** A reply that calls tools makes 2–4 model
turns, each with the full system prompt; counting only the last undercounts
cost.

**Read the transcript that comes with feedback.** It's where the second,
silent bug shows up. Store transcripts with feedback.

## Tooling

**mise renders task scripts as templates,** so `{{ '{{' }}PLACEHOLDER{{ '}}' }}` in a task's `run`
fails. Put such scripts in files (`deploy/render.sh`).

**mise appends task args to the end of the command string,** so `cmd | tee
log` plus `--flag` becomes `tee log --flag`. Wrap it: `f() { cmd "$@" | tee
log; }; f`.

**mise's `[env]` overrides inline variables:** `PORT=9000 mise run serve`
still binds the `mise.toml` port. Pass `--port` (or set the task's own
`env`).

**`ruff format` breaks scripted string-replace edits:** an edit written
against pre-format text matches nothing and silently doesn't happen. Use an
exact-match edit that fails loudly, and re-grep after any script that
failed partway.

**A `!=` label selector matches objects that lack the label.** `kubectl
delete -l 'app=x,component!=storage'` would delete an unlabelled volume.
Label protected objects explicitly.
