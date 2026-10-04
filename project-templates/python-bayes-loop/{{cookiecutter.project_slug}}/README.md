# {{cookiecutter.project_name}}

{{cookiecutter.description}}

You bring a dataset and a question; a coding agent builds a Bayesian model
for it in this project while you watch on a dashboard and steer in the
agent's own chat. Data goes in the way you ask: all at once, half and then
the rest, or in chunks of any size. Each fit sees every row fed so far, so
you can watch the posterior settle as evidence accumulates. It's a local
tool: the agent, the loop and the dashboard all run on your machine.

## Start here: you, an agent, and a dataset

1. **Set up** (once):
   ```bash
   mise trust && mise run setup    # `mise run setup:gpu` on a CUDA machine
   mise run skills                 # the agent skills: PyMC Labs' modeling skills and this project's own
   ```
2. **Hand it to your agent.** Open any coding agent (Claude Code, Codex,
   Cursor, ...) in this directory and give it the data and the problem in
   your words:
   > Read AGENTS.md. Our data is in /path/to/export.csv. We want to know
   > which customer segments respond best to our campaign, with honest
   > uncertainty for the small ones. Build a model in this project's loop and
   > show me on the dashboard. Feed in the first half of the data first.

   It finds its instructions on its own: AGENTS.md points it at the
   `new-model` skill (`.agents/skills/new-model/SKILL.md`). The skill takes it
   through profiling the data, `prepare.sql`, the model in
   `src/{{cookiecutter.package_name}}/model.py`, the model contract (`mise run check-model`),
   a check against the real data, and then the running loop.
3. **Watch** at http://localhost:{{cookiecutter.default_port}}, or this machine's address from
   elsewhere. The agent brings the dashboard up first, then journals as it
   goes: what it found in the data, what it's changing and why, each model
   version with its diagnostics and a plain-English description, and its
   report. A status line says what it's doing right now. A figures carousel
   shows each version's posterior predictive check, traces, prior vs
   posterior and rank plots, drawn in your browser, plus any plot the agent
   makes; pin a few to compare, save any as PNG.
4. **Steer in the agent's chat.** "Now feed the rest." "Feed it 50 rows at a
   time so I can watch." "Try a Student-t likelihood." "Commit v3." The
   dashboard is read-only: it shows what the agent did and keeps the record.
5. **Come back later.** Open an agent here and say "continue". The journal and
   every model version's source live on the belt, so it can pick up where
   things were.

No data yet? Run the built-in example (customer conversion by city,
simulated with known coefficients): see the quick start below.

## How it works

A PyMC model is compiled into a single XLA program (warmup, sampling and
summaries) and reused for every fit. Data goes through a **belt**: one DuckDB
file served over the Quack protocol, that `feed` writes to, a GPU (or CPU)
sampler reads from, and a Datastar dashboard watches. `feed` moves a cursor
through a data file; each batch it sends is fit together with every row fed
before it.

## Quick start: the built-in example

```bash
mise run setup           # CPU; `mise run setup:gpu` for JAX's CUDA build (~3.5 GB)
mise run simulate        # data/sim.parquet, plus its true coefficients beside it
mise run loop:cpu        # db, sample, plots, dashboard in tmux; `loop` on a GPU
open http://127.0.0.1:{{cookiecutter.default_port}}
mise run feed --rows 10% # the first tenth: one fit
mise run feed --chunk 200  # the rest, 200 rows at a time: a fit per chunk
```

The intervals narrow toward the true coefficients (dashed) as rows are fed.
The CPU profile (`mise.cpu.toml`) uses a small problem and its own database
file. On a GPU: `mise run setup:gpu`, `mise run check-gpu` (want
`gpu [CudaDevice(id=0)]`), then `mise run loop`.

The loop's tmux session:

```bash
mise run loop:cpu up db dev        # just the belt and the dashboard (watch an agent before its first model)
mise run loop:cpu status           # running / exited, per service
mise run loop:cpu restart sample   # after editing model.py: recompile, refit the rows fed so far
mise run loop:cpu down             # Ctrl-C each service, db last (it checkpoints)
tmux attach -t {{cookiecutter.project_slug}}-cpu      # watch
```

