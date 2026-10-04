---
name: new-model
description: Fit this project's compile-once Bayesian loop to a new dataset. Profile the data, prepare it with SQL, write the PyMC model and its simulator in src/{{cookiecutter.package_name}}/model.py, pass the model contract (mise run check-model), and check the fit on the real data. Use when the user hands over a dataset (CSV, Parquet, JSON) and a problem description, or asks to replace, change, or extend the model.
---

# A new model for a new dataset

**Input:** a data file and a problem description.
**Done when:**
1. `mise run check-model` passes.
2. `{{cookiecutter.project_slug}} bench --from <file>` fits the real data with clean diagnostics.
3. The loop is running in tmux (`mise run loop:cpu` or `loop`) with your model on the dashboard.
4. You've posted your report to the dashboard (`mise run note --kind report`) and given it in your session. "Done" is the user's call.

**The user watches the dashboard and talks to you here, in your session.** The dashboard is read-only: it shows your model, its description, what you're doing, the fits and the figures, and keeps the record. Your notes there are the journal of the work, next to each model version's diagnostics. When you act on something the user said in the session, say so in the note ("You asked for per-county intervals; ..."): the thread only has your side.

| Command | What |
| --- | --- |
| `mise run note "..."` | post to the thread (`--kind report` for your report, `--kind commit` after a commit; `-` reads stdin) |
| `mise run feed` | send data to the model and wait for the fit (see "Feeding data" below) |
| `mise run status "..."` | what you're doing right now, in a few words ("refitting with a Student-t", "done: over to you"). Shown beside the thread until the next one; post one whenever you start something that takes a while. |
| `mise run describe -` | the "What this model says" text for the current version (stdin): two short paragraphs, the data and what the model assumes, then what the headline parameters mean. Post one for every new version. |
| `mise run source <id or vN>` | the `model.py` a model version was compiled from |
| `mise run figures --save <dir>` | the dashboard's figures (posterior predictive, traces, prior vs posterior, rank plots, per version) as the JSON data they're drawn from; look at the drawn charts on the dashboard itself (a browser, e.g. Playwright) |
| `mise run figure <png> --title "..."` | add a figure of your own to the dashboard's carousel |

These need the belt running (`mise run loop:cpu`). Use the `mise run` forms: they carry this project's `QUACK_URL` and token, which a bare `uv run {{cookiecutter.project_slug}} ...` outside mise doesn't.

