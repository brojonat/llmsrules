"""Database migration system.

Two migration tracks:
- App migrations: DDL against PostgreSQL (users, sessions, etc.)
- Lake migrations: DDL against DuckLake via DuckDB (events, etc.)

Both are tracked in the app database's _migrations table.
"""

from migrations.runner import Migration, MigrationRunner

__all__ = ["Migration", "MigrationRunner"]
