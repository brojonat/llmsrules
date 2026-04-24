---
name: honker
description:
  Add cross-process pub/sub, durable task queues, event streams, and scheduled
  jobs to a SQLite database using the honker extension. Use when you need
  Postgres NOTIFY/LISTEN semantics, background job processing, or event-driven
  architecture without leaving SQLite. Supports Python, Node, Go, Rust, Ruby,
  Bun, and Elixir via language bindings, or raw SQL via the loadable extension.
---

# Honker: Postgres-Style Messaging for SQLite

Honker is a SQLite extension plus language bindings that brings Postgres
NOTIFY/LISTEN semantics to SQLite. You get push-style event delivery with
single-digit millisecond latency, durable work queues with retries and
dead-letter handling, event streams with per-consumer offsets, and a
leader-elected periodic task scheduler — all stored in your existing `.db` file
with no external daemon or broker.

## When to use this skill

- You want **cross-process pub/sub** without a message broker
- You need a **background job queue** with retries, priorities, and dead-letter
- You want **event streams** with per-consumer offset tracking (Kafka-like)
- You need **transactional outbox** — enqueue jobs/events atomically with
  business writes
- You want **periodic/cron tasks** with leader election
- Your application already uses SQLite and you don't want to add Postgres or
  Redis just for messaging

## When NOT to use this skill

- You need **multi-machine replication** — SQLite is single-host; use Postgres
- You need **workflow DAGs** (task chaining, pipelines, chords) — use Temporal
- You're already on Postgres — use the `pg-messaging` skill instead
- You need sub-millisecond latency — honker's wake latency is 1-5ms typical

---

# Architecture

## WAL-based signaling

Honker requires `PRAGMA journal_mode = WAL`. It monitors the `.db-wal` sidecar
file using `stat(2)` polling at ~1ms granularity. When any process commits a
write, the WAL file's size/mtime changes, and honker fans out async
notifications to all subscribers on that database.

`stat(2)` takes under 1 microsecond per call — 100 listeners cost the same as
1. The cost is one syscall per millisecond per database, regardless of
subscriber count.

## Single writer

SQLite supports one writer and concurrent readers. Honker's claim operations
use indexed `UPDATE ... RETURNING` statements; acknowledgments use `DELETE`.
This avoids the exclusive locks that would serialize work in DELETE/TRUNCATE
journal modes.

## Transactional outbox (built-in)

Jobs, events, and notifications are INSERTs within the caller's transaction.
Business writes and side-effect enqueues commit or rollback atomically — no
separate dispatch table or daemon process. This eliminates the classic
"notification sent but transaction rolled back" problem.

## Over-triggering

All subscribers wake on any commit. Filtering happens in the SELECT path, not
trigger dispatch. Each wasted wake is one indexed SELECT (microseconds). This
design prioritizes never missing a real event over eliminating false positives.

---

# Three Primitives

## 1. Notify (Ephemeral Pub/Sub)

Fire-and-forget channel notifications with no replay. Listeners attach at
`MAX(id)` of the notification table — history is not replayed.

**Not durable**: if a listener is offline when a notification fires, it misses
the event. Use streams for durable replay.

Stored in `_honker_notifications` table.

## 2. Stream (Durable Pub/Sub)

Persistent event log with per-consumer offset tracking. Each named consumer
tracks its offset in `_honker_stream_consumers`. On subscribe, the iterator
replays events past the saved offset, then transitions to live delivery on WAL
wakes.

**At-least-once semantics**: crash re-delivers events up to the last flushed
offset. Auto-saves offsets every 1000 events or 1 second (configurable via
`save_every_n` / `save_every_s`), or manual flush.

Stored in `_honker_streams` and `_honker_stream_consumers` tables.

## 3. Queue (At-Least-Once Work)

Durable task queue with retries, priorities, delayed jobs, and dead-letter
handling. Claims lock jobs for a visibility window (default 300s); if a worker
crashes, the job re-enters the queue after expiry. Exhausted retries move to
`_honker_dead`.

A partial index on `(queue, priority DESC, run_at, id) WHERE state IN
('pending','processing')` keeps the claim hot path bounded by working-set size,
not historical size.

Stored in `_honker_live` (active) and `_honker_dead` (failed) tables.

---

# Installation

## Python

```bash
pip install honker
```

```python
import honker
db = honker.open("app.db")
```

## Node.js

```bash
npm install @russellthehippo/honker-node
```

```javascript
const { open } = require('@russellthehippo/honker-node');
const db = open('app.db');
```

