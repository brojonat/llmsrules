"""End to end over a real Quack server: feed -> db -> worker -> dashboard snapshot.

Model-agnostic: expectations come from model.DIMS / VIEW and the batch's coords.
"""

import os

os.environ.setdefault("PYTENSOR_FLAGS", "floatX=float32")

import asyncio
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

from tests.fakes import fake_llm


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


def test_who_can_send_feedback():
    assert web.can_write("100.105.238.45", "any") and web.can_write("127.0.0.1", "local")
    assert not web.can_write("100.105.238.45", "local") and not web.can_write(None, "local")


def test_cli_sampler_names_match():
    assert cli.SAMPLER_NAMES == list(SAMPLERS)


def fit_all(con, batches: int, refit: int = 0) -> list[dict]:
    """Run the worker until there are `batches` fits; the fits, oldest first."""
    stop = threading.Event()
    kw = {"sampler": "chees", "chains": 16, "warmup": 30, "draws": 10, "latest": False, "poll": 0.05, "seed": 0}
    kw["refit"] = refit
    wcon = con.cursor()
    wcon.execute("use remote")  # a cursor doesn't inherit USE; query() needs it
    t = threading.Thread(target=worker.run, args=(wcon, stop), kwargs=kw)
    t.start()
    deadline = time.monotonic() + 120
    while belt.read(con, "select count(*) n from fits").to_pylist()[0]["n"] < batches:
        assert t.is_alive(), "worker died; see the traceback above"
        assert time.monotonic() < deadline, f"worker did not fit all {batches} batches"
        time.sleep(0.2)
    stop.set()
    t.join(timeout=30)
    return belt.read(con, "select * from fits order by id").to_pylist()


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


def test_feed_sample_snapshot(con, monkeypatch):
    # Reversed, so the dashboard has to follow VIEW's order rather than the draws' (alphabetical) order.
    monkeypatch.setitem(example.VIEW, "forest", example.VIEW["forest"][::-1])
    feed.simulate(con, np.random.default_rng(0), n=300, sizes=SIZES, every=0, drift=0.05, count=2)
    batches = belt.read(con, "select coords from batches").to_pylist()
    assert len(batches) == 2
    coords = json.loads(batches[0]["coords"])

    fits = fit_all(con, 2)
    assert fits[0]["compile_s"] is not None and fits[1]["compile_s"] is None  # second batch reused the program
    snap = web.snapshot(con)
    check_snapshot(snap, coords)
    # Simulated batches carry their truth, joined to the posterior by name. A forest variable the
    # simulator has no truth for (a derived probability, say) just shows no marker.
    known = {r["name"] for r in belt.read(con, "select distinct name from truth").to_pylist()}
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

    # The model panel streams Claude's description into its region, then saves it.
    board = web.Board(web.make_env())
    http, cfg, _ = fake_llm(["Customers in Austin ", "and Boston."])
    panel = web.ModelPanel(board, http, cfg)

    async def describe_once():
        await panel.show(con, models[0]["id"])
        await panel.task

    asyncio.run(describe_once())
    assert "Customers in Austin and Boston." in board.regions["model"] and "model-graph" in board.regions["model"]
    notes = belt.read(con, "select model_id, text from model_notes").to_pylist()
    assert notes == [{"model_id": models[0]["id"], "text": "Customers in Austin and Boston."}]


