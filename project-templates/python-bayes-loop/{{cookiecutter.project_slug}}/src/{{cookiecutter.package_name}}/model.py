"""Example model: hierarchical logistic regression with labeled dims.

Big N, modest parameter count - the shape of problem where the per-gradient
cost is dominated by a (N x K) matvec and a GPU earns its keep.

Every axis is named (`dims`) and labeled (`coords`), so a posterior scalar is
`beta[Denver, income]`, not `beta[3, 1]`. The labels come from the whole data
file (`coords_for`, stored with the feed's run in `runs.coords`), so every fit
of the file shares them and the sampler builds the model from them.

This module is the whole model-specific surface. To fit a different model,
replace it; feed, sample, bench and the dashboard only use these names:

  OBS_DDL        the obs table: one row per observation (feed adds batch_id)
  CONTEXT        what the data means, in plain words (shown with the model)
  DIMS           var -> dims, for every free variable and Deterministic
  VIEW           which variables the dashboard plots, and how
  coords_for     labels for every dim, from obs rows (`feed --from` calls it once per file)
  from_arrow     obs rows -> the arrays `build` takes as pm.Data
  build          the PyMC model
  SIM_DIMS, draw_truth, simulate
                 a simulator with known parameters: `{{cookiecutter.project_slug}} simulate`
                 (the default dataset), the benchmark, and the tests'
                 parameter-recovery check

`tests/test_model.py` checks any model against this contract.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from {{cookiecutter.package_name}}.labels import Coords, scalars

if TYPE_CHECKING:
    import pymc as pm

OBS_DDL = "create table if not exists obs(batch_id bigint, grp varchar, x float[], y tinyint);"

# Simulated world: conversion (y) of customers (rows) in cities (groups),
# driven by customer features. Past these lists, labels fall back to g20, x12...
CITIES = [
    "Austin", "Boston", "Chicago", "Denver", "Detroit", "Houston", "Miami", "Nashville",
    "Oakland", "Omaha", "Phoenix", "Portland", "Raleigh", "Reno", "Seattle", "Tampa",
    "Tucson", "Tulsa", "Boise", "Fresno", "Atlanta", "Dallas", "Memphis", "Orlando",
]  # fmt: skip
FEATURES = [
    "age", "tenure", "income", "visits", "discount", "mobile",
    "weekend", "referral", "email_opens", "cart_size", "support_calls", "distance",
]  # fmt: skip


# Simulated dim sizes (override with `--dim group=5` or BELT_DIMS="group=5 feature=4").
SIM_DIMS = {"group": 20, "feature": 8}


def feature_names(features: int) -> list[str]:
    return [FEATURES[i] if i < len(FEATURES) else f"x{i}" for i in range(features)]


def make_coords(groups: int, features: int) -> dict[str, list[str]]:
    return {
        "group": [CITIES[i] if i < len(CITIES) else f"g{i}" for i in range(groups)],
        "feature": feature_names(features),
    }


def coords_for(rows: pa.Table) -> dict[str, list[str]]:
    """Labels for a file of obs rows: every group in it, and the features by position."""
    return {
        "group": sorted(pc.unique(rows["grp"]).to_pylist()),
        "feature": feature_names(pc.max(pc.list_value_length(rows["x"])).as_py()),
    }


# What the numbers mean, for whoever (or whatever) explains the model to a reader.
CONTEXT = """\
Simulated data from the model's own generative story. Each row is one customer
in one city; y is 1 if the customer converted. X holds the customer's
standardized features. Each fit sees every row fed so far, so the intervals
narrow as data is fed, toward the true coefficients the simulator drew."""

DIMS = {"mu": ("feature",), "sigma": ("feature",), "z": ("group", "feature"), "beta": ("group", "feature")}

# What the dashboard plots. forest: intervals for the latest fit; track: those
# scalars across fits; grid (optional): a 2-D variable as rows x columns.
VIEW = {"forest": ["mu", "sigma"], "track": ["mu"], "grid": "beta"}


@dataclass(frozen=True)
class Truth:
    coords: dict[str, list[str]]
    mu: np.ndarray  # (feature,)
    sigma: np.ndarray  # (feature,)
    z: np.ndarray  # (group, feature)

    @property
    def beta(self) -> np.ndarray:
        return self.mu + self.sigma * self.z

    def rows(self) -> list[tuple[str, float]]:
        """(name, value) per scalar, named exactly like the sampler's params."""
        out = []
        for var, arr in (("mu", self.mu), ("sigma", self.sigma), ("beta", self.beta)):
            names = [name for name, _ in scalars(var, DIMS[var], self.coords)]
            out.extend(zip(names, map(float, arr.reshape(-1))))
        return out


def draw_truth(rng: np.random.Generator, sizes: Mapping[str, int] = SIM_DIMS) -> Truth:
    groups, features = sizes["group"], sizes["feature"]
    return Truth(
        coords=make_coords(groups, features),
        mu=rng.normal(0, 0.5, size=features),
        sigma=np.full(features, 0.3),
        z=rng.normal(size=(groups, features)),
    )


def simulate(rng: np.random.Generator, truth: Truth, n: int) -> pa.Table:
    """n obs rows drawn from the truth, shaped like the obs table (no batch_id)."""
    groups, features = truth.z.shape
    X = rng.normal(size=(n, features)).astype(np.float32)
    g = rng.integers(groups, size=n)
    logit = (X * truth.beta[g]).sum(-1)
    y = rng.random(n) < 1 / (1 + np.exp(-logit))
    return pa.table(
        {
            # The group is stored by label, so obs is queryable by city.
            "grp": pa.array(truth.coords["group"], pa.string()).take(g),
            "x": pa.FixedSizeListArray.from_arrays(pa.array(X.ravel()), features),
            "y": pa.array(y.astype(np.int8)),
        }
    )


def from_arrow(table: pa.Table, coords: Coords) -> dict[str, np.ndarray]:
    """obs rows -> model inputs; group labels become indices into coords["group"]."""
    g = pc.index_in(table["grp"], value_set=pa.array(coords["group"], pa.string()))
    if g.null_count:
        raise ValueError(f"obs has {g.null_count} rows whose group is not in the batch's coords")
    return {
        "X": table["x"].combine_chunks().flatten().to_numpy().reshape(-1, len(coords["feature"])),
        "g": g.to_numpy().astype(np.int32),
        "y": table["y"].to_numpy(),
    }


def build(data: dict[str, np.ndarray], coords: Coords) -> "pm.Model":
    # Imported here so the feeder and db processes don't pay for PyTensor.
    import pymc as pm

    with pm.Model(coords={k: list(v) for k, v in coords.items()}) as model:
        # obs_id has no labels: PyMC fills in integers. Its length is the data's.
        X = pm.Data("X", data["X"], dims=("obs_id", "feature"))
        g = pm.Data("g", data["g"], dims="obs_id")
        y = pm.Data("y", data["y"], dims="obs_id")

        mu = pm.Normal("mu", 0, 1, dims=DIMS["mu"])
        sigma = pm.HalfNormal("sigma", 1, dims=DIMS["sigma"])
        z = pm.Normal("z", 0, 1, dims=DIMS["z"])
        # dims are not inherited through arithmetic; label the Deterministic too.
        beta = pm.Deterministic("beta", mu + sigma * z, dims=DIMS["beta"])

        pm.Bernoulli("obs", logit_p=(X * beta[g]).sum(-1), observed=y, dims="obs_id")
    return model
