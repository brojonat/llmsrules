"""Benchmark the refit loop: fresh same-shape data each rep, one JSON line per fit.

For the jitted samplers (nuts, chees) the compile is its own row and no rep
should recompile. For the PyMC baselines every rep goes through pm.sample.

With --from, the reps are the file's first full chunks of n rows instead of
simulated data: a quick, bounded check of a model on real data, no belt needed.
"""

import itertools
import json
import logging
import sys
import time
from collections.abc import Iterator, Mapping

import jax
import numpy as np
from numpyro.diagnostics import effective_sample_size, split_gelman_rubin

from {{cookiecutter.package_name}} import feed
from {{cookiecutter.package_name}} import model as example
from {{cookiecutter.package_name}}.compile import jaxify
from {{cookiecutter.package_name}}.labels import Coords
from {{cookiecutter.package_name}}.samplers import SAMPLERS
from {{cookiecutter.package_name}}.summary import summarize

BASELINES = {"pymc": "pymc", "pymc-numpyro": "numpyro", "pymc-blackjax": "blackjax"}
log = logging.getLogger(__name__)


def diagnostics(draws: dict[str, np.ndarray]) -> dict:
    """Min bulk ESS and max split-Rhat over every scalar in the posterior."""
    ess, rhat = [], []
    for x in draws.values():
        x = np.asarray(x, dtype=np.float64)
        x = x.reshape(*x.shape[:2], -1)
        ess.append(effective_sample_size(x))
        rhat.append(split_gelman_rubin(x))
    return {"min_ess": float(np.min(np.concatenate(ess))), "max_rhat": float(np.max(np.concatenate(rhat)))}


def fresh(rng: np.random.Generator, truth: example.Truth, n: int) -> dict[str, np.ndarray]:
    return example.from_arrow(example.simulate(rng, truth, n), truth.coords)


def batches(args, rng: np.random.Generator, sizes: Mapping[str, int]) -> tuple[Coords, Iterator[dict]]:
    """(coords, model inputs for each rep): simulated, or the file's chunks."""
    if args.source:
        rows = feed.load(args.source, args.order_by)
        coords = example.coords_for(rows)
        chunks = feed.chunks(rows, args.n, args.source)[args.skip :][: args.reps]
        if not chunks:
            sys.exit(f"{args.source}: --skip {args.skip} leaves no chunks of {args.n} rows")
        return coords, (example.from_arrow(c, coords) for c in chunks)
    truth = example.draw_truth(rng, sizes)
    return truth.coords, (fresh(rng, truth, args.n) for _ in range(args.reps))


def bench_jitted(args, rng: np.random.Generator, sizes: Mapping[str, int]):
    coords, reps = batches(args, rng, sizes)
    first = next(reps)
    jm = jaxify(example.build(first, coords))
    build = SAMPLERS[args.sampler]
    run = build(
        jm, num_chains=args.chains, num_warmup=args.warmup, num_draws=args.draws,
        vectorized=jax.default_backend() != "cpu",
    )  # fmt: skip

    key = jax.random.key(args.seed)
    t0 = time.perf_counter()
    compiled = run.lower(key, jm.data).compile()
    yield {"phase": "compile", "seconds": time.perf_counter() - t0}

    for rep, data in enumerate(itertools.chain([first], reps)):
        data = jm.cast(data)
        key, k = jax.random.split(key)
        t0 = time.perf_counter()
        fit = jax.block_until_ready(compiled(k, data))
        dt = time.perf_counter() - t0
        draws = jax.device_get(fit.draws)
        yield {
            "phase": "fit",
            "rep": rep,
            "seconds": dt,
            "divergences": int(fit.divergences.sum()),
            "grad_evals": int(fit.grad_evals),
            **diagnostics(draws),
        }
        if args.params:
            cols = ["var", "name", "mean", "sd", "q05", "q50", "q95", "ess", "rhat"]
            for row in summarize(0, fit.draws, jm).select(cols).to_pylist():
                yield {"phase": "param", "rep": rep, **row}


def bench_pymc(args, rng: np.random.Generator, sizes: Mapping[str, int]):
    import pymc as pm

    coords, reps = batches(args, rng, sizes)
    first = next(reps)
    m = example.build(first, coords)
    var_names = [v.name for v in m.unobserved_value_vars]
    for rep, data in enumerate(itertools.chain([first], reps)):
        for name, value in data.items():
            m.set_data(name, value)
        t0 = time.perf_counter()
        with m:
            idata = pm.sample(
                draws=args.draws, tune=args.warmup, chains=args.chains,
                nuts_sampler=BASELINES[args.sampler], random_seed=args.seed + rep,
                progressbar=False, compute_convergence_checks=False,
            )  # fmt: skip
        dt = time.perf_counter() - t0
        post = idata["posterior"]
        names = [n for n in var_names if n in post]
        yield {
            "phase": "fit",
            "rep": rep,
            "seconds": dt,
            "divergences": int(idata["sample_stats"]["diverging"].values.sum()),
            **diagnostics({n: post[n].values for n in names}),
        }


def run(args, sizes: Mapping[str, int]) -> None:
    rng = np.random.default_rng(args.seed)
    device = str(jax.devices()[0])
    log.info(
        "%s on %s: n=%d chains=%d warmup=%d draws=%d",
        args.sampler,
        device,
        args.n,
        args.chains,
        args.warmup,
        args.draws,
    )
    bench = bench_pymc if args.sampler in BASELINES else bench_jitted
    if args.params and bench is bench_pymc:
        sys.exit("--params is for the jitted samplers (nuts, chees)")
    for row in bench(args, rng, sizes):
        if "min_ess" in row:
            row["ess_per_s"] = row["min_ess"] / row["seconds"]
        print(json.dumps({"sampler": args.sampler, "device": device, **row}), flush=True)
