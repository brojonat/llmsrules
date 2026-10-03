"""The app observing itself: counters handlers bump, periodic process samples,
and the history /admin and the load tester read.

A Python port of the go-local-app template's internal/metrics. Samples live
in an in-memory ring buffer: diagnostics are about this process, so they may
die with it.
"""

from __future__ import annotations

import asyncio
import os
import resource
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from statistics import median

import psutil

# Prometheus metric names start with the package name.
PREFIX = __name__.split(".")[0]


@dataclass
class Collector:
    """Counters handlers bump. Single event loop, so no locks; the query
    timer is called from worker threads but only ever adds."""

    started: float = field(default_factory=time.time)
    requests: int = 0
    errors: int = 0
    open_streams: int = 0
    patches: int = 0
    bytes_raw: int = 0
    bytes_wire: int = 0
    query_seconds: float = 0.0
    query_count: int = 0
    render_seconds: float = 0.0
    render_count: int = 0
    chat_replies: int = 0
    chat_in_flight: int = 0
    chat_errors: int = 0
    chat_seconds: float = 0.0
    chat_prompt_tokens: int = 0
    chat_completion_tokens: int = 0
    chat_cached_tokens: int = 0
    chat_cost: float = 0.0  # USD, as the provider reports it
    chat_tokens_today: int = 0  # all models, today (UTC), from the app DB
    chat_daily_tokens: int = 0  # the budget; 0 = unlimited
    sql_queries: int = 0
    sql_errors: int = 0
    sql_seconds: float = 0.0
    feedback: int = 0  # ratings + sent reports

    def request(self, status: int) -> None:
        self.requests += 1
        if status >= 500:
            self.errors += 1

    def query(self, seconds: float) -> None:
        self.query_seconds += seconds
        self.query_count += 1

    def render(self, seconds: float) -> None:
        self.render_seconds += seconds
        self.render_count += 1

    def chat_reply(self, seconds: float, usage, ok: bool) -> None:
        self.chat_replies += 1
        self.chat_errors += not ok
        self.chat_seconds += seconds
        if usage is not None:
            self.chat_prompt_tokens += usage.prompt_tokens
            self.chat_completion_tokens += usage.completion_tokens
            self.chat_cached_tokens += usage.cached_tokens
            self.chat_cost += usage.cost or 0.0

    def sql_query(self, seconds: float, ok: bool) -> None:
        self.sql_queries += 1
        self.sql_errors += not ok
        self.sql_seconds += seconds

    def patch(self, raw: int, wire: int) -> None:
        self.patches += 1
        self.bytes_raw += raw
        self.bytes_wire += wire


@dataclass
class Sample:
    """One observation of the process. Field names are metric names."""

    time: float
    cpu_pct: float
    rss_mb: float
    threads: int
    open_files: int
    streams: int
    requests: int
    errors: int
    req_per_s: float
    patches_per_s: float
    wire_kbps: float
    compression: float
    loop_lag_ms: float
    query_ms: float
    render_ms: float
    chats_streaming: int

    def value(self, name: str) -> float:
        return float(getattr(self, name))


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    unit: str = ""


# Tiles on /admin, in display order.
TILES = [
    Metric("cpu_pct", "CPU", "%"),
    Metric("rss_mb", "Resident memory", " MB"),
    Metric("streams", "Open streams"),
    Metric("loop_lag_ms", "Event loop lag", " ms"),
    Metric("patches_per_s", "Patches", "/s"),
    Metric("wire_kbps", "Stream out", " KB/s"),
    Metric("compression", "Compression", "×"),
    Metric("req_per_s", "Requests", "/s"),
    Metric("query_ms", "Query latency", " ms"),
    Metric("render_ms", "Render time", " ms"),
    Metric("chats_streaming", "Chat replies streaming"),
    Metric("threads", "Threads"),
    Metric("errors", "5xx responses"),
]

# Bands for "what does N connected clients cost". Upper bounds, inclusive.
CLIENT_BANDS = [0, 5, 10, 100, 1000, 10_000]


