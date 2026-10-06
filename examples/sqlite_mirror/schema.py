"""Schema configuration, strict parsers and additive-only SQLite migrations."""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime


class ParsingError(ValueError):
    pass


def text(value):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ParsingError("Expected text")
    return str(value)


def integer(value):
    if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value)):
        raise ParsingError("Expected integer")
    result = int(value)
    if not -(2**63) <= result < 2**63:
        raise ParsingError("Integer exceeds SQLite range")
    return result


def real(value):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ParsingError("Expected real number") from exc
    if isinstance(value, bool) or not math.isfinite(result):
        raise ParsingError("Expected finite real number")
    return result


def boolean(value):
    if (
        value is True
        or value == 1
        or isinstance(value, str)
        and value.lower() in ("true", "yes", "1")
    ):
        return 1
    if (
        value is False
        or value == 0
        or isinstance(value, str)
        and value.lower() in ("false", "no", "0")
    ):
        return 0
    raise ParsingError("Expected explicit boolean")


def concentration(value, unit):
    factors = {"nM": 1, "uM": 1000, "µM": 1000, "μM": 1000, "pM": 0.001, "mM": 1e6}
    if unit not in factors:
        raise ParsingError("Unsupported concentration unit")
    return real(real(value) * factors[unit])


def timestamp(value, *, day_first=None, default_timezone=None):
    """Return UTC ISO text; ambiguous slash dates need an explicit ordering policy."""
    if not isinstance(value, str):
        raise ParsingError("Expected datetime text")
    value = value.strip()
    try:
        if "/" in value:
            if day_first is None:
                raise ParsingError("Slash dates require day_first policy")
            masks = (
                ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y")
                if day_first
                else ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y")
            )
            for mask in masks:
                try:
                    parsed = datetime.strptime(value, mask)
                    break
                except ValueError:
                    continue
            else:
                raise ParsingError("Unsupported datetime format")
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            if default_timezone is None:
                raise ParsingError("Naive datetime requires a timezone policy")
            parsed = parsed.replace(tzinfo=default_timezone)
        return parsed.astimezone(UTC).isoformat()
    except ValueError as exc:
        raise ParsingError(
            "Invalid datetime or missing ordering/timezone policy"
        ) from exc


def identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Invalid SQL identifier")
    return '"' + value + '"'


@dataclass(frozen=True)
class Column:
    source: str
    name: str
    kind: str
    parser: Callable = text
    required: bool = False
    permissive: bool = False
    unit_field: str | None = None

    def parse(self, row):
        value = row.get(self.source)
        if value is None:
            if self.required:
                raise ParsingError(f"Missing required field {self.source}")
            return None
        try:
            if self.unit_field:
                return concentration(value, row.get(self.unit_field))
            return self.parser(value)
        except (ValueError, TypeError) as exc:
            if self.permissive and not self.required:
                return None
            raise ParsingError(f"Invalid field {self.source}") from exc


@dataclass(frozen=True)
class Table:
    name: str
    project: str
    datasource: str
    primary_source: str
    primary: str
    columns: tuple[Column, ...]
    foreign_keys: tuple[tuple[str, str, str], ...] = ()
    audit: str | None = None

    def __post_init__(self):
        identifier(self.name)
        identifier(self.primary)
        names = [c.name for c in self.columns]
        if len(names) != len(set(names)) or self.primary not in names:
            raise ValueError("Duplicate columns or missing primary key")
        for col in self.columns:
            identifier(col.name)
            if col.kind not in ("TEXT", "INTEGER", "REAL"):
                raise ValueError("Unsupported SQLite type")
        primary = next(c for c in self.columns if c.name == self.primary)
        if primary.source != self.primary_source or not primary.required:
            raise ValueError("Primary key must be a required source column")


