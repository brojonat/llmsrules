"""Application database (PostgreSQL): users, sessions, tags, migrations."""

import psycopg2

from server.config import Settings, get_settings


class AppDB:
    """A psycopg2 connection in autocommit mode.

    `raw_sql` returns the cursor, so callers can `fetchone()` / `fetchall()`.
    Pass values as `params` (`%s` placeholders), never by formatting them into
    the SQL.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._conn = None

    def connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.settings.app_db_dsn)
            self._conn.autocommit = True
        return self._conn

    def raw_sql(self, sql: str, params: tuple | list | None = None):
        cur = self.connect().cursor()
        cur.execute(sql, params)
        return cur

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None


_app_db: AppDB | None = None


def get_app_db() -> AppDB:
    """The process-wide app database (created on first use)."""
    global _app_db
    if _app_db is None:
        _app_db = AppDB(get_settings())
    return _app_db
