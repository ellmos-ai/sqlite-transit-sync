"""Verified snapshot transit and row-level merging for local SQLite databases."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import struct
import tempfile
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

PROTOCOL_VERSION = 1
SNAPSHOT_SUFFIX = ".sqlite-snapshot"
TOMBSTONE_TABLE = "__sqlite_transit_tombstones"
AUTH_PROTOCOL_VERSION = 1
HMAC_ALGORITHM = "HMAC-SHA256"
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_TIMESTAMP_COLUMNS = ("updated_at", "modified_at", "created_at")
_DEFAULT_EXCLUDE_TABLES = ("secrets", "sqlite_sequence")

# Credential trigger patterns live in data, not in code, so detection can be
# tightened over time without a release: see `credential-triggers.json` next to
# this module and the `secret_patterns_file` config key.
#
# `snapshot_exclude_tables` drops a *table* you already know about. This scan
# answers the different question the table rule cannot: is there a credential
# somewhere in free-text content — a note, a log line, a session summary?
_TRIGGER_FILE = Path(__file__).with_name("credential-triggers.json")


@dataclass(frozen=True, slots=True)
class SecretPattern:
    """One credential trigger: label, matcher and optional SQL pre-filter."""

    name: str
    regex: re.Pattern[str]
    prefilter: str | None = None


def load_secret_patterns(path: str | Path | None = None) -> tuple[SecretPattern, ...]:
    """Load a nonempty, typed trigger set; errors never disclose input values."""
    try:
        source = Path(path).expanduser() if path is not None else _TRIGGER_FILE
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, RecursionError):
        raise SyncError("Credential scan configuration error [trigger-file]") from None
    entries = raw.get("patterns") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        raise SyncError("Credential scan configuration error [empty-or-invalid-patterns]")
    patterns: list[SecretPattern] = []
    for index, entry in enumerate(entries):
        if (not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
                or not entry["name"] or not isinstance(entry.get("regex"), str)
                or not entry["regex"]
                or (entry.get("prefilter") is not None and not isinstance(entry["prefilter"], str))):
            raise SyncError(f"Credential scan configuration error [pattern#{index}]")
        try:
            compiled = re.compile(entry["regex"])
        except (re.error, OverflowError, RecursionError):
            raise SyncError(f"Credential scan configuration error [pattern#{index}]") from None
        patterns.append(SecretPattern(entry["name"], compiled, entry.get("prefilter") or None))
    return tuple(patterns)


class SyncError(RuntimeError):
    """Raised when a snapshot or synchronization operation is unsafe."""


def _secret_scan_options(value: Any, label: str) -> None:
    """Validate raw containers before legacy tuple conversion can hide errors."""
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(entry, str) or not entry or "\x00" in entry for entry in value
    ):
        raise SyncError(f"Credential scan configuration error [{label}-entries]")


def _secret_scan_label(value: str, fallback: str, patterns: Sequence[SecretPattern]) -> str:
    """Keep ordinary locations useful without disclosing a secret identifier."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", value) and not any(
        pattern.regex.search(value) for pattern in patterns
    ):
        return value
    return fallback


def _secret_scan_value(value: Any, location: str, patterns: Sequence[SecretPattern], findings: list[str]) -> None:
    """Scan actual SQLite types; opaque bytes have no proven encoding coverage."""
    if value is None:
        return
    if type(value) not in (str, int, float):
        raise SyncError("Credential scan unsupported representation [blob-or-value-type]")
    text = value if isinstance(value, str) else str(value)
    for index, pattern in enumerate(patterns):
        if pattern.regex.search(text):
            label = _secret_scan_label(pattern.name, f"pattern#{index}", patterns)
            finding = f"{location} ({label})"
            if finding not in findings:
                findings.append(finding)
            break


def _secret_scan_rowid(
    connection: sqlite3.Connection, table: str, without_rowid: int,
    columns: Sequence[tuple[Any, ...]], expected_indexes: set[str],
) -> str | None:
    """Prove an IPK alias or choose an unshadowed actual rowid selector."""
    if without_rowid:
        return None
    indexes = connection.execute(f"PRAGMA main.index_list({_quote_identifier(table)})").fetchall()
    seen: set[str] = set()
    primary_indexes = 0
    for index in indexes:
        if (len(index) != 5 or type(index[0]) is not int or index[0] < 0
                or not isinstance(index[1], str) or index[1] in seen
                or type(index[2]) is not int or index[2] not in (0, 1)
                or index[3] not in ("c", "u", "pk")
                or type(index[4]) is not int or index[4] not in (0, 1)):
            raise SyncError("Credential scan inventory error [rowid-index-list]")
        seen.add(index[1])
        if index[3] == "pk":
            if index[2] != 1 or index[4] != 0:
                raise SyncError("Credential scan inventory error [rowid-primary-index]")
            primary_indexes += 1
    if seen != expected_indexes or primary_indexes > 1:
        raise SyncError("Credential scan inventory error [rowid-index-binding]")
    primary_columns = [column for column in columns if column[5] > 0]
    # Exact INTEGER, one ordinary PK column, and no PRIMARY KEY index are
    # engine metadata for the alias. INT and inline INTEGER PRIMARY KEY DESC
    # have a separate PK index, so neither is silently treated as an alias.
    alias = (len(primary_columns) == 1 and primary_columns[0][5] == 1
             and primary_columns[0][2].strip().upper() == "INTEGER"
             and primary_columns[0][6] == 0 and primary_indexes == 0)
    if alias:
        return None  # This same stored value is already scanned as its real column.
    names = {column[1].casefold() for column in columns}
    for selector in ("rowid", "_rowid_", "oid"):
        if selector not in names:
            return selector
    raise SyncError("Credential scan unsupported structure [shadowed-rowid]")


def _fts_parse_external_descriptor(name: str, sql: str | None) -> Fts5Descriptor:
    """Parse and require a strict external-content FTS5 virtual table DDL."""
    if not isinstance(sql, str) or not sql:
        raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
    match = re.fullmatch(
        r"\s*CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(\x22(?:[^\x22]|\x22\x22)+\x22|\x60[^\x60]+\x60|\[[^\]]+\]|[A-Za-z_][A-Za-z_0-9]*)"
        r"\s+USING\s+fts5\s*\((.*)\)\s*;?\s*",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
    try:
        ddl_name = _fts_word(match.group(1))
    except SyncError:
        raise SyncError("Credential scan unsupported structure [virtual-or-shadow]") from None
    if ddl_name != name:
        raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
    cols: list[Fts5Column] = []
    options: dict[str, str] = {}
    try:
        for part in _fts_ddl_parts(sql):
            if "=" in part:
                k, v = part.split("=", 1)
                k, v = k.strip().lower(), v.strip()
                if k not in ("content", "content_rowid", "tokenize", "prefix", "detail", "columnsize") or k in options:
                    raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
                options[k] = v if v.isdigit() else _fts_word(v)
            else:
                flag = bool(re.search(r"\s+UNINDEXED\s*$", part, re.IGNORECASE))
                col_name = re.sub(r"\s+UNINDEXED\s*$", "", part, flags=re.IGNORECASE) if flag else part
                cols.append(Fts5Column(_fts_word(col_name), flag))
        content_table = options.get("content")
        if not content_table:
            raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
        prefix_raw = options.get("prefix", "")
        prefix = tuple(int(tok) for tok in prefix_raw.replace(",", " ").split()) if prefix_raw else ()
        columnsize_raw = options.get("columnsize", "1")
        if not columnsize_raw.isdigit():
            raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
        return Fts5Descriptor(
            name=name,
            columns=tuple(cols),
            content_table=content_table,
            content_rowid=options.get("content_rowid", "rowid"),
            tokenizer=options.get("tokenize", "unicode61"),
            prefix=prefix,
            detail=options.get("detail", "full"),
            columnsize=int(columnsize_raw),
        )
    except (ValueError, SyncError):
        raise SyncError("Credential scan unsupported structure [virtual-or-shadow]") from None


def _validate_external_fts5_for_republica(
    connection: sqlite3.Connection,
    objects: list[tuple[Any, ...]],
    object_names: dict[tuple[str, str], tuple[Any, ...]],
    ordinary_rows: list[tuple[str, str, int, int]],
    virtual_names: list[str],
    shadow_names: set[str],
    ordinary_metadata: dict[str, tuple[int, list[tuple[Any, ...]]]],
    redacted_tables: frozenset[str],
) -> tuple[tuple[Fts5Descriptor, ...], list[tuple[str, tuple[tuple[str, Any], ...]]]]:
    """Prove every virtual/shadow object belongs to a valid external-content FTS5 index."""
    if shadow_names and not virtual_names:
        raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
    ordinary_names = {name for name, _, _, _ in ordinary_rows}
    if ordinary_names & (set(virtual_names) | shadow_names):
        raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
    descriptors: list[Fts5Descriptor] = []
    fts_configs: list[tuple[str, tuple[tuple[str, Any], ...]]] = []
    for vname in virtual_names:
        obj = object_names.get(("table", vname))
        if obj is None or obj[2] != vname:
            raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
        descriptor = _fts_parse_external_descriptor(vname, obj[4])
        content_table = descriptor.content_table
        if (
            content_table is None
            or content_table not in ordinary_metadata
            or content_table.startswith("sqlite_")
            or content_table in redacted_tables
        ):
            raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
        without_rowid, content_cols = ordinary_metadata[content_table]
        declared = {col[1].casefold() for col in content_cols}
        if any(col.name.casefold() not in declared for col in descriptor.columns):
            raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
        rowid_key = descriptor.content_rowid.casefold()
        if rowid_key not in declared:
            if rowid_key not in ("rowid", "_rowid_", "oid") or without_rowid:
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
        descriptors.append(descriptor)

    proto = sqlite3.connect(":memory:")
    try:
        proto.execute("PRAGMA foreign_keys=OFF")
        for name, kind, _, _ in ordinary_rows:
            if kind == "table" and name != "sqlite_sequence":
                ddl = object_names[("table", name)][4]
                if not isinstance(ddl, str) or not ddl:
                    raise SyncError("Credential scan inventory error [schema-object]")
                proto.execute(ddl)
        proto_virtuals: set[str] = set()
        proto_shadows: set[str] = set()
        allowed_config_keys = {
            "automerge", "crisismerge", "deletemerge", "pgsz",
            "rank", "secure-delete", "usermerge", "version",
        }
        for descriptor in descriptors:
            vsql = object_names[("table", descriptor.name)][4]
            before = {o.name for o in _fts_schema(proto)}
            proto.execute(vsql)
            after = {o.name for o in _fts_schema(proto)}
            created = frozenset(after - before)
            if descriptor.name not in created or len(created) < 2:
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
            proto_kinds = {
                row[1]: row[2]
                for row in proto.execute("PRAGMA main.table_list")
                if row[0] == "main"
            }
            if proto_kinds.get(descriptor.name) != "virtual":
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
            for created_name in created:
                if created_name == descriptor.name:
                    continue
                if proto_kinds.get(created_name) != "shadow":
                    raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
                proto_shadows.add(created_name)
            proto_virtuals.add(descriptor.name)
            config_names = [
                n for n in created
                if tuple(r[1] for r in proto.execute(f"PRAGMA main.table_xinfo({_quote_identifier(n)})")) == ("k", "v")
            ]
            if len(config_names) != 1:
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
            config_table = config_names[0]
            if config_table not in shadow_names:
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
            actual_config = tuple(
                connection.execute(f"SELECT k,v FROM main.{_quote_identifier(config_table)} ORDER BY k")
            )
            if not actual_config or any(
                not isinstance(k, str) or k not in allowed_config_keys or type(v) not in (str, int)
                for k, v in actual_config
            ) or "version" not in dict(actual_config):
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
            q_vname = _quote_identifier(descriptor.name)
            for k, v in actual_config:
                if k != "version":
                    proto.execute(f"INSERT INTO {q_vname}({q_vname},rank) VALUES(?,?)", (k, v))
            expected_config = tuple(
                proto.execute(f"SELECT k,v FROM main.{_quote_identifier(config_table)} ORDER BY k")
            )
            if actual_config != expected_config:
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
            fts_configs.append((config_table, actual_config))

        if proto_virtuals != set(virtual_names) or proto_shadows != shadow_names:
            raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
        proto_objects = {
            (o.type, o.name): o for o in _fts_schema(proto)
            if o.name in (proto_virtuals | proto_shadows)
        }
        for technical_name in sorted(proto_virtuals | proto_shadows):
            snap_obj = object_names.get(("table", technical_name))
            proto_obj = proto_objects.get(("table", technical_name))
            if snap_obj is None or proto_obj is None or (snap_obj[0], snap_obj[1], snap_obj[2], snap_obj[4]) != (
                proto_obj.type, proto_obj.name, proto_obj.table_name, proto_obj.sql
            ):
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
            snap_xinfo = connection.execute(f"PRAGMA main.table_xinfo({_quote_identifier(technical_name)})").fetchall()
            proto_xinfo = proto.execute(f"PRAGMA main.table_xinfo({_quote_identifier(technical_name)})").fetchall()
            if snap_xinfo != proto_xinfo:
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
        for obj in objects:
            if obj[0] in ("index", "trigger") and obj[2] in shadow_names:
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
    finally:
        proto.close()
    return tuple(descriptors), fts_configs


def _secret_scan_inventory(
    connection: sqlite3.Connection,
    *,
    allow_external_fts5: bool = False,
    redacted_tables: frozenset[str] = frozenset(),
) -> tuple[
    list[tuple[Any, ...]],
    list[tuple[str, str, tuple[str, ...]]],
    tuple[Fts5Descriptor, ...],
    list[tuple[str, tuple[tuple[str, Any], ...]]],
]:
    """Bind table_list/xinfo to the complete main sqlite_schema inventory."""
    objects = connection.execute(
        "SELECT type,name,tbl_name,rootpage,sql,rowid FROM main.sqlite_schema ORDER BY type,name"
    ).fetchall()
    object_names: dict[tuple[str, str], tuple[Any, ...]] = {}
    for obj in objects:
        if (len(obj) != 6 or obj[0] not in ("table", "view", "index", "trigger")
                or not isinstance(obj[1], str) or not obj[1] or "\x00" in obj[1]
                or not isinstance(obj[2], str) or not obj[2] or "\x00" in obj[2]
                or type(obj[3]) is not int or obj[3] < 0
                or (obj[4] is not None and not isinstance(obj[4], str))
                or type(obj[5]) is not int):
            raise SyncError("Credential scan inventory error [schema-object]")
        key = (obj[0], obj[1])
        if key in object_names:
            raise SyncError("Credential scan inventory error [duplicate-object]")
        object_names[key] = obj
    listed = connection.execute("PRAGMA main.table_list").fetchall()
    if not listed:
        raise SyncError("Credential scan inventory error [table-list-unavailable]")
    inventory: list[tuple[str, str, tuple[str, ...]]] = []
    represented: set[tuple[str, str]] = set()
    rowid_metadata: dict[str, tuple[int, list[tuple[Any, ...]]]] = {}
    ordinary_rows: list[tuple[str, str, int, int]] = []
    virtual_names: list[str] = []
    shadow_names: set[str] = set()
    builtin_seen = False
    for row in listed:
        if (len(row) < 6 or row[0] != "main" or not isinstance(row[1], str)
                or not row[1] or "\x00" in row[1]
                or row[2] not in ("table", "view", "virtual", "shadow")
                or type(row[3]) is not int or row[3] < 0
                or type(row[4]) is not int or row[4] not in (0, 1)
                or type(row[5]) is not int or row[5] not in (0, 1)):
            raise SyncError("Credential scan inventory error [table-list-row]")
        name, kind, count = row[1], row[2], row[3]
        if name == "sqlite_schema":
            if builtin_seen or kind != "table" or count != 5 or row[4:] != (0, 0):
                raise SyncError("Credential scan inventory error [builtin-schema]")
            builtin_seen = True
            continue  # Its declared fields and stored rowids are in objects above.
        key = ("view" if kind == "view" else "table", name)
        if key not in object_names or key in represented:
            raise SyncError("Credential scan inventory error [unbound-table]")
        represented.add(key)
        if kind in ("virtual", "shadow"):
            if not allow_external_fts5:
                # No visible-column exception: transported FTS indices can retain
                # orphaned/stale tokens, including contentless/external-content FTS.
                raise SyncError("Credential scan unsupported structure [virtual-or-shadow]")
            if kind == "virtual":
                virtual_names.append(name)
            else:
                shadow_names.add(name)
            continue
        columns = connection.execute(f"PRAGMA main.table_xinfo({_quote_identifier(name)})").fetchall()
        if len(columns) != count or not columns:
            raise SyncError("Credential scan inventory error [table-xinfo-unavailable]")
        column_names: list[str] = []
        for ordinal, column in enumerate(columns):
            if (len(column) != 7 or column[0] != ordinal
                    or not isinstance(column[1], str) or not column[1] or "\x00" in column[1]
                    or column[1] in column_names
                    or not isinstance(column[2], str)
                    or type(column[3]) is not int or column[3] not in (0, 1)
                    or (column[4] is not None and not isinstance(column[4], str))
                    or type(column[5]) is not int or column[5] < 0
                    or type(column[6]) is not int or column[6] not in (0, 2, 3)):
                raise SyncError("Credential scan inventory error [table-xinfo-column]")
            column_names.append(column[1])
        inventory.append((name, kind, tuple(column_names)))
        rowid_metadata[name] = (row[4], columns)
        ordinary_rows.append((name, kind, count, row[4]))
    required = {key for key in object_names if key[0] in ("table", "view")}
    if not builtin_seen or represented != required:
        raise SyncError("Credential scan inventory error [incomplete-schema]")
    descriptors: tuple[Fts5Descriptor, ...] = ()
    fts_configs: list[tuple[str, tuple[tuple[str, Any], ...]]] = []
    if virtual_names or shadow_names:
        descriptors, fts_configs = _validate_external_fts5_for_republica(
            connection,
            objects,
            object_names,
            ordinary_rows,
            virtual_names,
            shadow_names,
            rowid_metadata,
            redacted_tables,
        )
    table_columns = {name: columns for name, kind, columns in inventory if kind == "table"}
    for obj in objects:
        if obj[0] != "index":
            continue
        if obj[2] not in table_columns:
            raise SyncError("Credential scan inventory error [index-owner]")
        indexed = connection.execute(f"PRAGMA main.index_xinfo({_quote_identifier(obj[1])})").fetchall()
        if not indexed:
            raise SyncError("Credential scan inventory error [index-xinfo-unavailable]")
        for ordinal, column in enumerate(indexed):
            if (len(column) != 6 or column[0] != ordinal or type(column[1]) is not int
                    or type(column[3]) is not int or column[3] not in (0, 1)
                    or not isinstance(column[4], str)
                    or type(column[5]) is not int or column[5] not in (0, 1)):
                raise SyncError("Credential scan inventory error [index-xinfo-column]")
            if column[1] == -2:
                raise SyncError("Credential scan unsupported structure [expression-index]")
            owner_columns = table_columns[obj[2]]
            if (column[1] < -1 or column[1] >= len(owner_columns)
                    or (column[1] == -1 and column[2] is not None)
                    or (column[1] >= 0 and column[2] != owner_columns[column[1]])):
                raise SyncError("Credential scan inventory error [index-column-binding]")
    # A quick_check alone does not verify table/index consistency. Do not
    # acknowledge normal binary index values unless they match scanned rows.
    if connection.execute("PRAGMA main.integrity_check").fetchall() != [("ok",)]:
        raise SyncError("Credential scan inventory error [index-or-database-integrity]")
    scanned_inventory: list[tuple[str, str, tuple[str, ...]]] = []
    for name, kind, column_names in inventory:
        if kind == "table":
            without_rowid, column_info = rowid_metadata[name]
            expected_indexes = {obj[1] for obj in objects if obj[0] == "index" and obj[2] == name}
            selector = _secret_scan_rowid(connection, name, without_rowid, column_info, expected_indexes)
            if selector is not None:
                column_names = (*column_names, selector)
        scanned_inventory.append((name, kind, column_names))
    return objects, scanned_inventory, descriptors, fts_configs


def _safe_identifier(value: str, fallback: str) -> str:
    cleaned = _SAFE_ID.sub("-", value.strip()).strip("-.")
    if not cleaned:
        cleaned = fallback
    if "__" in cleaned:
        cleaned = cleaned.replace("__", "-")
    return cleaned[:80]


def _is_reparse_or_symlink(path: Path) -> bool:
    """Return true for links/reparse points, including dangling targets."""
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False
    except OSError:
        # An unreadable path must not be treated as a safe regular file.
        return True


def _assert_transit_regular_file(path: Path, transit: Path, label: str) -> None:
    """Fail closed unless ``path`` is a direct, regular file in ``transit``."""
    candidate = Path(path)
    root = Path(transit).resolve()
    if ".." in candidate.parts:
        raise SyncError(f"{label} contains a traversal component")
    if _is_reparse_or_symlink(candidate):
        raise SyncError(f"{label} is a symlink or reparse point")
    try:
        if candidate.parent.resolve() != root:
            raise SyncError(f"{label} escapes the transit directory")
        canonical = candidate.resolve(strict=False)
    except OSError as error:
        raise SyncError(f"{label} path cannot be resolved safely") from error
    if canonical.parent != root:
        raise SyncError(f"{label} escapes the transit directory")
    if not candidate.is_file():
        raise SyncError(f"{label} is not a regular file")


def _validated_snapshot_name(value: Any) -> str:
    """Accept only a single relative filename from a transit manifest."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise SyncError("Manifest snapshot name is invalid")
    candidate = Path(value)
    if (
        candidate.is_absolute()
        or candidate.drive
        or candidate.name != value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise SyncError("Manifest snapshot path must be a single relative filename")
    return value


def _utc_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _parse_utc_token(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.strptime(value, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)


def _snapshot_filename(namespace: str, node_id: str, created_at: str) -> str:
    return f"{namespace}__{node_id}__{created_at}{SNAPSHOT_SUFFIX}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _sqlite_artifact_paths(path: Path) -> tuple[Path, ...]:
    sidecars = tuple(sorted(path.parent.glob(f"{path.name}-*")))
    return (path, *sidecars)


def _remove_sqlite_artifacts(path: Path) -> None:
    failures: list[tuple[Path, OSError]] = []
    for candidate in _sqlite_artifact_paths(path):
        try:
            candidate.unlink(missing_ok=True)
        except OSError as error:
            failures.append((candidate, error))
    if failures:
        details = "; ".join(f"{candidate}: {error}" for candidate, error in failures)
        raise SyncError(f"Could not clean temporary SQLite artifacts: {details}")


def _assert_no_sqlite_sidecars(path: Path) -> None:
    leftovers = _sqlite_artifact_paths(path)[1:]
    if leftovers:
        names = ", ".join(candidate.name for candidate in leftovers)
        raise SyncError(f"Unclosed SQLite snapshot has sidecars: {names}")


def _remove_manifest_artifacts(path: Path) -> None:
    candidates = (path, *sorted(path.parent.glob(f".{path.name}.*.tmp")))
    failures: list[tuple[Path, OSError]] = []
    for candidate in candidates:
        try:
            candidate.unlink(missing_ok=True)
        except OSError as error:
            failures.append((candidate, error))
    if failures:
        details = "; ".join(f"{candidate}: {error}" for candidate, error in failures)
        raise SyncError(f"Could not clean snapshot manifest artifacts: {details}")


class SnapshotAuthenticator(Protocol):
    """Optional authentication adapter for canonical snapshot manifests."""

    def sign(self, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return an authentication envelope for a manifest without ``auth``."""
        ...

    def verify(self, manifest: Mapping[str, Any], envelope: Mapping[str, Any]) -> None:
        """Raise ``SyncError`` when the manifest is not authenticated."""
        ...


@dataclass(frozen=True, slots=True)
class HMACKey:
    """One shared key in an application-owned key ring.

    The secret is deliberately an in-memory API value. It is never serialized
    into a manifest, transit file, log or example configuration.
    """

    sender: str
    secret: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sender, str)
            or not self.sender
            or not isinstance(self.secret, bytes)
            or not self.secret
        ):
            raise ValueError("HMAC keys require a sender and non-empty bytes")