**Resuming a project** (a new session, or a continued one): `mise run loop:cpu` (a no-op if it's running), then read the thread before anything else:
```bash
mise run query "select created_at, kind, model_id, text from messages where kind != 'status' order by id"
```
Then ask the user what's next if they haven't said.

Read `README.md` for the architecture if you haven't. The short version: `feed` moves a cursor through your data file, and each batch it sends is fit together with every row fed before it, by one XLA program compiled per `(padded row count, coords)` and reused.

## Feeding data

The user decides how data goes in; you translate. The default is all of it at once.

| The user says | You run | Fits |
| --- | --- | --- |
| "fit the data" / nothing about it | `mise run feed` | one, on every row |
| "feed the first half" | `mise run feed --rows 50%` | one, on rows 1 to n/2 |
| "now the rest" | `mise run feed` | one, on every row |
| "the next 500 rows" | `mise run feed --rows 500` | one |
| "chunks of 100" | `mise run feed --chunk 100` | one per chunk, each on everything so far |
| "one at a time, so I can watch" | `mise run feed --chunk 1` (with `--rows N` for the first N only) | one per row |
| "start over" | `mise run feed --restart` (plus any of the above) | the cursor goes back to row 0 |

- **Each fit sees every row fed so far** in the run, never just the newest batch. The dashboard plots the posterior against rows fed, so the intervals narrowing as data goes in is the picture.
- `feed` blocks until each batch's fit lands and prints one JSON line per batch (`rows`, `of`, `fit_s`, `max_rhat`, ...). A long chunked feed can run in the background; one row at a time on a big file is slow, because each fit runs on all rows so far. Estimate it from one fit's `fit_s` and tell the user before starting ("one row at a time is ~900 fits, about 25 minutes; chunks of 25 take about a minute").
- Rows go in file order, or `FEED_ORDER_BY`'s. Feeding incrementally only means something if that order does: by time if there is one (the survey as it came in), else shuffled in `prepare.sql` (`order by hash(id)`), so the first rows aren't one group.
- After a model edit, `mise run loop:cpu restart sample` refits the rows fed so far with the new model; no need to feed again.
- A changed data file (re-run `prepare.sql`, new `FEED_ORDER_BY`) starts a new run from row 0 by itself.

For the statistics, lean on the installed skills. The PyMC Labs ones come from Decision Hub (hub.decision.ai/orgs/pymc-labs) and match this project's PyMC 6 / ArviZ 1 stack:
- `bayesian-regression`: start simple, then upgrade the likelihood.
- `pymc-modeling`: likelihoods, hierarchies, dims, and testing a model with simulated data. Its `references/` has one file per topic.
- `prior-elicitation`: priors in meaningful units, and prior predictive checks.
- `arviz-diagnostics`: reading R-hat, ESS and divergences.
- `pytensor-workflows`: shape and dtype errors inside `build`.

**Which advice wins:**
- On **loop mechanics** (data through `pm.Data`, fixed shapes, dims, what gets compiled), the rules below win.
- On **statistics** (likelihood, priors, parameterization), the PyMC skills' references win. The rules below only set defaults for starting.
- Where those skills reach for `pm.sample`, nutpie, PreliZ or ArviZ `idata`, that's tooling this project doesn't run. Use `bench --from` and the belt's `params` table instead.

## What you edit

| File | What |
| --- | --- |
| `prepare.sql` (new, project root) | raw file → `data/<name>.parquet`, the rows the model sees |
| `src/{{cookiecutter.package_name}}/model.py` | the whole model contract; its docstring lists every name |
| `mise.cpu.toml` | `BELT_DIMS`: the simulator's sizes for the CPU profile, as `NAME=SIZE` with your `SIM_DIMS` names (the example's `group=5 feature=4` breaks any other model). `SIM_ROWS`: how many rows `mise run simulate` writes. |
| `.env` | `FEED_FROM=data/<name>.parquet`, and `FEED_ORDER_BY=<column>` if rows have a time order. Only `feed` reads these; `bench` uses `--from` explicitly. `.env` may hold other settings: add lines, don't rewrite it. |

Don't edit `compile.py`, `samplers.py`, `worker.py`, `summary.py`, `belt.py` or `web.py`. If the model seems to need it, stop and tell the user what the contract is missing.

## Rules the loop imposes (read before choosing a model)

1. **Continuous parameters only.** The samplers are NUTS and ChEES, so gradients are required. Marginalize discrete latents (`pm.Mixture`, `pymc_extras.marginalize`).
2. **Every input is `pm.Data`, observed included.** The keys `from_arrow` returns must be exactly the model's `pm.Data` names. A raw array is frozen into the compiled program, and every later fit would silently use the first fit's values.
3. **No constants computed from data inside `build`.** `y.mean()` as a prior location, or `X.std()` as a scale, is computed once at compile time and goes stale for every later fit (which sees more rows).
   - Do standardization and category lists over the whole file, in `prepare.sql`.
   - **A quantity that depends on the rows fed must come in as `pm.Data`.** Compute it in `from_arrow` and return it as another array. The common case is time-ordered data fed in order, whose covariate means drift: the first winter months have `temp_z ≈ -1.2`, so intercepts and slopes trade off and sampling slows. Pass the fit's covariate means (`xbar`), center on them inside the model, and map back to a fixed reference with a Deterministic. `from_arrow` gets padding rows (copies of the first row) too, so compute such means over the real rows only, or accept the small bias.