class Sampler:
    """Samples the process every `interval` seconds into a ring buffer.

    Also measures event loop lag: how late a sleep wakes up. In an asyncio
    server that is the number that goes bad first under load — CPU can read
    40% while every client waits in line behind one slow render.
    """

    def __init__(self, collector: Collector, interval: float = 1.0, keep: int = 3600) -> None:
        self.c = collector
        self.interval = interval
        self.history: deque[Sample] = deque(maxlen=keep)
        self.thresholds: dict[str, float] = {}
        self._proc = psutil.Process()
        self._proc.cpu_percent()  # prime: the first call always returns 0
        self._last = (time.monotonic(), 0, 0, 0, 0.0, 0, 0.0, 0)
        self._lag = 0.0

    @property
    def latest(self) -> Sample | None:
        return self.history[-1] if self.history else None

    async def measure_lag(self, every: float = 0.1) -> None:
        while True:
            t = time.perf_counter()
            await asyncio.sleep(every)
            self._lag = max(self._lag, (time.perf_counter() - t - every) * 1000)

    def take(self) -> Sample:
        c = self.c
        now = time.monotonic()
        t0, req0, patch0, wire0, qs0, qn0, rs0, rn0 = self._last
        dt = max(now - t0, 1e-9)
        dq, dqn = c.query_seconds - qs0, c.query_count - qn0
        dr, drn = c.render_seconds - rs0, c.render_count - rn0
        with self._proc.oneshot():
            s = Sample(
                time=time.time(),
                cpu_pct=self._proc.cpu_percent(),
                rss_mb=self._proc.memory_info().rss / 1e6,
                threads=self._proc.num_threads(),
                open_files=self._proc.num_fds(),
                streams=c.open_streams,
                requests=c.requests,
                errors=c.errors,
                req_per_s=(c.requests - req0) / dt,
                patches_per_s=(c.patches - patch0) / dt,
                wire_kbps=(c.bytes_wire - wire0) / dt / 1e3,
                compression=c.bytes_raw / c.bytes_wire if c.bytes_wire else 0.0,
                loop_lag_ms=self._lag,
                query_ms=1000 * dq / dqn if dqn else 0.0,
                render_ms=1000 * dr / drn if drn else 0.0,
                chats_streaming=c.chat_in_flight,
            )
        self._last = (now, c.requests, c.patches, c.bytes_wire, c.query_seconds, c.query_count,
                      c.render_seconds, c.render_count)  # fmt: skip
        self._lag = 0.0
        self.history.append(s)
        return s

    def by_clients(self) -> list[dict]:
        """Resource use grouped by how many streams were open. This is the
        table that answers "what do 5 / 10 / 100 / 1000 clients cost"."""
        rows = []
        lo = -1
        for hi in CLIENT_BANDS:
            band = [s for s in self.history if lo < s.streams <= hi]
            if band:
                rows.append({
                    "band": f"{lo + 1}–{hi}" if lo + 1 != hi else str(hi),
                    "samples": len(band),
                    "streams_max": max(s.streams for s in band),
                    "cpu_pct_p50": median(s.cpu_pct for s in band),
                    "cpu_pct_max": max(s.cpu_pct for s in band),
                    "rss_mb_max": max(s.rss_mb for s in band),
                    "loop_lag_ms_p50": median(s.loop_lag_ms for s in band),
                    "loop_lag_ms_max": max(s.loop_lag_ms for s in band),
                    "wire_kbps_p50": median(s.wire_kbps for s in band),
                })  # fmt: skip
            lo = hi
        return rows


@dataclass
class Limits:
    """What the process is allowed, as it sees it."""

    pid: int
    cpus: int
    cpu_affinity: int
    open_files_max: int
    mem_total_mb: float
    mem_available_mb: float
    cgroup_mem_limit_mb: float  # 0 = none found


def read_limits() -> Limits:
    soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    vm = psutil.virtual_memory()
    return Limits(
        pid=os.getpid(),
        cpus=os.cpu_count() or 0,
        cpu_affinity=len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else 0,
        open_files_max=soft,
        mem_total_mb=vm.total / 1e6,
        mem_available_mb=vm.available / 1e6,
        cgroup_mem_limit_mb=_cgroup_mem_limit() / 1e6,
    )


