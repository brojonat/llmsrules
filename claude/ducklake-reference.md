# DuckLake Reference (v0.3)

Comprehensive reference for the DuckLake table format and DuckDB extension. Intended for agents working on the DuckVSS codebase.

## Architecture

DuckLake is an open lakehouse format built on two components:

1. **Catalog Database** -- A SQL database (PostgreSQL, DuckDB, SQLite, or MySQL) storing all metadata, statistics, and schema information in 22 relational tables.
2. **Data Storage** -- Parquet files on any storage backend (local filesystem, S3, R2, GCS, Azure Blob, NFS, etc.).

DuckLake is not a black box: all metadata is queryable SQL. Every mutation creates a **snapshot** (an immutable point-in-time state), enabling time travel, change feeds, and conflict resolution.

**Current status**: v0.3, not yet production-ready. 1.0 expected early 2026. MIT license.

---

## Installation & Connection

```sql
INSTALL ducklake;
LOAD ducklake;
```

### ATTACH Syntax

```sql
-- Local DuckDB catalog + local files
ATTACH 'ducklake:metadata.ducklake' AS my_lake;

-- PostgreSQL catalog + S3 storage
ATTACH 'ducklake:postgres:dbname=ducklake host=myhost' AS my_lake
    (DATA_PATH 's3://my-bucket/data/');

-- Read-only
ATTACH 'ducklake:postgres:dbname=ducklake' AS my_lake (READ_ONLY);

-- At a specific snapshot version
ATTACH 'ducklake:metadata.ducklake' AS my_lake (SNAPSHOT_VERSION 3);

-- At a specific timestamp
ATTACH 'ducklake:metadata.ducklake' AS my_lake (SNAPSHOT_TIME '2025-05-26 00:00:00');
```

### ATTACH Parameters

| Parameter | Description | Default |
|---|---|---|
| `DATA_PATH` | Storage location for Parquet files | Varies by catalog |
| `ENCRYPTED` | Enable Parquet encryption | `false` |
| `READ_ONLY` | Read-only connection | `false` |
| `SNAPSHOT_VERSION` | Connect at specific snapshot ID | latest |
| `SNAPSHOT_TIME` | Connect at specific timestamp | latest |
| `DATA_INLINING_ROW_LIMIT` | Max rows to inline in catalog | `0` |
| `OVERRIDE_DATA_PATH` | Override stored path for this session | `true` |
| `METADATA_SCHEMA` | Schema for DuckLake tables in catalog | `main` |
| `MIGRATE_IF_REQUIRED` | Auto-migrate catalog schema | `true` |

### Secrets

```sql
CREATE SECRET my_secret (
    TYPE ducklake,
    METADATA_PATH 'postgres:dbname=ducklake',
    DATA_PATH 's3://my-bucket/',
    METADATA_PARAMETERS MAP {'TYPE': 'postgres', 'SECRET': 'pg_secret'}
);
ATTACH 'ducklake:my_secret' AS my_lake;
```

### Detaching

```sql
USE memory;
DETACH my_lake;
```

---

## Catalog Database Options

| Backend | Use Case | Notes |
|---|---|---|
| **DuckDB** | Single-client local | Simplest; `.ducklake` file. No multi-client. |
| **SQLite** | Multi-client local | Requires `INSTALL sqlite;` Multi-process via retry. |
| **PostgreSQL** | Multi-user remote | Requires `INSTALL postgres;` PG 12+. DB must pre-exist. |
| **MySQL** | Multi-user remote | Requires `INSTALL mysql;` MySQL 8+. Known issues; not recommended. |

**PostgreSQL example** (most relevant to DuckVSS):
```sql
INSTALL ducklake;
INSTALL postgres;
ATTACH 'ducklake:postgres:dbname=ducklake_dev host=myhost port=5432 user=ducklake_dev password=secret'
    AS my_lake (DATA_PATH 's3://my-bucket/data/');
USE my_lake;
```

---

## Storage Options

DuckLake works with any DuckDB-supported filesystem:

- **Local**: filesystem paths
- **S3/R2/compatible**: `s3://bucket/path/` (configure via DuckDB S3 secrets)
- **GCS**: `gs://bucket/path/`
- **Azure Blob**: `az://container/path/`
- **HTTPS**: `https://host/path/` (read-only)

DuckLake **never modifies or appends to existing files**. All writes create new files.

### S3/R2 Secrets (for DuckDB)

```sql
CREATE SECRET (
    TYPE s3,
    KEY_ID 'your-access-key',
    SECRET 'your-secret-key',
    ENDPOINT 'your-endpoint.r2.cloudflarestorage.com',
    URL_STYLE 'path'
);
```

---

## Data Types

