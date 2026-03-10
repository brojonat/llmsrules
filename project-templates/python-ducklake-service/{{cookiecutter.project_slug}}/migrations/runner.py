"""Migration runner with version tracking.

Executes DDL statements and tracks applied versions in a _migrations table.
Supports separate namespaces (e.g., "app" vs "lake") so different migration
tracks can be managed independently while sharing the same tracking table.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from server.log_config import get_logger

log = get_logger(__name__)


@dataclass
class Migration:
    """A single migration step."""

    version: int
    name: str
    up: str  # SQL DDL (may contain multiple semicolon-separated statements)


class MigrationRunner:
    """Runs migrations and tracks state.

    Args:
        tracking_con: Connection where _migrations table lives.
        namespace: Namespace string to isolate migration tracks (e.g., "app", "lake").
    """

    def __init__(self, tracking_con, namespace: str):
        self.tracking_con = tracking_con
        self.namespace = namespace

    def ensure_tracking_table(self) -> None:
        """Create the _migrations table if it doesn't exist."""
        self.tracking_con.raw_sql("""
            CREATE TABLE IF NOT EXISTS _migrations (
                version INTEGER NOT NULL,
                name VARCHAR NOT NULL,
                namespace VARCHAR NOT NULL,
                applied_at TIMESTAMP NOT NULL,
                PRIMARY KEY (version, namespace)
            )
        """)

    def get_current_version(self) -> int:
        """Get the highest applied migration version for this namespace."""
        self.ensure_tracking_table()
        result = self.tracking_con.raw_sql(
            f"SELECT COALESCE(MAX(version), 0) FROM _migrations "
            f"WHERE namespace = '{self.namespace}'"
        ).fetchone()
        return result[0]

    def get_pending(self, migrations: list[Migration]) -> list[Migration]:
        """Return migrations that haven't been applied yet."""
        current = self.get_current_version()
        return sorted(
            [m for m in migrations if m.version > current],
            key=lambda m: m.version,
        )

    def run(
        self,
        migrations: list[Migration],
        target_con=None,
    ) -> list[Migration]:
        """Apply pending migrations.

        Args:
            migrations: Full list of migrations (already-applied ones are skipped).
            target_con: Connection to execute DDL against. Defaults to tracking_con.
                        Use this for lake migrations where DDL runs on DuckDB but
                        tracking happens in the app database.

        Returns:
            List of migrations that were applied.
        """
        if target_con is None:
            target_con = self.tracking_con

        self.ensure_tracking_table()
        pending = self.get_pending(migrations)

        if not pending:
            log.info("no_pending_migrations", namespace=self.namespace)
            return []

        applied = []
        for migration in pending:
            log.info(
                "applying_migration",
                namespace=self.namespace,
                version=migration.version,
                name=migration.name,
            )

            # Execute DDL statements against target connection
            for statement in migration.up.split(";"):
                statement = statement.strip()
                if statement:
                    target_con.raw_sql(statement)

            # Record in tracking table
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            self.tracking_con.raw_sql(
                f"INSERT INTO _migrations (version, name, namespace, applied_at) "
                f"VALUES ({migration.version}, '{migration.name}', "
                f"'{self.namespace}', '{now}')"
            )

            applied.append(migration)
            log.info(
                "migration_applied",
                namespace=self.namespace,
                version=migration.version,
                name=migration.name,
            )

        return applied
