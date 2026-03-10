"""DuckLake table migrations.

These run against DuckDB with a DuckLake catalog attached.
DuckLake has no indexes, primary keys, or unique constraints --
uniqueness is enforced at the application layer.
"""

from migrations.runner import Migration

LAKE_MIGRATIONS: list[Migration] = [
    Migration(
        version=1,
        name="events",
        up="""
            CREATE TABLE IF NOT EXISTS lake.events (
                timestamp TIMESTAMP NOT NULL,
                entity_id VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL,
                value DOUBLE,
                value_string VARCHAR,
                metadata JSON,
                date VARCHAR
            )
        """,
    ),
]
