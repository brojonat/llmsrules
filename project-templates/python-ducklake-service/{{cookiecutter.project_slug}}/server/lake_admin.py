"""Lake administration utilities."""

import boto3
from botocore.config import Config

from server.config import get_settings
from server.data import get_connection
from server.log_config import get_logger

log = get_logger(__name__)


def get_s3_client():
    """Create S3 client from settings."""
    settings = get_settings()

    # Parse endpoint for boto3
    endpoint = settings.s3_endpoint
    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"https://{endpoint}"

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def list_lake_tables() -> list[str]:
    """List all tables in the lake catalog."""
    conn = get_connection()
    con = conn.connect()

    result = con.raw_sql(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_catalog = 'lake' AND table_schema = 'main'"
    ).fetchall()

    return [row[0] for row in result]


def drop_all_tables(dry_run: bool = False) -> list[str]:
    """Drop all tables in the lake catalog.

    Args:
        dry_run: If True, only list tables without dropping.

    Returns:
        List of dropped (or would-be-dropped) table names.
    """
    conn = get_connection()
    con = conn.connect()

    tables = list_lake_tables()

    if not tables:
        log.info("no_tables_to_drop")
        return []

    for table in tables:
        if dry_run:
            log.info("would_drop_table", table=table)
        else:
            log.info("dropping_table", table=table)
            con.raw_sql(f"DROP TABLE IF EXISTS lake.{table}")

    return tables


def delete_s3_objects(dry_run: bool = False) -> int:
    """Delete all objects from the lake S3 bucket.

    Args:
        dry_run: If True, only count objects without deleting.

    Returns:
        Number of deleted (or would-be-deleted) objects.
    """
    settings = get_settings()
    s3 = get_s3_client()
    bucket = settings.s3_bucket

    deleted_count = 0
    paginator = s3.get_paginator("list_objects_v2")

    try:
        for page in paginator.paginate(Bucket=bucket):
            if "Contents" not in page:
                continue

            objects = page["Contents"]

            if dry_run:
                for obj in objects:
                    log.info("would_delete_object", key=obj["Key"])
                    deleted_count += 1
            else:
                # Delete in batches of 1000 (S3 limit)
                delete_keys = [{"Key": obj["Key"]} for obj in objects]
                if delete_keys:
                    s3.delete_objects(Bucket=bucket, Delete={"Objects": delete_keys})
                    for obj in objects:
                        log.info("deleted_object", key=obj["Key"])
                    deleted_count += len(delete_keys)

    except s3.exceptions.NoSuchBucket:
        log.warning("bucket_not_found", bucket=bucket)
        return 0

    return deleted_count


def reset_lake(dry_run: bool = False, confirm: bool = False) -> dict:
    """Reset the entire lake - drop all tables and delete all S3 data.

    Args:
        dry_run: If True, only show what would be deleted.
        confirm: Must be True to actually delete (unless dry_run).

    Returns:
        Dict with counts of dropped tables and deleted objects.
    """
    if not dry_run and not confirm:
        raise ValueError(
            "Must pass confirm=True to reset lake. "
            "This operation is destructive and cannot be undone."
        )

    settings = get_settings()

    log.info(
        "lake_reset_starting",
        dry_run=dry_run,
        bucket=settings.s3_bucket,
        catalog_dsn=settings.catalog_dsn[:50] + "..."
        if len(settings.catalog_dsn) > 50
        else settings.catalog_dsn,
    )

    # Drop tables first (catalog metadata)
    tables = drop_all_tables(dry_run=dry_run)

    # Delete S3 objects (actual data)
    deleted_objects = delete_s3_objects(dry_run=dry_run)

    result = {
        "tables_dropped": len(tables),
        "objects_deleted": deleted_objects,
        "dry_run": dry_run,
    }

    if dry_run:
        log.info("lake_reset_dry_run_complete", **result)
    else:
        log.info("lake_reset_complete", **result)

    return result
