# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A live dashboard over a Parquet warehouse, with an assistant that can query
the data and drive the dashboard. It ships with a synthetic support-ticket
feed so everything works on first run; replace `generate` with a fetch of
your real data and keep the rest.

## Quick start

```bash
mise run setup       # uv sync
mise run build       # generate the feed, build data/warehouse/ (~15 s the first time)
mise run dev         # http://127.0.0.1:{{cookiecutter.default_port}}, hot reload, tees logs/serve.log
mise run loadtest    # in another terminal; watch http://127.0.0.1:{{cookiecutter.default_port}}/admin
```

`mise tasks` lists everything. Extra args pass through:
`mise run loadtest --levels 50,500 --churn 2`. For the assistant, put
`OPENROUTER_API_KEY` (or `LLM_API_KEY` plus `LLM_BASE_URL` for any
OpenAI-compatible endpoint) in `.env` (copy `.env.example`); without one the
dashboard works and the chat panel says it isn't configured.

## Architecture

**CQRS, twice.**

1. *Data:* the CLI is the write side. `generate` writes raw files; `build`
   turns them into typed Parquet plus small, query-shaped **read models** and
   writes `manifest.json` last. The server is the read side: it only reads
   the warehouse, and it hot-swaps to a new build when the manifest changes.
2. *UI ([Datastar](https://data-star.dev/)):* each page is one long-lived SSE
   read (`GET /stream`) that re-renders the page's live regions and morphs
   them in (a "fat morph"). Commands (`POST /filter/...`) mutate server-side
   state and answer `204`. What a dashboard shows is per-session state keyed
   by a `sid` cookie, so a command wakes only that session's streams. A new
   build wakes all of them.

The page stream carries three regions (the dataset builder, the dashboard,
the chat) and sends only the ones that changed. Sessions looking at the same
dataset share one render; every query is memoized on `(sql, params)`, so an
edit to one dimension re-runs only the queries that depend on it. Streams
are Brotli-compressed per connection, one flush per event; a repeat render
costs a few bytes on the wire.

### Every panel is one question

"Tickets per value of dimension D, given every selection except D's." The
year chart is the years picker's counts, the map is the states picker's, the
category bars are the categories picker's. One memoized query each feeds a
picker and a panel, and totals are the year counts summed over the selected
years. See `Warehouse.measures`.

### Charts: d3 in Rocket web components

The server never draws. It renders each chart as a bare custom element with
its data in attributes, as part of the region's fat morph:

```html
<chart-bars id="year-bars" series='[["2019",14012],...]' highlight="2026" selectable="true">
```

When a later morph changes an attribute, Rocket decodes it and d3 redraws
with a transition. Components render into an **open shadow root**, so the
morph diffs only the host's attributes and never touches d3's SVG. Chart
data never goes into signals; it lives on the server and arrives as markup.
User gestures (drag a year range, click a state) come back as DOM events
(`chart-range`, `chart-toggle`, `chart-state`) that the page turns into
commands. Components: `chart-bars`, `chart-hbars`, `chart-lines`,
`chart-sparkline`, `chart-map` (US states, pre-projected us-atlas), in
`static/components.js`, loaded with d3 through an import map. No build step.

### The dataset builder

The filter is a dataset you build by opting values in, per dimension
(products, plans, channels, categories, states, years opened): empty = any,
several values = any of them (OR within a dimension, AND across). Chips and
"+ add" pickers with faceted counts and search; drag across the year chart;
click states on the map; CSV / Parquet download of exactly that dataset.
Which picker is open is server state, so options are only computed for the
one someone is looking at.

### The assistant: "Ask about the data"

A chat panel docked bottom-right. Conversations are per-session server
state; replies stream into the chat region on the page's stream.

- **Tools.** `set_view` / `get_view` drive the same per-session filter as the
  page's controls (a tool call goes through the same `update_filter` and
  wakes the same stream, so the browser can't tell a person's change from
  the model's). `query_data` runs one read-only DuckDB SELECT in a
  locked-down sandbox. `search_text` is SQLite FTS5 over what customers
  wrote, aggregated in DuckDB. `show_chart` runs SQL and plots **what it
  returns** in the chat (the model can't invent the numbers). `submit_feedback`
  drafts a report the user must click to send.
- **The system prompt** is `docs/assistant.md` + the live schema (generated
  from the warehouse, so it can't drift) + `docs/methodology.md` (also served
  at `/methodology`) + build facts. Stable parts first, cached by the
  provider for `anthropic/*` models.
- **The SQL sandbox** (`sql.py`) is its own DuckDB instance: file access only
  inside the warehouse, `lock_configuration`, one SELECT, 2 threads, a memory
  cap, a timeout that interrupts, capped results.
- **Provider-agnostic:** a hand-written client for the OpenAI Chat
  Completions streaming format (`llm.py`, no SDK). OpenRouter, OpenAI, vLLM,
  Ollama all work by changing `LLM_BASE_URL`.
- **Guards:** model output rendered as Markdown with raw HTML off; one reply
  per session at a time; `LLM_MAX_CONCURRENT` across users; a context-window
  meter; a daily token budget (`LLM_DAILY_TOKENS`) read from the app DB.
- **Feedback:** after the third answer (or from the Feedback button) a
  check-in asks "How is the assistant doing? 1 Bad · 2 Fine · 3 Good". Ratings
  and sent reports go to the app DB with the transcript and dataset;
  `mise run feedback` reads them.

### The app database

The warehouse is rebuilt from the source and holds nothing users made. What
the service **keeps** (feedback, LLM usage per day) is one SQLite file
(`APP_DB`, default `data/app.sqlite`) in WAL mode, migrations an
append-only list tracked by `PRAGMA user_version`. In production litestream
replicates it to object storage and restores it into an empty volume.

## The data

### The synthetic feed (`generate`)

`src/{{cookiecutter.package_name}}/generate.py` writes one gzipped CSV per year
(`data/raw/tickets-YYYY.csv.gz`) of a fictional company's support tickets:
six products (two launching partway), four plans, four channels (chat
replacing phone), growth, weekly and yearly seasonality, a few incidents a
year with tell-tale wording, and resolution time, escalation, satisfaction
and refunds that depend on all of it. It's deterministic: each day's tickets
come from a stream seeded by `(seed, date)`, so the same arguments give
byte-identical files, and running it daily appends a day. A file is replaced
only when its content changed.

`--since`, `--until`, `--daily` (volume) and `--seed` configure it
(`GENERATE_*` env vars too). `docs/methodology.md` describes the world it
models; the assistant reads that page.

### Replacing it with real data

Keep the contract and everything downstream keeps working:

1. Rewrite `generate` (or add a `fetch` command beside it) to put your files
   under `data/raw/`, replacing a file only when its content changed, so the
   build's content hash is stable when nothing moved.
2. Update `schema.RAW_COLUMNS` and `ingest.TICKETS_SQL` / `READ_MODELS` for
   your columns. Keep the rollups at exactly the grain of the dashboard's
   filters, and store sums, not averages.
3. Update `warehouse.DIMENSIONS` / `METRICS`, the templates, `prompt.py`'s
   notes, `docs/*.md`, `evals/cases.toml` and the tests.

### Keeping data current

`generate && build` (`deploy/refresh.sh`) is idempotent and cheap when
nothing changed: `build` skips when the raw files' content hash and the
build's recipe hash both match the manifest, and refuses (exit 1, live build
untouched) when the new data has 2%+ fewer tickets or ends earlier than the
current build. A running server picks up a new build within a second.

**When to run it is not this project's business.** The container runs
`refresh.sh` once at startup (skip with `SKIP_REFRESH=1`); anything that
can run a command on a schedule can do the rest:

- **A sidecar** in the same pod sharing the `data` volume:
  `command: ["sh", "-c", "while sleep 3600; do /app/deploy/refresh.sh; done"]`.
- **A CronJob** with the same image and `command: ["/app/deploy/refresh.sh"]`,
  and a PersistentVolumeClaim in place of the server's `emptyDir` so both
  see one warehouse.
- **A systemd timer** on a plain box: `ExecStart=/path/to/.venv/bin/sh
  deploy/refresh.sh` with `OnCalendar=hourly`.

### Warehouse (`data/warehouse/`)

| File | Grain | Notes |
|---|---|---|
| `tickets.parquet` | ticket | every column, typed, with `year`, `month`, `resolved`, `resolution_hours` |
| `tickets_state_year.parquet` | product × plan × channel × category × state × year | sums only; the dashboard's workhorse |
| `product_month.parquet` | product × category × plan × channel × month | monthly trends |
| `states.parquet` | state | FIPS, name, 2020 Census population |
| `ticket_text.sqlite` | ticket | contentless FTS5 over subject + body (porter stemming) |
| `manifest.json` | – | build metadata; written last, atomically |

## CLI

JSON on stdout, progress on stderr, non-zero exit on failure.

```bash
{{cookiecutter.project_slug}} generate [--since 2019-01-01] [--until YYYY-MM-DD] [--daily 25] [--seed 1]
{{cookiecutter.project_slug}} build [--force]
{{cookiecutter.project_slug}} query "select product, count(*) n from tickets group by 1 order by 2 desc"
echo "select ..." | {{cookiecutter.project_slug}} query
{{cookiecutter.project_slug}} serve [--reload] [--port {{cookiecutter.default_port}}]
{{cookiecutter.project_slug}} loadtest [--levels 5,10,100,1000] [--hold 15] [--churn 0] [--chat 0]
{{cookiecutter.project_slug}} fakellm [--port 8399]
{{cookiecutter.project_slug}} eval [ID-SUBSTRING...] [--model M] [--judge M] [--repeat N]
{{cookiecutter.project_slug}} feedback [--since 2026-09-01] [--transcripts]
{{cookiecutter.project_slug}} usage [--days 30]
```

## HTTP

| Route | Kind | |
|---|---|---|
| `GET /` | page | first paint; issues the `sid` cookie |
| `GET /stream` | read (SSE) | builder, dashboard and chat regions, re-rendered on this session's changes |
| `POST /filter` | command | `metric`, or a whole dimension's set (`products`, `plans`, `channels`, `categories`, `states`, `years`); 204 |
| `POST /filter/toggle` | command | `{dim, value}`: opt one value in or out |
| `POST /filter/range` | command | `{from, to}`: years opened, from a drag on the year chart |
| `POST /filter/clear` | command | `{dim}` clears one dimension; `{}` clears the dataset |
| `POST /builder/open` · `/builder/search` | command | the open picker and its search text (session state) |
| `GET /dataset.csv` · `/dataset.parquet` | download | every ticket in the session's dataset |
| `POST /chat/send` · `/chat/clear` | command | `{message}`; the reply streams into the chat region |
| `POST /chat/feedback` · `/chat/feedback/draft` | command | the check-in, and sending/discarding a drafted report |
| `GET /methodology` | page | the methodology doc (part of the assistant's system prompt) |
| `GET /admin` · `/admin/stream` | page + read | diagnostics: CPU, RSS, streams, loop lag, patches, compression, query and render time, cost by connected clients |
| `PUT /admin/threshold/{metric}` | command | form field `value`; ≤0 clears |
| `GET /admin/samples?since=<unix>` | JSON | raw samples, for the load tester and `jq` |
| `GET /metrics` | Prometheus text | no client library |
| `GET /healthz` | text | `ok` |

## Load testing, profiling, evals

- **`mise run loadtest`** ramps virtual clients (GET `/`, then hold
  `/stream`); `--churn N` makes each edit its dataset every ~N s and times
  command → patch. The server's own samples over each level are summarized
  into `logs/loadtest.jsonl`. Watch `/admin`'s "cost by connected clients".
- **Chat under load, for free:** `mise run fakellm`, `mise run
  serve:fakellm`, `mise run loadtest:chat`.
- **`mise run profile`** runs the server under py-spy; Ctrl-C writes
  `logs/profile.svg`.
- **`mise run eval`** runs `evals/cases.toml` against the real model through
  the real app in-process, checking tools used, the view left behind, true
  numbers (computed by SQL at run time), charts, a rubric and groundedness
  (judge model). It costs money; use `--repeat` before trusting a pass rate.

## Config

Environment variables (mise loads `.env`):

| Env | Default | |
|---|---|---|
| `DATA_DIR` | `data` | root for `raw/` and `warehouse/` |
| `APP_DB` | `$DATA_DIR/app.sqlite` | the app database |
| `HOST` / `PORT` | `127.0.0.1` / `{{cookiecutter.default_port}}` | `mise.toml` sets `PORT`; pass `--port` to override it |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | any OpenAI-compatible endpoint |
| `LLM_API_KEY` | – | falls back to `OPENROUTER_API_KEY`, then `OPENAI_API_KEY`; chat is off without one |
| `LLM_MODEL` | `anthropic/claude-haiku-4.5` | |
| `LLM_MAX_TOKENS` / `LLM_MAX_CONCURRENT` / `LLM_CONTEXT_WINDOW` | `4096` / `8` / looked up | |
| `LLM_REASONING_TOKENS` | `0` | thinking budget per model turn |
| `LLM_DAILY_TOKENS` | `10000000` | chat refuses new messages past this many tokens a UTC day; `0` = no limit |
| `EVAL_JUDGE_MODEL` | `anthropic/claude-sonnet-5` | |
| `GENERATE_SINCE` / `GENERATE_DAILY` / `GENERATE_SEED` | `2019-01-01` / `25` / `1` | the synthetic feed |
| `BUILD_MEMORY` / `BUILD_THREADS` | DuckDB's | cap the build (it spills to disk past the memory cap) |
| `DUCKDB_MEMORY` / `DUCKDB_THREADS` | DuckDB's | cap the server's DuckDB; in a container, match the pod's limits |
| `QUERY_CACHE` | `20000` | memoized query results |
| `SANDBOX_MEMORY` | `1GB` | the assistant's SQL sandbox |
| `SAMPLE_INTERVAL` | `1` | seconds between /admin samples |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / text | `json` for structured logs |

## Development

```bash
mise run test
mise run lint      # mise run fmt to fix
mise run stop      # kill an orphaned server on $PORT
```

## Deploy

Kubernetes (k3s with Traefik and cert-manager assumed): one image,
`$DOCKER_REPO/{{cookiecutter.project_slug}}:<git hash>`, kustomize in `k8s/prod`,
secrets generated from gitignored files.

```bash
cp .env.prod.example .env.prod                                  # LLM key, optional litestream bucket
printf 'ADMIN_USER=admin\nADMIN_PASSWORD=...\n' > .env.admin    # basic auth for /admin, /metrics
git commit ...                                                  # the image tag is the commit
mise run deploy                                                 # build + push, htpasswd, apply, wait
mise run k8s-status | k8s-logs | k8s-restart | k8s-preview | k8s-delete
```

What runs: one `Deployment` (1 replica, `Recreate`: sessions and streams are
in memory) whose entrypoint refreshes the warehouse into an `emptyDir` and
serves, wrapped in `litestream replicate` when `LITESTREAM_*` are set; a
`Service`; two `Ingress`es, with `/admin*` and `/metrics` behind Traefik
basic auth. The pod is disposable: the warehouse is rebuilt from the source
and the app DB comes back from object storage. See "Keeping data current" to
add a refresh schedule.

## Layout

```
src/{{cookiecutter.package_name}}/
  cli.py        click entry point
  schema.py     raw columns, US states
  generate.py   the synthetic source (replace with your fetch)
  ingest.py     write side: raw -> Parquet read models + FTS index + manifest
  warehouse.py  read side: Filter, dimensions, metrics, memoized queries
  web.py        Starlette app: pages, streams, commands, chat, /admin, /metrics
  stream.py     compressed SSE responses + Hub (keyed watcher broadcast)
  metrics.py    Collector, Sampler, limits, Prometheus text
  appdb.py      the app database: feedback, LLM usage
  llm.py        streaming client for any OpenAI-compatible /chat/completions
  chat.py       per-session conversations, the tool loop, context accounting
  tools.py      the assistant's tools
  sql.py        the read-only DuckDB sandbox for model-written SQL
  search.py     SQLite FTS5 search over ticket text
  prompt.py     the system prompt: guide + live schema + methodology + facts
  evals.py      the eval runner;   evals/cases.toml is the battery
  fakellm.py    a free local LLM for load tests
  loadtest.py   N virtual browser clients
  display.py    number formatting for templates
  logs.py       pretty or JSON logs
  docs/         assistant.md, methodology.md
  static/       components.js (d3 + Rocket), favicons
  templates/    layout, builder, dashboard, chat, admin, methodology (Jinja2)
deploy/         run.sh (entrypoint), refresh.sh (what schedulers call), render.sh, litestream.yml
k8s/prod/       Deployment + Service, Ingresses, kustomization
```