## Rust

```toml
[dependencies]
honker = "0.x"
```

## Go, Ruby, Bun, Elixir

Bindings available — all wrap the same loadable extension binary. Install via
the language's package manager.

## Raw SQLite extension (any language)

```sql
.load ./libhonker_ext
SELECT honker_bootstrap();
```

Any SQLite 3.9+ client can load the extension. The `honker_bootstrap()` call
creates the schema tables if they don't exist.

---

# Python API

## Queue: enqueue and claim

```python
emails = db.queue("emails")
emails.enqueue({"to": "alice@example.com"})

async for job in emails.claim("worker-1"):
    try:
        send(job.payload)
        job.ack()
    except Exception as e:
        job.retry(delay_s=60, error=str(e))
```

## Transactional enqueue

Enqueue atomically with a business write — both commit or both rollback:

```python
with db.transaction() as tx:
    tx.execute("INSERT INTO orders (user_id) VALUES (?)", [42])
    emails.enqueue({"to": "alice@example.com"}, tx=tx)
```

## Task decorator

```python
@emails.task(retries=3, timeout_s=30)
def send_email(to: str, subject: str) -> dict:
    ...
    return {"sent_at": time.time()}

# Caller — blocks until result is available
r = send_email("alice@example.com", "Hi")
print(r.get(timeout=10))
```

Run workers via CLI:

```bash
python -m honker worker myapp.tasks:db --queue=emails --concurrency=4
```

## Stream: publish and subscribe

```python
stream = db.stream("user-events")

# Publish atomically with a business write
with db.transaction() as tx:
    tx.execute("UPDATE users SET name=? WHERE id=?", [name, uid])
    stream.publish({"user_id": uid, "change": "name"}, tx=tx)

# Subscribe with automatic offset tracking
async for event in stream.subscribe(consumer="dashboard"):
    await push_to_browser(event)
```

## Notify: ephemeral pub/sub

```python
# Listen
async for n in db.listen("orders"):
    print(n.channel, n.payload)

# Notify atomically with a business write
with db.transaction() as tx:
    tx.execute("INSERT INTO orders (id, total) VALUES (?, ?)", [42, 99.99])
    tx.notify("orders", {"id": 42})
```

## Periodic tasks

```python
@emails.periodic_task(crontab("0 3 * * *"))
def nightly_backup():
    ...
```

## Priority and delayed jobs

```python
queue = db.queue("tasks")

# Higher priority runs first (default 0)
queue.enqueue({"type": "urgent"}, priority=10)
queue.enqueue({"type": "background"}, priority=0)

# Delayed job — won't be claimable until run_at
from datetime import datetime, timedelta, timezone

run_at = datetime.now(timezone.utc) + timedelta(minutes=30)
queue.enqueue({"type": "scheduled_report"}, run_at=run_at)
```

## Dead-letter inspection and replay

```python
import sqlite3

conn = sqlite3.connect("app.db")

# Inspect failed jobs
dead = conn.execute("""
    SELECT id, queue, payload, error, attempts
    FROM _honker_dead
    WHERE queue = ?
    ORDER BY id DESC
    LIMIT 20
""", ["emails"]).fetchall()

for job in dead:
    print(f"Job {job[0]}: {job[3]} (attempts={job[4]})")

# Replay a dead job by moving it back to _honker_live
def replay_dead_job(conn, job_id):
    with conn:
        conn.execute("""
            INSERT INTO _honker_live (queue, payload, state, priority, run_at, attempts)
            SELECT queue, payload, 'pending', priority, unixepoch(), 0
            FROM _honker_dead WHERE id = ?
        """, [job_id])
        conn.execute("DELETE FROM _honker_dead WHERE id = ?", [job_id])
```

## Named locks

```python
# Acquire a lock for 60 seconds
acquired = db.lock_acquire("data-export", holder="worker-1", ttl_s=60)
if acquired:
    try:
        run_export()
    finally:
        db.lock_release("data-export", holder="worker-1")
```

## Rate limiting

```python
# Allow 10 requests per 60-second window
allowed = db.rate_limit_try("api:user:42", limit=10, window_s=60)
if not allowed:
    raise RateLimitExceeded()

# Periodic cleanup of expired windows
db.rate_limit_sweep(max_age_s=3600)
```

## Result storage with TTL