`mise run up` (or `up:cpu`) runs the same services in the foreground instead.
`mise tasks` lists everything. Extra args pass through:
`mise run sample --sampler nuts --chains 8`. `.env` overrides `mise.toml`'s
defaults (your `FEED_FROM`, a real `QUACK_TOKEN`, or another `PORT` and
`QUACK_URL` for a second checkout); the CPU profile overrides both.

## Feeding data

`feed` reads `FEED_FROM` (default `data/sim.parquet`), in file order or
`FEED_ORDER_BY`'s, and remembers how far it got. It waits for each batch's
fit before sending the next, and prints a JSON line per fit.

| Command | Sends | Fits |
|---|---|---|
| `mise run feed` | the rest of the file (all of it, the first time) | one, on every row |
| `mise run feed --rows 50%` | the next half of the file | one |
| `mise run feed --rows 500` | the next 500 rows | one |
| `mise run feed --chunk 100` | the rest, 100 rows at a time | one per chunk, each on everything so far |
| `mise run feed --restart ...` | starts over at row 0, in a new run | |

A **run** (`runs`) is one pass through a file: its size and its labels
(`coords_for` over the whole file, so every fit of the run shares one set).
A changed file (path, order, size or mtime) starts a new run by itself. The
dashboard follows the newest fit's run and plots the posterior against rows
fed. After a model edit, `restart sample` refits the rows fed so far; no need
to feed again.

Each fit runs on every row fed so far, so many small chunks of a big file
cost many big fits. Chunk accordingly: one row at a time is for a few hundred
rows, not a hundred thousand.

## Your own model and data

Everything model-specific lives in `src/{{cookiecutter.package_name}}/model.py`. Feed, sample,
bench and the dashboard only use the names its docstring lists:

| Name | What |
|---|---|
| `OBS_DDL` | the `obs` table: one row per observation (feed adds `batch_id`) |
| `CONTEXT` | what the data means, in plain words; shown with the model |
| `DIMS` | var → dims, for exactly the free variables and Deterministics |
| `VIEW` | what the dashboard plots: `forest` (latest fit), `track` (as data is fed), `grid` (one 2-D variable, or `None`) |
| `coords_for(rows)` | labels for every dim, from the obs rows of a whole file |
| `from_arrow(rows, coords)` | obs rows → the arrays `build` takes as `pm.Data` |
| `build(data, coords)` | the PyMC model |
| `SIM_DIMS`, `draw_truth`, `simulate` | a simulator with known parameters: `mise run simulate`, the benchmark and the parameter-recovery test |

The workflow, which the `new-model` skill spells out step by step:

```bash
$EDITOR prepare.sql              # raw file -> data/<name>.parquet (clean, standardized)
mise run prepare
$EDITOR src/{{cookiecutter.package_name}}/model.py  # the contract above
mise run check-model             # the contract + logp checks, ~15 s on CPU
mise run test                    # end to end over a real belt, with your model
JAX_PLATFORMS=cpu uv run {{cookiecutter.project_slug}} bench --from data/<name>.parquet --n <row count> --reps 1 --params
echo FEED_FROM=data/<name>.parquet >> .env && mise run loop:cpu && mise run feed
$EDITOR src/{{cookiecutter.package_name}}/model.py && mise run check-model && mise run loop:cpu restart sample
```

`mise run check-model` catches what would otherwise fail silently in a
compile-once loop:

- a variable without `dims`, or `DIMS` out of step with `build`;
- an input that isn't `pm.Data` (it would be frozen into the program);
- a constant computed from the data inside `build` (`y.mean()` as a prior
  location goes stale after the first fit);
- obs rows that don't survive the obs table's column types;
- a file that doesn't load, label itself and build;
- a likelihood that doesn't run along the rows (padding rows would count; see
  the architecture section);
- a model that can't recover its own simulator's parameters.

The dashboard shows only the current model's fits (same `str_repr()` as the
newest fit's model), so an edit starts the panels over.

### The agent's journal

The agent posts to the dashboard with shell commands, so any agent harness
works:

- `mise run note "..."`: what it's changing and why, what happened, its
  report (`--kind report`) and commits (`--kind commit`). Each note is
  labeled with the model version it's about.
