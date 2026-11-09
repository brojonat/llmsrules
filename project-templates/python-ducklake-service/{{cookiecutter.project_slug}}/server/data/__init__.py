"""DuckLake connection: DuckDB (via Ibis) with the lake attached as `lake`.

The catalog lives in PostgreSQL (or a local file for experiments) and the
Parquet data in S3. Queries address tables as `lake.<table>`.
"""

from threading import Lock

import ibis

from server.config import Settings, get_settings
from server.log_config import get_logger

log = get_logger(__name__)


def _sql_str(value: str) -> str:
    """Quote a string literal for DDL that cannot take bound parameters."""
    return "'" + value.replace("'", "''") + "'"


class LakeConnection:
    """One DuckDB connection with the DuckLake catalog attached.

    `con` is the Ibis backend; `query` runs parameterized SQL on the raw
    DuckDB connection. DuckDB connections are not safe to share across
    threads, so `query` serializes access.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._con = None
        self._lock = Lock()

    @property
    def con(self):
        if self._con is None:
            raise RuntimeError("LakeConnection.connect() has not been called")
        return self._con

    def connect(self):
        if self._con is not None:
            return self._con

        s = self.settings
        con = ibis.duckdb.connect()
        con.raw_sql(f"SET memory_limit = {_sql_str(s.duckdb_memory_limit)}")
        con.raw_sql(f"SET threads = {int(s.duckdb_threads)}")
        con.raw_sql("INSTALL ducklake; LOAD ducklake; INSTALL httpfs; LOAD httpfs")

        # http:// endpoints (local Garage) turn TLS off; DuckDB wants the bare host.
        endpoint = s.s3_endpoint
        use_ssl = not endpoint.startswith("http://")
        endpoint = endpoint.removeprefix("http://").removeprefix("https://")
        con.raw_sql(
            "CREATE OR REPLACE SECRET lake_s3 ("
            "TYPE s3, "
            f"KEY_ID {_sql_str(s.s3_access_key.get_secret_value())}, "
            f"SECRET {_sql_str(s.s3_secret_key.get_secret_value())}, "
            f"ENDPOINT {_sql_str(endpoint)}, "
            f"REGION {_sql_str(s.s3_region)}, "
            f"USE_SSL {str(use_ssl).lower()}, "
            "URL_STYLE 'path')"
        )

        # A libpq DSN ("host=... dbname=...") means a PostgreSQL catalog.
        catalog = s.catalog_dsn
        if "=" in catalog:
            con.raw_sql("INSTALL postgres; LOAD postgres")
            catalog = f"postgres:{catalog}"
        options = [f"DATA_PATH {_sql_str(f's3://{s.s3_bucket}/')}"]
        if s.encryption_enabled:
            options.append("ENCRYPTED")
        con.raw_sql(f"ATTACH {_sql_str('ducklake:' + catalog)} AS lake ({', '.join(options)})")

        log.info("lake_connected", bucket=s.s3_bucket)
        self._con = con
        return con

    def query(self, sql: str, params: list | None = None) -> list[tuple]:
        """Run parameterized SQL (`?` placeholders) and return all rows."""
        with self._lock:
            return self.con.con.execute(sql, params or []).fetchall()

    def execute_many(self, sql: str, rows: list[list]) -> None:
        """Run sql once per row in one transaction, so the lake gets one snapshot.

        Outside a transaction every row commits on its own: one snapshot (and,
        past the inlining limit, one Parquet file) per row.
        """
        with self._lock:
            raw = self.con.con
            raw.begin()
            try:
                raw.executemany(sql, rows)
                raw.commit()
            except BaseException:
                raw.rollback()
                raise

    def snapshot_id(self) -> int:
        """Latest committed lake snapshot. It changes on every write, from any process."""
        rows = self.query("SELECT max(snapshot_id) FROM lake.snapshots()")
        return rows[0][0] or 0

    def close(self) -> None:
        if self._con is not None:
            self._con.disconnect()
            self._con = None


_connection: LakeConnection | None = None


def get_connection() -> LakeConnection:
    """The process-wide lake connection (created on first use, connected by the caller)."""
    global _connection
    if _connection is None:
        _connection = LakeConnection(get_settings())
    return _connection


__all__ = ["LakeConnection", "get_connection"]
