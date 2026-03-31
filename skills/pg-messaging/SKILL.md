---
name: pg-messaging
description:
  Build pub/sub and task queue services using PostgreSQL as the backend. Use
  when implementing messaging primitives, log-based consumer groups, job queues
  with SKIP LOCKED, or replacing external message brokers (Kafka, RabbitMQ, SQS)
  with Postgres.
---

# Postgres Messaging Primitives

Pure-SQL pub/sub and task queue implementations using PostgreSQL. No external
message brokers required. All logic lives in SQL — clients connect directly, or
through a thin HTTP/gRPC layer.

## Core Principles

- **SQL is the API**: All messaging logic is implemented as SQL queries, not
  application code
- **Atomic by default**: Writes reserve offsets and insert messages in a single
  transaction
- **Consumer groups**: Log-based pub/sub with per-group offset tracking,
  inspired by Kafka
- **Lock-free queues**: `SELECT FOR UPDATE SKIP LOCKED` for contention-free job
  claiming
- **Flexible access**: Direct Postgres connections, HTTP wrapper, or
  auto-generated API (PostgREST)

## Pub/Sub System

A log-based pub/sub with monotonically increasing offsets per consumer group.

### Schema

```sql
-- Tracks the next available offset for each topic
CREATE TABLE log_counter (
  id           INT PRIMARY KEY,
  next_offset  BIGINT NOT NULL
);

-- Initialize counter for topic 0 (add more for additional topics)
INSERT INTO log_counter (id, next_offset) VALUES (0, 1);

-- Topic log table
CREATE TABLE topic (
  id          BIGSERIAL PRIMARY KEY,
  topic_id    INT NOT NULL,
  c_offset    BIGINT NOT NULL,
  payload     BYTEA NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (topic_id, c_offset)
);

-- Consumer group offset tracking (per topic)
CREATE TABLE consumer_offsets (
  group_id     TEXT NOT NULL,
  topic_id     INT NOT NULL,
  next_offset  BIGINT NOT NULL DEFAULT 1,
  PRIMARY KEY (group_id, topic_id)
);
```

### Publish Messages

Atomically reserves offsets and inserts messages in a single transaction:

```sql
-- Parameters:
--   $1 = number of messages (batch size)
--   $2 = array of message payloads (bytea[])
--   $3 = topic_id (int)

WITH reserve AS (
  UPDATE log_counter
  SET next_offset = next_offset + $1
  WHERE id = $3::int
  RETURNING (next_offset - $1) AS first_off
)
INSERT INTO topic(topic_id, c_offset, payload)
SELECT $3::int, r.first_off + p.ord - 1, p.payload
FROM reserve r,
     unnest($2::bytea[]) WITH ORDINALITY AS p(payload, ord);
```

### Initialize Consumer Group

Consumer groups must be initialized before first use:

```sql
INSERT INTO consumer_offsets (group_id, topic_id, next_offset)
VALUES ('my-consumer-group', 0, 1)
ON CONFLICT (group_id, topic_id) DO NOTHING;
```

### Claim Offsets

Atomically claims a range of offsets for a consumer group:

```sql
-- Parameters:
--   $1 = consumer group_id (text)
--   $2 = max number of messages to claim (bigint)
--   $3 = topic_id (int)

WITH counter_tip AS (
  SELECT (next_offset - 1) AS highest_committed_offset
  FROM log_counter
  WHERE id = $3::int
),
to_claim AS (
  SELECT
    c.group_id,
    c.next_offset AS n0,
    LEAST($2::bigint, GREATEST(0,
      (SELECT highest_committed_offset FROM counter_tip) -
      c.next_offset + 1)) AS delta
  FROM consumer_offsets c
  WHERE c.group_id = $1::text AND c.topic_id = $3::int
  FOR UPDATE
),
upd AS (
  UPDATE consumer_offsets c
  SET next_offset = c.next_offset + t.delta
  FROM to_claim t
  WHERE c.group_id = t.group_id AND c.topic_id = $3::int
  RETURNING t.n0 AS claimed_start_offset,
    (c.next_offset - 1) AS claimed_end_offset
)
SELECT claimed_start_offset, claimed_end_offset FROM upd;
```

### Fetch Messages

After claiming offsets, retrieve the actual messages:

```sql
-- Parameters:
--   $1 = start offset (from claim operation)
--   $2 = end offset (from claim operation)
--   $3 = topic_id (int)

SELECT c_offset, payload, created_at
FROM topic
WHERE topic_id = $3::int AND c_offset BETWEEN $1 AND $2
ORDER BY c_offset;
```

## Queue System

A task queue using `SELECT FOR UPDATE SKIP LOCKED` for lock-free job claiming
across multiple workers.

### Schema

