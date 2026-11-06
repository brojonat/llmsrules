"""Live views: render once per change, stream the newest frame to every viewer.

The dashboard is the same for every user, so it is one shared frame. A
background task polls the lake's latest snapshot id (cheap, and it changes on
every write from any process), re-renders the dashboard when it moves, and
publishes the HTML. Each open stream sends the newest frame it has not sent
yet; a slow client skips frames instead of queueing them, which is safe
because every frame is the whole view.

Add another shared view by giving it a key and a render function in `VIEWS`.
"""

import asyncio
from collections.abc import Callable

from fastapi.templating import Jinja2Templates

from server.data import LakeConnection
from server.log_config import get_logger

log = get_logger(__name__)

POLL_SECONDS = 2.0


class Frames:
    """Latest frame per view; `_next` is set and replaced on every publish."""

    def __init__(self) -> None:
        self._frames: dict[str, tuple[int, str]] = {}
        self._next = asyncio.Event()

    def current(self, key: str) -> tuple[int, str | None, asyncio.Event]:
        version, html = self._frames.get(key, (0, None))
        return version, html, self._next

    def publish(self, key: str, html: str) -> None:
        version, _ = self._frames.get(key, (0, None))
        self._frames[key] = (version + 1, html)
        self._next.set()
        self._next = asyncio.Event()


def dashboard_context(lake: LakeConnection) -> dict:
    """Everything the dashboard region shows. Missing tables render as empty."""
    try:
        entity_count, event_count = lake.query(
            "SELECT COUNT(DISTINCT entity_id), COUNT(*) FROM lake.events"
        )[0]
        event_types = lake.query(
            "SELECT event_type, COUNT(*) AS n FROM lake.events "
            "GROUP BY event_type ORDER BY n DESC LIMIT 20"
        )
        per_day = lake.query(
            "SELECT strftime(date_trunc('day', timestamp), '%Y-%m-%d') AS day, COUNT(*) "
            "FROM lake.events WHERE timestamp >= now() - INTERVAL 30 DAY "
            "GROUP BY day ORDER BY day"
        )
    except Exception as e:
        log.warning("dashboard_query_failed", error=str(e))
        return {
            "ready": False,
            "entity_count": 0,
            "event_count": 0,
            "event_types": [],
            "per_day": [],
        }
    return {
        "ready": True,
        "entity_count": entity_count,
        "event_count": event_count,
        "event_types": event_types,
        "per_day": [list(row) for row in per_day],
    }


def render_dashboard(templates: Jinja2Templates, lake: LakeConnection) -> str:
    # The same partial renders the first page load and every frame.
    return templates.get_template("_dashboard.html").render(**dashboard_context(lake))


VIEWS: dict[str, Callable[[Jinja2Templates, LakeConnection], str]] = {
    "dashboard": render_dashboard,
}


async def run_renderer(lake: LakeConnection, templates: Jinja2Templates, frames: Frames) -> None:
    """Re-render every view whenever the lake snapshot changes. Runs until cancelled."""
    last = None
    while True:
        try:
            snapshot = await asyncio.to_thread(lake.snapshot_id)
            if snapshot != last:
                for key, render in VIEWS.items():
                    frames.publish(key, await asyncio.to_thread(render, templates, lake))
                last = snapshot
        except Exception as e:
            # Not migrated yet, or the catalog is briefly unreachable: try again next poll.
            log.warning("live_render_failed", error=str(e))
        await asyncio.sleep(POLL_SECONDS)
