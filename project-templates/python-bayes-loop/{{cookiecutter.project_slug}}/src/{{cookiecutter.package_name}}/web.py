"""The dashboard: a read-only Quack client that streams one region over SSE.

One background task polls the belt (two ~2 ms server-side queries every
POLL_S). When a fit or batch lands it renders the dashboard once and bumps a
version; every open stream wakes, sends that shared render as a Datastar
morph, then sleeps MIN_INTERVAL_S. A belt firing 20 fits/s still repaints
browsers at most 4 times/s, always with the latest state.
"""

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import httpx
import pyarrow as pa
from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse, read_signals
from jinja2 import Environment, PackageLoader
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from {{cookiecutter.package_name}} import belt, journal, plots
from {{cookiecutter.package_name}}.describe import NoCredentials, describe
from {{cookiecutter.package_name}}.llm import LLMConfig, LLMError

log = logging.getLogger(__name__)

APP_NAME = "{{cookiecutter.project_name}}"
CLI = "{{cookiecutter.project_slug}}"  # the project's command, for the page's hints (its templates aren't rendered by the generator)
POLL_S = 0.1
MIN_INTERVAL_S = 0.25
REFRESH_S = 2.0  # re-render even when idle: "last fit 12 s ago" should age
HISTORY = 120  # fits shown in the time-series panels
LOCAL = {"127.0.0.1", "::1"}


class Board:
    """The current render of each page region, plus a version streams wait on.

    Four regions: `dashboard` changes with every fit; `model` (the PyMC
    graph) only when the sampler builds a new model; `agent` (the thread with
    the agent, journal.py) when a message lands; `figures` (the carousel,
    plots.py) when a figure is rendered or posted. Streams send a region only
    when it differs from what that stream last sent, so the diagram goes out
    once. `con` is the poll loop's belt connection; write handlers take a
    cursor from it (None while the belt is unreachable).
    """

    def __init__(self, env: Environment) -> None:
        self.env = env
        self.regions = {
            "dashboard": env.get_template("dashboard.html").render(empty=True),
            "model": env.get_template("model.html").render(model=None, note=None),
            "agent": env.get_template("agent.html").render(thread=[], activity={"mode": "none"}),
            "figures": env.get_template("figures.html").render(figs=[]),
        }
        self.con: duckdb.DuckDBPyConnection | None = None
        self.version = 0
        self._changed = asyncio.Condition()
        # /metrics: plain counters, no client library.
        self.counters = {"streams_open": 0, "patches_sent_total": 0, "renders_total": 0, "belt_up": 0}

    async def publish(self, region: str, html: str) -> None:
        self.counters["renders_total"] += 1
        if html == self.regions[region]:
            return
        async with self._changed:
            self.regions[region], self.version = html, self.version + 1
            self._changed.notify_all()

    async def wait(self, seen: int) -> int:
        async with self._changed:
            await self._changed.wait_for(lambda: self.version != seen)
            return self.version


