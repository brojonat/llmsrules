"""Hold N browser-shaped clients against a running server and measure what
they cost it.

A virtual client does what a tab does: GET / (which issues a session cookie),
then holds GET /stream open, counting patches. With `churn`, each client also
edits its dataset now and then (the CQRS write path) and times how long the
resulting patch takes to arrive on its own stream.

Levels ramp up cumulatively (5, then 5 more to 10, then 90 more to 100 ...).
At each level, after a settle period, the server's own samples from
/admin/samples over the hold window are summarised alongside client-side
latencies. One JSON object per level goes to stdout.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from statistics import median, quantiles

import httpx

from .generate import PLANS, PRODUCTS

CATEGORIES = ["Billing", "Access", "Performance", "Bug", "Data loss", "Integrations", "How-to"]
METRICS = ["count", "per_capita", "index", "resolution", "csat", "escalation"]
STATES = ["CA", "TX", "FL", "NY", "OH", "PA", "WA", "OR"]
QUESTIONS = [
    "How is resolution time computed?",
    "Why are some states hatched on the map?",
    "What does the national-mix index mean?",
    "Are open tickets counted in satisfaction?",
]
PATCH = b"event: datastar-patch-elements"


def random_command() -> tuple[str, dict]:
    """One dataset-builder action of the kinds a person takes: opt a product,
    plan or state in/out, drag a year range, change the map metric, search a
    picker, or start over. Mixed so the server sees a realistic cache-miss
    rate (and the builder's per-session region re-renders)."""
    kind = random.choice(["product", "product", "plan", "category", "state", "range", "metric", "search", "clear"])
    if kind == "product":
        return "/filter/toggle", {"dim": "products", "value": random.choice(PRODUCTS).name}
    if kind == "plan":
        return "/filter/toggle", {"dim": "plans", "value": random.choice(list(PLANS))}
    if kind == "category":
        return "/filter/toggle", {"dim": "categories", "value": random.choice(CATEGORIES)}
    if kind == "state":
        return "/filter/toggle", {"dim": "states", "value": random.choice(STATES)}
    if kind == "range":
        lo = random.randint(2019, 2025)
        return "/filter/range", {"from": lo, "to": random.randint(lo, 2026)}
    if kind == "metric":
        return "/filter", {"metric": random.choice(METRICS)}
    if kind == "search":  # open the products picker (or close it) and search it
        return random.choice([
            ("/builder/open", {"dim": "products"}),
            ("/builder/search", {"dim": "products", "q": random.choice(["le", "re", "at", "ha", ""])}),
        ])  # fmt: skip
    return "/filter/clear", {}


@dataclass
class Stats:
    connected: int = 0
    failed: int = 0
    patches: int = 0
    first_patch_ms: list[float] = field(default_factory=list)
    command_ms: list[float] = field(default_factory=list)
    chats_sent: int = 0
    chats_refused: int = 0  # 409: previous reply still streaming
    errors: list[str] = field(default_factory=list)


class Client:
    def __init__(self, base: str, stats: Stats, churn: float, chat: float = 0) -> None:
        self.http = httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(30, read=None))
        self.stats = stats
        self.churn = churn
        self.chat = chat
        self._pending: float | None = None  # perf_counter when the last command went out

    async def run(self) -> None:
        s = self.stats
        started = time.perf_counter()
        try:
            (await self.http.get("/")).raise_for_status()
            headers = {"Datastar-Request": "true", "Accept": "text/event-stream"}
            async with self.http.stream("GET", "/stream", headers=headers) as r:
                r.raise_for_status()
                s.connected += 1
                first = True
                writer = asyncio.create_task(self._write()) if self.churn > 0 else None
                asker = asyncio.create_task(self._ask()) if self.chat > 0 else None
                try:
                    async for chunk in r.aiter_bytes():
                        n = chunk.count(PATCH)
                        if not n:
                            continue
                        now = time.perf_counter()
                        s.patches += n
                        if first:
                            s.first_patch_ms.append(1000 * (now - started))
                            first = False
                        elif self._pending is not None:
                            s.command_ms.append(1000 * (now - self._pending))
                            self._pending = None
                finally:
                    for task in (writer, asker):
                        if task:
                            task.cancel()
                    s.connected -= 1
        except asyncio.CancelledError:
            raise
        except Exception as e:  # a load test reports failures, it does not stop on them
            s.failed += 1
            if len(s.errors) < 20:
                s.errors.append(f"{type(e).__name__}: {e}")
        finally:
            await self.http.aclose()

    async def _ask(self) -> None:
        """Ask the chat assistant now and then. Replies stream into this
        client's page stream as chat-region patches."""
        while True:
            await asyncio.sleep(random.expovariate(1 / self.chat))
            r = await self.http.post("/chat/send", json={"message": random.choice(QUESTIONS)},
                                     headers={"Datastar-Request": "true"})  # fmt: skip
            if r.status_code == 204:
                self.stats.chats_sent += 1
            elif r.status_code == 409:
                self.stats.chats_refused += 1
            elif len(self.stats.errors) < 20:
                self.stats.errors.append(f"POST /chat/send -> {r.status_code}: {r.text[:80]}")

    async def _write(self) -> None:
        while True:
            await asyncio.sleep(random.expovariate(1 / self.churn))
            self._pending = time.perf_counter()
            path, body = random_command()
            r = await self.http.post(path, json=body, headers={"Datastar-Request": "true"})
            if r.status_code != 204 and len(self.stats.errors) < 20:
                self.stats.errors.append(f"POST {path} {body} -> {r.status_code}: {r.text[:80]}")


