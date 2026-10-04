"""End to end over a real Quack server: feed a file -> db -> worker -> dashboard snapshot.

Model-agnostic: expectations come from model.DIMS / VIEW and the run's coords.
"""

import os

os.environ.setdefault("PYTENSOR_FLAGS", "floatX=float32")

import asyncio
import contextlib
import json
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from {{cookiecutter.package_name}} import belt, cli, feed, web, worker
from {{cookiecutter.package_name}} import model as example
from {{cookiecutter.package_name}}.labels import scalars
from {{cookiecutter.package_name}}.samplers import SAMPLERS


def _free_port() -> int:
    """A port nobody's using, so two checkouts can run the tests at once."""
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


URL, TOKEN = f"quack:localhost:{_free_port()}", "test-token"
SIZES = {d: min(size, 3) for d, size in example.SIM_DIMS.items()}


@pytest.fixture
def con(tmp_path):
    env = {**os.environ, "QUACK_URL": URL, "QUACK_TOKEN": TOKEN, "BELT_HOUSEKEEP_S": "1"}
    cmd = [
        sys.executable,
        "-c",
        "from {{cookiecutter.package_name}}.cli import main; main()",
        "db",
        "--path",
        str(tmp_path / "belt.duckdb"),
    ]
    db = subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE, text=True)
    try:
        yield belt.connect(URL, TOKEN, wait_s=20)
    finally:
        db.send_signal(signal.SIGINT)
        _, err = db.communicate(timeout=20)
    assert db.returncode == 0, err
    assert "checkpointed" in err


def test_cli_sampler_names_match():
    assert cli.SAMPLER_NAMES == list(SAMPLERS)


@contextlib.contextmanager
def sampling(con):
    """The worker in a thread while the block runs: feed.run waits on its fits."""
    stop, failed = threading.Event(), []
    kw = {"sampler": "chees", "chains": 16, "warmup": 30, "draws": 10, "poll": 0.05, "seed": 0}
    wcon = con.cursor()
    wcon.execute("use remote")  # a cursor doesn't inherit USE; query() needs it

    def work():
        try:
            worker.run(wcon, stop, **kw)
        except Exception as e:
            failed.append(e)
            raise

    t = threading.Thread(target=work)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=30)
    assert not failed, failed


def all_fits(con) -> list[dict]:
    return belt.read(con, "select * from fits order by id").to_pylist()


def sim_file(tmp_path, n: int) -> str:
    """A simulated data file with its truth beside it, as `{{cookiecutter.project_slug}} simulate` writes."""
    path = str(tmp_path / "sim.parquet")
    feed.simulate(path, np.random.default_rng(0), n=n, sizes=SIZES)
    return path


def wait_for(con, fits: int) -> None:
    deadline = time.monotonic() + 120
    while len(all_fits(con)) < fits:
        assert time.monotonic() < deadline, f"no fit number {fits}"
        time.sleep(0.2)


def names(vars: list[str], coords: dict) -> list[str]:
    return [name for v in vars for name, _ in scalars(v, example.DIMS[v], coords)]


def check_snapshot(snap: dict, coords: dict) -> None:
    """Labeled, in model order, as VIEW asks; and the page renders."""
    view = example.VIEW
    assert not snap["empty"]
    assert [r["name"] for r in snap["forest"]] == names(view.get("forest", []), coords)
    assert list(snap["panels"]) == names(view.get("track", []), coords)
    if grid := view.get("grid"):
        rows, cols = example.DIMS[grid]
        assert snap["grid_rows"] == coords[rows] and snap["grid_cols"] == coords[cols]
        assert [r["name"] for r in snap["grid"]] == names([grid], coords)
        assert (snap["grid"][1]["row"], snap["grid"][1]["col"]) == (coords[rows][0], coords[cols][1])  # row-major
    html = web.make_env().get_template("dashboard.html").render(**snap)
    assert ("coverage" in html) == snap["has_truth"]