```python
@emails.task(retries=3, timeout_s=30)
def generate_report(user_id: int) -> dict:
    report = build_report(user_id)
    return {"url": report.url, "rows": report.row_count}

# Caller retrieves the result
result = generate_report(42)
data = result.get(timeout=60)  # Blocks until result or timeout
print(data["url"])

# Results auto-expire per the TTL set on the task/queue
```

---

# Go API

Go bindings wrap the same loadable extension. The idiomatic approach is to load
the extension via your SQLite driver and call the SQL functions directly. This
works with any Go SQLite driver (`mattn/go-sqlite3`, `zombiezen/go-sqlite`,
`modernc.org/sqlite`).

The examples below use `mattn/go-sqlite3` (CGo) since it has the widest
adoption. The same SQL calls work identically with other drivers.

## Setup: load the extension

```go
package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/mattn/go-sqlite3"
)

func init() {
	// Register a driver that auto-loads the honker extension
	sql.Register("sqlite3_honker", &sqlite3.SQLiteDriver{
		Extensions: []string{"libhonker_ext"},
	})
}

func openDB(path string) (*sql.DB, error) {
	db, err := sql.Open("sqlite3_honker", path+"?_journal_mode=WAL")
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}
	// Bootstrap honker tables
	if _, err := db.Exec("SELECT honker_bootstrap()"); err != nil {
		return nil, fmt.Errorf("honker bootstrap: %w", err)
	}
	return db, nil
}
```

## Queue: enqueue and claim

```go
func enqueue(db *sql.DB, queue string, payload any) error {
	data, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal payload: %w", err)
	}
	_, err = db.Exec(`
		INSERT INTO _honker_live (queue, payload, state, priority, run_at, attempts)
		VALUES (?, ?, 'pending', 0, unixepoch(), 0)
	`, queue, string(data))
	if err != nil {
		return fmt.Errorf("enqueue: %w", err)
	}
	return nil
}

func claimAndProcess(db *sql.DB, queue, workerID string) error {
	for {
		var raw string
		row := db.QueryRow(
			"SELECT honker_claim_batch(?, ?, 1, 300)",
			queue, workerID,
		)
		if err := row.Scan(&raw); err != nil {
			return fmt.Errorf("claim: %w", err)
		}

		var jobs []struct {
			ID      int             `json:"id"`
			Payload json.RawMessage `json:"payload"`
		}
		if err := json.Unmarshal([]byte(raw), &jobs); err != nil {
			return fmt.Errorf("unmarshal claim: %w", err)
		}
		if len(jobs) == 0 {
			time.Sleep(50 * time.Millisecond)
			continue
		}

		for _, job := range jobs {
			if err := processJob(job.Payload); err != nil {
				log.Printf("job %d failed: %v", job.ID, err)
				// Job will be reclaimed after visibility timeout expires
				continue
			}
			ackIDs, _ := json.Marshal([]int{job.ID})
			db.Exec("SELECT honker_ack_batch(?, ?)", string(ackIDs), workerID)
		}
	}
}
```

## Transactional enqueue

```go
func createOrderWithEmail(db *sql.DB, userID int, email string) error {
	tx, err := db.Begin()
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	_, err = tx.Exec("INSERT INTO orders (user_id) VALUES (?)", userID)
	if err != nil {
		return fmt.Errorf("insert order: %w", err)
	}

	payload, _ := json.Marshal(map[string]string{
		"to":       email,
		"template": "order_confirmation",
	})
	_, err = tx.Exec(`
		INSERT INTO _honker_live (queue, payload, state, priority, run_at, attempts)
		VALUES ('emails', ?, 'pending', 0, unixepoch(), 0)
	`, string(payload))
	if err != nil {
		return fmt.Errorf("enqueue email: %w", err)
	}

	// Both the order and the email job commit or rollback together
	return tx.Commit()
}
```

## Stream: publish and subscribe