- `mise run status "..."`: what it's doing right now, shown beside the
  thread until the next one.
- `mise run describe -`: the "What this model says" text for the current
  version.
- `mise run figure plot.png --title "..."`: a plot of its own in the
  carousel.

The model's caption shows the version and the git revision it was compiled
from. Every compiled version keeps its `model.py` on the belt
(`{{cookiecutter.project_slug}} source vN`), so when you say "commit v3" the agent can restore
that version even after it has moved on, commit it and tag `model-v3`.

The status line also notices what the agent leaves in the project: a pulsing
dot while files under `src/`, `prepare.sql`, the profiles, tests or `data/`
changed in the last 2 minutes, grey when it's been quiet.

### Figures

The `plots` service computes figures for each model version's latest fit: a
posterior predictive check (calibration for a 0/1 outcome, a rootogram for
counts, densities otherwise), traces (density by chain beside the draws in
order), prior vs posterior, and rank plots for the headline variables. It
stores each figure's numbers on the belt as JSON (`/figures/ID.json`), and
the browser draws them with d3 (`figure-chart`), in the page's theme, with
tooltips. A new version renders within seconds; after that, at most every
`PLOTS_EVERY` seconds (60). `mise run figures --save DIR` writes each
figure's PNG or data.

Each figure has a "How to read this" chip (`plots.HOW_TO_READ`). The rank
plots need it most: every chain's draws are ranked among all chains' draws,
and each row is one chain's histogram of those ranks. Rows flat at the dashed
line mean the chains agree; a chain piled up at one end, or bulging in the
middle, explored a different part of the posterior.

On the dashboard they're one carousel: one figure at a time (← → or the
buttons under it), up to three pinned side by side for comparison (pins are
per browser), and Save PNG on each.

### Agent skills

`install-skills.sh` (run by `mise run skills`) installs into `.agents/skills/`,
symlinked into `.claude/skills/`, and pins them in `skills-lock.json`.
`npx skills experimental_install` restores that exact set. They are
gitignored; only the project's own `new-model` skill is committed.