def snapshot(con: duckdb.DuckDBPyConnection) -> dict:
    """Everything the dashboard shows, read on the server via query().

    Only the current model's fits: those whose model has the same spec
    (str_repr) as the newest fit's. Edit the model and restart the sampler,
    and the panels start over with the new model; a new batch size alone
    (same spec, new program) keeps the history.
    """
    current = "select id from models where spec = (select m.spec from fits f join models m on m.id = f.model_id order by f.id desc limit 1)"
    recent = f"select * from fits where model_id in ({current}) order by id desc limit {HISTORY}"
    fits = belt.read(con, recent).to_pylist()[::-1]
    if not fits:
        # Batches piling up with no fits means the sampler isn't running (or crashed).
        waiting = belt.read(con, "select count(*) n, epoch(now() - min(created_at)) oldest_s from batches").to_pylist()[
            0
        ]
        return {"empty": True, "waiting": waiting["n"], "oldest_s": waiting["oldest_s"]}
    latest = fits[-1]
    queued = belt.read(
        con, "select count(*) n from batches where id > (select coalesce(max(batch_id), 0) from fits)"
    ).to_pylist()[0]["n"]
    view = json.loads(belt.read(con, f"select view from models where id = {latest['model_id']}")["view"][0].as_py())
    # VIEW's order, then model order within a variable (pos follows the draws dict, which JAX sorts).
    forest_vars = ", ".join(belt.lit(v) for v in view["forest"]) or "null"
    track_vars = ", ".join(belt.lit(v) for v in view["track"]) or "null"
    totals = belt.read(
        con,
        "select count(*) fits, count(*) filter (where created_at > now() - interval 60 second) last_min,"
        f" (select count(*) from batches) batches from fits where model_id in ({current})",
    ).to_pylist()[0]
    forest = belt.read(
        con,
        f"""select p.name, p.q05, p.q25, p.q50, p.q75, p.q95, p.rhat, t.value truth
            from params p left join truth t on t.batch_id = {latest["batch_id"]} and t.name = p.name
            where p.fit_id = {latest["id"]} and p.var in ({forest_vars})
            order by list_position([{forest_vars}], p.var), p.pos""",
    ).to_pylist()
    grid = []
    if g := view["grid"]:
        grid = belt.read(
            con,
            f"""select p.name, p.coords ->> {belt.lit("$." + g["rows"])} "row", p.coords ->> {belt.lit("$." + g["cols"])} col,
                       p.q05, p.q25, p.q50, p.q75, p.q95, t.value truth
                from params p left join truth t on t.batch_id = {latest["batch_id"]} and t.name = p.name
                where p.fit_id = {latest["id"]} and p.var = {belt.lit(g["var"])}
                order by p.pos""",
        ).to_pylist()
    track = belt.read(
        con,
        f"""with f as ({recent})
            select p.name, f.id, p.q05, p.q50, p.q95, t.value truth
            from f join params p on p.fit_id = f.id and p.var in ({track_vars})
            left join truth t on t.batch_id = f.batch_id and t.name = p.name
            order by list_position([{track_vars}], p.var), p.pos, f.id""",
    ).to_pylist()
    coverage = belt.read(
        con,
        f"""with f as ({recent})
            select f.id, avg((t.value between p.q05 and p.q95)::int) cov
            from f join params p on p.fit_id = f.id
            join truth t on t.batch_id = f.batch_id and t.name = p.name
            group by f.id order by f.id""",
    ).to_pylist()

    panels: dict[str, list] = {}
    for r in track:
        panels.setdefault(r["name"], []).append([r["id"], r["q05"], r["q50"], r["q95"], r["truth"]])
    # x axis: fit sequence number within the window, so ns ids don't leak into the UI
    index = {f["id"]: i for i, f in enumerate(fits)}
    for rows in panels.values():
        for r in rows:
            r[0] = index.get(r[0], 0)

    lows = [v for r in track for v in (r["q05"], r["truth"]) if v is not None]
    highs = [v for r in track for v in (r["q95"], r["truth"]) if v is not None]
    ess_per_s = [f["min_ess"] / f["fit_s"] for f in fits]
    return {
        "empty": False,
        "latest": latest,
        "age_s": time.time() - latest["created_at"].timestamp(),
        "queued": queued,
        "totals": totals,
        "ess_per_s": ess_per_s[-1],
        "coverage": sum(c["cov"] for c in coverage) / len(coverage) if coverage else None,
        "has_truth": bool(coverage),  # simulated batches carry their truth; replayed ones don't
        "view": view,
        "forest": forest,
        "grid": grid,
        # Model order (pos is row-major), not alphabetical.
        "grid_rows": list(dict.fromkeys(r["row"] for r in grid)),
        "grid_cols": list(dict.fromkeys(r["col"] for r in grid)),
        "panels": panels,
        "track_y": [min(lows, default=0), max(highs, default=1)],  # facets share one y scale
        "spark": {
            "fit_s": [f["fit_s"] for f in fits],
            "ess_per_s": ess_per_s,
            "lag_s": [f["lag_s"] for f in fits],
            "max_rhat": [f["max_rhat"] for f in fits],
            "coverage": [c["cov"] for c in coverage],
        },
        "recent": fits[::-1][:8],
    }


