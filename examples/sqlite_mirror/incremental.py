"""Refresh one overlapping audit window in a single local transaction."""

import argparse
import os
from contextlib import closing
from pathlib import Path

from dotmatics_api import Browser

from .mirror import IncompleteLoad, Source, connect, delete_ids, insert_rows, validate
from .schema import create_table


def refresh(source, database, *, days=1, overlap_days=1):
    if days <= 0 or overlap_days < 0:
        raise ValueError("days must be positive; overlap_days must be nonnegative")
    if not Path(database).is_file():
        raise ValueError("Build the full mirror before incremental refresh")
    source.preflight()
    # All deletes, schema changes and replacement inserts share one rollback boundary.
    with closing(connect(database)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        tables = {table.name: table for table in source.tables}
        pending = {}
        deletions = {}
        changed_experiments = []
        for table in source.tables:
            create_table(conn, table)
            if table.name == "plate_results":
                continue
            if table.audit:
                ids, deleted = source.changes(table, days + overlap_days)
                pending[table.name] = source.rows(table, ids, deleted=deleted)
                returned = {
                    str(row[table.primary_source]) for row in pending[table.name]
                }
                # rows() permits mid-run disappearance only after checking an explicit tombstone.
                deletions[table.name] = deleted | (set(ids) - returned)
                if table.name == "experiments":
                    changed_experiments = sorted(returned)
            else:
                # Protocol metadata is small and has no audit in the fictional contract.
                pending[table.name] = source.rows(table)
                deletions[table.name] = set()
        result_table = tables.get("plate_results")
        result_rows = []
        if result_table:
            for exp in changed_experiments:
                ids = source.ids(
                    result_table, column="EXPERIMENT_ID", operator="equals", value=exp
                )
                rows = source.rows(result_table, ids)
                if any(str(row.get("EXPERIMENT_ID")) != exp for row in rows):
                    raise IncompleteLoad("Child query returned a different experiment")
                result_rows.extend(rows)
            delete_ids(conn, result_table.name, "experiment_id", changed_experiments)
        for table in reversed(source.tables):
            delete_ids(
                conn, table.name, table.primary, deletions.get(table.name, set())
            )
        for table in source.tables:
            insert_rows(
                conn,
                table,
                result_rows if table.name == "plate_results" else pending[table.name],
            )
        validate(conn)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--overlap-days", type=int, default=1)
    args = parser.parse_args()
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
        refresh(
            Source(browser),
            args.database,
            days=args.days,
            overlap_days=args.overlap_days,
        )


if __name__ == "__main__":
    main()
