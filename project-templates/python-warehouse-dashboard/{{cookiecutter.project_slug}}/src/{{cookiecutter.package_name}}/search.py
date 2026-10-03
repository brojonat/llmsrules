"""Full-text search over ticket subjects and bodies (SQLite FTS5).

`build` writes `ticket_text.sqlite`, a contentless FTS5 index whose rowids
are ticket ids. Searching it returns ticket ids; the tools then aggregate
those in DuckDB (by year, product, category, state). Each engine does what
it's good at: FTS5 finds a phrase among millions of rows in milliseconds,
DuckDB aggregates in tens of milliseconds.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .ingest import TEXT_INDEX

MAX_MATCHES = 250_000


class SearchError(Exception):
    pass


class TextIndex:
    def __init__(self, root: Path) -> None:
        self.path = root / f"{TEXT_INDEX}.sqlite"

    @property
    def ready(self) -> bool:
        return self.path.exists()

    def match(self, query: str) -> list[int]:
        """Ticket ids whose subject or body matches an FTS5 query."""
        if not self.ready:
            raise SearchError("the text index isn't built; run `build`")
        # A fresh read-only connection per search: SQLite connections don't
        # cross threads, and opening one is ~0.1 ms. immutable=1 skips locking;
        # a rebuild replaces the file rather than writing into it.
        db = sqlite3.connect(f"file:{self.path}?mode=ro&immutable=1", uri=True)
        try:
            rows = db.execute(
                f"SELECT rowid FROM {TEXT_INDEX} WHERE {TEXT_INDEX} MATCH ? LIMIT ?", [query, MAX_MATCHES]
            ).fetchall()
        except sqlite3.OperationalError as e:
            raise SearchError(f"bad search query: {e}. Quote phrases, e.g. '\"double charged\"'") from None
        finally:
            db.close()
        return [r[0] for r in rows]
