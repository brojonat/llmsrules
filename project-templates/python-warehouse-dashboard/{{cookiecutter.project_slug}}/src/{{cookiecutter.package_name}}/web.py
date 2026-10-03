"""The HTTP server, shaped by the Tao of Datastar.

Every page is `GET /<page>` for the first paint plus a stream, a read that
never returns: it renders the page's live regions, blocks until something
relevant changes, and renders again. Writes are short requests that mutate
server-side state and answer 204; the change reaches the screen on the
stream. Each region is one template used for both the first paint and every
patch.

What a dashboard shows is per-session state (a `sid` cookie keys a Filter),
so a write wakes only that session's streams. A new warehouse build wakes all
of them.
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import hashlib
import json
import logging
import os
import secrets
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import jinja2
from datastar_py import ServerSentEventGenerator as SSE
from markdown_it import MarkdownIt
from markupsafe import Markup
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from . import chat, display, llm, prompt
from .appdb import AppDB
from .chat import Chats
from .llm import LLMConfig
from .logs import configure as configure_logging
from .metrics import TILES, Collector, Sampler, prometheus, read_limits, sample_dict
from .schema import STATES
from .search import TextIndex
from .sql import Limits, SqlSandbox
from .stream import Hub, sse
from .tools import ViewTools
from .warehouse import (
    DIMENSIONS,
    METRICS,
    MIN_TICKETS,
    Filter,
    Warehouse,
    describe_years,
    toggle,
    update_filter,
    year_range,
)

log = logging.getLogger(__name__)

APP_NAME = "{{cookiecutter.project_name}}"
SESSION_COOKIE = "sid"
ADMIN = "admin"  # hub key for /admin watchers
STATIC = Path(__file__).parent / "static"


@dataclass
class Config:
    warehouse: Path
    app_db: Path | None = None  # SQLite for state we keep; None = a temp file (tests)
    sample_interval: float = 1.0
    llm: LLMConfig = field(default_factory=LLMConfig)
    app_name: str = APP_NAME
    # DuckDB sizes itself to the machine; in a container, cap it to the pod.
    duckdb_memory: str | None = None
    duckdb_threads: int | None = None
    query_cache: int = 20_000  # memoized query results (see Warehouse._query)
    sandbox: Limits = field(default_factory=Limits)

    @classmethod
    def from_env(cls) -> Config:
        env = os.environ.get
        data = Path(env("DATA_DIR", "data"))
        return cls(
            warehouse=Path(env("WAREHOUSE", str(data / "warehouse"))),
            app_db=Path(env("APP_DB", str(data / "app.sqlite"))),
            sample_interval=float(env("SAMPLE_INTERVAL", "1")),
            llm=LLMConfig.from_env(),
            app_name=env("APP_NAME", APP_NAME),
            duckdb_memory=env("DUCKDB_MEMORY") or None,
            duckdb_threads=int(env("DUCKDB_THREADS")) if env("DUCKDB_THREADS") else None,
            query_cache=int(env("QUERY_CACHE", "20000")),
            sandbox=Limits(memory=env("SANDBOX_MEMORY", "1GB")),
        )


@dataclass
class State:
    """Everything the handlers share. Built once in `create_app`."""

    config: Config
    collector: Collector
    sampler: Sampler
    warehouse: Warehouse
    hub: Hub
    templates: jinja2.Environment
    chats: Chats
    sandbox: SqlSandbox
    appdb: AppDB
    filters: dict[str, Filter] = field(default_factory=dict)
    searches: dict[str, dict[str, str]] = field(default_factory=dict)  # sid -> picker -> search text
    open_picker: dict[str, str] = field(default_factory=dict)  # sid -> the builder picker that's open
    rendered: dict[tuple, str] = field(default_factory=dict)
    prompt: tuple[str, str] = ("", "")  # (built_at, system prompt) cache


def create_app(config: Config, llm_http: httpx.AsyncClient | None = None) -> Starlette:
    """`llm_http` is the client chat requests go through; tests pass one with
    a mock transport. By default one is created and closed with the app."""
    collector = Collector()
    owns_http = llm_http is None
    llm_http = llm_http or httpx.AsyncClient(timeout=httpx.Timeout(30, read=120))
    collector.chat_daily_tokens = config.llm.daily_tokens
    templates = jinja2.Environment(
        loader=jinja2.PackageLoader(__package__, "templates"),
        autoescape=True,
        # A missing context variable is a bug; fail loudly instead of rendering "".
        undefined=jinja2.StrictUndefined,
        extensions=["jinja2.ext.do"],
        trim_blocks=True,
        lstrip_blocks=True,
    )
    templates.globals["app_name"] = config.app_name
    templates.filters["n"] = display.compact
    templates.filters["commas"] = lambda v: f"{int(v):,}"
    templates.filters["markdown"] = _markdown
    templates.filters["tool_chip"] = tool_chip
    hub = Hub()
    warehouse = Warehouse(config.warehouse, on_query=collector.query, cache_size=config.query_cache,
                          memory=config.duckdb_memory, threads=config.duckdb_threads)  # fmt: skip
    filters: dict[str, Filter] = {}
    sandbox = SqlSandbox(config.warehouse, config.sandbox, on_query=collector.sql_query)
    state = State(
        config=config,
        collector=collector,
        sampler=Sampler(collector, interval=config.sample_interval),
        warehouse=warehouse,
        hub=hub,
        templates=templates,
        filters=filters,
        sandbox=sandbox,
        appdb=AppDB(config.app_db or Path(tempfile.mkdtemp(prefix="app-db-")) / "app.sqlite"),
        chats=Chats(
            config.llm,
            llm_http,
            system_prompt=lambda: system_prompt(state),
            notify=hub.notify,
            # The assistant drives the same per-session filters the page's controls do.
            tools=ViewTools(warehouse, filters, hub.notify, sandbox, TextIndex(config.warehouse)),
            on_reply=lambda seconds, usage, ok: _on_reply(state, seconds, usage, ok),
            on_in_flight=lambda n: setattr(collector, "chat_in_flight", n),
            tokens_today=lambda: state.appdb.tokens_today(),
        ),
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await asyncio.to_thread(state.warehouse.reload_if_changed)
        if config.llm.configured:
            state.chats.window = await llm.context_window(llm_http, config.llm)
            log.info("chat model=%s context_window=%s", config.llm.model, state.chats.window or "unknown")
        tasks = [
            asyncio.create_task(state.sampler.measure_lag()),
            asyncio.create_task(_tick(state)),
        ]
        log.info("serving warehouse=%s built_at=%s", config.warehouse,
                 state.warehouse.manifest.get("built_at", "never"))  # fmt: skip
        yield
        for t in tasks:
            t.cancel()
        if owns_http:
            await llm_http.aclose()
        state.appdb.close()

    app = Starlette(
        routes=[
            Route("/", dashboard_page),
            Route("/stream", dashboard_stream),
            Route("/filter", set_filter, methods=["POST"]),
            Route("/filter/toggle", toggle_value, methods=["POST"]),
            Route("/filter/clear", clear_filter, methods=["POST"]),
            Route("/filter/range", set_range, methods=["POST"]),
            Route("/builder/search", builder_search, methods=["POST"]),
            Route("/builder/open", builder_open, methods=["POST"]),
            Route("/dataset.{fmt}", export_dataset),
            Route("/chat/send", chat_send, methods=["POST"]),
            Route("/chat/clear", chat_clear, methods=["POST"]),
            Route("/chat/feedback", chat_feedback, methods=["POST"]),
            Route("/chat/feedback/draft", chat_feedback_draft, methods=["POST"]),
            Route("/methodology", methodology_page),
            Route("/admin", admin_page),
            Route("/admin/stream", admin_stream),
            Route("/admin/threshold/{name}", set_threshold, methods=["PUT"]),
            Route("/admin/samples", admin_samples),
            Route("/metrics", metrics),
            Route("/healthz", healthz),
            # Browsers and iOS look for these at the root, not under /static.
            Route("/favicon.png", lambda r: FileResponse(STATIC / "favicon.png")),
            Route("/apple-touch-icon.png", lambda r: FileResponse(STATIC / "apple-touch-icon.png")),
            Mount("/static", StaticFiles(directory=STATIC), name="static"),
        ],
        lifespan=lifespan,
    )
    app.state.s = state
    return CountRequests(app, collector)


def app_from_env() -> Starlette:
    """Factory for `uvicorn --factory` (and so for --reload): config from env.
    Logging is configured here too, since --reload serves from a child process."""
    configure_logging()
    return create_app(Config.from_env())


async def _tick(state: State) -> None:
    """Once per interval: sample the process, wake /admin, and pick up a new
    warehouse build if one landed (which wakes every dashboard)."""
    while True:
        await asyncio.sleep(state.config.sample_interval)
        try:
            state.sampler.take()
            state.hub.notify(ADMIN)
            if await asyncio.to_thread(state.warehouse.reload_if_changed):
                log.info("warehouse reloaded built_at=%s", state.warehouse.manifest.get("built_at"))
                state.rendered.clear()
                state.hub.notify_all()
        except Exception:
            log.exception("tick failed")


class CountRequests:
    """ASGI middleware: count every response by status. Pure ASGI rather than
    BaseHTTPMiddleware, which buffers and would break streaming."""

    def __init__(self, app: ASGIApp, collector: Collector) -> None:
        self.app, self.collector = app, collector
        self.state = app.state  # so tests can reach app.state.s

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def counting_send(message) -> None:
            if message["type"] == "http.response.start":
                self.collector.request(message["status"])
            await send(message)

        await self.app(scope, receive, counting_send)


def _state(request: Request) -> State:
    return request.app.state.s


def _session(request: Request) -> tuple[str, bool]:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        return sid, False
    return secrets.token_urlsafe(16), True


def _render(state: State, name: str, **ctx) -> str:
    started = time.perf_counter()
    html = state.templates.get_template(name).render(**ctx)
    state.collector.render(time.perf_counter() - started)
    return html


def _page(state: State, region: str, title: str, stream_url: str, aside: str = "") -> str:
    return _render(state, "layout.html", region=Markup(region), aside=Markup(aside), title=title, stream_url=stream_url)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def describe(f: Filter, skip: tuple[str, ...] = ()) -> str:
    """A short human description of a dataset, for headings and labels:
    'Ledger, Relay · Enterprise · CA, OR · opened 2022–2024'."""
    parts = []
    for name in ("products", "plans", "channels", "categories", "states"):
        values = getattr(f, name)
        if values and name not in skip:
            label = DIMENSIONS[name].label.lower()
            parts.append(", ".join(values) if len(values) <= 3 else f"{len(values)} {label}")
    if not parts and "products" not in skip:
        parts.append("all tickets")
    if "years" not in skip:
        parts.append(f"opened {describe_years(f.years)}" if f.years else "all years")
    return " · ".join(parts)


async def _dashboard_ctx(state: State, f: Filter) -> dict:
    wh = state.warehouse
    if not wh.ready:
        return {"ready": False, "filter": f}
    board = await asyncio.to_thread(wh.dashboard, f)
    t = board.totals
    pct = "–" if t.escalation_pct is None else f"{t.escalation_pct:.1f}"
    hours = "–" if t.mean_hours is None else f"{t.mean_hours:.1f}"
    csat = "–" if t.mean_csat is None else f"{t.mean_csat:.2f}"
    return {
        "ready": True,
        "filter": f,
        "board": board,
        # (label, value, unit) for the stat tiles
        "tiles": [
            ("Tickets", display.compact(t.tickets), ""),
            ("Escalated", pct, "%"),
            ("Time to resolve", hours, " h mean"),
            ("Satisfaction", csat, " / 5"),
            ("Refunds", "$" + display.compact(t.refunds_usd), ""),
        ],
        "scope_no_years": describe(f, skip=("years",)),
        "scope_no_states": describe(f, skip=("states",)),
        "years_text": describe_years(f.years),
        "window": describe_years(f.years) if f.years else "all years",
        # Chart data travels as JSON in element attributes; d3 components draw it.
        "year_series": _year_series(board.by_year),
        "this_year": str(wh.through_year),
        "category_series": [[c, n] for c, n in board.categories],
        # [fips, usps, name, tickets, value|null] per state; value is what gets colored.
        "state_series": [
            [s.fips, s.state, s.name, s.tickets, None if s.value is None else round(s.value, 4)] for s in board.states
        ],
        "map_metric": board.metric,
        "metrics": [
            {
                "key": k,
                "label": m.label,
                "unit": m.unit,
                "kind": m.kind,
                "available": wh.available(k, f),
                "why": "needs products, plans, channels or categories selected" if m.needs_subset else "",
            }
            for k, m in METRICS.items()
        ],
        "min_tickets": MIN_TICKETS,
        "manifest": wh.manifest,
    }


async def render_builder(state: State, sid: str) -> str:
    """The dataset builder: chips for what's opted in, and a picker per
    dimension whose options carry faceted counts (given the other
    selections) and honor that picker's search text. Per session, not cached
    beyond the warehouse's per-(filter, dim, query) option cache."""
    f = state.filters.get(sid, Filter())
    wh = state.warehouse
    if not wh.ready:
        return '<section id="builder"></section>'
    searches = state.searches.get(sid, {})
    open_dim = state.open_picker.get(sid)
    totals = await asyncio.to_thread(wh.totals, f)
    dims = []
    for name, dim in DIMENSIONS.items():
        query = searches.get(name, "")
        # Only the open picker's options are worth a query; closed ones show chips only.
        options = (
            await asyncio.to_thread(wh.options, f, name, query, 60 if dim.kind is int else 40)
            if name == open_dim
            else []
        )
        chosen = set(getattr(f, name))
        dims.append({
            "name": name,
            "label": dim.label,
            "selected": [(v, _value_label(name, v)) for v in getattr(f, name)],
            "summary": describe_years(getattr(f, name)) if dim.kind is int else "",
            "options": [(v, _value_label(name, v), n, v in chosen) for v, n in options],
            "searchable": dim.kind is str,
            "query": query,
            "open": name == open_dim,
        })  # fmt: skip
    return _render(state, "builder.html", filter=f, dims=dims, total=totals.tickets)