| Skill | From | For |
|---|---|---|
| `new-model` | this repo | the model contract, feeding data, and the dataset → model workflow |
| `pymc-modeling`, `prior-elicitation`, `arviz-diagnostics`, `pytensor-workflows` | PyMC Labs via [Decision Hub](https://hub.decision.ai/orgs/pymc-labs) (`pymc-labs/python-analytics-skills`) | PyMC 6 / ArviZ 1 modeling, priors, diagnostics, shape errors |
| `bayesian-regression` | `brojonat/llmsrules` | start simple, upgrade the likelihood |
| `datastar` | `brojonat/llmsrules` | the dashboard |

## Architecture

```
feed ──insert a batch──▶  db (DuckDB + quack_serve)  ◀──read rows fed / insert fit── sample (GPU)
  ▲ waits for its fit          ▲
                     dashboard polls query('select max(id) ...'), streams SSE to browsers
```

Four services and a command, one database file, all on one machine:

| Process | Command | Job |
|---|---|---|
| `db` | `{{cookiecutter.project_slug}} db` | Owns `data/belt.duckdb`, creates the schema, serves it over Quack. Checkpoints on SIGINT/SIGTERM/SIGHUP. |
| `sample` | `{{cookiecutter.project_slug}} sample` | For each new batch, fits every row fed so far in its run; writes one summary row per scalar parameter. On start, refits the newest batch. |
| `plots` | `{{cookiecutter.project_slug}} plots` | Computes the dashboard's figures (PyMC on CPU, no JAX) from the thinned draws the sampler saves. |
| `serve` | `{{cookiecutter.project_slug}} serve` | The dashboard: model, journal, fits, figures, metrics. Read-only: no route writes. |
| `feed` | `{{cookiecutter.project_slug}} feed` | A command, not a service: sends the next rows of the file and waits for their fits. |

### Compile once, refit as data is fed (`compile.py`, `samplers.py`)

PyMC's JAX path folds every `pm.Data` into a constant, so new data means a
new XLA compile. `jaxify()` swaps each `pm.Data` for a symbolic input instead,
giving `logdensity(position, data)`. The sampler (`make_chees` or `make_nuts`)
puts BlackJAX warmup, sampling and the transform back to the model's
parameter space inside one `jax.jit`, compiled ahead of time with
`.lower().compile()`. A compiled program called with data of the wrong shape
or dtype raises instead of silently recompiling. The XLA persistent cache
(`.jax_cache/`) lets a restarted sampler skip compilation too.

A fit's row count grows as data is fed, so the logp weights each row's
likelihood terms (`WEIGHTS`), and the sampler pads the rows to a power of two
(at least 256) with weight-0 copies of the first row (`compile.pad`).
Programs are keyed by (padded rows, coords): feeding 919 rows in chunks of 25
compiles three programs, not 37. That's why the contract wants one likelihood
term per obs row, with the rows' dim first.

- **`chees`** (default): ChEES-tuned jittered HMC. Every chain takes the same
  number of leapfrog steps, so hundreds of chains run in lockstep on a GPU.
- **`nuts`**: window adaptation + NUTS. Chains vmapped on GPU, run one after
  another on CPU (where lockstep NUTS is ~20x slower).
- float32 by default: consumer GPUs run float64 at 1/32 to 1/64 speed.

### The belt (`belt.py`)

DuckDB locks a database file to one writing process. Quack (a DuckDB
extension, beta in 1.5) lets that process serve the file so any number of
clients can read and write it. The code is shaped around how Quack actually
behaves (details in `LEARNINGS.md`):

- Every read goes through `belt.read()`, which wraps the SQL in `query(...)`
  so it runs on the server. Plain queries against the attached database pull
  whole tables to the client.
- IDs are `time.time_ns()` from the writer: clients can't use sequences.
- Writes are made atomic by order, not transactions (ROLLBACK doesn't undo):
  payload rows first, then one marker row (`runs`, `batches`, `fits`).
  Readers only look at marker rows.
- Delivery is at-least-once: a batch is done when its `fits` row lands; a
  restarted sampler resumes after the newest.

| Table | Written by | Grain |
|---|---|---|
| `runs` | feed | one per pass through a data file: path, order, size, mtime, `coords` (JSON labels) — a marker |
| `batches` | feed | one per batch: its run, first row and row count — the marker |
| `obs` | feed | one per observation; columns from `model.OBS_DDL` |
| `truth` | feed | a simulated file's true value of every named parameter, per run |
| `models` | sample | one per compiled model: DOT graph, `str_repr()`, `CONTEXT`, `VIEW` as JSON, `model.py` source, git revision, padded rows |
| `fits` | sample | one per fit: timing, lag, ESS, R̂, divergences, rows fitted — the marker |
| `params` | sample | one per scalar per fit: `var`, `name` (`beta[Denver, income]`), `coords` JSON, mean/sd/quantiles, ESS, R̂, and the simulator's truth |
| `model_notes` | agent | the agent's description of a model version (`describe`) |
| `messages` | agent | the journal: notes, reports, commits, and statuses |
| `draws` | sample | thinned draws of some fits (each program's first, then every 30 s), for `plots`; the db keeps the newest 5 |
| `figures` | plots, agent | the carousel: each version's newest diagnostics as data (JSON) the browser draws, and every PNG the agent posted |

`mise run query "select name, q50 from params where var = 'mu' order by fit_id desc, pos limit 8"`
runs SQL on the server. A schema change (including `OBS_DDL`) makes `db`
refuse the old file; `mise run reset` (or `reset:cpu`) starts fresh.

### Labeled dims (`model.py`, `labels.py`)

Every axis is named (`dims`) and labeled (`coords`). The labels come from the
whole data file when a run starts, so every fit of the run shares them and
the sampler builds the model from them. A scalar is `beta[Denver, income]`
everywhere: in `params`, in `truth`, in the dashboard. `labels.scalars()` is
the one naming function; the simulator and the sampler must agree on it
because the dashboard joins on names.

### The dashboard (`web.py`, `templates/`, `static/components.js`)

One background task polls the belt every 100 ms with a ~2 ms server-side
query and renders the page regions once for all browsers. Each browser holds
one SSE stream (`GET /stream`) that receives only the regions that changed,
at most 4 times a second. The model region (graph + description) is sent
once per model; the dashboard region on every fit.

- What it plots comes from the model's `VIEW`, recorded on each `models` row:
  a forest of the latest fit, the `track` scalars against rows fed, and an
  optional rows × columns grid of one 2-D variable. Truth overlays and the
  coverage tile appear only for a simulated file.
- Model graph: `pm.model_to_graphviz` DOT, laid out in the browser by
  Graphviz compiled to WASM (no `dot` binary needed anywhere).
- Charts are d3 in Datastar Rocket web components (open shadow root, data in
  attributes). The figures' components fetch their data instead
  (`<figure-chart src="/figures/ID.json">`; ids never change, so it caches),
  which keeps the region small.
- `/healthz`, `/metrics` (Prometheus text, no client library).

## Benchmarks

`mise run bench` compares the compiled `nuts` and `chees` loops with
`pm.sample(nuts_sampler="numpyro")` (recompiles every call) and PyMC's
default sampler, JSON lines to `logs/bench.jsonl`. `rep 0` is the first fit
after the compile; later reps get fresh same-shape data and must not
recompile.

`bench --from FILE --n N` refits the file's full chunks of N rows instead
(`--n <row count> --reps 1` for the whole file; `--skip K` to start at chunk
K), and `--params` adds each rep's posterior summary: a bounded check of a
model on real data with no belt running.

## CLI

JSON on stdout, progress on stderr.

```bash
{{cookiecutter.project_slug}} db [--path data/belt.duckdb]
{{cookiecutter.project_slug}} simulate [--n 100000] [--dim group=20 ...] [--seed 0] [--out data/sim.parquet]
{{cookiecutter.project_slug}} feed [--from FILE] [--order-by COLUMN] [--rows N|P%] [--chunk N] [--restart] [--timeout 900]
{{cookiecutter.project_slug}} sample [--sampler chees|nuts] [--chains 256] [--warmup 300] [--draws 50]
{{cookiecutter.project_slug}} serve [--host 127.0.0.1] [--port {{cookiecutter.default_port}}] [--reload] [--replace]
{{cookiecutter.project_slug}} note [--kind note|report|commit] [--model ID] TEXT...   # or - for stdin
{{cookiecutter.project_slug}} status TEXT...
{{cookiecutter.project_slug}} describe [--model ID] TEXT...                            # or - for stdin
{{cookiecutter.project_slug}} source MODEL_ID|vN
{{cookiecutter.project_slug}} plots [--every 60]
{{cookiecutter.project_slug}} figure PLOT.png --title TEXT
{{cookiecutter.project_slug}} figures [--save DIR]                                     # --save: each figure's PNG or data
{{cookiecutter.project_slug}} bench [--sampler nuts|chees|pymc|pymc-numpyro|pymc-blackjax] [--reps 3] [--dim NAME=SIZE ...]
{{cookiecutter.project_slug}} bench --from data/x.parquet [--order-by COLUMN] --n 2000 [--skip K] [--params]
```

`--dim NAME=SIZE` sets a simulated dim's size; the names are `model.SIM_DIMS`'s.

Environment: `QUACK_URL`, `QUACK_TOKEN`, `BELT_DB`, `HOST`, `PORT`,
`LOG_LEVEL`; `FEED_FROM`, `FEED_ORDER_BY`, `FEED_TIMEOUT`; simulator sizes
`SIM_ROWS`, `BELT_DIMS` (`"group=5 feature=4"`); sample defaults
`SAMPLE_CHAINS`, `SAMPLE_WARMUP`, `SAMPLE_DRAWS` (see `mise.cpu.toml`);
`PLOTS_EVERY`.

## GPU notes

- `mise run setup:gpu` installs `jax[cuda13]` (the `gpu` extra); Turing
  (sm_75) and newer are supported.
- `XLA_PYTHON_CLIENT_PREALLOCATE=false` (in `mise.toml`) keeps JAX from
  grabbing 75% of VRAM up front.
- `Driver/library version mismatch` after a driver upgrade means the kernel
  module is stale: reboot (or `mise run loop:cpu` meanwhile).