### Primitives
`int8`, `int16`, `int32`, `int64`, `uint8`, `uint16`, `uint32`, `uint64`, `float32`, `float64`, `decimal(P,S)`, `boolean`, `varchar`, `blob`, `json`, `uuid`, `date`, `time`, `timetz`, `timestamp`, `timestamptz`, `timestamp_s`, `timestamp_ms`, `timestamp_ns`, `interval`

### Nested
`list`, `struct`, `map`

### Geometry
`point`, `linestring`, `polygon`, `multipoint`, `multilinestring`, `multipolygon`, `linestring z`, `geometrycollection`

---

## Core Operations

### DDL

```sql
CREATE SCHEMA my_schema;
CREATE TABLE my_schema.tbl (id INTEGER NOT NULL, name VARCHAR, ts TIMESTAMP);
DROP TABLE my_schema.tbl;
DROP SCHEMA my_schema;  -- must be empty
```

### DML

```sql
INSERT INTO tbl VALUES (1, 'alice', now());
UPDATE tbl SET name = 'bob' WHERE id = 1;
DELETE FROM tbl WHERE id = 1;
```

### UPSERT via MERGE INTO

DuckLake has no primary keys, so upserts use `MERGE INTO`:

```sql
MERGE INTO target USING source
    ON target.id = source.id
    WHEN MATCHED THEN UPDATE SET name = source.name
    WHEN NOT MATCHED THEN INSERT VALUES (source.id, source.name);
```

Limitation: only one UPDATE/DELETE action per MERGE statement.

### Ad-hoc Queries

```sql
SELECT * FROM tbl WHERE ts > '2025-01-01';
```

---

## Schema Evolution

All changes are metadata-only (no file rewrites):

```sql
ALTER TABLE tbl ADD COLUMN new_col INTEGER;
ALTER TABLE tbl ADD COLUMN new_col VARCHAR DEFAULT 'hello';
ALTER TABLE tbl DROP COLUMN old_col;
ALTER TABLE tbl RENAME old_col TO new_name;
ALTER TABLE tbl ALTER col SET TYPE BIGINT;  -- lossless promotions only
ALTER TABLE tbl RENAME TO new_table_name;

-- Struct fields
ALTER TABLE tbl ADD COLUMN nested.new_field INTEGER;
ALTER TABLE tbl DROP COLUMN nested.old_field;
```

**Valid type promotions**: int8->int16/32/64, int16->int32/64, int32->int64, uint8->uint16/32/64, uint16->uint32/64, uint32->uint64, float32->float64

---

## Snapshots

Every committed transaction = one snapshot. Snapshots track all changes.

```sql
-- List all snapshots
SELECT * FROM my_lake.snapshots();

-- Current snapshot
FROM my_lake.current_snapshot();

-- Last committed snapshot
FROM my_lake.last_committed_snapshot();

-- Add metadata to a snapshot
BEGIN;
INSERT INTO tbl VALUES (1, 'data');
CALL my_lake.set_commit_message('author_name', 'Description of changes',
    extra_info => '{"key": "value"}');
COMMIT;
```

---

## Time Travel

```sql
-- By snapshot version
SELECT * FROM tbl AT (VERSION => 3);

-- By timestamp
SELECT * FROM tbl AT (TIMESTAMP => now() - INTERVAL '1 week');

-- Attach at specific point in time
ATTACH 'ducklake:metadata.ducklake' (SNAPSHOT_VERSION 3);
ATTACH 'ducklake:metadata.ducklake' (SNAPSHOT_TIME '2025-01-01 00:00:00');
```

---

## Data Change Feed

Query changes between two snapshots:

```sql
-- By snapshot IDs
FROM my_lake.table_changes('tbl', 2, 5);

-- By timestamps
FROM my_lake.table_changes('tbl', now() - INTERVAL '1 week', now());
```

Returns all table columns plus: `snapshot_id`, `rowid`, `change_type` (`insert`, `delete`, `update_preimage`, `update_postimage`).

---

## Partitioning

```sql
-- Partition by column
ALTER TABLE tbl SET PARTITIONED BY (region);

-- Partition by temporal function
ALTER TABLE tbl SET PARTITIONED BY (year(ts), month(ts));

-- Remove partitioning (affects new writes only)
ALTER TABLE tbl RESET PARTITIONED BY;
```

Partition functions: `identity`, `year()`, `month()`, `day()`, `hour()`.

Partitioning only affects new data. Old data retains its original layout. Hive-style partitioning is the default.

---

## Encryption

```sql
-- Enable at creation
ATTACH 'ducklake:metadata.ducklake' (DATA_PATH 's3://bucket/', ENCRYPTED);
```

