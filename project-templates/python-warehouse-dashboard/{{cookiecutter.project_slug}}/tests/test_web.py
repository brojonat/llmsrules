import csv
import html
import io
import json
import re
import shutil

from starlette.testclient import TestClient

from {{cookiecutter.package_name}}.warehouse import Filter, Warehouse
from {{cookiecutter.package_name}}.web import Config, _year_series, create_app

J = {"Datastar-Request": "true"}


def _attr(page: str, tag: str, id_: str) -> list:
    m = re.search(rf"<{tag} id=\"{id_}\" series='([^']*)'", page)
    assert m, f"{tag}#{id_} missing"
    return json.loads(html.unescape(m.group(1)))


def _total(page: str) -> int:
    return int(re.search(r"<strong>([\d,]+)</strong> tickets in your dataset", page).group(1).replace(",", ""))


def test_first_paint_has_live_regions_and_stream(client):
    r = client.get("/")
    assert r.status_code == 200
    for region in ('<section id="builder"', '<main id="dashboard">', '<section id="chat"'):
        assert region in r.text
    assert "@get('/stream', {openWhenHidden: true})" in r.text
    assert "sid" in r.cookies


def test_totals_and_year_chart_match_the_warehouse(client, db):
    page = client.get("/").text
    [(n,)] = db("SELECT count(*) FROM tickets")
    assert _total(page) == n
    years = dict(db("SELECT year::VARCHAR, count(*) FROM tickets GROUP BY 1"))
    assert dict(_attr(page, "chart-bars", "year-bars")) == years
    assert "<svg" not in page.split("<main", 1)[1]  # charts are components, not server-drawn SVG


def test_filter_is_a_command_scoped_to_the_session(client, db):
    client.get("/")
    r = client.post("/filter/toggle", json={"dim": "products", "value": "Ledger"}, headers=J)
    assert r.status_code == 204 and r.text == ""
    [(n,)] = db("SELECT count(*) FROM tickets WHERE product = 'Ledger'")
    assert _total(client.get("/").text) == n
    with TestClient(client.app) as other:  # a different session is untouched
        [(everything,)] = db("SELECT count(*) FROM tickets")
        assert _total(other.get("/").text) == everything


def test_filter_rejects_unknown_values(client):
    assert client.post("/filter/toggle", json={"dim": "states", "value": "ZZ"}).status_code == 400
    assert client.post("/filter", json={"metric": "vibes"}).status_code == 400
    assert client.post("/filter/toggle", json={"dim": "colors", "value": "red"}).status_code == 400
    assert client.post("/filter/range", json={"from": "x", "to": 2024}).status_code == 400


def test_builder_ranges_facets_and_clears(client, db):
    client.get("/")
    assert client.post("/filter/range", json={"from": "2024", "to": "2023"}, headers=J).status_code == 204
    assert "2023–2024 <span" in client.get("/").text
    client.post("/filter/toggle", json={"dim": "plans", "value": "Enterprise"}, headers=J)
    client.post("/filter/toggle", json={"dim": "plans", "value": "Team"}, headers=J)
    client.post("/filter/toggle", json={"dim": "states", "value": "ca"}, headers=J)
    [(n,)] = db("SELECT count(*) FROM tickets WHERE plan IN ('Enterprise', 'Team') AND state = 'CA'")
    page = client.get("/").text
    assert _total(page) == n  # OR within a dimension, AND across
    assert 'selected="CA"' in page

    def builder():
        page = client.get("/").text
        return page[page.index('id="builder"') : page.index('id="dashboard"')]

    # Options (and their counts) exist only for the open picker: server state.
    assert 'class="picker-body"' not in builder()
    client.post("/builder/open", json={"dim": "products"}, headers=J)
    assert builder().count('class="picker-body"') == 1
    client.post("/builder/search", json={"dim": "products", "q": "led"}, headers=J)
    body = builder().split('class="picker-body"')[1]
    assert "Ledger <span" in body and "Relay <span" not in body
    client.post("/builder/open", json={"dim": "products"}, headers=J)  # again: closes it
    assert 'class="picker-body"' not in builder()
    client.post("/filter/clear", json={}, headers=J)
    [(everything,)] = db("SELECT count(*) FROM tickets")
    page = client.get("/").text
    assert _total(page) == everything and "Clear all" not in page