TABLES = (
    Table(
        "protocols",
        "Notebook",
        "DEMO_PROTOCOL_VW",
        "PROTOCOL_ID",
        "protocol_id",
        (
            Column("PROTOCOL_ID", "protocol_id", "INTEGER", integer, True),
            Column("NAME", "name", "TEXT", text, True),
        ),
    ),
    Table(
        "compounds",
        "Registry",
        "DEMO_COMPOUND_VW",
        "REG_ID",
        "reg_id",
        (
            Column("REG_ID", "reg_id", "INTEGER", integer, True),
            Column("COMPOUND_ID", "compound_id", "TEXT", text, True),
            Column("SMILES", "smiles", "TEXT"),
        ),
        audit="DEMO_COMPOUND_AUDIT_VW",
    ),
    Table(
        "experiments",
        "Notebook",
        "STUDIES_SUMMARY",
        "EXPERIMENT_ID",
        "experiment_id",
        (
            Column("EXPERIMENT_ID", "experiment_id", "INTEGER", integer, True),
            Column("PROTOCOL_ID", "protocol_id", "INTEGER", integer, True),
            Column("NAME", "name", "TEXT"),
            Column("CREATED_DATE", "created_date", "TEXT", timestamp),
        ),
        (("protocol_id", "protocols", "protocol_id"),),
        "DEMO_EXPERIMENT_AUDIT_VW",
    ),
    Table(
        "batches",
        "Registry",
        "DEMO_BATCH_VW",
        "BATCH_PK",
        "batch_pk",
        (
            Column("BATCH_PK", "batch_pk", "INTEGER", integer, True),
            Column("REG_ID", "reg_id", "INTEGER", integer, True),
            Column("ACTIVE", "active", "INTEGER", boolean),
        ),
        (("reg_id", "compounds", "reg_id"),),
        "DEMO_BATCH_AUDIT_VW",
    ),
    Table(
        "plate_results",
        "Assays",
        "DEMO_PLATE_RESULTS_VW",
        "RESULT_ID",
        "result_id",
        (
            Column("RESULT_ID", "result_id", "INTEGER", integer, True),
            Column("EXPERIMENT_ID", "experiment_id", "INTEGER", integer, True),
            Column("VALUE", "value", "REAL", real),
            Column("CONC", "conc_nm", "REAL", real, unit_field="CONC_UNIT"),
        ),
        (("experiment_id", "experiments", "experiment_id"),),
    ),
)


def create_table(conn, table):
    fields = []
    for col in table.columns:
        clause = " PRIMARY KEY" if col.name == table.primary else ""
        if col.required:
            clause += " NOT NULL"
        fields.append(f"{identifier(col.name)} {col.kind}{clause}")
    for col, parent, key in table.foreign_keys:
        fields.append(
            f"FOREIGN KEY ({identifier(col)}) REFERENCES {identifier(parent)}({identifier(key)}) ON DELETE CASCADE"
        )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {identifier(table.name)} ({', '.join(fields)})"
    )
    old = {
        r[1]: r for r in conn.execute(f"PRAGMA table_info({identifier(table.name)})")
    }
    expected = {c.name for c in table.columns}
    if set(old) - expected:
        raise ValueError("Removed/renamed columns require a rebuild")
    for col in table.columns:
        if col.name in old:
            entry = old[col.name]
            if (
                entry[2].upper() != col.kind
                or bool(entry[5]) != (col.name == table.primary)
                or bool(entry[3]) != col.required
            ):
                raise ValueError("Type/key/nullability changes require a rebuild")
        else:
            if col.required or col.name == table.primary:
                raise ValueError(
                    "Only nullable additive columns are supported; required columns need a rebuild"
                )
            conn.execute(
                f"ALTER TABLE {identifier(table.name)} ADD COLUMN {identifier(col.name)} {col.kind}"
            )
    actual_fk = {
        (r[3], r[2], r[4])
        for r in conn.execute(f"PRAGMA foreign_key_list({identifier(table.name)})")
    }
    if actual_fk != set(table.foreign_keys):
        raise ValueError("Foreign-key changes require a rebuild")
    for col, _, _ in table.foreign_keys:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {identifier(table.name + '_' + col + '_idx')} ON {identifier(table.name)} ({identifier(col)})"
        )
