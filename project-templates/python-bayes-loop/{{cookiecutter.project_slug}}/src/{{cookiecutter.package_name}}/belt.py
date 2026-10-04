"""The belt: one DuckDB file served over Quack; every other process is a client.

    feed ──insert batches──▶ db (quack_serve) ◀──read batches / insert fits── sample
                                  ▲
                         serve polls query('select max(id) ...')

Shaped around how Quack behaves in DuckDB 1.5 (beta). Measured, not assumed:

- Clients can't see sequences, and a remote catalog containing a `nextval`
  default fails to ATTACH. IDs are `time.time_ns()` from the writer.
- ROLLBACK over Quack does not undo an insert. A multi-table write is made
  atomic by writing the payload first and its marker row (`batches`, `fits`)
  last; readers only look for marker rows.
- Queries against the attached catalog stream whole tables to the client
  (count(*) over 1M rows: ~860 ms). `query('<sql>')` runs on the server
  (~2 ms). Every read here goes through `read()`, which uses `query()`.
  `query()` resolves names in the *current* catalog, hence `USE remote`
  (which a `.cursor()` does not inherit).
"""

import logging
import signal
import threading
import time

import duckdb
import pyarrow as pa

log = logging.getLogger(__name__)

SCHEMA = """
create table if not exists runs(
    id bigint, created_at timestamptz, source varchar, order_by varchar, rows bigint, mtime double, coords varchar);
    -- one pass of feed's cursor through a data file (feed.py); rows: the file's size;
    -- coords: JSON {dim: [labels]}, from the whole file, so every fit in the run shares them
create table if not exists batches(id bigint, created_at timestamptz, run_id bigint, first_row bigint, n integer);
    -- the run's rows first_row .. first_row + n - 1; a fit of a batch sees every row fed in its run so far
create table if not exists truth(run_id bigint, name varchar, value float);  -- a simulated file's true parameters
create table if not exists models(
    id bigint, created_at timestamptz, n integer, coords varchar,
    dot varchar, spec varchar, context varchar, view varchar, source varchar, git_rev varchar);
    -- dot: model_to_graphviz; spec: str_repr(); context: author's note; view: what the dashboard plots (JSON);
    -- source: model.py as compiled; git_rev: HEAD, "+dirty" if model.py differs from it (null outside git)
create table if not exists model_notes(
    model_id bigint, created_at timestamptz, text varchar);  -- the agent's description ({{cookiecutter.project_slug}} describe)
create table if not exists messages(
    id bigint, created_at timestamptz, kind varchar, model_id bigint, text varchar);
    -- the agent's journal on the dashboard (journal.py). kind: note | report | commit | status
create table if not exists draws(fit_id bigint, created_at timestamptz, npz blob);  -- thinned, for plots.py
create table if not exists figures(
    id bigint, created_at timestamptz, model_id bigint, fit_id bigint, author varchar, kind varchar,
    title varchar, png blob, data varchar);
    -- the dashboard's carousel (plots.py): the agent's PNGs, and the data (JSON) of each version's diagnostics
create table if not exists fits(
    id bigint, batch_id bigint, model_id bigint, created_at timestamptz, sampler varchar, device varchar,
    chains integer, draws integer, n integer, fit_s double, summarize_s double, lag_s double,
    grad_evals bigint, divergences integer, min_ess double, max_rhat double, compile_s double);
create table if not exists params(
    fit_id bigint, pos integer, var varchar, name varchar, coords varchar, mean float, sd float,
    q05 float, q25 float, q50 float, q75 float, q95 float, ess float, rhat float, truth float);
    -- truth: simulated batches only
"""


# Housekeeping the db process does locally: a DELETE from a client streams the
# table over Quack first, and the figures table is full of PNGs.
HOUSEKEEPING = """
delete from draws where fit_id not in (select fit_id from draws order by fit_id desc limit 5);
delete from figures where author != 'agent' and id not in (  -- newest render per (version, kind)
    select max(f.id) from figures f left join models m on m.id = f.model_id
    where f.author != 'agent' group by m.spec, f.kind);
"""


