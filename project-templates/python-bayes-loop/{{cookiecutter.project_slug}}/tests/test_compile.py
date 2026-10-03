import os

os.environ.setdefault("PYTENSOR_FLAGS", "floatX=float32")

import jax
import numpy as np

from {{cookiecutter.package_name}} import model as example
from {{cookiecutter.package_name}}.compile import jaxify
from {{cookiecutter.package_name}}.labels import scalars
from {{cookiecutter.package_name}}.samplers import make_chees, make_nuts

from tests.sim import SMALL, data


def setup(seed=0):
    rng = np.random.default_rng(seed)
    truth = example.draw_truth(rng, SMALL)
    m = example.build(data(rng, truth, 500), truth.coords)
    return rng, truth, m, jaxify(m)


def test_logp_tracks_new_data_without_rebuild():
    """The jaxified logp takes data as an argument and agrees with PyMC after set_data."""
    rng, truth, m, jm = setup()
    # Not the initial point: there the likelihood can be flat in the data.
    point = {k: (v + rng.normal(size=v.shape)).astype(v.dtype) for k, v in m.initial_point().items()}
    pymc_logp = m.compile_logp()

    before = pymc_logp(point)
    np.testing.assert_allclose(jm.logdensity(point, jm.data), before, rtol=1e-5)

    new = data(rng, truth, 500)
    for name, value in new.items():
        m.set_data(name, value)
    after = pymc_logp(point)
    assert not np.isclose(after, before, rtol=1e-4)  # new data really changes the logp, well past rtol below
    np.testing.assert_allclose(jm.logdensity(point, jm.cast(new)), after, rtol=1e-5)


def test_compiled_run_accepts_fresh_data():
    """AOT-compiled sampler runs on new same-shape data; a recompile would raise."""
    rng, truth, _, jm = setup()
    for make in (make_nuts, make_chees):
        run = make(jm, num_chains=4, num_warmup=20, num_draws=10, vectorized=False)
        compiled = run.lower(jax.random.key(0), jm.data).compile()
        fit = compiled(jax.random.key(1), jm.cast(data(rng, truth, 500)))
        for var, dims in example.DIMS.items():
            assert fit.draws[var].shape == (4, 10, *(len(jm.coords[d]) for d in dims)), var
            assert np.isfinite(fit.draws[var]).all(), var


def test_labels_line_up_with_flattened_values():
    """labels.scalars names values in reshape(-1) order (truth and params rows rely on it)."""
    coords = {"row": ["a", "b", "c"], "col": ["x", "y"]}
    names = [name for name, _ in scalars("v", ("row", "col"), coords)]
    values = np.arange(6).reshape(3, 2).reshape(-1)
    assert dict(zip(names, values)) == {
        "v[a, x]": 0,
        "v[a, y]": 1,
        "v[b, x]": 2,
        "v[b, y]": 3,
        "v[c, x]": 4,
        "v[c, y]": 5,
    }
    assert list(scalars("s", (), coords)) == [("s", {})]


def test_ordinal_with_indexed_predictor_compiles():
    """Data inputs keep their static shapes: PyMC's OrderedLogistic builds an arange over the rows,
    which JAX can only trace when the batch length is a constant."""
    import pymc as pm

    rng = np.random.default_rng(0)
    n = 200
    with pm.Model(coords={"cut": range(3), "type": ["a", "b"], "f": ["x1", "x2"]}) as m:
        X = pm.Data("X", rng.normal(size=(n, 2)).astype("float32"), dims=("obs_id", "f"))
        t = pm.Data("t", rng.integers(0, 2, size=n), dims="obs_id")
        y = pm.Data("y", rng.integers(0, 4, size=n), dims="obs_id")
        b = pm.Normal("b", 0, 1, dims=("type", "f"))
        cuts = pm.Normal(
            "cuts", np.array([-1.0, 0.0, 1.0]), 1, dims="cut", transform=pm.distributions.transforms.ordered
        )
        pm.OrderedLogistic("obs", eta=(X * b[t]).sum(-1), cutpoints=cuts, observed=y, compute_p=False, dims="obs_id")
    jm = jaxify(m)
    run = make_nuts(jm, num_chains=2, num_warmup=20, num_draws=10, vectorized=False)
    fit = run.lower(jax.random.key(0), jm.data).compile()(jax.random.key(1), jm.data)
    assert np.isfinite(fit.draws["b"]).all()
