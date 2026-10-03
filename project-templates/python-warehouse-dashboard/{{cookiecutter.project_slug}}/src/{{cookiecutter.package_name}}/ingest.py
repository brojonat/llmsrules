"""The write side: raw files -> typed Parquet -> query-shaped read models.

Nothing here serves traffic. `build` turns the files `generate` keeps under
raw/ into a warehouse directory the server only ever reads.
`manifest.json` is written last, by atomic rename, so a reader that sees a
new manifest sees a complete build.

A build is skipped when the manifest already records the same source content
hash and the same recipe hash (the SQL below), so `generate && build` on a
schedule does work only when there is work. A build that would publish
noticeably less data than the current one is refused: a source that loses
rows overnight is a broken source, not news.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .generate import raw_files
from .schema import RAW_COLUMNS, STATES

MANIFEST = "manifest.json"
TEXT_INDEX = "ticket_text"  # SQLite FTS5 over subject + body: <TEXT_INDEX>.sqlite

# One row per ticket, typed, with the derived columns every query wants.
TICKETS_SQL = """
CREATE TABLE tickets AS
SELECT
    ticket_id,
    opened_at,
    resolved_at,
    year(opened_at)                                              AS year,
    date_trunc('month', opened_at)::DATE                         AS month,
    trim(product)                                                AS product,
    trim(plan)                                                   AS plan,
    trim(channel)                                                AS channel,
    trim(category)                                               AS category,
    severity,
    upper(trim(state))                                           AS state,
    coalesce(escalated, false)                                   AS escalated,
    resolved_at IS NOT NULL                                      AS resolved,
    round(epoch(resolved_at - opened_at) / 3600, 2)              AS resolution_hours,
    satisfaction,
    coalesce(refund_usd, 0)                                      AS refund_usd,
    subject,
    body
