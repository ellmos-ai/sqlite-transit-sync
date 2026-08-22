"""Strict, read-only validation for application-owned SQLite projections.

The verifier deliberately does not publish, copy, merge, migrate, schedule, or
advance state.  An application adapter remains the sole publisher; consumers
can validate a closed projection before opening it for their own read-only use.
"""

from __future__ import annotations

import json
import re
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .core import SyncError

PROJECTION_CONTRACT_SCHEMA = "sqlite-transit-sync.projection-contract.v1"
_BUNDLED_CONTRACTS = Path(__file__).with_name("projection-contracts")
_SAFE_SQL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_SAFE_PARTICIPANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


class ProjectionContractError(SyncError):
    """Raised when a projection contract or database fails closed."""


@dataclass(frozen=True, slots=True)
class ProjectionColumn:
    name: str
    sqlite_type: str
    not_null: bool
    primary_key: int
    constraints: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProjectionTable:
    name: str
    columns: tuple[ProjectionColumn, ...]
    datetime_orderings: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectionContract:
    contract_id: str
    contract_version: str
    publisher_component: str
    metadata_table: str
    record_tables: tuple[str, ...]
    tombstone_table: str
    tables: tuple[ProjectionTable, ...]

    @classmethod
    def from_dict(cls, payload: Any) -> ProjectionContract:
        if not isinstance(payload, dict):
            raise ProjectionContractError("Projection contract must be a JSON object")
        required = {
            "contract_schema",
            "contract_id",
            "contract_version",
            "access",
            "publisher_policy",
            "publisher_component",
            "metadata_table",
            "record_tables",
            "tombstone_table",
            "tables",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProjectionContractError(f"Projection contract is missing keys: {', '.join(missing)}")
        if payload["contract_schema"] != PROJECTION_CONTRACT_SCHEMA:
            raise ProjectionContractError("Unsupported projection contract schema")
        if payload["access"] != "read-only":
            raise ProjectionContractError("Projection contract access must be read-only")
        if payload["publisher_policy"] != "single-canonical-app-adapter":
            raise ProjectionContractError("Projection contract must declare a single canonical app adapter")

        contract_id = _required_text(payload["contract_id"], "contract_id")
        contract_version = _required_text(payload["contract_version"], "contract_version")
        publisher_component = _required_text(payload["publisher_component"], "publisher_component")
        metadata_table = _sql_name(payload["metadata_table"], "metadata_table")
        tombstone_table = _sql_name(payload["tombstone_table"], "tombstone_table")
        raw_record_tables = payload["record_tables"]
        if not isinstance(raw_record_tables, list) or not raw_record_tables:
            raise ProjectionContractError("record_tables must be a non-empty array")
        record_tables = tuple(_sql_name(value, "record table") for value in raw_record_tables)
        if len(set(record_tables)) != len(record_tables):
            raise ProjectionContractError("record_tables contains duplicates")

        raw_tables = payload["tables"]
        if not isinstance(raw_tables, list) or not raw_tables:
            raise ProjectionContractError("tables must be a non-empty array")
        tables: list[ProjectionTable] = []
        for raw_table in raw_tables:
            tables.append(_parse_table(raw_table))
        names = tuple(table.name for table in tables)
        if len(set(names)) != len(names):
            raise ProjectionContractError("Projection contract contains duplicate tables")
        expected_roles = {metadata_table, tombstone_table, *record_tables}
        if set(names) != expected_roles:
            raise ProjectionContractError("Contract tables must exactly match metadata, records, and tombstones")
        if metadata_table in record_tables or tombstone_table in record_tables or metadata_table == tombstone_table:
            raise ProjectionContractError("Projection table roles must not overlap")

        contract = cls(
            contract_id=contract_id,
            contract_version=contract_version,
            publisher_component=publisher_component,
            metadata_table=metadata_table,
            record_tables=record_tables,
            tombstone_table=tombstone_table,
            tables=tuple(tables),
        )
        contract._validate_required_columns()
        return contract

    @classmethod
    def from_file(cls, path_or_name: str | Path) -> ProjectionContract:
        source = projection_contract_path(path_or_name)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectionContractError(f"Invalid projection contract {source}: {error}") from error
        return cls.from_dict(payload)

    def table(self, name: str) -> ProjectionTable:
        for table in self.tables:
            if table.name == name:
                return table
        raise ProjectionContractError(f"Unknown contract table: {name}")

    def _validate_required_columns(self) -> None:
        metadata = {column.name for column in self.table(self.metadata_table).columns}
        required_metadata = {
            "contract_id",
            "contract_version",
            "publisher_component",
            "publisher_instance",
            "generated_at",
            "source_checkpoint",
        }
        if not required_metadata.issubset(metadata):
            raise ProjectionContractError("Metadata table is missing projection protocol columns")
        for table_name in self.record_tables:
            columns = {column.name for column in self.table(table_name).columns}
            if not {"record_ref", "record_version", "source_checkpoint", "publisher_instance"}.issubset(columns):
                raise ProjectionContractError(f"Record table {table_name} is missing protocol columns")
        tombstone_columns = {column.name for column in self.table(self.tombstone_table).columns}
        required_tombstone = {
            "record_type",
            "record_ref",
            "deleted_at",
            "retain_until",
            "record_version",
            "source_checkpoint",
            "publisher_instance",
        }
        if not required_tombstone.issubset(tombstone_columns):
            raise ProjectionContractError("Tombstone table is missing protocol columns")


@dataclass(frozen=True, slots=True)
class ProjectionVerificationReport:
    contract_id: str
    contract_version: str
    publisher_component: str
    publisher_instance: str
    source_checkpoint: int
    generated_at: str
    database_name: str
    row_counts: dict[str, int]
    read_only: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "verified-read-only-projection",
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "publisher_component": self.publisher_component,
            "publisher_instance": self.publisher_instance,
            "source_checkpoint": self.source_checkpoint,
            "generated_at": self.generated_at,
            "database_name": self.database_name,
            "row_counts": dict(self.row_counts),
            "read_only": self.read_only,
        }