def _value_label(dim: str, value) -> str:
    return f"{value} · {STATES[value][1]}" if dim == "states" and value in STATES else str(value)


def _year_series(rows: list[tuple[int, int]]) -> list[list]:
    """Every year from first to last, zero-filled: a year with no tickets is
    a zero bar, not a gap the ordinal axis silently closes."""
    if not rows:
        return []
    counts = dict(rows)
    return [[str(y), counts.get(y, 0)] for y in range(rows[0][0], rows[-1][0] + 1)]


async def render_dashboard(state: State, f: Filter) -> str:
    """The dashboard region for a filter. Every session looking at the same
    filter shares one query (the Warehouse cache) and one render (this one)."""
    key = (f, state.warehouse.manifest.get("built_at"))
    html = state.rendered.get(key)
    if html is None:
        html = _render(state, "dashboard.html", **await _dashboard_ctx(state, f))
        if len(state.rendered) >= 512:
            state.rendered.clear()
        state.rendered[key] = html
    return html


async def dashboard_page(request: Request) -> Response:
    state = _state(request)
    sid, new = _session(request)
    region = await render_builder(state, sid) + await render_dashboard(state, state.filters.get(sid, Filter()))
    aside = _render(state, "chat_shell.html", region=Markup(render_chat(state, sid)))
    resp = HTMLResponse(_page(state, region, "Dashboard", "/stream", aside=aside))
    if new:
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
    return resp


