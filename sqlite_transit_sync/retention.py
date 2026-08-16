"""Opt-in, ownership-aware retention for verified transit snapshots.

The retention module deliberately knows nothing about BACH or an application's
database.  It plans from an inventory supplied by :class:`TransitSync` and
only removes an exact, re-verified snapshot/manifest pair when the caller
explicitly supplies an acknowledgement callback and a retention criterion.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

_REPORT_SCHEMA = "sqlite-transit-sync.retention-report.v1"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"


def _as_utc(value: datetime | None) -> datetime:
    """Return an aware UTC datetime, rejecting naive values."""
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("Retention timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


def _parse_created_at(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RetentionEntry:
    """One inventory item considered by a retention policy.

    ``snapshot`` is intentionally hidden from serialized reports.  It carries
    the verified core ``Snapshot`` object when available and is only used to
    make the acknowledgement callback explicit.
    """

    manifest_path: Path
    snapshot_path: Path | None
    namespace: str | None
    node_id: str | None
    created_at: str | None
    verified: bool
    pending: bool = False
    reason: str | None = None
    snapshot: Any = field(default=None, repr=False, compare=False)

    def paths(self) -> tuple[Path, ...]:
        values = [self.manifest_path]
        if self.snapshot_path is not None and self.snapshot_path not in values:
            values.insert(0, self.snapshot_path)
        return tuple(values)

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path),
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "namespace": self.namespace,
            "node_id": self.node_id,
            "created_at": self.created_at,
            "verified": self.verified,
            "pending": self.pending,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RetentionDecision:
    """A planned retain/delete decision with exact paths and a reason."""

    action: str
    reason: str
    paths: tuple[Path, ...]
    entry: RetentionEntry = field(repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "paths": [str(path) for path in self.paths],
            "manifest_path": str(self.entry.manifest_path),
            "snapshot_path": (
                str(self.entry.snapshot_path) if self.entry.snapshot_path else None
            ),
        }


@dataclass(slots=True)
class RetentionReport:
    """Serializable evidence from a dry-run or a bounded mutation."""

    dry_run: bool
    generated_at: str
    decisions: list[RetentionDecision] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def planned(self) -> list[RetentionDecision]:
        return [decision for decision in self.decisions if decision.action == "delete"]

    @property
    def retained(self) -> list[RetentionDecision]:
        return [decision for decision in self.decisions if decision.action == "retain"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": _REPORT_SCHEMA,
            "dry_run": self.dry_run,
            "generated_at": self.generated_at,
            "planned": [decision.as_dict() for decision in self.planned],
            "retained": [decision.as_dict() for decision in self.retained],
            "deleted": [str(path) for path in self.deleted],
            "errors": self.errors,
            "decisions": [decision.as_dict() for decision in self.decisions],
        }


class RetentionPolicy(Protocol):
    """Policy interface for deterministic retention planning."""

    def plan(
        self,
        entries: Iterable[RetentionEntry],
        *,
        owner_node_id: str,
        namespace: str,
        now: datetime | None = None,
    ) -> list[RetentionDecision]:
        """Return retain/delete decisions without mutating the transit."""


class SnapshotRetentionPolicy:
    """Age/count retention for acknowledged, verified snapshots owned by one node.

    At least one of ``max_age`` and ``keep_latest`` is required.  A missing
    acknowledgement callback deliberately makes every otherwise eligible
    snapshot ``not-acknowledged``; retention never infers ownership from a
    filename or from a successful integrity check.
    """

    def __init__(
        self,
        *,
        max_age: timedelta | None = None,
        keep_latest: int | None = None,
        acknowledge: Callable[[Any], bool] | None = None,
    ) -> None:
        if max_age is None and keep_latest is None:
            raise ValueError("Retention requires max_age or keep_latest")
        if max_age is not None and (not isinstance(max_age, timedelta) or max_age < timedelta(0)):
            raise ValueError("max_age must be a non-negative timedelta")
        if keep_latest is not None and (
            isinstance(keep_latest, bool) or not isinstance(keep_latest, int) or keep_latest < 0
        ):
            raise ValueError("keep_latest must be a non-negative integer")
        self.max_age = max_age
        self.keep_latest = keep_latest
        self.acknowledge = acknowledge

    def _eligibility_reason(
        self,
        entry: RetentionEntry,
        *,
        owner_node_id: str,
        namespace: str,
    ) -> str | None:
        if entry.reason:
            return entry.reason
        if not entry.verified:
            return "unverified"
        if entry.namespace != namespace:
            return "foreign-namespace"
        if entry.node_id != owner_node_id:
            return "pending-foreign" if entry.pending else "foreign-node"
        if entry.pending:
            return "pending"
        if self.acknowledge is None:
            return "not-acknowledged"
        try:
            acknowledged = bool(self.acknowledge(entry.snapshot or entry))
        except Exception:
            return "acknowledgement-error"
        if not acknowledged:
            return "not-acknowledged"
        if _parse_created_at(entry.created_at) is None:
            return "invalid-created-at"
        return None

    def plan(
        self,
        entries: Iterable[RetentionEntry],
        *,
        owner_node_id: str,
        namespace: str,
        now: datetime | None = None,
    ) -> list[RetentionDecision]:
        current = _as_utc(now)
        materialized = list(entries)
        eligible: list[tuple[RetentionEntry, datetime]] = []
        decisions: dict[int, RetentionDecision] = {}

        for entry in materialized:
            blocked = self._eligibility_reason(
                entry, owner_node_id=owner_node_id, namespace=namespace
            )
            if blocked is not None:
                decisions[id(entry)] = RetentionDecision(
                    "retain", blocked, entry.paths(), entry
                )
                continue
            parsed = _parse_created_at(entry.created_at)
            if parsed is None:  # Defensive: _eligibility_reason checked this.
                decisions[id(entry)] = RetentionDecision(
                    "retain", "invalid-created-at", entry.paths(), entry
                )
                continue
            eligible.append((entry, parsed))

        eligible.sort(key=lambda pair: (pair[1], pair[0].node_id or "", str(pair[0].manifest_path)))
        keep_paths: set[Path] = set()
        if self.keep_latest is not None:
            newest = eligible[-self.keep_latest :] if self.keep_latest else []
            keep_paths = {entry.manifest_path for entry, _ in newest}

        for entry, created in eligible:
            age_expired = self.max_age is not None and current - created > self.max_age
            count_expired = self.keep_latest is not None and entry.manifest_path not in keep_paths
            if age_expired or count_expired:
                reasons = []
                if age_expired:
                    reasons.append("max-age-exceeded")
                if count_expired:
                    reasons.append("outside-keep-latest")
                decisions[id(entry)] = RetentionDecision(
                    "delete", ";".join(reasons), entry.paths(), entry
                )
            else:
                decisions[id(entry)] = RetentionDecision(
                    "retain",
                    "keep-latest" if self.keep_latest is not None else "within-retention",
                    entry.paths(),
                    entry,
                )

        return [decisions[id(entry)] for entry in materialized]


def _write_report(path: Path, report: RetentionReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report.as_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


def _error(report: RetentionReport, decision: RetentionDecision, reason: str) -> None:
    report.errors.append(
        {
            "reason": reason,
            "paths": [str(path) for path in decision.paths],
        }
    )


def apply_retention(
    sync: Any,
    policy: RetentionPolicy,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    audit_path: str | Path | None = None,
) -> RetentionReport:
    """Plan or apply exact snapshot deletions and optionally persist an audit report."""

    current = _as_utc(now)
    if audit_path is not None:
        audit = Path(audit_path).expanduser().resolve()
        transit = Path(sync.config.transit).resolve()
        if audit == transit or transit in audit.parents:
            raise ValueError("Retention audit_path must be outside the transit directory")
    else:
        audit = None

    decisions = policy.plan(
        sync.retention_inventory(),
        owner_node_id=sync.config.node_id,
        namespace=sync.config.namespace,
        now=current,
    )
    report = RetentionReport(
        dry_run=dry_run,
        generated_at=current.isoformat().replace("+00:00", "Z"),
        decisions=decisions,
    )
    if not dry_run:
        for decision in decisions:
            if decision.action != "delete":
                continue
            entry = decision.entry
            try:
                current_snapshot = sync._read_snapshot(entry.manifest_path, verify=True)
                expected = entry.snapshot
                if (
                    entry.snapshot_path is None
                    or current_snapshot.path != entry.snapshot_path
                    or current_snapshot.manifest_path != entry.manifest_path
                    or current_snapshot.namespace != entry.namespace
                    or current_snapshot.node_id != entry.node_id
                    or current_snapshot.created_at != entry.created_at
                    or (expected is not None and current_snapshot.sha256 != expected.sha256)
                    or (expected is not None and current_snapshot.size != expected.size)
                ):
                    raise RuntimeError("snapshot changed since retention plan")
                # _read_snapshot already proved both are direct regular files in
                # transit.  Delete only these two exact paths, never a glob.
                current_snapshot.path.unlink()
                current_snapshot.manifest_path.unlink()
                report.deleted.extend((current_snapshot.path, current_snapshot.manifest_path))
            except Exception as error:
                _error(report, decision, str(error))
    if audit is not None:
        _write_report(audit, report)
    return report


__all__ = [
    "RetentionDecision",
    "RetentionEntry",
    "RetentionPolicy",
    "RetentionReport",
    "SnapshotRetentionPolicy",
    "apply_retention",
]
