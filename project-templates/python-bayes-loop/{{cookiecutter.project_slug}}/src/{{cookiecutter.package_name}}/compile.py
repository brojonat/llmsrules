"""Turn a PyMC model into pure JAX functions whose *data* is an argument.

PyMC's own JAX path (`pymc.sampling.jax.get_jaxified_graph`) folds every
`pm.Data` container into a constant. That means new data -> new graph -> new
XLA compile, every time. Here we swap each `pm.Data` shared variable for a
symbolic input instead, so the compiled program is reused for any data of the
same shape and dtype.

The likelihood is weighted per row (`WEIGHTS`, 1 by default). A fit sees every
row fed so far, so its row count grows; `pad` fills the rows up to a
power-of-two `capacity` with weight-0 copies, and a growing dataset compiles
once per doubling rather than once per fit.
"""

from collections.abc import Callable
from dataclasses import dataclass

import jax
import numpy as np
import pyarrow as pa
import pymc as pm
import pytensor.tensor as pt
from pymc.sampling.jax import get_jaxified_graph
from pytensor.graph.replace import graph_replace

type Position = dict[str, jax.Array]
type Data = dict[str, jax.Array]

WEIGHTS = "_w"  # the per-row likelihood weights, passed alongside the pm.Data inputs
MIN_CAPACITY = 256


@dataclass(frozen=True)
class JaxModel:
    """A PyMC model lowered to JAX.

    logdensity(position, data) -> scalar   log p on the unconstrained space
    constrain(position, data) -> dict      unconstrained values -> named model vars
    """

    logdensity: Callable[[Position, Data], jax.Array]
    constrain: Callable[[Position, Data], dict[str, jax.Array]]
    initial_position: Position
    data: Data
    var_names: list[str]
    dims: dict[str, tuple[str, ...]]  # var -> dim names, e.g. beta -> (group, feature)
    coords: dict[str, list[str]]  # dim -> labels (dims without labels are omitted)
    row_dim: str | None  # the observed variables' leading dim, which WEIGHTS runs along (None: no weights)

    def cast(self, data: dict[str, np.ndarray], weights: np.ndarray | None = None) -> Data:
        """Coerce new data to the dtypes the program was compiled for; weights default to all ones.

        PyMC narrows integer data (e.g. int32 -> int16) when building pm.Data;
        a dtype mismatch would otherwise force a recompile (or an AOT error).
        """
        out = {}
        for name, ref in self.data.items():
            value = (np.ones_like(ref) if weights is None else weights) if name == WEIGHTS else data[name]
            out[name] = np.asarray(value, dtype=ref.dtype)
        return out


def capacity(n: int) -> int:
    """The padded row count a fit of n rows compiles for: the next power of two, at least MIN_CAPACITY."""
    return max(MIN_CAPACITY, 1 << max(0, n - 1).bit_length())


def pad(table: pa.Table, cap: int) -> tuple[pa.Table, np.ndarray]:
    """(rows padded to cap with copies of the first row, weights: 1 per real row, 0 per copy)."""
    n = table.num_rows
    take = np.concatenate([np.arange(n), np.zeros(cap - n, dtype=np.int64)])
    weights = np.concatenate([np.ones(n), np.zeros(cap - n)]).astype(np.float32)
    return table.take(pa.array(take)), weights


def jaxify(model: pm.Model) -> JaxModel:
    value_vars = model.value_vars
    shared = list(model.data_vars)
    # Static shapes: the program is compiled per (n, coords) anyway, and a symbolic
    # batch length breaks JAX wherever PyMC builds an arange over the rows
    # (OrderedLogistic / Categorical with an indexed linear predictor).
    symbolic = [pt.tensor(dtype=s.type.dtype, shape=np.shape(s.get_value())) for s in shared]
    for s, sym in zip(shared, symbolic):
        sym.name = s.name

    # Free variables and Deterministics, constrained; not the transformed values (sigma_log__).
    named = {v.name for v in [*model.free_RVs, *model.deterministics]}
    out_vars = [v for v in model.unobserved_value_vars if v.name in named]
    row_dim, rows = _rows(model)
    weights = pt.tensor(dtype="floatX", shape=(rows,), name=WEIGHTS) if row_dim else None
    logp, *outs = graph_replace(
        [_weighted_logp(model, row_dim, weights), *out_vars], dict(zip(shared, symbolic)), strict=False
    )

    inputs = [*value_vars, *symbolic]
    logp_fn = get_jaxified_graph(inputs=inputs + ([weights] if row_dim else []), outputs=[logp])
    out_fn = get_jaxified_graph(inputs=inputs, outputs=outs)

    value_names = [v.name for v in value_vars]
    data_names = [s.name for s in shared]
    var_names = [v.name for v in out_vars]

    def args(position: Position, data: Data) -> list[jax.Array]:
        return [position[n] for n in value_names] + [data[n] for n in data_names]

    def logdensity(position: Position, data: Data) -> jax.Array:
        return logp_fn(*args(position, data), *([data[WEIGHTS]] if row_dim else []))[0]

    def constrain(position: Position, data: Data) -> dict[str, jax.Array]:
        return dict(zip(var_names, out_fn(*args(position, data))))

    ip = model.initial_point()
    data = {s.name: np.asarray(s.get_value()) for s in shared}
    if row_dim:
        data[WEIGHTS] = np.ones(rows, dtype=weights.dtype)
    return JaxModel(
        logdensity=logdensity,
        constrain=constrain,
        initial_position={n: np.asarray(ip[n]) for n in value_names},
        data=data,
        var_names=var_names,
        dims={v: tuple(model.named_vars_to_dims.get(v, ())) for v in var_names},
        coords={d: [str(c) for c in labels] for d, labels in model.coords.items() if labels is not None},
        row_dim=row_dim,
    )


def _rows(model: pm.Model) -> tuple[str | None, int]:
    """(the first observed variable's leading dim, its length): the dim the rows of obs run along."""
    for rv in model.observed_RVs:
        if dims := model.named_vars_to_dims.get(rv.name):
            return dims[0], int(model.dim_lengths[dims[0]].eval())
    return None, 0


def _weighted_logp(model: pm.Model, row_dim: str | None, weights) -> pt.TensorVariable:
    """model.logp(), with each row's likelihood terms multiplied by its weight.

    Weighted: observed variables and Potentials whose leading dim is the row
    dim. A model whose likelihood doesn't run along the rows (one that
    aggregates rows in build, say) can't be padded; tests/test_model.py says so.
    """
    terms = []
    for v in [*model.free_RVs, *model.observed_RVs, *model.potentials]:
        (term,) = model.logp(vars=[v], sum=False)
        per_row = v not in model.free_RVs and model.named_vars_to_dims.get(v.name, (None,))[:1] == (row_dim,)
        if row_dim and per_row:
            term = term * pt.shape_padright(weights, term.ndim - 1)
        terms.append(term.sum())
    return pt.stack(terms).sum()
