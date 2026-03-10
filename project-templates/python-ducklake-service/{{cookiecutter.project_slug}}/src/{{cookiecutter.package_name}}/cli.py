"""CLI for {{cookiecutter.project_name}}."""

import sys

import click

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
def cli() -> None:
    """{{cookiecutter.description}}"""
    pass


@cli.command()
@click.option("--host", default=None, help="Host to bind to.")
@click.option("--port", type=int, default=None, help="Port to bind to.")
@click.option("--reload", is_flag=True, help="Enable auto-reload.")
def serve(host: str | None, port: int | None, reload: bool) -> None:
    """Start the web server."""
    import uvicorn
    from server.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "server.main:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


@cli.command()
def migrate() -> None:
    """Run pending database migrations (lake + app)."""
    from migrations import MigrationRunner
    from migrations.lake import LAKE_MIGRATIONS
    from server.data import get_connection
    from server.data.app_db import get_app_db
    from server.log_config import configure_logging

    configure_logging(json_format=False, level="INFO")

    # Read app migration SQL files
    from pathlib import Path

    sql_dir = Path(__file__).resolve().parent.parent.parent / "migrations" / "app"
    from migrations.runner import Migration

    app_migrations = []
    # Find all .up.sql files and create migrations
    up_files = sorted(sql_dir.glob("*.up.sql"))
    for f in up_files:
        # Parse version from filename: 001_name.up.sql -> version=1, name=name
        parts = f.stem.replace(".up", "").split("_", 1)
        version = int(parts[0])
        name = parts[1] if len(parts) > 1 else f.stem
        app_migrations.append(Migration(version=version, name=name, up=f.read_text()))

    # Lake migrations — tracked and executed in DuckDB (via DuckLake catalog)
    lake_conn = get_connection()
    lake_con = lake_conn.connect()

    lake_runner = MigrationRunner(lake_con, namespace="lake")
    applied = lake_runner.run(LAKE_MIGRATIONS, target_con=lake_con)
    if applied:
        click.echo(f"Applied {len(applied)} lake migration(s):")
        for m in applied:
            click.echo(f"  {m.version}: {m.name}")
    else:
        click.echo("Lake migrations up to date.")

    # App migrations — tracked and executed in the app PostgreSQL database
    app_db = get_app_db()
    app_db.connect()

    app_runner = MigrationRunner(app_db, namespace="app")
    applied = app_runner.run(app_migrations)
    if applied:
        click.echo(f"Applied {len(applied)} app migration(s):")
        for m in applied:
            click.echo(f"  {m.version}: {m.name}")
    else:
        click.echo("App migrations up to date.")


# --- Lake admin commands ---


@cli.group()
def lake() -> None:
    """Lake administration commands."""
    pass


@lake.command("list")
def lake_list() -> None:
    """List tables in the lake catalog."""
    from server.lake_admin import list_lake_tables
    from server.log_config import configure_logging

    configure_logging(json_format=False, level="INFO")

    try:
        tables = list_lake_tables()
        if tables:
            click.echo("Tables in lake catalog:")
            for table in tables:
                click.echo(f"  - {table}")
        else:
            click.echo("No tables found in lake catalog.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@lake.command("reset")
@click.option("--dry-run", is_flag=True, help="Preview what would be deleted.")
@click.option("--confirm", is_flag=True, help="Required to actually delete data.")
def lake_reset(dry_run: bool, confirm: bool) -> None:
    """Drop all tables and delete all S3 data."""
    from server.lake_admin import reset_lake
    from server.log_config import configure_logging

    configure_logging(json_format=False, level="INFO")

    if not dry_run and not confirm:
        click.echo(
            "ERROR: Must pass --confirm to reset lake.\n"
            "This operation will DELETE ALL DATA and cannot be undone.\n"
            "Use --dry-run to preview what would be deleted.",
            err=True,
        )
        sys.exit(1)

    try:
        result = reset_lake(dry_run=dry_run, confirm=confirm)
        prefix = "[DRY RUN] " if result["dry_run"] else ""
        click.echo(f"\n{prefix}Lake reset complete:")
        click.echo(f"  Tables dropped: {result['tables_dropped']}")
        click.echo(f"  S3 objects deleted: {result['objects_deleted']}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@lake.command("snapshots")
def lake_snapshots() -> None:
    """List snapshots in the lake catalog."""
    from server.data import get_connection
    from server.log_config import configure_logging

    configure_logging(json_format=False, level="INFO")

    try:
        lake_conn = get_connection()
        lake_con = lake_conn.connect()
        rows = lake_con.raw_sql("SELECT * FROM lake.snapshots()").fetchall()
        if rows:
            desc = lake_con.raw_sql("DESCRIBE SELECT * FROM lake.snapshots()").fetchall()
            col_names = [d[0] for d in desc]
            click.echo(f"{'  '.join(col_names)}")
            click.echo("-" * 80)
            for row in rows:
                click.echo(f"{'  '.join(str(v) for v in row)}")
        else:
            click.echo("No snapshots found.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# --- App admin commands ---


@cli.group()
def app() -> None:
    """App database administration."""
    pass


@app.command("reset")
@click.option("--confirm", is_flag=True, help="Required to actually drop tables.")
def app_reset(confirm: bool) -> None:
    """Drop all app tables and re-run migrations."""
    from pathlib import Path

    from migrations import MigrationRunner
    from migrations.runner import Migration
    from server.data.app_db import get_app_db
    from server.log_config import configure_logging

    configure_logging(json_format=False, level="INFO")

    if not confirm:
        click.echo(
            "ERROR: Must pass --confirm to reset app database.\n"
            "This will drop all app tables (users, sessions, tags, etc.) "
            "and re-run migrations.",
            err=True,
        )
        sys.exit(1)

    try:
        app_db = get_app_db()
        app_db.connect()

        # Drop all app tables with CASCADE
        app_tables = [
            "entity_tags",
            "tags",
            "sessions",
            "users",
        ]

        for table in app_tables:
            app_db.raw_sql(f"DROP TABLE IF EXISTS {table} CASCADE")
            click.echo(f"  Dropped: {table}")

        # Clear app migration tracking
        try:
            app_db.raw_sql("DELETE FROM _migrations WHERE namespace = 'app'")
            click.echo("  Cleared app migration history")
        except Exception:
            pass  # _migrations table may not exist on first run

        # Re-run app migrations
        sql_dir = Path(__file__).resolve().parent.parent.parent / "migrations" / "app"
        app_migrations = []
        up_files = sorted(sql_dir.glob("*.up.sql"))
        for f in up_files:
            parts = f.stem.replace(".up", "").split("_", 1)
            version = int(parts[0])
            name = parts[1] if len(parts) > 1 else f.stem
            app_migrations.append(Migration(version=version, name=name, up=f.read_text()))

        runner = MigrationRunner(app_db, namespace="app")
        applied = runner.run(app_migrations)
        if applied:
            click.echo(f"\nApplied {len(applied)} migration(s):")
            for m in applied:
                click.echo(f"  {m.version}: {m.name}")
        click.echo("\nApp database reset complete.")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