async def dashboard_stream(request: Request) -> Response:
    state = _state(request)
    sid, _ = _session(request)

    async def events() -> AsyncIterator[str]:
        # Three regions share this stream: the dataset builder, the dashboard
        # and the chat panel. Each wake re-renders all of them but sends only
        # what changed, so a chat token doesn't resend the dashboard, and a
        # picker search doesn't resend the charts.
        sent: dict[str, str] = {}
        with state.hub.watch(sid) as changed:
            while True:
                regions = {
                    "builder": await render_builder(state, sid),
                    "dashboard": await render_dashboard(state, state.filters.get(sid, Filter())),
                    "chat": render_chat(state, sid),
                }
                patch = "".join(SSE.patch_elements(html) for k, html in regions.items() if sent.get(k) != html)
                if patch:
                    sent.update(regions)
                    yield patch
                await changed.wait()
                changed.clear()

    return sse(request, events(), state.collector)


# ---------------------------------------------------------------------------
# Commands: mutate the session's filter, wake its streams, answer 204
# ---------------------------------------------------------------------------


async def _fields(request: Request) -> dict:
    """A command's fields: a JSON body (Datastar `payload`), a form, or the
    query string. The builder's values can contain '&', ',' and quotes, so
    the page sends JSON."""
    fields = dict(request.query_params)
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except ValueError:
            body = {}
        fields.update(body if isinstance(body, dict) else {})
    else:
        fields.update(await request.form())
    return fields


