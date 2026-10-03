# {{cookiecutter.project_name}}

{{cookiecutter.description}}

You bring a dataset and a question; a coding agent builds a Bayesian model
for it in this project, and you watch and steer from a dashboard while it
works. The model refits on every batch of data that lands on a **belt**
(DuckDB served over the Quack protocol), so it can keep up with data that
keeps arriving.

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
   > uncertainty for the small ones, and we'll keep adding data monthly.
   > Build a model in this project's loop and show me on the dashboard.

   It finds its instructions on its own: AGENTS.md points it at the
   `new-model` skill (`.agents/skills/new-model/SKILL.md`). The skill takes it
   through profiling the data, `prepare.sql`, the model in
   `src/{{cookiecutter.package_name}}/model.py`, the model contract (`mise run check-model`),
   a check against the real data, and then the running loop.
3. **Watch and steer** at http://localhost:{{cookiecutter.default_port}}, or this machine's address
   from elsewhere. The agent brings the dashboard up first, then posts as it
   goes: what it found in the data, what it's changing and why, each model
   version with its diagnostics, a plain-English description of the model,
   and its report. A figures carousel shows each version's posterior
   predictive check, prior vs posterior, caterpillars and rank plots, plus
   any plot the agent makes; pin a few to compare, save any as PNG. A pulsing dot means it's working. Type feedback in the
   box; it reads it and carries on. Click **Approve the current model** on a
   version you want to keep: it commits it and tags it `model-vN`.
4. **Come back later.** Open an agent here and say "continue". The thread and
   your unread feedback live on the belt, so it picks up where things were.

No data yet? `mise run up:cpu` runs the built-in example (customer conversion
by city, simulated, with drifting true coefficients). The rest of this README
is the reference: how the loop works, the model contract, the CLI.

## How it works

A PyMC model is compiled once into a single XLA program (warmup, sampling and
summaries) and refit on every batch that lands on the belt: one DuckDB file
that a feeder writes to, a GPU (or CPU) sampler reads from, and a live
Datastar dashboard watches.

## Quick start: the built-in example

```bash
mise run setup:gpu    # uv sync --extra gpu (JAX's CUDA build); `mise run setup` for CPU only
mise run skills       # install the agent skills (install-skills.sh)
mise run check-gpu    # want: gpu [CudaDevice(id=0)]
mise run up           # db + feed + sample + dashboard, each tees logs/<name>.log
open http://127.0.0.1:{{cookiecutter.default_port}}
```

No GPU (or a driver that needs a reboot)? `mise run setup` skips the ~3.5 GB of
CUDA wheels, and `mise run up:cpu` runs the same belt on CPU with a small
problem and its own database file (`mise.cpu.toml`).

To run the belt in the background instead, with one tmux window per service
(the way an agent iterates on a model while you watch):

```bash
mise run loop:cpu                  # or `loop` on a GPU; session named after this directory
mise run loop:cpu up db dev        # just the belt and the dashboard (watch an agent before its first model)
mise run loop:cpu status           # running / exited, per service
mise run loop:cpu restart sample   # after editing model.py: recompile, re-fit the newest batch
mise run loop:cpu down             # Ctrl-C each service, db last (it checkpoints)
tmux attach -t {{cookiecutter.project_slug}}-cpu      # watch
```

For the model description, copy `.env.example` to `.env` and set
`OPENROUTER_API_KEY` (or `LLM_API_KEY` + `LLM_BASE_URL` for any
OpenAI-compatible endpoint). Without it the dashboard works and says how to
turn the description on.

`mise tasks` lists everything. Extra args pass through:
`mise run sample --sampler nuts --chains 8`. `.env` overrides `mise.toml`'s
defaults (a real `QUACK_TOKEN`, or another `PORT` and `QUACK_URL` for a second
checkout); the CPU profile overrides both.

## Your own model and data

Everything model-specific lives in `src/{{cookiecutter.package_name}}/model.py`. Feed, sample,
bench and the dashboard only use the names its docstring lists:

| Name | What |
|---|---|
| `OBS_DDL` | the `obs` table: one row per observation (feed adds `batch_id`) |
| `CONTEXT` | what the data means, in plain words; shown with the model, sent to the LLM |
| `DIMS` | var → dims, for exactly the free variables and Deterministics |
| `VIEW` | what the dashboard plots: `forest` (latest fit), `track` (across fits), `grid` (one 2-D variable, or `None`) |
| `coords_for(rows)` | labels for every dim, from the obs rows of a whole file |
| `from_arrow(rows, coords)` | obs rows → the arrays `build` takes as `pm.Data` |
| `build(data, coords)` | the PyMC model |
| `SIM_DIMS`, `draw_truth`, `drift`, `simulate` | a simulator with known parameters: the default feed, the benchmark and the parameter-recovery test |

