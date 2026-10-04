# Learnings

Hard-won knowledge. Each entry: what happened, why it was surprising, how to
avoid it. Versions: DuckDB 1.5.6, PyMC 6.3, JAX 0.11, BlackJAX 1.7. The
`python-bayes-loop` template ships these too; copy new ones there when you
sync it.

## PyMC to JAX

**PyMC's JAX path bakes `pm.Data` into the program.** `pm.sample(nuts_sampler=
"numpyro")` and `pymc.sampling.jax.get_jaxified_graph` replace every shared
variable with a constant, so new data means a new trace and XLA compile on
every call. For a model that samples in under a second, the compile is most
of the wall clock. `compile.jaxify()` swaps each `pm.Data` for a symbolic
input with `graph_replace` before jaxifying. Dim lengths stay constants: JAX
needs static shapes, so a new batch size is a new program.

**PyMC quietly narrows integer data.** An `int32` array passed to `pm.Data`
comes back as `int16` (and `int8` as `int16`). The AOT-compiled program then
rejects your original arrays ("Argument types differ"). Cast new batches to
the compiled dtypes with `JaxModel.cast()`. Calling the `.compile()`d object
(not the `jax.jit` wrapper) is what turns this into an error instead of a
silent recompile; keep it that way.

**A logp test at the initial point proves nothing.** At PyMC's initial point
every coefficient is 0, so every logit is 0 and a Bernoulli likelihood is the
same whatever `y` is. A "data swap changes nothing" bug passes. Test at a
random point and assert the logp actually moved.

**JAX sorts dict keys, so the draws come back alphabetical.** A dict is a
pytree, and JAX flattens it in sorted key order. `params.pos` follows the
draws, so "model order" is really alphabetical by variable. The dashboard
ordered its forest by `pos` and only looked right because the example's
`["mu", "sigma"]` happens to be alphabetical; a model with
`["mu_a", "alpha"]` came out reversed. Order by `VIEW` explicitly
(`list_position`), then `pos` within a variable. `test_belt` reverses `VIEW`
to keep this honest.

**`model.unobserved_value_vars` includes the transformed values.** For a
`HalfNormal` sigma you get both `sigma_log__` and `sigma`, so every fit
summarized each positive parameter twice, and the unconstrained copy leaked
into the dashboard and `--params`. `jaxify` keeps only the names of free RVs
and Deterministics.

**A constant computed from data in `build` is silently frozen.** With
compile-once, `pm.Normal("mu", y.mean(), 1)` takes the first batch's mean
forever: no error, just a stale prior. The contract test compiles the model
on batch A, feeds it batch B, and compares with a model built on B. Compare
two *JAX* programs, not JAX against PyTensor's `compile_logp`: their float32
results differ by ~1e-5 relative, and at the looser tolerance that needs,
the planted `y.mean()` bug (a 0.04 shift on a logp of ~550) slipped through.
Plant the bug and watch the test fail before trusting a test like this.

**Absolute thresholds in tests break when the problem size changes.** "The
new data moved the logp by more than 1.0" passed at 4x3 and failed at 4x4
(0.94). Assert relative to the comparison tolerance instead.

**`dims` aren't inherited through arithmetic.** `beta = mu + sigma * z` has
no dims unless the `Deterministic` says so; without them it is named
`beta[3, 1]`. A dim with no coords (`obs_id`) is fine: PyMC fills integers.

**Weight rows per variable, not on the summed logp.** To pad a fit's rows
without changing the posterior, `compile._weighted_logp` asks PyMC for each
variable's terms separately (`model.logp(vars=[v], sum=False)`), multiplies
the observed ones (and Potentials) whose first dim is the rows' dim by a
weight vector, and sums. With all-ones weights it equals `model.logp()`
(`test_logp_tracks_new_data_without_rebuild` checks). Gotcha on the way:
`pt.tensor(dtype=pm.floatX, ...)` fails with "Invalid dtype: <function
floatX>"; `pm.floatX` is a function. Pass the string `"floatX"`.

## Samplers

**Vectorized NUTS on CPU is a trap.** vmapping NUTS chains makes one batched
while-loop where every chain waits for the deepest tree, and XLA runs it on
one thread: 4 chains took ~20x one chain. On GPU the batched gradient is
nearly free, so vmap is right there. `make_nuts(vectorized=...)` picks
`lax.map` on CPU.

**BlackJAX ChEES wants one flat vector per chain.** Its adaptation computes
weighted means with `isfinite(x).all(axis=-1)`, which breaks on pytree leaves
with extra dims (a `(groups, features)` leaf). `samplers._flat()` ravels the
position once and unravels inside the logdensity.

**Consumer GPUs and float64.** RTX cards run fp64 at 1/32 to 1/64 of fp32.
The CLI defaults `PYTENSOR_FLAGS=floatX=float32`; PyTensor still emits int64
shape casts that JAX (x64 off) truncates with a warning per cast, which the
CLI filters.

**Many short ChEES chains need enough warmup.** With 64 chains and 200
warmup steps on CPU, max R̂ sat at 1.09 to 1.7. Judge convergence on R̂
across chains, not per-chain ESS, and raise `--warmup` before trusting it.

**On CPU, fit time grows much faster than the rows.** On the example model,
2,048 rows took 12 s and 8,192 rows 188 s with 64 ChEES chains (5 s and 77 s
with 4 NUTS chains), about 15x for 4x the data. Not yet known whether it's
more gradient steps or slower ones. Every fit sees all rows fed so far, so
this sets the chunk size: one row at a time is for a few hundred rows (radon,
919 rows in chunks of 25: 37 fits in a minute), not for big files.

## GPU and process hygiene

**Importing JAX claims the GPU.** `import blackjax` calls `jnp.log` at import
time, which initializes the CUDA backend. Only `sample` and `bench` import
JAX; `cli.py` imports it lazily so `db`, `feed` and `serve` never hold a GPU
context. With `jax[cuda13]` installed and no usable GPU, that import raises;
`cli._require_jax_device()` turns it into one readable line.

**"Driver/library version mismatch" means reboot.** A driver package upgrade
replaces the userspace libraries but the old kernel module stays loaded until
reboot; JAX then sees no GPU. `mise run up:cpu` keeps you working meanwhile.

**Python only runs signal handlers on the main thread, between bytecodes.**
Two ways that bit: the sampler ignored Ctrl-C for the length of an XLA call,
and the db process never woke because the kernel delivered SIGINT to one of
DuckDB's ~170 threads while the main thread sat in an untimed
`Event.wait()`. The sampler runs its loop in a worker thread with the main
thread in a timed `join` (`cli._run_until_signal`; first signal finishes the
fit, second exits), and `belt.serve` waits in 0.5 s slices.

**A watching browser blocks `uvicorn --reload`.** On reload uvicorn waits
for open connections to finish, and the dashboard's SSE stream never does.
With a remote viewer connected, every save left the old worker alive for
minutes: `/healthz` timed out, and `loop down` waited out its 30 s.
`serve` now passes `timeout_graceful_shutdown=1`, and excludes `model.py`
from reloads (the dashboard never imports it, and model edits are the
agent's main loop).

**An orphaned `uvicorn --reload` supervisor keeps the port.** When the
terminal under `mise run up` goes away, the reload supervisor can survive and
hold the socket; the next `dev` dies with "Address already in use" while the
browser keeps talking to stale code. If the app's startup also fails, the
supervisor holds the port with no worker and connections just queue.
`serve --replace` (used by `mise run dev`) stops an old dashboard on the
port, and refuses with the holder's pid if it isn't ours. Never block app
startup on a dependency: the web server connects to the belt lazily.

**mise's `[env]` beats your shell, and `uv` is a mise shim.** `QUACK_URL=...
uv run ...` inside the project silently gets `mise.toml`'s value. To point a
one-off process elsewhere, call `.venv/bin/<cli>` directly or use a mise
profile (`MISE_ENV=cpu`).

**Ctrl-C in a terminal or tmux pane signals the whole pipeline.** `uv run
{{cookiecutter.project_slug}} db 2>&1 | tee logs/db.log` puts tee in the same process group, so
tee died at once and the db's "checkpointed and closed" never reached the
log, while the checkpoint itself ran. `tee -i` ignores SIGINT and records the
shutdown.

**Entries in mise's `[env]` override `_.file = ".env"` if they come after
it.** `PORT=9999` in `.env` lost to `PORT = "{{cookiecutter.default_port}}"` below the `_.file` line,
and so did the "real `QUACK_TOKEN`" the comment told you to put there. Put
`_.file` last.

**tmux resolves a missing window name to some other window.** `loop down`
sent Ctrl-C to, and waited on, `=session:feed` in a session that only ran db;
each missing window cost its full 30 s wait. Check the window exists
(`list-windows -F '#{window_name}'`) before targeting it.

**`pkill -f` matches its own shell.** The pattern is in the shell's command
line too, so the shell gets killed (exit 144). Use a pattern that can't match
itself: `pkill -f '[.]venv/bin/name '`.

## DuckDB over Quack

**One DuckDB file, one writing process.** A second process can't even open
it read-only while the writer holds it. That's why the belt is served over
Quack instead of shared as a file.

**Clients can't see sequences.** `nextval('seq')` from a client fails, and a
remote catalog with a `nextval` column default fails to ATTACH at all
("Catalog does not exist"). Writers generate IDs (`time.time_ns()`).

**ROLLBACK over Quack doesn't undo an insert.** Writes behave as if each
statement commits. Order makes a multi-table write atomic: payload first,
marker row last, readers key off markers.

**Queries on the attached catalog run on the client.** `select count(*)
from remote.obs` over 1M rows took ~860 ms because the table was streamed to
the client; the same SQL inside `query('...')` ran on the server in ~2 ms.
Every read goes through `belt.read()`. `query()` resolves names in the
*current* catalog, hence `USE remote`, which a `.cursor()` doesn't inherit.

**Fetch Arrow, not tuples.** A 100k-row batch: 13 ms via
`.to_arrow_table()`, 575 ms via `.fetchall()`.

**Quack is localhost-only.** `quack_serve` refuses other hostnames unless
`allow_other_hostname = true`, and clients use HTTPS for any host that isn't
localhost, with no plain-HTTP option in 1.5.6. `quack+http:host` is not a
scheme: ATTACH silently creates a *local file* with that name. Keep every
belt process on one machine.

**`create table if not exists` keeps an old table as is.** After a schema
change the old file fails on the first insert with a column error far from
the cause. `belt._check_schema` compares column lists at `db` startup and
tells you to reset.

**Inserts are bulk, and fine.** 100k rows over Quack: ~100 to 160 ms with a
`float[]` column, ~19 ms as one blob. Bulk Arrow inserts, not row-by-row,
are what keep this fast.

**A DELETE from a Quack client streams the table first.** Pruning old PNG
renders with `delete from remote.figures where id in (...)` from the plots
process hung: like any query on the attached catalog, it pulls the table to
the client, and that table is full of blobs. Housekeeping runs in the db
process instead (`belt.HOUSEKEEPING`, every `BELT_HOUSEKEEP_S`), locally, on
its own cursor: 15 ms.

**Inserting into DuckDB is a free schema check.** `feed.load` inserts a
file's rows into a scratch copy of the obs table, which casts and validates
before anything touches the belt: missing columns fail with DuckDB's
"Referenced column not found", extra columns are ignored (only `OBS_DDL`'s
are selected), and a CSV's `"[0.1, 0.2]"` strings become a `float[]`.

**Match DuckDB type names exactly, not by prefix.** `duckdb_columns().data_type`
spells a list column `FLOAT[]`, so `startswith("FLOAT")` let the example's
feature vector in as a number, and a histogram query (the since-removed Data
panel) failed with "Unimplemented type for cast (FLOAT[] -> DOUBLE)". Exclude
anything ending in `]` when you pick numeric columns.

## Dashboard

**Send static regions once.** The stream keeps what each browser already has
and sends only changed regions, so the model graph goes out once per model
while the dashboard repaints on every fit, throttled to 4 per second.

**No graphviz binary.** `pm.model_to_graphviz(model).source` needs only the
pure-Python `graphviz` package; `@hpcc-js/wasm-graphviz` lays it out in the
browser (~800 KB, imported only when the graph is on the page).

**The dashboard is read-only on purpose.** It once took feedback and
approvals from the browser, fit painted selections, and asked its own LLM
(OpenRouter) for model descriptions. All of it duplicated the agent's
harness: two channels split the conversation, the agent had to poll an inbox
(`inbox --wait 540`) to hear a browser, the "any" default let anyone on the
network steer an agent with a shell, and the second LLM described models
worse than the agent that built them. The user steers in the agent's chat;
the agent writes to the dashboard with `note`, `status`, `describe` and
`figure`. Keep new features on that side of the line: if the user would ask
the agent to do it, it's a CLI command, not a button.

**One fit has no line to draw.** A run fed all at once has a single fit, and
the track panels (a band and a line through the fits) drew nothing at all.
Draw each fit as a dot, and a lone fit's interval as a bar.

**A shared y-scale hides the small parameters.** The track panels share one
scale, so `sigma_a` (0.08 to 0.15) read as flat next to `b_floor` (−1.4 to
−0.6). A note written from the chart said sigma_a "stays wide longest" and
the others "settle within 200 houses"; the numbers said otherwise. Read
`params` (`mise run query`) before narrating how a parameter moved.

**The dashboard holds its templates from startup.** `poll()` calls
`get_template` once, so a template edit doesn't show until the server
restarts. `mise run dev` restarts on any change under `src/`; a server
started without `--reload` keeps serving the old markup.

## Figures (d3 in the browser)

**Pick the posterior predictive check by outcome.** A density of a 0/1
outcome is a meaningless two-spike plot. Calibration for binary, a rootogram
for counts, densities otherwise (`plots._ppc`).

**Send each figure's reduced numbers, not the draws.** The posterior
predictive is one value per draw per row: millions of numbers. `plots.py`
reduces each figure to what it draws (bins, a KDE grid, rank histograms):
a few KB, and a version renders in about a second where ArviZ's matplotlib
PNGs took several. The region carries only `<figure-chart src=...>`; the
data comes from `/figures/ID.json`, which caches forever because ids never
change.

**An SVG drawn with CSS variables doesn't survive export.** Serialized on its
own, `stroke="var(--series-1)"` has nothing to resolve against and draws
black or nothing. `saveFigure` copies each element's computed
fill/stroke/font onto a clone before painting it on a canvas, and draws the
legend inside the SVG so the PNG keeps it.

**Rank plots need explaining.** People read the traces at a glance, but the
rank plot (each chain's histogram of its draws' ranks among all chains) was
the figure nobody understood. Every diagnostic now carries a "How to read
this" chip (`plots.HOW_TO_READ`).

## Agents fitting new data

**Run the skill cold before trusting it.** A fresh agent following only the
`new-model` skill on the radon data built a correct model in ~5 minutes and
still hit eight snags we hadn't seen: the dashboard ordering bug above,
`2>/dev/null` in the skill hiding bench's only error message, `BELT_DIMS` in
`mise.cpu.toml` tied to the example's dim names, `FEED_FROM` in `.env`
silently redirecting `bench`, a stale README. After changing the skill or
the contract, trial it again on a dataset with a different shape (outcome
type, groups, size).

**Files are often sorted by group.** The radon CSV is sorted by county, so
300-row chunks in file order each saw about a third of the 85 counties.
Check groups per chunk in the replay order (the skill has the SQL), and
order by time, or by a hash, in `prepare.sql`.

**Non-centered isn't always the safe default.** The bike-share trial's
hour × day-type profile had 10 to 30 hourly counts per cell. Non-centered,
the hierarchy sat on a ridge (R̂ 1.04 to 1.06, ~4 ESS/s); centered was 5 to 8x
cheaper per fit. Pick by how much data each group has, and flip it when only
the hierarchy parameters mix badly.

**A time-ordered stream makes intercepts and slopes fight.** Covariates
standardized over the whole file still have a batch mean far from 0 in a
winter batch, so the intercept at `temp_z = 0` trades off with the slope.
Passing the batch's covariate means in as `pm.Data` and centering on them
inside the model took the trial from R̂ 1.02 to 1.001 and ESS 140 to 1600+.
This is legal under compile-once (it's data, not a baked constant).

**`rows`, `days`, `months`, `first` and `name` are keywords in DuckDB SQL.** As
aliases (`count(*) rows`, `'a[' || c || ']' name`) they're parse errors;
always write `as`, and prefer `n_rows`, `first_id`, `label`.

**`pm.ZeroSumNormal` is `-inf` in PyMC's float32 logp.** Its sum-to-zero
check fails on rounding. The JAX path skips the check, so the loop sampled
happily; only the logp-agreement test (`tests/test_compile.py`) noticed.
`mise run check-model` now runs that test too. Center offsets by hand.

**A symbolic batch length breaks PyMC's ordinal and categorical
likelihoods.** `jaxify` used to give each `pm.Data` input an unknown shape.
`OrderedLogistic` with a group-indexed predictor then builds an `arange`
over the rows, which JAX can only trace with constant bounds ("JAX requires
the arguments of `jax.numpy.arange` to be constants"); a toy model with a
plain linear predictor didn't trigger it. Inputs now keep their static
shapes; the program is compiled per shape anyway.

**A NaN gradient freezes every chain silently.** A hand-written ordered
logit used ±1e4 as stand-in cutpoints inside a `where`. PyTensor's logp was
fine, but `jax.grad` differentiates both branches, `exp(1e4)` is inf, and
every slope's gradient came back NaN. The only symptom was the recovery
test's R̂ = inf, ESS ≈ 2. `check-model` now asserts a finite gradient at a
random point and names the variables.

**The loop's R̂ is noisy before it's wrong.** In the bank trial, ChEES with
64 chains × 50 draws on a ~35-parameter model gave R̂ 1.04 to 1.12, and the
agent rewrote a sound model twice chasing it. More warmup did nothing; 200
draws fixed it, and NUTS in `bench` was clean all along. Raise draws and
check with NUTS before changing the model.

**Generic ML skills are the wrong lens for this.** `tabular-eda` (leakage,
mutual information, one-hot encoding, plots) cost the trial agent time and
missed what matters for a pooled Bayesian model: rows per group, row order,
and what the first rows fed cover. It was dropped; that checklist is in `new-model`.

**A loop that fits batch by batch makes agents invent a stream.** Given a
static file and a template built around arriving batches, every case run
manufactured arrival: radon fed 20 weekly snapshots of the whole survey with
an `arrived` mask in a summed `pm.Potential`, telco and retail built
overlapping windows. The batches were fake, and only the last fit answered
the question. Now `feed` moves a cursor through the file and every fit sees
all rows fed so far: "fit it all" is one batch, "watch it arrive" is chunks.
The masked Potential also breaks row padding: its weights only reach terms
whose first dim is the rows', and a sum over rows has no dims (check-model's
padding test fails, as it should). A mask column for "not in yet" is a sign
the model is working around the loop.

**Feed waits for each fit.** A feeder that sends on a timer outruns or
starves the sampler: the old CPU profile skipped to the newest batch
(`SAMPLE_LATEST`) and tuned `FEED_EVERY` to the fit time. Waiting for each
batch's `fits` row before sending the next makes "a fit per chunk" exact and
needs no tuning.

## Skills and tooling

**`npx skills add` installs into `.agents/skills/` and symlinks into
`.claude/skills/`** (and every other agent it detects). A project's own
skill should use the same layout so Codex, Cursor and friends see it too.
Gitignore the installed ones and keep `skills-lock.json`; commit only your
own.

**Decision Hub's `dhub install` is global-only.** It unpacks into
`~/.dhub/skills` and symlinks into `~/.claude/skills`, `~/.codex/skills` and
so on, with no project-local option or lockfile. The hub's pymc-labs skills
auto-sync from `github.com/pymc-labs/python-analytics-skills`, so `npx skills
add pymc-labs/python-analytics-skills -s <skill>` gets the same content per
project. The older `pymc-labs/agent-skills` repo (Feb 2026) targets PyMC 5;
the hub's targets PyMC 6 / ArviZ 1, which is what this project runs.

**Keeping a template in step with the project it came from.**
`llmsrules/project-templates/sync-template.py` turns a project's changed
files back into template form, and fails unless the template then renders
back to the project exactly (the workbench's exact command is in its
TODO.md). Three things that bit while writing it:
- Cookiecutter turns a symlink into an empty directory, so
  `.claude/skills/new-model` is made by `hooks/post_gen_project.py`.
- Values are replaced as whole words only: `skills-lock.json` had a hash
  containing the default port's digits, which a plain replace templated.
- A literal that contains a value (the template's own name,
  `python-bayes-loop`, contains the slug) needs `--keep`.
Name things so values are distinct: a title-case `project_name` next to a
lowercase slug lets the title and the slug map back unambiguously.

**CUDA wheels are an extra, not a dependency.** `jax[cuda13]` pulled ~3.5
GB of NVIDIA wheels into every project, GPU or not, and filled a 16 GB tmpfs
during a trial. It's the `gpu` extra now: `mise run setup` is CPU-only,
`setup:gpu` adds CUDA. A plain `uv run` does an
inexact sync and leaves the extra installed; only `uv sync` without
`--extra gpu` removes it.

**A template inside a repo inherits that repo's `.gitignore`.** llmsrules
ignores `.agents/` (its own installed skills), which also matched the
template's `.agents/skills/new-model`: the round trip, the validator and a
local render all passed, but the skill was never committed, so a fresh clone
would have generated projects with no skill. Anchor such rules to the root
(`/.agents/`), and check a template from a fresh clone, not the working tree.

**A copied project needs `mise trust`.** mise refuses an untrusted
`mise.toml` in a new directory (a scratch copy, a fresh clone), and the error
can surface from an unrelated command like `uv sync` via mise's shims.

**`uv` here is a mise shim, and mise's environment wins.** A script that
exported `QUACK_URL` and `HOST` and then ran `uv run {{cookiecutter.project_slug}} ...` got
mise.toml's `[env]` and `.env` instead: the throwaway belt landed on the
default Quack port and the dashboard on 0.0.0.0. Calling `.venv/bin/{{cookiecutter.project_slug}}` directly honored the exports, including
`HOST=127.0.0.1`, which then left the dashboard unreachable from the user's
machine. For a side loop, call the venv's binary and pass `--host`/`--port`
explicitly.

**`pkill -f PATTERN` matches the shell that runs it.** A command line that
contains the pattern (because it also restarts the process) kills itself
before the restart. Kill by the pid holding the port
(`ss -ltnpH "sport = :PORT"`) instead.

**Playwright's Python package wants its own Chromium build.** `uv run --with
playwright` failed until pointed at the system browser:
`p.chromium.launch(executable_path="/usr/bin/chromium")`.

**Check an uncommitted template edit before syncing over it.** llmsrules had
an uncommitted 500-line diff to the template's `SKILL.md`; it was an
editor's format-on-save reflowing markdown (wrapped lines, padded tables),
not content. Comparing with whitespace and table padding squeezed out
(`tr -s ' \n|-'` on both sides) showed it was safe to replace.