def _command(state: State, sid: str, change) -> Response:
    """Apply a filter change (a function of the current Filter), wake the
    session's streams, answer 204. Invalid changes answer 400 with why."""
    try:
        state.filters[sid] = change(state.filters.get(sid, Filter()))
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=400)
    state.hub.notify(sid)
    return Response(status_code=204)


async def set_filter(request: Request) -> Response:
    """Write side: replace any of the filter's fields (the map metric, or a
    whole dimension's set). Renders nothing."""
    state, (sid, _) = _state(request), _session(request)
    fields = await _fields(request)
    return _command(state, sid, lambda f: update_filter(f, fields))


async def toggle_value(request: Request) -> Response:
    """Opt one value in or out: a picker option, a chip, a map state, a bar."""
    state, (sid, _) = _state(request), _session(request)
    fields = await _fields(request)
    dim = str(fields.get("dim", ""))
    if dim not in DIMENSIONS:
        return PlainTextResponse(f"unknown dimension {dim!r}", status_code=400)
    return _command(state, sid, lambda f: toggle(f, dim, fields.get("value")))


async def clear_filter(request: Request) -> Response:
    """Clear one dimension (`dim`), or every dimension (not the map metric)."""
    state, (sid, _) = _state(request), _session(request)
    dim = str((await _fields(request)).get("dim", ""))
    if dim and dim not in DIMENSIONS:
        return PlainTextResponse(f"unknown dimension {dim!r}", status_code=400)
    if not dim:
        state.searches.pop(sid, None)
    dims = [dim] if dim else list(DIMENSIONS)
    return _command(state, sid, lambda f: update_filter(f, {d: [] for d in dims}))