```go
func publishEvent(db *sql.DB, stream, key string, payload any) (int64, error) {
	data, err := json.Marshal(payload)
	if err != nil {
		return 0, fmt.Errorf("marshal: %w", err)
	}
	var offset int64
	err = db.QueryRow(
		"SELECT honker_stream_publish(?, ?, ?)",
		stream, key, string(data),
	).Scan(&offset)
	if err != nil {
		return 0, fmt.Errorf("publish: %w", err)
	}
	return offset, nil
}

func subscribe(ctx context.Context, db *sql.DB, stream, consumer string, handler func(json.RawMessage) error) error {
	// Get last saved offset
	var offset int64
	db.QueryRow(
		"SELECT honker_stream_get_offset(?, ?)", consumer, stream,
	).Scan(&offset)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		var raw string
		err := db.QueryRow(
			"SELECT honker_stream_read_since(?, ?, 100)",
			stream, offset,
		).Scan(&raw)
		if err != nil {
			return fmt.Errorf("read stream: %w", err)
		}

		var events []struct {
			ID      int64           `json:"id"`
			Payload json.RawMessage `json:"payload"`
		}
		json.Unmarshal([]byte(raw), &events)

		for _, evt := range events {
			if err := handler(evt.Payload); err != nil {
				return fmt.Errorf("handle event %d: %w", evt.ID, err)
			}
			offset = evt.ID
		}

		// Periodically save offset
		if len(events) > 0 {
			db.Exec("SELECT honker_stream_save_offset(?, ?, ?)",
				consumer, stream, offset)
		}

		if len(events) == 0 {
			time.Sleep(5 * time.Millisecond) // Wait for WAL change
		}
	}
}
```

## Notify: ephemeral pub/sub with WAL watcher

```go
// Publish a notification inside a transaction
func notifyInTx(tx *sql.Tx, channel string, payload any) error {
	data, _ := json.Marshal(payload)
	_, err := tx.Exec("SELECT notify(?, ?)", channel, string(data))
	return err
}

// Poll for notifications (pair with stat(2) watcher for push-style)
func pollNotifications(db *sql.DB, channel string, sinceID int64) ([]json.RawMessage, int64, error) {
	rows, err := db.Query(`
		SELECT id, payload FROM _honker_notifications
		WHERE channel = ? AND id > ?
		ORDER BY id
	`, channel, sinceID)
	if err != nil {
		return nil, sinceID, fmt.Errorf("poll: %w", err)
	}
	defer rows.Close()

	var results []json.RawMessage
	var lastID int64 = sinceID
	for rows.Next() {
		var id int64
		var payload string
		rows.Scan(&id, &payload)
		results = append(results, json.RawMessage(payload))
		lastID = id
	}
	return results, lastID, rows.Err()
}
```

## Named locks

```go
func withLock(db *sql.DB, name, holder string, ttlS int, fn func() error) error {
	var acquired int
	db.QueryRow(
		"SELECT honker_lock_acquire(?, ?, ?)", name, holder, ttlS,
	).Scan(&acquired)
	if acquired == 0 {
		return fmt.Errorf("lock %q held by another process", name)
	}
	defer db.Exec("SELECT honker_lock_release(?, ?)", name, holder)
	return fn()
}
```

## Rate limiting

```go
func checkRateLimit(db *sql.DB, key string, limit, windowS int) (bool, error) {
	var allowed int
	err := db.QueryRow(
		"SELECT honker_rate_limit_try(?, ?, ?)", key, limit, windowS,
	).Scan(&allowed)
	if err != nil {
		return false, fmt.Errorf("rate limit check: %w", err)
	}
	return allowed == 1, nil
}
```

## Scheduler

```go
func registerPeriodicTask(db *sql.DB, name, queue, cron string, payload any) error {
	data, _ := json.Marshal(payload)
	_, err := db.Exec(
		"SELECT honker_scheduler_register(?, ?, ?, ?, 0, NULL)",
		name, queue, cron, string(data),
	)
	return err
}

// Run this in a goroutine — only one leader should tick
func runScheduler(ctx context.Context, db *sql.DB, leaderID string) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		var acquired int
		db.QueryRow(
			"SELECT honker_lock_acquire('_honker_scheduler', ?, 60)", leaderID,
		).Scan(&acquired)
		if acquired == 0 {
			time.Sleep(5 * time.Second)
			continue
		}

		var raw string
		db.QueryRow(
			"SELECT honker_scheduler_tick(?)", time.Now().Unix(),
		).Scan(&raw)
		// raw is a JSON array of due tasks that were enqueued

		time.Sleep(1 * time.Second)
	}
}
```

## Full Go worker example

