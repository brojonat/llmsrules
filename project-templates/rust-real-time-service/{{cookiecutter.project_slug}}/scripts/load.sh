#!/usr/bin/env bash
# Open N streams on a view against a running server, hold them, then print the
# frame loop's metrics and the server's memory. The tick is the benchmark: if
# frames_tick_overruns_total climbs, the renderer is behind.
#
#   scripts/load.sh [N] [PATH] [BASE_URL]
#   scripts/load.sh 500 /todos/stream     # 500 tabs on one session's todos
set -euo pipefail
n="${1:-300}"
path="${2:-/monitor/stream}"
base="${3:-http://localhost:{{cookiecutter.default_port}}}"

# One session cookie for all of them, so a /todos/stream load is one view.
cookie="sid=$(cat /proc/sys/kernel/random/uuid)"
pids=()
for _ in $(seq "$n"); do
  curl -sN --compressed -H "cookie: $cookie" -o /dev/null "$base$path" &
  pids+=("$!")
done
trap 'kill "${pids[@]}" 2>/dev/null' EXIT

sleep 5
echo "$n streams on $path for 5 s:" >&2
curl -s "$base/metrics" | grep -E '^frames_(subscribers|tick_overruns_total|tick_duration_seconds_(sum|count)) '
# By path: /proc truncates process names to 15 characters, so pgrep -x misses.
if pid="$(pgrep -nf 'target/(debug|release)/{{cookiecutter.project_slug}}( |$)')"; then
  echo "server RSS: $(( $(awk '/VmRSS/ {print $2}' "/proc/$pid/status") / 1024 )) MiB"
fi