def _pct(xs: list[float], q: int) -> float | None:
    if not xs:
        return None
    if len(xs) == 1:
        return round(xs[0], 1)
    return round(quantiles(xs, n=100)[q - 1], 1)


async def _server_window(base: str, since: float) -> dict:
    # /admin is behind basic auth in production: ADMIN_AUTH=user:password.
    auth = tuple(os.environ["ADMIN_AUTH"].split(":", 1)) if os.environ.get("ADMIN_AUTH") else None
    async with httpx.AsyncClient(base_url=base, timeout=10, auth=auth) as http:
        r = await http.get("/admin/samples", params={"since": since})
        if r.status_code == 401:
            print("loadtest: /admin/samples needs ADMIN_AUTH=user:password", file=sys.stderr)
            return {}
        samples = r.json()["samples"]
    if not samples:
        return {}

    def col(k: str) -> list[float]:
        return [s[k] for s in samples]

    return {
        "samples": len(samples),
        "streams": max(col("streams")),
        "cpu_pct_p50": round(median(col("cpu_pct")), 1),
        "cpu_pct_max": round(max(col("cpu_pct")), 1),
        "rss_mb_max": round(max(col("rss_mb")), 1),
        "loop_lag_ms_p50": round(median(col("loop_lag_ms")), 1),
        "loop_lag_ms_max": round(max(col("loop_lag_ms")), 1),
        "patches_per_s_p50": round(median(col("patches_per_s")), 1),
        "wire_kbps_p50": round(median(col("wire_kbps")), 1),
        "open_files_max": max(col("open_files")),
        "chats_streaming_max": max(col("chats_streaming")),
    }


async def run(
    base: str, levels: list[int], hold: float, settle: float, churn: float, ramp: float, chat: float = 0
) -> list[dict]:
    """Ramp through `levels`, printing one JSON result per level."""
    stats = Stats()
    tasks: list[asyncio.Task] = []
    results = []
    try:
        for level in levels:
            print(f"loadtest: ramping to {level} clients", file=sys.stderr)
            mark_first = len(stats.first_patch_ms)
            while len(tasks) < level:
                c = Client(base, stats, churn, chat)
                tasks.append(asyncio.create_task(c.run()))
                await asyncio.sleep(1 / ramp)
            await asyncio.sleep(settle)
            mark_cmd, mark_patches, mark_chats = len(stats.command_ms), stats.patches, stats.chats_sent
            window_start = time.time()
            print(f"loadtest: holding {level} clients for {hold:.0f}s", file=sys.stderr)
            await asyncio.sleep(hold)
            # Latencies observed since this level started ramping.
            first_ms, command_ms = stats.first_patch_ms[mark_first:], stats.command_ms[mark_cmd:]
            result = {
                "clients": level,
                "connected": stats.connected,
                "failed": stats.failed,
                "hold_s": hold,
                "churn_s": churn,
                "client_patches": stats.patches - mark_patches,
                "chats_sent": stats.chats_sent - mark_chats,
                "chats_refused": stats.chats_refused,
                "first_patch_ms_p50": _pct(first_ms, 50),
                "first_patch_ms_p95": _pct(first_ms, 95),
                "command_to_patch_ms_p50": _pct(command_ms, 50),
                "command_to_patch_ms_p95": _pct(command_ms, 95),
                "server": await _server_window(base, window_start),
            }
            if stats.errors:
                result["errors"] = stats.errors[:5]
            print(json.dumps(result), flush=True)
            results.append(result)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return results
