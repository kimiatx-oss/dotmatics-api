"""Run a synthetic full load, refresh replay and rollback without a live server."""

import argparse
import sqlite3
from copy import deepcopy
from pathlib import Path

from .incremental import refresh
from .mirror import Source, full_load
from .schema import TABLES, ParsingError


class FakeBrowser:
    """Synthetic Browser-compatible replies; not a simulation of vendor guarantees."""

    def __init__(self):
        self.projects_by_name = {
            name: {"projectID": str(i)}
            for i, name in enumerate(("Notebook", "Registry", "Assays"), 1)
        }
        self.datasources_by_name = {name: {} for name in self.projects_by_name}
        self.data = {}
        self.fields = {}
        self.fetches = []
        self.queries = []
        self.count_offset = 0
        self.truncate_ids = None
        self.fetch_cap = None
        self.drop_ids = set()
        for i, table in enumerate(TABLES, 10):
            self.datasources_by_name[table.project][table.datasource] = {"dsID": str(i)}
            self.data[table.datasource] = {}
            self.fields[table.datasource] = table.primary_source
            if table.audit:
                self.datasources_by_name[table.project][table.audit] = {
                    "dsID": str(i + 100)
                }
                self.data[table.audit] = {}
                self.fields[table.audit] = table.primary_source
        self.data["DEMO_PROTOCOL_VW"] = {
            "1": {"PROTOCOL_ID": "1", "NAME": "Demo assay"}
        }
        self.data["DEMO_COMPOUND_VW"] = {
            "1": {"REG_ID": "1", "COMPOUND_ID": "CMP-000000001", "SMILES": "CCO"}
        }
        self.data["STUDIES_SUMMARY"] = {
            "10": {
                "EXPERIMENT_ID": "10",
                "PROTOCOL_ID": "1",
                "NAME": "Demo experiment",
                "CREATED_DATE": "2026-01-01T12:00:00Z",
            }
        }
        self.data["DEMO_BATCH_VW"] = {
            "100": {"BATCH_PK": "100", "REG_ID": "1", "ACTIVE": "false"}
        }
        self.data["DEMO_PLATE_RESULTS_VW"] = {
            "1000": {
                "RESULT_ID": "1000",
                "EXPERIMENT_ID": "10",
                "VALUE": "2.5",
                "CONC": "1",
                "CONC_UNIT": "uM",
            },
            "1001": {
                "RESULT_ID": "1001",
                "EXPERIMENT_ID": "10",
                "VALUE": "3.5",
                "CONC": "2",
                "CONC_UNIT": "nM",
            },
        }

    def run_query(
        self,
        column,
        operator,
        value,
        project=None,
        datasources=None,
        limit=-1,
        **kwargs,
    ):
        datasource = datasources[0]
        self.queries.append((datasource, column, operator, value, limit))
        rows = self.data[datasource]
        ids = sorted(
            pk
            for pk, row in rows.items()
            if operator != "equals" or str(row.get(column)) == str(value)
        )
        count = max(0, len(ids) + self.count_offset)
        effective = limit if limit >= 0 else 1000
        ids = ids[:effective]
        if self.truncate_ids is not None and limit:
            ids = ids[: self.truncate_ids]
        return {"ids": ids, "count": count}

    def fetch_data(self, pid=None, dsids=None, ids=None, **kwargs):
        dsid = dsids[0]
        datasource = next(
            name
            for project in self.datasources_by_name.values()
            for name, info in project.items()
            if info["dsID"] == dsid
        )
        self.fetches.append((datasource, list(ids)))
        selected = ids if self.fetch_cap is None else ids[: self.fetch_cap]
        return {
            pk: {
                "primary": pk,
                "dataSources": {dsid: {"1": deepcopy(self.data[datasource][pk])}},
            }
            for pk in selected
            if pk in self.data[datasource] and pk not in self.drop_ids
        }

    def mark_changed(self, table_name, pk, deleted=False):
        table = next(t for t in TABLES if t.name == table_name)
        self.data[table.audit][str(pk)] = {
            table.primary_source: str(pk),
            "IS_DELETED": deleted,
            "ENTRY_DATE": "2026-01-02T12:00:00Z",
        }
        if deleted:
            self.data[table.datasource].pop(str(pk), None)


def run_demo(path):
    browser = FakeBrowser()
    source = Source(browser)
    full_load(source, path)
    browser.data["DEMO_PLATE_RESULTS_VW"]["1000"]["VALUE"] = "4.5"
    browser.mark_changed("experiments", "10")
    refresh(source, path)
    refresh(source, path)
    with sqlite3.connect(path) as conn:
        before = conn.execute(
            "SELECT * FROM plate_results ORDER BY result_id"
        ).fetchall()
    browser.data["DEMO_PLATE_RESULTS_VW"]["1000"]["VALUE"] = "invalid"
    try:
        refresh(source, path)
    except ParsingError:
        pass
    else:
        raise AssertionError("Injected failure was not detected")
    with sqlite3.connect(path) as conn:
        after = conn.execute(
            "SELECT * FROM plate_results ORDER BY result_id"
        ).fetchall()
    if before != after:
        raise AssertionError("Refresh failure did not roll back")
    print(f"Created {path}: full load, refresh replay and rollback verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    run_demo(args.database)


if __name__ == "__main__":
    main()