4. **Shapes are fixed per program.** The rows fed so far, padded up to a power of two, and `coords` (the labels) form the compile key. `coords_for` runs once over the whole file, so every fit shares one set of labels. A group with no rows fed yet is fine: its parameters just stay at the prior.
5. **Every free variable and Deterministic has `dims`, and `DIMS` lists exactly those.** Each dim must have labels in `coords`. Don't add per-observation Deterministics (dims `obs_id`). The sampler summarizes every scalar, every fit, so a length-n Deterministic means n rows per fit in `params`.
6. **float32.** Standardize continuous predictors (in `prepare.sql`) and keep the outcome on a sane scale. Avoid priors that put mass at 1e6. Leave a 0/1 indicator as 0/1: then the intercept reads as the level for the 0 category.
7. **Each fit sees every row fed so far.** Fits don't carry a posterior forward; each starts from the prior and sees all the rows. Successive fits, as data is fed, are what the dashboard tracks.
8. **Centered or non-centered depends on how much data each group has.**
   - Thinly measured groups (a few rows each, as in the example): non-centered, `mu + sigma * z`.
   - Groups pinned by many informative rows (dozens of counts each): centered, `pm.Normal("level", mu, sigma)`.
   - If R̂ or ESS are bad only on `mu`/`sigma`/`z`, flip it. See `pymc-modeling` → `references/hierarchical.md`.
9. **`pm.Data` names can't equal dim names.** `pm.Data("day", ..., dims="obs_id")` next to a `day` dim fails with "conflicts with an existing dimension name". Use `day_idx`, as the example uses `g` for `group`.
10. **Avoid `pm.ZeroSumNormal`; center offsets by hand** (`sigma * (z - z.mean())`). Under float32, PyMC's own logp of a `ZeroSumNormal` is `-inf`: its sum-to-zero check fails on rounding. The JAX path drops the check, so the loop samples happily while `mise run check-model` fails its logp-agreement test.
11. **One likelihood term per obs row, with the rows' dim first.** The sampler pads a fit's rows to a power of two with copies of the first row and gives the copies zero weight in every observed variable (and `pm.Potential`) whose first dim is the rows' dim (`dims=("obs_id", ...)`). So `from_arrow` mustn't aggregate rows (counts per group, a mean), and the observed variable needs `dims`.

## Workflow

### 0. Open the dashboard first
As soon as the project is set up (and `.env` has its `PORT`), start the database and the dashboard, so the user can watch you from the first minute:
```bash
mise run loop:cpu up db dev     # or `mise run loop up db dev` on a GPU
```
Tell the user the address: `http://localhost:<PORT>`, or this machine's name or address from elsewhere; it listens on all interfaces. Then journal as you go, before any model exists:
- `mise run note` your restatement of the problem (step 1);
- what profiling found (step 2);
- the model you plan and why (step 3).

Notes before the first fit belong to no model version; that's fine. Step 8's `mise run loop:cpu` adds feed and sample to the same session.

### 1. Restate the problem
Write one paragraph covering:
- the outcome;
- the unit of observation (one row = one what?);
- the grouping structure;
- the predictors;
- the question the posterior must answer.

This paragraph becomes `CONTEXT`, which is shown with the model graph and sent to the LLM that explains the model. If the description leaves the outcome or the question ambiguous, ask the user before going further.

**Say what one row means in time.** Is it one unit followed until an event or until now (a cohort, with censoring)? One period at risk (a cross-section of who was exposed)? Or an aggregate over a window? Time-to-event and rate questions hinge on it, and briefs are often vague about it. State your reading in the restatement, and ask on the dashboard when the data could support more than one.

### 2. Profile the data
Run DuckDB through the project's Python. In SQL, always write `as` before an alias, and avoid `rows`, `days`, `months`, `first` and `name` (and plural time units generally) as aliases: they're keywords, and an implicit alias like `'x' || y name` fails inside `query()`.
```bash
uv run python -c "import duckdb; print(duckdb.sql(\"summarize from 'path/to/raw.csv'\"))"
```
What matters for this loop:
- **The outcome:** its type and range, which pick the likelihood. Missing values get dropped in `prepare.sql`.
- **Groups:** how many, and rows per group (min / median / max, and how many have 3 or fewer). Small groups are why you pool.
- **Predictors:** continuous or 0/1, missingness, and scale. Plan the standardization.
- **Row order:** is there a time column? Is the file sorted by group?
- **Feed order:** if the user may feed incrementally, the first rows should be a fair sample (or genuinely the earliest, for time-ordered data). A file sorted by group gives the first half only half the groups. Check what the first chunk of a given size covers:
  ```sql
  select chunk, count(*) n_rows, count(distinct grp) n_groups
  from (select grp, (row_number() over (order by sold_at) - 1) // 200 as chunk from 'data/x.parquet')
  group by chunk order by chunk
  ```
  If no order mixes the groups well, order by a hash (`order by hash(id)`) in `prepare.sql`.

  The `--order-by` column doesn't need to be in `OBS_DDL`: `feed`/`bench` order by the file's column, then keep only the obs columns.