def bundled_projection_contracts() -> tuple[str, ...]:
    """Return bundled contract stems without reading an application database."""
    return tuple(sorted(path.stem for path in _BUNDLED_CONTRACTS.glob("*.json")))


def projection_contract_path(path_or_name: str | Path) -> Path:
    """Resolve an explicit path or one bundled contract stem."""
    candidate = Path(path_or_name).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    value = str(path_or_name)
    if Path(value).name != value or "/" in value or "\\" in value:
        raise ProjectionContractError(f"Projection contract does not exist: {path_or_name}")
    bundled = _BUNDLED_CONTRACTS / (value if value.endswith(".json") else f"{value}.json")
    if not bundled.is_file():
        known = ", ".join(bundled_projection_contracts())
        raise ProjectionContractError(f"Unknown bundled projection contract {value!r}; available: {known}")
    return bundled.resolve()


def verify_projection_database(
    database: str | Path,
    contract: ProjectionContract | str | Path,
    *,
    consumer_id: str,
    minimum_offline_seconds: int,
    previous_checkpoint: int | None = None,
) -> ProjectionVerificationReport:
    """Validate one closed projection without changing it or local sync state."""
    selected = contract if isinstance(contract, ProjectionContract) else ProjectionContract.from_file(contract)
    consumer = _participant(consumer_id, "consumer_id")
    if type(minimum_offline_seconds) is not int or minimum_offline_seconds < 0:
        raise ProjectionContractError("minimum_offline_seconds must be a non-negative integer")
    if previous_checkpoint is not None and (type(previous_checkpoint) is not int or previous_checkpoint < 0):
        raise ProjectionContractError("previous_checkpoint must be a non-negative integer")

    path = Path(database).expanduser()
    _assert_closed_regular_database(path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or quick_check[0] != "ok":
            raise ProjectionContractError(f"SQLite quick_check failed: {quick_check}")
        _verify_schema(connection, selected)
        rows_by_table = {
            table.name: connection.execute(f"SELECT * FROM {_quote(table.name)}").fetchall()
            for table in selected.tables
        }
        for table in selected.tables:
            _verify_rows(table, rows_by_table[table.name])

        metadata_rows = rows_by_table[selected.metadata_table]
        if len(metadata_rows) != 1:
            raise ProjectionContractError("Projection metadata table must contain exactly one row")
        metadata = dict(metadata_rows[0])
        expected_metadata = {
            "contract_id": selected.contract_id,
            "contract_version": selected.contract_version,
            "publisher_component": selected.publisher_component,
        }
        for column, expected in expected_metadata.items():
            if metadata[column] != expected:
                raise ProjectionContractError(f"Projection metadata {column} does not match the contract")
        publisher_instance = _participant(metadata["publisher_instance"], "publisher_instance")
        if publisher_instance == consumer:
            raise ProjectionContractError("Loop guard rejected a projection published by this consumer")
        checkpoint = metadata["source_checkpoint"]
        if type(checkpoint) is not int or checkpoint < 0:
            raise ProjectionContractError("source_checkpoint must be a non-negative integer")
        if previous_checkpoint is not None and checkpoint <= previous_checkpoint:
            raise ProjectionContractError("Projection checkpoint is not newer than the consumer checkpoint")

        for table_name in selected.record_tables:
            for row in rows_by_table[table_name]:
                _verify_provenance(row, checkpoint, publisher_instance, table_name)
        tombstones = rows_by_table[selected.tombstone_table]
        _verify_tombstones(
            selected,
            rows_by_table,
            tombstones,
            checkpoint=checkpoint,
            publisher_instance=publisher_instance,
            minimum_offline_seconds=minimum_offline_seconds,
        )
        return ProjectionVerificationReport(
            contract_id=selected.contract_id,
            contract_version=selected.contract_version,
            publisher_component=selected.publisher_component,
            publisher_instance=publisher_instance,
            source_checkpoint=checkpoint,
            generated_at=metadata["generated_at"],
            database_name=path.name,
            row_counts={name: len(rows) for name, rows in rows_by_table.items()},
        )
    except sqlite3.Error as error:
        raise ProjectionContractError(f"Projection database could not be verified: {error}") from error
    finally:
        if connection is not None:
            connection.close()


def _parse_table(raw: Any) -> ProjectionTable:
    if not isinstance(raw, dict):
        raise ProjectionContractError("Every projection table must be an object")
    name = _sql_name(raw.get("name"), "table name")
    raw_columns = raw.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise ProjectionContractError(f"Projection table {name} must define columns")
    columns: list[ProjectionColumn] = []
    for raw_column in raw_columns:
        if not isinstance(raw_column, dict):
            raise ProjectionContractError(f"Invalid column in projection table {name}")
        column_name = _sql_name(raw_column.get("name"), "column name")
        sqlite_type = raw_column.get("type")
        if sqlite_type not in {"TEXT", "INTEGER"}:
            raise ProjectionContractError(f"Unsupported SQLite type for {name}.{column_name}")
        not_null = raw_column.get("not_null")
        primary_key = raw_column.get("primary_key", 0)
        if type(not_null) is not bool or type(primary_key) is not int or primary_key < 0:
            raise ProjectionContractError(f"Invalid schema flags for {name}.{column_name}")
        constraints = raw_column.get("constraints", {})
        if not isinstance(constraints, dict):
            raise ProjectionContractError(f"Invalid constraints for {name}.{column_name}")
        unknown = set(constraints) - {"const", "enum", "pattern", "minimum", "format"}
        if unknown:
            raise ProjectionContractError(f"Unknown constraints for {name}.{column_name}: {sorted(unknown)}")
        if "pattern" in constraints:
            try:
                re.compile(constraints["pattern"])
            except (TypeError, re.error) as error:
                raise ProjectionContractError(f"Invalid pattern for {name}.{column_name}: {error}") from error
        if "enum" in constraints and (
            not isinstance(constraints["enum"], list) or not constraints["enum"]
        ):
            raise ProjectionContractError(f"Invalid enum for {name}.{column_name}")
        if "minimum" in constraints and not isinstance(constraints["minimum"], (int, float)):
            raise ProjectionContractError(f"Invalid minimum for {name}.{column_name}")
        if "format" in constraints and constraints["format"] != "utc-datetime":
            raise ProjectionContractError(f"Unsupported format for {name}.{column_name}")
        columns.append(ProjectionColumn(column_name, sqlite_type, not_null, primary_key, constraints))
    if len({column.name for column in columns}) != len(columns):
        raise ProjectionContractError(f"Projection table {name} contains duplicate columns")
    pk_values = sorted(column.primary_key for column in columns if column.primary_key)
    if pk_values != list(range(1, len(pk_values) + 1)):
        raise ProjectionContractError(f"Projection table {name} has invalid primary-key order")
    raw_orderings = raw.get("datetime_orderings", [])
    if not isinstance(raw_orderings, list):
        raise ProjectionContractError(f"datetime_orderings for {name} must be an array")
    orderings: list[tuple[str, str]] = []
    known_columns = {column.name for column in columns}
    for ordering in raw_orderings:
        if not isinstance(ordering, list) or len(ordering) != 2 or not all(isinstance(value, str) for value in ordering):
            raise ProjectionContractError(f"Invalid datetime ordering in {name}")
        start, end = ordering
        if start not in known_columns or end not in known_columns:
            raise ProjectionContractError(f"Unknown datetime ordering column in {name}")
        orderings.append((start, end))
    return ProjectionTable(name, tuple(columns), tuple(orderings))


def _verify_schema(connection: sqlite3.Connection, contract: ProjectionContract) -> None:
    actual_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    expected_tables = {table.name for table in contract.tables}
    if actual_tables != expected_tables:
        extras = sorted(actual_tables - expected_tables)
        missing = sorted(expected_tables - actual_tables)
        raise ProjectionContractError(f"Projection table allowlist mismatch; extra={extras}, missing={missing}")
    unexpected_objects = connection.execute(
        "SELECT type, name FROM sqlite_schema "
        "WHERE type IN ('view', 'trigger') OR (type = 'index' AND sql IS NOT NULL)"
    ).fetchall()
    if unexpected_objects:
        labels = [f"{row[0]}:{row[1]}" for row in unexpected_objects]
        raise ProjectionContractError(f"Projection schema contains unallowlisted objects: {labels}")
    for table in contract.tables:
        actual = connection.execute(f"PRAGMA table_info({_quote(table.name)})").fetchall()
        if len(actual) != len(table.columns):
            raise ProjectionContractError(f"Projection column allowlist mismatch for {table.name}")
        for row, expected in zip(actual, table.columns, strict=True):
            if (
                row[1] != expected.name
                or str(row[2]).upper() != expected.sqlite_type
                or bool(row[3]) != expected.not_null
                or row[4] is not None
                or int(row[5]) != expected.primary_key
            ):
                raise ProjectionContractError(f"Projection schema mismatch for {table.name}.{expected.name}")


def _verify_rows(table: ProjectionTable, rows: list[sqlite3.Row]) -> None:
    for index, row in enumerate(rows):
        values = dict(row)
        for column in table.columns:
            value = values[column.name]
            if value is None:
                if column.not_null:
                    raise ProjectionContractError(f"NULL in {table.name}.{column.name} row {index}")
                continue
            if column.sqlite_type == "TEXT" and not isinstance(value, str):
                raise ProjectionContractError(f"Non-text value in {table.name}.{column.name} row {index}")
            if column.sqlite_type == "INTEGER" and type(value) is not int:
                raise ProjectionContractError(f"Non-integer value in {table.name}.{column.name} row {index}")
            _verify_constraints(table.name, column, value, index)
        for start_column, end_column in table.datetime_orderings:
            start = _parse_timestamp(values[start_column], f"{table.name}.{start_column}")
            end = _parse_timestamp(values[end_column], f"{table.name}.{end_column}")
            if end < start:
                raise ProjectionContractError(f"Invalid datetime ordering in {table.name} row {index}")


def _verify_constraints(table: str, column: ProjectionColumn, value: Any, index: int) -> None:
    constraints = column.constraints
    if "const" in constraints and value != constraints["const"]:
        raise ProjectionContractError(f"Unexpected value in {table}.{column.name} row {index}")
    if "enum" in constraints:
        allowed = constraints["enum"]
        if not isinstance(allowed, list) or value not in allowed:
            raise ProjectionContractError(f"Value outside enum in {table}.{column.name} row {index}")
    if "pattern" in constraints and re.fullmatch(constraints["pattern"], value) is None:
        raise ProjectionContractError(f"Value outside pattern in {table}.{column.name} row {index}")
    if "minimum" in constraints and value < constraints["minimum"]:
        raise ProjectionContractError(f"Value below minimum in {table}.{column.name} row {index}")
    if constraints.get("format") == "utc-datetime":
        _parse_timestamp(value, f"{table}.{column.name}")


def _verify_provenance(row: sqlite3.Row, checkpoint: int, publisher_instance: str, table: str) -> None:
    if row["source_checkpoint"] != checkpoint:
        raise ProjectionContractError(f"Source checkpoint mismatch in {table}")
    if row["publisher_instance"] != publisher_instance:
        raise ProjectionContractError(f"Publisher provenance mismatch in {table}")


def _verify_tombstones(
    contract: ProjectionContract,
    rows_by_table: dict[str, list[sqlite3.Row]],
    tombstones: list[sqlite3.Row],
    *,
    checkpoint: int,
    publisher_instance: str,
    minimum_offline_seconds: int,
) -> None:
    records = {
        table_name: {row["record_ref"]: row for row in rows_by_table[table_name]}
        for table_name in contract.record_tables
    }
    for row in tombstones:
        _verify_provenance(row, checkpoint, publisher_instance, contract.tombstone_table)
        record_type = row["record_type"]
        if record_type not in records:
            raise ProjectionContractError("Tombstone record_type is not a contracted record table")
        deleted_at = _parse_timestamp(row["deleted_at"], "tombstone.deleted_at")
        retain_until = _parse_timestamp(row["retain_until"], "tombstone.retain_until")
        if (retain_until - deleted_at).total_seconds() < minimum_offline_seconds:
            raise ProjectionContractError("Tombstone retention does not cover the configured offline interval")
        active = records[record_type].get(row["record_ref"])
        if active is not None and active["record_version"] <= row["record_version"]:
            raise ProjectionContractError("Tombstone conflicts with an equal or older active projection row")


def _assert_closed_regular_database(path: Path) -> None:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as error:
        raise ProjectionContractError(f"Projection database is not a readable regular file: {path.name}") from error
    if path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)) or not path.is_file():
        raise ProjectionContractError("Projection database must be a direct regular file")
    existing = [candidate.name for candidate in path.parent.glob(f"{path.name}-*")]
    if existing:
        raise ProjectionContractError(f"Projection database is not closed; sidecars present: {existing}")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ProjectionContractError(f"{label} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProjectionContractError(f"{label} must be an ISO-8601 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ProjectionContractError(f"{label} must use UTC")
    return parsed


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionContractError(f"{label} must be a non-empty string")
    return value


def _participant(value: Any, label: str) -> str:
    text = _required_text(value, label)
    if _SAFE_PARTICIPANT.fullmatch(text) is None:
        raise ProjectionContractError(f"{label} contains unsafe characters")
    return text


def _sql_name(value: Any, label: str) -> str:
    text = _required_text(value, label)
    if _SAFE_SQL_NAME.fullmatch(text) is None or text.startswith("sqlite_"):
        raise ProjectionContractError(f"{label} is not a safe SQLite identifier")
    return text


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