def test_replay_file(con, tmp_path):
    """feed --from: a file streams through in full chunks of n, one coords for all, no truth."""
    rng = np.random.default_rng(0)
    rows = example.simulate(rng, example.draw_truth(rng, SIZES), 700)
    path = tmp_path / "obs.parquet"
    pq.write_table(rows, path)

    feed.replay(con, str(path), n=300, order_by=None, every=0, count=0)
    batches = belt.read(con, "select n, coords from batches order by id").to_pylist()
    assert [b["n"] for b in batches] == [300, 300]  # the short tail is skipped: one program per file
    assert len({b["coords"] for b in batches}) == 1
    assert belt.read(con, "select count(*) n from truth").to_pylist() == [{"n": 0}]

    fits = fit_all(con, 2)
    assert [f["compile_s"] is not None for f in fits] == [True, False]
    # A sampler restarted with --refit 1 (after a model edit) fits the newest batch again.
    refits = fit_all(con, 3, refit=1)
    assert refits[-1]["batch_id"] == fits[-1]["batch_id"] and refits[-1]["model_id"] != fits[-1]["model_id"]
    assert refits[-1]["lag_s"] is None and fits[-1]["lag_s"] is not None  # a refit's "lag" would be the batch's age
    snap = web.snapshot(con)
    assert not snap["has_truth"] and snap["coverage"] is None
    check_snapshot(snap, json.loads(batches[0]["coords"]))


def test_agent_thread(con, monkeypatch, capsys):
    """Agent notes and dashboard feedback share one thread; inbox hands the agent what it hasn't read."""
    import httpx

    monkeypatch.setenv("QUACK_URL", URL)
    monkeypatch.setenv("QUACK_TOKEN", TOKEN)
    monkeypatch.setenv("FEEDBACK_FROM", "local")  # so the remote client below is refused
    feed.simulate(con, np.random.default_rng(0), n=300, sizes=SIZES, every=0, drift=0.05, count=1)
    (fit,) = fit_all(con, 1)
    model = belt.read(con, f"select source from models where id = {fit['model_id']}").to_pylist()[0]
    assert "def build(" in model["source"]  # every compiled version keeps its model.py
    capsys.readouterr()  # drop the feeder's and worker's JSON lines

    cli.main(["note", "Widening", "the", "prior", "on", "sigma"])
    assert json.loads(capsys.readouterr().out)["model_id"] == fit["model_id"]

    app = web.create_app()
    headers = {"Datastar-Request": "true"}

    def client(host: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(host, 50000)), base_url="http://test")

    async def dashboard():
        async with app.router.lifespan_context(app), client("127.0.0.1") as local, client("10.0.0.5") as remote:
            deadline = time.monotonic() + 20
            while app.state.board.con is None:  # the poll loop connects in the background
                assert time.monotonic() < deadline, "dashboard never reached the belt"
                await asyncio.sleep(0.1)
            assert (await remote.post("/messages", json={"feedback": "hi"}, headers=headers)).status_code == 403
            assert 'id="feedback-form"' not in (await remote.get("/")).text
            assert (
                await local.post("/messages", json={"feedback": "Try a Student-t"}, headers=headers)
            ).status_code == 204
            assert (await local.post("/approve", headers=headers)).status_code == 204
            assert 'id="feedback-form"' in (await local.get("/")).text

    asyncio.run(dashboard())
    thread = web.agent_view(con)["thread"]
    assert [(m["author"], m["kind"]) for m in thread] == [("agent", "note"), ("user", "feedback"), ("user", "approve")]

    cli.main(["inbox"])
    got = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(m["kind"], m["version"]) for m in got] == [("feedback", 1), ("approve", 1)]
    assert got[0]["text"] == "Try a Student-t" and got[1]["text"] == "Approved v1: commit this model."
    cli.main(["inbox"])
    assert capsys.readouterr().out == ""  # read once
    html = web.make_env().get_template("agent.html").render(**web.agent_view(con))
    assert "Widening the prior on sigma" in html and "working on your feedback" in html
    assert 'class="activity working"' in html  # the inbox read just now counts as activity

    # The agent's description of the model beats the LLM's, even after the LLM has written one.
    board = web.Board(web.make_env())
    http, cfg, _ = fake_llm(["An LLM reading of the graph."])
    panel = web.ModelPanel(board, http, cfg)

    async def describe_model():
        await panel.show(con, fit["model_id"])
        await panel.task
        assert "An LLM reading" in board.regions["model"]
        cli.main(["describe", "Customers", "convert", "by", "city."])
        await panel.show(con, fit["model_id"])

    asyncio.run(describe_model())
    assert "Customers convert by city." in board.regions["model"] and "Written by the agent" in board.regions["model"]


