"""The read side: query-shaped views over the Parquet read models.

The server never writes here. It opens the warehouse `build` produced and
reloads when `manifest.json` changes. Every panel on the dashboard is the
same question asked of one dimension: "tickets per value of D, given every
selection except D's". Those queries are memoized on (sql, params), so a
thousand dashboards looking at overlapping datasets mostly cost cache hits.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

import duckdb

from .ingest import MANIFEST, REQUIRED
from .schema import STATES

log = logging.getLogger(__name__)

# Below this many tickets in a state, a rate or an average is mostly noise:
# the map hatches it as "too few" rather than coloring it with confidence.
MIN_TICKETS = 20


@dataclass(frozen=True)
class Metric:
    label: str
    unit: str
    kind: str = "volume"  # "volume": how many tickets; "quality": how they went (an average)
    needs_subset: bool = False  # needs a product / plan / channel / category selection to compare


# What the map colors states by.
METRICS = {
    "count": Metric("Tickets", " tickets"),
    "per_capita": Metric("Per 100k residents", " per 100k residents / yr"),
    "index": Metric("vs. national mix", "× the national share", needs_subset=True),
    "resolution": Metric("Resolution time", " hours to resolve (mean)", kind="quality"),
    "csat": Metric("Satisfaction", " / 5 (mean survey score)", kind="quality"),
    "escalation": Metric("Escalation rate", "% escalated", kind="quality"),
}


@dataclass(frozen=True)
class Dim:
    column: str  # in tickets and the rollups
    label: str
    kind: type  # str or int


# The dataset builder's dimensions. Each is a set in the Filter: empty means
# "any", several values mean "any of these" (OR within a dimension, AND across).
DIMENSIONS = {
    "products": Dim("product", "Products", str),
    "plans": Dim("plan", "Plans", str),
    "channels": Dim("channel", "Channels", str),
    "categories": Dim("category", "Categories", str),
    "states": Dim("state", "States", str),
    "years": Dim("year", "Opened", int),
}


@dataclass(frozen=True)
class Filter:
    """What a dashboard is looking at: the dataset the user has built.
    Hashable (sorted tuples), so it keys the caches."""

    products: tuple[str, ...] = ()
    plans: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    states: tuple[str, ...] = ()  # USPS codes; narrow everything except the map
    years: tuple[int, ...] = ()  # years opened; narrow everything except the year chart
    metric: str = "count"  # what the map colors by

    def where(self, skip: tuple[str, ...] = ()) -> tuple[str, list]:
        """SQL predicate for this dataset, for `tickets` and the rollups alike.
        `skip` leaves dimensions out (each panel ignores its own)."""
        clauses, params = ["true"], []
        for name, dim in DIMENSIONS.items():
            values = getattr(self, name)
            if values and name not in skip:
                clauses.append(f"{dim.column} IN ({', '.join('?' * len(values))})")
                params.extend(values)
        return " AND ".join(clauses), params

    @property
    def subset(self) -> bool:
        """Narrower than "all tickets" in a way the national-mix index can compare."""
        return bool(self.products or self.plans or self.channels or self.categories)

    @property
    def empty(self) -> bool:
        return not any(getattr(self, d) for d in DIMENSIONS)


def _clean(dim: str, values) -> tuple:
    """Validate and normalize one dimension's values into a sorted tuple."""
    if values is None:
        return ()
    if isinstance(values, (str, int)):
        values = [values]
    label = DIMENSIONS[dim].label.lower()
    out = set()
    for v in values:
        if isinstance(v, str) and v.strip().upper() in ("", "ALL", "ANY"):
            continue
        if DIMENSIONS[dim].kind is int:
            try:
                n = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"{label} must be years; got {v!r}") from None
            if not 1990 <= n <= datetime.now(UTC).year + 1:
                raise ValueError(f"{n} is out of range for {label}")
            out.add(n)
        elif dim == "states":
            code = str(v).strip().upper()
            if code not in STATES:
                raise ValueError(f"unknown state {v!r}")
            out.add(code)
        else:  # values match the data exactly; the assistant's tools resolve loose names first
            out.add(str(v).strip()[:80])
    if len(out) > 60:
        raise ValueError(f"at most 60 {label} at once")
    return tuple(sorted(out))


