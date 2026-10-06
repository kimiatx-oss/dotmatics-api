"""Conservative API extraction and atomic SQLite publication."""

import argparse
import logging
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from dotmatics_api import Browser

from .schema import TABLES, boolean, create_table, identifier, integer

log = logging.getLogger(__name__)


class IncompleteLoad(ValueError):
    """The returned data cannot satisfy the extraction contract."""


def chunked(values, size):
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("Batch size must be a positive integer")
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start : start + size]


def normalized_ids(values):
    if not isinstance(values, (list, tuple, set)):
        raise IncompleteLoad("Expected an ID collection")
    ids = []
    for value in values:
        if (
            not isinstance(value, (str, int))
            or isinstance(value, bool)
            or not str(value)
            or str(value) == "*"
        ):
            raise IncompleteLoad("Malformed primary ID")
        ids.append(str(value))
    if len(ids) != len(set(ids)):
        raise IncompleteLoad("Duplicate primary IDs")
    # Stable lexical order also supports alphanumeric primary keys in custom schemas.
    return sorted(ids)


def reported_count(response):
    if not isinstance(response, dict) or "count" not in response:
        raise IncompleteLoad("Missing query count")
    try:
        count = integer(response["count"])
    except ValueError as exc:
        raise IncompleteLoad("Invalid query count") from exc
    if count < 0:
        raise IncompleteLoad("Negative query count")
    return count


def fetch_all_query_ids(
    browser,
    project,
    datasource,
    column,
    operator="greaterthanequals",
    value="0",
    *,
    max_ids=100_000,
):
    """Validate a bounded enumeration. Count skew can still hide omissions; see README."""
    count = reported_count(
        browser.run_query(
            column, operator, value, project=project, datasources=[datasource], limit=0
        )
    )
    limit = count + 10_000
    if limit > max_ids:
        raise IncompleteLoad(
            "Enumeration exceeds configured bound; implement validated stable-key partitions before proceeding"
        )
    response = browser.run_query(
        column, operator, value, project=project, datasources=[datasource], limit=limit
    )
    count = reported_count(response)
    if "ids" not in response:
        raise IncompleteLoad("Missing query IDs")
    ids = normalized_ids(response["ids"])
    if len(ids) < count or len(ids) >= limit:
        raise IncompleteLoad("Truncated or saturated query enumeration")
    if len(ids) > count:
        log.warning(
            "Query count under-reports enumerated IDs; count is not a completeness proof"
        )
    return ids