- Auto-generates a unique key per file write
- Keys stored in `ducklake_data_file.encryption_key` in the catalog
- Transparent: encrypted lakes are used identically to unencrypted ones
- Uses Parquet encryption

---

## Data Inlining

Small inserts can be stored directly in the catalog database instead of creating Parquet files:

```sql
-- At connection time
ATTACH 'ducklake:metadata.ducklake' AS my_lake (DATA_INLINING_ROW_LIMIT 10);

-- Persistent setting
CALL my_lake.set_option('data_inlining_row_limit', 10);

-- Flush inlined data to Parquet files
CALL ducklake_flush_inlined_data('my_lake');
```

Note: data inlining is only supported with DuckDB catalogs.

---

## Transactions

DuckLake provides ACID compliance with snapshot isolation.

```sql
BEGIN TRANSACTION;
CREATE TABLE tbl (id INTEGER);
INSERT INTO tbl VALUES (1), (2);
COMMIT;
-- This creates one snapshot
```

### Conflict Resolution

Concurrent writes are detected via `snapshot_id` collisions. DuckLake auto-retries non-conflicting transactions (e.g., inserts to different tables). Conflicting operations (same table modified) will fail after retries.

```sql
SET ducklake_max_retry_count = 10;    -- default: 10
SET ducklake_retry_wait_ms = 100;     -- default: 100ms
SET ducklake_retry_backoff = 1.5;     -- default: 1.5x
```

---

## Constraints

Only `NOT NULL` is supported. No primary keys, foreign keys, unique, or check constraints.

```sql
CREATE TABLE tbl (id INTEGER NOT NULL, name VARCHAR);
ALTER TABLE tbl ALTER name SET NOT NULL;
ALTER TABLE tbl ALTER name DROP NOT NULL;
```

---

## Views & Comments

```sql
CREATE VIEW my_view AS SELECT * FROM tbl WHERE active = true;
COMMENT ON TABLE tbl IS 'Description of the table';
COMMENT ON COLUMN tbl.col IS 'Description of the column';
```

---

## Row Lineage

Every row gets a unique `rowid` that persists through updates, compaction, and file moves:

```sql
SELECT rowid, * FROM tbl;
```

---

## Metadata Functions

### List Files

```sql
FROM ducklake_list_files('my_lake', 'tbl');
FROM ducklake_list_files('my_lake', 'tbl', snapshot_version => 2);
FROM ducklake_list_files('my_lake', 'tbl', schema => 'main');
```

### Add External Parquet Files

```sql
CALL ducklake_add_data_files('my_lake', 'tbl', 'path/to/file.parquet');
CALL ducklake_add_data_files('my_lake', 'tbl', 'file.parquet', allow_missing => true);
CALL ducklake_add_data_files('my_lake', 'tbl', 'file.parquet', ignore_extra_columns => true);
```

Warning: DuckLake assumes ownership of registered files and may delete them during compaction.

---

## Maintenance

### All-in-One

```sql
CHECKPOINT;
```

Runs (in order): flush inlined data, expire snapshots, merge files, rewrite data files, cleanup old files, delete orphaned files.

### Individual Operations

**Merge small files** into larger ones:
```sql
CALL ducklake_merge_adjacent_files('my_lake');
CALL ducklake_merge_adjacent_files('my_lake', 'tbl', schema => 'main');
CALL ducklake_merge_adjacent_files('my_lake', 'tbl', max_compacted_files => 1000);
```

**Expire old snapshots** (required to physically delete data):
```sql
CALL ducklake_expire_snapshots('my_lake', older_than => now() - INTERVAL '1 week');
CALL ducklake_expire_snapshots('my_lake', versions => [2, 3]);
CALL ducklake_expire_snapshots('my_lake', dry_run => true, older_than => now() - INTERVAL '1 week');
```

**Clean up deleted files** (after expiring snapshots):
```sql
CALL ducklake_cleanup_old_files('my_lake', older_than => now() - INTERVAL '1 week');
CALL ducklake_cleanup_old_files('my_lake', cleanup_all => true);
CALL ducklake_cleanup_old_files('my_lake', dry_run => true);
```

**Delete orphaned files** (untracked by catalog):
```sql
CALL ducklake_delete_orphaned_files('my_lake', older_than => now() - INTERVAL '1 week');
CALL ducklake_delete_orphaned_files('my_lake', cleanup_all => true);
```

**Rewrite files with many deletes**:
```sql
CALL ducklake_rewrite_data_files('my_lake');
CALL ducklake_rewrite_data_files('my_lake', 'tbl', delete_threshold => 0.5);
```

### Persistent Maintenance Settings

