---
name: litestream-k8s
description: Run SQLite with Litestream replication to S3-compatible storage (Cloudflare R2, etc.) on Kubernetes. Use when adding persistent SQLite to a containerized app, setting up Litestream, or doing point-in-time database recovery.
---

# Litestream on Kubernetes with S3/R2

Run SQLite as your primary database in Kubernetes with continuous replication to S3-compatible object storage via Litestream. The database restores automatically on pod startup — no PersistentVolumeClaim needed.

## Why this pattern

SQLite is fast, simple, and zero-dependency. The problem on Kubernetes is that pods are ephemeral — when a pod dies, the DB is gone. Litestream solves this by continuously streaming WAL changes to object storage (Cloudflare R2, AWS S3, etc.) and restoring on startup. This gives you:

- Single-binary app with no external database dependency
- Durability via object storage (cheaper and more resilient than a PVC on a single node)
- Point-in-time recovery for free — every WAL segment is preserved
- Works with any S3-compatible backend

**Trade-off**: single-writer only (one replica). If you need horizontal scaling or concurrent writes, use Postgres.

## File layout

```
.
├── Dockerfile          # Multi-stage build, installs litestream
├── run.sh              # Entrypoint: restore → replicate → app
├── litestream.yml      # Replication config (env vars for creds)
├── .env.prod           # S3/R2 credentials
└── k8s/prod/
    └── deployment.yaml # emptyDir volume at /data
```

## litestream.yml

Use environment variables so the same config works across environments:

```yaml
dbs:
  - path: /data/app.db
    replicas:
      - type: s3
        bucket: ${LITESTREAM_BUCKET}
        path: app.db
        endpoint: ${LITESTREAM_ENDPOINT}
        access-key-id: ${LITESTREAM_ACCESS_KEY_ID}
        secret-access-key: ${LITESTREAM_SECRET_ACCESS_KEY}
```

## run.sh (container entrypoint)

This script runs on every pod start. It restores the DB from the replica if one exists, then starts litestream in replication mode wrapping the app process:

```bash
#!/bin/bash
set -e

DB_PATH="/data/app.db"
export DB_PATH

# Restore from replica if the DB doesn't exist yet
if [ ! -f "$DB_PATH" ]; then
  echo "restoring database from litestream replica..."
  litestream restore -if-replica-exists -o "$DB_PATH" "$DB_PATH" || true
fi

# Start litestream replication in the background, then run the app
exec litestream replicate -exec "/app"
```

Key details:
- `litestream restore -if-replica-exists` exits cleanly if no replica exists yet (first deploy).
- `litestream replicate -exec` runs the app as a child process — if the app dies, litestream stops too, and Kubernetes restarts the pod.
- `DB_PATH` must be exported as an env var so the app can read it. Do NOT try to inline it in the `-exec` string like `DB_PATH=/data/app.db /app` — litestream will try to execute that as a literal path.

## Dockerfile

Install litestream from GitHub releases. Use the version-specific tar.gz URL:

```Dockerfile
FROM golang:1.25-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /bin/app .

FROM alpine:latest
RUN apk add --no-cache ca-certificates bash

# Install litestream
RUN wget -qO- https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.tar.gz \
    | tar xz -C /usr/local/bin

COPY --from=builder /bin/app /app
COPY --from=builder /app/static /static
COPY litestream.yml /etc/litestream.yml
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080
CMD ["/run.sh"]
```

Note: `CGO_ENABLED=0` works if you use a pure-Go SQLite driver like `modernc.org/sqlite`. If using `mattn/go-sqlite3` (CGO), you need `CGO_ENABLED=1` and `apk add build-base` in the builder stage.

## Kubernetes deployment

