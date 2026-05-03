---
name: data-flywheel
description:
  Build a data flywheel service that ingests labeled data into SQLite, triggers
  async model training via honker queues after every N records, and hot-swaps
  the active model for inference. Use when you need a self-improving ML service
  backed by a single SQLite database with no external broker or scheduler.
---

# Data Flywheel: Ingest, Train, Serve on SQLite

A single-process service that accepts labeled data, persists it in SQLite,
triggers model retraining after every N records using honker's durable job
queue, and serves predictions from the latest model. The entire system — data,
jobs, events, model metadata — lives in one `.db` file.

## When to use this skill

- You need a **self-improving service** where incoming labeled data feeds back
  into model training
- You want **async training** that doesn't block the ingest or inference paths
- You want **transactional guarantees** — data persistence and training triggers
  commit or rollback atomically
- Your write throughput fits in a **single process** (thousands of ingests/sec
  is fine)
- You want to avoid adding Redis, RabbitMQ, or Celery for background jobs

## When NOT to use this skill

- You need **distributed training** across multiple machines — use a proper ML
  platform (SageMaker, Vertex AI, Ray)
- You need **GPU training** — this pattern runs training in-process; offload to
  a GPU cluster and use honker to dispatch the job instead
- Your training data is too large for SQLite (>100GB) — use Postgres or a data
  warehouse
- You need **workflow DAGs** (chained training stages, fan-out) — use Temporal
  (see the temporal-python skill)

---

## Architecture

```
POST /ingest                          POST /predict
  │                                     │
  ▼                                     ▼
┌──────────────────────────────┐  ┌──────────────┐
│ INSERT training_data         │  │ load active   │
│ stream.publish (audit)       │  │ model from    │
│ if count % N == 0:           │  │ memory, run   │
│   queue.enqueue (training)   │  │ inference     │
│ — all in one transaction —   │  └──────┬───────┘
└──────────────┬───────────────┘         │
               │                         │ listen("model-updated")
               ▼                         │ → hot-swap on notify
     ┌──────────────────┐               │
     │ honker queue:    │               │
     │   "training"     │               │
     └────────┬─────────┘               │
              │                          │
        worker claims                    │
              ▼                          │
     ┌──────────────────┐               │
     │ acquire lock     │               │
     │ load data        │               │
     │ train model      │               │
     │ save artifact    │               │
     │ INSERT models    │               │
     │ notify()  ───────────────────────┘
     │ ack job          │
     └──────────────────┘
```

**Two processes, one database file:**

| Process     | Role                                                          |
| ----------- | ------------------------------------------------------------- |
| API server  | Handles `/ingest` and `/predict`, listens for model-swap      |
| Worker      | Claims training jobs, trains models, publishes notifications  |

---

## Schema

```sql
CREATE TABLE IF NOT EXISTS training_data (
    id         INTEGER PRIMARY KEY,
    features   TEXT NOT NULL,   -- JSON object
    label      TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS models (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL,      -- filesystem path to artifact
    metrics    TEXT,               -- JSON: {"accuracy": 0.94, ...}
    data_count INTEGER NOT NULL,   -- how many rows it trained on
    active     INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_models_active ON models(active) WHERE active = 1;
```

Honker tables (`_honker_live`, `_honker_streams`, etc.) are created by
`honker_bootstrap()` — see the honker skill for details.

---

## Database Setup

```python
import honker

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "100"))

db = honker.open(os.environ.get("DB_PATH", "app.db"))
training_queue = db.queue("training")
data_stream = db.stream("data-events")

# Create application tables
with db.transaction() as tx:
    tx.executescript("""
        CREATE TABLE IF NOT EXISTS training_data (
            id         INTEGER PRIMARY KEY,
            features   TEXT NOT NULL,
            label      TEXT NOT NULL,
            created_at INTEGER NOT NULL DEFAULT (unixepoch())
        );
        CREATE TABLE IF NOT EXISTS models (
            id         INTEGER PRIMARY KEY,
            path       TEXT NOT NULL,
            metrics    TEXT,
            data_count INTEGER NOT NULL,
            active     INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL DEFAULT (unixepoch())
        );
        CREATE INDEX IF NOT EXISTS idx_models_active
            ON models(active) WHERE active = 1;
    """)
```