async def set_range(request: Request) -> Response:
    """Years opened from a drag on the year chart: every year from..to."""
    state, (sid, _) = _state(request), _session(request)
    fields = await _fields(request)
    try:
        years = year_range(fields["from"], fields["to"])
    except (KeyError, TypeError, ValueError):
        return PlainTextResponse("range needs integer 'from' and 'to' years", status_code=400)
    return _command(state, sid, lambda f: update_filter(f, {"years": years}))


async def builder_search(request: Request) -> Response:
    """A picker's search text. Session UI state, kept on the server so the
    builder region re-renders with matching options on the stream."""
    state, (sid, _) = _state(request), _session(request)
    fields = await _fields(request)
    dim = str(fields.get("dim", ""))
    if dim not in DIMENSIONS:
        return PlainTextResponse(f"unknown dimension {dim!r}", status_code=400)
    state.searches.setdefault(sid, {})[dim] = str(fields.get("q", ""))[:80]
    state.hub.notify(sid)
    return Response(status_code=204)


async def builder_open(request: Request) -> Response:
    """Open a picker (closing any other), or close it. Server state, so
    options are computed only for the picker someone is looking at.

    `{dim}` toggles (the "+ add" summary). `{dim, open: false}` closes that
    picker only if it's the open one (a click outside it, or Escape), so it
    can race a click on another picker's summary in either order and still
    leave that one open."""
    state, (sid, _) = _state(request), _session(request)
    fields = await _fields(request)
    dim = str(fields.get("dim", ""))
    if dim not in DIMENSIONS:
        return PlainTextResponse(f"unknown dimension {dim!r}", status_code=400)
    is_open = state.open_picker.get(sid) == dim
    want = fields.get("open")
    if want is False or (want is None and is_open):
        if is_open:
            state.open_picker.pop(sid)
    else:
        state.open_picker[sid] = dim
    state.hub.notify(sid)
    return Response(status_code=204)


async def export_dataset(request: Request) -> Response:
    """The session's dataset as CSV or Parquet: every matching ticket, text
    included. Written by DuckDB to a temp file, streamed, deleted."""
    state, (sid, _) = _state(request), _session(request)
    fmt = request.path_params["fmt"]
    if fmt not in ("csv", "parquet"):
        return PlainTextResponse("csv or parquet", status_code=404)
    f = state.filters.get(sid, Filter())
    try:
        path = await asyncio.to_thread(state.warehouse.export, f, fmt)
    except RuntimeError as e:
        return PlainTextResponse(str(e), status_code=503)
    name = f"tickets-{state.warehouse.manifest.get('data_through', '')}.{fmt}"
    return FileResponse(path, filename=name, background=BackgroundTask(os.unlink, path),
                        media_type="text/csv" if fmt == "csv" else "application/vnd.apache.parquet")  # fmt: skip


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