def serve(path: str, url: str, token: str, ddl: str, housekeep_s: float = 60.0) -> None:
    """Own the database file and serve it until SIGINT/SIGTERM/SIGHUP (closed terminal).

    Localhost only: Quack refuses other hostnames by default, and its clients
    switch to HTTPS for any non-localhost host. Every process that talks to the
    belt runs on the same machine.
    """
    con = duckdb.connect(path)
    con.execute("INSTALL quack; LOAD quack;")
    con.execute(SCHEMA + ddl)
    _check_schema(con, SCHEMA + ddl, path)
    endpoint = con.execute(f"CALL quack_serve({lit(url)}, token = {lit(token)})").fetchone()[1]
    log.info("serving %s at %s", path, endpoint)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    # Python runs signal handlers on the main thread, but the kernel may deliver
    # the signal to any of DuckDB's threads; an untimed wait would never wake.
    chores = con.cursor()  # its own connection: quack_serve's threads use `con`
    last = time.monotonic()
    while not stop.wait(0.5):
        if time.monotonic() - last >= housekeep_s:
            try:
                chores.execute(HOUSEKEEPING)
            except duckdb.Error as e:  # costs disk, not correctness: say so and carry on
                log.warning("housekeeping: %s", e)
            last = time.monotonic()
    chores.close()
    con.execute("CHECKPOINT")
    con.close()
    log.info("checkpointed and closed %s", path)


def _check_schema(con: duckdb.DuckDBPyConnection, ddl: str, path: str) -> None:
    """`create table if not exists` keeps an old table as is; fail loudly instead of on first insert."""
    sql = "select table_name, list(column_name || ' ' || data_type order by ordinal_position) from information_schema.columns group by 1"
    ref = duckdb.connect()
    ref.execute(ddl)
    want = dict(ref.execute(sql).fetchall())
    have = dict(con.execute(sql).fetchall())
    stale = [t for t, cols in want.items() if have.get(t) != cols]
    if stale:
        raise SystemExit(
            f"{path} was created by an older version (tables changed: {', '.join(sorted(stale))}). "
            "Stop the belt and run `mise run reset` (`mise run reset:cpu` for the CPU profile), or point BELT_DB at a new file."
        )


def connect(url: str, token: str, *, wait_s: float = 60.0) -> duckdb.DuckDBPyConnection:
    """Attach the served database as `remote`, retrying while the server starts."""
    con = duckdb.connect()
    con.execute("INSTALL quack; LOAD quack;")
    con.execute(f"CREATE SECRET (TYPE quack, TOKEN {lit(token)})")
    deadline = time.monotonic() + wait_s
    while True:
        try:
            con.execute(f"ATTACH {lit(url)} AS remote")
            con.execute("USE remote")  # query('<sql>') resolves names in the current catalog
            return con
        except duckdb.Error as e:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"attaching {url}: {e}") from e
            log.info("waiting for db at %s", url)
            time.sleep(1.0)


def read(con: duckdb.DuckDBPyConnection, sql: str) -> pa.Table:
    """Run `sql` on the server and fetch the result as Arrow.

    `sql` is inlined as a string literal; only interpolate values you
    produced (ints, floats), never user input.
    """
    return con.execute(f"select * from query({lit(sql)})").to_arrow_table()


def fed(con: duckdb.DuckDBPyConnection, batch_id: int) -> pa.Table:
    """Every obs row fed in the batch's run up to and including it, in feed order, without batch_id.

    What a fit of the batch sees, and what model.from_arrow takes.
    """
    b = int(batch_id)
    return read(
        con,
        f"""select o.* exclude (batch_id) from obs o join batches b on b.id = o.batch_id
            where b.run_id = (select run_id from batches where id = {b}) and b.id <= {b}
            order by b.id, o.rowid""",
    )


def coords(con: duckdb.DuckDBPyConnection, batch_id: int) -> str:
    """The labels (JSON) of the batch's run."""
    sql = f"select r.coords from batches b join runs r on r.id = b.run_id where b.id = {int(batch_id)}"
    return read(con, sql)["coords"][0].as_py()


def cursor(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """A cursor for another thread, with `USE remote` (a cursor doesn't inherit it; read() needs it)."""
    cur = con.cursor()
    cur.execute("USE remote")
    return cur


def write(con: duckdb.DuckDBPyConnection, table: str, rows: pa.Table) -> None:
    con.register("_rows", rows)
    try:
        con.execute(f"insert into remote.{table} by name select * from _rows")
    finally:
        con.unregister("_rows")


def lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"