def _canonical_auth_payload(
    manifest: Mapping[str, Any], envelope: Mapping[str, Any]
) -> bytes:
    """Serialize exactly the signed manifest and authentication header."""
    signed_manifest = {key: value for key, value in manifest.items() if key != "auth"}
    signed_header = {
        key: envelope[key]
        for key in ("version", "algorithm", "key_id", "sender", "trust_source")
        if key in envelope
    }
    try:
        encoded = json.dumps(
            {"auth": signed_header, "manifest": signed_manifest},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise SyncError("Snapshot authentication payload is not canonical JSON") from error
    return encoded.encode("utf-8")


class HMACSnapshotAuthenticator:
    """Reference authenticator using an application-owned HMAC-SHA256 key ring.

    This is shared-key authentication, not non-repudiating public-key
    signatures. The manifest protocol, sender, key identifier and snapshot
    SHA-256 are all covered by the canonical payload. Keep old keys in the
    verifier key ring during rotation and change only ``active_key_id`` for
    newly published snapshots.
    """

    algorithm = HMAC_ALGORITHM

    def __init__(
        self,
        *,
        keys: Mapping[str, HMACKey],
        active_key_id: str,
        trusted_senders: Iterable[str] | None = None,
        trust_source: str = "application-key-ring",
    ) -> None:
        self._keys = dict(keys)
        if not self._keys or active_key_id not in self._keys:
            raise ValueError("HMAC authenticator requires an active key in the key ring")
        if any(not key_id or not isinstance(key_id, str) for key_id in self._keys):
            raise ValueError("HMAC key identifiers must be non-empty strings")
        if any(not isinstance(key, HMACKey) for key in self._keys.values()):
            raise ValueError("HMAC key ring values must be HMACKey instances")
        if not isinstance(trust_source, str) or not trust_source:
            raise ValueError("HMAC authenticator requires a trust source identifier")
        self.active_key_id = active_key_id
        self.trust_source = trust_source
        self.trusted_senders = (
            frozenset(trusted_senders)
            if trusted_senders is not None
            else frozenset(key.sender for key in self._keys.values())
        )
        if not self.trusted_senders:
            raise ValueError("HMAC authenticator requires at least one trusted sender")

    def sign(self, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        key = self._keys[self.active_key_id]
        if manifest.get("node_id") != key.sender:
            raise SyncError("Snapshot authentication sender does not match manifest")
        envelope: dict[str, Any] = {
            "version": AUTH_PROTOCOL_VERSION,
            "algorithm": self.algorithm,
            "key_id": self.active_key_id,
            "sender": key.sender,
            "trust_source": self.trust_source,
        }
        signature = hmac.new(
            key.secret,
            _canonical_auth_payload(manifest, envelope),
            hashlib.sha256,
        ).hexdigest()
        envelope["signature"] = signature
        return envelope

    def verify(self, manifest: Mapping[str, Any], envelope: Mapping[str, Any]) -> None:
        if not isinstance(envelope, Mapping):
            raise SyncError("Snapshot authentication envelope is invalid")
        required = {
            "version",
            "algorithm",
            "key_id",
            "sender",
            "trust_source",
            "signature",
        }
        if not required.issubset(envelope):
            raise SyncError("Snapshot authentication envelope is incomplete")
        if envelope["version"] != AUTH_PROTOCOL_VERSION:
            raise SyncError("Unsupported snapshot authentication version")
        if envelope["algorithm"] != self.algorithm:
            raise SyncError("Unsupported snapshot authentication algorithm")
        if envelope["trust_source"] != self.trust_source:
            raise SyncError("Snapshot authentication trust source is not trusted")
        key_id = envelope["key_id"]
        sender = envelope["sender"]
        signature = envelope["signature"]
        if not isinstance(key_id, str) or not isinstance(sender, str) or not isinstance(signature, str):
            raise SyncError("Snapshot authentication envelope has invalid fields")
        key = self._keys.get(key_id)
        if key is None:
            raise SyncError(f"Unknown snapshot authentication key: {key_id}")
        if sender not in self.trusted_senders or key.sender != sender:
            raise SyncError("Snapshot authentication sender is not trusted")
        if manifest.get("node_id") != sender:
            raise SyncError("Snapshot authentication sender does not match manifest")
        try:
            supplied = bytes.fromhex(signature)
        except ValueError as error:
            raise SyncError("Snapshot authentication signature is not hexadecimal") from error
        expected = hmac.new(
            key.secret,
            _canonical_auth_payload(manifest, envelope),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied, expected):
            raise SyncError("Snapshot authentication signature mismatch")


def ensure_tombstone_table(connection: sqlite3.Connection) -> None:
    """Create the reference tombstone table explicitly in an application DB."""
    connection.execute(
        f"""CREATE TABLE IF NOT EXISTS {_quote_identifier(TOMBSTONE_TABLE)} (
            table_name TEXT NOT NULL,
            primary_key TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            PRIMARY KEY (table_name, primary_key)
        )"""
    )
    connection.commit()


@dataclass(slots=True)
class SyncConfig:
    """Portable configuration for one node participating in a transit."""

    database: Path
    transit: Path
    state: Path
    node_id: str = field(default_factory=socket.gethostname)
    namespace: str = "default"
    timestamp_columns: tuple[str, ...] = _DEFAULT_TIMESTAMP_COLUMNS
    exclude_tables: tuple[str, ...] = _DEFAULT_EXCLUDE_TABLES
    snapshot_exclude_tables: tuple[str, ...] = ("secrets",)
    scan_snapshot_for_secrets: bool = True
    secret_scan_extra_patterns: tuple[str, ...] = ()
    secret_scan_skip_tables: tuple[str, ...] = ()
    secret_patterns_file: Path | None = None
    # Publish-replica mode only (see replica.py). Unused by push/pull, so an existing
    # configuration keeps working untouched.
    key_file: Path | None = None
    republica_root: Path | None = None
    allow_key_in_synced_folder: bool = False

    def __post_init__(self) -> None:
        self.database = Path(self.database).expanduser().resolve()
        self.transit = Path(self.transit).expanduser().resolve()
        self.state = Path(self.state).expanduser().resolve()
        self.node_id = _safe_identifier(self.node_id, "node")
        self.namespace = _safe_identifier(self.namespace, "default")
        self.timestamp_columns = tuple(self.timestamp_columns)
        self.exclude_tables = tuple(self.exclude_tables)
        self.snapshot_exclude_tables = tuple(self.snapshot_exclude_tables)
        _secret_scan_options(self.secret_scan_extra_patterns, "extra")
        _secret_scan_options(self.secret_scan_skip_tables, "skip")
        self.secret_scan_extra_patterns = tuple(self.secret_scan_extra_patterns)
        self.secret_scan_skip_tables = tuple(self.secret_scan_skip_tables)
        if self.secret_patterns_file is not None:
            self.secret_patterns_file = Path(self.secret_patterns_file).expanduser().resolve()
        # The key path may come from the environment so that a configuration file can
        # be shared or version-controlled without naming a local credential location.
        if self.key_file is None:
            from_env = os.environ.get("SQLITE_TRANSIT_SYNC_KEY_FILE")
            if from_env:
                self.key_file = Path(from_env)
        if self.key_file is not None:
            self.key_file = Path(self.key_file).expanduser().resolve()
        self.republica_root = (
            Path(self.republica_root).expanduser().resolve()
            if self.republica_root is not None
            else Path.home() / ".republica"
        )
        if self.state == self.transit or self.transit in self.state.parents:
            raise ValueError("The sync state must be outside the transit directory")
        # An imported replica holds decrypted foreign data. Inside the transit it would
        # be republished in the clear — the exact outcome the encryption prevents.
        if self.republica_root == self.transit or self.transit in self.republica_root.parents:
            raise ValueError("Replicas must not be stored inside the transit directory")

    @classmethod
    def from_file(cls, path: str | Path) -> SyncConfig:
        config_path = Path(path).expanduser().resolve()
        return cls.from_bytes(config_path.read_bytes(), source_path=config_path)

    @classmethod
    def from_bytes(cls, payload: bytes, *, source_path: str | Path) -> SyncConfig:
        """Parse exact config bytes using paths relative to their source file."""
        config_path = Path(source_path).expanduser().resolve()
        raw = json.loads(payload.decode("utf-8"))
        if type(raw.get("scan_snapshot_for_secrets", True)) is not bool:
            raise SyncError("Credential scan configuration error [enable-flag]")
        _secret_scan_options(raw.get("secret_scan_extra_patterns", ()), "extra")
        _secret_scan_options(raw.get("secret_scan_skip_tables", ()), "skip")
        base = config_path.parent

        def resolve(value: str) -> Path:
            candidate = Path(value).expanduser()
            return candidate if candidate.is_absolute() else base / candidate

        database = resolve(raw["database"])
        transit = resolve(raw["transit"])
        state = resolve(raw.get("state", ".sync-state.json"))
        return cls(
            database=database,
            transit=transit,
            state=state,
            node_id=raw.get("node_id") or socket.gethostname(),
            namespace=raw.get("namespace", "default"),
            timestamp_columns=tuple(raw.get("timestamp_columns", _DEFAULT_TIMESTAMP_COLUMNS)),
            exclude_tables=tuple(raw.get("exclude_tables", _DEFAULT_EXCLUDE_TABLES)),
            snapshot_exclude_tables=tuple(raw.get("snapshot_exclude_tables", ("secrets",))),
            scan_snapshot_for_secrets=bool(raw.get("scan_snapshot_for_secrets", True)),
            secret_scan_extra_patterns=tuple(raw.get("secret_scan_extra_patterns", ())),
            secret_scan_skip_tables=tuple(raw.get("secret_scan_skip_tables", ())),
            secret_patterns_file=(
                resolve(raw["secret_patterns_file"])
                if raw.get("secret_patterns_file")
                else None
            ),
            key_file=resolve(raw["key_file"]) if raw.get("key_file") else None,
            republica_root=resolve(raw["republica_root"]) if raw.get("republica_root") else None,
            allow_key_in_synced_folder=bool(raw.get("allow_key_in_synced_folder", False)),
        )

    def write(self, path: str | Path) -> Path:
        target = Path(path).expanduser().resolve()
        payload = {
            "database": str(self.database),
            "transit": str(self.transit),
            "state": str(self.state),
            "node_id": self.node_id,
            "namespace": self.namespace,
            "timestamp_columns": list(self.timestamp_columns),
            "exclude_tables": list(self.exclude_tables),
            "snapshot_exclude_tables": list(self.snapshot_exclude_tables),
            "scan_snapshot_for_secrets": self.scan_snapshot_for_secrets,
            "secret_scan_extra_patterns": list(self.secret_scan_extra_patterns),
            "secret_scan_skip_tables": list(self.secret_scan_skip_tables),
            "secret_patterns_file": (
                str(self.secret_patterns_file) if self.secret_patterns_file else None
            ),
            "key_file": str(self.key_file) if self.key_file else None,
            "republica_root": str(self.republica_root) if self.republica_root else None,
            "allow_key_in_synced_folder": self.allow_key_in_synced_folder,
        }
        _atomic_json_write(target, payload)
        return target


@dataclass(frozen=True, slots=True)
class Snapshot:
    path: Path
    manifest_path: Path
    node_id: str
    namespace: str
    created_at: str
    sha256: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["path"] = str(self.path)
        value["manifest_path"] = str(self.manifest_path)
        return value


@dataclass(slots=True)
class MergeReport:
    snapshot: str
    source_node: str
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    skipped_tables: list[str] = field(default_factory=list)
    tables: dict[str, dict[str, int]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MergePolicy(Protocol):
    """Interface for application-specific snapshot merge policies."""

    def merge(
        self,
        local: sqlite3.Connection,
        remote: sqlite3.Connection,
        snapshot: Snapshot,
    ) -> MergeReport:
        ...


class TimestampMergePolicy:
    """Last-write-wins per primary key for tables with a timestamp column.

    Tables without a primary key or a configured timestamp column are ignored.
    Deletions are intentionally not inferred. Applications needing tombstones,
    CRDTs, domain validation, or clock-skew handling should supply another policy.
    """

    def __init__(
        self,
        timestamp_columns: Sequence[str] = _DEFAULT_TIMESTAMP_COLUMNS,
        exclude_tables: Sequence[str] = _DEFAULT_EXCLUDE_TABLES,
    ) -> None:
        self.timestamp_columns = tuple(timestamp_columns)
        self.exclude_tables = set(exclude_tables)

    @staticmethod
    def _tables(conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}

    @staticmethod
    def _table_info(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
        return conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()

    @staticmethod
    def _remote_wins(
        remote_value: Any,
        local_value: Any,
        remote_fingerprint: str,
        local_fingerprint: str,
    ) -> bool:
        if remote_value is None:
            return False
        if local_value is None:
            return True
        try:
            if remote_value != local_value:
                return remote_value > local_value
        except TypeError:
            if str(remote_value) != str(local_value):
                return str(remote_value) > str(local_value)
        return remote_fingerprint > local_fingerprint

    def merge(
        self,
        local: sqlite3.Connection,
        remote: sqlite3.Connection,
        snapshot: Snapshot,
    ) -> MergeReport:
        local.row_factory = sqlite3.Row
        remote.row_factory = sqlite3.Row
        report = MergeReport(snapshot=snapshot.path.name, source_node=snapshot.node_id)
        common_tables = sorted(self._tables(local) & self._tables(remote))

        for table in common_tables:
            if table in self.exclude_tables:
                report.skipped_tables.append(table)
                continue
            local_info = self._table_info(local, table)
            remote_info = self._table_info(remote, table)
            local_columns = [row[1] for row in local_info]
            remote_columns = {row[1] for row in remote_info}
            shared = [column for column in local_columns if column in remote_columns]
            primary_keys = [row[1] for row in sorted(local_info, key=lambda row: row[5]) if row[5] > 0]
            timestamp = next((name for name in self.timestamp_columns if name in shared), None)
            if not primary_keys or not timestamp or not all(key in shared for key in primary_keys):
                report.skipped_tables.append(table)
                continue

            table_sql = _quote_identifier(table)
            columns_sql = ", ".join(_quote_identifier(column) for column in shared)
            placeholders = ", ".join("?" for _ in shared)
            where = " AND ".join(f"{_quote_identifier(key)} = ?" for key in primary_keys)
            update_columns = [column for column in shared if column not in primary_keys]
            update_sql = ", ".join(f"{_quote_identifier(column)} = ?" for column in update_columns)
            table_stats = {"inserted": 0, "updated": 0, "unchanged": 0}

            for remote_row in remote.execute(f"SELECT {columns_sql} FROM {table_sql}"):
                key_values = tuple(remote_row[key] for key in primary_keys)
                local_row = local.execute(
                    f"SELECT {columns_sql} FROM {table_sql} WHERE {where}", key_values
                ).fetchone()
                if local_row is None:
                    local.execute(
                        f"INSERT INTO {table_sql} ({columns_sql}) VALUES ({placeholders})",
                        tuple(remote_row[column] for column in shared),
                    )
                    table_stats["inserted"] += 1
                else:
                    remote_fingerprint = json.dumps(
                        [remote_row[column] for column in shared],
                        ensure_ascii=False,
                        default=str,
                        separators=(",", ":"),
                    )
                    local_fingerprint = json.dumps(
                        [local_row[column] for column in shared],
                        ensure_ascii=False,
                        default=str,
                        separators=(",", ":"),
                    )
                if local_row is not None and self._remote_wins(
                    remote_row[timestamp],
                    local_row[timestamp],
                    remote_fingerprint,
                    local_fingerprint,
                ):
                    if update_columns:
                        local.execute(
                            f"UPDATE {table_sql} SET {update_sql} WHERE {where}",
                            tuple(remote_row[column] for column in update_columns) + key_values,
                        )
                    table_stats["updated"] += 1
                elif local_row is not None:
                    table_stats["unchanged"] += 1

            report.tables[table] = table_stats
            report.inserted += table_stats["inserted"]
            report.updated += table_stats["updated"]
            report.unchanged += table_stats["unchanged"]

        return report


class TombstoneMergePolicy:
    """Reference merge policy for an explicit tombstone table.

    Applications create :data:`TOMBSTONE_TABLE` with
    :func:`ensure_tombstone_table` and retain one row per deleted primary key.
    ``deleted_at`` is the tombstone version. A tombstone wins ties and older
    rows; a later row timestamp may deliberately resurrect the key. The policy
    never prunes tombstones, so retention must cover the application's maximum
    offline interval.
    """

    def __init__(
        self,
        timestamp_columns: Sequence[str] = _DEFAULT_TIMESTAMP_COLUMNS,
        exclude_tables: Sequence[str] = _DEFAULT_EXCLUDE_TABLES,
        tombstone_table: str = TOMBSTONE_TABLE,
    ) -> None:
        self.timestamp_columns = tuple(timestamp_columns)
        self.exclude_tables = set(exclude_tables)
        self.tombstone_table = tombstone_table

    @staticmethod
    def _tables(conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}

    @staticmethod
    def _table_info(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
        return conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()

    @staticmethod
    def _canonical_key(values: Sequence[Any]) -> str:
        try:
            return json.dumps(
                list(values),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise SyncError("Tombstone primary key is not canonical JSON") from error

    @staticmethod
    def _at_least(candidate: Any, current: Any) -> bool:
        if current is None:
            return True
        if candidate is None:
            return False
        try:
            return candidate >= current
        except TypeError:
            return str(candidate) >= str(current)

    def _load_tombstones(self, connection: sqlite3.Connection) -> dict[tuple[str, str], str]:
        if self.tombstone_table not in self._tables(connection):
            return {}
        table_sql = _quote_identifier(self.tombstone_table)
        try:
            rows = connection.execute(
                f"SELECT table_name, primary_key, deleted_at FROM {table_sql}"
            ).fetchall()
        except sqlite3.Error as error:
            raise SyncError("Tombstone table has an incompatible schema") from error
        result: dict[tuple[str, str], str] = {}
        for table_name, primary_key, deleted_at in rows:
            if (
                not isinstance(table_name, str)
                or not table_name
                or table_name.startswith("sqlite_")
                or not isinstance(primary_key, str)
                or not isinstance(deleted_at, str)
                or not deleted_at
            ):
                raise SyncError("Tombstone row has invalid table, key or version")
            try:
                decoded = json.loads(primary_key)
            except json.JSONDecodeError as error:
                raise SyncError("Tombstone primary key is not valid JSON") from error
            if not isinstance(decoded, list) or self._canonical_key(decoded) != primary_key:
                raise SyncError("Tombstone primary key is not canonical JSON")
            key = (table_name, primary_key)
            current = result.get(key)
            if current is None or self._at_least(deleted_at, current):
                result[key] = deleted_at
        return result

    @staticmethod
    def _decode_key(primary_key: str, primary_keys: Sequence[str]) -> tuple[Any, ...]:
        try:
            values = json.loads(primary_key)
        except json.JSONDecodeError as error:
            raise SyncError("Tombstone primary key is not valid JSON") from error
        if not isinstance(values, list) or len(values) != len(primary_keys):
            raise SyncError("Tombstone primary key does not match the target schema")
        return tuple(values)

    def _semantics(
        self,
        local: sqlite3.Connection,
        remote: sqlite3.Connection,
        table: str,
    ) -> tuple[list[str], str | None, list[str]]:
        local_info = self._table_info(local, table)
        remote_info = self._table_info(remote, table)
        local_columns = [row[1] for row in local_info]
        remote_columns = {row[1] for row in remote_info}
        shared = [column for column in local_columns if column in remote_columns]
        primary_keys = [
            row[1] for row in sorted(local_info, key=lambda row: row[5]) if row[5] > 0
        ]
        timestamp = next((name for name in self.timestamp_columns if name in shared), None)
        return primary_keys, timestamp, shared

    def merge(
        self,
        local: sqlite3.Connection,
        remote: sqlite3.Connection,
        snapshot: Snapshot,
    ) -> MergeReport:
        local.row_factory = sqlite3.Row
        remote.row_factory = sqlite3.Row
        report = MergeReport(snapshot=snapshot.path.name, source_node=snapshot.node_id)
        local_tables = self._tables(local)
        remote_tables = self._tables(remote)
        if self.tombstone_table in remote_tables and self.tombstone_table not in local_tables:
            raise SyncError(
                f"Tombstone policy requires {self.tombstone_table!r} in the local schema"
            )

        local_tombstones = self._load_tombstones(local)
        remote_tombstones = self._load_tombstones(remote)
        merged_tombstones = dict(local_tombstones)
        if self.tombstone_table in local_tables or self.tombstone_table in remote_tables:
            report.skipped_tables.append(self.tombstone_table)
        if self.tombstone_table in remote_tables:
            table_sql = _quote_identifier(self.tombstone_table)
            for (table_name, primary_key), deleted_at in remote_tombstones.items():
                current = merged_tombstones.get((table_name, primary_key))
                if current is None:
                    local.execute(
                        f"INSERT INTO {table_sql} (table_name, primary_key, deleted_at) VALUES (?, ?, ?)",
                        (table_name, primary_key, deleted_at),
                    )
                    merged_tombstones[(table_name, primary_key)] = deleted_at
                elif self._at_least(deleted_at, current) and deleted_at != current:
                    local.execute(
                        f"UPDATE {table_sql} SET deleted_at = ? WHERE table_name = ? AND primary_key = ?",
                        (deleted_at, table_name, primary_key),
                    )
                    merged_tombstones[(table_name, primary_key)] = deleted_at

        for (table_name, primary_key), deleted_at in merged_tombstones.items():
            if table_name not in local_tables or table_name in self.exclude_tables:
                continue
            if table_name == self.tombstone_table:
                continue
            if table_name in remote_tables:
                primary_keys, timestamp, _shared = self._semantics(
                    local, remote, table_name
                )
            else:
                primary_keys, timestamp, _shared = [], None, []
            if not primary_keys or not timestamp:
                continue
            key_values = self._decode_key(primary_key, primary_keys)
            where = " AND ".join(f"{_quote_identifier(key)} = ?" for key in primary_keys)
            table_sql = _quote_identifier(table_name)
            local_row = local.execute(
                f"SELECT {_quote_identifier(timestamp)} FROM {table_sql} WHERE {where}",
                key_values,
            ).fetchone()
            if local_row is not None and self._at_least(deleted_at, local_row[timestamp]):
                local.execute(f"DELETE FROM {table_sql} WHERE {where}", key_values)
                report.deleted += 1

        common_tables = sorted((local_tables & remote_tables) - {self.tombstone_table})
        for table in common_tables:
            if table in self.exclude_tables:
                report.skipped_tables.append(table)
                continue
            primary_keys, timestamp, shared = self._semantics(local, remote, table)
            if not primary_keys or not timestamp or not all(key in shared for key in primary_keys):
                report.skipped_tables.append(table)
                continue
            table_sql = _quote_identifier(table)
            columns_sql = ", ".join(_quote_identifier(column) for column in shared)
            placeholders = ", ".join("?" for _ in shared)
            where = " AND ".join(f"{_quote_identifier(key)} = ?" for key in primary_keys)
            update_columns = [column for column in shared if column not in primary_keys]
            update_sql = ", ".join(
                f"{_quote_identifier(column)} = ?" for column in update_columns
            )
            table_stats = {"inserted": 0, "updated": 0, "unchanged": 0}
            for remote_row in remote.execute(f"SELECT {columns_sql} FROM {table_sql}"):
                key_values = tuple(remote_row[key] for key in primary_keys)
                key_json = self._canonical_key(key_values)
                tombstone = merged_tombstones.get((table, key_json))
                if tombstone is not None and self._at_least(
                    tombstone, remote_row[timestamp]
                ):
                    table_stats["unchanged"] += 1
                    continue
                local_row = local.execute(
                    f"SELECT {columns_sql} FROM {table_sql} WHERE {where}", key_values
                ).fetchone()
                if local_row is None:
                    local.execute(
                        f"INSERT INTO {table_sql} ({columns_sql}) VALUES ({placeholders})",
                        tuple(remote_row[column] for column in shared),
                    )
                    table_stats["inserted"] += 1
                    continue
                remote_fingerprint = json.dumps(
                    [remote_row[column] for column in shared],
                    ensure_ascii=False,
                    default=str,
                    separators=(",", ":"),
                )
                local_fingerprint = json.dumps(
                    [local_row[column] for column in shared],
                    ensure_ascii=False,
                    default=str,
                    separators=(",", ":"),
                )
                if TimestampMergePolicy._remote_wins(
                    remote_row[timestamp],
                    local_row[timestamp],
                    remote_fingerprint,
                    local_fingerprint,
                ):
                    if update_columns:
                        local.execute(
                            f"UPDATE {table_sql} SET {update_sql} WHERE {where}",
                            tuple(remote_row[column] for column in update_columns) + key_values,
                        )
                    table_stats["updated"] += 1
                else:
                    table_stats["unchanged"] += 1
            report.tables[table] = table_stats
            report.inserted += table_stats["inserted"]
            report.updated += table_stats["updated"]
            report.unchanged += table_stats["unchanged"]
        return report



@dataclass(frozen=True)
class _PublicationPaths:
    """Capture one publication's local paths; configuration is otherwise mutable."""

    database: Path
    transit: Path
    state: Path
    node_id: str
    namespace: str

    @classmethod
    def capture(cls, config: SyncConfig) -> _PublicationPaths:
        paths = cls(
            *(Path(getattr(config, key)).expanduser().resolve() for key in ("database", "transit", "state")),
            config.node_id, config.namespace,
        )
        if paths.state == paths.transit or paths.transit in paths.state.parents:
            raise SyncError("The sync state must remain outside the transit directory")
        if paths.database == paths.transit or paths.transit in paths.database.parents:
            raise SyncError("The live database must remain outside the transit directory")
        if (paths.node_id != _safe_identifier(paths.node_id, "node")
                or paths.namespace != _safe_identifier(paths.namespace, "default")):
            raise SyncError("Publication identity changed to an unsafe value")
        return paths

    def check(self, config: SyncConfig) -> None:
        if self.capture(config) != self:
            raise SyncError("Publication paths or identity changed during preparation")

    @contextmanager
    def workspace(self) -> Iterator[Path]:
        # TEMP/TMP may name the transport itself. Use the resolved local-state
        # parent instead, and never promise isolation from other sync roots or
        # processes running as the same OS user.
        self.state.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".sqlite-transit-stage-", dir=self.state.parent) as name:
            stage = Path(name).resolve()
            if stage == self.transit or self.transit in stage.parents:
                raise SyncError("Private staging must be outside the transit directory")
            yield stage
        # TemporaryDirectory cleanup errors deliberately propagate. A leftover
        # private plaintext artifact must not be reported as successful cleanup.


def _assert_publication_target(path: Path) -> None:
    manifest = path.with_suffix(path.suffix + ".json")
    if any(candidate.exists() or _is_reparse_or_symlink(candidate) for candidate in (path, manifest)):
        raise SyncError("Publication target already exists")
    _assert_no_sqlite_sidecars(path)


def _publish_prepared_file(source: Path, target: Path, digest: str, size: int) -> None:
    """Copy only validated/ciphertext bytes into an owned target-filesystem temp."""
    if target.parent.resolve() != target.parent:
        raise SyncError("Publication directory was redirected")
    _assert_publication_target(target)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".partial", dir=target.parent)
    temporary = Path(name)
    renamed = False
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, out)
            out.flush()
            os.fsync(out.fileno())
        if temporary.stat().st_size != size or _sha256(temporary) != digest:
            raise SyncError("Prepared publication copy failed integrity verification")
        if target.parent.resolve() != target.parent:
            raise SyncError("Publication directory was redirected")
        _assert_publication_target(target)
        os.replace(temporary, target)
        renamed = True
    finally:
        if not renamed:
            temporary.unlink(missing_ok=True)


class TransitSync:
    """Coordinates verified snapshots between independent local SQLite writers."""

    def __init__(
        self,
        config: SyncConfig,
        policy: MergePolicy | None = None,
        authenticator: SnapshotAuthenticator | None = None,
        *,
        fts_contract: FtsSnapshotContract | None = None,
        fts_limits: FtsReceiveLimits | None = None,
        fts_merge_contract: FtsMergeContract | None = None,
    ) -> None:
        if fts_contract is None and (fts_limits is not None or fts_merge_contract is not None):
            raise ValueError("FTS options require an explicit typed contract")
        if fts_contract is not None:
            if type(fts_contract) is not FtsSnapshotContract:
                raise ValueError("Typed FTS contract required")
            if fts_limits is not None and type(fts_limits) is not FtsReceiveLimits:
                raise ValueError("Typed FTS receive limits required")
            if fts_merge_contract is not None and (type(fts_merge_contract) is not FtsMergeContract or fts_merge_contract.contract_id != fts_contract.contract_id):
                raise ValueError("Typed matching FTS merge contract required")
            self._fts_limits = fts_limits or FtsReceiveLimits()
            self._fts_merge_contract = fts_merge_contract
            _fts_initialize(self, config, policy, authenticator, fts_contract)
            return
        self._fts_contract = fts_contract
        self.config = config
        self.policy = policy or TimestampMergePolicy(
            timestamp_columns=config.timestamp_columns,
            exclude_tables=config.exclude_tables,
        )
        self.authenticator = authenticator
        self.config.transit.mkdir(parents=True, exist_ok=True)
        self.config.state.parent.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict[str, Any]:
        if not self.config.state.exists():
            return {"protocol": PROTOCOL_VERSION, "last_pulled": {}}
        try:
            state = json.loads(self.config.state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SyncError(f"Invalid sync state: {self.config.state}: {error}") from error
        state.setdefault("last_pulled", {})
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        state["protocol"] = PROTOCOL_VERSION
        _atomic_json_write(self.config.state, state)

    def _snapshot_name(self, created_at: str) -> str:
        return _snapshot_filename(
            self.config.namespace,
            self.config.node_id,
            created_at,
        )

    def _redact_snapshot(self, path: Path) -> list[str]:
        if not self.config.snapshot_exclude_tables:
            return []
        connection = sqlite3.connect(str(path))
        redacted: list[str] = []
        try:
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table in self.config.snapshot_exclude_tables:
                if table in existing:
                    connection.execute(f"DELETE FROM {_quote_identifier(table)}")
                    redacted.append(table)
            connection.commit()
            if redacted:
                connection.execute("VACUUM")
        finally:
            connection.close()
        return redacted

    @staticmethod
    def _close_snapshot(path: Path) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(path))
            result = connection.execute("PRAGMA journal_mode=DELETE").fetchone()
        except sqlite3.Error as error:
            raise SyncError(f"Could not close SQLite snapshot {path}: {error}") from error
        finally:
            if connection is not None:
                connection.close()
        if not result or str(result[0]).lower() != "delete":
            raise SyncError(f"Could not switch SQLite snapshot to DELETE journal mode: {path}")
        _assert_no_sqlite_sidecars(path)

    def _scan_snapshot_for_secrets(
        self,
        path: Path,
        *,
        allow_external_fts5: bool = False,
    ) -> list[str]:
        """Scan the closed private snapshot; unsupported coverage aborts publication.

        Explicit disable/skip remains a legacy bypass, never a full-coverage
        credential acknowledgement. No regex SQL prefilter or lossy decoding.
        """
        if type(self.config.scan_snapshot_for_secrets) is not bool:
            raise SyncError("Credential scan configuration error [enable-flag]")
        if not self.config.scan_snapshot_for_secrets:
            return []
        patterns = list(load_secret_patterns(self.config.secret_patterns_file))
        extras = self.config.secret_scan_extra_patterns
        skips = self.config.secret_scan_skip_tables
        if not isinstance(extras, (tuple, list)) or not isinstance(skips, (tuple, list)):
            raise SyncError("Credential scan configuration error [extra-or-skip-types]")
        if any(not isinstance(value, str) or not value or "\x00" in value for value in skips):
            raise SyncError("Credential scan configuration error [skip-entry]")
        for index, expr in enumerate(extras):
            if not isinstance(expr, str) or not expr:
                raise SyncError(f"Credential scan configuration error [extra#{index}]")
            try:
                patterns.append(SecretPattern(f"custom[{index}]", re.compile(expr)))
            except (re.error, OverflowError, RecursionError):
                raise SyncError(f"Credential scan configuration error [extra#{index}]") from None
        if not patterns:
            raise SyncError("Credential scan configuration error [empty-patterns]")
        skip = set(skips)
        findings: list[str] = []
        descriptors: tuple[Fts5Descriptor, ...] = ()
        fts_configs: list[tuple[str, tuple[tuple[str, Any], ...]]] = []
        connection: sqlite3.Connection | None = None
        try:
            # immutable applies only to this closed private copy, after confirming
            # it has no sidecars. It never opens a live application connection.
            try:
                _assert_no_sqlite_sidecars(path)
            except SyncError:
                raise SyncError("Credential scan failed [snapshot-sidecars]") from None
            connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
            connection.execute("PRAGMA query_only=ON")
            objects, inventory, descriptors, fts_configs = _secret_scan_inventory(
                connection,
                allow_external_fts5=allow_external_fts5,
                redacted_tables=frozenset(self.config.snapshot_exclude_tables),
            )
            for index, obj in enumerate(objects):
                for field_index, value in enumerate(obj):
                    _secret_scan_value(value, f"schema#{index}.field#{field_index}", patterns, findings)
            for config_table, config_rows in fts_configs:
                table_label = _secret_scan_label(config_table, "fts_config", patterns)
                for key, value in config_rows:
                    _secret_scan_value(key, f"{table_label}.k", patterns, findings)
                    _secret_scan_value(value, f"{table_label}.v", patterns, findings)
            for table_index, (table, kind, columns) in enumerate(inventory):
                if kind == "view" or table in skip:
                    continue  # View DDL is scanned; arbitrary view SQL is not executed.
                table_label = _secret_scan_label(table, f"table#{table_index}", patterns)
                for column_index, column in enumerate(columns):
                    column_label = _secret_scan_label(column, f"column#{column_index}", patterns)
                    location = f"{table_label}.{column_label}"
                    cursor = connection.execute(
                        f"SELECT {_quote_identifier(column)} FROM main.{_quote_identifier(table)}"
                    )
                    for (value,) in cursor:
                        _secret_scan_value(value, location, patterns, findings)
        except SyncError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, UnicodeError, RecursionError):
            raise SyncError("Credential scan failed [snapshot-query-or-introspection]") from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    raise SyncError("Credential scan failed [snapshot-close]") from None
        if descriptors and not findings:
            before_hash = _sha256(path)
            verify_conn: sqlite3.Connection | None = None
            try:
                verify_conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True)
                verify_conn.execute("BEGIN IMMEDIATE")
                _fts_integrity(verify_conn, descriptors)
                verify_conn.rollback()
            except sqlite3.Error:
                raise SyncError("Credential scan unsupported structure [fts-integrity]") from None
            finally:
                if verify_conn is not None:
                    try:
                        verify_conn.close()
                    except sqlite3.Error:
                        raise SyncError("Credential scan failed [snapshot-close]") from None
            _assert_no_sqlite_sidecars(path)
            if _sha256(path) != before_hash:
                raise SyncError("Credential scan failed [snapshot-integrity-mutation]")
        return findings

    @staticmethod
    def _quick_check(path: Path) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            result = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as error:
            raise SyncError(f"SQLite verification failed for {path}: {error}") from error
        finally:
            if connection is not None:
                connection.close()
        if not result or result[0] != "ok":
            raise SyncError(f"SQLite quick_check failed for {path}: {result}")

    def _backup_to(self, target: Path, *, database: Path | None = None) -> None:
        source: sqlite3.Connection | None = None
        destination: sqlite3.Connection | None = None
        try:
            source = sqlite3.connect(str(database if database is not None else self.config.database))
            destination = sqlite3.connect(str(target))
            with destination:
                source.backup(destination)
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()

    def push(self) -> Snapshot:
        if self._fts_contract is not None:
            return _fts_push(self)
        paths = _PublicationPaths.capture(self.config)
        if not paths.database.is_file():
            raise SyncError(f"Live database not found: {paths.database}")
        created_at = _utc_token()
        final_path = paths.transit / _snapshot_filename(paths.namespace, paths.node_id, created_at)
        manifest_path = final_path.with_suffix(final_path.suffix + ".json")
        _assert_publication_target(final_path)
        published_snapshot = False
        manifest_attempted = False
        try:
            with paths.workspace() as staging:
                snapshot_db = staging / "snapshot.db"
                self._backup_to(snapshot_db, database=paths.database)
                self._close_snapshot(snapshot_db)
                redacted_tables = self._redact_snapshot(snapshot_db)
                leaks = self._scan_snapshot_for_secrets(snapshot_db)
                if leaks:
                    raise SyncError(
                        "Snapshot publication aborted: credential-looking values remain in "
                        + ", ".join(leaks)
                        + ". Remove them from the source database, add the table to "
                        "snapshot_exclude_tables, or disable scan_snapshot_for_secrets if "
                        "this is a false positive. The value itself is not shown on purpose."
                    )
                self._quick_check(snapshot_db)
                _assert_no_sqlite_sidecars(snapshot_db)
                digest = _sha256(snapshot_db)
                size = snapshot_db.stat().st_size
                manifest = {
                    "protocol": PROTOCOL_VERSION,
                    "namespace": paths.namespace,
                    "node_id": paths.node_id,
                    "created_at": created_at,
                    "snapshot": final_path.name,
                    "sha256": digest,
                    "size": size,
                    "redacted_tables": redacted_tables,
                }
                if self.authenticator is not None:
                    authentication = self.authenticator.sign(manifest)
                    if not isinstance(authentication, Mapping):
                        raise SyncError("Snapshot authenticator returned an invalid envelope")
                    manifest["auth"] = dict(authentication)
                paths.check(self.config)
                _publish_prepared_file(snapshot_db, final_path, digest, size)
                published_snapshot = True
                paths.check(self.config)
                manifest_attempted = True
                _atomic_json_write(manifest_path, manifest)
                paths.check(self.config)
        except Exception as error:
            try:
                if manifest_attempted:
                    manifest_path.unlink(missing_ok=True)
                if published_snapshot:
                    final_path.unlink(missing_ok=True)
            except (OSError, SyncError) as cleanup_error:
                raise cleanup_error from error
            raise
        return Snapshot(
            path=final_path,
            manifest_path=manifest_path,
            node_id=paths.node_id,
            namespace=paths.namespace,
            created_at=created_at,
            sha256=digest,
            size=size,
        )

    def _read_snapshot(self, manifest_path: Path, verify: bool = True) -> Snapshot:
        if self._fts_contract is not None:
            typed = _fts_read_snapshot(self, manifest_path, verify)
            if typed is not None:
                return typed
        _assert_transit_regular_file(manifest_path, self.config.transit, "Manifest")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SyncError(f"Invalid manifest {manifest_path}: {error}") from error
        if not isinstance(manifest, dict):
            raise SyncError(f"Invalid manifest object: {manifest_path}")
        required = {"protocol", "namespace", "node_id", "created_at", "snapshot", "sha256", "size"}
        if not required.issubset(manifest):
            raise SyncError(f"Incomplete manifest: {manifest_path}")
        if type(manifest["protocol"]) is not int or manifest["protocol"] != PROTOCOL_VERSION:
            raise SyncError(f"Unsupported protocol in {manifest_path}")
        if manifest["namespace"] != self.config.namespace:
            raise SyncError(f"Wrong namespace in {manifest_path}")
        if self.authenticator is not None:
            authentication = manifest.get("auth")
            if not isinstance(authentication, Mapping):
                raise SyncError("Snapshot authentication is required for this reader")
            try:
                self.authenticator.verify(manifest, authentication)
            except SyncError:
                raise
            except Exception as error:
                raise SyncError("Snapshot authentication failed") from error
        if not all(
            isinstance(manifest[key], str)
            for key in ("namespace", "node_id", "created_at", "snapshot", "sha256")
        ):
            raise SyncError(f"Invalid manifest value types: {manifest_path}")
        node_id = _safe_identifier(manifest["node_id"], "node")
        if node_id != manifest["node_id"]:
            raise SyncError(f"Unsafe node id in {manifest_path}")
        try:
            _parse_utc_token(manifest["created_at"])
        except ValueError as error:
            raise SyncError(
                f"Invalid snapshot timestamp in {manifest_path}: {manifest['created_at']}"
            ) from error
        expected_name = _snapshot_filename(
            manifest["namespace"],
            node_id,
            manifest["created_at"],
        )
        if manifest["snapshot"] != expected_name or manifest_path.name != f"{expected_name}.json":
            raise SyncError(f"Manifest and snapshot identity do not match: {manifest_path}")
        if not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]):
            raise SyncError(f"Invalid SHA-256 in {manifest_path}")
        if type(manifest["size"]) is not int or manifest["size"] < 0:
            raise SyncError(f"Invalid snapshot size in {manifest_path}")
        if manifest_path.resolve().parent != self.config.transit.resolve():
            raise SyncError(f"Manifest escapes transit directory: {manifest_path}")
        snapshot_path = manifest_path.parent / expected_name
        if snapshot_path.parent.resolve() != self.config.transit.resolve():
            raise SyncError(f"Snapshot escapes transit directory: {snapshot_path}")
        _assert_transit_regular_file(snapshot_path, self.config.transit, "Snapshot")
        snapshot = Snapshot(
            path=snapshot_path,
            manifest_path=manifest_path,
            node_id=node_id,
            namespace=manifest["namespace"],
            created_at=manifest["created_at"],
            sha256=manifest["sha256"],
            size=int(manifest["size"]),
        )
        if verify:
            if not snapshot.path.is_file():
                raise SyncError(f"Snapshot missing: {snapshot.path}")
            if snapshot.path.stat().st_size != snapshot.size or _sha256(snapshot.path) != snapshot.sha256:
                raise SyncError(f"Snapshot checksum mismatch: {snapshot.path}")
            self._quick_check(snapshot.path)
        return snapshot

    def retention_inventory(self) -> list[Any]:
        """Return a fail-closed inventory for the opt-in retention policy.

        Every transit item is represented.  Only a manifest that belongs to
        this configured namespace and passes the normal snapshot verifier can
        become eligible for deletion; foreign, incomplete, unknown and
        unverified artifacts are retained by policy.
        """
        from .retention import RetentionEntry

        state = self._load_state()
        last_pulled = state.get("last_pulled", {})
        if not isinstance(last_pulled, Mapping):
            last_pulled = {}
        entries: list[RetentionEntry] = []
        manifest_suffix = f"{SNAPSHOT_SUFFIX}.json"

        def artifact(path: Path, reason: str = "unrecognized-artifact") -> RetentionEntry:
            return RetentionEntry(
                manifest_path=path,
                snapshot_path=None,
                namespace=None,
                node_id=None,
                created_at=None,
                verified=False,
                reason=reason,
            )

        for path in sorted(self.config.transit.iterdir(), key=lambda item: item.name):
            if not path.name.endswith(manifest_suffix):
                entries.append(artifact(path))
                continue
            if _is_reparse_or_symlink(path) or not path.is_file():
                entries.append(artifact(path, "invalid-manifest"))
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                entries.append(artifact(path, "invalid-manifest"))
                continue
            if not isinstance(raw, Mapping):
                entries.append(artifact(path, "invalid-manifest"))
                continue

            namespace = raw.get("namespace")
            node_id = raw.get("node_id")
            created_at = raw.get("created_at")
            snapshot_path: Path | None = None
            try:
                if isinstance(raw.get("snapshot"), str):
                    snapshot_path = self.config.transit / _validated_snapshot_name(raw["snapshot"])
            except SyncError:
                snapshot_path = None

            # A manifest from another namespace is foreign by construction.
            # Do not ask the configured verifier to interpret or delete it.
            if isinstance(namespace, str) and namespace != self.config.namespace:
                entries.append(
                    RetentionEntry(
                        manifest_path=path,
                        snapshot_path=snapshot_path,
                        namespace=namespace,
                        node_id=node_id if isinstance(node_id, str) else None,
                        created_at=created_at if isinstance(created_at, str) else None,
                        verified=False,
                        reason="foreign-namespace",
                    )
                )
                continue

            required = {
                "protocol",
                "namespace",
                "node_id",
                "created_at",
                "snapshot",
                "sha256",
                "size",
            }
            if (
                not required.issubset(raw)
                or namespace != self.config.namespace
                or not isinstance(node_id, str)
                or not isinstance(created_at, str)
                or snapshot_path is None
            ):
                entries.append(
                    RetentionEntry(
                        manifest_path=path,
                        snapshot_path=snapshot_path,
                        namespace=namespace if isinstance(namespace, str) else None,
                        node_id=node_id if isinstance(node_id, str) else None,
                        created_at=created_at if isinstance(created_at, str) else None,
                        verified=False,
                        reason="invalid-manifest",
                    )
                )
                continue

            try:
                snapshot = self._read_snapshot(path, verify=True)
            except (SyncError, OSError, TypeError, ValueError, OverflowError):
                entries.append(
                    RetentionEntry(
                        manifest_path=path,
                        snapshot_path=snapshot_path,
                        namespace=namespace,
                        node_id=node_id,
                        created_at=created_at,
                        verified=False,
                        reason="unverified",
                    )
                )
                continue
            pending = (
                snapshot.node_id != self.config.node_id
                and snapshot.created_at > str(last_pulled.get(snapshot.node_id, ""))
            )
            entries.append(
                RetentionEntry(
                    manifest_path=path,
                    snapshot_path=snapshot.path,
                    namespace=snapshot.namespace,
                    node_id=snapshot.node_id,
                    created_at=snapshot.created_at,
                    verified=True,
                    pending=pending,
                    snapshot=snapshot,
                )
            )
        return entries

    def apply_retention(
        self,
        policy: Any,
        *,
        dry_run: bool = True,
        now: datetime | None = None,
        audit_path: str | Path | None = None,
    ) -> Any:
        """Plan or apply an explicit retention policy for this transit."""
        from .retention import apply_retention

        return apply_retention(
            self,
            policy,
            dry_run=dry_run,
            now=now,
            audit_path=audit_path,
        )

    def snapshots(self, verify: bool = False) -> list[Snapshot]:
        if self._fts_contract is not None:
            return _fts_snapshots(self, verify)
        manifests = self.config.transit.glob(
            f"{self.config.namespace}__*__*{SNAPSHOT_SUFFIX}.json"
        )
        snapshots: list[Snapshot] = []
        for manifest in manifests:
            snapshots.append(self._read_snapshot(manifest, verify=verify))
        return sorted(snapshots, key=lambda item: (item.created_at, item.node_id))

    def cleanup(
        self,
        *,
        keep_days: int = 7,
        keep_per_node: int = 10,
        include_foreign: bool = False,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Select and optionally remove old verified-snapshot artifacts.

        Cleanup is deliberately conservative: it is a dry-run by default and
        only manages snapshots published by this node unless the caller makes
        foreign-node administration explicit. A snapshot is eligible only when
        it is both older than ``keep_days`` and outside the newest
        ``keep_per_node`` snapshots for its source node.
        """
        if keep_days < 0:
            raise ValueError("keep_days must be zero or greater")
        if keep_per_node < 0:
            raise ValueError("keep_per_node must be zero or greater")

        snapshots = self.snapshots(verify=False)
        selected = [
            snapshot
            for snapshot in snapshots
            if include_foreign or snapshot.node_id == self.config.node_id
        ]
        # Cleanup is destructive when applied, so every managed pair is verified
        # before selection. A damaged foreign payload does not block local-only
        # maintenance, but becomes fail-closed as soon as all-node authority is
        # requested.
        managed = [
            self._read_snapshot(snapshot.manifest_path, verify=True)
            for snapshot in selected
        ]
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        by_node: dict[str, list[Snapshot]] = {}
        for snapshot in managed:
            by_node.setdefault(snapshot.node_id, []).append(snapshot)

        eligible: list[Snapshot] = []
        for node_snapshots in by_node.values():
            newest_first = sorted(
                node_snapshots,
                key=lambda item: item.created_at,
                reverse=True,
            )
            for index, snapshot in enumerate(newest_first):
                try:
                    created_at = _parse_utc_token(snapshot.created_at)
                except ValueError as error:
                    raise SyncError(
                        f"Invalid snapshot timestamp in {snapshot.manifest_path}: "
                        f"{snapshot.created_at}"
                    ) from error
                if index >= keep_per_node and created_at < cutoff:
                    eligible.append(snapshot)

        eligible.sort(key=lambda item: (item.node_id, item.created_at))

        def summary(snapshot: Snapshot) -> dict[str, str]:
            return {
                "snapshot": snapshot.path.name,
                "manifest": snapshot.manifest_path.name,
                "node_id": snapshot.node_id,
                "created_at": snapshot.created_at,
            }

        deleted: list[dict[str, str]] = []
        if not dry_run:
            for snapshot in eligible:
                _assert_no_sqlite_sidecars(snapshot.path)
                tombstone = snapshot.manifest_path.with_name(
                    f".{snapshot.manifest_path.name}.cleanup"
                )
                if tombstone.exists():
                    raise SyncError(f"Cleanup tombstone already exists: {tombstone}")
                try:
                    os.replace(snapshot.manifest_path, tombstone)
                except OSError as error:
                    raise SyncError(
                        f"Could not stage snapshot manifest for cleanup: {snapshot.manifest_path}: "
                        f"{error}"
                    ) from error
                try:
                    snapshot.path.unlink()
                except OSError as error:
                    try:
                        os.replace(tombstone, snapshot.manifest_path)
                    except OSError as restore_error:
                        raise SyncError(
                            f"Could not remove {snapshot.path} and could not restore "
                            f"{snapshot.manifest_path}: {restore_error}"
                        ) from error
                    raise SyncError(f"Could not remove snapshot {snapshot.path}: {error}") from error
                try:
                    tombstone.unlink()
                except OSError as error:
                    raise SyncError(f"Could not remove cleanup tombstone {tombstone}: {error}") from error
                deleted.append(summary(snapshot))

        return {
            "dry_run": dry_run,
            "scope": "all-nodes" if include_foreign else "local-node",
            "keep_days": keep_days,
            "keep_per_node": keep_per_node,
            "examined": len(snapshots),
            "managed": len(managed),
            "skipped_foreign": len(snapshots) - len(managed),
            "eligible": [summary(snapshot) for snapshot in eligible],
            "deleted": deleted,
        }

    def pending(self, verify: bool = False) -> list[Snapshot]:
        if self._fts_contract is not None:
            return _fts_pending(self, verify)
        state = self._load_state()
        last_pulled = state.get("last_pulled", {})
        return [
            snapshot
            for snapshot in self.snapshots(verify=verify)
            if snapshot.node_id != self.config.node_id
            and snapshot.created_at > last_pulled.get(snapshot.node_id, "")
        ]

    def _pull_snapshots(
        self,
        pending: Sequence[Snapshot],
        *,
        dry_run: bool,
    ) -> list[MergeReport]:
        if self._fts_contract is not None:
            return _fts_call("pull", lambda: _fts_pull_snapshots(self, pending, dry_run=dry_run))
        if dry_run:
            return [MergeReport(snapshot=item.path.name, source_node=item.node_id) for item in pending]
        if not self.config.database.is_file():
            raise SyncError(
                "The local database must exist with its application schema before pull; "
                "automatic first-copy is intentionally disabled"
            )

        reports: list[MergeReport] = []
        state = self._load_state()
        for snapshot in pending:
            local: sqlite3.Connection | None = None
            remote: sqlite3.Connection | None = None
            try:
                local = sqlite3.connect(str(self.config.database))
                remote = sqlite3.connect(f"file:{snapshot.path.as_posix()}?mode=ro", uri=True)
                local.execute("BEGIN IMMEDIATE")
                report = self.policy.merge(local, remote, snapshot)
                local.commit()
            except Exception:
                if local is not None:
                    local.rollback()
                raise
            finally:
                if remote is not None:
                    remote.close()
                if local is not None:
                    local.close()
            state.setdefault("last_pulled", {})[snapshot.node_id] = snapshot.created_at
            self._save_state(state)
            reports.append(report)
        return reports

    def pull(self, dry_run: bool = False) -> list[MergeReport]:
        """Merge every pending verified snapshot in deterministic order."""

        if self._fts_contract is not None:
            return _fts_call("pull", lambda: _fts_pull(self, None, dry_run=dry_run))
        return self._pull_snapshots(self.pending(verify=True), dry_run=dry_run)

    def pull_selected(
        self,
        snapshot_names: Sequence[str],
        dry_run: bool = False,
    ) -> list[MergeReport]:
        """Merge only explicitly selected pending snapshots.

        Selection uses snapshot basenames returned by :meth:`pending`; paths,
        manifest names, duplicates and snapshots that are no longer pending are
        rejected before the local database or sync state is changed. This keeps
        application adapters from reimplementing merge and state advancement
        when their lifecycle deliberately processes one pending snapshot.
        """

        if self._fts_contract is not None:
            return _fts_call("selected-pull", lambda: _fts_pull(self, snapshot_names, dry_run=dry_run))
        if isinstance(snapshot_names, (str, bytes)):
            raise ValueError("snapshot_names must be a sequence of snapshot basenames")
        requested = list(snapshot_names)
        if not requested:
            return []
        if any(not isinstance(name, str) for name in requested):
            raise ValueError("snapshot_names must contain only strings")
        if len(requested) != len(set(requested)):
            raise ValueError("snapshot_names must not contain duplicates")
        for name in requested:
            # Check both separators explicitly rather than relying solely on
            # Path(name).name: pathlib only treats "\\" as a separator on
            # Windows, so a POSIX runner would let a "..\\name" traversal
            # attempt straight through this basename gate.
            if (
                "/" in name
                or "\\" in name
                or Path(name).name != name
                or not name.endswith(SNAPSHOT_SUFFIX)
            ):
                raise ValueError(f"Invalid snapshot basename: {name!r}")

        pending = self.pending(verify=True)
        by_name = {snapshot.path.name: snapshot for snapshot in pending}
        missing = [name for name in requested if name not in by_name]
        if missing:
            raise SyncError(
                "Selected snapshots are not pending: " + ", ".join(sorted(missing))
            )
        selected = [by_name[name] for name in requested]
        return self._pull_snapshots(selected, dry_run=dry_run)

    def sync(self) -> dict[str, Any]:
        pulled = self.pull()
        pushed = self.push()
        return {"pulled": [report.as_dict() for report in pulled], "pushed": pushed.as_dict()}

    def verify(self) -> dict[str, Any]:
        if self._fts_contract is not None:
            return _fts_verify(self)
        self._quick_check(self.config.database)
        snapshots = self.snapshots(verify=True)
        return {"database": "ok", "verified_snapshots": len(snapshots)}

    def status(self) -> dict[str, Any]:
        if self._fts_contract is not None:
            return _fts_status(self)
        state = self._load_state()
        pending = self.pending(verify=False)
        return {
            "node_id": self.config.node_id,
            "namespace": self.config.namespace,
            "database": str(self.config.database),
            "transit": str(self.config.transit),
            "state": str(self.config.state),
            "database_exists": self.config.database.is_file(),
            "pending": [snapshot.as_dict() for snapshot in pending],
            "last_pulled": state.get("last_pulled", {}),
        }


# Protocol 2 requires a typed receiver; protocol-1 readers reject it.
FTS_SNAPSHOT_PROTOCOL = 2
FTS_SNAPSHOT_FORMAT = "sqlite-logical-fts5-v1"


@dataclass(frozen=True, slots=True)
class FtsSchemaObject:
    """Complete local sqlite_schema authority, excluding physical page numbers."""
    type: str
    name: str
    table_name: str
    sql: str | None

    def __post_init__(self) -> None:
        if self.type not in ("table", "index", "trigger", "view"):
            raise ValueError("Unsupported schema object")
        if any(type(v) is not str or not v or "\x00" in v for v in (self.name, self.table_name)):
            raise ValueError("Invalid schema identifier")
        if self.sql is not None and (type(self.sql) is not str or not self.sql):
            raise ValueError("Invalid schema DDL")


@dataclass(frozen=True, slots=True)
class Fts5Column:
    name: str
    unindexed: bool = False

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name or "\x00" in self.name or type(self.unindexed) is not bool:
            raise ValueError("Invalid typed FTS column")


@dataclass(frozen=True, slots=True)
class Fts5Descriptor:
    """Ordinary internal stored content or ordinary external content only."""
    name: str
    columns: tuple[Fts5Column, ...]
    content_table: str | None = None
    content_rowid: str = "rowid"
    tokenizer: str = "unicode61"
    prefix: tuple[int, ...] = ()
    detail: str = "full"
    columnsize: int = 1
    configuration: tuple[tuple[str, str | int], ...] = (("version", 4),)

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name or "\x00" in self.name:
            raise ValueError("Invalid FTS name")
        if type(self.columns) is not tuple or not self.columns or any(type(c) is not Fts5Column for c in self.columns):
            raise ValueError("Immutable typed columns required")
        names = tuple(c.name.casefold() for c in self.columns)
        if len(names) != len(set(names)) or any(n in ("rowid", self.name.casefold(), "rank") for n in names):
            raise ValueError("Ambiguous FTS columns")
        if self.content_table is not None and (type(self.content_table) is not str or not self.content_table or "\x00" in self.content_table):
            raise ValueError("Contentless FTS unsupported")
        if type(self.content_rowid) is not str or not self.content_rowid or "\x00" in self.content_rowid:
            raise ValueError("Invalid docid selector")
        if self.content_table is None and self.content_rowid != "rowid":
            raise ValueError("Internal FTS requires rowid")
        if type(self.tokenizer) is not str or not self.tokenizer or "\x00" in self.tokenizer or self.tokenizer.split()[0] not in ("unicode61", "ascii", "porter", "trigram"):
            raise ValueError("Unsupported tokenizer")
        if type(self.prefix) is not tuple or any(type(v) is not int or not 1 <= v <= 1000 for v in self.prefix) or self.prefix != tuple(sorted(set(self.prefix))):
            raise ValueError("Invalid prefix lengths")
        if self.detail not in ("full", "column", "none") or type(self.columnsize) is not int or self.columnsize not in (0, 1):
            raise ValueError("Invalid FTS detail/columnsize")
        if type(self.configuration) is not tuple or not self.configuration or any(type(p) is not tuple or len(p) != 2 or type(p[0]) is not str or type(p[1]) not in (str, int) for p in self.configuration):
            raise ValueError("Complete typed FTS configuration required")
        if self.configuration != tuple(sorted(self.configuration)) or len({k for k, _ in self.configuration}) != len(self.configuration) or "version" not in dict(self.configuration):
            raise ValueError("Ambiguous FTS configuration")


@dataclass(frozen=True, slots=True)
class FtsSQLiteProfile:
    """Locally pinned complete SQLite implementation identity."""
    version: str
    source_id: str
    compile_options: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v for v in (self.version, self.source_id)):
            raise ValueError("SQLite identity required")
        if type(self.compile_options) is not tuple or any(type(v) is not str for v in self.compile_options) or self.compile_options != tuple(sorted(set(self.compile_options))):
            raise ValueError("Complete sorted compilation options required")


@dataclass(frozen=True, slots=True)
class FtsSnapshotContract:
    """Local schema/config authority; never populated from a remote manifest."""
    contract_id: str
    private_root: Path
    sqlite: FtsSQLiteProfile
    schema_objects: tuple[FtsSchemaObject, ...]
    descriptors: tuple[Fts5Descriptor, ...]
    user_version: int
    redacted_tables: tuple[str, ...]
    foreign_key_violations: tuple[tuple[Any, ...], ...] = ()

    def __post_init__(self) -> None:
        if type(self.contract_id) is not str or not self.contract_id or "\x00" in self.contract_id:
            raise ValueError("Contract identity required")
        if not isinstance(self.private_root, Path) or not self.private_root.is_absolute() or ".." in self.private_root.parts:
            raise ValueError("Explicit absolute private root required")
        if type(self.sqlite) is not FtsSQLiteProfile:
            raise ValueError("Typed SQLite authority required")
        if type(self.schema_objects) is not tuple or not self.schema_objects or any(type(o) is not FtsSchemaObject for o in self.schema_objects):
            raise ValueError("Complete immutable schema required")
        keys = tuple((o.type, o.name) for o in self.schema_objects)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("Schema must be unique and sorted")
        if type(self.descriptors) is not tuple or not self.descriptors or any(type(d) is not Fts5Descriptor for d in self.descriptors) or len({d.name for d in self.descriptors}) != len(self.descriptors):
            raise ValueError("Unique typed FTS descriptors required")
        if type(self.user_version) is not int or not 0 <= self.user_version <= 2147483647:
            raise ValueError("Invalid user_version")
        if type(self.redacted_tables) is not tuple or any(type(v) is not str or not v or "\x00" in v for v in self.redacted_tables) or self.redacted_tables != tuple(sorted(set(self.redacted_tables))):
            raise ValueError("Exact sorted redactions required")
        if type(self.foreign_key_violations) is not tuple or any(type(v) is not tuple for v in self.foreign_key_violations):
            raise ValueError("Complete FK violation tuples required")


def _fts_frame(value: Any) -> bytes:
    if value is None:
        tag, payload = b"N", b""
    elif type(value) is int:
        if not -(1 << 63) <= value < (1 << 63):
            raise SyncError("FTS SQLite int64 range")
        tag, payload = b"I", value.to_bytes(8, "big", signed=True)
    elif type(value) is float:
        if not math.isfinite(value):
            raise SyncError("FTS nonfinite value")
        tag, payload = b"F", struct.pack(">d", value)
    elif type(value) is str:
        tag, payload = b"T", value.encode("utf-8", "strict")
    else:
        raise SyncError("FTS unsupported plaintext representation")
    return tag + len(payload).to_bytes(8, "big") + payload


def _fts_relation(rows: Iterable[Sequence[Any]], scan: Any = None) -> tuple[int, str]:
    """Typed length-framed multiset commitment, including duplicate count."""
    hashes = []
    for row in rows:
        digest = hashlib.sha256()
        digest.update(len(row).to_bytes(8, "big"))
        for ordinal, value in enumerate(row):
            if scan is not None:
                scan(value, ordinal)
            digest.update(_fts_frame(value))
        hashes.append(digest.digest())
    digest = hashlib.sha256()
    digest.update(len(hashes).to_bytes(8, "big"))
    for value in sorted(hashes):
        digest.update(value)
    return len(hashes), digest.hexdigest()


def _fts_schema(connection: sqlite3.Connection) -> tuple[FtsSchemaObject, ...]:
    return tuple(FtsSchemaObject(*row) for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM main.sqlite_schema ORDER BY type,name"
    ))


def _fts_schema_digest(objects: tuple[FtsSchemaObject, ...]) -> str:
    return _fts_relation((o.type, o.name, o.table_name, o.sql) for o in objects)[1]


def _fts_profile(connection: sqlite3.Connection, profile: FtsSQLiteProfile) -> None:
    actual = (
        connection.execute("SELECT sqlite_version()").fetchone()[0],
        connection.execute("SELECT sqlite_source_id()").fetchone()[0],
        tuple(sorted(r[0] for r in connection.execute("PRAGMA compile_options"))),
    )
    if actual != (profile.version, profile.source_id, profile.compile_options):
        raise SyncError("FTS SQLite implementation mismatch")


def _fts_file_identity(path: Path, *, sidecars: bool = True) -> tuple[int, int, int, int]:
    if not path.is_absolute() or ".." in path.parts:
        raise SyncError("FTS path must be absolute without traversal")
    for p in (path, *path.parents):
        if _is_reparse_or_symlink(p):
            raise SyncError("FTS path has link/reparse ancestor")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SyncError("FTS file must be exclusively owned and regular")
    if sidecars and any(p.name.startswith(path.name + "-") for p in path.parent.iterdir()):
        raise SyncError("FTS private image has SQLite sidecars")
    with path.open("rb", buffering=0) as stream:
        fd = os.fstat(stream.fileno())
        if (fd.st_dev, fd.st_ino, fd.st_size, fd.st_mtime_ns) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
            raise SyncError("FTS pathname/FD identity mismatch")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _fts_private_root(root: Path, transit: Path) -> None:
    if not root.is_absolute() or ".." in root.parts or not root.is_dir():
        raise SyncError("FTS private root must preexist")
    for p in (root, *root.parents):
        if _is_reparse_or_symlink(p):
            raise SyncError("FTS private root is aliased")
    if os.name != "nt" and root.stat().st_mode & 0o077:
        raise SyncError("FTS private root is accessible outside its owner")
    actual, transport = root.resolve(strict=True), transit.resolve()
    if actual == transport or actual.is_relative_to(transport) or transport.is_relative_to(actual):
        raise SyncError("Private root and transit must be separate")


def _fts_word(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"', "\x60"):
        return text[1:-1].replace(text[0] * 2, text[0])
    if text.startswith("[") and text.endswith("]"):
        return text[1:-1]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", text):
        raise SyncError("Unsupported FTS argument")
    return text


def _fts_ddl_parts(sql: str) -> list[str]:
    match = re.fullmatch(
        r"\s*CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:\x22(?:[^\x22]|\x22\x22)+\x22|\x60[^\x60]+\x60|\[[^\]]+\]|[A-Za-z_][A-Za-z_0-9]*)"
        r"\s+USING\s+fts5\s*\((.*)\)\s*;?\s*", sql, re.IGNORECASE | re.DOTALL)
    if match is None:
        raise SyncError("Unsupported locally pinned FTS DDL")
    body, parts, start, index, quote = match.group(1), [], 0, 0, None
    while index < len(body):
        char = body[index]
        if quote is not None:
            close = "]" if quote == "[" else quote
            if char == close:
                if index + 1 < len(body) and body[index + 1] == close and quote != "[":
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"', "\x60", "["):
            quote = char
        elif char == ",":
            parts.append(body[start:index].strip())
            start = index + 1
        elif char in "();":
            raise SyncError("Unsupported FTS argument grammar")
        index += 1
    parts.append(body[start:].strip())
    if quote is not None or any(not p for p in parts):
        raise SyncError("Invalid FTS arguments")
    return parts


def _fts_bind_ddl(obj: FtsSchemaObject, d: Fts5Descriptor) -> None:
    if obj.type != "table" or obj.name != d.name or obj.table_name != d.name or obj.sql is None:
        raise SyncError("FTS descriptor/schema mismatch")
    cols, options = [], {}
    for part in _fts_ddl_parts(obj.sql):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip().lower(), v.strip()
            if k not in ("content", "content_rowid", "tokenize", "prefix", "detail", "columnsize") or k in options:
                raise SyncError("Unknown/duplicate FTS option")
            options[k] = v if v.isdigit() else _fts_word(v)
        else:
            flag = bool(re.search(r"\s+UNINDEXED\s*$", part, re.IGNORECASE))
            name = re.sub(r"\s+UNINDEXED\s*$", "", part, flags=re.IGNORECASE) if flag else part
            cols.append(Fts5Column(_fts_word(name), flag))
    actual = (options.get("content"), options.get("content_rowid", "rowid"),
              options.get("tokenize", "unicode61"), options.get("prefix", ""),
              options.get("detail", "full"), options.get("columnsize", "1"))
    expected = (d.content_table, d.content_rowid, d.tokenizer,
                " ".join(str(v) for v in d.prefix), d.detail, str(d.columnsize))
    if tuple(cols) != d.columns or actual != expected:
        raise SyncError("FTS DDL/config descriptor mismatch")


def _fts_layout(c: sqlite3.Connection) -> tuple[Any, ...]:
    objects = _fts_schema(c)
    tables = tuple(sorted(tuple(r) for r in c.execute("PRAGMA main.table_list")))
    cols = tuple((o.name, tuple(tuple(r) for r in c.execute(
        f"PRAGMA main.table_xinfo({_quote_identifier(o.name)})"
    ))) for o in objects if o.type in ("table", "view"))
    indexes = tuple((o.name, tuple(tuple(r) for r in c.execute(
        f"PRAGMA main.index_xinfo({_quote_identifier(o.name)})"
    ))) for o in objects if o.type == "index")
    return objects, tables, cols, indexes


def _fts_config(c: sqlite3.Connection, generated: frozenset[str]) -> tuple[tuple[str, Any], ...]:
    names = [n for n in generated if tuple(r[1] for r in c.execute(
        f"PRAGMA main.table_xinfo({_quote_identifier(n)})"
    )) == ("k", "v")]
    if len(names) != 1:
        raise SyncError("FTS engine config relation is ambiguous")
    return tuple(c.execute(f"SELECT k,v FROM main.{_quote_identifier(names[0])} ORDER BY k"))


def _fts_integrity(c: sqlite3.Connection, descriptors: tuple[Fts5Descriptor, ...]) -> None:
    if c.execute("PRAGMA main.integrity_check").fetchall() != [("ok",)]:
        raise SyncError("FTS rebuilt database integrity failed")
    for d in descriptors:
        name = _quote_identifier(d.name)
        c.execute(f"INSERT INTO {name}({name},rank) VALUES('integrity-check',1)")



def _fts_plain_inventory(c: sqlite3.Connection, derived: frozenset[str],
                         bound_layout: tuple[Any, ...]) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    """Validate ordinary C1 layout; old opaque FTS bytes are never coverage."""
    if _fts_layout(c) != bound_layout:
        raise SyncError("FTS source/prototype complete layout mismatch")
    objects = _fts_schema(c)
    inventory = []
    for row in c.execute("PRAGMA main.table_list"):
        if row[0] != "main" or row[2] not in ("table", "view", "virtual", "shadow"):
            raise SyncError("FTS unexpected schema namespace/kind")
        name, kind = row[1:3]
        if name == "sqlite_schema":
            continue
        if name in derived:
            if kind not in ("virtual", "shadow"):
                raise SyncError("FTS derived object kind mismatch")
            continue
        if kind in ("virtual", "shadow"):
            raise SyncError("FTS unbound virtual/shadow object")
        columns = c.execute(f"PRAGMA main.table_xinfo({_quote_identifier(name)})").fetchall()
        if not columns or len(columns) != row[3]:
            raise SyncError("FTS incomplete ordinary xinfo")
        names = []
        for ordinal, col in enumerate(columns):
            if (len(col) != 7 or col[0] != ordinal or type(col[1]) is not str
                    or not col[1] or "\x00" in col[1] or col[1] in names
                    or type(col[2]) is not str or type(col[3]) is not int
                    or col[3] not in (0, 1) or (col[4] is not None and type(col[4]) is not str)
                    or type(col[5]) is not int or col[5] < 0
                    or type(col[6]) is not int or col[6] not in (0, 2, 3)):
                raise SyncError("FTS unsupported ordinary column")
            names.append(col[1])
        if kind == "view":
            continue  # Scan DDL, never run arbitrary view SQL.
        indices = {o.name for o in objects if o.type == "index" and o.table_name == name}
        for index in indices:
            info = c.execute(f"PRAGMA main.index_xinfo({_quote_identifier(index)})").fetchall()
            if not info:
                raise SyncError("FTS unavailable ordinary index metadata")
            for ordinal, col in enumerate(info):
                if (len(col) != 6 or col[0] != ordinal or type(col[1]) is not int
                        or type(col[3]) is not int or col[3] not in (0, 1)
                        or type(col[4]) is not str or type(col[5]) is not int or col[5] not in (0, 1)
                        or col[1] < -1 or col[1] >= len(names)
                        or (col[1] == -1 and col[2] is not None)
                        or (col[1] >= 0 and col[2] != names[col[1]])):
                    raise SyncError("FTS unsupported expression/ordinary index binding")
        selector = _secret_scan_rowid(c, name, row[4], columns, indices)
        all_columns = tuple(names) + ((selector,) if selector is not None else ())
        stored_columns = tuple(col[1] for col in columns if col[6] == 0) + ((selector,) if selector is not None else ())
        inventory.append((name, all_columns, stored_columns))
    if c.execute("PRAGMA main.integrity_check").fetchall() != [("ok",)]:
        raise SyncError("FTS ordinary index/database integrity failure")
    return sorted(inventory)


def _fts_rows(c: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> sqlite3.Cursor:
    return c.execute(f"SELECT {','.join(_quote_identifier(v) for v in columns)} FROM main.{_quote_identifier(table)}")


def _fts_logical_rows(c: sqlite3.Connection, d: Fts5Descriptor,
                      inventory: list[tuple[str, tuple[str, ...], tuple[str, ...]]]) -> sqlite3.Cursor:
    if d.content_table is None:
        # Internal FTS without MATCH reads current stored content, not old token
        # segments. The engine-derived layout is bound before this query.
        return _fts_rows(c, d.name, ("rowid", *(col.name for col in d.columns)))
    ordinary = {name: columns for name, columns, _ in inventory}
    if d.content_table not in ordinary:
        raise SyncError("FTS external content is not a validated ordinary table")
    info = c.execute(f"PRAGMA main.table_xinfo({_quote_identifier(d.content_table)})").fetchall()
    declared = {r[1].casefold(): r[1] for r in info}
    selector = declared.get(d.content_rowid.casefold())
    if selector is None:
        if d.content_rowid.casefold() not in ("rowid", "_rowid_", "oid"):
            raise SyncError("FTS missing external docid")
        if d.content_rowid.casefold() in declared:
            raise SyncError("FTS shadowed external rowid")
        table_row = next(r for r in c.execute("PRAGMA main.table_list") if r[1] == d.content_table)
        if table_row[4]:
            raise SyncError("FTS external content has no implicit rowid")
        selector = d.content_rowid
    columns = []
    for col in d.columns:
        if col.name.casefold() not in declared:
            raise SyncError("FTS missing external content column")
        columns.append(declared[col.name.casefold()])
    return _fts_rows(c, d.content_table, (selector, *columns))


def _fts_set_config(c: sqlite3.Connection, d: Fts5Descriptor) -> None:
    allowed = {"automerge", "crisismerge", "deletemerge", "pgsz", "rank", "secure-delete", "usermerge", "version"}
    for key, value in d.configuration:
        if key not in allowed:
            raise SyncError("Unsupported pinned FTS configuration")
        if key != "version":
            name = _quote_identifier(d.name)
            c.execute(f"INSERT INTO {name}({name},rank) VALUES(?,?)", (key, value))


def _fts_construct(c: sqlite3.Connection, contract: FtsSnapshotContract,
                   source_kinds: Mapping[str, str], *, delayed: bool) -> dict[str, frozenset[str]]:
    """SQLite creates every technical object; never copy old shadow pages."""
    descriptor_names = {d.name for d in contract.descriptors}
    objects = {(o.type, o.name): o for o in contract.schema_objects}
    for o in contract.schema_objects:
        if o.type == "table" and source_kinds.get(o.name) == "table" and o.name != "sqlite_sequence":
            if o.sql is None or o.name.startswith("sqlite_"):
                raise SyncError("FTS unsupported reserved ordinary table")
            c.execute(o.sql)
    generated = {}
    for d in contract.descriptors:
        obj = objects.get(("table", d.name))
        if obj is None:
            raise SyncError("FTS descriptor has no schema object")
        _fts_bind_ddl(obj, d)
        before = {o.name for o in _fts_schema(c)}
        c.execute(obj.sql)
        _fts_set_config(c, d)
        after = {o.name for o in _fts_schema(c)}
        names = frozenset(after - before)
        if d.name not in names or not names:
            raise SyncError("FTS engine did not produce the declared layout")
        table_kinds = {r[1]: r[2] for r in c.execute("PRAGMA main.table_list")}
        if table_kinds[d.name] != "virtual" or any(table_kinds.get(n) != "shadow" for n in names if n != d.name):
            raise SyncError("FTS engine-created layout is not FTS5")
        if _fts_config(c, names) != d.configuration:
            raise SyncError("FTS configuration not reproduced")
        generated[d.name] = names
    virtuals = {n for n, k in source_kinds.items() if k == "virtual"}
    if virtuals != descriptor_names:
        raise SyncError("FTS descriptor set is not complete")
    if delayed:
        _fts_delayed_schema(c, contract)
    c.execute(f"PRAGMA user_version={contract.user_version}")
    return generated


def _fts_delayed_schema(c: sqlite3.Connection, contract: FtsSnapshotContract) -> None:
    for kind in ("index", "view", "trigger"):
        for o in contract.schema_objects:
            if o.type == kind and o.sql is not None:
                c.execute(o.sql)


def _fts_scan_values(c: sqlite3.Connection, contract: FtsSnapshotContract,
                     inventory: list[tuple[str, tuple[str, ...], tuple[str, ...]]],
                     generated: Mapping[str, frozenset[str]], patterns: Sequence[SecretPattern],
                     *, source: bool) -> dict[tuple[str, str], tuple[int, str]]:
    findings: list[str] = []
    def scan(value: Any, ordinal: int) -> None:
        _secret_scan_value(value, f"logical-value#{ordinal}", patterns, findings)
    for ordinal, row in enumerate(c.execute(
            "SELECT type,name,tbl_name,rootpage,sql,rowid FROM main.sqlite_schema ORDER BY type,name")):
        for field_index, value in enumerate(row):
            _secret_scan_value(value, f"schema#{ordinal}.field#{field_index}", patterns, findings)
    relations = {}
    for name, columns, _ in inventory:
        if source and name in contract.redacted_tables:
            relations[("ordinary", name)] = _fts_relation(())
        else:
            relations[("ordinary", name)] = _fts_relation(_fts_rows(c, name, columns), scan)
    for d in contract.descriptors:
        for key, value in _fts_config(c, generated[d.name]):
            scan(key, 0)
            scan(value, 1)
        omit = d.name in contract.redacted_tables or d.content_table in contract.redacted_tables
        seen: set[int] = set()
        def rows() -> Iterable[Sequence[Any]]:
            if omit and source:
                return
            for row in _fts_logical_rows(c, d, inventory):
                docid = row[0]
                if type(docid) is not int or not -(1 << 63) <= docid < (1 << 63) or docid in seen:
                    raise SyncError("FTS docids must be unique nonnull int64")
                seen.add(docid)
                yield row
        relations[("fts", d.name)] = _fts_relation(rows(), scan)
    if findings:
        raise SyncError("FTS publication refused: credential-looking logical values or schema")
    return relations


def _fts_prepare(source_path: Path, output_path: Path, prototype_path: Path,
                 contract: FtsSnapshotContract, patterns: Sequence[SecretPattern],
                 *, budget: _FtsBudget | None = None) -> dict[str, Any]:
    """Closed immutable source -> new owned logical image, with scoped coverage.

    Only the exact newly constructed output receives generated-index coverage.
    Old opaque index bytes are neither scanned as safe nor copied.
    """
    identity = _fts_file_identity(source_path)
    _fts_file_identity(output_path)
    _fts_file_identity(prototype_path)
    original_hash = _sha256(source_path)
    source = prototype = output = None
    interrupted = False
    try:
        source = (budget.connect(source_path, writable=False) if budget is not None
                  else sqlite3.connect(source_path.as_uri() + "?mode=ro&immutable=1", uri=True))
        prototype = budget.connect(prototype_path, writable=True) if budget is not None else sqlite3.connect(str(prototype_path))
        output = budget.connect(output_path, writable=True) if budget is not None else sqlite3.connect(str(output_path))
        source.execute("PRAGMA query_only=ON")
        _fts_profile(source, contract.sqlite)
        _fts_profile(prototype, contract.sqlite)
        _fts_profile(output, contract.sqlite)
        if _fts_schema(source) != contract.schema_objects or source.execute("PRAGMA user_version").fetchone()[0] != contract.user_version:
            raise SyncError("FTS complete local schema/user_version authority mismatch")
        source_kinds = {r[1]: r[2] for r in source.execute("PRAGMA main.table_list") if r[0] == "main"}
        source_fk = tuple(sorted(tuple(r) for r in source.execute("PRAGMA foreign_key_check")))
        if source_fk != contract.foreign_key_violations:
            raise SyncError("FTS source foreign-key fingerprint mismatch")
        prototype.execute("PRAGMA journal_mode=DELETE")
        prototype.execute("PRAGMA foreign_keys=OFF")
        prototype_generated = _fts_construct(prototype, contract, source_kinds, delayed=True)
        prototype.commit()
        bound_layout = _fts_layout(prototype)
        if bound_layout != _fts_layout(source):
            raise SyncError("FTS actual source/engine prototype layout mismatch")
        generated = frozenset(n for names in prototype_generated.values() for n in names)
        if {n for n, k in source_kinds.items() if k in ("virtual", "shadow")} != generated:
            raise SyncError("FTS source has unbound technical objects")
        for d in contract.descriptors:
            if _fts_config(source, prototype_generated[d.name]) != d.configuration:
                raise SyncError("FTS source config mismatch")
        inventory = _fts_plain_inventory(source, generated, bound_layout)
        expected = _fts_scan_values(source, contract, inventory, prototype_generated, patterns, source=True)
        output.execute("PRAGMA journal_mode=DELETE")
        output.execute("PRAGMA foreign_keys=OFF")
        output.execute("BEGIN IMMEDIATE")
        output_generated = _fts_construct(output, contract, source_kinds, delayed=False)
        if output_generated != prototype_generated:
            raise SyncError("FTS output engine ownership layout mismatch")
        for name, _, stored in inventory:
            if name == "sqlite_sequence" or name in contract.redacted_tables:
                continue
            quoted = ",".join(_quote_identifier(n) for n in stored)
            sql = f"INSERT INTO main.{_quote_identifier(name)}({quoted}) VALUES({','.join('?' for _ in stored)})"
            cursor = _fts_rows(source, name, stored)
            if budget is not None:
                output.executemany(sql, budget.rows(cursor))
            else:
                while rows := cursor.fetchmany(256):
                    output.executemany(sql, rows)
        # SQLite_sequence is allocation metadata, not a default secret-table
        # redaction. Preserve its exact relation after ordinary row insertion.
        if any(n == "sqlite_sequence" for n, _, _ in inventory):
            output.execute("DELETE FROM sqlite_sequence")
            output.executemany("INSERT INTO sqlite_sequence(rowid,name,seq) VALUES(?,?,?)",
                               source.execute("SELECT rowid,name,seq FROM sqlite_sequence"))
        for d in contract.descriptors:
            name = _quote_identifier(d.name)
            omit = d.name in contract.redacted_tables or d.content_table in contract.redacted_tables
            if d.content_table is None:
                if not omit:
                    columns = ("rowid", *(v.name for v in d.columns))
                    sql = f"INSERT INTO {name}({','.join(_quote_identifier(v) for v in columns)}) VALUES({','.join('?' for _ in columns)})"
                    cursor = _fts_logical_rows(source, d, inventory)
                    while rows := cursor.fetchmany(256):
                        output.executemany(sql, rows)
            else:
                if d.name in contract.redacted_tables and d.content_table not in contract.redacted_tables:
                    raise SyncError("External FTS redaction requires redacting its content table")
                output.execute(f"INSERT INTO {name}({name}) VALUES('rebuild')")
        _fts_delayed_schema(output, contract)
        if _fts_layout(output) != bound_layout:
            raise SyncError("FTS rebuilt full schema/layout differs")
        _fts_integrity(output, contract.descriptors)
        _fts_plain_inventory(output, generated, bound_layout)
        # Private proof: output is this exact locally constructed connection,
        # full engine-generated layout is pinned above, and all current logical
        # relations below must equal the source after explicit redactions.
        def scan_constructed_output(connection: sqlite3.Connection) -> dict[tuple[str, str], tuple[int, str]]:
            # This closure is not public configuration: it admits only the
            # actual constructor connection, or its own subsequent reopen.
            if connection is not output and connection is not reopened:
                raise SyncError("FTS coverage proof belongs to another connection")
            databases = connection.execute("PRAGMA database_list").fetchall()
            main = [r for r in databases if r[1] == "main"]
            if len(main) != 1 or Path(main[0][2]).resolve() != output_path.resolve():
                raise SyncError("FTS coverage proof has another output origin")
            if _fts_layout(connection) != bound_layout or output_generated != prototype_generated:
                raise SyncError("FTS coverage proof generated layout changed")
            ordinary = _fts_plain_inventory(connection, generated, bound_layout)
            return _fts_scan_values(connection, contract, ordinary, output_generated, patterns, source=False)
        actual = scan_constructed_output(output)
        if actual != expected:
            raise SyncError("FTS rebuilt relation count/hash mismatch")
        output_fk = tuple(sorted(tuple(r) for r in output.execute("PRAGMA foreign_key_check")))
        if output_fk != contract.foreign_key_violations:
            raise SyncError("FTS output foreign-key fingerprint mismatch")
        output.commit()
        effect = {
            "format": FTS_SNAPSHOT_FORMAT, "contract_id": contract.contract_id,
            "source_sha256": original_hash,
            "source_schema_sha256": _fts_schema_digest(contract.schema_objects),
            "schema_sha256": _fts_schema_digest(_fts_schema(output)),
            "relations": [{"kind": k[0], "name": k[1], "count": v[0], "sha256": v[1]}
                          for k, v in sorted(actual.items())],
            "sqlite": asdict(contract.sqlite), "fts": [asdict(d) for d in contract.descriptors],
            "user_version": contract.user_version,
            "redacted_tables": list(contract.redacted_tables),
            "foreign_keys_sha256": _fts_relation(output_fk)[1],
            "coverage": "reconstructed-current-logical-content-and-schema",
        }
    except BaseException as error:
        interrupted = not isinstance(error, Exception)
        raise
    finally:
        _fts_close_connections((output, prototype, source), interrupted=interrupted)
    _fts_file_identity(output_path)
    digest = _sha256(output_path)
    reopened = (budget.connect(output_path, writable=True) if budget is not None
                else sqlite3.connect(output_path.as_uri() + "?mode=rw", uri=True))
    interrupted = False
    try:
        _fts_profile(reopened, contract.sqlite)
        if _fts_layout(reopened) != bound_layout or reopened.execute("PRAGMA user_version").fetchone()[0] != contract.user_version:
            raise SyncError("FTS reopen schema/implementation mismatch")
        _fts_integrity(reopened, contract.descriptors)
        current = scan_constructed_output(reopened)
        if current != expected:
            raise SyncError("FTS reopen relation mismatch")
        reopened.rollback()  # Integrity commands have no intended data effects.
    except BaseException as error:
        interrupted = not isinstance(error, Exception)
        raise
    finally:
        _fts_close_connections((reopened,), interrupted=interrupted)
    _fts_file_identity(output_path)
    if _sha256(output_path) != digest:
        raise SyncError("FTS integrity reopening changed the closed image")
    if _fts_file_identity(source_path) != identity or _sha256(source_path) != original_hash:
        raise SyncError("FTS immutable source drift")
    effect["effect_sha256"] = hashlib.sha256(json.dumps(effect, sort_keys=True, ensure_ascii=False,
                                                        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return effect




def _fts_close_connections(connections: tuple[sqlite3.Connection | None, ...],
                           *, interrupted: bool = False) -> None:
    failed = False
    for connection in connections:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                failed = True
    if failed and not interrupted:
        raise SyncError("FTS private connection close failed") from None


@dataclass(frozen=True, slots=True)
class _FtsOwnedLeaf:
    path: Path
    parents: tuple[tuple[Path, int, int], ...]
    device: int
    inode: int


def _fts_parent_identity(path: Path) -> tuple[tuple[Path, int, int], ...]:
    if not path.is_absolute() or ".." in path.parts:
        raise SyncError("FTS explicit path required")
    result = []
    for parent in path.parents:
        if _is_reparse_or_symlink(parent):
            raise SyncError("FTS parent alias")
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise SyncError("FTS parent kind")
        result.append((parent, info.st_dev, info.st_ino))
    return tuple(result)


def _fts_check_parents(parents: tuple[tuple[Path, int, int], ...]) -> None:
    for parent, device, inode in parents:
        if _is_reparse_or_symlink(parent):
            raise SyncError("FTS parent alias")
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != (device, inode):
            raise SyncError("FTS parent replaced")


def _fts_live_file(path: Path) -> tuple[tuple[tuple[Path, int, int], ...], int, int] | None:
    """Observe a literal SQLite path through a regular, nonaliased read FD.

    Bytes, length and mtime may change during a legitimate live WAL backup.
    These bounded path/FD observations are not an atomic SQLite VFS lock.
    """
    parents = _fts_parent_identity(path)
    if _is_reparse_or_symlink(path):
        raise SyncError("FTS live file alias")
    try:
        info = path.lstat()
    except FileNotFoundError:
        _fts_check_parents(parents)
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SyncError("FTS live file kind/link")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        actual = os.fstat(fd)
        current = path.lstat()
        if (_is_reparse_or_symlink(path) or not stat.S_ISREG(actual.st_mode)
                or actual.st_nlink != 1 or current.st_nlink != 1
                or (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino)
                or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
            raise SyncError("FTS live FD/path identity")
        _fts_check_parents(parents)
    finally:
        os.close(fd)
    return parents, info.st_dev, info.st_ino


def _fts_live_bind(database: Path) -> dict[Path, tuple[Any, ...] | None]:
    # Literal names, never glob patterns or suffix-based ownership.
    paths = (database, *(database.with_name(database.name + suffix)
                         for suffix in ("-wal", "-shm", "-journal")))
    result = {path: _fts_live_file(path) for path in paths}
    if result[database] is None:
        raise SyncError("FTS source missing")
    return result


def _fts_live_check(bound: dict[Path, tuple[Any, ...] | None], database: Path,
                    *, closed: bool = False) -> None:
    for path, previous in tuple(bound.items()):
        current = _fts_live_file(path)
        if previous is not None:
            _fts_check_parents(previous[0])
            if current is None:
                # SQLite itself may retire a sidecar when the last connection
                # closes. Disappearance during backup, or of main, is refused.
                if not closed or path == database:
                    raise SyncError("FTS live file disappeared")
                # Retire only the sidecar which is actually absent at this
                # accepted closed boundary. A later connection may create a new
                # regular sidecar; main/parents/replacements remain pinned.
                bound[path] = None
            elif current != previous:
                raise SyncError("FTS live file identity changed")
        elif current is not None:
            # Observed new regular sidecars are bound, never owned for deletion.
            bound[path] = current


def _fts_owned_check(leaf: _FtsOwnedLeaf, owned: list[_FtsOwnedLeaf]) -> None:
    aliases = [item for item in owned if (item.device, item.inode) == (leaf.device, leaf.inode)]
    if leaf not in aliases or len({item.path for item in aliases}) != len(aliases):
        raise SyncError("FTS ownership registry mismatch")
    # A temporary exclusive publication link is allowed only when both exact
    # pathnames are registered aliases of the actual created inode.
    for item in aliases:
        _fts_check_parents(item.parents)
        if _is_reparse_or_symlink(item.path):
            raise SyncError("FTS owned leaf alias")
        info = item.path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != len(aliases)
                or (info.st_dev, info.st_ino) != (item.device, item.inode)):
            raise SyncError("FTS owned leaf replaced or linked")
        fd = os.open(item.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            actual = os.fstat(fd)
            after = item.path.lstat()
            if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != len(aliases)
                    or (actual.st_dev, actual.st_ino) != (item.device, item.inode)
                    or (after.st_dev, after.st_ino) != (item.device, item.inode)
                    or after.st_nlink != len(aliases) or _is_reparse_or_symlink(item.path)):
                raise SyncError("FTS owned FD/path mismatch")
            _fts_check_parents(item.parents)
        finally:
            os.close(fd)


def _fts_create_private_file(path: Path, owned: list[_FtsOwnedLeaf]) -> _FtsOwnedLeaf:
    parents = _fts_parent_identity(path)
    if _is_reparse_or_symlink(path):
        raise SyncError("FTS new file alias")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        metadata = os.fstat(fd)
        # Retain creation provenance immediately; no later filename scan can
        # confer ownership on a replacement or a SQLite-created sidecar.
        leaf = _FtsOwnedLeaf(path, parents, metadata.st_dev, metadata.st_ino)
        owned.append(leaf)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SyncError("FTS new leaf kind/link")
        _fts_owned_check(leaf, owned)
        return leaf
    finally:
        os.close(fd)


def _fts_remove_owned(leaf: _FtsOwnedLeaf, owned: list[_FtsOwnedLeaf]) -> None:
    _fts_owned_check(leaf, owned)
    # Closing the verifying FD before unlink also works on Windows. Separate
    # stdlib path checks cannot promise atomic protection against a hostile
    # concurrent rename; no hard-race guarantee is asserted.
    leaf.path.unlink()
    owned.remove(leaf)


def _fts_cleanup(work: Path, identity: tuple[int, int],
                 parents: tuple[tuple[Path, int, int], ...],
                 owned: list[_FtsOwnedLeaf]) -> None:
    _fts_check_parents(parents)
    if _is_reparse_or_symlink(work):
        raise SyncError("FTS cleanup directory aliased; retained")
    info = work.lstat()
    if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
        raise SyncError("FTS cleanup directory replaced; retained")
    leaves = tuple(item for item in owned if item.path.parent == work)
    children = tuple(work.iterdir())  # This exact validated list is the only list used.
    if {child.name for child in children} != {item.path.name for item in leaves}:
        raise SyncError("FTS unowned private entry; retained")
    for leaf in leaves:
        _fts_owned_check(leaf, owned)
    for leaf in leaves:
        _fts_check_parents(parents)
        current = work.lstat()
        if (current.st_dev, current.st_ino) != identity or _is_reparse_or_symlink(work):
            raise SyncError("FTS cleanup parent drift; retained")
        _fts_remove_owned(leaf, owned)
    # A subsequently arriving unknown file prevents rmdir; it is never deleted.
    _fts_check_parents(parents)
    current = work.lstat()
    if (current.st_dev, current.st_ino) != identity or _is_reparse_or_symlink(work):
        raise SyncError("FTS cleanup parent drift; retained")
    work.rmdir()


def _fts_publish_copy(source: Path, target: Path, expected_hash: str,
                      owned: list[_FtsOwnedLeaf]) -> _FtsOwnedLeaf:
    """Cross-filesystem sanitized transport with exclusive FD provenance."""
    identity = _fts_file_identity(source)
    leaf = _fts_create_private_file(target, owned)
    _fts_owned_check(leaf, owned)
    fd = os.open(target, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (leaf.device, leaf.inode) or info.st_nlink != 1:
            raise SyncError("FTS staging write FD drift")
        source_digest = hashlib.sha256()
        with source.open("rb", buffering=0) as reader, os.fdopen(fd, "wb", buffering=0) as writer:
            fd = -1
            info = os.fstat(reader.fileno())
            if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != identity:
                raise SyncError("FTS source FD drift")
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                source_digest.update(block)
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
            info = os.fstat(reader.fileno())
            if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != identity:
                raise SyncError("FTS source changed during copy")
        _fts_owned_check(leaf, owned)
        if source_digest.hexdigest() != expected_hash or _sha256(target) != expected_hash:
            raise SyncError("FTS staging digest mismatch")
        if _fts_file_identity(source) != identity:
            raise SyncError("FTS source pathname drift")
        return leaf
    finally:
        if fd != -1:
            os.close(fd)


def _fts_publish_link(stage: _FtsOwnedLeaf, target: Path,
                      owned: list[_FtsOwnedLeaf], expected_hash: str) -> _FtsOwnedLeaf:
    _fts_owned_check(stage, owned)
    if _sha256(stage.path) != expected_hash:
        raise SyncError("FTS stage bytes drift")
    parents = _fts_parent_identity(target)
    if _is_reparse_or_symlink(target):
        raise SyncError("FTS final alias")
    os.link(stage.path, target)  # Exclusive; a concurrent target is never replaced.
    final = _FtsOwnedLeaf(target, parents, stage.device, stage.inode)
    owned.append(final)  # Successful link, not identical bytes, confers ownership.
    _fts_owned_check(final, owned)
    if _sha256(target) != expected_hash:
        raise SyncError("FTS linked bytes drift")
    _fts_remove_owned(stage, owned)
    _fts_owned_check(final, owned)
    return final


def _fts_publish_manifest(manifest: dict[str, Any], target: Path, work: Path,
                          owned: list[_FtsOwnedLeaf]) -> tuple[_FtsOwnedLeaf, str]:
    # This private file is exclusively created through our own FD, rather than
    # deriving rollback ownership from an atomic-writer name or matching bytes.
    private = _fts_create_private_file(work / "manifest.json", owned)
    payload = json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    _fts_owned_check(private, owned)
    fd = os.open(private.path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (private.device, private.inode) or info.st_nlink != 1:
            raise SyncError("FTS manifest write FD drift")
        with os.fdopen(fd, "wb", buffering=0) as writer:
            fd = -1
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
    finally:
        if fd != -1:
            os.close(fd)
    _fts_owned_check(private, owned)
    digest = hashlib.sha256(payload).hexdigest()
    if _sha256(private.path) != digest:
        raise SyncError("FTS private manifest bytes drift")
    stage = target.with_name("." + target.name + ".partial")
    return _fts_publish_copy(private.path, stage, digest, owned), digest


def _fts_initialize(sync: TransitSync, config: SyncConfig, policy: MergePolicy | None,
                    authenticator: SnapshotAuthenticator | None,
                    contract: FtsSnapshotContract) -> None:
    failed = False
    try:
        if type(contract) is not FtsSnapshotContract or type(authenticator) is not HMACSnapshotAuthenticator:
            raise SyncError("FTS typed contract/auth required")
        _fts_private_root(contract.private_root, config.transit)
        if config.scan_snapshot_for_secrets is not True or config.secret_scan_skip_tables:
            raise SyncError("FTS full coverage required")
        sync._fts_contract = contract
        sync.config = config
        sync.policy = policy or TimestampMergePolicy(timestamp_columns=config.timestamp_columns,
                                                     exclude_tables=config.exclude_tables)
        sync.authenticator = authenticator
        # Metadata/dry-run do not create directories. Applying APIs require
        # actual pre-existing admin-owned transport/private/state roots.
    except Exception:
        failed = True
    if failed:
        # Raised outside except: neither __cause__ nor __context__ retains a
        # SQLite/OS exception containing a schema, pathname or private value.
        raise SyncError("FTS publication refused [contract]") from None


def _fts_push(sync: TransitSync) -> Snapshot:
    phase = ["contract"]
    failed = False
    result = None
    try:
        result = _fts_push_owned(sync, phase)
    except Exception:
        failed = True
    if failed:
        raise SyncError("FTS publication refused [" + phase[0] + "]") from None
    return result





# Optional format-2 receiver/merge authority. None retains the protocol-1 ABI.
@dataclass(frozen=True, slots=True)
class FtsReceiveLimits:
    manifest_bytes: int = 65536
    snapshot_bytes: int = 268435456
    compressed_bytes: int = 268435456
    cipher_bytes: int = 536870912
    output_bytes: int = 268435456
    rows: int = 1000000
    relations: int = 4096
    text_bytes: int = 1048576
    busy_milliseconds: int = 3000
    deadline_milliseconds: int = 30000

    def __post_init__(self) -> None:
        if any(type(value) is not int or not 0 < value <= (1 << 40)
               for value in asdict(self).values()):
            raise ValueError("Finite positive non-bool FTS limits required")
        if self.busy_milliseconds > self.deadline_milliseconds:
            raise ValueError("Busy budget exceeds operation deadline")


@dataclass(frozen=True, slots=True)
class FtsInternalMergeBinding:
    table: str
    timestamp_column: str
    tombstone_table: str
    docid_column: str = "rowid"

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v or "\x00" in v for v in
               (self.table, self.timestamp_column, self.tombstone_table)) or self.docid_column != "rowid":
            raise ValueError("Explicit internal docid/version/tombstone authority required")


@dataclass(frozen=True, slots=True)
class FtsTriggerEffect:
    """Local pinned trigger may alter only these target provenance fields."""
    table: str
    trigger: str
    trigger_sql_sha256: str
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v or "\x00" in v for v in (self.table, self.trigger)):
            raise ValueError("Trigger origin required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.trigger_sql_sha256):
            raise ValueError("Pinned trigger source required")
        if type(self.columns) is not tuple or not self.columns or any(type(v) is not str or not v for v in self.columns):
            raise ValueError("Immutable provenance columns required")


@dataclass(frozen=True, slots=True)
class FtsMergeContract:
    """Application-owned table selection and existing reference-policy binding."""
    contract_id: str
    merge_tables: tuple[str, ...]
    preserve_tables: tuple[str, ...] = ()
    internal: tuple[FtsInternalMergeBinding, ...] = ()
    trigger_effects: tuple[FtsTriggerEffect, ...] = ()

    def __post_init__(self) -> None:
        if type(self.contract_id) is not str or not self.contract_id:
            raise ValueError("Local merge contract required")
        for values in (self.merge_tables, self.preserve_tables):
            if type(values) is not tuple or any(type(v) is not str or not v or "\x00" in v for v in values) or values != tuple(sorted(set(values))):
                raise ValueError("Exact immutable sorted table disposition required")
        if set(self.merge_tables) & set(self.preserve_tables):
            raise ValueError("Ambiguous merge/preserve table")
        if type(self.internal) is not tuple or any(type(v) is not FtsInternalMergeBinding for v in self.internal) or len({v.table for v in self.internal}) != len(self.internal):
            raise ValueError("Exact internal bindings required")
        if type(self.trigger_effects) is not tuple or any(type(v) is not FtsTriggerEffect for v in self.trigger_effects):
            raise ValueError("Local typed trigger effects required")


@dataclass(frozen=True, slots=True)
class FtsVerificationReport:
    source_node: str
    contract_id: str
    received_sha256: str
    sender_source_sha256: str
    receiver_private_source_sha256: str
    receiver_effect_sha256: str
    relations: tuple[tuple[str, str, int, str], ...]
    rebuilt_indexes: tuple[str, ...]
    payload_checked: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _FtsSnapshot(Snapshot):
    manifest_sha256: str
    payload_checked: bool = False


class _FtsBudget:
    def __init__(self, limits: FtsReceiveLimits) -> None:
        if type(limits) is not FtsReceiveLimits:
            raise SyncError("FTS local receive limits required")
        self.limits = limits
        self.until = time.monotonic() + limits.deadline_milliseconds / 1000

    def check(self) -> None:
        if time.monotonic() >= self.until:
            raise SyncError("FTS deadline exceeded")

    def connect(self, path: Path, *, writable: bool) -> sqlite3.Connection:
        self.check()
        c = None
        try:
            c = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro&immutable=1"),
                                uri=True, timeout=min(self.limits.busy_milliseconds / 1000,
                                                      max(0.001, self.until-time.monotonic())))
            c.set_progress_handler(lambda: int(time.monotonic() >= self.until), 1000)
            if hasattr(c, "setlimit") and hasattr(sqlite3, "SQLITE_LIMIT_LENGTH"):
                c.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, self.limits.text_bytes)
            if writable:
                page_size = c.execute("PRAGMA page_size").fetchone()[0]
                pages = self.limits.output_bytes // page_size
                if pages < 1 or c.execute(f"PRAGMA max_page_count={pages}").fetchone()[0] > pages:
                    raise SyncError("FTS SQLite file budget exceeded")
            else:
                c.execute("PRAGMA query_only=ON")
            return c
        except BaseException:
            if c is not None:
                c.close()
            raise

    def rows(self, cursor: sqlite3.Cursor) -> Iterable[tuple[Any, ...]]:
        count = 0
        while True:
            self.check()
            batch = cursor.fetchmany(256)
            if not batch:
                break
            for row in batch:
                count += 1
                if count > self.limits.rows:
                    raise SyncError("FTS row budget exceeded")
                for value in row:
                    if type(value) is str and len(value.encode("utf8")) > self.limits.text_bytes:
                        raise SyncError("FTS text budget exceeded")
                    _fts_frame(value)
                yield tuple(row)


def _fts_patterns(sync: TransitSync) -> list[SecretPattern]:
    if sync.config.scan_snapshot_for_secrets is not True or sync.config.secret_scan_skip_tables:
        raise SyncError("FTS full credential coverage required")
    contract = sync._fts_contract
    if tuple(sorted(set(sync.config.snapshot_exclude_tables) - {"sqlite_sequence"})) != contract.redacted_tables:
        raise SyncError("FTS redaction profile mismatch")
    patterns = list(load_secret_patterns(sync.config.secret_patterns_file))
    for ordinal, expression in enumerate(sync.config.secret_scan_extra_patterns):
        if type(expression) is not str or not expression:
            raise SyncError("FTS invalid credential matcher")
        patterns.append(SecretPattern(f"custom[{ordinal}]", re.compile(expression)))
    return patterns


class _FtsPreparedArtifactOwner:
    """One composition of the accepted backup/reconstruction/leaf owner.

    Output remains private. Publishers, receiver and Republica share the same
    constructor and exact inode registry; no raw image is published to Transit.
    """
    def __init__(self, sync: TransitSync, budget: _FtsBudget) -> None:
        self.sync, self.budget = sync, budget
        self.paths = _PublicationPaths.capture(sync.config)
        self.key_file = (Path(sync.config.key_file).expanduser().resolve()
                         if sync.config.key_file is not None else None)
        self.contract = sync._fts_contract
        _fts_private_root(self.contract.private_root, sync.config.transit)
        self.patterns = _fts_patterns(sync)
        parents = _fts_parent_identity(self.contract.private_root / ".fts-owner-probe")
        self.work = Path(tempfile.mkdtemp(prefix=".fts-logical-", dir=self.contract.private_root))
        info = self.work.lstat()
        self.identity = info.st_dev, info.st_ino
        self.parents = _fts_parent_identity(self.work)
        self.owned: list[_FtsOwnedLeaf] = []
        _fts_check_parents(parents)
        if _is_reparse_or_symlink(self.work) or not stat.S_ISDIR(info.st_mode):
            raise SyncError("FTS private directory alias/kind")
        os.chmod(self.work, 0o700)
        try:
            self.source = self.new("private-source.sqlite")
            self.prototype = self.new("prototype.sqlite")
            self.output = self.new("logical.sqlite")
            self.effect: dict[str, Any] | None = None
        except BaseException as error:
            self.abort(interrupted=not isinstance(error, Exception))
            raise

    def new(self, name: str) -> Path:
        if Path(name).name != name or "/" in name or "\\" in name:
            raise SyncError("FTS private leaf identity")
        return _fts_create_private_file(self.work / name, self.owned).path

    def check_config(self) -> None:
        self.paths.check(self.sync.config)
        key_file = (Path(self.sync.config.key_file).expanduser().resolve()
                    if self.sync.config.key_file is not None else None)
        if key_file != self.key_file:
            raise SyncError("Publication key path changed during preparation")

    def check(self) -> None:
        self.check_config()
        self.budget.check()
        _fts_check_parents(self.parents)
        info = self.work.lstat()
        if (info.st_dev, info.st_ino) != self.identity or _is_reparse_or_symlink(self.work):
            raise SyncError("FTS private owner drift")
        for leaf in self.owned:
            _fts_owned_check(leaf, self.owned)

    def prepare_live(self) -> dict[str, Any]:
        database = self.sync.config.database
        live_bound = _fts_live_bind(database)
        live = destination = None
        interrupted = False
        try:
            self.check()
            _fts_live_check(live_bound, database)
            live = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True,
                                   timeout=self.budget.limits.busy_milliseconds / 1000)
            _fts_profile(live, self.contract.sqlite)
            live.set_progress_handler(lambda: int(time.monotonic() >= self.budget.until), 1000)
            live.execute("BEGIN")
            pages = live.execute("PRAGMA page_count").fetchone()[0]
            page_size = live.execute("PRAGMA page_size").fetchone()[0]
            if pages * page_size > self.budget.limits.snapshot_bytes:
                raise SyncError("FTS live backup file budget exceeded")
            destination = self.budget.connect(self.source, writable=True)
            _fts_live_check(live_bound, database)
            def progress(status: int, remaining: int, total: int) -> None:
                self.budget.check()
                if total * page_size > self.budget.limits.snapshot_bytes:
                    raise SyncError("FTS backup file budget exceeded")
            live.backup(destination, pages=256, progress=progress)
            _fts_live_check(live_bound, database)
            destination.execute("PRAGMA journal_mode=DELETE")
            destination.commit()
        except BaseException as error:
            interrupted = not isinstance(error, Exception)
            raise
        finally:
            _fts_close_connections((destination, live), interrupted=interrupted)
        _fts_live_check(live_bound, database, closed=True)
        return self.prepare()

    def prepare(self) -> dict[str, Any]:
        self.check()
        _fts_file_identity(self.source)
        _fts_validate_input(self, self.source, index=False)
        self.effect = _fts_prepare(self.source, self.output, self.prototype,
                                   self.contract, self.patterns, budget=self.budget)
        self.check()
        if self.output.stat().st_size > self.budget.limits.output_bytes:
            raise SyncError("FTS output budget exceeded")
        return self.effect

    def cleanup(self) -> None:
        if self.work is not None:
            _fts_cleanup(self.work, self.identity, self.parents, self.owned)
            self.work = None

    def abort(self, *, interrupted: bool = False) -> None:
        failed = False
        for leaf in tuple(reversed(self.owned)):
            if self.work is not None and leaf.path.parent == self.work:
                continue
            try:
                _fts_remove_owned(leaf, self.owned)
            except Exception:
                failed = True
        try:
            self.cleanup()
        except Exception:
            failed = True
        if failed and not interrupted:
            raise SyncError("FTS owner cleanup retained artifacts")


class _FtsBoundInput:
    """Retain the actual authenticated file FD, not a portable pathname proof."""
    def __init__(self, path: Path, maximum: int) -> None:
        self.path, self.maximum = path, maximum
        self.identity = _fts_file_identity(path)
        self.parents = _fts_parent_identity(path)
        if self.identity[2] > maximum:
            raise SyncError("FTS input budget exceeded")
        self.fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        try:
            self.check()
        except BaseException:
            os.close(self.fd)
            raise

    def check(self) -> None:
        _fts_check_parents(self.parents)
        info = os.fstat(self.fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != self.identity
                or _fts_file_identity(self.path) != self.identity):
            raise SyncError("FTS retained input FD drift")

    def chunks(self, budget: _FtsBudget) -> Iterable[bytes]:
        os.lseek(self.fd, 0, os.SEEK_SET)
        count = 0
        while True:
            budget.check()
            block = os.read(self.fd, min(1048576, self.maximum + 1 - count))
            if not block:
                break
            count += len(block)
            if count > self.maximum:
                raise SyncError("FTS input cap exceeded")
            yield block
        self.check()

    def read(self, budget: _FtsBudget) -> bytes:
        return b"".join(self.chunks(budget))

    def close(self) -> None:
        os.close(self.fd)


_FTS_DIRECT_MANIFEST_KEYS = frozenset({
    "protocol", "format", "namespace", "node_id", "created_at", "snapshot",
    "sha256", "size", "contract_id", "source_sha256", "source_schema_sha256",
    "schema_sha256", "relations", "sqlite", "fts", "user_version",
    "redacted_tables", "foreign_keys_sha256", "coverage", "effect_sha256", "auth",
})
_FTS_REPLICA_MANIFEST_KEYS = _FTS_DIRECT_MANIFEST_KEYS | frozenset({
    "republica_protocol", "mode", "payload_sha256", "payload_size",
    "clean_sha256", "clean_size", "encryption", "compression", "payload",
})
_FTS_AUTH_KEYS = frozenset({"version", "algorithm", "key_id", "sender", "trust_source", "signature"})


def _fts_json_shape(value: Any) -> None:
    """Reject non-JSON and nonfinite values anywhere, including the auth object."""
    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise SyncError("FTS JSON key type")
            _fts_json_shape(item)
    elif kind is list:
        for item in value:
            _fts_json_shape(item)
    elif kind is float:
        if not math.isfinite(value):
            raise SyncError("FTS nonfinite JSON value")
    elif kind not in (str, int, bool, type(None)):
        raise SyncError("FTS JSON scalar type")


def _fts_json_exact_equal(left: Any, right: Any) -> bool:
    """Local normalized authority is compared without Python's numeric coercions."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return (left.keys() == right.keys()
                and all(_fts_json_exact_equal(left[key], right[key]) for key in left))
    if type(left) is list:
        return (len(left) == len(right)
                and all(_fts_json_exact_equal(a, b) for a, b in zip(left, right)))
    return left == right