```sql
CALL my_lake.set_option('expire_older_than', '1 month');
CALL my_lake.set_option('delete_older_than', '1 week');
CALL my_lake.set_option('rewrite_delete_threshold', 0.5);
```

### PostgreSQL Catalog

Run `VACUUM` periodically on the PostgreSQL catalog database to maintain performance.

---

## Configuration

### DuckLake-Specific Options (persistent, stored in catalog)

| Setting | Description | Default |
|---|---|---|
| `data_inlining_row_limit` | Max rows to inline | `0` |
| `parquet_compression` | Compression: uncompressed, snappy, gzip, zstd, brotli, lz4, lz4_raw | `snappy` |
| `parquet_version` | Parquet format version (1 or 2) | `1` |
| `parquet_compression_level` | Compression intensity | `3` |
| `parquet_row_group_size` | Rows per row group | `122880` |
| `target_file_size` | Target file size for writes/compaction | `512MB` |
| `hive_file_pattern` | Hive-style folder structure | `true` |
| `require_commit_message` | Enforce commit messages | `false` |
| `rewrite_delete_threshold` | Deletion fraction triggering rewrites (0-1) | `0.95` |
| `encrypted` | Enable Parquet encryption | `false` |
| `per_thread_output` | Separate output files per thread | `false` |

Settings have priority: Table > Schema > Global > Default.

```sql
-- Set globally
CALL my_lake.set_option('parquet_compression', 'zstd');

-- Set per-table
CALL my_lake.set_option('target_file_size', '256MB', table_name => 'big_table');
```

---

## Path Structure

DuckLake organizes files hierarchically:

```
<root_data_path>/
  <schema_name>/
    <table_name>/
      ducklake-<uuid>.parquet          # unpartitioned
      year=2025/ducklake-<uuid>.parquet # hive-partitioned
```

Paths are stored as relative by default (via `path_is_relative` column).

---

## Access Control

DuckLake relies on the catalog database and storage permissions for access control. Three roles:

| Role | Catalog Permissions | Storage Permissions |
|---|---|---|
| **Superuser** | CREATE, SELECT, INSERT, UPDATE, DELETE | ListBucket, GetObject, PutObject, DeleteObject |
| **Writer** | SELECT, INSERT, UPDATE, DELETE | ListBucket, GetObject, PutObject, DeleteObject (scoped to schema/table paths) |
| **Reader** | SELECT only | GetObject only (scoped to table paths) |

---

## Migration from DuckDB

```sql
ATTACH 'ducklake:my_lake.ducklake' AS my_lake;
ATTACH 'existing.duckdb' AS old_db;
COPY FROM DATABASE old_db TO my_lake;
```

Incompatible features requiring manual handling: ENUM/UNION types (cast to VARCHAR), non-literal defaults, macros, generated columns.

---

## Catalog Tables (22 total)

| Category | Tables |
|---|---|
| Snapshots | `ducklake_snapshot`, `ducklake_snapshot_changes` |
| Schema | `ducklake_schema`, `ducklake_table`, `ducklake_view`, `ducklake_column` |
| Data files | `ducklake_data_file`, `ducklake_delete_file`, `ducklake_files_scheduled_for_deletion`, `ducklake_inlined_data_tables` |
| File mapping | `ducklake_column_mapping`, `ducklake_name_mapping` |
| Statistics | `ducklake_table_stats`, `ducklake_table_column_stats`, `ducklake_file_column_stats` |
| Partitioning | `ducklake_partition_info`, `ducklake_partition_column`, `ducklake_file_partition_value` |
| Auxiliary | `ducklake_metadata`, `ducklake_tag`, `ducklake_column_tag`, `ducklake_schema_versions` |

---

## Unsupported Features

**By specification** (may never be supported): indexes, primary/foreign/unique keys, sequences, VARINT, BITSTRING, UNION types.

**By specification** (may be supported later): ENUM, CHECK constraints, macros, non-literal defaults, CASCADE, generated columns.

**By DuckDB extension**: data inlining only with DuckDB catalogs, MySQL catalogs have known issues, no multi-row updates targeting same row.

---

## Backups

Catalog and storage must be backed up separately:

- **Catalog**: use `COPY FROM DATABASE` to create backup copies, or PostgreSQL-native pg_dump/PITR
- **Storage**: use cloud provider replication, versioning, or backup services
- **Important**: run compaction/cleanup *before* manual backups, not after

---

## Key Differences from Plain DuckDB

- No indexes, primary keys, foreign keys, unique constraints, or check constraints
- `MERGE INTO` instead of `INSERT ... ON CONFLICT`
- Every transaction creates a snapshot
- Schema changes are metadata-only (no file rewrites)
- Deletes use merge-on-read (delete files, not in-place mutation)
- Updates = DELETE + INSERT in one transaction
