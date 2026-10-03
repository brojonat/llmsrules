import csv
import gzip
from datetime import date

from {{cookiecutter.package_name}}.generate import generate, raw_files
from {{cookiecutter.package_name}}.schema import RAW_COLUMNS


def _rows(path):
    with gzip.open(path, "rt") as f:
        return list(csv.DictReader(f))


def test_same_inputs_same_bytes_and_nothing_rewritten(tmp_path):
    first = generate(tmp_path / "a", date(2024, 1, 1), date(2024, 2, 15), daily=5, seed=3)
    again = generate(tmp_path / "a", date(2024, 1, 1), date(2024, 2, 15), daily=5, seed=3)
    elsewhere = generate(tmp_path / "b", date(2024, 1, 1), date(2024, 2, 15), daily=5, seed=3)
    assert [r.changed for r in first] == [True] and [r.changed for r in again] == [False]
    assert first[0].sha256 == again[0].sha256 == elsewhere[0].sha256
    assert first[0].rows > 100


def test_a_different_seed_is_a_different_feed(tmp_path):
    a = generate(tmp_path / "a", date(2024, 1, 1), date(2024, 1, 31), seed=1)
    b = generate(tmp_path / "b", date(2024, 1, 1), date(2024, 1, 31), seed=2)
    assert a[0].sha256 != b[0].sha256


def test_extending_until_appends_days_and_leaves_past_years_alone(tmp_path):
    raw = tmp_path / "raw"
    before = {r.file: r.sha256 for r in generate(raw, date(2022, 6, 1), date(2023, 3, 1), daily=4)}
    after = generate(raw, date(2022, 6, 1), date(2023, 5, 1), daily=4)
    by_file = {r.file: r for r in after}
    old_2022, old_2023 = (str(raw / f"tickets-{y}.csv.gz") for y in (2022, 2023))
    assert not by_file[old_2022].changed and by_file[old_2022].sha256 == before[old_2022]
    assert by_file[old_2023].changed
    # The days already there come out the same: same ids, same text.
    ids_then = {r["ticket_id"] for r in _rows(raw / "tickets-2022.csv.gz")}
    assert len(ids_then) == by_file[old_2022].rows


def test_files_have_the_schema_columns_and_sane_values(tmp_path):
    generate(tmp_path, date(2023, 1, 1), date(2023, 12, 31), daily=8)
    rows = _rows(tmp_path / "tickets-2023.csv.gz")
    assert list(rows[0]) == [c for c, _ in RAW_COLUMNS]
    assert {r["plan"] for r in rows} == {"Free", "Pro", "Team", "Enterprise"}
    assert "Quill" in {r["product"] for r in rows}  # launched 2023-03-01
    assert all(r["opened_at"][:10] >= "2023-03-01" for r in rows if r["product"] == "Quill")
    assert all(float(r["refund_usd"]) == 0 for r in rows if r["category"] != "Billing" or r["plan"] == "Free")
    assert all(1 <= int(r["satisfaction"]) <= 5 for r in rows if r["satisfaction"])
    assert all(r["resolved_at"] > r["opened_at"] for r in rows if r["resolved_at"])
    assert len({r["ticket_id"] for r in rows}) == len(rows)


def test_weekends_are_quieter_and_volume_grows(tmp_path):
    generate(tmp_path, date(2020, 1, 1), date(2024, 12, 31), daily=10)
    rows = [r for f in raw_files(tmp_path) for r in _rows(f)]
    days = {}
    for r in rows:
        d = date.fromisoformat(r["opened_at"][:10])
        days[d.weekday() >= 5] = days.get(d.weekday() >= 5, 0) + 1
    assert days[True] / 2 < 0.7 * days[False] / 5  # per day
    per_year = {y: sum(r["opened_at"].startswith(str(y)) for r in rows) for y in (2020, 2024)}
    assert per_year[2024] > 2 * per_year[2020]


def test_out_of_range_years_are_removed(tmp_path):
    generate(tmp_path, date(2022, 1, 1), date(2023, 2, 1), daily=2)
    results = generate(tmp_path, date(2023, 1, 1), date(2023, 2, 1), daily=2)
    assert [p.name for p in raw_files(tmp_path)] == ["tickets-2023.csv.gz"]
    assert any(r.removed and r.file.endswith("tickets-2022.csv.gz") for r in results)