class Source:
    """One source row per primary ID, including independent RESULT_ID primary keys."""

    def __init__(self, browser, tables=TABLES, batch_size=100, max_ids=100_000):
        list(chunked([], batch_size))
        if max_ids <= 10_000:
            raise ValueError("max_ids must exceed enumeration slack of 10000")
        self.browser = browser
        self.tables = tables
        self.batch_size = batch_size
        self.max_ids = max_ids

    def preflight(self):
        for table in self.tables:
            self._resolve(table.project, table.datasource)
            if table.audit:
                self._resolve(table.project, table.audit)

    def _resolve(self, project, datasource):
        if self.browser.projects_by_name is None:
            self.browser._populate_projects()
        if self.browser.datasources_by_name is None:
            self.browser._populate_datasources()
        try:
            return str(self.browser.projects_by_name[project]["projectID"]), str(
                self.browser.datasources_by_name[project][datasource]["dsID"]
            )
        except KeyError as exc:
            raise ValueError(
                f"Missing configured project/view: {project}/{datasource}"
            ) from exc

    def ids(self, table, *, column=None, operator="greaterthanequals", value="0"):
        return fetch_all_query_ids(
            self.browser,
            table.project,
            table.datasource,
            column or table.primary_source,
            operator,
            value,
            max_ids=self.max_ids,
        )

    def _fetch_chunk(self, project, datasource, ids):
        pid, dsid = self._resolve(project, datasource)
        response = self.browser.fetch_data(
            pid=pid, dsids=[dsid], ids=ids, alias_column_names=False
        )
        if not isinstance(response, dict) or set(response) - set(ids):
            raise IncompleteLoad("Malformed response or unrequested IDs")
        rows = {}
        for pk in ids:
            record = response.get(pk)
            if record is None:
                continue
            if not isinstance(record, dict) or str(record.get("primary")) != pk:
                raise IncompleteLoad("Malformed primary record")
            sources = record.get("dataSources")
            if not isinstance(sources, dict):
                raise IncompleteLoad("Malformed datasource payload")
            data = sources.get(dsid)
            if data is None or data == {}:
                continue
            if (
                not isinstance(data, dict)
                or len(data) != 1
                or not isinstance(next(iter(data.values())), dict)
            ):
                raise IncompleteLoad(
                    "View must return exactly one row per primary ID; enumerate child RESULT_IDs independently"
                )
            rows[pk] = next(iter(data.values()))
        if len(rows) != len(ids) and len(ids) > 1:
            # A smaller explicit-ID request may avoid a response cap. Never retry a write here.
            mid = len(ids) // 2
            return {
                **self._fetch_chunk(project, datasource, ids[:mid]),
                **self._fetch_chunk(project, datasource, ids[mid:]),
            }
        return rows

    def _fetch(self, project, datasource, ids):
        rows = {}
        for batch in chunked(normalized_ids(ids), self.batch_size):
            rows.update(self._fetch_chunk(project, datasource, batch))
        return rows

    def tombstone(self, table, pk):
        if not table.audit:
            return False
        audit = self._fetch(table.project, table.audit, [pk])
        row = audit.get(pk)
        return bool(
            row
            and str(row.get(table.primary_source)) == pk
            and boolean(row.get("IS_DELETED"))
        )

    def rows(self, table, ids=None, *, deleted=()):
        requested = self.ids(table) if ids is None else normalized_ids(ids)
        rows = self._fetch(table.project, table.datasource, requested)
        allowed_missing = set(deleted)
        for pk in set(requested) - set(rows):
            if pk not in allowed_missing and not self.tombstone(table, pk):
                raise IncompleteLoad(
                    f"Missing {table.name} primary ID {pk}; deletion is not confirmed"
                )
        for pk, row in rows.items():
            if str(row.get(table.primary_source)) != pk:
                raise IncompleteLoad("Source row key differs from requested primary ID")
        return list(rows.values())

    def changes(self, table, days):
        if not table.audit:
            return [], set()
        ids = fetch_all_query_ids(
            self.browser,
            table.project,
            table.audit,
            "ENTRY_DATE",
            "days",
            str(days),
            max_ids=self.max_ids,
        )
        rows = self._fetch(table.project, table.audit, ids)
        if set(rows) != set(ids):
            raise IncompleteLoad("Incomplete audit response")
        deleted = set()
        for pk, row in rows.items():
            if str(row.get(table.primary_source)) != pk:
                raise IncompleteLoad(
                    "Audit primary ID must match the entity primary ID"
                )
            if boolean(row.get("IS_DELETED")):
                deleted.add(pk)
        return [pk for pk in ids if pk not in deleted], deleted


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def insert_rows(conn, table, rows):
    names = ", ".join(identifier(c.name) for c in table.columns)
    placeholders = ", ".join("?" for _ in table.columns)
    updates = ", ".join(
        f"{identifier(c.name)}=excluded.{identifier(c.name)}"
        for c in table.columns
        if c.name != table.primary
    )
    conflict = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    statement = f"INSERT INTO {identifier(table.name)} ({names}) VALUES ({placeholders}) ON CONFLICT({identifier(table.primary)}) {conflict}"
    conn.executemany(statement, ([c.parse(row) for c in table.columns] for row in rows))


def delete_ids(conn, table, column, ids):
    # 500 is below the historical SQLite 999-variable default.
    for batch in chunked(sorted(ids), 500):
        placeholders = ",".join("?" for _ in batch)
        conn.execute(
            f"DELETE FROM {identifier(table)} WHERE {identifier(column)} IN ({placeholders})",
            batch,
        )


def validate(conn):
    if (
        conn.execute("PRAGMA foreign_key_check").fetchone()
        or conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
    ):
        raise IncompleteLoad("SQLite integrity validation failed")


def full_load(source, destination):
    source.preflight()
    destination = Path(destination)
    if not destination.parent.is_dir():
        raise ValueError("Destination directory must exist")
    # Fetch into a staging DB so large mirrors need not retain the whole extraction in memory.
    fd, filename = tempfile.mkstemp(
        prefix=".mirror-", suffix=".db", dir=destination.parent
    )
    os.close(fd)
    try:
        with closing(connect(filename)) as conn, conn:
            for table in source.tables:
                create_table(conn, table)
                insert_rows(conn, table, source.rows(table))
            validate(conn)
        os.replace(filename, destination)
    finally:
        Path(filename).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    kwargs = {
        "user": os.environ["DOTMATICS_USER"],
        "dotmatics_instance": os.environ["DOTMATICS_INSTANCE"],
        "lazy": True,
    }
    if os.environ.get("DOTMATICS_TOKEN"):
        kwargs["token"] = os.environ["DOTMATICS_TOKEN"]
    else:
        kwargs["password"] = os.environ["DOTMATICS_PASSWORD"]
    with Browser(**kwargs) as browser:
        full_load(Source(browser, batch_size=args.batch_size), args.database)


if __name__ == "__main__":
    main()
