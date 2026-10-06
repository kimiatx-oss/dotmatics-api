import sqlite3
from dataclasses import replace
from datetime import UTC

import pytest

from examples.sqlite_mirror.demo import FakeBrowser, run_demo
from examples.sqlite_mirror.incremental import refresh
from examples.sqlite_mirror.mirror import (
    IncompleteLoad,
    Source,
    chunked,
    connect,
    delete_ids,
    fetch_all_query_ids,
    full_load,
    insert_rows,
    normalized_ids,
)
from examples.sqlite_mirror.schema import (
    TABLES,
    Column,
    ParsingError,
    boolean,
    concentration,
    create_table,
    identifier,
    integer,
    real,
    timestamp,
)


@pytest.fixture
def setup(tmp_path):
    browser = FakeBrowser()
    source = Source(browser, batch_size=3)
    path = tmp_path / "mirror.db"
    full_load(source, path)
    return browser, source, path


def snapshot(path):
    with sqlite3.connect(path) as conn:
        return {
            t.name: conn.execute(
                f'SELECT * FROM "{t.name}" ORDER BY "{t.primary}"'
            ).fetchall()
            for t in TABLES
        }


def test_demo(tmp_path):
    run_demo(tmp_path / "demo.db")


def test_full_load_each_id_once_and_foreign_keys(setup):
    browser, _, path = setup
    fetched = [(view, pk) for view, ids in browser.fetches for pk in ids]
    assert len(fetched) == len(set(fetched)) == 6
    assert snapshot(path)["batches"][0][2] == 0
    assert snapshot(path)["plate_results"][0][-1] == 1000


def test_server_default_defeated_and_count_skew():
    browser = FakeBrowser()
    browser.data["DEMO_COMPOUND_VW"] = {str(i): {"REG_ID": str(i)} for i in range(1500)}
    browser.count_offset = -1
    assert len(Source(browser).ids(TABLES[1])) == 1500
    browser.truncate_ids = 7
    with pytest.raises(IncompleteLoad, match="Truncated"):
        Source(browser).ids(TABLES[1])


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"count": "bad", "ids": []},
        {"count": -1, "ids": []},
        {"count": 2, "ids": ["1", 1]},
        {"count": 1, "ids": None},
    ],
)
def test_invalid_enumeration(reply):
    class Browser:
        def run_query(self, *args, **kwargs):
            return reply

    with pytest.raises(IncompleteLoad):
        fetch_all_query_ids(Browser(), "Registry", "demo", "ID")


def test_saturation_and_large_source_fail():
    class Browser:
        def run_query(self, *args, **kwargs):
            return {
                "count": 0,
                "ids": [] if kwargs["limit"] == 0 else list(range(10_000)),
            }

    with pytest.raises(IncompleteLoad, match="saturated"):
        fetch_all_query_ids(Browser(), "Registry", "demo", "ID")
    with pytest.raises(IncompleteLoad, match="bound"):
        fetch_all_query_ids(Browser(), "Registry", "demo", "ID", max_ids=9999)


def test_empty_ids_dont_enumerate(setup):
    browser, source, _ = setup
    browser.queries.clear()
    assert source.rows(TABLES[1], []) == []
    assert browser.queries == []
    assert normalized_ids(["C2", "A1"]) == ["A1", "C2"]


def test_smaller_batches_recover_response_cap(setup):
    browser, source, _ = setup
    browser.fetch_cap = 1
    assert len(source.rows(TABLES[-1])) == 2


def test_failed_full_load_preserves_existing_destination(setup):
    browser, source, path = setup
    before = path.read_bytes()
    browser.drop_ids = {"1001"}
    with pytest.raises(IncompleteLoad, match="deletion is not confirmed"):
        full_load(source, path)
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".mirror-*"))


def test_mid_run_deleted_id_requires_tombstone(setup):
    browser, source, path = setup
    original = browser.fetch_data

    def fetch(**kwargs):
        if kwargs["dsids"] == [
            browser.datasources_by_name["Registry"]["DEMO_BATCH_VW"]["dsID"]
        ]:
            browser.mark_changed("batches", "100", deleted=True)
        return original(**kwargs)

    browser.fetch_data = fetch
    full_load(source, path)
    assert snapshot(path)["batches"] == []


