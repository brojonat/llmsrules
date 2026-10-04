"""Fire the belt: for each new batch, fit every row fed so far in its run, write the summary.

A fit's rows are padded to a power-of-two capacity with weight-0 copies
(compile.pad), and one long-lived process holds the compiled programs, keyed by
(capacity, coords): feeding a file one row at a time compiles once per doubling.

Delivery is at-least-once: a batch counts as done when its `fits` row lands, and
a restart resumes after the newest one. A (re)started sampler fits the newest
batch again first, so after a model edit the new model shows on the data fed so far.
"""

import json
import logging
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import jax
import numpy as np
import pyarrow as pa
import pymc as pm

from {{cookiecutter.package_name}} import belt, plots
from {{cookiecutter.package_name}} import model as example
from {{cookiecutter.package_name}}.compile import JaxModel, capacity, jaxify, pad
from {{cookiecutter.package_name}}.samplers import SAMPLERS
from {{cookiecutter.package_name}}.summary import summarize

log = logging.getLogger(__name__)


def run(
    con: duckdb.DuckDBPyConnection,
    stop: threading.Event,
    *,
    sampler: str,
    chains: int,
    warmup: int,
    draws: int,
    poll: float,
    seed: int,
) -> None:
    device = str(jax.devices()[0])
    programs: dict[tuple[int, str], tuple[JaxModel, jax.stages.Compiled, int]] = {}
    key = jax.random.key(seed)
    # `sampler` is one of a fixed set of names, safe to inline.
    last = belt.read(con, f"select coalesce(max(batch_id), 0) m from fits where sampler = '{sampler}'")["m"][0].as_py()
    fitted = last  # batches up to here were fit before: refitting them has no meaningful lag
    newest = belt.read(con, "select coalesce(max(id), 0) m from batches")["m"][0].as_py()
    if 0 < newest <= last:  # nothing new: fit the newest batch again (ids are unique, so newest - 1 is just before it)
        last = newest - 1
    log.info("%s on %s, resuming after batch %d", sampler, device, last)
    draws_saved = 0.0

    def fit(b: dict) -> dict | None:
        """Fit every row fed so far in the batch's run; the fits row, or None if the db went away."""
        nonlocal key, draws_saved
        coords_json = belt.coords(con, b["id"])
        coords = json.loads(coords_json)
        rows = belt.fed(con, b["id"])
        cap = capacity(rows.num_rows)
        padded, weights = pad(rows, cap)
        data = example.from_arrow(padded, coords)

        # The compiled program depends on the data's shape and the model's coords.
        shape = (cap, coords_json)
        compile_s = None
        if shape not in programs:
            dims = ", ".join(f"{d}={len(v)}" for d, v in coords.items())
            log.info("compiling for %d rows (fitting %d), %s", cap, rows.num_rows, dims)
            t0 = time.perf_counter()
            model = example.build(data, coords)
            jm = jaxify(model)
            if jm.row_dim is None:
                raise SystemExit(
                    "model.py: no observed variable has dims; see tests/test_model.py (mise run check-model)"
                )
            build = SAMPLERS[sampler]
            run_fn = build(
                jm, num_chains=chains, num_warmup=warmup, num_draws=draws, vectorized=jax.default_backend() != "cpu"
            )
            compiled = run_fn.lower(key, jm.data).compile()
            model_id = time.time_ns()
            belt.write(con, "models", pa.table({
                "id": [model_id], "created_at": [datetime.now(UTC)], "n": [cap], "coords": [coords_json],
                "dot": [pm.model_to_graphviz(model).source],  # rendered in the browser; no graphviz binary needed
                "spec": [model.str_repr()], "context": [example.CONTEXT], "view": [json.dumps(view(jm))],
                **{k: [v] for k, v in provenance().items()},
            }))  # fmt: skip
            programs[shape] = (jm, compiled, model_id)
            compile_s = time.perf_counter() - t0
        jm, compiled, model_id = programs[shape]

        key, k = jax.random.split(key)
        t0 = time.perf_counter()
        result = jax.block_until_ready(compiled(k, jm.cast(data, weights)))
        fit_s = time.perf_counter() - t0

        fit_id = time.time_ns()
        t0 = time.perf_counter()
        params = summarize(fit_id, result.draws, jm)
        truth = run_truth(con, b["run_id"])
        params = params.append_column(
            "truth", pa.array([truth.get(n) for n in params["name"].to_pylist()], pa.float32())
        )
        if compile_s is not None or time.monotonic() - draws_saved > plots.DRAWS_EVERY_S:
            plots.save_draws(con, fit_id, jax.device_get(result.draws), keep=set(example.DIMS))  # for the figures
            draws_saved = time.monotonic()
        summarize_s = time.perf_counter() - t0

        now = datetime.now(UTC)
        row = {
            "id": fit_id,
            "batch_id": b["id"],
            "model_id": model_id,
            "created_at": now,
            "sampler": sampler,
            "device": device,
            "chains": chains,
            "draws": draws,
            "n": rows.num_rows,
            "fit_s": fit_s,
            "summarize_s": summarize_s,
            "lag_s": None if b["id"] <= fitted else (now - b["created_at"]).total_seconds(),
            "grad_evals": int(result.grad_evals),
            "divergences": int(result.divergences.sum()),
            "min_ess": float(np.min(params["ess"])),
            "max_rhat": float(np.max(params["rhat"])),
            "compile_s": compile_s,
        }
        try:
            belt.write(con, "params", params)
            belt.write(con, "fits", pa.table({k: [v] for k, v in row.items()}, schema=FITS))  # marker last
        except duckdb.Error:
            if not stop.is_set():
                raise
            # `mise run up` stops db and sampler together. The batch has no fits
            # row, so the next start picks it up again; stray params rows are
            # never read without their marker.
            log.info("db gone during shutdown; dropping the fit for batch %d", b["id"])
            return None
        print(json.dumps(row, default=str), flush=True)
        return row

    while not stop.is_set():
        batch = belt.read(con, f"select * from batches where id > {last} order by id limit 1").to_pylist()
        if not batch:
            stop.wait(poll)
            continue
        b = batch[0]
        if fit(b) is None:
            break
        last = b["id"]


