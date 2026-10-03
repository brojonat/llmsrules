from pathlib import Path

import pytest

from {{cookiecutter.package_name}} import evals
from {{cookiecutter.package_name}}.warehouse import Filter

CASES = Path(__file__).parent.parent / "evals" / "cases.toml"


def test_the_shipped_battery_is_valid():
    cases = evals.load_cases(CASES)
    assert len(cases) >= 8
    assert all(c["id"].startswith("view-") for c in evals.load_cases(CASES, ("view-",)))


def test_the_battery_rejects_typos(tmp_path):
    bad = tmp_path / "cases.toml"
    bad.write_text('[[case]]\nid = "x"\nask = "hi"\nrequire_tool = ["set_view"]\n')
    with pytest.raises(ValueError, match="unknown keys"):
        evals.load_cases(bad)


def test_truth_sql_in_the_battery_runs(warehouse, db):
    """Every truth query must run against a real warehouse, so a renamed
    column fails here rather than in a paid eval run."""
    facts = {"setup_filter": "true", "data_through": "2024-06-30", "through_year": 2024}
    for case in evals.load_cases(CASES):
        for spec in case.get("numbers", []):
            db(spec["sql"].format(**facts))


def test_numbers_parse_what_models_write():
    text = "There were **1,193** tickets (3.2% escalated), about 1.4K in 2021 and 2.1M overall; Team-50."
    assert evals._numbers(text) == [1193, 3.2, 1400, 2021, 2.1e6, 50]


def test_view_check():
    f = Filter(products=("Ledger", "Relay"), years=(2024, 2025, 2026))
    assert evals._check_view({"products": ["Relay", "Ledger"], "years_from": 2024}, f, 2026).ok
    assert evals._check_view({"states": []}, f, 2026).ok
    bad = evals._check_view({"products": ["Ledger"], "metric": "per_capita"}, f, 2026)
    assert not bad.ok and "products" in bad.detail and "metric" in bad.detail


def test_chart_check():
    chart = {
        "kind": "line",
        "legend": [["Pro", 0], ["Team", 1]],
        "panels": [{"name": "", "series": [{"name": "Pro", "points": [[2020, 5], [2021, 7]]},
                                           {"name": "Team", "points": [[2020, 3], [2021, None]]}]}],
    }  # fmt: skip
    assert evals._check_chart({"kind": "line", "series": 2, "min_points": 4}, [chart], lambda: 15).ok
    assert evals._check_chart({"total_equals_dataset": True}, [chart], lambda: 15).ok
    assert not evals._check_chart({"total_equals_dataset": True}, [chart], lambda: 16).ok
    assert not evals._check_chart({"kind": "bar"}, [chart], lambda: 0).ok
    assert not evals._check_chart({}, [], lambda: 0).ok