@pytest.mark.parametrize("failure", ["fetch", "parse", "constraint", "audit"])
def test_incremental_failure_rolls_back_all_tables(setup, failure):
    browser, source, path = setup
    before = snapshot(path)
    browser.mark_changed("experiments", "10")
    browser.mark_changed("compounds", "1")
    browser.data["DEMO_COMPOUND_VW"]["1"]["SMILES"] = "CO"
    if failure == "fetch":
        browser.drop_ids = {"1001"}
    elif failure == "parse":
        browser.data["DEMO_PLATE_RESULTS_VW"]["1000"]["VALUE"] = "bad"
    elif failure == "constraint":
        browser.data["STUDIES_SUMMARY"]["10"]["PROTOCOL_ID"] = "99"
    else:
        browser.data["DEMO_EXPERIMENT_AUDIT_VW"]["10"]["EXPERIMENT_ID"] = "999"
    with pytest.raises((IncompleteLoad, ParsingError, sqlite3.IntegrityError)):
        refresh(source, path)
    assert snapshot(path) == before


def test_refresh_replay_deletion_and_child_replacement(setup):
    browser, source, path = setup
    browser.mark_changed("experiments", "10")
    browser.mark_changed("batches", "100", deleted=True)
    browser.data["DEMO_PLATE_RESULTS_VW"].pop("1001")
    refresh(source, path)
    first = snapshot(path)
    refresh(source, path)
    assert snapshot(path) == first
    assert len(first["plate_results"]) == 1
    assert first["batches"] == []
    assert any(query[2:4] == ("days", "2") for query in browser.queries)
    browser.mark_changed("experiments", "10", deleted=True)
    refresh(source, path)
    assert snapshot(path)["plate_results"] == []


def test_middle_column_migration_uses_named_inserts(tmp_path):
    table = TABLES[1]
    new = replace(
        table,
        columns=(table.columns[0], Column("NOTE", "note", "TEXT"), *table.columns[1:]),
    )
    conn = connect(tmp_path / "migration.db")
    with conn:
        create_table(conn, table)
        create_table(conn, new)
        insert_rows(
            conn,
            new,
            [
                {
                    "REG_ID": "1",
                    "COMPOUND_ID": "CMP-1",
                    "SMILES": "CCO",
                    "NOTE": "middle",
                }
            ],
        )
        assert conn.execute(
            "SELECT note, compound_id, smiles FROM compounds"
        ).fetchone() == ("middle", "CMP-1", "CCO")
    conn.close()


@pytest.mark.parametrize("change", ["type", "remove", "required", "pk", "fk"])
def test_incompatible_schema_requires_rebuild(tmp_path, change):
    table = TABLES[1]
    cols = list(table.columns)
    if change == "type":
        cols[-1] = replace(cols[-1], kind="REAL")
    elif change == "remove":
        cols.pop()
    elif change == "required":
        cols.append(Column("NOTE", "note", "TEXT", required=True))
    elif change == "pk":
        table_new = replace(table, primary="compound_id", primary_source="COMPOUND_ID")
    elif change == "fk":
        table_new = replace(table, foreign_keys=(("reg_id", "other", "id"),))
    if change not in ("pk", "fk"):
        table_new = replace(table, columns=tuple(cols))
    conn = connect(tmp_path / "incompatible.db")
    with conn:
        create_table(conn, table)
        with pytest.raises(ValueError, match="rebuild"):
            create_table(conn, table_new)
    conn.close()


def test_large_delete_batches(tmp_path):
    conn = connect(tmp_path / "delete.db")
    conn.execute("CREATE TABLE items (id INTEGER)")
    conn.executemany("INSERT INTO items VALUES (?)", ((i,) for i in range(2000)))
    delete_ids(conn, "items", "id", set(range(2000)))
    assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize(
    "value,expected",
    [("False", 0), ("0", 0), (False, 0), ("TRUE", 1), ("yes", 1), (1, 1)],
)
def test_boolean(value, expected):
    assert boolean(value) == expected


@pytest.mark.parametrize("unit", ["uM", "µM", "μM"])
def test_micro_units(unit):
    assert concentration(2, unit) == 2000


def test_strict_and_permissive_fields():
    strict = Column("VALUE", "value", "REAL", real)
    assert strict.parse({}) is None
    with pytest.raises(ParsingError):
        strict.parse({"VALUE": "1,2"})
    assert replace(strict, permissive=True).parse({"VALUE": "1,2"}) is None
    with pytest.raises(ParsingError):
        replace(strict, required=True).parse({})
    with pytest.raises(ParsingError):
        boolean("maybe")
    with pytest.raises(ParsingError):
        real("nan")
    with pytest.raises(ParsingError):
        integer("1.5")


def test_datetime_order_timezone_and_sql_identifiers():
    with pytest.raises(ParsingError):
        timestamp("01/02/2026")
    assert timestamp("01/02/2026", day_first=True, default_timezone=UTC).startswith(
        "2026-02-01"
    )
    assert timestamp("2026-01-01T12:00:00Z").endswith("+00:00")
    with pytest.raises(ParsingError):
        timestamp("2026-01-01")
    with pytest.raises(ValueError):
        identifier("x; DROP TABLE protocols")
    with pytest.raises(ValueError):
        list(chunked([], 0))