def test_feed_sample_snapshot(con, monkeypatch, tmp_path):
    """Feed half a simulated file, then the rest: two fits, the second on all of it."""
    # Reversed, so the dashboard has to follow VIEW's order rather than the draws' (alphabetical) order.
    monkeypatch.setitem(example.VIEW, "forest", example.VIEW["forest"][::-1])
    path = sim_file(tmp_path, 200)
    with sampling(con):
        assert [line["rows"] for line in feed.run(con, path, rows="50%", timeout=120)] == [100]
        assert [line["rows"] for line in feed.run(con, path, timeout=120)] == [200]
    coords = json.loads(belt.read(con, "select coords from runs").to_pylist()[0]["coords"])

    fits = all_fits(con)
    assert [f["n"] for f in fits] == [100, 200]  # each fit sees every row fed so far
    assert fits[0]["compile_s"] is not None and fits[1]["compile_s"] is None  # both pad to 256 rows: one program
    snap = web.snapshot(con)
    check_snapshot(snap, coords)
    assert snap["run"]["fed"] == snap["run"]["rows"] == 200 and snap["run"]["file"] == "sim.parquet"
    assert all([p[0] for p in points] == [100, 200] for points in snap["panels"].values())  # x: rows fed
    # A simulated file carries its truth, saved with the posterior by name. A forest variable the
    # simulator has no truth for (a derived probability, say) shows no marker.
    truth = belt.read(con, "select name, value from truth").to_pylist()
    name = truth[0]["name"]
    want = truth[0]["value"]
    got = belt.read(con, f"select truth from params where fit_id = {fits[1]['id']} and name = {belt.lit(name)}")
    assert np.isclose(got["truth"][0].as_py(), want)
    known = {t["name"] for t in truth}
    assert snap["has_truth"] and all(r["truth"] is not None for r in snap["forest"] if r["name"] in known)
    models = belt.read(con, "select id, view from models").to_pylist()
    assert len(models) == 1 and {f["model_id"] for f in fits} == {models[0]["id"]}
    assert json.loads(models[0]["view"])["forest"] == example.VIEW.get("forest", [])

    # Edit the model (a new spec) and its first fit takes over the panels; the old model's history drops out.
    v2 = time.time_ns()
    model = belt.read(con, f"select * from models where id = {models[0]['id']}").to_pylist()[0]
    belt.write(con, "models", pa.Table.from_pylist([{**model, "id": v2, "spec": model["spec"] + "\n# v2"}]))
    params = belt.read(con, f"select * from params where fit_id = {fits[-1]['id']}")
    belt.write(con, "params", params.set_column(0, "fit_id", pa.array([v2] * params.num_rows, pa.int64())))
    belt.write(con, "fits", pa.Table.from_pylist([{**fits[-1], "id": v2, "model_id": v2}]))
    snap = web.snapshot(con)
    assert snap["latest"]["model_id"] == v2 and len(snap["spark"]["fit_s"]) == 1

    # The model region shows the graph, and waits for the agent's description.
    html = web.make_env().get_template("model.html").render(**web.model_view(con, models[0]["id"]))
    assert "model-graph" in html and "Waiting for the agent" in html