def _on_reply(state: State, seconds: float, usage: llm.Usage | None, ok: bool) -> None:
    """Metrics, plus today's usage in the app DB (what the daily budget reads)."""
    state.collector.chat_reply(seconds, usage, ok)
    if usage is None:
        return
    model = state.config.llm.model
    today = state.appdb.add_usage(
        model, usage.prompt_tokens, usage.completion_tokens, usage.cached_tokens, usage.cost or 0.0
    )
    state.collector.chat_tokens_today = today
    log.info(
        "chat reply model=%s seconds=%.1f prompt_tokens=%d completion_tokens=%d cached_tokens=%d cost=%.5f "
        "tokens_today=%d budget=%d",
        model, seconds, usage.prompt_tokens, usage.completion_tokens, usage.cached_tokens, usage.cost or 0.0,
        today, state.config.llm.daily_tokens,
    )  # fmt: skip


def _usage_summary(state: State) -> dict:
    """/admin's LLM usage line: today and the last 7 days, all models."""
    rows = state.appdb.usage(days=7)
    today = datetime.now(UTC).date().isoformat()

    def total(rs) -> dict:
        rs = list(rs)
        return {"tokens": sum(r.tokens for r in rs), "replies": sum(r.replies for r in rs),
                "cost": sum(r.cost for r in rs)}  # fmt: skip

    return {"today": total(r for r in rows if r.day == today), "week": total(rows),
            "budget": state.config.llm.daily_tokens}  # fmt: skip


def _partial_year(through: str) -> str:
    """How much of the partial year the data covers, so the model never counts days."""
    try:
        day = date.fromisoformat(through)
    except (TypeError, ValueError):
        return "Partial-year coverage: unknown"
    elapsed = day.timetuple().tm_yday
    total = 366 if calendar.isleap(day.year) else 365
    return f"Partial-year coverage: {elapsed} of {total} days of {day.year} ({100 * elapsed / total:.1f}%)"


def system_prompt(state: State) -> str:
    """docs/assistant.md + the live schema + the methodology + build facts.
    Rebuilt only when the warehouse changes, so it's stable within a
    conversation (and cacheable by the provider)."""
    wh = state.warehouse
    built_at = wh.manifest.get("built_at", "")
    if state.prompt[0] == built_at and state.prompt[1]:
        return state.prompt[1]
    through = wh.manifest.get("data_through") or ""
    first = wh.span[0].isoformat() if wh.span else "unknown"
    facts = [
        f"Today: {datetime.now(UTC).date().isoformat()}",
        f"Warehouse built: {built_at or 'not built'}",
        f"Data runs from {first} through {through or 'unknown'}",
        f"Partial year: {wh.through_year} (data through {through or '?'}). Last full year: {wh.through_year - 1}. "
        f"Every year before {wh.through_year} is complete.",
        _partial_year(through),
        f"Minimum tickets to rate a state on the map: {MIN_TICKETS}",
        f"Chat model: {state.config.llm.model}",
    ]
    sandbox = None
    if wh.ready:
        state.sandbox.ensure(built_at)
        sandbox = state.sandbox
    text = prompt.build(sandbox, facts)
    state.prompt = (built_at, text)
    return text


def render_chat(state: State, sid: str) -> str:
    chats = state.chats
    return _render(state, "chat.html", conv=chats.get(sid), usage=chats.usage(sid), configured=chats.cfg.configured,
                   model=chats.cfg.model, max_chars=chat.MAX_MESSAGE_CHARS)  # fmt: skip


async def chat_send(request: Request) -> Response:
    """Command: append the user's message and start the reply. The reply
    streams into the chat region on the page's SSE stream."""
    state, (sid, _) = _state(request), _session(request)
    fields = await _fields(request)
    if error := state.chats.send(sid, str(fields.get("message", ""))):
        return PlainTextResponse(error, status_code=409 if "wait" in error else 400)
    return Response(status_code=204)


async def chat_clear(request: Request) -> Response:
    state, (sid, _) = _state(request), _session(request)
    state.chats.clear(sid)
    return Response(status_code=204)


def _pseudonym(sid: str) -> str:
    """Stored with feedback instead of the session cookie itself: groups one
    session's feedback without keeping anything that could resume it."""
    return hashlib.sha256(sid.encode()).hexdigest()[:16]