The workflow, which the `new-model` skill (`.agents/skills/new-model/SKILL.md`)
spells out step by step:

```bash
$EDITOR prepare.sql              # raw file -> data/<name>.parquet (clean, standardized)
mise run prepare
$EDITOR src/{{cookiecutter.package_name}}/model.py  # the contract above
mise run check-model             # the contract + logp checks, ~10 s on CPU
mise run test                    # end to end over a real belt, with your model
JAX_PLATFORMS=cpu uv run {{cookiecutter.project_slug}} bench --from data/<name>.parquet --n 2000 --params
echo FEED_FROM=data/<name>.parquet >> .env && mise run loop:cpu
$EDITOR src/{{cookiecutter.package_name}}/model.py && mise run check-model && mise run loop:cpu restart sample
```

`mise run check-model` catches what would otherwise fail silently in a
compile-once loop:

- a variable without `dims`, or `DIMS` out of step with `build`;
- an input that isn't `pm.Data` (it would be frozen into the program);
- a constant computed from the data inside `build` (`y.mean()` as a prior
  location goes stale after the first batch);
- obs rows that don't survive the obs table's column types;
- a file that doesn't load, label itself and build;
- a model that can't recover its own simulator's parameters.

`feed --from FILE` replays a Parquet, CSV or JSON file through the belt in
full chunks of `--n` rows, in file order or `--order-by COLUMN`. Every chunk
shares the labels `coords_for` derives from the whole file, so they all reuse
one compiled program; a short tail is skipped rather than compiled.

`sample --refit N` re-fits the newest N batches on start, so a sampler
restarted after a model edit shows the new model on data already in the
belt. The dashboard shows only the current model's fits (same `str_repr()` as
the newest fit's model), so an edit starts the panels over.

### Watching and steering the agent

The dashboard has an agent thread. The agent posts what it's changing and
why (`mise run note`), what happened, and its report; each message is
labeled with the model version it's about, and the model's caption shows the
version and the git revision it was compiled from. The agent also writes the
"What this model says" text for each version (`mise run describe`); an LLM
key in `.env` only fills in until it does. You can type feedback or approve
the current model from any browser that reaches the dashboard
(`FEEDBACK_FROM=any`, the default) or only from the machine the agent runs
on (`FEEDBACK_FROM=local`): feedback steers an agent with a shell, so pick
`local` on a network you don't trust.

- **Feedback** goes to the agent's inbox: it reads it with `mise run inbox`
  after each change, or blocks on `mise run inbox --wait` once it's done
  (the thread then says "waiting for feedback"). The thread marks each
  message read when the agent has picked it up.
- **Approve** asks the agent to commit that model version: it restores that
  version's `model.py` if it has moved on (`{{cookiecutter.project_slug}} source vN`), commits,
  tags `model-vN`, and posts the commit to the thread. Every compiled version
  keeps its source on the belt, so nothing is lost before you approve.
- **Resuming:** the thread and the inbox live on the belt, not in the
  agent's session. A new or continued session runs `mise run loop:cpu` and
  `mise run inbox` and carries on (AGENTS.md says so).

The thread's header shows what the agent is doing, from what it leaves in
the project: a pulsing green dot while it works (files under `src/`,
`prepare.sql`, the profiles, tests, `data/` changed in the last 2 minutes, or
a message), amber while it's blocked on `inbox --wait`, grey when it's been
quiet (thinking, a long command, or stopped).

These commands only need a shell, so any agent harness works.

### Figures

The `plots` service (part of `mise run loop`) renders ArviZ figures for each
model version's latest fit: a posterior predictive check (calibration for a
0/1 outcome, a rootogram for counts, densities otherwise), prior vs posterior
for the headline variables, caterpillars for long vectors, and rank plots. A
new version renders within seconds; after that, at most every `PLOTS_EVERY`
seconds (60). The agent adds its own with `mise run figure plot.png --title
"..."`, and reads them all with `mise run figures --save DIR`.

On the dashboard they're one carousel: one figure at a time (← → or the
thumbnails), up to three pinned side by side for comparison (pins are per
browser), and Save PNG on each. Figures and the thinned draws they're drawn
from live on the belt; the db process prunes superseded renders.

### Agent skills

`install-skills.sh` (run by `mise run skills`) installs into `.agents/skills/`,
symlinked into `.claude/skills/`, and pins them in `skills-lock.json`.
`npx skills experimental_install` restores that exact set. They are
gitignored; only the project's own `new-model` skill is committed.