```go
func main() {
	db, err := openDB("app.db")
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Trap SIGTERM for graceful shutdown
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
		<-sigCh
		cancel()
	}()

	workerID := fmt.Sprintf("worker-%d", os.Getpid())
	log.Printf("starting worker %s", workerID)

	// Sweep expired jobs periodically
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case <-time.After(30 * time.Second):
				db.Exec("SELECT honker_sweep_expired('emails')")
			}
		}
	}()

	// Process jobs until shutdown
	for {
		select {
		case <-ctx.Done():
			log.Println("shutting down")
			return
		default:
		}

		var raw string
		db.QueryRow(
			"SELECT honker_claim_batch('emails', ?, 1, 300)", workerID,
		).Scan(&raw)

		var jobs []struct {
			ID      int             `json:"id"`
			Payload json.RawMessage `json:"payload"`
		}
		json.Unmarshal([]byte(raw), &jobs)

		if len(jobs) == 0 {
			time.Sleep(50 * time.Millisecond)
			continue
		}

		for _, job := range jobs {
			if err := processJob(job.Payload); err != nil {
				log.Printf("job %d failed: %v", job.ID, err)
				continue
			}
			ackIDs, _ := json.Marshal([]int{job.ID})
			db.Exec("SELECT honker_ack_batch(?, ?)", string(ackIDs), workerID)
		}
	}
}
```

---

# Node.js API

```javascript
const { open } = require('@russellthehippo/honker-node');
const db = open('app.db');

// Transactional enqueue + notify
const tx = db.transaction();
tx.execute('INSERT INTO orders (id) VALUES (?)', [42]);
tx.notify('orders', { id: 42 });
tx.commit();

// Listen for notifications
for await (const n of db.listen('orders')) {
    handle(n.payload);
}
```

---

# Raw SQL API

All functions return JSON or integers for cross-language compatibility. Use
these directly from any SQLite client after loading the extension.

## Queue operations

```sql
-- Claim up to 32 jobs, 300s visibility timeout
SELECT honker_claim_batch('emails', 'worker-1', 32, 300);  -- JSON array

-- Acknowledge completed jobs
SELECT honker_ack_batch('[1,2,3]', 'worker-1');             -- Count

-- Move expired jobs back to pending or to dead-letter
SELECT honker_sweep_expired('emails');                      -- Dead count
```

## Stream operations

```sql
-- Publish an event
SELECT honker_stream_publish('orders', 'key', '{"id":42}'); -- Offset

-- Read events since offset
SELECT honker_stream_read_since('orders', 0, 1000);         -- JSON array

-- Save/get consumer offset
SELECT honker_stream_save_offset('worker', 'orders', 42);
SELECT honker_stream_get_offset('worker', 'orders');        -- Offset or 0
```

## Notification operations

```sql
SELECT notify('orders', '{"id":42}');
SELECT honker_prune_notifications(3600, 10000);  -- older_than_s, max_keep
```

## Scheduler (leader-elected periodic tasks)

```sql
-- Register a periodic task
SELECT honker_scheduler_register(
    'nightly',      -- name
    'backups',      -- queue
    '0 3 * * *',   -- cron expression
    '"go"',        -- payload (JSON)
    0,             -- paused (0=active)
    NULL           -- description
);

-- Tick the scheduler (call once per second from leader)
SELECT honker_scheduler_tick(unixepoch());      -- JSON: due tasks

-- Query next fire time
SELECT honker_cron_next_after('0 3 * * *', unixepoch());

-- Get soonest next fire across all tasks
SELECT honker_scheduler_soonest();

-- Unregister
SELECT honker_scheduler_unregister('nightly');
```

Leader election uses `honker_lock_acquire('_honker_scheduler', leader_id, 60)`
internally — only one active scheduler leader runs `honker_scheduler_tick()`.

## Named locks

```sql
SELECT honker_lock_acquire('backup', 'me', 60);  -- 1=acquired, 0=held
SELECT honker_lock_release('backup', 'me');       -- 1=released
```

## Rate limiting

```sql
SELECT honker_rate_limit_try('api', 10, 60);   -- 1=under limit, 0=at limit
SELECT honker_rate_limit_sweep(3600);           -- Drop old windows
```

## Result storage

```sql
SELECT honker_result_save(42, '{"ok":true}', 3600);  -- task_id, value, TTL
SELECT honker_result_get(42);                         -- Value or NULL
SELECT honker_result_sweep();                         -- Prune expired
```

---

# Schema

Honker creates these tables via `honker_bootstrap()`:

| Table                        | Purpose                                       |
| ---------------------------- | --------------------------------------------- |
| `_honker_live`               | Pending and processing jobs                   |
| `_honker_dead`               | Failed jobs after max retries                 |
| `_honker_notifications`      | Ephemeral pub/sub events                      |
| `_honker_streams`            | Event log per stream                          |
| `_honker_stream_consumers`   | Per-consumer offsets                           |
| `_honker_results`            | Optional task result storage with TTL         |
| `_honker_locks`              | Named distributed locks                       |
| `_honker_rate_limits`        | Sliding-window rate limit tracking            |
| `_honker_scheduler`          | Periodic task definitions (cron)              |