async def chat_feedback(request: Request) -> Response:
    """The Claude Code-style check-in. Actions: open (the Feedback button),
    rate (1 bad, 2 fine, 3 good: stored at once, with the conversation and
    dataset), comment (the optional follow-up), skip, dismiss."""
    state, (sid, _) = _state(request), _session(request)
    fields = await _fields(request)
    action = str(fields.get("action", ""))
    conv = state.chats.conversation(sid)
    if action == "open":
        conv.checkin, conv.checkin_id = "asking", None
    elif action == "rate":
        try:
            rating = int(fields.get("rating", 0))
        except (TypeError, ValueError):
            rating = 0
        if rating not in (1, 2, 3):
            return PlainTextResponse("rating is 1, 2 or 3", status_code=400)
        conv.checkin_id = await asyncio.to_thread(
            state.appdb.add_feedback, kind="rating", rating=rating, session=_pseudonym(sid),
            dataset=asdict(state.filters.get(sid, Filter())), transcript=conv.transcript(),
            model=state.config.llm.model,
        )  # fmt: skip
        conv.checkin = "rated"
        state.collector.feedback += 1
    elif action == "comment" and conv.checkin == "rated" and conv.checkin_id:
        text = str(fields.get("text", "")).strip()[:4000]
        if text:
            await asyncio.to_thread(state.appdb.add_comment, conv.checkin_id, text)
        conv.checkin = "done"
    elif action in ("skip", "dismiss"):
        conv.checkin = "done" if action == "skip" else "dismissed"
    else:
        return PlainTextResponse(f"unknown feedback action {action!r}", status_code=400)
    state.hub.notify(sid)
    return Response(status_code=204)


async def chat_feedback_draft(request: Request) -> Response:
    """Send or discard feedback the assistant drafted (submit_feedback). This
    click is the user's consent: nothing is stored before it."""
    state, (sid, _) = _state(request), _session(request)
    fields = await _fields(request)
    call_id, action = str(fields.get("call_id", "")), str(fields.get("action", ""))
    conv = state.chats.conversation(sid)
    msg = next((m for m in conv.messages if m.tool_call_id == call_id and m.attachment
                and "feedback_draft" in m.attachment), None)  # fmt: skip
    if msg is None:
        return PlainTextResponse("no such draft", status_code=404)
    draft = msg.attachment["feedback_draft"]
    if draft["status"] != "pending":
        return Response(status_code=204)  # already handled (a double click)
    if action == "send":
        draft["id"] = await asyncio.to_thread(
            state.appdb.add_feedback, kind="report", category=draft["category"], summary=draft["summary"],
            comment=draft["details"], session=_pseudonym(sid), dataset=asdict(state.filters.get(sid, Filter())),
            transcript=conv.transcript(), model=state.config.llm.model,
        )  # fmt: skip
        draft["status"] = "sent"
        state.collector.feedback += 1
    elif action == "discard":
        draft["status"] = "discarded"
    else:
        return PlainTextResponse("action is send or discard", status_code=400)
    state.hub.notify(sid)
    return Response(status_code=204)


async def methodology_page(request: Request) -> Response:
    """The same document the assistant is given."""
    state = _state(request)
    region = _render(state, "methodology.html", body=_markdown(prompt.doc("methodology.md")))
    return HTMLResponse(_page(state, region, "Methodology", ""))


_md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")


def _markdown(text: str) -> Markup:
    """Markdown to HTML with raw HTML disabled, so model output can't inject
    markup."""
    return Markup(_md.render(text))


def tool_chip(m: chat.Message) -> dict:
    """What the chat shows for a tool call: a one-line label, plus detail
    (the SQL or search query) the user can expand."""
    try:
        result, args = json.loads(m.content), json.loads(m.arguments or "{}")
    except ValueError:
        result, args = {}, {}
    purpose = args.get("purpose") or ""
    if m.name == "query_data":
        detail = args.get("sql", "")
        if "error" in result:
            return {"label": f"↳ query failed ({purpose}): {result['error'][:160]}", "detail": detail}
        rows = f"{result.get('row_count', 0)} row{'s' * (result.get('row_count') != 1)}"
        return {"label": f"↳ queried: {purpose} · {rows} · {result.get('seconds', 0)}s", "detail": detail}
    if m.name == "submit_feedback":
        return {"label": "", "detail": ""}  # the draft card says it all
    if m.name == "show_chart":
        detail = args.get("sql", "")
        if "error" in result:
            return {"label": f"↳ chart failed ({args.get('title', '')}): {result['error'][:160]}", "detail": detail}
        return {"label": f"↳ charted: {args.get('title', '')} · {result.get('points', 0)} points", "detail": detail}
    if m.name == "search_text":
        detail = args.get("query", "")
        if "error" in result:
            return {"label": f"↳ search failed ({purpose}): {result['error'][:160]}", "detail": detail}
        return {"label": f"↳ searched ticket text: {purpose} · {result.get('matching_tickets', 0):,} matches",
                "detail": detail}  # fmt: skip
    if "error" in result:
        return {"label": f"↳ {m.name} failed: {result['error']}", "detail": ""}
    if m.name == "get_view":
        return {"label": "↳ looked at your view", "detail": ""}
    v = result.get("view", {})

    def part(key: str, prefix: str = "") -> str:
        value = v.get(key, "any")
        if value in ("any", [], None, ""):
            return ""
        return prefix + (", ".join(map(str, value)) if isinstance(value, list) else str(value))

    parts = [part("products"), part("plans"), part("channels"), part("categories"), part("states"),
             part("opened_years", "opened ")]  # fmt: skip
    dataset = " · ".join(p for p in parts if p) or "all tickets"
    return {"label": f"↳ dataset: {dataset} · map: {v.get('map_metric', '').split(' (')[0]}", "detail": ""}