FROM raw
WHERE ticket_id IS NOT NULL
ORDER BY opened_at, ticket_id;
"""

# Read models. Each is shaped for the questions asked of it, small enough
# that every dashboard query is a scan of a few MB.
READ_MODELS = {
    # The dashboard's workhorse. Every filter dimension (product, plan,
    # channel, category, state, year) is a column, and nothing else is: that
    # grain is the whole performance story. Sums, not averages, so any
    # subset can be re-aggregated exactly.
    "tickets_state_year": """
        SELECT product, plan, channel, category, state, year,
               count(*)                                   AS tickets,
               count(*) FILTER (escalated)                AS escalated,
               count(*) FILTER (resolved)                 AS resolved,
               coalesce(sum(resolution_hours), 0)         AS resolution_hours,
               count(satisfaction)                        AS csat_responses,
               coalesce(sum(satisfaction), 0)             AS csat_points,
               sum(refund_usd)                            AS refunds_usd
        FROM tickets GROUP BY ALL
    """,
    # Monthly grain for trends (the assistant's line charts, `query`).
    "product_month": """
        SELECT product, category, plan, channel, month,
               count(*)                                   AS tickets,
               count(*) FILTER (escalated)                AS escalated,
               count(*) FILTER (resolved)                 AS resolved,
               coalesce(sum(resolution_hours), 0)         AS resolution_hours,
               count(satisfaction)                        AS csat_responses,
               coalesce(sum(satisfaction), 0)             AS csat_points
        FROM tickets GROUP BY ALL
    """,
}
# Sorted by the columns people filter on, in small row groups: DuckDB skips
# row groups whose min/max can't match, so a narrow dataset reads a sliver.
SORT = {"tickets_state_year": "product, category, state, year", "product_month": "product, month"}

# Every file the server needs. A warehouse missing one was built by an older
# recipe; the server keeps serving the previous build until a new one lands.
REQUIRED = ["tickets", "states", *READ_MODELS]


def recipe_hash() -> str:
    """Changes whenever the build would produce different output from the
    same input, so an unchanged source still rebuilds after a code change."""
    recipe = json.dumps([RAW_COLUMNS, TICKETS_SQL, READ_MODELS, SORT, sorted(STATES.items()), "fts5-porter-v1"])
    return hashlib.sha256(recipe.encode()).hexdigest()[:16]


@dataclass
class BuildResult:
    warehouse: str
    source: str
    source_sha256: str
    recipe: str
    built_at: str
    seconds: float
    rows: dict[str, int]
    data_through: str | None = None  # latest ticket opened (its year is partial)
    skipped: bool = False


class ShrinkError(Exception):
    """A new build would publish noticeably less data than the current one."""


# A day's new data never loses rows. Fewer than this fraction of the current
# build's means a broken source (a truncated download, a bad export).
MAX_SHRINK = 0.02


def source_hash(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def build(
    raw: Path,
    warehouse: Path,
    threads: int | None = None,
    force: bool = False,
    memory_limit: str | None = None,
) -> BuildResult:
    """Rebuild every file under `warehouse` from the raw files, unless the
    existing build came from the same content with the same recipe.

    Refuses (ShrinkError) to replace a build with one that has noticeably
    fewer tickets or an earlier latest ticket; `force` overrides."""
    started = time.monotonic()
    files = raw_files(raw)
    if not files:
        raise FileNotFoundError(f"no raw files in {raw}; run `generate` first")
    sha = source_hash(files)
    recipe = recipe_hash()
    try:
        prev = json.loads((warehouse / MANIFEST).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        prev = {}
    if not force and prev.get("source_sha256") == sha and prev.get("recipe") == recipe:
        prev.pop("skipped", None)
        return BuildResult(**prev, skipped=True)

    warehouse.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=warehouse, prefix=".build-") as tmpdir:
        tmp = Path(tmpdir)
        con = duckdb.connect(str(tmp / "build.duckdb"))
        con.execute("SET enable_progress_bar = false")
        if threads:
            con.execute(f"SET threads = {int(threads)}")
        if memory_limit:
            # On a small node: cap DuckDB and let it spill to the build dir.
            con.execute(f"SET memory_limit = '{memory_limit}'")
            con.execute(f"SET temp_directory = '{tmp / 'spill'}'")
            con.execute("SET preserve_insertion_order = false")
        print(f"build: loading {len(files)} raw files", file=sys.stderr)
        columns = "{" + ", ".join(f"'{c}': '{t}'" for c, t in RAW_COLUMNS) + "}"
        paths = ", ".join(f"'{f}'" for f in files)
        con.execute(f"CREATE TABLE raw AS SELECT * FROM read_csv([{paths}], header = true, columns = {columns})")
        con.execute(TICKETS_SQL)
        con.execute("DROP TABLE raw")
        for name, sql in READ_MODELS.items():
            con.execute(f"CREATE TABLE {name} AS {sql}")
        con.execute("CREATE TABLE states (state VARCHAR, fips VARCHAR, name VARCHAR, population BIGINT)")
        con.executemany("INSERT INTO states VALUES (?, ?, ?, ?)", [(k, *v) for k, v in STATES.items()])

        through = con.execute("SELECT max(opened_at)::DATE FROM tickets").fetchone()[0]
        data_through = str(through) if through else None
        rows = {}
        out = tmp / "out"
        out.mkdir()
        for name in REQUIRED:
            print(f"build: writing {name}.parquet", file=sys.stderr)
            if name in SORT:
                sorted_rows = f"SELECT * FROM {name} ORDER BY {SORT[name]}"
                options = "FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 16384"
                con.execute(f"COPY ({sorted_rows}) TO '{out / name}.parquet' ({options})")
            else:
                con.execute(f"COPY {name} TO '{out / name}.parquet' (FORMAT parquet, COMPRESSION zstd)")
            rows[name] = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        _check_not_shrinking(prev, rows, data_through, force)
        print("build: indexing ticket text (full-text)", file=sys.stderr)
        rows[TEXT_INDEX] = build_text_index(con, out / f"{TEXT_INDEX}.sqlite")
        con.close()

        for f in out.iterdir():
            f.replace(warehouse / f.name)
        # Drop files this recipe no longer produces (renamed or removed read
        # models), so the warehouse is exactly this build.
        for stale in [*warehouse.glob("*.parquet"), *warehouse.glob("*.sqlite")]:
            if stale.stem not in {*REQUIRED, TEXT_INDEX}:
                stale.unlink()

    result = BuildResult(
        warehouse=str(warehouse),
        source=str(raw),
        source_sha256=sha,
        recipe=recipe,
        built_at=datetime.now(UTC).isoformat(),
        seconds=round(time.monotonic() - started, 1),
        rows=rows,
        data_through=data_through,
    )
    manifest_tmp = warehouse / (MANIFEST + ".tmp")
    manifest_tmp.write_text(json.dumps(asdict(result), indent=2))
    manifest_tmp.replace(warehouse / MANIFEST)
    return result


def build_text_index(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """A SQLite FTS5 index over ticket subjects and bodies, keyed by ticket id.

    DuckDB scans text with ILIKE in seconds once there are millions of rows;
    FTS5 answers a phrase query in milliseconds and adds stemming, phrases
    and NEAR. The index is contentless (rowid = ticket_id): the text itself
    stays in tickets.parquet.
    """
    cur = con.execute("SELECT ticket_id, subject, body FROM tickets")
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode = OFF")
    db.execute("PRAGMA synchronous = OFF")
    db.execute(f"CREATE VIRTUAL TABLE {TEXT_INDEX} USING fts5(subject, body, content='', tokenize='porter unicode61')")
    # Streamed in batches, so memory stays flat however big the table gets.
    n = 0
    while batch := cur.fetchmany(20_000):
        db.executemany(f"INSERT INTO {TEXT_INDEX}(rowid, subject, body) VALUES (?, ?, ?)", batch)
        n += len(batch)
    db.commit()
    db.execute(f"INSERT INTO {TEXT_INDEX}({TEXT_INDEX}) VALUES ('optimize')")
    db.commit()
    db.close()
    return n


def _check_not_shrinking(prev: dict, rows: dict[str, int], data_through: str | None, force: bool) -> None:
    had = (prev.get("rows") or {}).get("tickets")
    if force or not had:
        return
    if rows["tickets"] < had * (1 - MAX_SHRINK):
        raise ShrinkError(
            f"the new data has {rows['tickets']:,} tickets, the current build {had:,}: refusing to publish a "
            "shrunken warehouse (source truncated?); `build --force` overrides"
        )
    if (data_through or "") < (prev.get("data_through") or ""):
        raise ShrinkError(
            f"the new data runs through {data_through}, the current build through {prev['data_through']}: "
            "refusing to go backwards; `build --force` overrides"
        )
