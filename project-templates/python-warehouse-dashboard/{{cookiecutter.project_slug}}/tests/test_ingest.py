import json
from datetime import date

import pytest

from {{cookiecutter.package_name}}.generate import generate
from {{cookiecutter.package_name}}.ingest import MANIFEST, REQUIRED, TEXT_INDEX, ShrinkError, build


def test_build_writes_every_read_model_and_the_manifest_last(warehouse, db):
    for name in REQUIRED:
        assert (warehouse / f"{name}.parquet").exists()
    assert (warehouse / f"{TEXT_INDEX}.sqlite").exists()
    m = json.loads((warehouse / MANIFEST).read_text())
    [(tickets,)] = db("SELECT count(*) FROM tickets")
    assert m["rows"]["tickets"] == tickets == m["rows"][TEXT_INDEX]
    assert m["data_through"] == "2024-06-30"
    assert not list(warehouse.glob(".build-*"))  # the scratch dir is gone


def test_rollups_reaggregate_to_the_detail_table(db):
    detail = db("SELECT count(*), count(*) FILTER (escalated), round(sum(resolution_hours), 1), "
                "count(satisfaction), sum(satisfaction) FROM tickets")  # fmt: skip
    rollup = db("SELECT sum(tickets), sum(escalated), round(sum(resolution_hours), 1), sum(csat_responses), "
                "sum(csat_points) FROM tickets_state_year")  # fmt: skip
    assert detail == rollup


def test_unchanged_source_skips_and_force_rebuilds(tmp_path):
    raw = tmp_path / "raw"
    generate(raw, date(2024, 1, 1), date(2024, 1, 31), daily=4)
    first = build(raw, tmp_path / "wh")
    assert not first.skipped
    again = build(raw, tmp_path / "wh")
    assert again.skipped and again.built_at == first.built_at
    assert not build(raw, tmp_path / "wh", force=True).skipped


def test_new_data_rebuilds(tmp_path):
    raw = tmp_path / "raw"
    generate(raw, date(2024, 1, 1), date(2024, 1, 31), daily=4)
    first = build(raw, tmp_path / "wh")
    generate(raw, date(2024, 1, 1), date(2024, 2, 10), daily=4)
    second = build(raw, tmp_path / "wh")
    assert not second.skipped and second.rows["tickets"] > first.rows["tickets"]
    assert second.data_through == "2024-02-10"


def test_a_shrinking_source_is_refused_and_the_live_build_kept(tmp_path):
    raw, wh = tmp_path / "raw", tmp_path / "wh"
    generate(raw, date(2024, 1, 1), date(2024, 3, 31), daily=4)
    good = build(raw, wh)
    generate(raw, date(2024, 1, 1), date(2024, 2, 15), daily=4)  # half the feed went missing
    with pytest.raises(ShrinkError, match="refusing"):
        build(raw, wh)
    assert json.loads((wh / MANIFEST).read_text())["built_at"] == good.built_at
    assert build(raw, wh, force=True).data_through == "2024-02-15"


def test_no_raw_files_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="generate"):
        build(tmp_path, tmp_path / "wh")
