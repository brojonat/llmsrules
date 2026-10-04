"""Figures for the dashboard's carousel: diagnostics of each model version's latest fit, and the agent's own.

The sampler saves a thinned copy of a fit's draws on the belt (`draws`): the first fit of each
program, then at most every DRAWS_EVERY_S. This process takes the newest saved fit, rebuilds its
model on the rows it was fit to (a sample of PLOT_ROWS of them), samples the prior and the posterior
predictive with PyMC (on CPU, no JAX), and reduces each figure to the numbers it draws: a
posterior predictive check (calibration for a 0/1 outcome, a rootogram for counts, densities
otherwise), traces, prior vs posterior, and rank plots. Those go on the belt as JSON (`figures`);
the browser draws them with d3 (static/components.js, `figure-chart`). A new model version is
rendered at once; after that, at most every `every` seconds.

Everything goes through the belt, so no directory has to agree between processes or profiles.
The db process prunes (belt.HOUSEKEEPING): it keeps the newest render per (version, kind), every
figure the agent posts (`{{cookiecutter.project_slug}} figure`, a PNG), and the newest draws.
"""

import io
import json
import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa

from {{cookiecutter.package_name}} import belt, journal
from {{cookiecutter.package_name}} import model as example
from {{cookiecutter.package_name}}.labels import scalars

log = logging.getLogger(__name__)

KEEP_CHAINS, KEEP_DRAWS = 8, 100  # thinned draws per fit: enough for traces, rank plots and predictive checks
DRAWS_EVERY_S = 30.0  # the sampler saves draws at most this often (and for every new program)
PRIOR_DRAWS = 200
PLOT_ROWS = 20_000  # rows the predictive checks are drawn for: plenty for a calibration curve or rootogram
PREDICTIVE_DRAWS = 100  # predictive draws behind a density check's band
GRID = 96  # points per density curve
MAX_SCALARS = 12  # per trace, prior/posterior or rank figure: more is unreadable
MAX_COUNTS = 60  # values a rootogram shows
RANK_BINS = 20
KIND_ORDER = ("agent", "ppc", "trace", "prior_posterior", "rank")

# The carousel's "How to read this", by the figure's chart.
HOW_TO_READ = {
    "calibration": "Rows are grouped by the probability the model predicts for them (x). Each dot is the share of "
    "the group that actually came out 1; the blue bar is where the model expects that share to land 90% of the "
    "time. Dots inside their bars, near the dashed diagonal, mean the predicted probabilities can be taken at face "
    "value. Dots above (or below) the bars mean the model predicts too low (or too high) there.",
    "rootogram": "How often each value of the outcome occurs. Bars are the observed counts; dots are what the model "
    "expects, with lines for its 90% range. The y axis is a square-root scale so rare values stay visible. A bar "
    "top well off its line means the model gets that value's frequency wrong: too few zeros or a tail that's too "
    "thin, say.",
    "density": "The black line is the distribution of the observed outcome; the blue band is where the "
    "distributions of datasets simulated from the model fall 90% of the time. Where the black line leaves the band, "
    "the model gets the data's shape wrong: its skew, its tails, a second peak.",
    "trace": "One row per parameter. Right: each chain's draws in order. Healthy chains overlap into one fuzzy band "
    "(a caterpillar) with no trends, steps or stuck stretches. Left: each chain's own density; they should lie on "
    "top of each other. A chain off on its own hasn't found the same posterior as the others.",
    "prior_posterior": "Dashed: what the model believed about the parameter before seeing the data (the prior). "
    "Blue: after (the posterior). A posterior much narrower than its prior means the data pinned the parameter "
    "down. One that looks like its prior means the data said little about it, and the prior is doing the work.",
    "rank": "Every draw from every chain is ranked against all of them; each row is one chain's histogram of its "
    "draws' ranks. If the chains explored the same posterior, every row is flat at the dashed line, give or take "
    "noise. A chain piled up at one end sat higher or lower than the others; one bulging in the middle explored "
    "too narrow a range. It asks the same question as the traces, more sensitively.",
}


