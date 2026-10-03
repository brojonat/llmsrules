"""Turn a PyMC model into pure JAX functions whose *data* is an argument.

PyMC's own JAX path (`pymc.sampling.jax.get_jaxified_graph`) folds every
`pm.Data` container into a constant. That means new data -> new graph -> new
XLA compile, every time. Here we swap each `pm.Data` shared variable for a
symbolic input instead, so the compiled program is reused for any data of the
same shape and dtype.
"""

from collections.abc import Callable
from dataclasses import dataclass

import jax
import numpy as np
import pymc as pm
import pytensor.tensor as pt
from pymc.sampling.jax import get_jaxified_graph
from pytensor.graph.replace import graph_replace

type Position = dict[str, jax.Array]
type Data = dict[str, jax.Array]


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

    def cast(self, data: dict[str, np.ndarray]) -> Data:
        """Coerce new data to the dtypes the program was compiled for.

        PyMC narrows integer data (e.g. int32 -> int16) when building pm.Data;
        a dtype mismatch would otherwise force a recompile (or an AOT error).
        """
        return {name: np.asarray(data[name], dtype=ref.dtype) for name, ref in self.data.items()}


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
    logp, *outs = graph_replace([model.logp(), *out_vars], dict(zip(shared, symbolic)), strict=False)

    inputs = [*value_vars, *symbolic]
    logp_fn = get_jaxified_graph(inputs=inputs, outputs=[logp])
    out_fn = get_jaxified_graph(inputs=inputs, outputs=outs)

    value_names = [v.name for v in value_vars]
    data_names = [s.name for s in shared]
    var_names = [v.name for v in out_vars]

    def args(position: Position, data: Data) -> list[jax.Array]:
        return [position[n] for n in value_names] + [data[n] for n in data_names]

    def logdensity(position: Position, data: Data) -> jax.Array:
        return logp_fn(*args(position, data))[0]

    def constrain(position: Position, data: Data) -> dict[str, jax.Array]:
        return dict(zip(var_names, out_fn(*args(position, data))))

    ip = model.initial_point()
    return JaxModel(
        logdensity=logdensity,
        constrain=constrain,
        initial_position={n: np.asarray(ip[n]) for n in value_names},
        data={s.name: np.asarray(s.get_value()) for s in shared},
        var_names=var_names,
        dims={v: tuple(model.named_vars_to_dims.get(v, ())) for v in var_names},
        coords={d: [str(c) for c in labels] for d, labels in model.coords.items() if labels is not None},
    )
