"""The app database: state the service writes and keeps (feedback, LLM usage).

SQLite in WAL mode, one file (APP_DB, default data/app.sqlite). It lives
outside the warehouse on purpose: the warehouse is rebuilt from the source
and a rebuild deletes whatever it didn't produce; this is the one place
user-contributed state survives. In production it's replicated to object
storage with litestream (deploy/litestream.yml), so the pod itself can stay
disposable.

Migrations are an ordered list; PRAGMA user_version records how many have
run. Append to MIGRATIONS, never edit an entry that has shipped.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS = [
    """
    CREATE TABLE feedback (
        id          INTEGER PRIMARY KEY,
        created_at  TEXT NOT NULL,              -- ISO 8601 UTC
        updated_at  TEXT NOT NULL,
        kind        TEXT NOT NULL,              -- 'rating' (the check-in) | 'report' (drafted by the assistant)
        rating      INTEGER,                    -- 1 bad, 2 fine, 3 good (ratings only)
        category    TEXT,                       -- reports: bug | data_quality | feature_request | praise | other
        summary     TEXT,                       -- reports: one line
        comment     TEXT,                       -- the user's words (ratings: the optional follow-up)
        session     TEXT NOT NULL,              -- pseudonymous: a hash of the session cookie
        dataset     TEXT,                       -- JSON: the dashboard filter at the time
        transcript  TEXT,                       -- JSON: the conversation up to that point
        model       TEXT
    );
    CREATE INDEX feedback_created ON feedback (created_at);
    """,
    """
    -- LLM usage per UTC day and model: the daily token budget reads it, and
    -- it's the long-run record of what the assistant costs.
    CREATE TABLE llm_usage (
        day                TEXT NOT NULL,       -- YYYY-MM-DD, UTC
        model              TEXT NOT NULL,
        replies            INTEGER NOT NULL DEFAULT 0,
        prompt_tokens      INTEGER NOT NULL DEFAULT 0,   -- cached ones included
        completion_tokens  INTEGER NOT NULL DEFAULT 0,   -- reasoning included
        cached_tokens      INTEGER NOT NULL DEFAULT 0,
        cost               REAL NOT NULL DEFAULT 0,      -- USD, as the provider reports it
        PRIMARY KEY (day, model)
    );
    """,
]


@dataclass
class Feedback:
    id: int
    created_at: str
    updated_at: str
    kind: str
    rating: int | None
    category: str | None
    summary: str | None
    comment: str | None
    session: str
    dataset: dict | None
    transcript: list | None
    model: str | None


@dataclass
class DailyUsage:
    day: str
    model: str
    replies: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost: float

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class AppDB:
    """One connection, serialized with a lock: writes are rare and tiny."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                # executescript commits anything pending before it runs, so the
                # transaction has to be inside the script to make it atomic.
                self._db.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {i};\nCOMMIT;")

    @property
    def version(self) -> int:
        return self._db.execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        self._db.close()

    def add_feedback(
        self,
        *,
        kind: str,
        session: str,
        rating: int | None = None,
        category: str | None = None,
        summary: str | None = None,
        comment: str | None = None,
        dataset: dict | None = None,
        transcript: list | None = None,
        model: str | None = None,
    ) -> int:
        now = _now()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO feedback (created_at, updated_at, kind, rating, category, summary, comment, session, "
                "dataset, transcript, model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [now, now, kind, rating, category, summary, comment, session,
                 _json(dataset), _json(transcript), model],
            )  # fmt: skip
            return int(cur.lastrowid)

    def add_comment(self, feedback_id: int, comment: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE feedback SET comment = ?, updated_at = ? WHERE id = ?", [comment, _now(), feedback_id]
            )

    def feedback(self, limit: int = 100, since: str = "") -> list[Feedback]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, created_at, updated_at, kind, rating, category, summary, comment, session, dataset, "
                "transcript, model FROM feedback WHERE created_at >= ? ORDER BY id DESC LIMIT ?",
                [since, limit],
            ).fetchall()
        return [Feedback(*r[:9], _unjson(r[9]), _unjson(r[10]), r[11]) for r in rows]

    def feedback_counts(self) -> dict:
        """For /admin: numbers only, never the text."""
        with self._lock:
            ratings = dict(self._db.execute(
                "SELECT rating, count(*) FROM feedback WHERE kind = 'rating' GROUP BY rating"
            ).fetchall())  # fmt: skip
            reports = dict(self._db.execute(
                "SELECT category, count(*) FROM feedback WHERE kind = 'report' GROUP BY category"
            ).fetchall())  # fmt: skip
        return {"ratings": {k: ratings.get(k, 0) for k in (1, 2, 3)}, "reports": reports}

    def add_usage(self, model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int, cost: float) -> int:
        """Count one reply against today (UTC). Returns today's total tokens, all models."""
        day = _today()
        with self._lock:
            self._db.execute(
                "INSERT INTO llm_usage (day, model, replies, prompt_tokens, completion_tokens, cached_tokens, cost) "
                "VALUES (?, ?, 1, ?, ?, ?, ?) ON CONFLICT (day, model) DO UPDATE SET replies = replies + 1, "
                "prompt_tokens = prompt_tokens + excluded.prompt_tokens, "
                "completion_tokens = completion_tokens + excluded.completion_tokens, "
                "cached_tokens = cached_tokens + excluded.cached_tokens, cost = cost + excluded.cost",
                [day, model, prompt_tokens, completion_tokens, cached_tokens, cost],
            )
            return self._tokens_on(day)

    def tokens_today(self) -> int:
        with self._lock:
            return self._tokens_on(_today())

    def _tokens_on(self, day: str) -> int:
        row = self._db.execute(
            "SELECT coalesce(sum(prompt_tokens + completion_tokens), 0) FROM llm_usage WHERE day = ?", [day]
        ).fetchone()
        return int(row[0])

    def usage(self, days: int = 30) -> list[DailyUsage]:
        """Newest day first; one row per day and model."""
        with self._lock:
            rows = self._db.execute(
                "SELECT day, model, replies, prompt_tokens, completion_tokens, cached_tokens, cost FROM llm_usage "
                "WHERE day >= date('now', ?) ORDER BY day DESC, model",
                [f"-{max(days, 1) - 1} days"],
            ).fetchall()
        return [DailyUsage(*r) for r in rows]


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json(v) -> str | None:
    return None if v is None else json.dumps(v, default=str)


def _unjson(s: str | None):
    return None if s is None else json.loads(s)