| Skill | From | For |
|---|---|---|
| `new-model` | this repo | the model contract and the dataset → model workflow |
| `pymc-modeling`, `prior-elicitation`, `arviz-diagnostics`, `pytensor-workflows` | PyMC Labs via [Decision Hub](https://hub.decision.ai/orgs/pymc-labs) (`pymc-labs/python-analytics-skills`) | PyMC 6 / ArviZ 1 modeling, priors, diagnostics, shape errors |
| `bayesian-regression` | `brojonat/llmsrules` | start simple, upgrade the likelihood |
| `datastar`, `k8s-deployment` | `brojonat/llmsrules` | the dashboard; deployment |

## Architecture

```
feed ──insert batches──▶  db (DuckDB + quack_serve)  ◀──read batch / insert fit── sample (GPU)
                               ▲
                     dashboard polls query('select max(id) ...'), streams SSE to browsers
```

Five processes, one database file, all on one machine (or in one pod):

| Process | Command | Job |
|---|---|---|
| `db` | `{{cookiecutter.project_slug}} db` | Owns `data/belt.duckdb`, creates the schema, serves it over Quack. Checkpoints on SIGINT/SIGTERM/SIGHUP. |
| `feed` | `{{cookiecutter.project_slug}} feed` | Inserts a batch every `--every` seconds: simulated from a drifting truth, or the next chunk of `--from FILE`. |
| `sample` | `{{cookiecutter.project_slug}} sample` | Fits each new batch with the compiled program, writes one summary row per scalar parameter. |
| `plots` | `{{cookiecutter.project_slug}} plots` | Renders the dashboard's figures (ArviZ, on CPU) from the thinned draws the sampler saves. |
| `serve` | `{{cookiecutter.project_slug}} serve` | The dashboard: model, agent thread, metrics, figures. Writes only the user's messages and cached LLM descriptions. |

### Compile once, refit forever (`compile.py`, `samplers.py`)

PyMC's JAX path folds every `pm.Data` into a constant, so new data means a
new XLA compile. `jaxify()` swaps each `pm.Data` for a symbolic input instead,
giving `logdensity(position, data)`. The sampler (`make_chees` or `make_nuts`)
puts BlackJAX warmup, sampling and the transform back to the model's
parameter space inside one `jax.jit`, compiled ahead of time with
`.lower().compile()`. A compiled program called with data of the wrong shape
or dtype raises instead of silently recompiling. The XLA persistent cache
(`.jax_cache/`) lets a restarted sampler skip compilation too.

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
  payload rows first, then one marker row (`batches`, `fits`). Readers only
  look at marker rows.
- Delivery is at-least-once: a batch is done when its `fits` row lands; a
  restarted sampler resumes after the newest.

| Table | Written by | Grain |
|---|---|---|
| `batches` | feed | one per batch: `n`, `coords` (JSON labels) — the marker |
| `obs` | feed | one per observation; columns from `model.OBS_DDL` |
| `truth` | feed | the simulated true value of every named parameter (simulated batches only) |
| `models` | sample | one per compiled model: DOT graph, `str_repr()`, `CONTEXT`, `VIEW` as JSON, `model.py` source, git revision |
| `fits` | sample | one per fit: timing, lag, ESS, R̂, divergences — the marker |
| `params` | sample | one per scalar per fit: `var`, `name` (`beta[Denver, income]`), `coords` JSON, mean/sd/quantiles, ESS, R̂ |
| `model_notes` | serve | the LLM's description of a model, cached |
| `messages` | agent, serve | the agent thread: agent notes, reports and commits; your feedback and approvals |
| `handled` | agent | which of your messages the agent has read (`mise run inbox`) |
| `draws` | sample | thinned draws of some fits (each program's first, then every 30 s), for `plots`; the db keeps the newest 5 |
| `figures` | plots, agent | the carousel's PNGs: newest render per (version, kind), and every figure the agent posted |

`mise run query "select name, q50 from params where var = 'mu' order by fit_id desc, pos limit 8"`
runs SQL on the server. A schema change (including `OBS_DDL`) makes `db`
refuse the old file; `mise run reset` (or `reset:cpu`) starts fresh.

### Labeled dims (`model.py`, `labels.py`)

Every axis is named (`dims`) and labeled (`coords`), and the labels travel
with each batch, so the feeder decides them and the sampler builds the model
from them. A scalar is `beta[Denver, income]` everywhere: in `params`, in
`truth`, in the dashboard. `labels.scalars()` is the one naming function;
the feeder and the sampler must agree on it because the dashboard joins on
names.

### The dashboard (`web.py`, `templates/`, `static/components.js`)

One background task polls the belt every 100 ms with a ~2 ms server-side
query and renders the page regions once for all browsers. Each browser holds
one SSE stream (`GET /stream`) that receives only the regions that changed,
at most 4 times a second. The model region (graph + description) is sent
once per model; the dashboard region on every fit.

- What it plots comes from the model's `VIEW`, recorded on each `models` row:
  a forest of the latest fit, the `track` scalars across fits, and an
  optional rows × columns grid of one 2-D variable. Truth overlays and the
  coverage tile appear only for simulated batches.
- Model graph: `pm.model_to_graphviz` DOT, laid out in the browser by
  Graphviz compiled to WASM (no `dot` binary needed anywhere).
- Model description: the agent's (`mise run describe`) when there is one.
  Otherwise an LLM, if a key is set, gets the DOT, `str_repr()`, coords and
  `model.CONTEXT` and streams two paragraphs into the page. Both are saved in
  `model_notes`, per version.
- Charts are d3 in Datastar Rocket web components (open shadow root, data in
  attributes).
- `/healthz`, `/metrics` (Prometheus text, no client library).

## Benchmarks

`mise run bench` compares the compiled `nuts` and `chees` loops with
`pm.sample(nuts_sampler="numpyro")` (recompiles every call) and PyMC's
default sampler, JSON lines to `logs/bench.jsonl`. `rep 0` is the first fit
after the compile; later reps get fresh same-shape data and must not
recompile.

`bench --from FILE` refits the file's full chunks instead (`--skip K` to start
at chunk K), and
`--params` adds each rep's posterior summary: a bounded check of a model on
real data with no belt running.

## Deploying

One image, one pod: `db`, `feed`, `sample` (with `nvidia.com/gpu: 1`) and
`dashboard` are containers sharing localhost, with a PersistentVolumeClaim
for the belt file and the XLA cache. Quack only serves localhost and its
clients insist on HTTPS for other hosts, so the belt never leaves the pod.

```bash
cp .env.prod.example .env.prod        # QUACK_TOKEN, OPENROUTER_API_KEY
uv lock && git commit -am "lock"      # the image builds with --frozen
mise run k8s-preview                  # render the manifests
mise run deploy                       # build, push, apply; waits for rollout
mise run k8s-logs sample              # db | feed | sample | dashboard
```

The cluster needs a GPU node with the NVIDIA device plugin; the image carries
CUDA as pip wheels. Set the real domain in `k8s/prod/ingress.yaml` first.

## CLI

JSON on stdout, progress on stderr.

```bash
{{cookiecutter.project_slug}} db [--path data/belt.duckdb]
{{cookiecutter.project_slug}} feed [--n 100000] [--dim group=20 ...] [--every 1.0] [--drift 0.02] [--count 0]
{{cookiecutter.project_slug}} feed --from data/x.parquet [--order-by COLUMN] [--n 100000] [--every 1.0] [--count 0]
{{cookiecutter.project_slug}} sample [--sampler chees|nuts] [--chains 256] [--warmup 300] [--draws 50] [--latest] [--refit N]
{{cookiecutter.project_slug}} serve [--host 127.0.0.1] [--port {{cookiecutter.default_port}}] [--reload] [--replace]
{{cookiecutter.project_slug}} note [--kind note|report|commit] [--model ID] TEXT...   # or - for stdin
{{cookiecutter.project_slug}} inbox [--wait SECONDS]
{{cookiecutter.project_slug}} source MODEL_ID|vN
{{cookiecutter.project_slug}} plots [--every 60]
{{cookiecutter.project_slug}} figure PLOT.png --title TEXT
{{cookiecutter.project_slug}} figures [--save DIR]
{{cookiecutter.project_slug}} describe [--model ID] TEXT...                            # or - for stdin
{{cookiecutter.project_slug}} bench [--sampler nuts|chees|pymc|pymc-numpyro|pymc-blackjax] [--reps 3] [--dim NAME=SIZE ...]
{{cookiecutter.project_slug}} bench --from data/x.parquet [--order-by COLUMN] --n 2000 [--skip K] [--params]
```

`--dim NAME=SIZE` sets a simulated dim's size; the names are `model.SIM_DIMS`'s.

Environment: `QUACK_URL`, `QUACK_TOKEN`, `BELT_DB`, `HOST`, `PORT`, `FEEDBACK_FROM`,
`LOG_LEVEL`, `LLM_*` / `OPENROUTER_API_KEY`; feed defaults `BELT_N`,
`BELT_DIMS` (`"group=5 feature=4"`), `FEED_EVERY`, `FEED_FROM`,
`FEED_ORDER_BY`; sample defaults `SAMPLE_CHAINS`, `SAMPLE_WARMUP`,
`SAMPLE_DRAWS`, `SAMPLE_LATEST`, `SAMPLE_REFIT` (see `mise.cpu.toml`).

## GPU notes

- `mise run setup:gpu` installs `jax[cuda13]` (the `gpu` extra); Turing
  (sm_75) and newer are supported. The Docker image always includes it.
- `XLA_PYTHON_CLIENT_PREALLOCATE=false` (in `mise.toml`) keeps JAX from
  grabbing 75% of VRAM up front.
- `Driver/library version mismatch` after a driver upgrade means the kernel
  module is stale: reboot (or `mise run up:cpu` meanwhile).