class ModelPanel:
    """The model region: the PyMC graph plus a plain-English description.

    The agent working on the model writes the description (`{{cookiecutter.project_slug}}
    describe`), and that one wins, whenever it lands. Until it does, an LLM
    (if a key is configured) describes the model from its graph, streamed into
    the page and saved to `model_notes`. Descriptions belong to a version
    (spec), so a recompile of the same model keeps its text.
    """

    def __init__(self, board: Board, http: httpx.AsyncClient, cfg: LLMConfig) -> None:
        self.board, self.http, self.cfg = board, http, cfg
        self.template = board.env.get_template("model.html")
        self.model_id: int | None = None
        self.model: dict | None = None
        self.note: dict = {}
        self.task: asyncio.Task | None = None
        self.described = 0  # descriptions written by the LLM since start

    async def show(self, con: duckdb.DuckDBPyConnection, model_id: int) -> None:
        saved = await asyncio.to_thread(journal.description, con, model_id)
        if model_id == self.model_id:
            # Same model: only an agent's description landing (or changing) repaints it.
            if saved and saved["llm"] == journal.AGENT and saved["text"] != self.note.get("text"):
                if self.task:
                    self.task.cancel()
                self.note = {"status": "done", **saved}
                await self._render()
            return
        self.model_id = model_id
        self.model = (
            await asyncio.to_thread(belt.read, con, f"select * from models where id = {model_id}")
        ).to_pylist()[0]
        self.model["version"] = (await asyncio.to_thread(journal.versions, con)).get(model_id)
        if self.task:
            self.task.cancel()
        if saved:
            self.note = {"status": "done", **saved}
        else:
            self.note = {"status": "writing", "llm": self.cfg.model, "text": ""}
            self.task = asyncio.create_task(self._narrate(con, model_id))
        await self._render()

    async def _narrate(self, con: duckdb.DuckDBPyConnection, model_id: int) -> None:
        try:
            async for text in describe(self.http, self.cfg, self.model):
                self.note["text"] += text
                await self._render()
            self.note["status"] = "done"
            self.described += 1
            await self._render()
            row = {
                "model_id": [model_id], "created_at": [datetime.now(UTC)],
                "llm": [self.cfg.model], "text": [self.note["text"]],
            }  # fmt: skip
            # Own cursor: the poll loop is using `con` from another thread.
            await asyncio.to_thread(belt.write, con.cursor(), "model_notes", pa.table(row))
        except NoCredentials as e:
            self.note = {"status": "nokey", "llm": self.cfg.model, "text": str(e)}
        except (LLMError, httpx.HTTPError) as e:
            log.warning("describing model %d: %s", model_id, e)
            self.note = {"status": "error", "llm": self.cfg.model, "text": str(e) or type(e).__name__}
        except duckdb.Error as e:  # shown, just not saved; the next server start asks again
            log.warning("saving the description of model %d: %s", model_id, e)
        await self._render()

    async def _render(self) -> None:
        await self.board.publish("model", self.template.render(model=self.model, note=self.note))


async def poll(url: str, token: str, board: Board, panel: ModelPanel) -> None:
    """Connect (and reconnect) to the belt, re-rendering whenever it moves.

    The server starts without the db: until it's reachable the page says so.
    Any error drops the connection, so a restarted db is picked up again.
    """
    template = board.env.get_template("dashboard.html")
    agent = board.env.get_template("agent.html")
    figures = board.env.get_template("figures.html")
    con, seen, rendered_at = None, None, 0.0
    while True:
        try:
            if con is None:
                con = await asyncio.to_thread(belt.connect, url, token, wait_s=0)
                log.info("dashboard reading %s", url)
                seen = None
                board.con = con
                board.counters["belt_up"] = 1
            marks = await asyncio.to_thread(
                belt.read,
                con,
                "select (select coalesce(max(id), 0) from fits) f, (select coalesce(max(id), 0) from batches) b,"
                " (select coalesce(max(id), 0) from messages) m, (select count(*) from model_notes) d,"
                " (select coalesce(max(id), 0) from figures) g",
            )
            mark = tuple(marks.to_pylist()[0].values())
            if mark != seen or time.monotonic() - rendered_at > REFRESH_S:
                ctx = await asyncio.to_thread(snapshot, con)
                await board.publish("dashboard", template.render(**ctx))
                await board.publish("agent", agent.render(**await asyncio.to_thread(agent_view, con)))
                await board.publish("figures", figures.render(figs=await asyncio.to_thread(figures_view, con)))
                seen, rendered_at = mark, time.monotonic()
                if (model_id := ctx.get("latest", {}).get("model_id")) is not None:
                    await panel.show(con, model_id)
        except (duckdb.CatalogException, duckdb.BinderException) as e:
            # Reachable, but the tables aren't what this code expects (an older db file).
            log.warning("querying the belt: %s", e)
            await board.publish("dashboard", template.render(empty=True, schema_error=str(e).splitlines()[0]))
            await asyncio.sleep(1.0)
        except (duckdb.Error, RuntimeError) as e:
            if con is not None:
                log.warning("lost the belt at %s: %s", url, e)
                board.con = None
                con.close()
                con = None
            board.counters["belt_up"] = 0
            await board.publish("dashboard", template.render(empty=True, offline=url))
            await asyncio.sleep(1.0)
        await asyncio.sleep(POLL_S)


