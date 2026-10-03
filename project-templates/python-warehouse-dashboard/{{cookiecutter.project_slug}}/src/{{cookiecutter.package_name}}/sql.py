"""A read-only SQL sandbox over the warehouse, for the assistant's
`query_data` and `show_chart` tools.

Model-written SQL runs on its own DuckDB database instance, never on the
dashboard's connection, locked down before any query runs:

- file access only inside the warehouse directory (`allowed_directories` +
  `enable_external_access = false`), then `lock_configuration`, so SQL can't
  undo any of it
- exactly one statement, and it must be a SELECT (WITH ... SELECT included)
- 2 threads, a memory cap, at most 2 queries at once, and a timeout that
  interrupts the query
- at most MAX_ROWS rows back, long strings (ticket text) cut short

Every Parquet file in the warehouse is a view named after it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import decimal
import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import duckdb

MAX_ROWS = 200
MAX_CELL = 400  # characters per string value
MAX_RESULT_CHARS = 24_000  # the whole JSON result, so one query can't flood the context


@dataclass
class Limits:
    timeout: float = 20.0
    threads: int = 2
    memory: str = "1GB"
    concurrent: int = 2


class QueryError(Exception):
    pass


class SqlSandbox:
    def __init__(self, root: Path, limits: Limits | None = None, on_query=lambda seconds, ok: None) -> None:
        self.root = root.resolve()
        self.limits = limits or Limits()
        self.on_query = on_query
        self._slots = threading.BoundedSemaphore(self.limits.concurrent)
        self._lock = threading.Lock()
        self._con: duckdb.DuckDBPyConnection | None = None
        self._built_at: str | None = None
        self.tables: dict[str, list[tuple[str, str]]] = {}  # view -> [(column, type)]
        self.row_counts: dict[str, int] = {}

    def ensure(self, built_at: str) -> None:
        """(Re)open over the current build. Cheap when nothing changed."""
        with self._lock:
            if self._con is not None and built_at == self._built_at:
                return
            con = duckdb.connect()  # its own database instance: settings below are global to it
            tables, counts = {}, {}
            for f in sorted(self.root.glob("*.parquet")):
                con.execute(f"CREATE VIEW {f.stem} AS SELECT * FROM read_parquet('{f}')")
                tables[f.stem] = [(r[0], r[1]) for r in con.execute(f"DESCRIBE {f.stem}").fetchall()]
                counts[f.stem] = con.execute(f"SELECT count(*) FROM {f.stem}").fetchone()[0]
            lim = self.limits
            con.execute(f"SET allowed_directories = ['{self.root}/']")
            con.execute("SET enable_external_access = false")
            con.execute(f"SET threads = {int(lim.threads)}")
            con.execute(f"SET memory_limit = '{lim.memory}'")
            con.execute("SET enable_progress_bar = false")
            con.execute("SET lock_configuration = true")
            old, self._con, self._built_at = self._con, con, built_at
            self.tables, self.row_counts = tables, counts
        if old is not None:
            old.close()

    def run(self, sql: str, max_rows: int = MAX_ROWS, for_model: bool = True) -> dict:
        """Run one SELECT. Returns columns/rows, or raises QueryError with a
        message meant for the model to read and fix its query.

        Results the model will read are capped (rows and total size) so one
        query can't flood its context. Chart data goes to the page instead
        (for_model=False) and only needs the row cap."""
        if self._con is None:
            raise QueryError("the warehouse isn't loaded yet")
        sql = sql.strip().rstrip(";")
        try:
            statements = self._con.extract_statements(sql)
        except duckdb.Error as e:
            raise QueryError(_first_line(e)) from None
        if len(statements) != 1:
            raise QueryError("send exactly one statement")
        if statements[0].type != duckdb.StatementType.SELECT:
            raise QueryError(f"only SELECT queries are allowed, not {statements[0].type.name}")
        if not self._slots.acquire(timeout=self.limits.timeout):
            raise QueryError("the query sandbox is busy; try again in a moment")
        started = time.perf_counter()
        ok = False
        try:
            cur = self._con.cursor()
            timer = threading.Timer(self.limits.timeout, cur.interrupt)
            timer.start()
            try:
                cur.execute(sql)
                columns = [d[0] for d in cur.description or []]
                rows = cur.fetchmany(max_rows + 1)
            except duckdb.InterruptException:
                raise QueryError(
                    f"timed out after {self.limits.timeout:.0f}s; narrow it (filters, rollup tables, LIMIT)"
                ) from None
            except duckdb.Error as e:
                raise QueryError(_first_line(e)) from None
            finally:
                timer.cancel()
                cur.close()
            ok = True
        finally:
            self._slots.release()
            self.on_query(time.perf_counter() - started, ok)
        truncated = len(rows) > max_rows
        out = {
            "columns": columns,
            "rows": [[_cell(v) for v in r] for r in rows[:max_rows]],
            "row_count": min(len(rows), max_rows),
            "truncated": truncated,
            "seconds": round(time.perf_counter() - started, 2),
        }
        # Keep one result from swamping the conversation.
        while for_model and len(json.dumps(out, default=str)) > MAX_RESULT_CHARS and len(out["rows"]) > 5:
            out["rows"] = out["rows"][: len(out["rows"]) // 2]
            out["row_count"], out["truncated"] = len(out["rows"]), True
        if out["truncated"]:
            out["note"] = "rows were cut; aggregate or add a LIMIT to see everything that matters"
        return out

    @contextlib.contextmanager
    def session(self) -> Iterator[Callable[[str, list | None], list[tuple]]]:
        """A cursor for trusted SQL written by our own code (the search tool's
        aggregations), on the same locked-down database. Temp tables made in it
        vanish when it closes. Not for model SQL."""
        if self._con is None:
            raise QueryError("the warehouse isn't loaded yet")
        cur = self._con.cursor()

        def query(sql: str, params: list | None = None) -> list[tuple]:
            return [tuple(_cell(v) for v in row) for row in cur.execute(sql, params or []).fetchall()]

        try:
            yield query
        finally:
            cur.close()

    def query(self, sql: str, params: list | None = None) -> list[tuple]:
        """One trusted query (see `session`)."""
        with self.session() as q:
            return q(sql, params)


def _cell(v):
    if isinstance(v, str):
        return v if len(v) <= MAX_CELL else v[:MAX_CELL] + "…"
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, float):
        return round(v, 6)
    return v


def _first_line(e: Exception) -> str:
    lines = [ln for ln in str(e).splitlines() if ln.strip()]
    return " ".join(lines[:3])[:400]