---

## Ingest Path

The critical transaction: persist labeled data, publish an audit event, and
conditionally enqueue a training job — all atomically.

```python
import json

def ingest(features: dict, label: str) -> int:
    with db.transaction() as tx:
        cur = tx.execute(
            "INSERT INTO training_data (features, label) VALUES (?, ?)",
            [json.dumps(features), label],
        )
        row_id = cur.lastrowid

        data_stream.publish(
            {"id": row_id, "label": label},
            tx=tx,
        )

        count = tx.execute(
            "SELECT COUNT(*) FROM training_data"
        ).fetchone()[0]

        if count % BATCH_SIZE == 0:
            training_queue.enqueue(
                {"trigger": "threshold", "count": count},
                tx=tx,
            )

    return row_id
```

If the transaction rolls back, nothing happens — no orphaned jobs, no phantom
stream events. This is the transactional outbox pattern, built into honker.

### FastAPI endpoint

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class IngestRequest(BaseModel):
    features: dict
    label: str

@app.post("/ingest")
def handle_ingest(req: IngestRequest):
    row_id = ingest(req.features, req.label)
    count = db.execute("SELECT COUNT(*) FROM training_data").fetchone()[0]
    return {"id": row_id, "count": count}
```

---

## Training Worker

Claims jobs from the queue, acquires a lock to prevent concurrent training
runs, trains the model, saves the artifact, and notifies the inference path.

```python
import joblib
from pathlib import Path
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "artifacts"))
ARTIFACTS_DIR.mkdir(exist_ok=True)

async def run_worker():
    async for job in training_queue.claim("trainer"):
        acquired = db.lock_acquire("training-lock", holder="trainer", ttl_s=600)
        if not acquired:
            job.retry(delay_s=30, error="training lock held")
            continue

        try:
            train_and_publish(job)
            job.ack()
        except Exception as e:
            job.retry(delay_s=60, error=str(e))
        finally:
            db.lock_release("training-lock", holder="trainer")


def train_and_publish(job):
    rows = db.execute(
        "SELECT features, label FROM training_data ORDER BY id"
    ).fetchall()

    X = [json.loads(r[0]) for r in rows]
    y = [r[1] for r in rows]

    # Replace with your actual pipeline — this is a placeholder
    import pandas as pd
    df = pd.DataFrame(X)
    pipeline = Pipeline([
        ("scale", StandardScaler()),
        ("model", LogisticRegression(max_iter=1000)),
    ])
    pipeline.fit(df, y)

    # Evaluate
    accuracy = float(pipeline.score(df, y))

    # Save artifact
    artifact_path = ARTIFACTS_DIR / f"model_{len(rows)}.joblib"
    joblib.dump(pipeline, artifact_path)

    # Register and activate
    with db.transaction() as tx:
        tx.execute("UPDATE models SET active = 0 WHERE active = 1")
        tx.execute(
            """INSERT INTO models (path, metrics, data_count, active)
               VALUES (?, ?, ?, 1)""",
            [str(artifact_path), json.dumps({"accuracy": accuracy}), len(rows)],
        )
        tx.notify("model-updated", {"path": str(artifact_path)})
```

The named lock (`training-lock`) prevents two workers from training
simultaneously. If a worker crashes mid-training, the lock expires after
`ttl_s` and the job re-enters the queue after the visibility timeout.

---

## Inference Path

Load the active model on startup. Listen for `model-updated` notifications to
hot-swap without polling.

```python
import asyncio
import joblib

_current_model = None

def load_active_model():
    global _current_model
    row = db.execute(
        "SELECT path FROM models WHERE active = 1"
    ).fetchone()
    if row:
        _current_model = joblib.load(row[0])

# Load on startup
load_active_model()

# Background listener — hot-swap on notify
async def model_listener():
    async for notification in db.listen("model-updated"):
        path = notification.payload.get("path")
        if path:
            global _current_model
            _current_model = joblib.load(path)

@app.on_event("startup")
async def start_listener():
    asyncio.create_task(model_listener())
```

### Predict endpoint

```python
import pandas as pd

class PredictRequest(BaseModel):
    features: dict

class PredictResponse(BaseModel):
    prediction: str
    model_version: int | None