# What the agent leaves behind in the project as it works, newest wins. Checked
# from the dashboard's working directory (the project root), so it needs
# nothing from the agent or its harness.
FOOTPRINTS = [
    ("src/*/*.py", "edited {name}"),
    ("prepare.sql", "edited prepare.sql"),
    ("mise.cpu.toml", "edited mise.cpu.toml"),
    ("mise.toml", "edited mise.toml"),
    ("tests/*.py", "edited {name}"),
    (".pytest_cache/v/cache/nodeids", "ran the tests"),
    ("data/*.parquet", "prepared {name}"),
]
WORKING_S = 120  # activity this recent: working
STALE_WAIT_S = 600  # inbox --wait checks in every ~9 min; longer than this and it may have stopped


def footprint(root: Path) -> tuple[float, str] | None:
    """(mtime, what) of the newest file the agent touched, or None."""
    newest = None
    for pattern, what in FOOTPRINTS:
        for path in root.glob(pattern):
            with contextlib.suppress(OSError):
                t = path.stat().st_mtime
                if newest is None or t > newest[0]:
                    newest = (t, what.format(name=path.name))
    return newest


def activity(state: dict | None, files: tuple[float, str] | None, now: float) -> dict:
    """The agent's state from its last message and its newest footprint: working, waiting, quiet, or none."""
    events = [files] if files else []
    if state and state["kind"] != "status":
        events.append((state["created_at"].timestamp(), f"posted a {state['kind']}"))
    elif state and not state["text"].startswith("waiting"):
        events.append((state["created_at"].timestamp(), state["text"]))  # "working on your feedback"
    last = max(events, default=None)
    if state and state["kind"] == "status" and state["text"].startswith("waiting"):
        since = state["created_at"].timestamp()
        if last is None or since >= last[0]:
            return {"mode": "waiting", "since": state["created_at"], "stale": now - since > STALE_WAIT_S}
    if last is None:
        return {"mode": "none"}
    mode = "working" if now - last[0] < WORKING_S else "quiet"
    return {"mode": mode, "what": last[1], "ago_s": now - last[0]}


def agent_view(con: duckdb.DuckDBPyConnection, root: Path | None = None) -> dict:
    """The agent region: the thread, each message labeled with its model version, and what the agent is doing."""
    versions = journal.versions(con)
    thread = [{**m, "version": versions.get(m["model_id"])} for m in journal.thread(con)]
    files = footprint(root or Path.cwd())
    return {"thread": thread, "activity": activity(journal.agent_state(con), files, time.time())}


def can_write(host: str | None, feedback_from: str) -> bool:
    """Who may send feedback and approvals: anyone who can reach the dashboard ("any"), or this machine ("local").

    Feedback steers an agent that has a shell; "any" trusts everyone who can reach HOST:PORT.
    """
    return feedback_from == "any" or host in LOCAL


