from datetime import date
from pathlib import Path

import duckdb
import pytest

from {{cookiecutter.package_name}}.generate import generate
from {{cookiecutter.package_name}}.ingest import build

# A small, seeded feed: 18 months, a handful of tickets a day. Built once per
# test session; tests that change data build their own in tmp_path.
SINCE, UNTIL, DAILY, SEED = date(2023, 1, 1), date(2024, 6, 30), 6.0, 7


@pytest.fixture(scope="session")
def raw(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data") / "raw"
    generate(root, SINCE, UNTIL, daily=DAILY, seed=SEED)
    return root


@pytest.fixture(scope="session")
def warehouse(raw: Path) -> Path:
    out = raw.parent / "warehouse"
    build(raw, out)
    return out


@pytest.fixture(scope="session")
def db(warehouse: Path):
    """A DuckDB connection over the fixture warehouse, for computing what the
    app should say."""
    con = duckdb.connect()
    for f in warehouse.glob("*.parquet"):
        con.execute(f"CREATE VIEW {f.stem} AS SELECT * FROM read_parquet('{f}')")
    return lambda sql, params=None: con.execute(sql, params or []).fetchall()


@pytest.fixture
def client(warehouse: Path):
    """The app over the fixture warehouse, with chat unconfigured."""
    from starlette.testclient import TestClient

    from {{cookiecutter.package_name}}.web import Config, create_app

    with TestClient(create_app(Config(warehouse=warehouse, sample_interval=0.05))) as c:
        yield c
