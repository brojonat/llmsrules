"""Load the belt: insert batches of obs rows, each followed by its marker.

Two sources. `simulate` draws batches from the model's simulator, whose truth
drifts so the dashboard has something to track. `replay` streams a file
(Parquet, CSV, JSON: anything DuckDB reads) through the belt in fixed-size
chunks, in file order or ordered by a column, as if it were arriving live.
"""

import json
import logging
import time
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime

import duckdb
import numpy as np
import pyarrow as pa

from {{cookiecutter.package_name}} import belt
from {{cookiecutter.package_name}} import model as example
from {{cookiecutter.package_name}}.labels import Coords

log = logging.getLogger(__name__)


def simulate(
    con: duckdb.DuckDBPyConnection,
    rng: np.random.Generator,
    *,
    n: int,
    sizes: Mapping[str, int],
    every: float,
    drift: float,
    count: int,
) -> None:
    truth = example.draw_truth(rng, sizes)

    def batches() -> Iterator[tuple[pa.Table, Coords, list[tuple[str, float]]]]:
        nonlocal truth
        while True:
            truth = example.drift(rng, truth, drift)
            yield example.simulate(rng, truth, n), truth.coords, truth.rows()

    _pump(con, batches(), every=every, count=count)


def replay(
    con: duckdb.DuckDBPyConnection, path: str, *, n: int, order_by: str | None, every: float, count: int
) -> None:
    rows = load(path, order_by)
    coords = example.coords_for(rows)  # once per file: every batch shares one compiled program
    log.info("%s: %d rows, %s", path, rows.num_rows, ", ".join(f"{d}={len(v)}" for d, v in coords.items()))
    _pump(con, ((chunk, coords, None) for chunk in chunks(rows, n, path)), every=every, count=count)
    log.info("replayed %s; done (restart feed to replay it again)", path)


def chunks(rows: pa.Table, n: int, path: str) -> list[pa.Table]:
    """The file's full chunks of n rows. A short tail is skipped: it would need its own program."""
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


def _pump(
    con: duckdb.DuckDBPyConnection,
    batches: Iterator[tuple[pa.Table, Coords, list[tuple[str, float]] | None]],
    *,
    every: float,
    count: int,
) -> None:
    """Write each (obs rows, coords, truth or None) as a batch, one every `every` seconds."""
    for i, (rows, coords, truth) in enumerate(batches):
        if count and i >= count:
            return
        t0 = time.monotonic()
        batch_id = time.time_ns()
        belt.write(con, "obs", rows.append_column("batch_id", pa.array(np.full(rows.num_rows, batch_id))))
        if truth:
            names, values = zip(*truth)
            belt.write(con, "truth", pa.table({"batch_id": [batch_id] * len(names), "name": names, "value": values}))
        # Marker last: the sampler only sees a batch once its rows are all in.
        marker = {
            "id": [batch_id],
            "created_at": [datetime.now(UTC)],
            "n": [rows.num_rows],
            "coords": [json.dumps(coords)],
        }
        belt.write(con, "batches", pa.table(marker))

        write_s = time.monotonic() - t0
        print(json.dumps({"batch_id": batch_id, "n": rows.num_rows, "write_s": round(write_s, 4)}), flush=True)
        time.sleep(max(0.0, every - write_s))


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
