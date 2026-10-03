"""The thread between the agent and whoever watches the dashboard.

One `messages` table holds both directions. The agent posts notes (what it's
changing and why, what happened), a report when it's done, and the commit it
made; the user posts feedback, or approves a model version, from the
dashboard. `handled` records which user messages the agent has read, so the
inbox is everything from the user that isn't in it. Append-only, like the
rest of the belt: nothing is updated in place.

Model versions are numbered by spec (`str_repr()`): v1 is the first model the
sampler compiled, v2 the next one that differs, and so on. A new batch size or
a sampler restart compiles a new `models` row but not a new version.
"""

import time
from datetime import UTC, datetime

import duckdb
import pyarrow as pa

from {{cookiecutter.package_name}} import belt

AGENT = "agent"  # model_notes.llm for a description the agent wrote ({{cookiecutter.project_slug}} describe)
AGENT_KINDS = ("note", "report", "commit", "status")  # status: hidden from the thread, shown as the agent's state
USER_KINDS = ("feedback", "approve")


def post(con: duckdb.DuckDBPyConnection, author: str, kind: str, text: str, model_id: int | None = None) -> int:
    message_id = time.time_ns()
    row = {
        "id": [message_id], "created_at": [datetime.now(UTC)], "author": [author], "kind": [kind],
        "model_id": pa.array([model_id], pa.int64()), "text": [text],
    }  # fmt: skip
    belt.write(con, "messages", pa.table(row))
    return message_id


def describe(con: duckdb.DuckDBPyConnection, model_id: int, text: str) -> None:
    """The agent's plain-English description of a model version; the dashboard prefers it to an LLM's."""
    row = {"model_id": [model_id], "created_at": [datetime.now(UTC)], "llm": [AGENT], "text": [text]}
    belt.write(con, "model_notes", pa.table(row))


def description(con: duckdb.DuckDBPyConnection, model_id: int) -> dict | None:
    """The best saved description of this model's version (same spec): the agent's newest, else an LLM's."""
    rows = belt.read(
        con,
        f"""select n.llm, n.text from model_notes n join models m on m.id = n.model_id
            where m.spec = (select spec from models where id = {model_id})
            order by (n.llm = '{AGENT}') desc, n.created_at desc limit 1""",
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


def unread(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """The user's messages the agent hasn't read, oldest first."""
    return belt.read(
        con,
        """select m.id, m.created_at, m.kind, m.model_id, m.text from messages m
           where m.author = 'user' and m.id not in (select message_id from handled)
           order by m.id""",
    ).to_pylist()


def mark_read(con: duckdb.DuckDBPyConnection, ids: list[int]) -> None:
    if ids:
        belt.write(con, "handled", pa.table({"message_id": ids, "handled_at": [datetime.now(UTC)] * len(ids)}))


def thread(con: duckdb.DuckDBPyConnection, limit: int = 40) -> list[dict]:
    """The newest `limit` messages (statuses aside), oldest first, with read state."""
    return belt.read(
        con,
        f"""select * from (
              select m.*, h.message_id is not null as read from messages m
              left join (select distinct message_id from handled) h on h.message_id = m.id
              where m.kind != 'status' order by m.id desc limit {limit})
            order by id""",
    ).to_pylist()


def agent_state(con: duckdb.DuckDBPyConnection) -> dict | None:
    """The agent's newest message of any kind: a 'status' says what it's doing, anything else means working."""
    rows = belt.read(
        con, "select kind, text, created_at from messages where author = 'agent' order by id desc limit 1"
    ).to_pylist()
    return rows[0] if rows else None