---

# Configuration

## WAL autocheckpoint

```python
db = honker.open("app.db", wal_autocheckpoint=10000)
```

Default `wal_autocheckpoint=10000` batches 10k page writes per fsync,
dramatically improving throughput over per-commit fsync in DELETE mode.

## Queue visibility timeout

```python
async for job in queue.claim("worker", visibility_timeout_s=600):
    ...
```

Default 300s. If a worker crashes, the job re-enters the queue after expiry.

## Stream auto-save interval

```python
async for event in stream.subscribe(
    consumer="worker",
    save_every_n=1000,
    save_every_s=5,
):
    ...
```

Default flushes every 1000 events or 5 seconds.

## Retries and backoff

```python
@queue.task(retries=5, timeout_s=30)
def work():
    ...

# Or manually on retry
job.retry(delay_s=60, backoff=2.0)  # Exponential backoff
```

Default max_attempts is 3. After exhaustion, the job moves to `_honker_dead`.

---

# Crash Recovery

**Transaction safety**: Rollback drops jobs/events/notifications with the
business write (SQLite ACID). SIGKILL mid-transaction is safe — WAL rollback on
next open leaves no stale state.

**Claim expiry**: If a worker crashes with a claimed job, it expires after
`visibility_timeout_s` and another worker reclaims. `attempts` increments;
after `max_attempts`, the row moves to `_honker_dead`.

**Stream replay**: A crashed subscriber replays events from the last flushed
offset (at-least-once). Tune `save_every_n` / `save_every_s` to control the
replay window.

**Notify durability**: Ephemeral — listeners offline during publish miss the
event. Use `db.stream()` for durable replay.

---

# Performance

| Metric             | Value                                                          |
| ------------------ | -------------------------------------------------------------- |
| Wake latency       | 1-5ms typical (commit to subscriber wake)                      |
| Idle CPU cost      | One `stat(2)` per ms per database; <0.1% CPU                  |
| Claim throughput   | Bounded by working-set size (partial index), not history       |
| Wasted wake cost   | One indexed SELECT (microseconds)                              |
| Listener scaling   | 100 listeners cost the same as 1 (single stat poller fans out) |

---

# Limitations

- **Single-machine only**: SQLite's locking is per-host; NFS multi-writer
  corrupts the database
- **No workflow DAGs**: No task chaining, pipelines, groups, or chords
- **No multi-writer replication**: Use Postgres for distributed setups
- **WAL required**: Cannot use DELETE or TRUNCATE journal modes
- **WAL sidecars required**: `.db-wal` and `.db-shm` files must remain
  alongside the database file
- **Over-triggering**: All subscribers wake on any commit to the database, not
  just their channel — filtering happens after wake

---

# Patterns

## Background email queue with transactional outbox

```python
import honker

db = honker.open("app.db")
emails = db.queue("emails")

# In your request handler — atomic with the order insert
def create_order(user_id, items):
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO orders (user_id, items) VALUES (?, ?)",
            [user_id, json.dumps(items)],
        )
        emails.enqueue(
            {"to": get_email(user_id), "template": "order_confirmation"},
            tx=tx,
        )

# Worker process
async def run_worker():
    async for job in emails.claim("email-worker-1"):
        try:
            send_email(**job.payload)
            job.ack()
        except Exception as e:
            job.retry(delay_s=60, error=str(e))
```

## Event sourcing with streams

```python
stream = db.stream("account-events")

def transfer(from_id, to_id, amount):
    with db.transaction() as tx:
        tx.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?",
                   [amount, from_id])
        tx.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?",
                   [amount, to_id])
        stream.publish({
            "type": "transfer",
            "from": from_id,
            "to": to_id,
            "amount": amount,
        }, tx=tx)

# Multiple independent consumers, each with their own offset
async def audit_consumer():
    async for event in stream.subscribe(consumer="audit-log"):
        append_to_audit_log(event)

async def analytics_consumer():
    async for event in stream.subscribe(consumer="analytics"):
        update_dashboard(event)
```

## Combining notify + queue for fast wake

Use ephemeral notify for instant wake, queue for durable processing:

```python
def enqueue_with_notify(queue_name, payload):
    with db.transaction() as tx:
        db.queue(queue_name).enqueue(payload, tx=tx)
        tx.notify(queue_name, {"hint": "new_job"})
```

This avoids polling the queue table — workers listen on the channel and only
check the queue when notified.