### 3. Choose the simplest model that answers the question

| Outcome | Likelihood |
| --- | --- |
| binary | `Bernoulli(logit_p=...)` |
| ordered categories (ratings, scores) | `OrderedLogistic(eta=..., cutpoints=..., compute_p=False)`; cutpoints with `transform=ordered`. `compute_p=False`, or PyMC adds a per-row `obs_probs` Deterministic (rule 5). |
| successes of k trials | `Binomial(k, logit_p=...)` (k is `pm.Data`) |
| count | `Poisson(log mu)`, or `NegativeBinomial` if overdispersed |
| continuous | `Normal`, or `StudentT` if outliers |
| positive, skewed | `LogNormal` or `Gamma` |

Groups (stores, cities, patients) get partial pooling: varying intercepts first, varying slopes only if the question needs them.

**Build up; don't start at the top.** The first model is the lowest rung that answers the question:
1. The likelihood above, plus the predictors the question names, with weakly informative priors.
2. Partial pooling across the groups the question is about.
3. Only after the loop shows a specific problem, upgrade one thing per iteration:
   - overdispersion → NegativeBinomial;
   - outliers → StudentT;
   - a drifting effect → its own term;
   - a curved response → a quadratic or spline.

The PyMC skills describe horseshoes, GPs, mixtures and BART. Treat those as later rungs that need a reason you can show the user (a diagnostic, a residual pattern, a parameter that moves as rows are fed), not as a starting point.

See `pymc-modeling` → `references/likelihoods.md` and `references/hierarchical.md`. Set priors in the outcome's units with `prior-elicitation`.

### 4. Prepare the data
`prepare.sql` turns the raw file into exactly the rows the model reads, as one or more DuckDB statements:
```sql
copy (
  select store as grp,
         (price - avg(price) over ()) / stddev(price) over () as price_z,
         units,
         sold_at
  from read_csv('data/raw/sales.csv')
  where units is not null
) to 'data/sales.parquet' (format parquet);
```
Run it with `mise run prepare`. `data/` is gitignored, so `prepare.sql` is how the data step stays reproducible.

### 5. Rewrite `model.py`
Keep the module's shape and replace each name:

- **`OBS_DDL`:** `create table if not exists obs(batch_id bigint, <the parquet's columns>)`. `feed`/`bench --from` load only these columns, cast to these types.
- **`CONTEXT`:** from step 1.
- **`coords_for(rows)`:** labels for every dim, from the whole file (e.g. sorted distinct group labels, predictor names). Labels are strings. For an integer-coded dim (hour of day), zero-pad (`f"{h:02d}"`) so they sort numerically, and in `from_arrow` map values to positions with `pc.index_in` on the same strings. A dim with fixed meaning (`day = ["non-working", "working"]`, the predictor names) can be hard-coded.
- **`from_arrow(rows, coords)`:** turns rows into numpy arrays, one per `pm.Data`. Group labels become indices via `coords`. Raise if a label isn't in `coords`.
- **`build(data, coords)`:** the PyMC model.
- **`DIMS`:** every free variable and Deterministic, mapped to its dims. A scalar gets `()`, in both `DIMS` and `dims=` (or no `dims`).
- **`VIEW`:** what the dashboard plots, in the order listed:
  - `forest`: the few headline variables;
  - `track`: the ones worth watching across fits;
  - `grid`: an optional 2-D variable, or `None`.

  Leave out non-centered offsets (`z`); summaries still include them. The forest shares one x-axis and the track panels one y-scale, so don't mix probabilities and log-odds in one list. Keep the forest to headline scalars and short vectors: an 85-county vector there fills the page, and a 2-D variable belongs in `grid`.
