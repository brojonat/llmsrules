"""The agent's journal on the dashboard: what it's doing and why, for whoever watches.

The agent posts notes (what it's changing and why, what happened), a report
when it's done, and the commits it made; a `status` says what it's doing right
now and shows beside the thread rather than in it. One direction only: the
user talks to the agent in the agent's own harness. Append-only, like the rest
of the belt.

Model versions are numbered by spec (`str_repr()`): v1 is the first model the
sampler compiled, v2 the next one that differs, and so on. A new batch size or
a sampler restart compiles a new `models` row but not a new version.
"""

import time
from datetime import UTC, datetime

import duckdb
import pyarrow as pa

from {{cookiecutter.package_name}} import belt

KINDS = ("note", "report", "commit", "status")  # status: hidden from the thread, shown as what the agent is doing


def post(con: duckdb.DuckDBPyConnection, kind: str, text: str, model_id: int | None = None) -> int:
    message_id = time.time_ns()
    row = {
        "id": [message_id], "created_at": [datetime.now(UTC)], "kind": [kind],
        "model_id": pa.array([model_id], pa.int64()), "text": [text],
    }  # fmt: skip
    belt.write(con, "messages", pa.table(row))
    return message_id


def describe(con: duckdb.DuckDBPyConnection, model_id: int, text: str) -> None:
    """The agent's plain-English description of a model version (the dashboard's "What this model says")."""
    row = {"model_id": [model_id], "created_at": [datetime.now(UTC)], "text": [text]}
    belt.write(con, "model_notes", pa.table(row))


def description(con: duckdb.DuckDBPyConnection, model_id: int) -> dict | None:
    """The newest description of this model's version (same spec): {text}, or None."""
    rows = belt.read(
        con,
        f"""select n.text from model_notes n join models m on m.id = n.model_id
            where m.spec = (select spec from models where id = {model_id})
            order by n.created_at desc limit 1""",
    ).to_pylist()
    return rows[0] if rows else None


def latest_model(con: duckdb.DuckDBPyConnection) -> int | None:
    """The model of the newest fit: the one the dashboard is showing."""
    rows = belt.read(con, "select model_id from fits order by id desc limit 1").to_pylist()
    return rows[0]["model_id"] if rows else None


def versions(con: duckdb.DuckDBPyConnection) -> dict[int, int]:
    """model id -> version number (1, 2, ...), by first appearance of each spec."""
    rows = belt.read(
        con,
        """select id, dense_rank() over (order by first_id) v
           from (select id, min(id) over (partition by spec) first_id from models)""",
    ).to_pylist()
    return {r["id"]: r["v"] for r in rows}


def thread(con: duckdb.DuckDBPyConnection, limit: int = 40) -> list[dict]:
    """The newest `limit` messages (statuses aside), oldest first."""
    return belt.read(
        con,
        f"""select * from (select * from messages where kind != 'status' order by id desc limit {limit})
            order by id""",
    ).to_pylist()


def latest(con: duckdb.DuckDBPyConnection, status: bool) -> dict | None:
    """The newest status (status=True) or the newest other message: kind, text, created_at."""
    rows = belt.read(
        con,
        f"select kind, text, created_at from messages where (kind = 'status') = {status} order by id desc limit 1",
    ).to_pylist()
    return rows[0] if rows else None
