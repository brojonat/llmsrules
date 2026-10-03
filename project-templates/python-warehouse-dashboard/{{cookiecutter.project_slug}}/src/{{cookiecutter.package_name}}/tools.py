"""Tools the assistant uses to see and drive a session's dashboard.

A tool call is just another source of the commands the page's controls send:
`set_view` goes through the same `update_filter` as `POST /filter`, stores the
session's filter, and wakes its page streams, so the dashboard re-renders on
the stream the browser already holds. The browser never knows whether a
person or the model changed the view.

Tools answer with compact JSON: the view as it now stands, plus the numbers the
dashboard shows for it. That way the model can talk about the result instead
of guessing.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

from .schema import STATES
from .search import SearchError, TextIndex
from .sql import MAX_ROWS, QueryError, SqlSandbox
from .warehouse import METRICS, Filter, Warehouse, describe_years, inline_sql, update_filter, year_range

CLEAR = {"", "ALL", "ANY", "NONE", "*"}

# set_view argument -> Filter dimension, for the dimensions matched by name.
TEXT_ARGS = {"products": "products", "plans": "plans", "channels": "channels", "categories": "categories"}


def _names(description: str) -> dict:
    return {"type": "array", "items": {"type": "string"}, "description": description}


SPECS = [
    {
        "type": "function",
        "function": {
            "name": "set_view",
            "description": (
                "Change the dataset the user's dashboard shows. Each dimension is a set: empty = any, several "
                "values = any of them (OR within a dimension, AND across). Pass only what should change; with "
                "mode 'replace' (default) a list you pass replaces that dimension's set, 'add' opts values in, "
                "'remove' opts them out. Returns the resulting view and its key numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["replace", "add", "remove"],
                             "description": "How list fields apply. Default replace."},
                    "products": _names("Products, matched loosely ('ledger'). [] or ['all'] = any product."),
                    "plans": _names("Plans, matched loosely ('enterprise')."),
                    "channels": _names("Channels, matched loosely ('phone')."),
                    "categories": _names("Ticket categories, matched loosely ('billing', 'data loss')."),
                    "states": _names("US states by name or USPS code. Filter every panel except the map."),
                    "opened_years": {"type": "array", "items": {"type": "integer"},
                                     "description": "Years tickets were opened (any set, e.g. [2021, 2024])."},
                    "opened_from": {"type": "integer",
                                    "description": "With opened_to: every year opened in a range."},
                    "opened_to": {"type": "integer", "description": "End of the opened-year range (inclusive)."},
                    "map_metric": {
                        "type": "string",
                        "enum": list(METRICS),
                        "description": "What colors the map: "
                        + "; ".join(f"{k} = {m.label}" for k, m in METRICS.items())
                        + ". 'index' needs products, plans, channels or categories selected.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_view",
            "description": "What the user's dashboard shows right now, with the same key numbers set_view returns.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_data",
            "description": (
                "Run one read-only DuckDB SELECT over the warehouse tables described in the system prompt. "
                f"Returns at most {MAX_ROWS} rows; long text is cut. Aggregate in SQL rather than fetching rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string",
                            "description": "A single SELECT (WITH ... SELECT is fine), DuckDB dialect."},
                    "purpose": {"type": "string", "description": "A few words shown to the user describing what "
                                "this query finds, e.g. 'Ledger billing tickets per month in 2024'."},
                },
                "required": ["sql", "purpose"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": (
                "Full-text search of what customers wrote (ticket subjects and bodies). Returns how many tickets "
                "match, broken down by year, product, category and state, plus a few recent excerpts. Optional "
                "filters narrow the matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQLite FTS5 query, stemmed (charge matches charged). "
                              "Phrases in double quotes; AND / OR / NOT (upper case); NEAR(a b, 5); prefix*. "
                              "E.g. '\"double charged\"', 'sync AND missing', 'refund OR chargeback'."},
                    "purpose": {"type": "string", "description": "A few words shown to the user."},
                    "product": {"type": "string", "description": "Exact product name (optional)."},
                    "state": {"type": "string", "description": "USPS code, e.g. 'OR' (optional)."},
                    "since": {"type": "integer", "description": "First year opened (optional)."},
                },
                "required": ["query", "purpose"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_chart",
            "description": (
                "Draw a chart in the chat from a SQL query's result. The server runs the SQL (same rules as "
                "query_data) and plots exactly what it returns, so charts always show real data. Result shape: "
                "(x, y) for one series, or (x, series, y) for up to 4 series in long format. "
                "kind 'bar': x = years, months or categories (≤ 240 bars). 'hbar': x = category labels, a ranking "
                "(≤ 100 rows, order by y desc). 'line': x = years or months, 1–4 series (≤ 500 points each). "
                "facet=true draws one small panel per value of an extra FIRST column (≤ 16 panels)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["bar", "hbar", "line"]},
                    "title": {"type": "string", "description": "Short chart title, e.g. 'Tickets per year'."},
                    "sql": {"type": "string", "description": "One SELECT returning (x, y) or (x, series, y)."},
                    "unit": {"type": "string", "description": "Unit for values in tooltips, e.g. 'tickets', 'h'."},
                    "facet": {"type": "boolean", "description": "Small multiples: the SQL's FIRST column names the "
                              "panel, so the shape is (facet, x, y) or (facet, x, series, y). At most 16 panels."},
                    "shared_y": {"type": "boolean", "description": "Facets share one y scale (default true: compare "
                                 "sizes). false: each panel scales to its own data (compare shapes)."},
                },
                "required": ["kind", "title", "sql"],
                "additionalProperties": False,
            },
        },
    },
]  # fmt: skip

FEEDBACK_CATEGORIES = ["bug", "data_quality", "feature_request", "praise", "other"]

SPECS.append({
    "type": "function",
    "function": {
        "name": "submit_feedback",
        "description": (
            "Draft feedback for the people who run this site, when the user wants to report something: a bug, a "
            "number that looks wrong, a missing feature, praise. It does NOT send anything: the user sees the draft "
            "in the chat and clicks Send (or Discard). Write it in the user's voice and keep their specifics."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": FEEDBACK_CATEGORIES},
                "summary": {"type": "string", "description": "One line, e.g. 'Escalation map looks wrong for Texas'."},
                "details": {"type": "string",
                            "description": "What happened or what they want, with the specifics (products, years, "
                            "numbers, what they expected). A few sentences."},
            },
            "required": ["category", "summary", "details"],
            "additionalProperties": False,
        },
    },
})  # fmt: skip

# (points per series, series). Generous: they guard the page, not taste. The
# line limit of 4 series is about telling colors apart, not size.
CHART_LIMITS = {"bar": (240, 1), "hbar": (100, 1), "line": (500, 4)}
MAX_FACETS = 16
MAX_CHART_POINTS = 5000


class ViewTools:
    """Implements chat.Tools: the dashboard's per-session filters, plus
    read-only SQL and full-text search over the warehouse."""

    def __init__(
        self,
        warehouse: Warehouse,
        filters: dict[str, Filter],
        notify: Callable[[str], None],
        sandbox: SqlSandbox | None = None,
        text: TextIndex | None = None,
    ) -> None:
        self.warehouse = warehouse
        self.filters = filters
        self.notify = notify
        self.sandbox = sandbox
        self.text = text

    def specs(self) -> list[dict]:
        return SPECS

    async def call(self, sid: str, name: str, args: dict) -> dict:
        if name == "get_view":
            return await self.summary(self.filters.get(sid, Filter()))
        if name == "set_view":
            return await self.set_view(sid, args)
        if name == "query_data":
            return await self.query_data(str(args.get("sql", "")))
        if name == "search_text":
            return await self.search_text(args)
        if name == "show_chart":
            return await self.show_chart(args)
        if name == "submit_feedback":
            return self.draft_feedback(args)
        return {"error": f"unknown tool {name!r}"}

    async def set_view(self, sid: str, args: dict) -> dict:
        current = self.filters.get(sid, Filter())
        mode = str(args.get("mode") or "replace")
        if mode not in ("replace", "add", "remove"):
            return {"error": "mode must be replace, add or remove"}
        fields: dict = {}
        if "map_metric" in args:
            fields["metric"] = args["map_metric"]
        wanted: dict[str, list] = {}
        for arg, dim in [*TEXT_ARGS.items(), ("states", "states"), ("opened_years", "years")]:
            if arg in args:
                wanted[dim] = args[arg] if isinstance(args[arg], list) else [args[arg]]
        if "opened_from" in args or "opened_to" in args:
            first = self.warehouse.span[0].year if self.warehouse.span else 1990
            wanted["years"] = year_range(args.get("opened_from") or first,
                                         args.get("opened_to") or self.warehouse.through_year)  # fmt: skip
        # Names people say -> values in the data.
        for dim in TEXT_ARGS.values():
            if dim in wanted:
                resolved = []
                for v in wanted[dim]:
                    if str(v).strip().upper() in CLEAR:
                        continue
                    value, error = await asyncio.to_thread(self.resolve, dim, str(v))
                    if error:
                        return error
                    resolved.append(value)
                wanted[dim] = resolved
        if "states" in wanted:
            codes = []
            for v in wanted["states"]:
                code = _resolve_state(str(v))
                if code is None:
                    return {"error": f"unknown state {v!r}; use a US state name or USPS code"}
                if code:
                    codes.append(code)
            wanted["states"] = codes
        for dim, values in wanted.items():
            have = set(getattr(current, dim))
            if mode == "add":
                values = [*have, *values]
            elif mode == "remove":
                values = [v for v in have if v not in set(values) and str(v) not in {str(x) for x in values}]
            fields[dim] = values
        try:
            new = update_filter(current, fields)
        except ValueError as e:
            return {"error": str(e)}
        if new.metric != current.metric and not self.warehouse.available(new.metric, new):
            return {"error": f"map metric {new.metric!r} needs products, plans, channels or categories selected"}
        self.filters[sid] = new
        self.notify(sid)
        return await self.summary(new)

    def resolve(self, dim: str, query: str) -> tuple[str, dict | None]:
        """A loose name ('enterprise', 'how to', 'data-loss') -> the value in
        the data. Exact (ignoring case and punctuation) wins; otherwise the
        only candidate, or one with 5× the tickets of the runner-up. Anything
        else goes back to the model as candidates to ask about."""
        counts = sorted(self.warehouse.counts(Filter(), dim).items(), key=lambda vn: -vn[1])
        q = _norm(query)
        exact = [v for v, _ in counts if _norm(v) == q]
        if exact:
            return exact[0], None
        found = [(v, n) for v, n in counts if q and q in _norm(v)]
        label = dim.rstrip("s")
        if not found:
            return "", {"error": f"no {label} matches {query!r}", "values": [v for v, _ in counts][:40]}
        (best, n1), n2 = found[0], found[1][1] if len(found) > 1 else 0
        if len(found) == 1 or n1 >= 5 * max(n2, 1):
            return best, None
        return "", {
            "error": f"{query!r} matches several values of {label}; ask which, or pass several",
            "candidates": [{label: v, "tickets": n} for v, n in found[:10]],
        }

    async def summary(self, f: Filter) -> dict:
        """The view and the numbers the dashboard shows for it."""
        wh = self.warehouse
        if not wh.ready:
            return {"error": "the data warehouse isn't loaded yet"}
        board = await asyncio.to_thread(wh.dashboard, f)
        m = METRICS[board.metric]
        rated = sorted((s for s in board.states if s.value is not None), key=lambda s: s.value, reverse=True)
        by_year = dict(board.by_year)
        years = sorted(by_year)
        t = board.totals

        def rounded(v: float | None, places: int = 1) -> float | None:
            return None if v is None else round(v, places)

        return {
            "view": {
                "products": list(f.products) or "any",
                "plans": list(f.plans) or "any",
                "channels": list(f.channels) or "any",
                "categories": list(f.categories) or "any",
                "states": list(f.states) or "any",
                "opened_years": describe_years(f.years) or "any",
                "map_metric": f"{board.metric} ({m.label})",
            },
            "data_through": wh.manifest.get("data_through"),
            # The dataset as SQL, built by the same code as the dashboard's own
            # queries: use it verbatim so answers match what's on screen. It
            # works on `tickets` and on the rollups alike.
            "sql_filter": inline_sql(*f.where()),
            "totals": {
                "tickets": t.tickets,
                "escalated": t.escalated,
                "escalation_pct": rounded(t.escalation_pct),
                "open": t.tickets - t.resolved,
                "mean_resolution_hours": rounded(t.mean_hours),
                "mean_satisfaction": rounded(t.mean_csat, 2),
                "survey_responses": t.csat_responses,
                "refunds_usd": round(t.refunds_usd, 2),
            },
            # Recent years in full, earlier ones summarized: enough to talk about a trend.
            "tickets_per_year_recent": {y: by_year[y] for y in years[-6:]},
            "tickets_before_that": sum(by_year[y] for y in years[:-6]),
            "top_categories": [{"category": c, "tickets": n} for c, n in board.categories[:6]],
            "products": [
                {"product": p, "tickets": pt.tickets, "escalation_pct": rounded(pt.escalation_pct),
                 "mean_resolution_hours": rounded(pt.mean_hours), "mean_satisfaction": rounded(pt.mean_csat, 2)}
                for p, pt in board.products[:8]
            ],
            "map": {
                "metric": m.label,
                "unit": m.unit.strip(),
                "highest": [{"state": s.name, "value": round(s.value, 3), "tickets": s.tickets} for s in rated[:5]],
                "lowest": [{"state": s.name, "value": round(s.value, 3), "tickets": s.tickets} for s in rated[-3:]],
                "unrated_states": len(board.states) - len(rated),
            },
        }  # fmt: skip

    async def show_chart(self, args: dict) -> dict:
        """Run the SQL, shape its rows into one chart or a grid of facets, and
        attach it to the chat message. The model gets a summary, not the data."""
        kind = str(args.get("kind", ""))
        if kind not in CHART_LIMITS:
            return {"error": f"kind must be one of {', '.join(CHART_LIMITS)}"}
        # Chart rows go to the page, not the model: only the row cap applies.
        sql = str(args.get("sql", ""))
        try:
            result = await asyncio.to_thread(
                lambda: self._sandbox().run(sql, max_rows=MAX_CHART_POINTS, for_model=False)
            )
        except QueryError as e:
            return {"error": str(e)}
        facet = bool(args.get("facet"))
        try:
            panels = _chart_panels(result["columns"], result["rows"], kind, facet)
        except ValueError as e:
            return {"error": f"can't chart that result: {e}"}
        title = str(args.get("title") or "")
        points = [p for panel in panels for s in panel["series"] for p in s["points"]]
        xs, ys = [p[0] for p in points], [p[1] for p in points if p[1] is not None]
        years = bool(xs) and all(isinstance(x, int) and 1900 < x < 2200 for x in xs)
        through = self.warehouse.through_year
        chart = {
            "kind": kind,
            "title": title,
            "unit": str(args.get("unit") or ""),
            "panels": panels,
            "faceted": facet,
            "highlight": str(through) if years and through in xs else "",
            # Facets compare on one y scale unless asked not to, and share an x range.
            "y_max": max(ys) if facet and ys and args.get("shared_y", True) else 0,
            "x_range": [min(xs), max(xs)] if facet and years else None,
            "legend": _legend(panels) if kind == "line" else [],
            "table": _chart_table(result["columns"], panels, facet),
        }
        summary = {
            "shown": f"{kind} chart '{title}'" + (f", {len(panels)} facets" if facet else ""),
            "facets": [p["name"] for p in panels] if facet else None,
            "series": [name for name, _ in chart["legend"]] or None,
            "points": len(points),
            "partial_x": chart["highlight"] or None,
            # What the model may say about the chart comes from here: it can't
            # see the picture. Stats for every panel and series, always; the
            # full table when it's small.
            "stats": _chart_stats(panels),
        }
        if len(points) <= 60:
            summary["data"] = chart["table"]
        return {**{k: v for k, v in summary.items() if v is not None}, "__attachment__": {"chart": chart}}

    def draft_feedback(self, args: dict) -> dict:
        """A draft the user confirms in the chat; nothing is stored until they
        click Send (a command handled by the web layer)."""
        category = str(args.get("category") or "other")
        if category not in FEEDBACK_CATEGORIES:
            category = "other"
        summary = str(args.get("summary") or "").strip()[:200]
        details = str(args.get("details") or "").strip()[:4000]
        if not summary:
            return {"error": "a feedback draft needs a summary"}
        draft = {"category": category, "summary": summary, "details": details, "status": "pending"}
        return {
            "status": "drafted: the user sees it in the chat and must click Send; it has NOT been sent",
            "__attachment__": {"feedback_draft": draft},
        }

    def _sandbox(self) -> SqlSandbox:
        if self.sandbox is None:
            raise QueryError("querying is disabled on this server")
        self.sandbox.ensure(self.warehouse.manifest.get("built_at", ""))
        return self.sandbox

    async def query_data(self, sql: str) -> dict:
        try:
            return await asyncio.to_thread(lambda: self._sandbox().run(sql))
        except QueryError as e:
            return {"error": str(e)}

    async def search_text(self, args: dict) -> dict:
        if self.text is None:
            return {"error": "text search is disabled on this server"}
        query = str(args.get("query", "")).strip()
        try:
            ids = await asyncio.to_thread(self.text.match, query)
            return await asyncio.to_thread(self._summarize_matches, query, ids, args)
        except (SearchError, QueryError) as e:
            return {"error": str(e)}

    def _summarize_matches(self, query: str, ids: list[int], args: dict) -> dict:
        """Aggregate FTS matches in DuckDB: counts by year, product, category
        and state, and a few recent excerpts."""
        where, params = ["true"], []
        if product := str(args.get("product") or "").strip():
            where.append("product = ?")
            params.append(product)
        if state := str(args.get("state") or "").strip().upper():
            where.append("state = ?")
            params.append(state)
        if args.get("since"):
            where.append("year >= ?")
            params.append(int(args["since"]))
        # Matches become a temp table, joined below. Binding a 30K-element list
        # parameter costs seconds per query; one comma-joined string split in
        # DuckDB costs milliseconds, once.
        src = f"(SELECT * FROM tickets SEMI JOIN matches USING (ticket_id) WHERE {' AND '.join(where)})"
        with self._sandbox().session() as q:
            q("CREATE TEMP TABLE matches AS SELECT unnest(string_split(?, ','))::BIGINT AS ticket_id",
              [",".join(map(str, ids))])  # fmt: skip

            def top(col: str, n: int = 8) -> list:
                rows = q(f"SELECT {col} AS k, count(*) AS c FROM {src} WHERE k IS NOT NULL "
                         f"GROUP BY k ORDER BY c DESC LIMIT {n}", params)  # fmt: skip
                return [{"name": k, "tickets": c} for k, c in rows]

            [(total,)] = q(f"SELECT count(*) FROM {src}", params)
            by_year = dict(q(f"SELECT year, count(*) FROM {src} GROUP BY year ORDER BY year", params))
            breakdown = {"top_products": top("product"), "top_categories": top("category"),
                         "top_states": top("state", 6)}  # fmt: skip
            samples = q(
                f"SELECT ticket_id, opened_at, product, category, state, subject, body FROM {src} "
                "ORDER BY opened_at DESC LIMIT 5",
                params,
            )
        return {
            "query": query,
            "matching_tickets": total,
            "matches_before_filters": len(ids),
            "by_year": by_year,
            **breakdown,
            "recent_excerpts": [
                {"ticket_id": i, "opened": str(o)[:10], "product": p, "category": c, "state": s, "subject": subj,
                 "excerpt": _excerpt(body or "", query)}
                for i, o, p, c, s, subj, body in samples
            ],
        }  # fmt: skip


def _chart_panels(columns: list[str], rows: list[list], kind: str, facet: bool) -> list[dict]:
    """Rows -> [{name, series}], one panel per facet (or a single unnamed
    panel). With facet, the first column names the panel."""
    if not rows:
        raise ValueError("the query returned no rows")
    if len(rows) > MAX_CHART_POINTS:
        raise ValueError(f"{len(rows)} rows; charts take at most {MAX_CHART_POINTS}. Aggregate or LIMIT")
    if not facet:
        return [{"name": "", "series": _chart_series(columns, rows, kind)}]
    groups: dict = {}
    for row in rows:
        groups.setdefault(str(row[0]), []).append(row[1:])
    if len(groups) > MAX_FACETS:
        raise ValueError(f"{len(groups)} facets; at most {MAX_FACETS}. Filter to the ones that matter")
    panels = [{"name": name, "series": _chart_series(columns[1:], rs, kind, fill=False)} for name, rs in groups.items()]
    if kind == "line":  # one legend for the grid, so at most 4 series across all panels
        names = list(dict.fromkeys(s["name"] for p in panels for s in p["series"]))
        if len(names) > 4:
            raise ValueError(f"{len(names)} series across facets; line charts take at most 4")
    if kind == "bar":  # every panel over the same years, so they line up
        xs = [pt[0] for p in panels for s in p["series"] for pt in s["points"]]
        if xs and all(isinstance(x, int) and 1900 < x < 2200 for x in xs):
            for p in panels:
                p["series"] = [_fill_years(s, min(xs), max(xs)) for s in p["series"]]
    return panels


def _chart_series(columns: list[str], rows: list[list], kind: str, fill: bool = True) -> list[dict]:
    """(x, y) or (x, series, y) rows -> [{name, points: [[x, y], ...]}]."""
    max_points, max_series = CHART_LIMITS[kind]
    if not rows:
        raise ValueError("the query returned no rows")
    if len(columns) == 2:
        groups = {"": [(r[0], r[1]) for r in rows]}
    elif len(columns) == 3:
        groups: dict = {}
        for x, name, y in rows:
            groups.setdefault(str(name), []).append((x, y))
    else:
        raise ValueError(
            f"return 2 columns (x, y) or 3 (x, series, y), plus the facet column first when faceting; got {columns}"
        )
    if len(groups) > max_series:
        raise ValueError(f"{len(groups)} series; {kind} charts take at most {max_series}. Filter, or fold into 'Other'")
    series = []
    for name, points in groups.items():
        if len(points) > max_points:
            raise ValueError(f"{len(points)} points; {kind} charts take at most {max_points}. Aggregate or LIMIT")
        clean = []
        for x, y in points:
            if y is not None and not isinstance(y, (int, float)):
                raise ValueError(f"y must be numeric; got {y!r} (is the column order [facet,] x, [series,] y?)")
            clean.append([x if isinstance(x, (int, float)) else str(x), y])
        series.append({"name": name, "points": clean})
    if kind == "bar" and fill:
        series = [_fill_years(s) for s in series]
    return series


def _chart_stats(panels: list[dict]) -> list[dict]:
    """Per panel and series: first, last, min and max (as [x, y]), the total,
    and the top five when there are more. Enough to describe a trend, a peak
    or the head of a ranking without the whole table."""
    out = []
    for p in panels:
        for s in p["series"]:
            pts = [pt for pt in s["points"] if pt[1] is not None]
            if not pts:
                continue
            row = {"facet": p["name"] or None, "series": s["name"] or None,
                   "first": pts[0], "last": pts[-1],
                   "min": min(pts, key=lambda pt: pt[1]), "max": max(pts, key=lambda pt: pt[1]),
                   "total": round(sum(pt[1] for pt in pts), 3),
                   "top": sorted(pts, key=lambda pt: pt[1], reverse=True)[:5] if len(pts) > 5 else None}  # fmt: skip
            out.append({k: v for k, v in row.items() if v is not None})
    return out


def _legend(panels: list[dict]) -> list[tuple[str, int]]:
    """Series names in first-seen order with a fixed color slot, stamped onto
    each series as `c` so a series keeps its color in every facet."""
    slots = {name: i for i, name in enumerate(dict.fromkeys(s["name"] for p in panels for s in p["series"]))}
    for p in panels:
        for s in p["series"]:
            s["c"] = slots[s["name"]]
    return [(name, i) for name, i in slots.items() if name]


def _fill_years(s: dict, lo: int | None = None, hi: int | None = None) -> dict:
    """Bars sit on an ordinal axis, which silently closes gaps (2019 next to
    2022). Fill missing years with null: an empty slot, not a zero, since
    for a rate 'no data' isn't 0."""
    xs = [p[0] for p in s["points"]]
    if not xs or not all(isinstance(x, int) and 1900 < x < 2200 for x in xs):
        return s
    have = dict((x, y) for x, y in s["points"])
    lo, hi = min(xs) if lo is None else lo, max(xs) if hi is None else hi
    return {**s, "points": [[y, have.get(y)] for y in range(lo, hi + 1)]}