- **The simulator** (`SIM_DIMS`, `Truth`, `draw_truth`, `simulate`): the same generative story in numpy, returning rows shaped like the obs table.
  - `SIM_DIMS` holds only dims whose size may vary (groups). It may be empty (`{}`, with `BELT_DIMS = ""`) when every dim has a fixed meaning. The tests shrink every entry to 3 or 4 to stay fast. Fixed-meaning dims (`day`, the predictor list) stay out of it and are hard-coded in `draw_truth`.
  - Draw parameters at plausible values, e.g. near a quick fit of the real data, or a prior draw that looks sane.
  - Draw covariates that resemble the data.
  - `Truth.rows()` names scalars with `labels.scalars` so they line up with the posterior. Use `np.asarray(x).reshape(-1)` so scalars and arrays go through the same path.
  - `Truth` may also hold covariate settings that aren't parameters (e.g. the share of first-floor rows); `rows()` lists only the parameters.
  - Uniform group assignment is fine for a rudimentary model.
  - If a parameter's meaning depends on the rows fed (an intercept at the fit's `xbar`), report its expected value under the simulator's covariate distribution, or leave it out of `rows()`: variables without a truth just show no marker.
  - The simulator drives the tests' parameter-recovery check, the benchmark and `mise run simulate` (a dataset with known truth, for showing the loop recovering it). Writing it is also the cheapest way to find out whether you understand your own model.
  - See `pymc-modeling` → `references/model-testing.md`.
- **Dims:** see `pymc-modeling` → `references/model-data-dimensions.md`. For shape errors in `build`, use `pytensor-workflows` → `references/shapes.md`.

**Check the priors before fitting.** PreliZ isn't installed; this prints what the priors imply for the outcome, to compare with the data's own quantiles from step 2:
```bash
JAX_PLATFORMS=cpu uv run python -c "
import numpy as np, pymc as pm
from {{cookiecutter.package_name}} import feed, model
rows = feed.load('data/<name>.parquet', None)[:2000]
coords = model.coords_for(rows)
m = model.build(model.from_arrow(rows, coords), coords)
with m: pp = pm.sample_prior_predictive(200, random_seed=0)
for rv in m.observed_RVs: print(rv.name, np.quantile(pp['prior_predictive'][rv.name].values, [0.05, 0.5, 0.95]))
"
```
A model whose likelihood is a `pm.Potential` has no `observed_RVs`, so this prints nothing: simulate the outcome in numpy from prior draws instead. Want: the right order of magnitude, not a tight match. Counts in the millions, or rates pinned at 0, mean a prior is off in the outcome's units (`prior-elicitation`).

### 6. Pass the contract
```bash
mise run check-model
```

| Failure | Meaning |
| --- | --- |
| `test_dims_cover_every_variable` | a variable without `dims`, or `DIMS` out of sync with `build` |
| `test_every_input_is_pm_data` | rule 2 |
| `test_program_depends_on_data_only_through_pm_data` | rule 3 |
| `test_obs_rows_survive_the_obs_table` | `OBS_DDL` can't hold what `simulate` produces: a missing column, a count over 127 in a `tinyint`, a fraction in an integer column |
| `test_replayed_file_builds_the_model` | `coords_for` misses a dim, or `from_arrow` can't read what `feed.load` returns |
| `test_gradient_is_finite` | `jax.grad` of the logp is inf/NaN somewhere, usually an untaken `where` branch that overflows (`exp(1e4)`): JAX differentiates both branches |
| `test_logp_tracks_new_data_without_rebuild` (test_compile) | PyMC's and the JAX logp disagree; `-inf` on PyMC's side usually means a constraint check failing in float32 (rule 10) |
| `test_padding_rows_carry_no_weight` | rule 11: the copies the sampler pads with changed the logp, so the likelihood doesn't run along the rows |
| `test_view_names_real_variables` | `VIEW` names a variable missing from `DIMS`, or `grid` isn't 2-D |
| `test_recovers_simulated_truth` | R̂ = inf with ESS ≈ 2: the chains never moved (see the gradient test). Otherwise R̂ ≥ 1.05, or 90% intervals cover < 75% of the truth: the model, the priors and the simulator disagree. Look for a sign error, a mismatched link, or a prior that's far too tight. |