```sql
CREATE TABLE queue (
  id BIGSERIAL PRIMARY KEY,
  payload BYTEA NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE queue_archive (
  id BIGINT,
  payload BYTEA NOT NULL,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### Enqueue

```sql
INSERT INTO queue (payload) VALUES ($1);
```

### Claim and Process

Run within a single transaction:

```sql
BEGIN;

-- Claim a job (lock-free with SKIP LOCKED)
SELECT id, payload, created_at
FROM queue
ORDER BY id
FOR UPDATE SKIP LOCKED
LIMIT 1;

-- Archive the processed job
DELETE FROM queue WHERE id = $1;
INSERT INTO queue_archive (id, payload, created_at, processed_at)
VALUES ($1, $2, $3, NOW());

COMMIT;
```

A single CTE version for sqlc compatibility:

```sql
WITH deleted AS (
  DELETE FROM queue WHERE id = $1 RETURNING *
)
INSERT INTO queue_archive (id, payload, created_at)
SELECT id, payload, created_at FROM deleted;
```

## Using with sqlc

Both systems work with sqlc out of the box. Example query annotations:

```sql
-- name: PublishMessages :exec
WITH reserve AS (
  UPDATE log_counter
  SET next_offset = next_offset + $1
  WHERE id = $3::int
  RETURNING (next_offset - $1) AS first_off
)
INSERT INTO topic(topic_id, c_offset, payload)
SELECT $3::int, r.first_off + p.ord - 1, p.payload
FROM reserve r,
     unnest($2::bytea[]) WITH ORDINALITY AS p(payload, ord);

-- name: ClaimOffsets :one
WITH counter_tip AS (
  SELECT (next_offset - 1) AS highest_committed_offset
  FROM log_counter WHERE id = $3::int
),
to_claim AS (
  SELECT c.group_id, c.next_offset AS n0,
    LEAST($2::bigint, GREATEST(0,
      (SELECT highest_committed_offset FROM counter_tip) - c.next_offset + 1
    )) AS delta
  FROM consumer_offsets c
  WHERE c.group_id = $1::text AND c.topic_id = $3::int
  FOR UPDATE
),
upd AS (
  UPDATE consumer_offsets c
  SET next_offset = c.next_offset + t.delta
  FROM to_claim t
  WHERE c.group_id = t.group_id AND c.topic_id = $3::int
  RETURNING t.n0 AS claimed_start_offset, (c.next_offset - 1) AS claimed_end_offset
)
SELECT claimed_start_offset, claimed_end_offset FROM upd;

-- name: GetMessages :many
SELECT c_offset, payload, created_at
FROM topic
WHERE topic_id = $3::int AND c_offset BETWEEN $1 AND $2
ORDER BY c_offset;

-- name: EnqueueJob :exec
INSERT INTO queue (payload) VALUES ($1);

-- name: ClaimJob :one
SELECT id, payload, created_at
FROM queue
ORDER BY id
FOR UPDATE SKIP LOCKED
LIMIT 1;

-- name: ArchiveJob :exec
WITH deleted AS (
  DELETE FROM queue WHERE id = $1 RETURNING *
)
INSERT INTO queue_archive (id, payload, created_at)
SELECT id, payload, created_at FROM deleted;
```

## Architecture Patterns

### Direct Postgres Connection

Clients use native drivers (pgx, psycopg2, node-postgres) and execute the SQL
directly. Simplest architecture — no additional services. Best when clients
already have database access.

### HTTP/API Wrapper

A thin Go/Python/Rust service wraps the SQL and exposes REST/gRPC endpoints:

```http
POST /pubsub/publish
GET  /pubsub/consume
POST /queue/enqueue
GET  /queue/claim
```

Better security boundary, connection pooling, and authentication.

## Operational Considerations

- **Topics**: Create an entry in `log_counter` for each topic (topic_id 0, 1, 2,
  etc.)
- **Connection pooling**: Essential for performance — use pgbouncer or similar
- **Monitoring**: Track consumer lag per topic, queue depth, message throughput
- **Vacuuming**: Regular VACUUM on queue and archive tables to reclaim space
- **Indexes**: The UNIQUE constraint on `(topic_id, c_offset)` creates an index
  automatically

## Scaling

- **Vertical**: 4vCPU handles ~5k writes/s and ~25k reads/s; 96vCPU handles
  ~243k writes/s and ~1.2M reads/s
- **Read replicas**: Offload consumer reads to replicas
- **Multiple topics**: Already supported — add more topic_ids to `log_counter`
- **Topic partitioning**: Split a high-volume topic across multiple physical
  tables to reduce lock contention on a single `log_counter` entry

## Key Patterns

- Always initialize consumer groups before first read
- Publish uses a two-phase approach: reserve offsets in `log_counter`, then bulk
  insert
- Claim + fetch are separate operations — claim is the atomic coordination
  point, fetch is a simple range query
- Queue claim uses `SKIP LOCKED` so blocked workers never wait — they just get
  the next available job
- Archive processed queue jobs rather than deleting them to preserve audit
  history