def test_feed_cursor(con, tmp_path):
    """feed moves a cursor through the file: --rows, --chunk, the rest, --restart; a changed file starts over."""
    rng = np.random.default_rng(0)
    rows = example.simulate(rng, example.draw_truth(rng, SIZES), 700)
    path = str(tmp_path / "obs.parquet")
    pq.write_table(rows, path)  # real data: no truth beside it

    with sampling(con):
        assert [line["rows"] for line in feed.run(con, path, rows="300", timeout=120)] == [300]
        assert [line["rows"] for line in feed.run(con, path, chunk=200, timeout=120)] == [500, 700]
        assert feed.run(con, path, timeout=120) == []  # all fed
    fits = all_fits(con)
    assert [f["n"] for f in fits] == [300, 500, 700]
    assert [f["compile_s"] is not None for f in fits] == [True, False, True]  # 512, 512, then 1024 rows
    batches = belt.read(con, "select run_id, first_row, n from batches order by id").to_pylist()
    assert [(b["first_row"], b["n"]) for b in batches] == [(0, 300), (300, 200), (500, 200)]
    assert len({b["run_id"] for b in batches}) == 1
    assert belt.read(con, "select count(*) n from truth").to_pylist() == [{"n": 0}]
    snap = web.snapshot(con)
    assert not snap["has_truth"] and snap["coverage"] is None
    check_snapshot(snap, json.loads(belt.read(con, "select coords from runs").to_pylist()[0]["coords"]))

    # A (re)started sampler fits the newest batch again: after a model edit, the new model sees every row fed.
    with sampling(con):
        wait_for(con, 4)
    refit = all_fits(con)[-1]
    assert (refit["batch_id"], refit["n"]) == (fits[-1]["batch_id"], 700) and refit["model_id"] != fits[-1]["model_id"]
    assert refit["lag_s"] is None and fits[-1]["lag_s"] is not None  # a refit's "lag" would be the batch's age

    # --restart: back to row 0 in a new run, and the panels follow it.
    with sampling(con):
        assert [line["rows"] for line in feed.run(con, path, rows="10", restart=True, timeout=120)] == [10]
    snap = web.snapshot(con)
    assert snap["latest"]["n"] == 10 and snap["run"]["fed"] == 10 and len(snap["spark"]["fit_s"]) == 1
    # A changed file starts a new run by itself.
    pq.write_table(rows.slice(0, 650), path)
    with sampling(con):
        assert feed.run(con, path, rows="1%", timeout=120)[0]["of"] == 650
    assert belt.read(con, "select count(*) n from runs").to_pylist() == [{"n": 3}]
    with pytest.raises(SystemExit, match="doesn't exist"):
        feed.run(con, str(tmp_path / "missing.parquet"))


def test_agent_thread(con, monkeypatch, capsys, tmp_path):
    """The agent's notes make the thread; its status shows beside it, not in it; no route writes."""

    monkeypatch.setenv("QUACK_URL", URL)
    monkeypatch.setenv("QUACK_TOKEN", TOKEN)
    path = sim_file(tmp_path, 300)
    with sampling(con):
        feed.run(con, path, timeout=120)
    (fit,) = all_fits(con)
    model = belt.read(con, f"select source from models where id = {fit['model_id']}").to_pylist()[0]
    assert "def build(" in model["source"]  # every compiled version keeps its model.py
    capsys.readouterr()  # drop the feeder's and worker's JSON lines

    cli.main(["note", "Widening", "the", "prior", "on", "sigma"])
    assert json.loads(capsys.readouterr().out)["model_id"] == fit["model_id"]
    cli.main(["status", "refitting", "with", "a", "Student-t"])
    assert json.loads(capsys.readouterr().out)["kind"] == "status"

    view = web.agent_view(con)
    assert [(m["kind"], m["version"]) for m in view["thread"]] == [("note", 1)]
    assert view["activity"]["mode"] == "working" and view["activity"]["status"] == "refitting with a Student-t"
    html = web.make_env().get_template("agent.html").render(**view)
    assert "Widening the prior on sigma" in html and "refitting with a Student-t" in html

    app = web.create_app()
    assert not [r for r in app.routes if "POST" in (getattr(r, "methods", None) or ())]

    # The agent's description shows with its version, and survives a recompile of the same spec.
    cli.main(["describe", "Customers", "convert", "by", "city."])
    html = web.make_env().get_template("model.html").render(**web.model_view(con, fit["model_id"]))
    assert "Customers convert by city." in html and "v1" in html
    model = belt.read(con, f"select * from models where id = {fit['model_id']}").to_pylist()[0]
    belt.write(con, "models", pa.Table.from_pylist([{**model, "id": time.time_ns()}]))
    assert web.model_view(con, fit["model_id"])["note"]["text"] == "Customers convert by city."


def test_agent_activity():
    """Working while the newest sign of life is fresh, quiet after; the status rides along until replaced."""
    from datetime import UTC, datetime

    now = time.time()
    at = lambda t: datetime.fromtimestamp(t, UTC)
    edited = (now - 10, "edited model.py")
    got = web.activity(None, None, edited, now)
    assert (got["mode"], got["what"], got["ago_s"], got["status"]) == ("working", "edited model.py", 10, None)
    assert web.activity(None, None, (now - 400, "ran the tests"), now)["mode"] == "quiet"
    status = {"kind": "status", "text": "fitting v3", "created_at": at(now - 600)}
    got = web.activity(status, None, edited, now)
    assert (got["mode"], got["what"], got["status"]) == ("working", "edited model.py", "fitting v3")
    assert web.activity(status, None, None, now)["mode"] == "quiet"
    note = {"kind": "note", "text": "Trying a Student-t", "created_at": at(now - 3)}
    assert web.activity(None, note, edited, now)["what"] == "posted a note"
    assert web.activity(None, None, None, now) == {"mode": "none"}


