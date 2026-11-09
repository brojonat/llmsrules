"""LakeConnection against a local DuckLake (file catalog, local data path). No services needed."""

import ibis
from server.config import get_settings
from server.data import LakeConnection


def local_lake(tmp_path) -> LakeConnection:
    lake = LakeConnection(get_settings())
    con = ibis.duckdb.connect()
    con.raw_sql("INSTALL ducklake; LOAD ducklake")
    con.raw_sql(
        f"ATTACH 'ducklake:{tmp_path}/catalog.ducklake' AS lake (DATA_PATH '{tmp_path}/data/')"
    )
    lake._con = con
    return lake


def test_execute_many_commits_one_snapshot(tmp_path):
    lake = local_lake(tmp_path)
    lake.query("CREATE TABLE lake.t (n INTEGER)")
    before = lake.snapshot_id()

    lake.execute_many("INSERT INTO lake.t VALUES (?)", [[n] for n in range(50)])

    assert lake.snapshot_id() == before + 1
    assert lake.query("SELECT count(*) FROM lake.t") == [(50,)]
