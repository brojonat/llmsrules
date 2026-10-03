"""Figures for the dashboard's carousel: ArviZ plots of each model version's latest fit, and the agent's own.

The sampler saves a thinned copy of a fit's draws on the belt (`draws`): the first fit of each
program, then at most every DRAWS_EVERY_S. This process takes the newest saved fit, rebuilds its
model on its batch, samples the prior and the posterior predictive with PyMC (on CPU, no JAX),
and renders a posterior predictive check, prior vs posterior, caterpillars and rank plots as PNG
(`figures`). A new model version is rendered at once; after that, at most every `every` seconds.

Everything goes through the belt, so no directory has to agree between processes or profiles.
The db process prunes (belt.HOUSEKEEPING): it keeps the newest render per (version, kind), every
figure the agent posts (`{{cookiecutter.project_slug}} figure`), and the newest draws.
"""

import io
import json
import logging
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa

from {{cookiecutter.package_name}} import belt, journal
from {{cookiecutter.package_name}} import model as example

log = logging.getLogger(__name__)

KEEP_CHAINS, KEEP_DRAWS = 8, 100  # thinned draws per fit: enough for rank plots and predictive checks
DRAWS_EVERY_S = 30.0  # the sampler saves draws at most this often (and for every new program)
PRIOR_DRAWS = 200
RESERVED_DIMS = {"group", "sample"}  # ArviZ stacks prior vs posterior along "group"
MAX_SCALARS = 12  # per prior/posterior or rank figure: more is unreadable
KIND_ORDER = ("agent", "ppc", "prior_posterior", "forest", "rank")


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
    import matplotlib

    matplotlib.use("Agg")
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
    """Rebuild the fit's model on its batch and render each figure; returns the kinds written.

    A figure that fails (a plot that doesn't suit this model) is logged and skipped.
    """
    import arviz_base as azb
    import pymc as pm

    batch = belt.read(con, f"select coords from batches where id = {fit['batch_id']}").to_pylist()[0]
    coords = json.loads(batch["coords"])
    rows = belt.read(con, f"select * exclude (batch_id) from obs where batch_id = {fit['batch_id']} order by rowid")
    model = example.build(example.from_arrow(rows, coords), coords)
    npz = belt.read(con, f"select npz from draws where fit_id = {fit['id']}")["npz"][0].as_py()
    with np.load(io.BytesIO(npz)) as f:
        draws = dict(f)
    dims = {k: list(v) for k, v in example.DIMS.items() if k in draws}
    tree = azb.from_dict({"posterior": draws}, dims=dims, coords=coords)
    with model:
        prior = pm.sample_prior_predictive(PRIOR_DRAWS, random_seed=0)
        predictive = pm.sample_posterior_predictive(tree, random_seed=0, progressbar=False)
    for name in ("prior", "prior_predictive", "observed_data"):
        if name in prior.children:
            tree[name] = prior[name]
    tree["posterior_predictive"] = predictive["posterior_predictive"]
    tree = _rename_reserved(tree)

    view = {"forest": [], "track": [], "grid": None, **example.VIEW}
    written = []
    for kind, title, plot in _figures(model, tree, view, draws):
        try:
            pc = plot()
            with tempfile.TemporaryDirectory() as tmp:  # PlotCollection.savefig wants a path, not a buffer
                path = Path(tmp) / "figure.png"
                pc.savefig(path, dpi=96, bbox_inches="tight")
                png = path.read_bytes()
            _close()
            post(con, model_id=fit["model_id"], fit_id=fit["id"], author="plots", kind=kind, title=title, png=png)
            written.append(kind)
        except Exception as e:  # noqa: BLE001 - one unsuitable plot shouldn't cost the others
            _close()
            log.warning("v%s %s: %s: %s", version, kind, type(e).__name__, e)
    return written


def _figures(model, tree, view: dict, draws: dict):
    """(kind, title, plot) for each figure, in carousel order."""
    import arviz_plots as azp

    def size(var: str) -> int:
        return int(np.prod(draws[var].shape[2:])) if var in draws else 0

    for rv in model.observed_RVs:
        observed = np.asarray(tree["observed_data"][rv.name])
        if set(np.unique(observed)) <= {0, 1}:
            plot, how = azp.plot_ppc_pava, "calibration"
        elif np.issubdtype(observed.dtype, np.integer):
            plot, how = azp.plot_ppc_rootogram, "rootogram"
        else:
            plot, how = azp.plot_ppc_dist, "densities"
        yield (
            f"ppc:{rv.name}",
            f"Posterior predictive: {rv.name} ({how})",
            lambda plot=plot, rv=rv: plot(tree, var_names=[rv.name], backend="matplotlib"),
        )
    headline = _within(view["forest"] + view["track"], size)
    if headline:
        yield (
            "prior_posterior",
            "Prior vs posterior: " + ", ".join(headline),
            lambda: azp.plot_prior_posterior(tree, var_names=headline, backend="matplotlib"),
        )
    vectors = [v for v in dict.fromkeys([*view["forest"], *view["track"], view["grid"]]) if v and size(v) >= 8]
    for var in vectors[:3]:
        yield (
            f"forest:{var}",
            f"Caterpillar: {var}",
            lambda var=var: azp.plot_forest(tree, var_names=[var], combined=True, backend="matplotlib"),
        )
    if headline:
        yield (
            "rank",
            "Rank plots: " + ", ".join(headline),
            lambda: azp.plot_rank(tree, var_names=headline, backend="matplotlib"),
        )


def _within(names: list[str], size) -> list[str]:
    """The leading variables whose scalars fit in one figure."""
    picked, total = [], 0
    for name in dict.fromkeys(names):
        n = size(name)
        if n and total + n <= MAX_SCALARS:
            picked.append(name)
            total += n
    return picked


def _rename_reserved(tree):
    renames = {d: f"{d}_" for d in tree["posterior"].dims if d in RESERVED_DIMS}
    if not renames:
        return tree
    return tree.map_over_datasets(lambda ds: ds.rename({k: v for k, v in renames.items() if k in ds.dims}))


def _close() -> None:
    import matplotlib.pyplot as plt

    plt.close("all")


def post(
    con: duckdb.DuckDBPyConnection,
    *,
    model_id: int | None,
    fit_id: int | None,
    author: str,
    kind: str,
    title: str,
    png: bytes,
) -> int:
    figure_id = time.time_ns()
    row = {
        "id": [figure_id], "created_at": [datetime.now(UTC)],
        "model_id": pa.array([model_id], pa.int64()), "fit_id": pa.array([fit_id], pa.int64()),
        "author": [author], "kind": [kind], "title": [title], "png": pa.array([png], pa.binary()),
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
        con, "select id, created_at, model_id, fit_id, author, kind, title from figures order by id desc limit 2000"
    ).to_pylist()
    seen, out = set(), []
    for r in rows:
        version = versions.get(r["model_id"])
        key = r["kind"] if r["author"] == "agent" else f"v{version}:{r['kind']}"
        if key in seen:
            continue
        seen.add(key)
        out.append({**r, "version": version, "key": key.replace(":", "-")})
    newest = sorted({f["version"] for f in out if f["version"] is not None}, reverse=True)[:keep_versions]
    out = [f for f in out if f["version"] in newest or f["version"] is None]
    rank = {k: i for i, k in enumerate(KIND_ORDER)}
    out.sort(key=lambda f: (-(f["version"] or 0), rank.get(f["kind"].split(":")[0], 9), -f["id"]))
    return out
