"""Reduce a fit to what the dashboard shows: one row per scalar parameter.

Moments and quantiles are computed on device (jitted, compiled once per
shape), so only (7, P) numbers cross into the rest of the system. ESS and
split-Rhat need autocorrelations; numpyro's numpy versions are fast enough at
this size and keep this module small.
"""

import json

import jax
import jax.numpy as jnp
import numpy as np
import pyarrow as pa
from numpyro.diagnostics import effective_sample_size, split_gelman_rubin

from {{cookiecutter.package_name}}.compile import JaxModel
from {{cookiecutter.package_name}}.labels import scalars

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
COLUMNS = ("mean", "sd", "q05", "q25", "q50", "q75", "q95")


def flat_labels(draws: dict[str, jax.Array], jm: JaxModel) -> list[tuple[str, str, dict[str, str]]]:
    """(var, name, {dim: label}) per scalar, in the order `flatten` lays them out.

    Named from the model's dims/coords (beta[Denver, income]); a dim without
    labels falls back to integer positions.
    """
    out = []
    for var, x in draws.items():
        dims = jm.dims.get(var) or tuple(f"{var}_dim_{i}" for i in range(x.ndim - 2))
        coords = {d: jm.coords.get(d) or [str(i) for i in range(n)] for d, n in zip(dims, x.shape[2:])}
        out.extend((var, name, labels) for name, labels in scalars(var, dims, coords))
    return out


def flatten(draws: dict[str, jax.Array]) -> jax.Array:
    """dict of (chains, draws, *shape) -> (chains, draws, P)."""
    return jnp.concatenate([x.reshape(*x.shape[:2], -1) for x in draws.values()], axis=-1)


@jax.jit
def _moments(flat: jax.Array) -> jax.Array:
    pooled = flat.reshape(-1, flat.shape[-1])
    qs = jnp.quantile(pooled, jnp.asarray(QUANTILES), axis=0)
    return jnp.concatenate([pooled.mean(0)[None], pooled.std(0)[None], qs])


def summarize(fit_id: int, draws: dict[str, jax.Array], jm: JaxModel) -> pa.Table:
    flat = flatten(draws)
    stats = np.asarray(_moments(flat))
    host = np.asarray(flat, dtype=np.float64)
    cols = {name: stats[i].astype(np.float32) for i, name in enumerate(COLUMNS)}
    var, name, labels = zip(*flat_labels(draws, jm))
    return pa.table(
        {
            "fit_id": pa.array(np.full(len(name), fit_id, dtype=np.int64)),
            "pos": pa.array(np.arange(len(name), dtype=np.int32)),  # model order, for sorting
            "var": var,
            "name": name,
            "coords": [json.dumps(c) for c in labels],
            **cols,
            "ess": effective_sample_size(host).astype(np.float32),
            "rhat": split_gelman_rubin(host).astype(np.float32),
        }
    )