def test_figures(con, monkeypatch, capsys, tmp_path):
    """The sampler saves draws; plots reduces them to each figure's data; the agent adds a PNG; the dashboard serves both."""
    import httpx

    from {{cookiecutter.package_name}} import journal, plots

    monkeypatch.setenv("QUACK_URL", URL)
    monkeypatch.setenv("QUACK_TOKEN", TOKEN)
    path = sim_file(tmp_path, 300)
    with sampling(con):
        feed.run(con, path, timeout=120)
    (fit,) = all_fits(con)
    assert belt.read(con, "select count(*) n from draws").to_pylist() == [{"n": 1}]  # a new program's first fit

    kinds = plots.render(con, fit, version=1)
    assert kinds == ["ppc:obs", "trace", "prior_posterior", "rank"]
    plots.render(con, fit, version=1)  # a newer render of the same version replaces the older one
    deadline = time.monotonic() + 10  # the db prunes the older render (BELT_HOUSEKEEP_S=1 here)
    while belt.read(con, "select count(*) n from figures").to_pylist()[0]["n"] > len(kinds):
        assert time.monotonic() < deadline, "the db never pruned the superseded renders"
        time.sleep(0.2)
    figs = plots.carousel(con, journal.versions(con))
    assert [f["kind"] for f in figs] == kinds and figs[0]["title"] == "Posterior predictive: obs (calibration)"
    assert all(f["how"] for f in figs)  # every diagnostic says how to read it
    data = {
        f["kind"]: json.loads(belt.read(con, f"select data from figures where id = {f['id']}")["data"][0].as_py())
        for f in figs
    }
    assert data["ppc:obs"]["chart"] == "calibration" and all(len(b) == 5 for b in data["ppc:obs"]["bins"])
    trace = data["trace"]["panels"]
    assert (
        [p["name"] for p in trace]
        == [p["name"] for p in data["rank"]["panels"]]
        == [p["name"] for p in data["prior_posterior"]["panels"]]
    )
    assert len(trace[0]["draws"]) == len(trace[0]["kde"]) and len(trace[0]["grid"]) == plots.GRID

    png = tmp_path / "mine.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    capsys.readouterr()
    cli.main(["figure", str(png), "--title", "Observed vs expected"])
    assert json.loads(capsys.readouterr().out)["version"] == 1
    figs = plots.carousel(con, journal.versions(con))
    assert figs[0]["author"] == "agent" and figs[0]["title"] == "Observed vs expected"  # agent figures lead
    cli.main(["figures", "--save", str(tmp_path / "out")])
    saved = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(saved) == len(kinds) + 1 and Path(saved[0]["path"]).read_bytes()[:4] == b"\x89PNG"
    assert all(json.loads(Path(r["path"]).read_text())["chart"] for r in saved[1:])

    app = web.create_app()

    async def dashboard():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://t") as http,
        ):
            while app.state.board.con is None:
                await asyncio.sleep(0.1)
            diagnostic = next(f for f in figs if not f["is_png"])
            r = await http.get(f"/figures/{diagnostic['id']}.json")
            assert (
                r.status_code == 200
                and r.headers["content-type"] == "application/json"
                and r.json()["chart"] == "calibration"
            )
            assert (await http.get(f"/figures/{diagnostic['id']}.png")).status_code == 404  # data, not a picture
            assert (await http.get(f"/figures/{figs[0]['id']}.png")).content[:4] == b"\x89PNG"  # the agent's
            assert (await http.get("/figures/1.png")).status_code == 404
            deadline = time.monotonic() + 10
            while 'class="carousel"' not in (page := (await http.get("/")).text):
                assert time.monotonic() < deadline, "the carousel never rendered"
                await asyncio.sleep(0.2)
            assert (
                "Observed vs expected" in page
                and "Save PNG" in page
                and "<figure-chart" in page
                and "How to read this" in page
            )

    asyncio.run(dashboard())