Then run `mise run test` (the end-to-end tests run the belt with your model) and `mise run lint`.

### 7. Fit the real data
A bounded check with no belt, on CPU, on the whole file (`--n` its row count):
```bash
JAX_PLATFORMS=cpu uv run {{cookiecutter.project_slug}} bench --from data/<name>.parquet --n <row count> \
  --chains 4 --warmup 500 --draws 500 --reps 1 --params
```
- **Smaller pieces:** a smaller `--n` fits the file's first chunks of that size (`--reps 3` the first three; `--skip K` starts at chunk K). Use it to see how the model behaves on the first rows the user might feed, or when the whole file is slow.
- **Output:** JSON on stdout: one line per fit with `seconds`, `divergences`, `max_rhat` and `min_ess`, and with `--params`, one line per scalar per rep (`"phase": "param"`, with `rep`). Progress and errors go to stderr. Don't discard stderr: "fewer than --n" lands there.
- **Finding the bad parameter:** sort the param lines by `ess` (or `rhat`) to see which variables are the problem, e.g. `... --params | jq -s 'map(select(.phase=="param")) | sort_by(.ess) | .[:5]'`.
- **Reps:** the file's first full chunks of n rows, in `--order-by` order. A short tail is skipped, so `--n <row count>` gives exactly one rep.

**Want:** zero divergences (a few at most), max R̂ < 1.01, min ESS > 400.

**Then read the posterior against the question:** signs, magnitudes, and which effects are distinguishable from zero. A posterior that's just the prior means too few rows, or a predictor that carries nothing.

Divergences usually mean a centered hierarchy, a scale prior that's too wide, or an unstandardized predictor. See `pymc-modeling` → `references/troubleshooting.md` and `arviz-diagnostics`.

### 8. Run the loop, and iterate in it
The belt runs in tmux, one window per service, via `scripts/loop.sh`:

| Command | What |
| --- | --- |
| `mise run loop:cpu` | start the session (`<dir>-cpu`): db, sample, plots, dev; any already running (step 0's db and dev) are left alone. `up NAME...` starts just those. Use `mise run loop` on a GPU. |
| `mise run loop:cpu status` | one line per service: `running`, or `exited <code>` |
| `mise run loop:cpu restart sample` | restart one service. A restarted `sample` first refits the rows fed so far with the current model. |
| `mise run loop:cpu down` | Ctrl-C each service (the sampler finishes its fit, db checkpoints), then end the session |

Each service still tees `logs/<name>.log`, so read logs there rather than by attaching. The user can `tmux attach -t <session>` to watch.

**Setup:**
1. Put `FEED_FROM` (and `FEED_ORDER_BY`) in `.env`, and `BELT_DIMS` in `mise.cpu.toml`.
2. Put every column a later version might want in `OBS_DDL` from the start (a covariate you plan to try next): then adding it to the model needs only `restart sample`, not a reset.
3. A changed `OBS_DDL` means the old belt file is refused, so reset it (`mise run reset:cpu`) with the loop down.
4. `mise run loop:cpu`, then feed the data the way the user asked ("Feeding data" above; all of it by default). The dashboard is at `http://localhost:{{cookiecutter.default_port}}`.

**The iteration cycle.** One change per restart, each with a reason the user can see:
1. `mise run note "Changing X because Y; expect Z to move"`, and `mise run status` what you're doing.
2. Make the change and restart.
3. When the new fit lands, `mise run describe -` the new version (if the model changed), and `mise run note` what happened.
   - **Look at the figures before you call it.** The `plots` service computes them for each version's latest fit within a few seconds of its first fit, and the dashboard draws them in its Figures carousel. Open the dashboard in a browser and read the posterior predictive check (does the data sit inside what the model predicts?) and the traces (do the chains overlap into one band?). Without a browser, `mise run figures --save /tmp/figs` writes the numbers behind each one.
   - **Show, don't only tell.** When you compute something the user should see (observed vs expected by group, a residual pattern, a backtest), plot it with matplotlib and `mise run figure plot.png --title "..."`. It joins the carousel under the current version.

| You changed | Then |
| --- | --- |
| `build`, priors, `VIEW`, `CONTEXT` | `mise run check-model`, then `mise run loop:cpu restart sample`. The sampler recompiles and re-fits the rows fed so far, and the dashboard switches to the new model (it shows only fits whose model spec matches the newest). |
| `coords_for`, a new dim, or `from_arrow`'s inputs (same obs columns) | `mise run check-model`, `mise run prepare` if needed, `restart sample`, then `mise run feed --restart` (plus the user's chunking): a run keeps the labels it started with, so new labels need a new run. The old program may fit once against the new run first; harmless. |
| `OBS_DDL` (the obs columns) | `loop:cpu down`, `reset:cpu`, `loop:cpu`. **A reset erases the belt, the thread with the user included**: post your summary again afterwards, and avoid this by loading every column you might want up front (setup step 2). |
| want the whole evolution again under the current model | `mise run feed --restart` with the same chunking. Just the latest picture needs only `restart sample`. |