# Explicit, so a null compile_s or lag_s still has a type.
FITS = pa.schema([
    ("id", pa.int64()), ("batch_id", pa.int64()), ("model_id", pa.int64()), ("created_at", pa.timestamp("us", "UTC")),
    ("sampler", pa.string()), ("device", pa.string()), ("chains", pa.int32()), ("draws", pa.int32()),
    ("n", pa.int32()), ("fit_s", pa.float64()), ("summarize_s", pa.float64()), ("lag_s", pa.float64()),
    ("grad_evals", pa.int64()), ("divergences", pa.int32()), ("min_ess", pa.float64()), ("max_rhat", pa.float64()),
    ("compile_s", pa.float64()),
])  # fmt: skip


def run_truth(con: duckdb.DuckDBPyConnection, run_id: int) -> dict[str, float]:
    """A simulated file's true parameters, by scalar name; {} for real data."""
    rows = belt.read(con, f"select name, value from truth where run_id = {int(run_id)}").to_pylist()
    return {r["name"]: r["value"] for r in rows}


def view(jm: JaxModel) -> dict:
    """model.VIEW with the grid's row and column dims spelled out, for the dashboard."""
    v = {"forest": [], "track": [], "grid": None, **example.VIEW}
    if v["grid"]:
        rows, cols = jm.dims[v["grid"]]
        v["grid"] = {"var": v["grid"], "rows": rows, "cols": cols}
    return v


def provenance() -> dict[str, str | None]:
    """model.py as this process imported it, and the git revision it came from.

    The source is read from disk at compile time: the module was imported at
    start, and a sampler restarted after an edit imports the new file.
    """
    path = Path(example.__file__)
    git = ["git", "-C", str(path.parent)]
    try:
        rev = subprocess.run([*git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        dirty = subprocess.run(
            [*git, "status", "--porcelain", "--", path.name], capture_output=True, text=True, check=False
        )
        git_rev = rev.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.CalledProcessError):  # not a git checkout (yet), or no commits
        git_rev = None
    return {"source": path.read_text(), "git_rev": git_rev}
