"""Feed the belt from a data file: a cursor moves through it, a batch at a time.

A run (`runs`) is one pass through a file: its size and its labels (coords_for
over the whole file, so every fit in the run shares one set). `feed` sends the
rows after the cursor as batches, and the sampler fits each batch on every row
fed in the run so far. So, with the sampler running:

    feed                   the rest of the file, one batch: one fit on all of it
    feed --rows 50%        the next half (of the whole file): one fit
    feed --chunk 100       the rest, 100 rows at a time: a fit per chunk
    feed --rows 10 --chunk 1   the next 10 rows, one per fit
    feed --restart         back to row 0, in a new run

Each batch waits for its fit before the next is sent, so every step gets one.
A new run also starts when the file changes (path, order, size or mtime).
`simulate` writes a dataset from the model's simulator, with its true
parameters beside it (`<file>.truth.json`); feeding that file shows the truth
on the dashboard.
"""

import json
import logging
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from {{cookiecutter.package_name}} import belt
from {{cookiecutter.package_name}} import model as example

log = logging.getLogger(__name__)


def run(
    con: duckdb.DuckDBPyConnection,
    path: str,
    *,
    order_by: str | None = None,
    rows: str | None = None,
    chunk: int | None = None,
    restart: bool = False,
    timeout: float = 900.0,
) -> list[dict]:
    """Feed the next `rows` (all that are left by default) in batches of `chunk`; one dict per batch, with its fit."""
    if not os.path.exists(path):
        raise SystemExit(
            f"{path} doesn't exist: `mise run simulate` writes a simulated dataset there,"
            " or set FEED_FROM in .env to your prepared file"
        )
    table = load(path, order_by)
    mtime = os.stat(path).st_mtime
    r = latest_run(con)
    same = r is not None and (r["source"], r["order_by"], r["rows"], r["mtime"]) == (
        path,
        order_by,
        table.num_rows,
        mtime,
    )
    if restart or not same:
        r = new_run(con, path, order_by, table, mtime)
    fed = cursor(con, r["id"])
    left = table.num_rows - fed
    if not left:
        log.warning("all %d rows of %s are fed; `feed --restart` feeds it again from row 0", table.num_rows, path)
        return []
    n = left if rows is None else min(left, count(rows, table.num_rows))
    size = chunk or n
    out = []
    for start in range(fed, fed + n, size):
        k = min(size, fed + n - start)
        batch_id = write_batch(con, r["id"], start, table.slice(start, k))
        fit = wait_for_fit(con, batch_id, timeout)
        line = {"batch_id": batch_id, "rows": start + k, "of": table.num_rows}
        line |= {key: fit[key] for key in ("fit_s", "max_rhat", "divergences", "min_ess")}
        print(json.dumps(line), flush=True)
        out.append(line)
    return out


def count(rows: str, total: int) -> int:
    """`--rows`: a number of rows, or a percentage of the whole file (`50%`)."""
    try:
        n = round(total * float(rows[:-1]) / 100) if rows.endswith("%") else int(rows)
    except ValueError:
        raise SystemExit(f"--rows wants a number of rows or a percentage like 50%, not {rows!r}") from None
    if n < 1:
        raise SystemExit(f"--rows {rows} is less than one row of {total}")
    return n


def latest_run(con: duckdb.DuckDBPyConnection) -> dict | None:
    rows = belt.read(con, "select * from runs order by id desc limit 1").to_pylist()
    return rows[0] if rows else None


def cursor(con: duckdb.DuckDBPyConnection, run_id: int) -> int:
    """Rows of the run fed so far."""
    return belt.read(con, f"select coalesce(sum(n), 0)::bigint n from batches where run_id = {int(run_id)}")["n"][
        0
    ].as_py()