def figures_view(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """The carousel: newest render per (version, kind), and the agent's figures (plots.carousel)."""
    return plots.carousel(con, journal.versions(con))


def _writable(request: Request) -> bool:
    return can_write(request.client.host if request.client else None, request.app.state.feedback_from)


async def page(request: Request) -> HTMLResponse:
    board: Board = request.app.state.board
    html = board.env.get_template("page.html").render(app_name=APP_NAME, can_write=_writable(request), **board.regions)
    return HTMLResponse(html)


async def _user_message(request: Request, kind: str, text: str | None) -> Response:
    """Post a user message to the thread; the stream repaints, so 204."""
    if not _writable(request):
        return PlainTextResponse("feedback and approval are localhost-only here (FEEDBACK_FROM=local)", status_code=403)
    board: Board = request.app.state.board
    if board.con is None:
        return PlainTextResponse("the belt isn't reachable", status_code=503)
    con = belt.cursor(board.con)  # the poll loop uses board.con from another thread

    def write() -> None:
        model_id = journal.latest_model(con)
        body = text
        if kind == "approve":
            if model_id is None:
                return
            version = journal.versions(con).get(model_id)
            body = f"Approved v{version}: commit this model."
        journal.post(con, "user", kind, body, model_id)

    if text or kind == "approve":
        await asyncio.to_thread(write)
    return Response(status_code=204)


async def post_message(request: Request) -> Response:
    signals = await read_signals(request) or {}
    return await _user_message(request, "feedback", str(signals.get("feedback", "")).strip())


async def approve(request: Request) -> Response:
    return await _user_message(request, "approve", None)


async def stream(request: Request) -> DatastarResponse:
    board: Board = request.app.state.board

    async def events() -> AsyncIterator:
        sent: dict[str, str] = {}  # what this browser has; unchanged regions are never resent
        board.counters["streams_open"] += 1
        try:
            while True:
                seen = board.version
                changed = {k: html for k, html in board.regions.items() if sent.get(k) != html}
                if changed:
                    yield "".join(SSE.patch_elements(html) for html in changed.values())
                    sent.update(changed)
                    board.counters["patches_sent_total"] += len(changed)
                await asyncio.sleep(MIN_INTERVAL_S)
                await board.wait(seen)  # returns at once if a region changed meanwhile
        finally:  # Starlette cancels the generator when the browser goes away
            board.counters["streams_open"] -= 1

    return DatastarResponse(events())


async def figure(request: Request) -> Response:
    """One figure's PNG. Ids are never reused (a newer render gets a new id), so it caches forever."""
    board: Board = request.app.state.board
    if board.con is None:
        return PlainTextResponse("the belt isn't reachable", status_code=503)
    con = belt.cursor(board.con)
    sql = f"select png from figures where id = {int(request.path_params['figure_id'])}"
    rows = await asyncio.to_thread(belt.read, con, sql)
    if not rows.num_rows:
        return PlainTextResponse("no such figure (a newer render may have replaced it)", status_code=404)
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    return Response(rows["png"][0].as_py(), media_type="image/png", headers=headers)


async def healthz(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


async def metrics(request: Request) -> PlainTextResponse:
    """Prometheus text format, hand-written: a handful of gauges and counters."""
    board: Board = request.app.state.board
    panel: ModelPanel = request.app.state.panel
    values = {**board.counters, "llm_descriptions_total": panel.described}
    lines = []
    for name, value in values.items():
        kind = "counter" if name.endswith("_total") else "gauge"
        lines += [f"# TYPE dashboard_{name} {kind}", f"dashboard_{name} {value}"]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


def make_env() -> Environment:
    env = Environment(loader=PackageLoader("{{cookiecutter.package_name}}"), autoescape=True)
    env.filters["num"] = _num
    env.globals["cli"] = CLI
    env.filters["clock"] = lambda t: t.astimezone().strftime("%H:%M:%S") if t else "–"
    env.filters["ago"] = _ago
    return env


def create_app() -> Starlette:
    """App factory (uvicorn --factory), configured from QUACK_URL / QUACK_TOKEN / FEEDBACK_FROM."""
    url, token = os.environ.get("QUACK_URL", "quack:localhost"), os.environ["QUACK_TOKEN"]
    feedback_from = os.environ.get("FEEDBACK_FROM", "any")
    if feedback_from not in ("any", "local"):
        raise SystemExit(f"FEEDBACK_FROM must be 'any' or 'local', not {feedback_from!r}")
    env = make_env()

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.board = Board(env)
        app.state.feedback_from = feedback_from
        # LLM_* / OPENROUTER_API_KEY from the environment (.env via mise), as in nhtsa.
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
            panel = app.state.panel = ModelPanel(app.state.board, http, LLMConfig.from_env())
            task = asyncio.create_task(poll(url, token, app.state.board, panel))
            yield
            task.cancel()

    static = Path(__file__).parent / "static"
    routes = [
        Route("/", page),
        Route("/stream", stream),
        Route("/messages", post_message, methods=["POST"]),
        Route("/approve", approve, methods=["POST"]),
        Route("/healthz", healthz),
        Route("/metrics", metrics),
        Mount("/static", StaticFiles(directory=static), name="static"),
        Route("/figures/{figure_id:int}.png", figure),
    ]
    return Starlette(routes=routes, lifespan=lifespan)


def _ago(seconds: float, suffix: bool = True) -> str:
    """12 s ago, 4 min ago, 2 h ago (suffix=False: 12 s, 4 min, 2 h)."""
    s = max(0, int(seconds))
    text = f"{s} s" if s < 90 else f"{s // 60} min" if s < 5400 else f"{s // 3600} h"
    return f"{text} ago" if suffix else text


def _num(v: float | None, digits: int = 2) -> str:
    """1.6M, 95.9K, 950, 3.14, 0.012 - matches compact() in components.js."""
    if v is None:
        return "–"
    a = abs(v)
    if isinstance(v, int) and a < 1e4:
        return f"{v:,}"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e4:
        return f"{v / 1e3:.1f}K"
    if a >= 100:
        return f"{v:,.0f}"
    if a >= 1:
        return f"{v:.{digits}f}"
    return f"{v:.{digits}g}"
