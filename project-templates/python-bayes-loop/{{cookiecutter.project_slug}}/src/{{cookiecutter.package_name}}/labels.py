"""Name every scalar the way ArviZ does: beta[Denver, income].

The feeder (truth rows) and the sampler (param rows) must agree on these
strings, since the dashboard joins on them. Pure Python on purpose: the
feeder must not import JAX.
"""

import itertools
from collections.abc import Iterator, Mapping, Sequence

type Coords = Mapping[str, Sequence[str]]


def scalars(var: str, dims: Sequence[str], coords: Coords) -> Iterator[tuple[str, dict[str, str]]]:
    """(name, {dim: label}) for each element of `var`, in C (row-major) order.

    That is the order `x.reshape(-1)` lays elements out, so the i-th yielded
    name labels the i-th flattened value.
    """
    if not dims:
        yield var, {}
        return
    for labels in itertools.product(*(coords[d] for d in dims)):
        yield f"{var}[{', '.join(map(str, labels))}]", dict(zip(dims, map(str, labels)))
