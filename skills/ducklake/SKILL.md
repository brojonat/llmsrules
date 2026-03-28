---
name: ducklake
description: Work with DuckLake, an open lakehouse format built on DuckDB. Use when creating or querying DuckLake tables, managing snapshots, time travel, schema evolution, partitioning, or lakehouse maintenance operations.
---

# DuckLake

DuckLake is an open lakehouse format with a SQL catalog database (PostgreSQL, DuckDB, SQLite) and Parquet data files on any storage backend (local, S3, R2, GCS, Azure).

Every mutation creates an immutable **snapshot**, enabling time travel, change feeds, and conflict resolution.

## Installation & Connection

```sql
INSTALL ducklake;
LOAD ducklake;

-- Local DuckDB catalog + local files
ATTACH 'ducklake:metadata.ducklake' AS my_lake;

-- PostgreSQL catalog + S3 storage
ATTACH 'ducklake:postgres:dbname=ducklake host=myhost' AS my_lake
    (DATA_PATH 's3://my-bucket/data/');

-- Read-only / at specific snapshot
ATTACH 'ducklake:metadata.ducklake' AS my_lake (READ_ONLY);
ATTACH 'ducklake:metadata.ducklake' AS my_lake (SNAPSHOT_VERSION 3);
ATTACH 'ducklake:metadata.ducklake' AS my_lake (SNAPSHOT_TIME '2025-05-26 00:00:00');
```

## Core Operations

```sql
-- DDL
CREATE SCHEMA my_schema;
CREATE TABLE my_schema.tbl (id INTEGER NOT NULL, name VARCHAR, ts TIMESTAMP);

-- DML
INSERT INTO tbl VALUES (1, 'alice', now());
UPDATE tbl SET name = 'bob' WHERE id = 1;
DELETE FROM tbl WHERE id = 1;

-- Upsert via MERGE INTO (no primary keys in DuckLake)
MERGE INTO target USING source
    ON target.id = source.id
    WHEN MATCHED THEN UPDATE SET name = source.name
    WHEN NOT MATCHED THEN INSERT VALUES (source.id, source.name);
```

## Schema Evolution

All changes are metadata-only (no file rewrites):

```sql
ALTER TABLE tbl ADD COLUMN new_col INTEGER;
ALTER TABLE tbl ADD COLUMN new_col VARCHAR DEFAULT 'hello';
ALTER TABLE tbl DROP COLUMN old_col;
ALTER TABLE tbl RENAME old_col TO new_name;
ALTER TABLE tbl ALTER col SET TYPE BIGINT;  -- lossless promotions only
```

Valid type promotions: int8->int16/32/64, int16->int32/64, int32->int64, float32->float64.

## Snapshots & Time Travel

```sql
-- List / inspect snapshots
SELECT * FROM my_lake.snapshots();
FROM my_lake.current_snapshot();

-- Add metadata to a snapshot
BEGIN;
INSERT INTO tbl VALUES (1, 'data');
CALL my_lake.set_commit_message('author', 'Description', extra_info => '{"key": "value"}');
COMMIT;

-- Time travel
SELECT * FROM tbl AT (VERSION => 3);
SELECT * FROM tbl AT (TIMESTAMP => now() - INTERVAL '1 week');

-- Change feed between snapshots
FROM my_lake.table_changes('tbl', 2, 5);
FROM my_lake.table_changes('tbl', now() - INTERVAL '1 week', now());
```

## Partitioning

```sql
ALTER TABLE tbl SET PARTITIONED BY (region);
ALTER TABLE tbl SET PARTITIONED BY (year(ts), month(ts));
ALTER TABLE tbl RESET PARTITIONED BY;
```

Functions: `identity`, `year()`, `month()`, `day()`, `hour()`. Only affects new data.

## Maintenance

```sql
-- All-in-one
CHECKPOINT;

-- Individual operations
CALL ducklake_merge_adjacent_files('my_lake');
CALL ducklake_expire_snapshots('my_lake', older_than => now() - INTERVAL '1 week');
CALL ducklake_cleanup_old_files('my_lake', older_than => now() - INTERVAL '1 week');
CALL ducklake_delete_orphaned_files('my_lake', older_than => now() - INTERVAL '1 week');
CALL ducklake_rewrite_data_files('my_lake', 'tbl', delete_threshold => 0.5);
```

## Configuration

```sql
-- Persistent settings (stored in catalog)
CALL my_lake.set_option('parquet_compression', 'zstd');
CALL my_lake.set_option('target_file_size', '256MB', table_name => 'big_table');
```

Key settings: `parquet_compression` (snappy/zstd/gzip), `target_file_size` (512MB), `data_inlining_row_limit` (0), `encrypted` (false), `require_commit_message` (false).

## Key Differences from Plain DuckDB

- No indexes, primary keys, foreign keys, unique constraints, or check constraints
- `MERGE INTO` instead of `INSERT ... ON CONFLICT`
- Every transaction creates a snapshot
- Schema changes are metadata-only
- Deletes use merge-on-read (delete files, not in-place mutation)
- Updates = DELETE + INSERT in one transaction
- Only `NOT NULL` constraint is supported
