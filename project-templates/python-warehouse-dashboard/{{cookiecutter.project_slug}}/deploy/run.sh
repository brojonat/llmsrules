#!/bin/sh
# The server's entrypoint.
#
# 1. Refresh once, so a fresh pod (or an empty volume) serves data. When
#    something else owns refreshes and the volume persists, this is a no-op
#    that costs a hash of the raw files. Set SKIP_REFRESH=1 to start serving
#    "not ready" immediately and let the scheduler fill the warehouse.
# 2. Serve. When litestream is configured, the app database (feedback, LLM
#    usage) is restored from object storage if the volume is empty, and
#    replicated while the server runs.
set -e
mkdir -p "$(dirname "$APP_DB")"

if [ -z "${SKIP_REFRESH:-}" ]; then
  /app/deploy/refresh.sh
fi

if [ -n "${LITESTREAM_BUCKET:-}" ]; then
  if [ ! -f "$APP_DB" ]; then
    echo "restoring app database from litestream replica (if one exists)..." >&2
    litestream restore -config /app/deploy/litestream.yml -if-replica-exists "$APP_DB" || true
  fi
  exec litestream replicate -config /app/deploy/litestream.yml -exec "{{cookiecutter.project_slug}} serve"
fi

exec {{cookiecutter.project_slug}} serve
