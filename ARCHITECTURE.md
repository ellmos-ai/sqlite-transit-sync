# Architecture

## Data flow

```text
local DB A --SQLite backup--> snapshot + manifest --transport--> local staging/read
     ^                                                               |
     |                         MergePolicy                            v
     +----------------------- local transaction <--------------- local DB B
```

Only snapshots cross node boundaries. Before publication, every backup is
switched to SQLite's `DELETE` journal mode and checked for adjacent sidecars.
A live database, WAL, SHM, rollback-journal or other unmanifested SQLite file is
never opened through or left in the transport.

On read, the manifest itself must be a direct regular file in the canonical
transit directory. Its `snapshot` value is restricted to one relative filename;
absolute paths, `..` components, nested paths, symlinks and Windows reparse
points are rejected before checksum verification, `quick_check` or merge. The
opened snapshot is checked again against the same canonical directory. These
checks protect the filesystem boundary; SHA-256 still verifies bytes and does
not authenticate who supplied a manifest.

An application may inject `SnapshotAuthenticator` into `TransitSync`. The
reference `HMACSnapshotAuthenticator` signs a canonical manifest envelope
including the protocol version, sender/node, snapshot name, SHA-256, size,
redaction metadata and trust-source identifier. This is opt-in shared-key authentication; key storage,
rotation and freshness remain outside the module.

## Components

- `SyncConfig`: resolves paths and defines node, namespace, timestamps and exclusions.
- `TransitSync`: publishes, discovers, verifies, pulls and records local state.
- `Snapshot`: immutable reference to a database snapshot and its manifest.
- `SnapshotAuthenticator`: optional canonical-manifest authentication boundary.
- `MergePolicy`: application extension point.
- `TimestampMergePolicy`: safe generic baseline for timestamped rows with primary keys.
- `TombstoneMergePolicy`: opt-in explicit deletion reference policy.
- `cli.py`: JSON interface for humans, agents and automations.

## Default merge semantics

The policy intersects tables and columns from local and remote schemas. For each
common table it requires a local primary key and the first configured timestamp
column. A missing local key is inserted; an existing key is updated only if the
remote timestamp is newer. Other rows remain unchanged. Excluded tables and tables
without sufficient semantics are reported as skipped. Equal timestamps use the
lexicographically larger canonical row representation as a deterministic tie-breaker,
so two nodes converge instead of retaining different values.

This deliberately avoids guessing deletion, schema migration or conflict intent.
Applications can provide a custom `MergePolicy` for those decisions.

The opt-in `TombstoneMergePolicy` is a reference deletion contract rather than
a change to the default LWW policy. Applications explicitly create
`__sqlite_transit_tombstones` with `ensure_tombstone_table()`. Its canonical
primary-key JSON and `deleted_at` version make deletion ordering deterministic:
equal/older rows stay deleted, while a later row version may resurrect the key.
The policy does not infer missing-row deletion or prune retained tombstones.

## Trust boundary

Manifests and SHA-256 protect against partial transfer and accidental corruption.
They do not establish sender identity. Deployments with an untrusted transport must
add signatures or an authenticated transport before accepting snapshots.

## Relationship to BACH ProSync

BACH remains the production integration and owns BACH-specific table semantics,
startup/exit hooks, heartbeat, retention and secret handling. This module is the
neutral reusable core. A future BACH adapter can replace duplicated generic mechanics
only after compatibility and migration tests.
