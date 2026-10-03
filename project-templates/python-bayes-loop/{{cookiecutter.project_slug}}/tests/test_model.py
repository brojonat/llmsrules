"""The model contract (see model.py's docstring). Any model must pass these.

They catch, before a GPU ever sees the model: a variable without dims (the
dashboard can't label it), a VIEW naming a variable that doesn't exist, obs
rows that don't survive the obs table's types, and a model or simulator that
can't recover the simulator's own parameters.
"""

import os

os.environ.setdefault("PYTENSOR_FLAGS", "floatX=float32")

import duckdb
import jax
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from {{cookiecutter.package_name}} import feed
from {{cookiecutter.package_name}} import model as example
from {{cookiecutter.package_name}}.compile import jaxify
from {{cookiecutter.package_name}}.samplers import make_nuts
from {{cookiecutter.package_name}}.summary import summarize

from tests.sim import SMALL, data


def small(seed=0, n=500):
    """(truth, simulated obs rows) for a small problem."""
    rng = np.random.default_rng(seed)
    truth = example.draw_truth(rng, SMALL)
    return truth, example.simulate(rng, truth, n)


def test_dims_cover_every_variable():
    """Every free variable and Deterministic has dims, and DIMS says what build() does."""
    truth, rows = small()
    m = example.build(example.from_arrow(rows, truth.coords), truth.coords)
    named = [v.name for v in [*m.free_RVs, *m.deterministics]]
    assert sorted(example.DIMS) == sorted(named), "DIMS must list exactly the free variables and Deterministics"
    for name in named:
        assert tuple(m.named_vars_to_dims.get(name, ())) == tuple(example.DIMS[name]), (
            f"{name}: pass dims=DIMS[{name!r}]"
        )
    for dims in example.DIMS.values():
        for d in dims:
            assert d in truth.coords, f"dim {d!r} has no labels in the simulator's coords"


def test_every_input_is_pm_data():
    """from_arrow's arrays are exactly the model's pm.Data: anything else is frozen into the compiled program."""
    truth, rows = small()
    data = example.from_arrow(rows, truth.coords)
    m = example.build(data, truth.coords)
    assert sorted(data) == sorted(d.name for d in m.data_vars), "wrap every from_arrow array (observed too) in pm.Data"


def test_program_depends_on_data_only_through_pm_data():
    """A program compiled on batch A, given batch B, computes B's logp.

    Fails when build() derives a constant from the data (y.mean() as a prior
    location, a scale from X.std()): the sampler compiles once and would keep
    using the first batch's value. Compute such things in prepare.sql over the
    whole file, or pass them in as pm.Data.
    """
    rng = np.random.default_rng(2)
    truth = example.draw_truth(rng, SMALL)
    a, b = data(rng, truth, 500), data(rng, truth, 500)
    on_a, on_b = jaxify(example.build(a, truth.coords)), jaxify(example.build(b, truth.coords))
    point = {k: v + rng.normal(size=v.shape).astype(v.dtype) for k, v in on_b.initial_position.items()}
    # Same JAX ops on the same inputs: anything past float noise is a baked-in constant.
    np.testing.assert_allclose(on_a.logdensity(point, on_a.cast(b)), on_b.logdensity(point, on_b.data), rtol=1e-6)


def test_gradient_is_finite():
    """The samplers follow jax.grad of the logp. A NaN gradient (e.g. exp(1e4) in the untaken branch
    of a where, which JAX still differentiates) freezes every chain: the recovery test then shows
    R-hat = inf and ESS ~2, which says nothing about the cause. This says it."""
    rng = np.random.default_rng(3)
    truth = example.draw_truth(rng, SMALL)
    jm = jaxify(example.build(data(rng, truth, 500), truth.coords))
    point = {k: v + rng.normal(size=v.shape).astype(v.dtype) for k, v in jm.initial_position.items()}
    grad = jax.grad(lambda p: jm.logdensity(p, jm.data))(point)
    bad = [name for name, g in grad.items() if not np.isfinite(np.asarray(g)).all()]
    assert not bad, f"non-finite gradient for {bad}: look for inf/nan in an untaken branch (where, switch)"


def test_view_names_real_variables():
    view = example.VIEW
    assert set(view) <= {"forest", "track", "grid"}
    for var in [*view.get("forest", []), *view.get("track", [])]:
        assert var in example.DIMS, f"VIEW names {var!r}, which isn't in DIMS"
    if grid := view.get("grid"):
        assert len(example.DIMS[grid]) == 2, f"VIEW grid {grid!r} must be a 2-D variable"


def test_obs_rows_survive_the_obs_table():
    """Simulated rows -> obs table (its real column types) -> from_arrow gives the same inputs."""
    truth, rows = small()
    con = duckdb.connect()
    con.execute(example.OBS_DDL)
    con.register("rows", rows.append_column("batch_id", pa.array(np.zeros(rows.num_rows, dtype=np.int64))))
    con.execute("insert into obs by name select * from rows")
    back = con.execute("select * exclude (batch_id) from obs order by rowid").to_arrow_table()

    want, got = example.from_arrow(rows, truth.coords), example.from_arrow(back, truth.coords)
    assert want.keys() == got.keys()
    for name in want:
        np.testing.assert_allclose(got[name], want[name], rtol=1e-6, err_msg=name)


def test_replayed_file_builds_the_model(tmp_path):
    """`feed --from`: a file of obs rows loads, labels itself (coords_for), and builds."""
    _, rows = small()
    path = tmp_path / "obs.parquet"
    # An extra column (a timestamp, say) is fine: only the obs table's columns load.
    pq.write_table(rows.append_column("_test_order", pa.array(np.arange(rows.num_rows)[::-1])), path)
    loaded = feed.load(str(path), order_by=None)
    assert loaded.num_rows == rows.num_rows and loaded.column_names == rows.column_names
    by_t = feed.load(str(path), order_by="_test_order")
    assert by_t.slice(0, 1).to_pylist() == loaded.slice(rows.num_rows - 1).to_pylist()
    coords = example.coords_for(loaded)
    for dims in example.DIMS.values():
        assert set(dims) <= set(coords), f"coords_for must label every dim; got {list(coords)}"
    jaxify(example.build(example.from_arrow(loaded, coords), coords))


def test_recovers_simulated_truth():
    """Fit simulated data on CPU: chains agree, and the 90% intervals cover the truth."""
    rng = np.random.default_rng(1)
    truth = example.draw_truth(rng, SMALL)
    jm = jaxify(example.build(data(rng, truth, 2000), truth.coords))
    run = make_nuts(jm, num_chains=4, num_warmup=300, num_draws=300, vectorized=False)
    fit = jax.block_until_ready(run(jax.random.key(0), jm.data))
    params = {r["name"]: r for r in summarize(0, fit.draws, jm).to_pylist()}

    assert max(r["rhat"] for r in params.values()) < 1.05
    missing = [name for name, _ in truth.rows() if name not in params]
    assert not missing, f"truth names with no posterior scalar (labels must match labels.scalars): {missing[:5]}"
    inside = [params[name]["q05"] <= value <= params[name]["q95"] for name, value in truth.rows()]
    assert np.mean(inside) >= 0.75, f"90% intervals cover only {np.mean(inside):.0%} of the true values"
