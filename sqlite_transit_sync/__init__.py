"""Public API for sqlite-transit-sync."""

from .core import (
    HMACKey,
    HMACSnapshotAuthenticator,
    MergeReport,
    SecretPattern,
    Snapshot,
    SnapshotAuthenticator,
    SyncConfig,
    SyncError,
    TOMBSTONE_TABLE,
    TombstoneMergePolicy,
    TimestampMergePolicy,
    TransitSync,
    ensure_tombstone_table,
    load_secret_patterns,
)
from .retention import (
    RetentionDecision,
    RetentionEntry,
    RetentionPolicy,
    RetentionReport,
    SnapshotRetentionPolicy,
    apply_retention,
)

__all__ = [
    "HMACKey",
    "HMACSnapshotAuthenticator",
    "MergeReport",
    "SecretPattern",
    "Snapshot",
    "SnapshotAuthenticator",
    "SyncConfig",
    "SyncError",
    "TOMBSTONE_TABLE",
    "TombstoneMergePolicy",
    "TimestampMergePolicy",
    "TransitSync",
    "ensure_tombstone_table",
    "load_secret_patterns",
    "RetentionDecision",
    "RetentionEntry",
    "RetentionPolicy",
    "RetentionReport",
    "SnapshotRetentionPolicy",
    "apply_retention",
]

__version__ = "0.2.0"

