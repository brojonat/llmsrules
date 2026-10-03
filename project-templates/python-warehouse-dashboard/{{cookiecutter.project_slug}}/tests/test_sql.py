import pytest

from {{cookiecutter.package_name}}.search import SearchError, TextIndex
from {{cookiecutter.package_name}}.sql import Limits, QueryError, SqlSandbox


@pytest.fixture(scope="module")
def sandbox(warehouse):
    sb = SqlSandbox(warehouse)
    sb.ensure("fixture")
    return sb


def test_select_works_and_reports_shape(sandbox, db):
    r = sandbox.run("SELECT plan, count(*) AS n FROM tickets GROUP BY plan ORDER BY plan")
    assert r["columns"] == ["plan", "n"]
    assert r["rows"] == [list(row) for row in db("SELECT plan, count(*) FROM tickets GROUP BY plan ORDER BY plan")]
    assert r["truncated"] is False


@pytest.mark.parametrize(
    "sql, message",
    [
        ("DROP VIEW tickets", "only SELECT"),
        ("CREATE TABLE t AS SELECT 1", "only SELECT"),
        ("SELECT 1; SELECT 2", "exactly one statement"),
        ("SELECT * FROM read_text('/etc/hosts')", "Permission"),
        ("SELECT * FROM read_csv('https://example.com/x.csv')", "Permission"),
        ("COPY (SELECT 1) TO '/tmp/x.csv'", "only SELECT"),
        ("SET enable_external_access = true", "only SELECT"),
        ("SELEC oops", "syntax error"),
    ],
)
def test_sandbox_refuses_anything_but_a_read(sandbox, sql, message):
    with pytest.raises(QueryError, match=message):
        sandbox.run(sql)


def test_the_warehouse_dir_is_the_only_readable_place(sandbox, warehouse):
    assert sandbox.run(f"SELECT count(*) > 0 FROM '{warehouse}/tickets.parquet'")["rows"] == [[True]]
    with pytest.raises(QueryError, match="Permission"):
        sandbox.run(f"SELECT * FROM read_text('{warehouse}/../raw/tickets-2023.csv.gz')")


def test_timeout_interrupts(warehouse):
    sb = SqlSandbox(warehouse, Limits(timeout=0.5))
    sb.ensure("x")
    with pytest.raises(QueryError, match="timed out"):
        sb.run("SELECT count(*) FROM range(1000000000) a, range(1000) b WHERE a.range % 7 = b.range")


def test_rows_and_cells_are_capped(sandbox):
    r = sandbox.run("SELECT range AS i, repeat('x', 5000) AS s FROM range(1000)")
    assert r["truncated"] and r["row_count"] <= 200 and len(r["rows"][0][1]) <= 401


def test_text_search_is_stemmed_and_finds_incidents(warehouse, db):
    idx = TextIndex(warehouse)
    # Every incident ticket carries its phrase in the subject; the index finds the same ones.
    subject = db("SELECT subject FROM tickets WHERE subject LIKE '%: %' LIMIT 1")[0][0]
    phrase = subject.split(": ", 1)[1]
    [(n,)] = db("SELECT count(*) FROM tickets WHERE subject LIKE ?", [f"%: {phrase}"])
    assert len(idx.match(f'subject:"{phrase}"')) >= n > 0
    assert set(idx.match("charge")) >= set(idx.match("charged"))  # stemmed
    with pytest.raises(SearchError, match="bad search query"):
        idx.match('"unbalanced')