def save_draws(con: duckdb.DuckDBPyConnection, fit_id: int, draws: dict, keep: set[str]) -> None:
    """A thinned copy of the fit's draws for the plots process."""
    thinned = {}
    for name, x in draws.items():
        if name in keep:
            x = np.asarray(x)[:KEEP_CHAINS]
            thinned[name] = x[:, :: max(1, x.shape[1] // KEEP_DRAWS)][:, :KEEP_DRAWS]
    buf = io.BytesIO()
    np.savez(buf, **thinned)
    row = {"fit_id": [fit_id], "created_at": [datetime.now(UTC)], "npz": pa.array([buf.getvalue()], pa.binary())}
    belt.write(con, "draws", pa.table(row))


def run(con: duckdb.DuckDBPyConnection, stop: threading.Event, *, every: float, poll: float) -> None:
    """Render the newest saved fit whenever its version is new, or `every` seconds have passed."""
    rendered: dict[int, tuple[int, float]] = {}  # version -> (fit id, when)
    while not stop.is_set():
        fits = belt.read(
            con,
            "select f.id, f.batch_id, f.model_id from fits f join draws d on d.fit_id = f.id order by f.id desc limit 1",
        ).to_pylist()
        if fits:
            fit = fits[0]
            version = journal.versions(con).get(fit["model_id"])
            done = rendered.get(version)
            if done is None or (done[0] != fit["id"] and time.monotonic() - done[1] >= every):
                t0 = time.perf_counter()
                kinds = render(con, fit, version)
                rendered[version] = (fit["id"], time.monotonic())
                log.info(
                    "v%s fit %d: %s in %.1f s",
                    version,
                    fit["id"],
                    ", ".join(kinds) or "nothing",
                    time.perf_counter() - t0,
                )
        stop.wait(poll)


def render(con: duckdb.DuckDBPyConnection, fit: dict, version: int) -> list[str]:
    """Rebuild the fit's model on its rows and write each figure's data; returns the kinds written.

    A figure that fails (one that doesn't suit this model) is logged and skipped.
    """
    import arviz_base as azb
    import pymc as pm

    coords = json.loads(belt.coords(con, fit["batch_id"]))
    rows = belt.fed(con, fit["batch_id"])
    if rows.num_rows > PLOT_ROWS:
        rows = rows.take(np.sort(np.random.default_rng(0).choice(rows.num_rows, PLOT_ROWS, replace=False)))
    model = example.build(example.from_arrow(rows, coords), coords)
    npz = belt.read(con, f"select npz from draws where fit_id = {fit['id']}")["npz"][0].as_py()
    with np.load(io.BytesIO(npz)) as f:
        draws = dict(f)
    dims = {k: list(v) for k, v in example.DIMS.items() if k in draws}
    tree = azb.from_dict({"posterior": draws}, dims=dims, coords=coords)
    with model:
        prior = pm.sample_prior_predictive(PRIOR_DRAWS, random_seed=0)
        predictive = pm.sample_posterior_predictive(tree, random_seed=0, progressbar=False)
    observed = {rv.name: np.asarray(prior["observed_data"][rv.name]) for rv in model.observed_RVs}
    predicted = {name: np.asarray(predictive["posterior_predictive"][name]) for name in observed}
    priors = {var: np.asarray(prior["prior"][var])[0] for var in draws if var in prior["prior"]}

    view = {"forest": [], "track": [], "grid": None, **example.VIEW}
    written = []
    for kind, title, compute in _figures(observed, predicted, draws, priors, coords, view):
        try:
            data = compute()
            post(con, model_id=fit["model_id"], fit_id=fit["id"], author="plots", kind=kind, title=title, data=data)
            written.append(kind)
        except Exception as e:  # noqa: BLE001 - one unsuitable figure shouldn't cost the others
            log.warning("v%s %s: %s: %s", version, kind, type(e).__name__, e)
    return written


def _figures(observed: dict, predicted: dict, draws: dict, priors: dict, coords: dict, view: dict):
    """(kind, title, compute -> the figure's JSON-able data) for each figure, in carousel order."""
    for name, obs in observed.items():
        how = (
            "calibration"
            if np.isin(np.unique(obs), [0, 1]).all()
            else "rootogram"
            if np.issubdtype(obs.dtype, np.integer)
            else "densities"
        )
        yield (
            f"ppc:{name}",
            f"Posterior predictive: {name} ({how})",
            lambda name=name, obs=obs: _ppc(obs, predicted[name]),
        )

    def size(var: str) -> int:
        return int(np.prod(draws[var].shape[2:])) if var in draws else 0

    headline = _within(view["forest"] + view["track"], size)
    if not headline:
        return
    named = [pair for var in headline for pair in _scalars(var, draws[var], coords)]
    title = ", ".join(headline)
    yield "trace", f"Traces: {title}", lambda: {"chart": "trace", "panels": [_trace(n, d) for n, d in named]}
    if all(var in priors for var in headline):
        prior = dict(pair for var in headline for pair in _scalars(var, priors[var][None], coords))
        yield "prior_posterior", f"Prior vs posterior: {title}", lambda: {
            "chart": "prior_posterior", "panels": [_prior_posterior(n, prior[n], d) for n, d in named],
        }  # fmt: skip
    yield "rank", f"Rank plots: {title}", lambda: {
        "chart": "rank", "expected": draws[headline[0]].shape[1] / RANK_BINS, "panels": [_rank(n, d) for n, d in named],
    }  # fmt: skip


def _scalars(var: str, x: np.ndarray, coords: dict) -> list[tuple[str, np.ndarray]]:
    """[(scalar name, its (chains, draws) samples)] for a var's (chains, draws, *shape) samples, named like params rows."""
    flat = x.reshape(*x.shape[:2], -1)
    return [(name, flat[:, :, i]) for i, (name, _) in enumerate(scalars(var, example.DIMS[var], coords))]


def _ppc(obs: np.ndarray, predicted: np.ndarray) -> dict:
    """The predictive check's numbers, by the outcome's type."""
    obs = obs.ravel()
    pp = predicted.reshape(-1, obs.size)
    if np.isin(np.unique(obs), [0, 1]).all():
        # Reliability: rows binned by predicted probability; observed share vs the predictive 90% band.
        p = pp.mean(0)
        edges = np.unique(np.quantile(p, np.linspace(0, 1, 11)))
        idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, max(0, len(edges) - 2))
        bins = []
        for b in np.unique(idx):
            m = idx == b
            lo, hi = np.quantile(pp[:, m].mean(1), [0.05, 0.95])
            bins.append(_r([p[m].mean(), obs[m].mean(), lo, hi]) + [int(m.sum())])
        return {"chart": "calibration", "bins": bins}
    if np.issubdtype(obs.dtype, np.integer):
        # Rootogram: how often each value occurs, observed vs expected (mean and 90% band over draws).
        kmin = int(obs.min())
        kmax = int(min(np.quantile(np.concatenate([obs, pp.ravel()]), 0.995), kmin + MAX_COUNTS - 1))
        k = np.arange(kmin, kmax + 1)
        count = lambda d: np.bincount(d[(d >= kmin) & (d <= kmax)].astype(np.int64) - kmin, minlength=k.size)
        per = np.stack([count(d) for d in pp])
        lo, hi = np.quantile(per, [0.05, 0.95], axis=0)
        return {
            "chart": "rootogram",
            "counts": [[int(a), int(b), *_r([c, d, e])] for a, b, c, d, e in zip(k, count(obs), per.mean(0), lo, hi)],
        }
    # Densities: the observed KDE against the 90% band of predictive draws' KDEs.
    grid = _grid(obs, pp.ravel())
    some = pp[np.random.default_rng(0).choice(len(pp), min(PREDICTIVE_DRAWS, len(pp)), replace=False)]
    dens = np.stack([_kde(d, grid) for d in some])
    lo, mid, hi = np.quantile(dens, [0.05, 0.5, 0.95], axis=0)
    return {
        "chart": "density",
        "grid": _r(grid),
        "observed": _r(_kde(obs, grid)),
        "lo": _r(lo),
        "mid": _r(mid),
        "hi": _r(hi),
    }


def _trace(name: str, d: np.ndarray) -> dict:
    """One scalar: each chain's draws (the trace) and each chain's density on a shared grid."""
    grid = _grid(d.ravel())
    return {"name": name, "grid": _r(grid), "kde": [_r(_kde(c, grid)) for c in d], "draws": [_r(c) for c in d]}


def _prior_posterior(name: str, prior: np.ndarray, d: np.ndarray) -> dict:
    grid = _grid(prior, d.ravel())
    return {"name": name, "grid": _r(grid), "prior": _r(_kde(prior, grid)), "posterior": _r(_kde(d.ravel(), grid))}


def _rank(name: str, d: np.ndarray) -> dict:
    """One scalar: each chain's histogram of its draws' ranks among all chains (flat when the chains agree)."""
    ranks = np.argsort(np.argsort(d.ravel(), kind="stable"), kind="stable").reshape(d.shape)
    edges = np.linspace(0, d.size, RANK_BINS + 1)
    return {"name": name, "counts": [np.histogram(r, edges)[0].tolist() for r in ranks]}


def _grid(*samples: np.ndarray) -> np.ndarray:
    """GRID points over the samples' central 99%, plus a margin."""
    x = np.concatenate([np.asarray(s, dtype=np.float64).ravel() for s in samples])
    x = x[np.isfinite(x)]
    lo, hi = np.quantile(x, [0.005, 0.995])
    pad = (hi - lo) * 0.05 or abs(lo) * 0.05 or 1.0
    return np.linspace(lo - pad, hi + pad, GRID)


def _kde(x: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Gaussian kernel density of samples x on the grid, Silverman's bandwidth."""
    x = np.asarray(x, dtype=np.float64).ravel()
    x = x[np.isfinite(x)]
    iqr = np.subtract(*np.quantile(x, [0.75, 0.25]))
    spread = min(x.std(), iqr / 1.34) if iqr > 0 else x.std()
    bw = 0.9 * spread * x.size**-0.2 or (grid[1] - grid[0])
    z = (grid[:, None] - x[None, :]) / bw
    return np.exp(-0.5 * z * z).sum(1) / (x.size * bw * np.sqrt(2 * np.pi))


def _r(values) -> list[float]:
    """Four significant digits: the browser draws them, nobody reads them all."""
    return [float(f"{v:.4g}") for v in np.asarray(values, dtype=np.float64).ravel()]


def _within(names: list[str], size) -> list[str]:
    """The leading variables whose scalars fit in one figure."""
    picked, total = [], 0
    for name in dict.fromkeys(names):
        n = size(name)
        if n and total + n <= MAX_SCALARS:
            picked.append(name)
            total += n
    return picked


def post(
    con: duckdb.DuckDBPyConnection,
    *,
    model_id: int | None,
    fit_id: int | None,
    author: str,
    kind: str,
    title: str,
    png: bytes | None = None,
    data: dict | None = None,
) -> int:
    """One figure: a PNG (the agent's), or the data the browser draws it from."""
    figure_id = time.time_ns()
    row = {
        "id": [figure_id], "created_at": [datetime.now(UTC)],
        "model_id": pa.array([model_id], pa.int64()), "fit_id": pa.array([fit_id], pa.int64()),
        "author": [author], "kind": [kind], "title": [title], "png": pa.array([png], pa.binary()),
        "data": pa.array([None if data is None else json.dumps(data)], pa.string()),
    }  # fmt: skip
    belt.write(con, "figures", pa.table(row))
    return figure_id


def post_file(con: duckdb.DuckDBPyConnection, source: Path, title: str) -> dict:
    """The agent's own figure, added to the carousel under the current model version."""
    if source.suffix.lower() != ".png":
        raise SystemExit(f"{source}: the carousel shows PNG files")
    model_id = journal.latest_model(con)
    figure_id = time.time_ns()  # the kind is unique per agent figure, so none replaces another
    post(
        con,
        model_id=model_id,
        fit_id=None,
        author="agent",
        kind=f"agent:{figure_id}",
        title=title,
        png=source.read_bytes(),
    )
    return {"model_id": model_id, "version": journal.versions(con).get(model_id), "kind": f"agent:{figure_id}"}


def carousel(con: duckdb.DuckDBPyConnection, versions: dict[int, int], keep_versions: int = 5) -> list[dict]:
    """What the carousel shows: newest render per (version, kind), newest versions first, agent figures first within one."""
    rows = belt.read(
        con,
        "select id, created_at, model_id, fit_id, author, kind, title, png is not null as is_png,"
        " json_extract_string(data, '$.chart') chart from figures"
        " order by id desc limit 2000",
    ).to_pylist()
    seen, out = set(), []
    for r in rows:
        version = versions.get(r["model_id"])
        key = r["kind"] if r["author"] == "agent" else f"v{version}:{r['kind']}"
        if key in seen:
            continue
        seen.add(key)
        out.append({**r, "version": version, "key": key.replace(":", "-"), "how": HOW_TO_READ.get(r["chart"])})
    newest = sorted({f["version"] for f in out if f["version"] is not None}, reverse=True)[:keep_versions]
    out = [f for f in out if f["version"] in newest or f["version"] is None]
    rank = {k: i for i, k in enumerate(KIND_ORDER)}
    out.sort(key=lambda f: (-(f["version"] or 0), rank.get(f["kind"].split(":")[0], 9), -f["id"]))
    return out