def update_filter(current: Filter, fields: dict) -> Filter:
    """Apply a partial update from any command source (the page's controls or
    the assistant). Dimension fields replace that dimension's set; fields left
    out keep their value. Raises ValueError with a message fit for the user
    (or the model)."""
    changes: dict = {}
    if "metric" in fields:
        metric = str(fields["metric"])
        if metric not in METRICS:
            raise ValueError(f"unknown metric {metric!r}; one of {', '.join(METRICS)}")
        changes["metric"] = metric
    for dim in DIMENSIONS:
        if dim in fields:
            changes[dim] = _clean(dim, fields[dim])
    return replace(current, **changes)


def toggle(current: Filter, dim: str, value) -> Filter:
    """Opt a value in, or back out."""
    [v] = _clean(dim, [value]) or [None]
    if v is None:
        return current
    values = set(getattr(current, dim))
    values ^= {v}
    return replace(current, **{dim: tuple(sorted(values))})


def inline_sql(sql: str, params: list) -> str:
    """Replace each ? with a SQL literal: ints as-is, strings quoted with
    embedded quotes doubled."""
    parts = sql.split("?")
    if len(parts) != len(params) + 1:
        raise ValueError("placeholder count mismatch")
    out = [parts[0]]
    for value, rest in zip(params, parts[1:], strict=True):
        literal = str(int(value)) if isinstance(value, int) else "'" + str(value).replace("'", "''") + "'"
        out += [literal, rest]
    return "".join(out)


def year_range(lo: int, hi: int) -> list[int]:
    lo, hi = sorted((int(lo), int(hi)))
    return list(range(lo, hi + 1))


def describe_years(years: tuple[int, ...]) -> str:
    """(2015, 2016, 2017, 2020) -> '2015–2017, 2020'."""
    runs: list[list[int]] = []
    for y in years:
        if runs and y == runs[-1][-1] + 1:
            runs[-1].append(y)
        else:
            runs.append([y])
    return ", ".join(f"{r[0]}–{r[-1]}" if len(r) > 1 else str(r[0]) for r in runs)


@dataclass
class Totals:
    """Sums over a set of tickets. Sums re-aggregate exactly; averages are
    derived from them at the end."""

    tickets: int = 0
    escalated: int = 0
    resolved: int = 0
    resolution_hours: float = 0.0
    csat_responses: int = 0
    csat_points: int = 0
    refunds_usd: float = 0.0

    def __add__(self, other: Totals) -> Totals:
        return Totals(*(a + b for a, b in zip(vars(self).values(), vars(other).values(), strict=True)))

    @property
    def escalation_pct(self) -> float | None:
        return 100 * self.escalated / self.tickets if self.tickets else None

    @property
    def mean_hours(self) -> float | None:
        return self.resolution_hours / self.resolved if self.resolved else None

    @property
    def mean_csat(self) -> float | None:
        return self.csat_points / self.csat_responses if self.csat_responses else None


@dataclass
class StateValue:
    state: str
    fips: str
    name: str
    tickets: int
    value: float | None  # None: too few tickets to rate


@dataclass
class Dashboard:
    filter: Filter
    totals: Totals
    by_year: list[tuple[int, int]] = field(default_factory=list)  # (year opened, tickets)
    categories: list[tuple[str, int]] = field(default_factory=list)
    products: list[tuple[str, Totals]] = field(default_factory=list)
    states: list[StateValue] = field(default_factory=list)
    metric: str = "count"  # the metric actually drawn (falls back to count if unavailable)