def test_picker_counts_are_faceted(warehouse, db):
    wh = Warehouse(warehouse)
    wh.reload_if_changed()
    f = Filter(products=("Ledger",))
    # The products picker ignores the products selection (you can add Relay)...
    assert dict(wh.options(f, "products", "", 40)) == dict(db("SELECT product, count(*) FROM tickets GROUP BY 1"))
    # ...while other pickers count within it.
    assert dict(wh.options(f, "plans", "", 40)) == dict(
        db("SELECT plan, count(*) FROM tickets WHERE product = 'Ledger' GROUP BY 1")
    )


def test_map_compares_every_state_and_outlines_the_selection(client, db):
    client.get("/")
    client.post("/filter/toggle", json={"dim": "states", "value": "TX"}, headers=J)
    rows = {r[1]: r for r in _attr(client.get("/").text, "chart-map", "state-map")}
    [(ca,)] = db("SELECT count(*) FROM tickets WHERE state = 'CA'")
    assert rows["CA"][:4] == ["06", "CA", "California", ca]  # the map ignores the states selection


def test_metrics_and_their_fallbacks(client):
    client.get("/")
    client.post("/filter", json={"metric": "index"}, headers=J)
    page = client.get("/").text
    assert 'metric="count"' in page  # index needs a subset: falls back
    client.post("/filter/toggle", json={"dim": "products", "value": "Atlas"}, headers=J)
    assert 'metric="index"' in client.get("/").text
    client.post("/filter", json={"metric": "csat"}, headers=J)
    page = client.get("/").text
    values = [r[4] for r in _attr(page, "chart-map", "state-map") if r[4] is not None]
    assert values and all(1 <= v <= 5 for v in values)


def test_export_matches_the_dataset(client, db):
    client.get("/")
    client.post("/filter/toggle", json={"dim": "categories", "value": "Billing"}, headers=J)
    r = client.get("/dataset.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    [(n,)] = db("SELECT count(*) FROM tickets WHERE category = 'Billing'")
    assert len(rows) == n and {row["category"] for row in rows} == {"Billing"}
    assert client.get("/dataset.parquet").status_code == 200


def test_admin_and_machine_endpoints(client):
    assert client.get("/healthz").text == "ok"
    assert '<main id="admin">' in client.get("/admin").text
    assert "_open_streams" in client.get("/metrics").text
    assert client.put("/admin/threshold/cpu_pct", data={"value": "50"}).status_code == 204
    assert client.put("/admin/threshold/nope", data={"value": "50"}).status_code == 404
    assert "samples" in client.get("/admin/samples").json()
    assert "# Methodology" not in client.get("/methodology").text  # rendered, not raw markdown
    assert "<h1>Methodology</h1>" in client.get("/methodology").text
    for path in ("/favicon.png", "/apple-touch-icon.png", "/static/components.js"):
        assert client.get(path).status_code == 200


def test_year_series_zero_fills_gaps():
    assert _year_series([(2019, 3), (2021, 5)]) == [["2019", 3], ["2020", 0], ["2021", 5]]
    assert _year_series([]) == []


def test_a_stale_warehouse_does_not_crash_startup(warehouse, tmp_path):
    """Code that expects read models an older build didn't write must keep
    serving (as "not ready"), not die in startup."""
    old = tmp_path / "old"
    shutil.copytree(warehouse, old)
    (old / "tickets_state_year.parquet").unlink()
    with TestClient(create_app(Config(warehouse=old, sample_interval=0.05))) as c:
        r = c.get("/")
        assert r.status_code == 200 and "No warehouse yet" in r.text
