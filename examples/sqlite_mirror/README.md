# Fictional SQLite mirror

Run the offline demonstration from the repository root after installing the client:

```sh
python -m examples.sqlite_mirror.demo demo.db
```

It builds a full mirror, changes a synthetic experiment, replays an incremental
window and checks rollback after an injected parser failure. No network, cloud
configuration or proprietary dependencies are needed.

## Deployment contract

These views are fictional. Adapt `schema.py` and supply equivalent configured
views on your own deployment; the names are not vendor defaults.

| Project | View | API primary ID | SQLite table |
|---|---|---|---|
| Notebook | DEMO_PROTOCOL_VW | PROTOCOL_ID | protocols |
| Registry | DEMO_COMPOUND_VW | REG_ID | compounds |
| Notebook | STUDIES_SUMMARY | EXPERIMENT_ID | experiments |
| Registry | DEMO_BATCH_VW | BATCH_PK | batches |
| Assays | DEMO_PLATE_RESULTS_VW | RESULT_ID | plate_results |

Each view returns exactly one row per API primary ID. IDs in this schema are
nonnegative numeric keys; display names such as `CMP-000000001` are separate
fields. Every child result is independently queryable by `RESULT_ID`, including
queries filtered by `EXPERIMENT_ID`. The example refuses a many-row parent
response instead of silently treating the parent ID as proof of child coverage.
Table mappings are `Table`/`Column` objects with source field, SQLite field/type,
parser and explicit missing-value policies. Extend mappings in Python rather
than evaluating configuration strings. SQL identifiers are validated and quoted;
all row and delete values are bound parameters.

Experiment and batch foreign keys reference protocols and compounds respectively;
results reference experiments. The table order puts parents first, deletion
order puts children first, and every connection enables foreign-key enforcement.

Three fictional audit views live beside their entity views:
`DEMO_EXPERIMENT_AUDIT_VW`, `DEMO_COMPOUND_AUDIT_VW`, `DEMO_BATCH_AUDIT_VW`.
Each is keyed by its entity's API primary ID and exposes that key field,
`ENTRY_DATE` and explicit `IS_DELETED`. The view must represent the latest state
per entity, preserve deletion tombstones, and support `ENTRY_DATE days N` queries.
Changes/deletions to results must also mark their parent experiment changed.
Protocol metadata is small and refreshed in full; protocol deletion is not
supported incrementally and requires a rebuild. Protocol edits and additions are
upserted. These assumptions must be verified when adapting the example.

## Live use

Configure `DOTMATICS_INSTANCE`, `DOTMATICS_USER` and either `DOTMATICS_PASSWORD`
or `DOTMATICS_TOKEN`, then run:

```sh
python -m examples.sqlite_mirror.mirror mirror.db --batch-size 100
python -m examples.sqlite_mirror.incremental mirror.db --days 1 --overlap-days 1
```

The destination directory must exist. Full load replaces the destination only
after its temporary database validates and closes. Run one writer at a time,
and close readers before replacing the file; atomic pathname replacement does
not update an already-open reader's connection. Do not replace a destination
being actively written in WAL mode. The incremental command operates on an
existing mirror and makes one transaction for the entire window, including schema
changes, deletions and inserts. A failed run rolls back. It holds a write lock
while fetching; adapt transaction scope deliberately for larger deployments.

An explicit empty ID list performs no extraction; `None` requests enumeration.
Enumeration uses deterministic lexical ID ordering. Smaller fetch batches are
tried when rows are omitted; a missing singleton fails unless its audit view
positively confirms deletion. Audit windows overlap and are safe to replay.
Choose their size and source timezone/retention together. An outage longer than
the retained window requires a larger lookback or rebuild.

## Limits and migration

Enumeration rejects duplicate/malformed IDs, counts, short lists and limit
saturation. The default bound is 100,000 IDs including 10,000 slack; larger
enumerations fail with instructions to implement validated stable-key partitions.
This is a small example, not an unbounded production extraction engine.
Counts can under-report, so joint count/ID omissions remain undetectable. The
mirror is an extraction over an interval, not a consistent server-side snapshot.
No helper proves that a source query itself returned every match. An independently
verified source count/key manifest or snapshot/export API is needed for stronger
guarantees. Preflight checks project/view availability, not every server schema
or audit-semantic assumption.

Only nullable additive columns migrate automatically. Named inserts remain safe
when SQLite appends a new column in a different physical order. Renames, type/key,
nullability and relationship changes require a full rebuild. Strict parsers reject
malformed required and optional values; set `permissive=True` only on optional
columns where silently nulling invalid data is an intentional policy. Date fields
default to offset-aware ISO text; custom slash-date policies must supply both
ordering and timezone. Concentration units include nM, uM, µM, μM, pM and mM.

Run the offline suite with:

```sh
python -m pytest examples/sqlite_mirror/tests
```