class Warehouse:
    """A DuckDB connection over the read models, reloadable in place.

    Queries run on worker threads (DuckDB releases the GIL), each on its own
    cursor. `on_query` receives the wall time of every uncached query.
    `memory` and `threads` cap DuckDB: by default it sizes itself to the
    machine, not to a container's limits.
    """

    def __init__(
        self,
        root: Path,
        on_query: Callable[[float], None] = lambda _: None,
        cache_size: int = 20_000,
        memory: str | None = None,
        threads: int | None = None,
    ) -> None:
        self.root = root
        self._on_query = on_query
        self._cache_size = cache_size
        self._memory, self._threads = memory, threads
        self._lock = threading.Lock()
        self._con: duckdb.DuckDBPyConnection | None = None
        self.manifest: dict = {}
        self.span: tuple[date, date] | None = None  # first and last day with tickets
        self._manifest_mtime = 0.0
        self._export_slot = threading.BoundedSemaphore(1)
        self._results: OrderedDict[tuple, list[tuple]] = OrderedDict()
        self.dashboard = lru_cache(maxsize=512)(self._dashboard)
        self.options = lru_cache(maxsize=2048)(self._options)

    @property
    def ready(self) -> bool:
        return self._con is not None

    def reload_if_changed(self) -> bool:
        """Reopen the views if a new build landed. True if anything changed.

        A warehouse built by a different recipe (code that expects read models
        the build didn't write) is not an error: it is logged once per
        manifest, the previous views stay up, and the server keeps serving
        until `build` catches up.
        """
        path = self.root / MANIFEST
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return False
        if mtime == self._manifest_mtime:
            return False
        self._manifest_mtime = mtime  # don't retry a broken build every tick
        missing = [name for name in REQUIRED if not (self.root / f"{name}.parquet").exists()]
        if missing:
            log.warning("warehouse at %s lacks %s (built by an older recipe?); run `build`", self.root, missing)
            return False
        con = duckdb.connect()
        con.execute("SET enable_progress_bar = false")
        if self._memory:
            con.execute(f"SET memory_limit = '{self._memory}'")
        if self._threads:
            con.execute(f"SET threads = {int(self._threads)}")
        for name in REQUIRED:
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{self.root / name}.parquet')")
        first, last = con.execute("SELECT min(opened_at)::DATE, max(opened_at)::DATE FROM tickets").fetchone()
        with self._lock:
            old, self._con = self._con, con
            self.manifest = json.loads(path.read_text())
            self.span = (first, last) if first else None
            self.dashboard.cache_clear()
            self.options.cache_clear()
            self._results.clear()
        if old is not None:
            old.close()
        return True

    def _query(self, sql: str, params: list | None = None) -> list[tuple]:
        """Run a read, memoized on (sql, params) until the next build.

        A cache keyed on the whole Filter rarely hits once every user builds
        their own dataset. But one edit changes one dimension, and every
        query that ignores that dimension has the same SQL and params as
        before: those are hits here."""
        key = (sql, tuple(params or ()))
        with self._lock:
            if self._con is None:
                return []
            if (hit := self._results.get(key)) is not None:
                self._results.move_to_end(key)
                return hit
            cur = self._con.cursor()
        started = time.perf_counter()
        try:
            rows = cur.execute(sql, params or []).fetchall()
        finally:
            cur.close()
            self._on_query(time.perf_counter() - started)
        with self._lock:
            self._results[key] = rows
            if len(self._results) > self._cache_size:
                self._results.popitem(last=False)
        return rows

    def measures(self, f: Filter, dim: str) -> dict:
        """Totals per value of `dim`, given every *other* selection. One query
        feeds a picker and its panel: the year chart is the years picker's
        counts, the map is the states picker's."""
        col = DIMENSIONS[dim].column
        where, params = f.where(skip=(dim,))
        rows = self._query(
            f"SELECT {col}, sum(tickets), sum(escalated), sum(resolved), sum(resolution_hours), "
            f"sum(csat_responses), sum(csat_points), sum(refunds_usd) "
            f"FROM tickets_state_year WHERE {where} GROUP BY {col}",
            params,
        )
        return {v: Totals(int(t), int(e), int(r), float(h), int(cn), int(cp), float(rf))
                for v, t, e, r, h, cn, cp, rf in rows}  # fmt: skip

    def counts(self, f: Filter, dim: str) -> dict:
        return {v: t.tickets for v, t in self.measures(f, dim).items()}

    def totals(self, f: Filter) -> Totals:
        """The dataset's totals, from the year chart's query (cached with it):
        its rows ignore the years selection, so keep the selected years."""
        chosen = set(f.years)
        out = Totals()
        for year, t in self.measures(f, "years").items():
            if not chosen or year in chosen:
                out += t
        return out

    def available(self, metric: str, f: Filter) -> bool:
        m = METRICS.get(metric)
        return m is not None and (f.subset or not m.needs_subset)

    @property
    def through_year(self) -> int:
        return self.span[1].year if self.span else 9999

    def years_covered(self, years: tuple[int, ...]) -> float:
        """How many years of data the selection spans, counting partial first
        and last years as the fraction the data covers. Rates divide by it."""
        if not self.span:
            return 0.0
        first, last = self.span
        total = 0.0
        for y in years or range(first.year, last.year + 1):
            lo, hi = max(first, date(y, 1, 1)), min(last, date(y, 12, 31))
            if lo <= hi:
                total += ((hi - lo).days + 1) / (date(y + 1, 1, 1) - date(y, 1, 1)).days
        return total

    def _states(self, f: Filter) -> tuple[str, list[StateValue]]:
        """Per-state values for the map. Ignores the states selection: the map
        is for comparing states, with the selected ones outlined."""
        metric = f.metric if self.available(f.metric, f) else "count"
        by_state = self.measures(f, "states")
        values: dict[str, float | None] = {}
        if metric == "per_capita":
            years = self.years_covered(f.years) or 1.0
            values = {s: 1e5 * t.tickets / STATES[s][2] / years for s, t in by_state.items() if s in STATES}
        elif metric == "index":
            # (the selection's share of its tickets in the state) / (everyone's
            # share there, same years): 1 = the national mix.
            everyone = self.counts(Filter(years=f.years), "states")
            mine_total = sum(t.tickets for t in by_state.values()) or 1
            all_total = sum(everyone.values()) or 1
            for s in STATES:
                expected = everyone.get(s, 0) / all_total * mine_total
                values[s] = by_state[s].tickets / expected if expected and s in by_state else None
        elif metric == "resolution":
            values = {s: t.mean_hours for s, t in by_state.items()}
        elif metric == "csat":
            values = {s: t.mean_csat for s, t in by_state.items()}
        elif metric == "escalation":
            values = {s: t.escalation_pct for s, t in by_state.items()}
        out = []
        for code, (fips, name, _) in STATES.items():
            n = by_state[code].tickets if code in by_state else 0
            value = float(n) if metric == "count" else values.get(code)
            if metric != "count" and n < MIN_TICKETS:
                value = None  # too few tickets to rate
            out.append(StateValue(code, fips, name, n, value))
        return metric, out

    def export(self, f: Filter, fmt: str) -> str:
        """Write the dataset's tickets to a temp file (CSV or Parquet) and
        return its path; the caller deletes it. One at a time: an export of
        everything is every ticket with its text."""
        if self._con is None:
            raise RuntimeError("the warehouse isn't loaded yet")
        if not self._export_slot.acquire(timeout=30):
            raise RuntimeError("another export is running; try again in a minute")
        try:
            where, params = f.where()
            fd, path = tempfile.mkstemp(prefix="export-", suffix=f".{fmt}")
            os.close(fd)
            options = "FORMAT csv, HEADER true" if fmt == "csv" else "FORMAT parquet, COMPRESSION zstd"
            with self._lock:
                cur = self._con.cursor()
            try:
                # COPY takes no bound parameters, so the (already validated)
                # values are inlined as escaped SQL literals.
                sql = f"SELECT * FROM tickets WHERE {inline_sql(where, params)} ORDER BY opened_at"
                cur.execute(f"COPY ({sql}) TO '{path}' ({options})")
            finally:
                cur.close()
            return path
        finally:
            self._export_slot.release()

    def find_values(self, dim: str, query: str, limit: int = 8) -> list[tuple[str, int]]:
        """Values of a text dimension containing `query`, most tickets first."""
        col = DIMENSIONS[dim].column
        return self._query(
            f"SELECT {col}, sum(tickets) n FROM tickets_state_year WHERE {col} ILIKE ? "
            f"GROUP BY {col} ORDER BY n DESC LIMIT ?",
            [f"%{query.strip()}%", limit],
        )

    def _options(self, f: Filter, dim: str, query: str = "", limit: int = 40) -> list[tuple]:
        """A picker's choices: values of `dim` with their ticket counts given
        every *other* selection (faceted counts), best first. Years are listed
        newest first. `query` filters by substring."""
        items = [(v, n) for v, n in self.counts(f, dim).items() if v is not None]
        if query:  # in Python: the counts are already here
            q = query.strip().lower()
            items = [(v, n) for v, n in items if q in str(v).lower()]
        key = (lambda vn: -vn[0]) if DIMENSIONS[dim].kind is int else (lambda vn: -vn[1])
        return sorted(items, key=key)[:limit]

    def _dashboard(self, f: Filter) -> Dashboard:
        # Every panel is one dimension's measures, ignoring that dimension's
        # own selection, then narrowed to it where the panel is a breakdown.
        totals = self.totals(f)
        # Every year, whatever the years selection: the chart is where you
        # choose them (by dragging), with the selection highlighted.
        by_year = sorted((y, n) for y, n in self.counts(f, "years").items() if y is not None)
        categories = sorted(
            ((c, n) for c, n in self.counts(f, "categories").items() if not f.categories or c in f.categories),
            key=lambda cn: -cn[1],
        )
        products = sorted(
            ((p, t) for p, t in self.measures(f, "products").items() if not f.products or p in f.products),
            key=lambda pt: -pt[1].tickets,
        )
        metric, states = self._states(f)
        return Dashboard(f, totals, by_year, categories, products, states, metric)