def new_run(con: duckdb.DuckDBPyConnection, path: str, order_by: str | None, table: pa.Table, mtime: float) -> dict:
    coords = example.coords_for(table)
    log.info("%s: %d rows, %s; feeding from row 0", path, table.num_rows, _dims(coords))
    row = {
        "id": time.time_ns(), "created_at": datetime.now(UTC), "source": path, "order_by": order_by,
        "rows": table.num_rows, "mtime": mtime, "coords": json.dumps(coords),
    }  # fmt: skip
    truth = truth_path(path)
    if truth.exists():
        names, values = zip(*json.loads(truth.read_text()))
        belt.write(con, "truth", pa.table({"run_id": [row["id"]] * len(names), "name": names, "value": values}))
    belt.write(con, "runs", pa.Table.from_pylist([row], schema=RUNS))  # after its truth: a run is its marker
    return row


# Explicit, so a null order_by still has a type.
RUNS = pa.schema([
    ("id", pa.int64()), ("created_at", pa.timestamp("us", "UTC")), ("source", pa.string()), ("order_by", pa.string()),
    ("rows", pa.int64()), ("mtime", pa.float64()), ("coords", pa.string()),
])  # fmt: skip


def write_batch(con: duckdb.DuckDBPyConnection, run_id: int, first_row: int, rows: pa.Table) -> int:
    batch_id = time.time_ns()
    belt.write(con, "obs", rows.append_column("batch_id", pa.array(np.full(rows.num_rows, batch_id))))
    # Marker last: the sampler only sees a batch once its rows are all in.
    marker = {"id": [batch_id], "created_at": [datetime.now(UTC)], "run_id": [run_id], "first_row": [first_row]}
    belt.write(con, "batches", pa.table({**marker, "n": pa.array([rows.num_rows], pa.int32())}))
    return batch_id


def wait_for_fit(con: duckdb.DuckDBPyConnection, batch_id: int, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        rows = belt.read(con, f"select * from fits where batch_id = {batch_id} limit 1").to_pylist()
        if rows:
            return rows[0]
        if time.monotonic() > deadline:
            raise SystemExit(
                f"no fit of batch {batch_id} after {timeout:g} s: is the sampler running?"
                " (`mise run loop:cpu status`, logs/sample.log). The batch is on the belt; it's fit when the sampler runs."
            )
        time.sleep(0.1)


def simulate(path: str, rng: np.random.Generator, *, n: int, sizes: Mapping[str, int]) -> dict:
    """Write n rows from the model's simulator to a parquet file, and the truth beside it."""
    truth = example.draw_truth(rng, sizes)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(example.simulate(rng, truth, n), path)
    truth_path(path).write_text(json.dumps(truth.rows()))
    return {"path": path, "rows": n, "truth": str(truth_path(path))}


def truth_path(path: str) -> Path:
    return Path(path).with_suffix(".truth.json")


def chunks(rows: pa.Table, n: int, path: str) -> list[pa.Table]:
    """The file's full chunks of n rows (for `bench --from`). A short tail is skipped: it would need its own program."""
    if rows.num_rows < n:
        raise SystemExit(f"{path} has {rows.num_rows} rows, fewer than --n {n}")
    full = rows.num_rows - rows.num_rows % n
    if full < rows.num_rows:
        log.info(
            "skipping the last %d rows of %s (a short batch would compile a second program)", rows.num_rows - full, path
        )
    return [rows.slice(i, n) for i in range(0, full, n)]


def load(path: str, order_by: str | None) -> pa.Table:
    """A file's rows as the obs table's columns, cast to its types (checked locally, before any write)."""
    local = duckdb.connect()
    local.execute(example.OBS_DDL)
    cols = [c for (c,) in local.execute("select column_name from duckdb_columns() where table_name = 'obs'").fetchall()]
    cols.remove("batch_id")
    select = ", ".join(_ident(c) for c in cols)
    order = f" order by {_ident(order_by)}" if order_by else ""
    try:
        local.execute(f"insert into obs by name select {select} from {belt.lit(path)}{order}")
    except duckdb.Error as e:
        raise SystemExit(f"loading {path} as obs rows ({', '.join(cols)}; see model.OBS_DDL): {e}") from e
    return local.execute(f"select {select} from obs order by rowid").to_arrow_table()


def _dims(coords: dict) -> str:
    return ", ".join(f"{d}={len(v)}" for d, v in coords.items())


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