def _fts_json(data: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in values:
            if key in result:
                raise SyncError("FTS duplicate JSON key")
            result[key] = value
        return result
    def invalid(_: str) -> Any:
        raise SyncError("FTS nonfinite JSON value")
    value = json.loads(data.decode("utf8", "strict"), object_pairs_hook=pairs, parse_constant=invalid)
    if type(value) is not dict:
        raise SyncError("FTS manifest object required")
    _fts_json_shape(value)
    return value


def _fts_read_json(path: Path, limits: FtsReceiveLimits) -> tuple[dict[str, Any], str]:
    budget = _FtsBudget(limits)
    bound = _FtsBoundInput(path, limits.manifest_bytes)
    try:
        data = bound.read(budget)
        value = _fts_json(data)
        bound.check()
        return value, hashlib.sha256(data).hexdigest()
    finally:
        bound.close()


def _fts_effect_projection(effect: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("format", "contract_id", "source_schema_sha256", "schema_sha256", "relations",
            "sqlite", "fts", "user_version", "redacted_tables", "foreign_keys_sha256", "coverage")
    if any(key not in effect for key in keys):
        raise SyncError("FTS effect incomplete")
    return {key: effect[key] for key in keys}


def _fts_json_normalized(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":"), allow_nan=False))


def _fts_authenticate_manifest(sync: TransitSync, value: dict[str, Any],
                               *, replica: bool = False) -> None:
    contract = sync._fts_contract
    if type(contract) is not FtsSnapshotContract or type(sync.authenticator) is not HMACSnapshotAuthenticator:
        raise SyncError("FTS local contract/HMAC required")
    _fts_json_shape(value)
    expected_keys = _FTS_REPLICA_MANIFEST_KEYS if replica else _FTS_DIRECT_MANIFEST_KEYS
    if type(value) is not dict or value.keys() != expected_keys:
        raise SyncError("FTS exact manifest fields required")
    if type(value["protocol"]) is not int or value["protocol"] != 2 or value["format"] != FTS_SNAPSHOT_FORMAT:
        raise SyncError("FTS incompatible protocol")
    auth = value["auth"]
    if type(auth) is not dict or auth.keys() != _FTS_AUTH_KEYS:
        raise SyncError("FTS exact authentication fields required")
    if (type(auth["version"]) is not int or auth["version"] != AUTH_PROTOCOL_VERSION
            or any(type(auth[k]) is not str for k in _FTS_AUTH_KEYS-{"version"})
            or re.fullmatch(r"[0-9a-f]{64}", auth["signature"]) is None):
        raise SyncError("FTS authentication field types")
    # Structural validation does not confer trust. The unchanged local HMAC
    # key-ring, sender and trust_source verification remains mandatory.
    sync.authenticator.verify(value, auth)  # All fields except auth are authenticated.
    if replica:
        fixed = {"republica_protocol": 2, "mode": "replica", "payload": FTS_SNAPSHOT_FORMAT,
                 "encryption": "fernet", "compression": "gzip"}
        if any(not _fts_json_exact_equal(value[k], v) for k, v in fixed.items()):
            raise SyncError("FTS exact replica transport profile")
        for key, maximum in (("payload_size",sync._fts_limits.compressed_bytes),
                             ("clean_size",sync._fts_limits.snapshot_bytes)):
            if type(value[key]) is not int or not 0 < value[key] <= maximum:
                raise SyncError("FTS replica signed size budget")
        for key in ("payload_sha256", "clean_sha256"):
            if type(value[key]) is not str or re.fullmatch(r"[0-9a-f]{64}",value[key]) is None:
                raise SyncError("FTS replica digest type")
    required = ("namespace", "node_id", "created_at", "snapshot", "sha256", "size",
                "source_sha256", "effect_sha256", "relations", "coverage")
    if any(key not in value for key in required):
        raise SyncError("FTS manifest incomplete")
    for key in ("namespace", "node_id", "created_at", "snapshot"):
        if type(value[key]) is not str:
            raise SyncError("FTS identity type")
    if value["namespace"] != sync.config.namespace or _safe_identifier(value["node_id"], "node") != value["node_id"]:
        raise SyncError("FTS identity mismatch")
    _parse_utc_token(value["created_at"])
    expected = (_snapshot_filename(value["namespace"], value["node_id"], value["created_at"])
                if not replica else f"{value['namespace']}__{value['node_id']}__{value['created_at']}.republica")
    if value["snapshot"] != expected:
        raise SyncError("FTS snapshot basename mismatch")
    for key in ("sha256", "source_sha256", "effect_sha256", "source_schema_sha256", "schema_sha256", "foreign_keys_sha256"):
        if type(value.get(key)) is not str or re.fullmatch(r"[0-9a-f]{64}", value[key]) is None:
            raise SyncError("FTS manifest digest")
    maximum = sync._fts_limits.cipher_bytes if replica else sync._fts_limits.snapshot_bytes
    if type(value["size"]) is not int or not 0 < value["size"] <= maximum:
        raise SyncError("FTS signed size budget")
    pinned = {"contract_id": contract.contract_id,
              "format": FTS_SNAPSHOT_FORMAT,
              "source_schema_sha256": _fts_schema_digest(contract.schema_objects),
              "schema_sha256": _fts_schema_digest(contract.schema_objects),
              "sqlite": asdict(contract.sqlite), "fts": [asdict(d) for d in contract.descriptors],
              "user_version": contract.user_version, "redacted_tables": list(contract.redacted_tables),
              "foreign_keys_sha256": _fts_relation(contract.foreign_key_violations)[1],
              "coverage": "reconstructed-current-logical-content-and-schema"}
    if any(not _fts_json_exact_equal(value[k], _fts_json_normalized(v)) for k, v in pinned.items()):
        raise SyncError("FTS signed local profile mismatch")
    relations = value["relations"]
    if type(relations) is not list or not relations or len(relations) > sync._fts_limits.relations:
        raise SyncError("FTS relation budget")
    seen = set()
    for row in relations:
        if type(row) is not dict or set(row) != {"kind", "name", "count", "sha256"}:
            raise SyncError("FTS relation shape")
        if type(row["kind"]) is not str or row["kind"] not in ("ordinary", "fts") or type(row["name"]) is not str or not row["name"] or "\x00" in row["name"]:
            raise SyncError("FTS relation identity")
        key = row["kind"], row["name"]
        if key in seen or type(row["count"]) is not int or not 0 <= row["count"] <= sync._fts_limits.rows or type(row["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None:
            raise SyncError("FTS relation count/digest/duplicate")
        seen.add(key)
    if relations != sorted(relations, key=lambda r: (r["kind"], r["name"])):
        raise SyncError("FTS relation order")
    if {name for kind, name in seen if kind == "fts"} != {d.name for d in contract.descriptors}:
        raise SyncError("FTS descriptor relation set")
    original_effect = {k: value[k] for k in (*_fts_effect_projection(value), "source_sha256")}
    # effect_sha256 commits only the original A effect, not transport metadata.
    digest = hashlib.sha256(json.dumps(original_effect, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if digest != value["effect_sha256"]:
        raise SyncError("FTS effect digest mismatch")


def _fts_manifest(sync: TransitSync, path: Path, *, replica: bool = False) -> tuple[dict[str, Any], str]:
    _assert_transit_regular_file(path, sync.config.transit if not replica else path.parent, "FTS manifest")
    if replica and path.parent.parent.resolve() != sync.config.transit.resolve():
        raise SyncError("FTS replica manifest parent")
    value, digest = _fts_read_json(path, sync._fts_limits)
    _fts_authenticate_manifest(sync, value, replica=replica)
    if path.name != value["snapshot"] + ".json" or (replica and path.parent.name != value["node_id"]):
        raise SyncError("FTS manifest path identity")
    _fts_file_identity(path.parent / value["snapshot"])
    return value, digest


def _fts_write_owned(owner: _FtsPreparedArtifactOwner, path: Path,
                     chunks: Iterable[bytes], *, maximum: int,
                     expected_hash: str | None = None, expected_size: int | None = None) -> tuple[int, str]:
    leaf = next((v for v in owner.owned if v.path == path), None)
    if leaf is None:
        raise SyncError("FTS write has no leaf authority")
    _fts_owned_check(leaf, owner.owned)
    fd = os.open(path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
    count, digest = 0, hashlib.sha256()
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (leaf.device, leaf.inode) or info.st_nlink != 1:
            raise SyncError("FTS owned write FD mismatch")
        _fts_owned_check(leaf, owner.owned)
        os.ftruncate(fd, 0)
        with os.fdopen(fd, "wb", buffering=0) as stream:
            fd = -1
            for chunk in chunks:
                owner.budget.check()
                count += len(chunk)
                if count > maximum:
                    raise SyncError("FTS owned write budget")
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd != -1:
            os.close(fd)
    _fts_owned_check(leaf, owner.owned)
    actual = digest.hexdigest()
    if ((expected_hash is not None and actual != expected_hash)
            or (expected_size is not None and count != expected_size)
            or _sha256(path) != actual):
        raise SyncError("FTS owned stream commitment mismatch")
    return count, actual


def _fts_validate_input(owner: _FtsPreparedArtifactOwner, path: Path,
                        *, index: bool) -> dict[str, Any]:
    """Typed prototype proof and bounded reads before reconstruction.

    Only an owned copy is opened. Received rank1 verification is rolled back;
    neither sender DDL nor a shadow-name heuristic supplies executable authority.
    """
    owner.check()
    contract, budget = owner.contract, owner.budget
    identity, digest = _fts_file_identity(path), _sha256(path)
    proof_path = owner.new("input-proof-" + str(len(owner.owned)) + ".sqlite")
    source = prototype = None
    interrupted = False
    try:
        source = budget.connect(path, writable=index)
        _fts_profile(source, contract.sqlite)
        if _fts_schema(source) != contract.schema_objects or source.execute("PRAGMA user_version").fetchone()[0] != contract.user_version:
            raise SyncError("FTS receiver local schema mismatch")
        kinds = {r[1]: r[2] for r in source.execute("PRAGMA main.table_list") if r[0] == "main"}
        prototype = budget.connect(proof_path, writable=True)
        prototype.execute("PRAGMA journal_mode=DELETE")
        prototype.execute("PRAGMA foreign_keys=OFF")
        _fts_profile(prototype, contract.sqlite)
        generated = _fts_construct(prototype, contract, kinds, delayed=True)
        prototype.commit()
        layout = _fts_layout(prototype)
        if _fts_layout(source) != layout:
            raise SyncError("FTS receiver prototype/layout mismatch")
        technical = frozenset(n for names in generated.values() for n in names)
        if {n for n, k in kinds.items() if k in ("virtual", "shadow")} != technical:
            raise SyncError("FTS receiver unbound technical object")
        inventory = _fts_plain_inventory(source, technical, layout)
        if len(inventory) + len(contract.descriptors) > budget.limits.relations:
            raise SyncError("FTS receiver relation budget")
        for name, columns, _ in inventory:
            if name not in contract.redacted_tables:
                _fts_relation(budget.rows(_fts_rows(source, name, columns)))
        for d in contract.descriptors:
            if _fts_config(source, generated[d.name]) != d.configuration:
                raise SyncError("FTS receiver config mismatch")
            if d.name not in contract.redacted_tables and d.content_table not in contract.redacted_tables:
                _fts_relation(budget.rows(_fts_logical_rows(source, d, inventory)))
        fk = tuple(sorted(tuple(r) for r in source.execute("PRAGMA foreign_key_check")))
        if fk != contract.foreign_key_violations:
            raise SyncError("FTS receiver FK fingerprint mismatch")
        relations = _fts_scan_values(source, contract, inventory, generated, owner.patterns, source=True)
        if index:
            source.execute("BEGIN IMMEDIATE")
            _fts_integrity(source, contract.descriptors)
            source.rollback()
        return {"layout": layout, "generated": generated, "inventory": inventory,
                "relations": relations, "foreign_keys": fk}
    except BaseException as error:
        interrupted = not isinstance(error, Exception)
        raise
    finally:
        _fts_close_connections((prototype, source), interrupted=interrupted)
        if not interrupted and (_fts_file_identity(path) != identity or _sha256(path) != digest):
            raise SyncError("FTS receiver integrity verification changed input")


def _fts_receive_snapshot(sync: TransitSync, snapshot: _FtsSnapshot,
                          budget: _FtsBudget | None = None) -> tuple[_FtsPreparedArtifactOwner, FtsVerificationReport]:
    budget = budget or _FtsBudget(sync._fts_limits)
    owner = None
    interrupted = False
    try:
        manifest, manifest_digest = _fts_manifest(sync, snapshot.manifest_path)
        if manifest_digest != snapshot.manifest_sha256 or manifest["sha256"] != snapshot.sha256:
            raise SyncError("FTS selected metadata drift")
        bound = _FtsBoundInput(snapshot.path, budget.limits.snapshot_bytes)
        try:
            owner = _FtsPreparedArtifactOwner(sync, budget)
            _fts_write_owned(owner, owner.source, bound.chunks(budget), maximum=budget.limits.snapshot_bytes,
                             expected_hash=manifest["sha256"], expected_size=manifest["size"])
            bound.check()
            report = _fts_finish_received(owner, manifest)
            bound.check()
            final_manifest, final_digest = _fts_manifest(sync, snapshot.manifest_path)
            if final_digest != manifest_digest or final_manifest != manifest:
                raise SyncError("FTS authenticated manifest changed")
        finally:
            bound.close()
        return owner, report
    except BaseException as error:
        interrupted = not isinstance(error, Exception)
        if owner is not None:
            owner.abort(interrupted=interrupted)
        raise


def _fts_call(phase: str, operation: Any) -> Any:
    failed, partial, result = False, False, None
    try:
        result = operation()
    except FtsCommittedPartialError:
        failed, partial = True, True
    except Exception:
        failed = True
    if failed:
        if partial:
            raise FtsCommittedPartialError("FTS operation incomplete [committed-partial]") from None
        # Outside except: public errors carry no raw SQLite/OS cause/context.
        raise SyncError("FTS operation refused [" + phase + "]") from None
    return result


def _fts_read_snapshot(sync: TransitSync, path: Path, verify: bool) -> _FtsSnapshot | None:
    def read() -> _FtsSnapshot | None:
        value, _ = _fts_read_json(path, sync._fts_limits)
        if value.get("protocol") == 1 and type(value.get("protocol")) is int:
            raise SyncError("FTS selected reader requires explicit format2")
        # Inactive/default protocol1 follows its unchanged original reader;
        # the explicitly selected typed reader never falls into unbounded
        # legacy decoding or mistakes an old snapshot for receiver authority.
        value, digest = _fts_manifest(sync, path)
        snapshot = _FtsSnapshot(path.parent / value["snapshot"], path, value["node_id"],
            value["namespace"], value["created_at"], value["sha256"], value["size"], digest, verify)
        if verify:
            owner, _ = _fts_receive_snapshot(sync, snapshot)
            owner.cleanup()  # No transferable private coverage proof survives.
        return snapshot
    return _fts_call("receiver-manifest", read)


def _fts_verify(sync: TransitSync) -> dict[str, Any]:
    def verify() -> dict[str, Any]:
        owner = _FtsPreparedArtifactOwner(sync, _FtsBudget(sync._fts_limits))
        try:
            effect = owner.prepare_live()
            owner.cleanup()
        except BaseException as error:
            owner.abort(interrupted=not isinstance(error, Exception))
            raise
        reports = []
        for snapshot in sync.snapshots(verify=False):
            if not isinstance(snapshot, _FtsSnapshot):
                raise SyncError("FTS verification requires explicit format2 payload")
            remote, report = _fts_receive_snapshot(sync, snapshot)
            try:
                remote.cleanup()
            except BaseException as error:
                remote.abort(interrupted=not isinstance(error, Exception))
                raise
            reports.append(report.as_dict())
        return {"database": "verified-private-logical-backup", "database_effect_sha256": effect["effect_sha256"],
                "verified_snapshots": len(reports), "format": FTS_SNAPSHOT_FORMAT,
                "payload_checked": True, "reports": reports}
    return _fts_call("verify", verify)


class _FtsBudgetCursor:
    def __init__(self, cursor: sqlite3.Cursor, budget: _FtsBudget) -> None:
        self.cursor, self.budget = cursor, budget
    def __iter__(self) -> Any:
        count = 0
        for row in self.cursor:
            self.budget.check()
            count += 1
            if count > self.budget.limits.rows:
                raise SyncError("FTS reference row budget exceeded")
            for value in row:
                _fts_frame(value)
                if type(value) is str and len(value.encode("utf8"))>self.budget.limits.text_bytes:
                    raise SyncError("FTS reference text budget exceeded")
            yield row
    def fetchall(self) -> list[Any]:
        return list(iter(self))
    def fetchone(self) -> Any:
        self.budget.check()
        row = self.cursor.fetchone()
        if row is not None:
            for value in row:
                _fts_frame(value)
                if type(value) is str and len(value.encode("utf8")) > self.budget.limits.text_bytes:
                    raise SyncError("FTS reference field budget exceeded")
        return row
    @property
    def rowcount(self) -> int:
        return self.cursor.rowcount


class _FtsTableCursor:
    def __init__(self, names: Iterable[str]) -> None:
        self.rows = [(name,) for name in sorted(names)]
    def fetchall(self) -> list[tuple[str]]:
        return list(self.rows)
    def __iter__(self) -> Any:
        return iter(self.rows)


def _fts_identifier_list(value: str) -> tuple[str, ...]:
    parts, position = [], 0
    for match in re.finditer(r'"((?:[^"]|"")*)"|([A-Za-z_][A-Za-z_0-9]*)', value):
        if value[position:match.start()].strip() not in ("", ","):
            raise SyncError("FTS observation identifier grammar")
        parts.append(match.group(1).replace('""', '"') if match.group(1) is not None else match.group(2))
        position = match.end()
    if value[position:].strip() or not parts:
        raise SyncError("FTS observation identifier list")
    return tuple(parts)


def _fts_key_rows(c: sqlite3.Connection, table: str, budget: _FtsBudget) -> tuple[tuple[str, ...], tuple[str, ...], dict[tuple[Any, ...], tuple[Any, ...]]]:
    info = c.execute(f"PRAGMA main.table_xinfo({_quote_identifier(table)})").fetchall()
    columns = tuple(r[1] for r in info)
    table_meta = next(r for r in c.execute("PRAGMA main.table_list") if r[0]=="main" and r[1]==table)
    indices = {r[1] for r in c.execute(f"PRAGMA main.index_list({_quote_identifier(table)})")}
    selector = _secret_scan_rowid(c, table, table_meta[4], info, indices)
    if selector is not None:
        columns += (selector,)
    keys = tuple(r[1] for r in sorted(info, key=lambda r: r[5]) if r[5] > 0)
    if not keys:
        raise SyncError("FTS merge requires actual primary-key authority")
    rows = {}
    for row in budget.rows(_fts_rows(c, table, columns)):
        key = tuple(row[columns.index(k)] for k in keys)
        if any(v is None for v in key) or key in rows:
            raise SyncError("FTS merge ambiguous primary key")
        rows[key] = row
    return columns, keys, rows


def _fts_assignment_columns(value: str, separator: str,
                            *, unquoted_columns: tuple[str, ...] = ()) -> tuple[str, ...]:
    pattern = re.compile(r'"((?:[^"]|"")*)" = \?')
    names, position = [], 0
    while position < len(value):
        match = pattern.match(value, position)
        if match is not None:
            name = match.group(1).replace('""', '"')
        else:
            # Only the exact locally bound reference catalog UPDATE calls this
            # branch; ordinary DML retains its original quoted-only grammar.
            match = re.compile(r'([A-Za-z_][A-Za-z_0-9]*) = \?').match(value, position)
            if match is None or match.group(1) not in unquoted_columns:
                raise SyncError("FTS reference assignment grammar")
            name = match.group(1)
        names.append(name)
        position = match.end()
        if position == len(value):
            break
        if not value.startswith(separator, position):
            raise SyncError("FTS reference assignment separator")
        position += len(separator)
    if not names or len(set(names)) != len(names):
        raise SyncError("FTS reference assignment columns")
    return tuple(names)


class _FtsObservedConnection:
    """Reference policy picks winners; this seam checks its actual SQL effects.

    It is not another conflict algorithm. Only the exact DML forms emitted by
    the unchanged reference policies are admitted; ignored mutations refuse.
    """
    def __init__(self, connection: sqlite3.Connection, names: set[str],
                 budget: _FtsBudget, permitted: Mapping[str, frozenset[str]] | None = None,
                 *, observe: bool = False, reference_catalog: str | None = None) -> None:
        if reference_catalog is not None and (type(reference_catalog) is not str or reference_catalog not in names):
            raise SyncError("FTS reference catalog authority")
        self.reference_catalog = reference_catalog
        self.connection, self.names, self.budget = connection, names, budget
        self.permitted = permitted or {}
        self.observe = observe
        self.expected = {name: _fts_key_rows(connection, name, budget) for name in names} if observe else {}
        self.inserted_tables: set[str] = set()

    @property
    def row_factory(self) -> Any:
        return self.connection.row_factory
    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self.connection.row_factory = value

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        self.budget.check()
        if sql == "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'":
            return _FtsTableCursor(self.names)
        mutation = re.match(r"^(INSERT INTO|UPDATE|DELETE FROM)\s+", sql)
        if not self.observe or mutation is None:
            return _FtsBudgetCursor(self.connection.execute(sql, params), self.budget)
        operation = mutation.group(1)
        table = next((name for name in self.names if sql[mutation.end():].startswith(_quote_identifier(name)) and sql[mutation.end()+len(_quote_identifier(name)):].startswith(" ")), None)
        if table is None:
            raise SyncError("FTS mutation outside typed table inventory")
        columns, keys, expected_rows = self.expected[table]
        tail = sql[mutation.end()+len(_quote_identifier(table)):].strip()
        changed: dict[str, Any] = {}
        if operation == "INSERT INTO":
            match = re.fullmatch(r"\((.*)\)\s+VALUES\s+\((.*)\)", tail)
            if match is None or any(v.strip() != "?" for v in match.group(2).split(",")):
                raise SyncError("FTS insert observation grammar")
            supplied = _fts_identifier_list(match.group(1))
            if len(supplied) != len(params) or len(set(supplied)) != len(supplied):
                raise SyncError("FTS inserted columns mismatch")
            changed = dict(zip(supplied, params))
            key = tuple(changed[k] for k in keys)
            if key in expected_rows:
                raise SyncError("FTS unexpected insert target")
        elif operation == "UPDATE":
            if not tail.startswith("SET ") or " WHERE " not in tail:
                raise SyncError("FTS update observation grammar")
            if (table == self.reference_catalog
                    and tail == "SET deleted_at = ? WHERE table_name = ? AND primary_key = ?"):
                # Admit precisely the original TombstoneMergePolicy UPDATE on
                # its actual locally bound catalog, never general bare SQL.
                supplied = _fts_assignment_columns("deleted_at = ?", ", ",
                                                   unquoted_columns=("deleted_at",))
                where_columns = _fts_assignment_columns("table_name = ? AND primary_key = ?", " AND ",
                                                        unquoted_columns=("table_name", "primary_key"))
            else:
                split = re.search(r'(?:"(?:[^"]|"")*" = \?)(?:, "(?:[^"]|"")*" = \?)* WHERE ', tail[4:])
                if split is None or split.start()!=0:
                    raise SyncError("FTS update boundary grammar")
                boundary = split.end()-len(" WHERE ")
                setters, where = tail[4:4+boundary], tail[4+boundary+len(" WHERE "):]
                supplied = _fts_assignment_columns(setters, ", ")
                where_columns = _fts_assignment_columns(where, " AND ")
            if where_columns != keys:
                raise SyncError("FTS update key grammar")
            if len(params) != len(supplied)+len(keys):
                raise SyncError("FTS update parameter count")
            changed = dict(zip(supplied, params[:len(supplied)]))
            key = tuple(params[len(supplied):])
            if key not in expected_rows:
                raise SyncError("FTS update target missing")
        else:
            if not tail.startswith("WHERE "):
                raise SyncError("FTS delete observation grammar")
            if _fts_assignment_columns(tail[6:], " AND ") != keys or len(params) != len(keys):
                raise SyncError("FTS delete key grammar")
            key = tuple(params)
            if key not in expected_rows:
                raise SyncError("FTS delete target missing")
        cursor = self.connection.execute(sql, params)
        if cursor.rowcount != 1:
            raise SyncError("FTS reference DML ignored or ambiguous")
        where = " AND ".join(_quote_identifier(k)+" = ?" for k in keys)
        actual = self.connection.execute(f"SELECT {','.join(_quote_identifier(n) for n in columns)} FROM {_quote_identifier(table)} WHERE {where}", key).fetchall()
        if operation == "DELETE FROM":
            if actual:
                raise SyncError("FTS deletion has no actual effect")
            del expected_rows[key]
        else:
            if len(actual) != 1:
                raise SyncError("FTS mutation has no unique actual row")
            row = tuple(actual[0])
            generated = {r[1] for r in self.connection.execute(f"PRAGMA main.table_xinfo({_quote_identifier(table)})") if r[6] in (2, 3)}
            permitted = self.permitted.get(table, frozenset())
            if any(row[columns.index(k)] != v for k, v in changed.items() if k not in permitted):
                raise SyncError("FTS chosen mutation values differ")
            if operation == "UPDATE":
                previous = expected_rows[key]
                if any(row[i] != previous[i] for i, name in enumerate(columns)
                       if name not in changed and name not in generated and name not in permitted):
                    raise SyncError("FTS unpermitted trigger target effect")
            expected_rows[key] = row
            if operation == "INSERT INTO":
                self.inserted_tables.add(table)
        return cursor

    def verify(self) -> None:
        for table, expected in self.expected.items():
            actual = _fts_key_rows(self.connection, table, self.budget)
            if actual != expected:
                raise SyncError("FTS nonchosen row effect")


@dataclass(slots=True)
class FtsMergeReport(MergeReport):
    contract_id: str = ""
    before_relations_sha256: str = ""
    after_relations_sha256: str = ""
    received_sha256: str = ""
    receiver_effect_sha256: str = ""
    rebuilt_indexes: list[str] = field(default_factory=list)
    committed: bool = False
    application_seal_required: bool = True


class FtsCommittedPartialError(SyncError):
    """Destination commit succeeded, subsequent verification/state did not."""
    committed = True


def _fts_bound_merge(sync: TransitSync, owner: _FtsPreparedArtifactOwner,
                     connection: sqlite3.Connection) -> tuple[set[str], dict[str, frozenset[str]], dict[str, Any]]:
    contract, merge = sync._fts_contract, sync._fts_merge_contract
    if type(merge) is not FtsMergeContract or merge.contract_id != contract.contract_id:
        raise SyncError("FTS direct merge requires local application authority")
    if type(sync.policy) not in (TimestampMergePolicy, TombstoneMergePolicy):
        raise SyncError("FTS policy observation requires source-bound reference policy")
    _fts_profile(connection, contract.sqlite)
    if _fts_schema(connection) != contract.schema_objects or connection.execute("PRAGMA user_version").fetchone()[0] != contract.user_version:
        raise SyncError("FTS destination schema/profile mismatch")
    proof = _fts_validate_input(owner, owner.output, index=True)
    if _fts_layout(connection) != proof["layout"]:
        raise SyncError("FTS destination complete layout mismatch")
    technical = frozenset(n for v in proof["generated"].values() for n in v)
    inventory = _fts_plain_inventory(connection, technical, proof["layout"])
    ordinary = {name for name, _, _ in inventory if name != "sqlite_sequence"}
    if set(merge.merge_tables) | set(merge.preserve_tables) != ordinary or set(merge.merge_tables) & set(sync.policy.exclude_tables):
        raise SyncError("FTS ordinary merge/preserve profile incomplete")
    permitted: dict[str, frozenset[str]] = {}
    objects = {(o.type, o.name): o for o in contract.schema_objects}
    for effect in merge.trigger_effects:
        obj = objects.get(("trigger", effect.trigger))
        if obj is None or obj.sql is None or obj.table_name != effect.table or hashlib.sha256(obj.sql.encode()).hexdigest() != effect.trigger_sql_sha256 or effect.table not in merge.merge_tables:
            raise SyncError("FTS trigger effect source mismatch")
        columns = {r[1] for r in connection.execute(f"PRAGMA main.table_xinfo({_quote_identifier(effect.table)})")}
        keys = {r[1] for r in connection.execute(f"PRAGMA main.table_info({_quote_identifier(effect.table)})") if r[5]}
        if not set(effect.columns) <= columns or set(effect.columns) & keys:
            raise SyncError("FTS trigger effect column authority")
        permitted[effect.table] = permitted.get(effect.table, frozenset()) | frozenset(effect.columns)
    internal = {d.name for d in contract.descriptors if d.content_table is None}
    if {b.table for b in merge.internal} != internal:
        raise SyncError("FTS internal merge authority incomplete")
    for binding in merge.internal:
        descriptor = next(d for d in contract.descriptors if d.name == binding.table)
        fields = {c.name for c in descriptor.columns}
        if (type(sync.policy) is not TombstoneMergePolicy
                or binding.tombstone_table != sync.policy.tombstone_table
                or binding.tombstone_table not in merge.merge_tables
                or binding.timestamp_column not in fields
                or next((v for v in sync.policy.timestamp_columns if v in fields), None) != binding.timestamp_column):
            raise SyncError("FTS internal original policy/catalog authority mismatch")
    for table in merge.merge_tables:
        columns, keys, _ = _fts_key_rows(connection, table, owner.budget)
        if type(sync.policy) is TombstoneMergePolicy and table == sync.policy.tombstone_table:
            if keys != ("table_name", "primary_key") or not {"table_name","primary_key","deleted_at"} <= set(columns):
                raise SyncError("FTS original tombstone catalog profile mismatch")
        elif not any(value in columns for value in sync.policy.timestamp_columns):
            raise SyncError("FTS selected table lacks original timestamp authority")
    if merge.internal:
        catalog = sync.policy.tombstone_table
        internal_names = {b.table for b in merge.internal}
        for name, encoded in ((r[0],r[1]) for r in owner.budget.rows(connection.execute(
                f"SELECT table_name,primary_key FROM {_quote_identifier(catalog)}"))):
            if name in internal_names:
                key = json.loads(encoded)
                if type(key) is not list or len(key)!=1 or type(key[0]) is not int or not -(1<<63)<=key[0]<(1<<63) or sync.policy._canonical_key(key)!=encoded:
                    raise SyncError("FTS internal canonical docid tombstone authority mismatch")
    return set(merge.merge_tables), permitted, proof


def _fts_state_relations(connection: sqlite3.Connection, contract: FtsSnapshotContract,
                         proof: Mapping[str, Any], budget: _FtsBudget) -> dict[tuple[str, str], tuple[int, str]]:
    technical = frozenset(n for values in proof["generated"].values() for n in values)
    inventory = _fts_plain_inventory(connection, technical, proof["layout"])
    relations = {("ordinary", name): _fts_relation(budget.rows(_fts_rows(connection, name, columns)))
                 for name, columns, _ in inventory}
    for descriptor in contract.descriptors:
        if _fts_config(connection, proof["generated"][descriptor.name]) != descriptor.configuration:
            raise SyncError("FTS destination config drift")
        relations[("fts", descriptor.name)] = _fts_relation(budget.rows(_fts_logical_rows(connection, descriptor, inventory)))
    return relations


def _fts_relations_digest(value: Mapping[tuple[str, str], tuple[int, str]]) -> str:
    return _fts_relation((kind, name, count, digest) for (kind, name), (count, digest) in sorted(value.items()))[1]


def _fts_internal_mirrors(sync: TransitSync, owner: _FtsPreparedArtifactOwner,
                          local: sqlite3.Connection, remote: sqlite3.Connection,
                          snapshot: Snapshot, permitted: Mapping[str, frozenset[str]]) -> MergeReport:
    """Original FTS names and canonical [docid] stay under the original policy."""
    aggregate = MergeReport(snapshot.path.name, snapshot.node_id)
    if not sync._fts_merge_contract.internal:
        return aggregate
    catalog = sync.policy.tombstone_table
    obj = next((o for o in owner.contract.schema_objects if o.type == "table" and o.name == catalog), None)
    if obj is None or obj.sql is None:
        raise SyncError("FTS actual tombstone catalog DDL missing")
    paths = (owner.new("internal-local.sqlite"), owner.new("internal-remote.sqlite"))
    left = right = None
    interrupted = False
    try:
        left, right = (owner.budget.connect(path, writable=True) for path in paths)
        names = {binding.table for binding in sync._fts_merge_contract.internal} | {catalog}
        for mirror, origin in ((left, local), (right, remote)):
            mirror.execute("PRAGMA journal_mode=DELETE")
            mirror.execute("PRAGMA foreign_keys=OFF")
            mirror.execute(obj.sql)  # Exact locally authorized catalog; no rename.
            all_catalog_columns, _, _ = _fts_key_rows(origin, catalog, owner.budget)
            generated_columns = {r[1] for r in origin.execute(f"PRAGMA main.table_xinfo({_quote_identifier(catalog)})") if r[6] in (2,3)}
            catalog_columns = tuple(v for v in all_catalog_columns if v not in generated_columns)
            mirror.executemany(f"INSERT INTO {_quote_identifier(catalog)}({','.join(_quote_identifier(v) for v in catalog_columns)}) VALUES({','.join('?' for _ in catalog_columns)})",
                               owner.budget.rows(_fts_rows(origin, catalog, catalog_columns)))
            for binding in sync._fts_merge_contract.internal:
                descriptor = next(d for d in owner.contract.descriptors if d.name == binding.table)
                columns = tuple(c.name for c in descriptor.columns)
                mirror.execute(f"CREATE TABLE {_quote_identifier(binding.table)}(rowid INTEGER PRIMARY KEY,{','.join(_quote_identifier(v) for v in columns)})")
                mirror.executemany(f"INSERT INTO {_quote_identifier(binding.table)}(rowid,{','.join(_quote_identifier(v) for v in columns)}) VALUES({','.join('?' for _ in range(len(columns)+1))})",
                                   owner.budget.rows(_fts_rows(origin, binding.table, ("rowid", *columns))))
            mirror.commit()
        left.execute("BEGIN IMMEDIATE")
        observed = _FtsObservedConnection(left, names, owner.budget, observe=True,
                                          reference_catalog=catalog)
        remote_view = _FtsObservedConnection(right, names, owner.budget)
        aggregate = sync.policy.merge(observed, remote_view, snapshot)
        left.row_factory = right.row_factory = None
        observed.verify()  # Includes actual mirror catalog INSERT/UPDATE/DELETE.
        # Catalog was already merged by the original ordinary policy below.
        # Both mirrors hold that exact actual catalog. Any divergence is not
        # silently copied or rewritten into a guessed/private tombstone key.
        catalog_actual = _fts_key_rows(local, catalog, owner.budget)
        catalog_chosen = _fts_key_rows(left, catalog, owner.budget)
        if catalog_actual != catalog_chosen:
            raise SyncError("FTS internal catalog diverged from actual original-policy effects")
        for binding in sync._fts_merge_contract.internal:
            descriptor = next(d for d in owner.contract.descriptors if d.name == binding.table)
            columns = ("rowid", *(c.name for c in descriptor.columns))
            old = {row[0]: tuple(row) for row in owner.budget.rows(_fts_rows(local, binding.table, columns))}
            chosen = {row[0]: tuple(row) for row in owner.budget.rows(_fts_rows(left, binding.table, columns))}
            table = _quote_identifier(binding.table)
            for docid in sorted(set(old)-set(chosen)):
                cursor = local.execute(f"DELETE FROM {table} WHERE rowid=?", (docid,))
                if cursor.rowcount != 1 or local.execute(f"SELECT rowid FROM {table} WHERE rowid=?", (docid,)).fetchone() is not None:
                    raise SyncError("FTS internal chosen DELETE ignored")
            for docid, row in chosen.items():
                if old.get(docid) == row:
                    continue
                if docid in old:
                    cursor = local.execute(f"UPDATE {table} SET {','.join(_quote_identifier(v)+'=?' for v in columns[1:])} WHERE rowid=?", (*row[1:], docid))
                else:
                    cursor = local.execute(f"INSERT INTO {table}({','.join(_quote_identifier(v) for v in columns)}) VALUES({','.join('?' for _ in columns)})", row)
                actual = local.execute(f"SELECT {','.join(_quote_identifier(v) for v in columns)} FROM {table} WHERE rowid=?", (docid,)).fetchall()
                if cursor.rowcount != 1 or len(actual) != 1 or tuple(actual[0]) != row:
                    raise SyncError("FTS internal chosen target mutation ignored")
            actual_final = {row[0]: tuple(row) for row in owner.budget.rows(_fts_rows(local, binding.table, columns))}
            if actual_final != chosen:
                raise SyncError("FTS internal nonchosen target effects")
        left.rollback()
    except BaseException as error:
        interrupted = not isinstance(error, Exception)
        raise
    finally:
        _fts_close_connections((right, left), interrupted=interrupted)
    return aggregate


def _fts_merge_received_snapshot(sync: TransitSync, snapshot: _FtsSnapshot,
                                  committed: list[bool]) -> FtsMergeReport:
    budget = _FtsBudget(sync._fts_limits)
    owner, verification = _fts_receive_snapshot(sync, snapshot, budget)
    local = remote = reopened = None
    interrupted = False
    expected_after = None
    proof = None
    try:
        bound = _fts_live_bind(sync.config.database)
        _fts_live_check(bound, sync.config.database)
        local = budget.connect(sync.config.database, writable=True)  # mode=rw, no first copy.
        _fts_live_check(bound, sync.config.database)
        local.execute("BEGIN IMMEDIATE")
        _fts_live_check(bound, sync.config.database)
        names, permitted, proof = _fts_bound_merge(sync, owner, local)
        before_fk = tuple(sorted(tuple(r) for r in local.execute("PRAGMA foreign_key_check")))
        if before_fk != sync._fts_contract.foreign_key_violations:
            raise SyncError("FTS actual destination FK fingerprint mismatch")
        before_relations = _fts_state_relations(local, owner.contract, proof, budget)
        preserved = {name: before_relations[("ordinary", name)] for name in sync._fts_merge_contract.preserve_tables}
        initial_sequence = dict(local.execute("SELECT name,seq FROM sqlite_sequence")) if ("ordinary", "sqlite_sequence") in before_relations else None
        remote = budget.connect(owner.output, writable=False)
        if sync._fts_merge_contract.internal:
            catalog = sync.policy.tombstone_table
            internal_names = {b.table for b in sync._fts_merge_contract.internal}
            for name, encoded in budget.rows(remote.execute(f"SELECT table_name,primary_key FROM {_quote_identifier(catalog)}")):
                if name in internal_names:
                    key = json.loads(encoded)
                    if type(key) is not list or len(key)!=1 or type(key[0]) is not int or not -(1<<63)<=key[0]<(1<<63) or sync.policy._canonical_key(key)!=encoded:
                        raise SyncError("FTS remote internal canonical docid tombstone mismatch")
        observed = _FtsObservedConnection(local, names, budget, permitted, observe=True,
                                          reference_catalog=(sync.policy.tombstone_table
                                              if type(sync.policy) is TombstoneMergePolicy else None))
        remote_view = _FtsObservedConnection(remote, names, budget)
        ordinary_report = sync.policy.merge(observed, remote_view, snapshot)
        local.row_factory = remote.row_factory = None
        observed.verify()  # Katalog INSERT/UPDATE and DELETE effects are included.
        internal_report = _fts_internal_mirrors(sync, owner, local, remote, snapshot, permitted)
        observed.verify()
        # Existing local PK UPDATE retains its genuine rowid. Inserts retain
        # SQLite's actually assigned destination rowid, never remote docids.
        for descriptor in owner.contract.descriptors:
            if descriptor.content_table is not None:
                name = _quote_identifier(descriptor.name)
                local.execute(f"INSERT INTO {name}({name}) VALUES('rebuild')")
        _fts_integrity(local, owner.contract.descriptors)
        expected_after = _fts_state_relations(local, owner.contract, proof, budget)
        if any(expected_after[("ordinary", name)] != digest for name, digest in preserved.items()):
            raise SyncError("FTS preserved application table changed")
        if initial_sequence is not None:
            after_sequence = dict(local.execute("SELECT name,seq FROM sqlite_sequence"))
            if set(initial_sequence)-set(after_sequence) or any(after_sequence[name] < value for name, value in initial_sequence.items()):
                raise SyncError("FTS allocation metadata regressed")
            if any(after_sequence.get(name) != initial_sequence.get(name) for name in set(initial_sequence)|set(after_sequence) if name not in observed.inserted_tables):
                raise SyncError("FTS nonchosen allocation metadata changed")
        if _fts_layout(local) != proof["layout"] or local.execute("PRAGMA user_version").fetchone()[0] != owner.contract.user_version:
            raise SyncError("FTS merge changed schema/config version")
        after_fk = tuple(sorted(tuple(r) for r in local.execute("PRAGMA foreign_key_check")))
        if after_fk != before_fk:
            raise SyncError("FTS merge changed actual FK tuples")
        remote.close()
        remote = None
        owner.cleanup()  # Unknown leaves prevent commit and any positive ACK.
        _fts_live_check(bound, sync.config.database)
        local.commit()
        committed[0] = True
        local.close()
        local = None
        _fts_live_check(bound, sync.config.database, closed=True)
        reopened = budget.connect(sync.config.database, writable=True)
        _fts_live_check(bound, sync.config.database)
        reopened.execute("BEGIN IMMEDIATE")
        _fts_profile(reopened, sync._fts_contract.sqlite)
        if _fts_layout(reopened) != proof["layout"] or reopened.execute("PRAGMA user_version").fetchone()[0] != sync._fts_contract.user_version:
            raise SyncError("FTS committed reopen schema changed")
        _fts_integrity(reopened, sync._fts_contract.descriptors)
        if _fts_state_relations(reopened, sync._fts_contract, proof, budget) != expected_after or tuple(sorted(tuple(r) for r in reopened.execute("PRAGMA foreign_key_check"))) != before_fk:
            raise SyncError("FTS committed reopen effect changed")
        reopened.rollback()
        reopened.close()
        reopened = None
        _fts_live_check(bound, sync.config.database, closed=True)
        result = FtsMergeReport(snapshot.path.name, snapshot.node_id,
            inserted=ordinary_report.inserted+internal_report.inserted,
            updated=ordinary_report.updated+internal_report.updated,
            unchanged=ordinary_report.unchanged+internal_report.unchanged,
            deleted=ordinary_report.deleted+internal_report.deleted,
            skipped_tables=ordinary_report.skipped_tables,
            tables={**ordinary_report.tables, **internal_report.tables},
            contract_id=sync._fts_contract.contract_id,
            before_relations_sha256=_fts_relations_digest(before_relations),
            after_relations_sha256=_fts_relations_digest(expected_after),
            received_sha256=verification.received_sha256,
            receiver_effect_sha256=verification.receiver_effect_sha256,
            rebuilt_indexes=[d.name for d in sync._fts_contract.descriptors], committed=True)
        return result
    except BaseException as error:
        interrupted = not isinstance(error, Exception)
        if local is not None and not committed[0]:
            local.rollback()
        raise
    finally:
        try:
            _fts_close_connections((reopened, remote, local), interrupted=interrupted)
        finally:
            if owner.work is not None:
                owner.abort(interrupted=interrupted)


def _fts_pull_snapshots(sync: TransitSync, pending: Sequence[Snapshot], *, dry_run: bool) -> list[MergeReport]:
    if dry_run:
        return [MergeReport(snapshot=item.path.name, source_node=item.node_id) for item in pending]
    reports, state = [], _fts_state(sync)
    for item in pending:
        committed = [False]
        failed, report = False, None
        try:
            if not isinstance(item, _FtsSnapshot):
                raise SyncError("Typed FTS destination needs explicit format2 receiver proof")
            report = _fts_merge_received_snapshot(sync, item, committed)
            state.setdefault("last_pulled", {})[item.node_id] = item.created_at
            _fts_save_state(sync, state)  # Separate durability boundary after commit/reopen.
        except Exception:
            failed = True
        if failed:
            if committed[0]:
                raise FtsCommittedPartialError("FTS operation incomplete [committed-partial]") from None
            raise SyncError("FTS operation refused [direct-merge]") from None
        reports.append(report)
    return reports


def _fts_pull(sync: TransitSync, names: Sequence[str] | None, *, dry_run: bool) -> list[MergeReport]:
    # Metadata selection never opens databases. Payloads are rebound only in
    # the actual pull lifetime; a prior verify(True) is not trusted authority.
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be bool")
    pending = sync.pending(verify=False)
    if names is not None:
        if isinstance(names, (str, bytes)) or any(type(v) is not str for v in names) or len(names) != len(set(names)):
            raise ValueError("snapshot_names must be unique basenames")
        by_name = {item.path.name: item for item in pending}
        if any(name not in by_name or Path(name).name != name or "/" in name or "\\" in name for name in names):
            raise SyncError("FTS selected snapshot is not pending")
        pending = [by_name[name] for name in names]
    return _fts_pull_snapshots(sync, pending, dry_run=dry_run)


def _fts_finish_received(owner: _FtsPreparedArtifactOwner,
                         manifest: Mapping[str, Any]) -> FtsVerificationReport:
    proof = _fts_validate_input(owner, owner.source, index=True)
    actual = [{"kind": k[0], "name": k[1], "count": v[0], "sha256": v[1]}
              for k, v in sorted(proof["relations"].items())]
    if actual != manifest["relations"]:
        raise SyncError("FTS received logical commitment mismatch")
    effect = owner.prepare()
    if not _fts_json_exact_equal(_fts_json_normalized(_fts_effect_projection(effect)),
                                 _fts_json_normalized(_fts_effect_projection(manifest))):
        raise SyncError("FTS receiver effect projection mismatch")
    return FtsVerificationReport(manifest["node_id"], owner.contract.contract_id,
        manifest.get("clean_sha256", manifest["sha256"]), manifest["source_sha256"],
        _sha256(owner.source), effect["effect_sha256"],
        tuple((r["kind"], r["name"], r["count"], r["sha256"]) for r in effect["relations"]),
        tuple(d.name for d in owner.contract.descriptors))


def _fts_publish_prepared(sync: TransitSync, owner: _FtsPreparedArtifactOwner,
                          payload: Path, final_path: Path, manifest: dict[str, Any],
                          phase: list[str]) -> tuple[Path, str, int]:
    """Shared accepted private-stage/manifest/inode publication sequence."""
    owner.check()
    digest, size = _sha256(payload), payload.stat().st_size
    if digest != manifest["sha256"] or size != manifest["size"]:
        raise SyncError("FTS prepared publication bytes mismatch")
    phase[0] = "transport"
    partial = final_path.with_name("."+final_path.name+".partial")
    manifest_path = final_path.with_suffix(final_path.suffix+".json")
    stage = _fts_publish_copy(payload, partial, digest, owner.owned)
    _assert_transit_regular_file(partial, final_path.parent, "FTS sanitized stage")
    authentication = sync.authenticator.sign(manifest)
    if not isinstance(authentication, Mapping):
        raise SyncError("FTS HMAC envelope missing")
    manifest["auth"] = dict(authentication)
    sync.authenticator.verify(manifest, manifest["auth"])
    encoded = json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > owner.budget.limits.manifest_bytes:
        raise SyncError("FTS manifest budget exceeded")
    phase[0] = "manifest"
    manifest_stage, manifest_digest = _fts_publish_manifest(manifest, manifest_path, owner.work, owner.owned)
    phase[0] = "cleanup"
    owner.check_config()
    owner.cleanup()  # Raw/clean/prototype leaves gone before discoverable pair.
    phase[0] = "publication"
    owner.check_config()
    final = _fts_publish_link(stage, final_path, owner.owned, digest)
    owner.check_config()
    final_manifest = _fts_publish_link(manifest_stage, manifest_path, owner.owned, manifest_digest)
    owner.check_config()
    _fts_owned_check(final, owner.owned)
    _fts_owned_check(final_manifest, owner.owned)
    if _sha256(final_path) != digest or _sha256(manifest_path) != manifest_digest:
        raise SyncError("FTS final publication bytes drift")
    return manifest_path, digest, size


def _fts_push_owned(sync: TransitSync, phase: list[str]) -> Snapshot:
    owner = None
    completed = interrupted = False
    try:
        phase[0] = "contract"
        if type(sync._fts_contract) is not FtsSnapshotContract or type(sync.authenticator) is not HMACSnapshotAuthenticator:
            raise SyncError("FTS local contract/HMAC required")
        if not sync.config.transit.is_dir() or not sync.config.state.parent.is_dir():
            raise SyncError("FTS transport/state roots must preexist")
        owner = _FtsPreparedArtifactOwner(sync, _FtsBudget(sync._fts_limits))
        phase[0] = "backup-reconstruction"
        effect = owner.prepare_live()
        created = _utc_token()
        final = sync.config.transit / sync._snapshot_name(created)
        digest, size = _sha256(owner.output), owner.output.stat().st_size
        manifest = {"protocol": 2, "format": FTS_SNAPSHOT_FORMAT,
                    "namespace": sync.config.namespace, "node_id": sync.config.node_id,
                    "created_at": created, "snapshot": final.name,
                    "sha256": digest, "size": size, **effect}
        manifest_path, digest, size = _fts_publish_prepared(sync, owner, owner.output, final, manifest, phase)
        completed = True
        return Snapshot(final, manifest_path, sync.config.node_id, sync.config.namespace, created, digest, size)
    except BaseException as error:
        interrupted = not isinstance(error, Exception)
        raise
    finally:
        if owner is not None and not completed:
            try:
                owner.abort(interrupted=interrupted)
            except Exception:
                phase[0] = "cleanup-retained"
                if not interrupted:
                    raise SyncError("FTS cleanup retained unverified artifacts") from None


def _fts_state(sync: TransitSync) -> dict[str, Any]:
    if not sync.config.state.exists():
        return {"protocol":1,"last_pulled":{}}
    value, _ = _fts_read_json(sync.config.state,sync._fts_limits)
    if type(value.get("protocol",1)) is not int or value.get("protocol",1) not in (1,2) or type(value.get("last_pulled",{})) is not dict:
        raise SyncError("FTS local state shape")
    for node, stamp in value.get("last_pulled",{}).items():
        if type(node) is not str or _safe_identifier(node,"node") != node or type(stamp) is not str:
            raise SyncError("FTS local state identity")
        _parse_utc_token(stamp)
    value.setdefault("last_pulled",{})
    return value


def _fts_save_state(sync: TransitSync, value: dict[str, Any]) -> None:
    """Same local checkpoint semantics, existing leaf owner, separate durability."""
    value["protocol"] = 1
    data = json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2).encode()+b"\n"
    if len(data)>sync._fts_limits.manifest_bytes:
        raise SyncError("FTS local checkpoint budget")
    target = sync.config.state
    if not target.parent.is_dir():
        raise SyncError("FTS local state parent must preexist")
    parents = _fts_parent_identity(target)
    previous = _fts_file_identity(target) if target.exists() or _is_reparse_or_symlink(target) else None
    old_hash = _sha256(target) if previous is not None else None
    owned: list[_FtsOwnedLeaf] = []
    stage = _fts_create_private_file(target.with_name("."+target.name+"."+secrets.token_hex(16)+".tmp"),owned)
    fd = None
    moved = False
    try:
        _fts_owned_check(stage,owned)
        fd = os.open(stage.path,os.O_WRONLY|getattr(os,"O_NOFOLLOW",0))
        meta = os.fstat(fd)
        if (meta.st_dev,meta.st_ino)!=(stage.device,stage.inode) or meta.st_nlink!=1:
            raise SyncError("FTS checkpoint stage FD mismatch")
        with os.fdopen(fd, "wb", buffering=0) as writer:
            fd = None
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        _fts_owned_check(stage,owned)
        if _sha256(stage.path)!=hashlib.sha256(data).hexdigest():
            raise SyncError("FTS checkpoint stage bytes drift")
        _fts_check_parents(parents)
        if previous is not None:
            if _fts_file_identity(target)!=previous or _sha256(target)!=old_hash:
                raise SyncError("FTS checkpoint previous drift")
        elif target.exists() or _is_reparse_or_symlink(target):
            raise SyncError("FTS checkpoint unexpected target")
        os.replace(stage.path,target)
        moved=True
        final = _FtsOwnedLeaf(target,parents,stage.device,stage.inode)
        owned[:]=[final]
        _fts_owned_check(final,owned)
        parsed,digest = _fts_read_json(target,sync._fts_limits)
        if parsed!=value or digest!=hashlib.sha256(data).hexdigest():
            raise SyncError("FTS checkpoint final readback mismatch")
        _fts_owned_check(final,owned)
        owned.clear()  # Actual verified local checkpoint handoff.
    finally:
        if fd is not None:
            os.close(fd)
        if not moved:
            for leaf in tuple(owned):
                _fts_remove_owned(leaf,owned)
        # After replace retain actual published state even if readback refuses;
        # the caller reports committed-partial, never database+JSON atomicity.


def _fts_snapshots(sync: TransitSync, verify: bool) -> list[Snapshot]:
    def collect() -> list[Snapshot]:
        values=[]
        for path in sync.config.transit.glob(f"{sync.config.namespace}__*__*{SNAPSHOT_SUFFIX}.json"):
            if len(values)>=sync._fts_limits.relations:
                raise SyncError("FTS manifest count budget")
            values.append(sync._read_snapshot(path,verify=verify))
        return sorted(values,key=lambda item:(item.created_at,item.node_id))
    return _fts_call("snapshot-inventory",collect)


def _fts_pending(sync: TransitSync, verify: bool) -> list[Snapshot]:
    def pending() -> list[Snapshot]:
        state=_fts_state(sync)
        return [s for s in sync.snapshots(verify=verify) if s.node_id!=sync.config.node_id
                and s.created_at>state["last_pulled"].get(s.node_id,"")]
    return _fts_call("pending",pending)


def _fts_status(sync: TransitSync) -> dict[str, Any]:
    def status() -> dict[str, Any]:
        state=_fts_state(sync)
        return {"node_id":sync.config.node_id,"namespace":sync.config.namespace,
                "database":str(sync.config.database),"transit":str(sync.config.transit),
                "state":str(sync.config.state),"database_exists":sync.config.database.is_file(),
                "pending":[s.as_dict() for s in sync.pending(verify=False)],
                "last_pulled":state["last_pulled"],"format":FTS_SNAPSHOT_FORMAT,
                "payload_checked":False,"coverage":"metadata-only"}
    return _fts_call("status",status)