Then check the fit:
```bash
mise run query "select model_id, max_rhat, divergences, fit_s, lag_s from fits order by id desc limit 5"
mise run query "select name, q05, q50, q95, rhat from params where fit_id = (select max(id) from fits) order by pos"
```

**What to expect from the loop's sampler:** ChEES with many chains (`mise.cpu.toml`: 64 chains × 200 draws) lands around max R̂ 1.02 on the example, a little looser than `bench`'s NUTS. The dashboard flags R̂ above 1.05. Split-R̂ is noisy on short chains, and more so the more parameters you have, so check the sampler before the model:
1. Raise `SAMPLE_DRAWS` in `mise.cpu.toml` (200 → 400) and restart `sample`. Warmup rarely helps here.
2. Fit the same block with NUTS: `bench --from ... --skip <block> --reps 1`. If NUTS is clean (R̂ ≤ 1.01), the model is fine and the loop's sampler settings are the problem.

Rewriting a sound model to chase the loop's R̂ costs whole iterations.

`serve` logs `dashboard on http://localhost:<PORT>` to `logs/serve.log` when it starts; after that it's quiet. `feed` prints a line per fit and exits when its rows are in; once the whole file is fed it says so (`--restart` feeds it again). After `restart sample`, `logs/sample.log` can show the old run for a moment; the belt is the reliable signal (`select count(*) from models`).

`mise run stop` is the hammer: it kills this checkout's {{cookiecutter.project_slug}} processes, whatever started them. A second checkout on the same machine needs its own `PORT` and `QUACK_URL` (e.g. `quack:localhost:9611`) in `.env`.

On a GPU, `mise run loop`, then size `--chains/--warmup/--draws` with `mise run bench` (see `TODO.md`).

### 9. Report, then hand over
Post the report to the dashboard (`mise run note --kind report -`, from stdin) and give it in your session too:
- the model in a few lines of math or words;
- what each headline parameter means in the problem's terms;
- the diagnostics;
- the first reading of the posterior;
- what's knowingly left out (e.g. no time trend, slopes not pooled).

Suggest the next upgrade, but don't build it unasked.

Then `mise run status "done: over to you"`, leave the loop running so the user can look, and end your turn. What the user says next is your next task: run it through the iteration cycle, then report again. If they say they're done, stop the loop (`mise run loop:cpu down`).

### 10. Commit an approved model
Commit only when the user tells you to. They'll name a version from the dashboard ("commit v3"); its newest `model_id` is in `select id from models` (or `mise run source v3` prints its source).
1. If `src/<package>/model.py` differs from `mise run source vN`, the user approved an earlier version: restore it (`mise run source vN > src/<package>/model.py`) and run `mise run check-model`.
2. If the project isn't a git repository yet: `git init`.
3. `git add -A` (`.gitignore` keeps out data, logs and `.env`), then commit:
   - subject: `Model vN: <what it is, in a few words>`;
   - body: why it looks the way it does, from your notes.
4. `git tag model-vN`.
5. `mise run loop:cpu restart sample`. The model's caption on the dashboard shows the git revision it was compiled from, and this recompiles from the commit, so it reads `git <hash>` instead of `+dirty` or "not committed".
6. `mise run note --kind commit "Committed vN as <short hash> (tag model-vN)"`.
