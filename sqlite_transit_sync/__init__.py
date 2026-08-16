"""Public API for sqlite-transit-sync."""

from .core import (
    TOMBSTONE_TABLE,
    HMACKey,
    HMACSnapshotAuthenticator,
    MergeReport,
    SecretPattern,
    Snapshot,
    SnapshotAuthenticator,
    SyncConfig,
    SyncError,
    TimestampMergePolicy,
    TombstoneMergePolicy,
    TransitSync,
    ensure_tombstone_table,
    load_secret_patterns,
)
from .republica import (
    Envelope,
    EnvelopeReceipt,
    RepublicaImport,
    RepublicaSnapshot,
    RepublicaTransit,
    generate_key,
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
    "Envelope",
    "EnvelopeReceipt",
    "HMACKey",
    "HMACSnapshotAuthenticator",
    "MergeReport",
    "RepublicaImport",
    "RepublicaSnapshot",
    "RepublicaTransit",
    "RetentionDecision",
    "RetentionEntry",
    "RetentionPolicy",
    "RetentionReport",
    "SecretPattern",
    "Snapshot",
    "SnapshotAuthenticator",
    "SnapshotRetentionPolicy",
    "SyncConfig",
    "SyncError",
    "TOMBSTONE_TABLE",
    "TimestampMergePolicy",
    "TombstoneMergePolicy",
    "TransitSync",
    "apply_retention",
    "ensure_tombstone_table",
    "generate_key",
    "load_secret_patterns",
]

__version__ = "0.4.0"
