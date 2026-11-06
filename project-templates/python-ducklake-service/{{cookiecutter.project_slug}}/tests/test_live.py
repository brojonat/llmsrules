"""Live views and Datastar partials. No services needed."""

import asyncio

from server.live import Frames, dashboard_context
from server.routes.api import event_filters
from server.routes.pages import templates


async def test_frames_wake_streams_and_keep_only_the_newest():
    frames = Frames()
    version, html, next_frame = frames.current("dashboard")
    assert (version, html) == (0, None)

    frames.publish("dashboard", "<div id='dashboard'>1</div>")
    frames.publish("dashboard", "<div id='dashboard'>2</div>")

    # A stream waiting on the old event wakes, and reads only the newest frame.
    await asyncio.wait_for(next_frame.wait(), timeout=1)
    assert frames.current("dashboard")[:2] == (2, "<div id='dashboard'>2</div>")


class BrokenLake:
    def query(self, sql, params=None):
        raise RuntimeError("Catalog Error: Table with name events does not exist!")


def test_dashboard_renders_before_migrations():
    html = templates.get_template("_dashboard.html").render(**dashboard_context(BrokenLake()))
    assert 'id="dashboard"' in html
    assert "mise run migrate" in html


def test_dashboard_chart_carries_its_data_in_an_attribute():
    html = templates.get_template("_dashboard.html").render(
        ready=True,
        entity_count=2,
        event_count=1234,
        event_types=[("click", 1234)],
        per_day=[["2026-10-01", 1234]],
    )
    assert '<chart-bars id="events-per-day"' in html
    assert "series='[[\"2026-10-01\", 1234]]'" in html
    assert "1,234" in html


def test_entity_rows_escape_ids():
    html = templates.get_template("_entity_rows.html").render(entities=["<b>o'brien</b>"])
    assert html.startswith('<tbody id="entity-list">')
    assert "<b>" not in html
    assert 'href="/entities/%3Cb%3Eo%27brien%3C/b%3E"' in html


def test_event_filters_bind_every_value():
    where, params = event_filters("o'brien", None, None, None)
    assert where == "WHERE entity_id = ?"
    assert params == ["o'brien"]
    assert event_filters(None, None, None, None) == ("", [])