def _cgroup_mem_limit() -> float:
    """The container's memory ceiling under cgroup v2, which is what a k8s
    `resources.limits.memory` becomes. 0 when unset or not in a cgroup."""
    try:
        raw = open("/sys/fs/cgroup/memory.max").read().strip()
    except OSError:
        return 0
    return 0 if raw == "max" else float(raw)


def raise_open_files_limit() -> int:
    """Lift the soft RLIMIT_NOFILE to the hard limit. Every SSE client is a
    socket, and 1000 of them overrun the common 1024 default. macOS reports
    an unlimited hard limit it won't actually grant, so ask for 64K there."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = hard if hard != resource.RLIM_INFINITY else 65_536
    if soft < target:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        except (ValueError, OSError):
            return soft
    return max(soft, target)


def prometheus(c: Collector, s: Sample | None) -> str:
    """/metrics in Prometheus text format, no client library."""
    lines = []

    def emit(name: str, kind: str, help_: str, value: float) -> None:
        lines.append(f"# HELP {PREFIX}_{name} {help_}")
        lines.append(f"# TYPE {PREFIX}_{name} {kind}")
        lines.append(f"{PREFIX}_{name} {value}")

    emit("requests_total", "counter", "HTTP requests served.", c.requests)
    emit("errors_total", "counter", "HTTP 5xx responses.", c.errors)
    emit("open_streams", "gauge", "Open SSE streams.", c.open_streams)
    emit("patches_total", "counter", "SSE patch events sent.", c.patches)
    emit("stream_bytes_raw_total", "counter", "SSE bytes before compression.", c.bytes_raw)
    emit("stream_bytes_wire_total", "counter", "SSE bytes after compression.", c.bytes_wire)
    emit("query_seconds_total", "counter", "Time spent in DuckDB queries.", c.query_seconds)
    emit("queries_total", "counter", "DuckDB queries run (cache misses).", c.query_count)
    emit("chat_replies_total", "counter", "Chat replies attempted.", c.chat_replies)
    emit("chat_errors_total", "counter", "Chat replies that failed.", c.chat_errors)
    emit("chat_in_flight", "gauge", "Chat replies streaming now.", c.chat_in_flight)
    emit("chat_seconds_total", "counter", "Time spent streaming chat replies.", c.chat_seconds)
    emit("chat_prompt_tokens_total", "counter", "Prompt tokens sent (provider-reported).", c.chat_prompt_tokens)
    emit("chat_completion_tokens_total", "counter", "Completion tokens received.", c.chat_completion_tokens)
    emit("chat_cached_tokens_total", "counter", "Prompt tokens served from the provider cache.", c.chat_cached_tokens)
    emit("chat_cost_usd_total", "counter", "LLM cost in USD (provider-reported).", c.chat_cost)
    emit("chat_tokens_today", "gauge", "LLM tokens (prompt + completion) used today, UTC.", c.chat_tokens_today)
    emit("chat_daily_token_budget", "gauge", "Daily LLM token budget; 0 = unlimited.", c.chat_daily_tokens)
    emit("sql_queries_total", "counter", "Assistant SQL queries run.", c.sql_queries)
    emit("sql_errors_total", "counter", "Assistant SQL queries that failed.", c.sql_errors)
    emit("sql_seconds_total", "counter", "Time spent in assistant SQL queries.", c.sql_seconds)
    emit("feedback_total", "counter", "Feedback stored (check-in ratings and sent reports).", c.feedback)
    if s is not None:
        emit("process_cpu_percent", "gauge", "Process CPU over the last sample interval.", s.cpu_pct)
        emit("process_resident_memory_bytes", "gauge", "Resident set size.", s.rss_mb * 1e6)
        emit("process_open_fds", "gauge", "Open file descriptors.", s.open_files)
        emit("event_loop_lag_seconds", "gauge", "Worst event loop lag in the last interval.", s.loop_lag_ms / 1000)
    return "\n".join(lines) + "\n"


def sample_dict(s: Sample) -> dict:
    return asdict(s)