def _chart_table(columns: list[str], panels: list[dict], facet: bool = False) -> dict:
    """The chart's data as a wide table ([facet,] x, then one column per
    series), for the collapsible table under every chart."""
    names = list(dict.fromkeys(s["name"] for p in panels for s in p["series"]))
    xcol = columns[1] if facet else columns[0]
    header = ([columns[0]] if facet else []) + [xcol] + [n or columns[-1] for n in names]
    rows = []
    for p in panels:
        lookup = {s["name"]: {pt[0]: pt[1] for pt in s["points"]} for s in p["series"]}
        for x in dict.fromkeys(pt[0] for s in p["series"] for pt in s["points"]):
            rows.append(([p["name"]] if facet else []) + [x] + [lookup.get(n, {}).get(x) for n in names])
    return {"header": header, "rows": rows}


def _excerpt(text: str, query: str, width: int = 160) -> str:
    """The text around the first word of the query that appears in it."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query) if w.upper() not in {"AND", "OR", "NOT", "NEAR"}]
    low = text.lower()
    hits = [i for w in words if (i := low.find(w.lower()[:5])) >= 0]
    at = min(hits) if hits else 0
    start = max(0, at - width // 2)
    snippet = text[start : start + width].strip()
    return ("…" if start else "") + snippet + ("…" if start + width < len(text) else "")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _resolve_state(value: str) -> str | None:
    v = value.strip().upper()
    if v in CLEAR:
        return ""
    if v in STATES:
        return v
    for code, (_, name, _) in STATES.items():
        if name.upper() == v:
            return code
    return None
