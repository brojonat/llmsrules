"""Fire the belt: take each new batch, fit it on the GPU, write the summary.

One long-lived process holds the compiled programs, keyed by data shape, so
only a batch with a new n or new coords pays a compile. Delivery is
at-least-once: a batch counts as done when its `fits` row lands, and a restart
resumes after the newest one. `refit` re-fits the newest batches on start, so
a sampler restarted after a model edit shows the new model on data already seen.
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
from {{cookiecutter.package_name}}.compile import JaxModel, jaxify
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
    latest: bool,
    poll: float,
    seed: int,
    refit: int = 0,
) -> None:
    device = str(jax.devices()[0])
    programs: dict[tuple[int, str], tuple[JaxModel, jax.stages.Compiled, int]] = {}
    key = jax.random.key(seed)
    # `sampler` is one of a fixed set of names, safe to inline.
    last = belt.read(con, f"select coalesce(max(batch_id), 0) m from fits where sampler = '{sampler}'")["m"][0].as_py()
    fitted = last  # batches up to here were fit before: refitting them has no meaningful lag
    if refit:
        newest = f"select id from batches order by id desc limit {refit}"
        last = min(last, belt.read(con, f"select coalesce(min(id), 1) - 1 m from ({newest})")["m"][0].as_py())
    log.info("%s on %s, resuming after batch %d", sampler, device, last)
    draws_saved = 0.0

    while not stop.is_set():
        order = "desc" if latest else "asc"  # latest: skip a backlog instead of working through it
        batch = belt.read(con, f"select * from batches where id > {last} order by id {order} limit 1").to_pylist()
        if not batch:
            stop.wait(poll)
            continue
        b = batch[0]
        coords = json.loads(b["coords"])
        rows = belt.read(con, f"select * exclude (batch_id) from obs where batch_id = {b['id']} order by rowid")
        data = example.from_arrow(rows, coords)

        # The compiled program depends on the data's shape and the model's coords.
        shape = (b["n"], b["coords"])
        compile_s = None
        if shape not in programs:
            log.info("compiling for n=%d, %s", b["n"], ", ".join(f"{d}={len(v)}" for d, v in coords.items()))
            t0 = time.perf_counter()
            model = example.build(data, coords)
            jm = jaxify(model)
            build = SAMPLERS[sampler]
            run_fn = build(
                jm, num_chains=chains, num_warmup=warmup, num_draws=draws, vectorized=jax.default_backend() != "cpu"
            )
            compiled = run_fn.lower(key, jm.data).compile()
            model_id = time.time_ns()
            belt.write(con, "models", pa.table({
                "id": [model_id], "created_at": [datetime.now(UTC)], "n": [b["n"]], "coords": [b["coords"]],
                "dot": [pm.model_to_graphviz(model).source],  # rendered in the browser; no graphviz binary needed
                "spec": [model.str_repr()], "context": [example.CONTEXT], "view": [json.dumps(view(jm))],
                **{k: [v] for k, v in provenance().items()},
            }))  # fmt: skip
            programs[shape] = (jm, compiled, model_id)
            compile_s = time.perf_counter() - t0
        jm, compiled, model_id = programs[shape]

        key, k = jax.random.split(key)
        t0 = time.perf_counter()
        fit = jax.block_until_ready(compiled(k, jm.cast(data)))
        fit_s = time.perf_counter() - t0

        fit_id = time.time_ns()
        t0 = time.perf_counter()
        params = summarize(fit_id, fit.draws, jm)
        if compile_s is not None or time.monotonic() - draws_saved > plots.DRAWS_EVERY_S:
            plots.save_draws(con, fit_id, jax.device_get(fit.draws), keep=set(example.DIMS))  # for the figures
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
            "n": b["n"],
            "fit_s": fit_s,
            "summarize_s": summarize_s,
            "lag_s": None if b["id"] <= fitted else (now - b["created_at"]).total_seconds(),
            "grad_evals": int(fit.grad_evals),
            "divergences": int(fit.divergences.sum()),
            "min_ess": float(np.min(params["ess"])),
            "max_rhat": float(np.max(params["rhat"])),
            "compile_s": compile_s,
        }
        try:
            belt.write(con, "params", params)
            belt.write(con, "fits", pa.table({k: [v] for k, v in row.items()}))  # marker last
        except duckdb.Error:
            if not stop.is_set():
                raise
            # `mise run up` stops db and sampler together. The batch has no fits
            # row, so the next start picks it up again; stray params rows are
            # never read without their marker.
            log.info("db gone during shutdown; dropping the fit for batch %d", b["id"])
            break
        print(json.dumps(row, default=str), flush=True)
        last = b["id"]


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