# ---------------------------------------------------------------------------
# Admin: diagnostics, and the numbers load tests are about
# ---------------------------------------------------------------------------


def _admin_ctx(state: State) -> dict:
    sampler = state.sampler
    latest = sampler.latest
    limits = read_limits()
    ctx = {
        "latest": latest,
        "limits": limits,
        "uptime": _duration(time.time() - state.collector.started),
        "interval": sampler.interval,
        "warehouse": state.config.warehouse,
        "manifest": state.warehouse.manifest,
        "by_clients": sampler.by_clients(),
        "feedback": state.appdb.feedback_counts(),
        "usage": _usage_summary(state),
        "tiles": [],
        "meters": [],
    }
    if latest is None:
        return ctx
    history = list(sampler.history)[-60:]
    for m in TILES:
        v = latest.value(m.name)
        th = sampler.thresholds.get(m.name, 0.0)
        ctx["tiles"].append({
            "metric": m,
            "value": display.compact(v),
            "threshold": display.compact(th) if th else "",
            "over": bool(th) and v > th,
            "series": [round(s.value(m.name), 3) for s in history],
        })  # fmt: skip
    mem_limit = limits.cgroup_mem_limit_mb or limits.mem_total_mb
    ctx["meters"] = [
        display.meter("Open files", latest.open_files, limits.open_files_max, "{:,.0f} of {:,.0f}"),
        display.meter("Resident memory" + (" (cgroup limit)" if limits.cgroup_mem_limit_mb else " (host RAM)"),
                      latest.rss_mb, mem_limit, "{:,.0f} of {:,.0f} MB"),
        display.meter("CPU (of one core)", latest.cpu_pct, 100, "{:.0f}% of {:.0f}%"),
    ]  # fmt: skip
    return ctx


async def admin_page(request: Request) -> Response:
    state = _state(request)
    region = _render(state, "admin.html", **_admin_ctx(state))
    return HTMLResponse(_page(state, region, "Diagnostics", "/admin/stream"))


async def admin_stream(request: Request) -> Response:
    state = _state(request)

    async def events() -> AsyncIterator[str]:
        with state.hub.watch(ADMIN) as changed:
            while True:
                yield SSE.patch_elements(_render(state, "admin.html", **_admin_ctx(state)))
                await changed.wait()
                changed.clear()

    return sse(request, events(), state.collector)


async def set_threshold(request: Request) -> Response:
    state = _state(request)
    name = request.path_params["name"]
    if name not in {m.name for m in TILES}:
        return PlainTextResponse("unknown metric", status_code=404)
    form = await request.form()
    try:
        value = float(str(form.get("value", "")).strip() or 0)
    except ValueError:
        return PlainTextResponse("not a number", status_code=400)
    if value > 0:
        state.sampler.thresholds[name] = value
    else:
        state.sampler.thresholds.pop(name, None)
    state.hub.notify(ADMIN)
    return Response(status_code=204)


async def admin_samples(request: Request) -> Response:
    """Recent samples as JSON, for the load tester and for `curl | jq`."""
    state = _state(request)
    since = float(request.query_params.get("since", 0))
    samples = [sample_dict(s) for s in state.sampler.history if s.time > since]
    return JSONResponse({"samples": samples, "by_clients": state.sampler.by_clients()})


async def metrics(request: Request) -> Response:
    state = _state(request)
    state.collector.chat_tokens_today = state.appdb.tokens_today()  # rolls over at midnight
    return PlainTextResponse(prometheus(state.collector, state.sampler.latest), media_type="text/plain; version=0.0.4")


async def healthz(request: Request) -> Response:
    return PlainTextResponse("ok")


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"