Use `emptyDir` for the data volume — litestream is the durability layer, not the volume:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 1  # Single writer — do not scale beyond 1
  selector:
    matchLabels:
      app: myapp
  template:
    spec:
      containers:
        - name: myapp
          image: "myregistry/myapp:latest"
          envFrom:
            - secretRef:
                name: myapp-secret-envs
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          emptyDir: {}
```

**Important**: Keep `replicas: 1`. SQLite is single-writer. Multiple replicas will corrupt the database.

## Environment variables

```
LITESTREAM_BUCKET=myapp-backups
LITESTREAM_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
LITESTREAM_ACCESS_KEY_ID=<r2-access-key>
LITESTREAM_SECRET_ACCESS_KEY=<r2-secret-key>
```

For Cloudflare R2:
1. Create a bucket in the R2 dashboard
2. Go to R2 > Manage R2 API Tokens > Create API Token
3. The endpoint is `https://<cloudflare-account-id>.r2.cloudflarestorage.com`

## Point-in-time recovery

Litestream stores WAL segments and snapshots in the replica. You can restore to any prior point in time. This is the killer feature — you get backup/recovery for free.

**Step 1: Restore to a local file**

```bash
# Load R2 credentials
source <(grep -E '^(LITESTREAM_)' .env.prod | sed 's/^/export /')

# Restore to a specific timestamp
litestream restore -config litestream.yml \
  -timestamp "2026-04-15T21:16:00Z" \
  -o /tmp/restored.db \
  /data/app.db

# Or restore to the latest available state (omit -timestamp)
litestream restore -config litestream.yml \
  -o /tmp/restored.db \
  /data/app.db
```

The path `/data/app.db` here refers to the `dbs[].path` in `litestream.yml` — litestream uses it to locate the correct replica in S3. It does not need to exist locally.

**Step 2: Inspect the restored data**

```bash
sqlite3 /tmp/restored.db "SELECT * FROM my_table;"
```

**Step 3: Re-insert recovered rows into the live database**

Do NOT replace the live DB file — that breaks litestream's WAL tracking and will cause replication errors. Instead, extract the rows you need and insert them into the live pod:

```bash
POD=$(kubectl get pods -l app=myapp -o jsonpath='{.items[0].metadata.name}')

# Install sqlite3 in the pod (alpine)
kubectl exec $POD -- apk add --no-cache sqlite

# Insert recovered rows
kubectl exec $POD -- sqlite3 /data/app.db "INSERT OR IGNORE INTO ..."
```

You can also `kubectl cp` a SQL dump file into the pod and execute it:

```bash
sqlite3 /tmp/restored.db ".dump my_table" > /tmp/recovery.sql
kubectl cp /tmp/recovery.sql $POD:/tmp/recovery.sql
kubectl exec $POD -- sqlite3 /data/app.db < /tmp/recovery.sql
```

## SQLite migration pattern

Since the DB is created fresh from litestream restore, your app's migration code must handle both cases:

1. **Fresh DB** (first deploy): `CREATE TABLE IF NOT EXISTS ...` creates everything.
2. **Restored DB** (schema change): Use `ALTER TABLE ... ADD COLUMN` with error suppression for idempotent migrations.

```go
// Always safe — creates tables if they don't exist
db.Exec(`CREATE TABLE IF NOT EXISTS users (...)`)

// Add new columns to existing tables — ignore "duplicate column" errors
db.Exec(`ALTER TABLE users ADD COLUMN confirmed BOOLEAN NOT NULL DEFAULT FALSE`)
```

## Gotchas

- **Never set replicas > 1**. SQLite is single-writer. Two pods writing to separate copies will diverge and you'll lose data.
- **Never replace the live DB file**. Litestream tracks WAL position. Swapping the file causes it to lose track and either error or re-upload a full snapshot. Insert recovered rows instead.
- **`run.sh` must use `exec`**. Without `exec`, litestream runs as a grandchild process and won't receive signals properly — `SIGTERM` from Kubernetes won't propagate and you'll get ungraceful shutdowns.
- **`-if-replica-exists` on first deploy**. Without this flag, the restore command fails if no replica has been created yet (first-ever deploy).
- **DB lock on hot reload**. If you use `air` or similar in dev, the old process may hold the SQLite lock when the new one starts. Clean the DB file between restarts (`rm -f app.db tmp/main`).
