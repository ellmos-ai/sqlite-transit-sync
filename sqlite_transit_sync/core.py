"""Verified snapshot transit and row-level merging for local SQLite databases."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import socket
import sqlite3
import stat
import tempfile
from collections.abc import Iterable, Mapping, Sequence
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
    """Load credential triggers from JSON (defaults to the bundled file)."""
    source = Path(path).expanduser() if path else _TRIGGER_FILE
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SyncError(f"Invalid credential trigger file: {source}: {error}") from error
    entries = raw.get("patterns", []) if isinstance(raw, dict) else raw
    patterns: list[SecretPattern] = []
    for index, entry in enumerate(entries):
        try:
            name = str(entry["name"])
            compiled = re.compile(str(entry["regex"]))
        except (KeyError, TypeError, re.error) as error:
            raise SyncError(
                f"Invalid credential trigger #{index} in {source}: {error}"
            ) from error
        prefilter = entry.get("prefilter") or None
        patterns.append(SecretPattern(name, compiled, prefilter))
    return tuple(patterns)


class SyncError(RuntimeError):
    """Raised when a snapshot or synchronization operation is unsafe."""


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


class TransitSync:
    """Coordinates verified snapshots between independent local SQLite writers."""

    def __init__(
        self,
        config: SyncConfig,
        policy: MergePolicy | None = None,
        authenticator: SnapshotAuthenticator | None = None,
    ) -> None:
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

    def _scan_snapshot_for_secrets(self, path: Path) -> list[str]:
        """Report credential-looking values in snapshot content.

        Runs on the snapshot copy, never on the live database. Returns locations
        as ``table.column`` — deliberately **without** the matched value, so the
        credential is not copied into logs, exceptions or CI output.
        """
        if not self.config.scan_snapshot_for_secrets:
            return []

        patterns = list(load_secret_patterns(self.config.secret_patterns_file))
        for index, expr in enumerate(self.config.secret_scan_extra_patterns):
            try:
                patterns.append(SecretPattern(f"custom[{index}]", re.compile(expr)))
            except re.error as error:
                raise SyncError(f"Invalid secret_scan_extra_patterns[{index}]: {error}") from error
        if not patterns:
            return []

        # Rows are pre-filtered in SQL when every pattern carries a literal that
        # must be present. A single pattern without one makes the pre-filter
        # unsound — missing a credential is worse than a slower scan — so the
        # column is then read in full.
        prefilters = [p.prefilter for p in patterns]
        can_prefilter = all(prefilters)
        skip = set(self.config.secret_scan_skip_tables)
        findings: list[str] = []
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            connection.text_factory = lambda value: value.decode("utf-8", "replace")
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                if not row[0].startswith("sqlite_") and row[0] not in skip
            ]
            for table in tables:
                columns = [
                    row[1]
                    for row in connection.execute(
                        f"PRAGMA table_info({_quote_identifier(table)})"
                    ).fetchall()
                    if (row[2] or "").upper() not in {"INTEGER", "REAL", "NUMERIC", "BOOLEAN"}
                ]
                for column in columns:
                    quoted = _quote_identifier(column)
                    select = (
                        f"SELECT CAST({quoted} AS TEXT) FROM {_quote_identifier(table)}"
                    )
                    params: list[str] = []
                    if can_prefilter:
                        clause = " OR ".join(f"CAST({quoted} AS TEXT) LIKE ?" for _ in prefilters)
                        select = f"{select} WHERE {clause}"
                        params = [f"%{token}%" for token in prefilters]
                    try:
                        rows = connection.execute(select, params).fetchall()
                    except sqlite3.Error:
                        continue  # virtual tables / odd column types stay out of the way
                    for (value,) in rows:
                        if not value:
                            continue
                        for pattern in patterns:
                            if pattern.regex.search(value):
                                location = f"{table}.{column} ({pattern.name})"
                                if location not in findings:
                                    findings.append(location)
                                break
        finally:
            connection.close()
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

    def push(self) -> Snapshot:
        if not self.config.database.is_file():
            raise SyncError(f"Live database not found: {self.config.database}")
        created_at = _utc_token()
        final_path = self.config.transit / self._snapshot_name(created_at)
        partial_path = final_path.with_name(f".{final_path.name}.partial")
        manifest_path = final_path.with_suffix(final_path.suffix + ".json")
        _remove_sqlite_artifacts(partial_path)
        source: sqlite3.Connection | None = None
        destination: sqlite3.Connection | None = None
        try:
            try:
                source = sqlite3.connect(str(self.config.database))
                destination = sqlite3.connect(str(partial_path))
                with destination:
                    source.backup(destination)
            finally:
                if destination is not None:
                    destination.close()
                if source is not None:
                    source.close()
        except Exception as error:
            try:
                _remove_sqlite_artifacts(partial_path)
            except SyncError as cleanup_error:
                raise cleanup_error from error
            raise

        published_snapshot = False
        try:
            self._close_snapshot(partial_path)
            redacted_tables = self._redact_snapshot(partial_path)
            leaks = self._scan_snapshot_for_secrets(partial_path)
            if leaks:
                raise SyncError(
                    "Snapshot publication aborted: credential-looking values remain in "
                    + ", ".join(leaks)
                    + ". Remove them from the source database, add the table to "
                    "snapshot_exclude_tables, or disable scan_snapshot_for_secrets if "
                    "this is a false positive. The value itself is not shown on purpose."
                )
            self._quick_check(partial_path)
            _assert_no_sqlite_sidecars(partial_path)
            digest = _sha256(partial_path)
            size = partial_path.stat().st_size
            os.replace(partial_path, final_path)
            published_snapshot = True
            _assert_no_sqlite_sidecars(final_path)
        except Exception as error:
            try:
                _remove_sqlite_artifacts(partial_path)
                if published_snapshot:
                    _remove_sqlite_artifacts(final_path)
            except SyncError as cleanup_error:
                raise cleanup_error from error
            raise
        manifest = {
            "protocol": PROTOCOL_VERSION,
            "namespace": self.config.namespace,
            "node_id": self.config.node_id,
            "created_at": created_at,
            "snapshot": final_path.name,
            "sha256": digest,
            "size": size,
            "redacted_tables": redacted_tables,
        }
        try:
            if self.authenticator is not None:
                authentication = self.authenticator.sign(manifest)
                if not isinstance(authentication, Mapping):
                    raise SyncError("Snapshot authenticator returned an invalid envelope")
                manifest["auth"] = dict(authentication)
            _atomic_json_write(manifest_path, manifest)
        except Exception as error:
            try:
                _remove_manifest_artifacts(manifest_path)
                _remove_sqlite_artifacts(final_path)
                _remove_sqlite_artifacts(partial_path)
            except SyncError as cleanup_error:
                raise cleanup_error from error
            raise
        return Snapshot(
            path=final_path,
            manifest_path=manifest_path,
            node_id=self.config.node_id,
            namespace=self.config.namespace,
            created_at=created_at,
            sha256=digest,
            size=size,
        )

    def _read_snapshot(self, manifest_path: Path, verify: bool = True) -> Snapshot:
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
        self._quick_check(self.config.database)
        snapshots = self.snapshots(verify=True)
        return {"database": "ok", "verified_snapshots": len(snapshots)}

    def status(self) -> dict[str, Any]:
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