def test_agent_activity():
    """Working while there are fresh footprints; waiting once it's blocked on the inbox; quiet otherwise."""
    from datetime import UTC, datetime

    now = time.time()
    at = lambda t: datetime.fromtimestamp(t, UTC)
    edited = (now - 10, "edited model.py")
    assert web.activity(None, edited, now) == {"mode": "working", "what": "edited model.py", "ago_s": 10}
    assert web.activity(None, (now - 400, "ran the tests"), now)["mode"] == "quiet"
    waiting = {"kind": "status", "text": "waiting for feedback", "created_at": at(now - 5)}
    assert web.activity(waiting, edited, now)["mode"] == "waiting"
    assert not web.activity(waiting, edited, now)["stale"]
    assert web.activity({**waiting, "created_at": at(now - 900)}, None, now)["stale"]
    # An edit after it started waiting means it's working again (it got feedback some other way).
    assert web.activity({**waiting, "created_at": at(now - 60)}, edited, now)["mode"] == "working"
    note = {"kind": "note", "text": "Trying a Student-t", "created_at": at(now - 3)}
    assert web.activity(note, None, now)["what"] == "posted a note"
    assert web.activity(None, None, now) == {"mode": "none"}


def test_figures(con, monkeypatch, capsys, tmp_path):
    """The sampler saves draws; plots renders the carousel from them; the agent adds its own; the dashboard serves them."""
    import httpx
    import matplotlib

    from {{cookiecutter.package_name}} import journal, plots

    matplotlib.use("Agg")
    monkeypatch.setenv("QUACK_URL", URL)
    monkeypatch.setenv("QUACK_TOKEN", TOKEN)
    feed.simulate(con, np.random.default_rng(0), n=300, sizes=SIZES, every=0, drift=0.05, count=1)
    (fit,) = fit_all(con, 1)
    assert belt.read(con, "select count(*) n from draws").to_pylist() == [{"n": 1}]  # a new program's first fit

    kinds = plots.render(con, fit, version=1)
    assert kinds[0] == "ppc:obs" and "prior_posterior" in kinds and "forest:beta" in kinds and "rank" in kinds
    plots.render(con, fit, version=1)  # a newer render of the same version replaces the older one
    deadline = time.monotonic() + 10  # the db prunes the older render (BELT_HOUSEKEEP_S=1 here)
    while belt.read(con, "select count(*) n from figures").to_pylist()[0]["n"] > len(kinds):
        assert time.monotonic() < deadline, "the db never pruned the superseded renders"
        time.sleep(0.2)
    figs = plots.carousel(con, journal.versions(con))
    assert [f["kind"] for f in figs] == kinds and figs[0]["title"].startswith("Posterior predictive")

    png = tmp_path / "mine.png"
    png.write_bytes(belt.read(con, f"select png from figures where id = {figs[0]['id']}")["png"][0].as_py())
    capsys.readouterr()
    cli.main(["figure", str(png), "--title", "Observed vs expected"])
    assert json.loads(capsys.readouterr().out)["version"] == 1
    figs = plots.carousel(con, journal.versions(con))
    assert figs[0]["author"] == "agent" and figs[0]["title"] == "Observed vs expected"  # agent figures lead
    cli.main(["figures", "--save", str(tmp_path / "out")])
    saved = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(saved) == len(kinds) + 1 and all(Path(r["path"]).read_bytes()[:4] == b"\x89PNG" for r in saved)

    app = web.create_app()

    async def dashboard():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://t") as http,
        ):
            while app.state.board.con is None:
                await asyncio.sleep(0.1)
            r = await http.get(f"/figures/{figs[1]['id']}.png")
            assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
            assert (await http.get("/figures/1.png")).status_code == 404
            deadline = time.monotonic() + 10
            while 'class="carousel"' not in (page := (await http.get("/")).text):
                assert time.monotonic() < deadline, "the carousel never rendered"
                await asyncio.sleep(0.2)
            assert "Observed vs expected" in page and "Save PNG" in page

    asyncio.run(dashboard())