@app.post("/predict")
def handle_predict(req: PredictRequest):
    if _current_model is None:
        raise HTTPException(status_code=503, detail="no model available")

    df = pd.DataFrame([req.features])
    prediction = _current_model.predict(df)[0]

    row = db.execute("SELECT id FROM models WHERE active = 1").fetchone()
    return PredictResponse(
        prediction=str(prediction),
        model_version=row[0] if row else None,
    )
```

---

## Running It

### Makefile

```makefile
SHELL := /bin/bash

define setup_env
    $(eval ENV_FILE := $(1))
    $(eval include $(1))
    $(eval export)
endef

.PHONY: run-server
run-server: ## API server with hot reload
	@mkdir -p logs
	$(call setup_env, .env)
	uv run uvicorn server:app --reload 2>&1 | tee logs/server.log

.PHONY: run-worker
run-worker: ## Training worker
	@mkdir -p logs
	$(call setup_env, .env)
	uv run python -m honker worker server:db --queue=training 2>&1 | tee logs/worker.log

.PHONY: run-all
run-all: ## Run server and worker (backgrounded)
	@mkdir -p logs
	$(MAKE) run-server &
	$(MAKE) run-worker &
	wait
```

### Environment (`.env`)

```bash
DB_PATH=app.db
BATCH_SIZE=100
ARTIFACTS_DIR=artifacts
LOG_LEVEL=INFO
```

---

## Deployment

Pair with the litestream-k8s skill for durable deployment on Kubernetes. The
`run.sh` entrypoint restores the database on pod startup, then starts both
processes under litestream replication:

```bash
#!/bin/bash
set -e

DB_PATH="/data/app.db"
export DB_PATH

if [ ! -f "$DB_PATH" ]; then
  litestream restore -if-replica-exists -o "$DB_PATH" "$DB_PATH" || true
fi

# Start worker in background, then run server under litestream
python -m honker worker server:db --queue=training &
exec litestream replicate -exec "uvicorn server:app --host 0.0.0.0 --port 8080"
```

Model artifacts should be stored on the `emptyDir` volume alongside the
database. They're rebuilt from the training data on first training run after a
pod restart — the data is the source of truth, not the artifact.

---

## Configuration

| Variable        | Default      | Purpose                                       |
| --------------- | ------------ | --------------------------------------------- |
| `DB_PATH`       | `app.db`     | SQLite database path                          |
| `BATCH_SIZE`    | `100`        | Train after every N ingested records          |
| `ARTIFACTS_DIR` | `artifacts/` | Where to save model files                     |
| `LOG_LEVEL`     | `INFO`       | Logging verbosity                             |

Honker queue defaults (override in code):

| Setting              | Default | Purpose                                      |
| -------------------- | ------- | -------------------------------------------- |
| `visibility_timeout` | 300s    | How long a claimed training job is held       |
| `max_attempts`       | 3       | Retries before dead-letter                   |
| `lock ttl_s`         | 600s    | Training lock expiry (> expected train time)  |

---

## Gotchas

- **Single writer.** SQLite allows one writer at a time. The ingest endpoint
  and the training worker share the write lock — but writes are fast (INSERTs
  and UPDATEs), so contention is minimal. Training reads are concurrent under
  WAL mode.

- **Training lock prevents double runs.** Without the named lock, two workers
  could train simultaneously if the queue has multiple pending jobs (e.g., after
  a backlog). The lock serializes training; extra jobs retry after a short
  delay.

- **Model artifacts are ephemeral on K8s.** On pod restart, artifacts are gone
  (emptyDir is wiped). The first training run rebuilds them from the data. If
  you need instant inference on startup, store the active artifact as a blob in
  the `models` table instead of on disk.

- **Don't block ingest with training.** Training runs in the worker process,
  not in the request handler. The ingest path only does an INSERT + conditional
  enqueue — both are sub-millisecond.

- **Count-based triggers can pile up.** If you ingest 500 records in a burst
  with `BATCH_SIZE=100`, you'll enqueue 5 training jobs. The lock ensures only
  one runs at a time; the rest retry. For bursty workloads, consider deduping
  in the worker (skip if a model already exists for a higher count).

- **Pair with litestream for durability.** Without litestream (or a persistent
  volume), a pod restart loses everything. See the litestream-k8s skill.
