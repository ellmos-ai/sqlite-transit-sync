# Architecture

## Two operating modes, meant to coexist

| | Direct sync (`push` / `pull`) | **Republica** (`republica-*`) |
|---|---|---|
| Direction | two-way convergence | one-way showcase |
| Transport | a tunnel between machines (SSH, Tailscale, LAN) | any file area, even untrusted |
| Effect on the local database | rows are merged in | untouched, never opened |
| Result | one converged database | a separate read-only copy per source node |
| Payload | SQLite file | curated SQL dump, gzip, Fernet-encrypted |
| Needs | reachable hosts, trust setup, an agreed merge policy | one key, handed over once |
| Extra dependency | none | `cryptography` |

Both use the same publication gate: journal closing, table redaction, credential scan,
`quick_check`, sidecar checks, manifest and SHA-256.

**These are redundant layers, not a migration path.** Republica is not a stopgap until the
tunnel exists — it is the mode that still works when the tunnel does not:

| Failure | Direct sync | Republica |
|---|---|---|
| A machine is asleep or offline | stalls (no peer) | keeps working (drop-off, pick-up later) |
| Network blocks the tunnel, VPN or SSH is down | stalls | keeps working over the file area |
| Key rotation or trust setup pending | stalls | keeps working with the old shared key |
| The shared folder is broken, full or desynced | keeps working | stalls |
| No merge policy agreed for a dataset | not applicable | keeps working (no merge needed) |

A fallback that is set up once and then left to rot is worthless on the day it is needed, so
Republica is meant to stay configured and exercised even while the direct path is healthy.

## Sealed envelope

The same channel and key also carry a single encrypted file (`envelope-send` /
`envelope-receive`). It exists for the bootstrap problem: two machines share no secure
channel yet, and a credential has to cross. The plaintext is written **as a file** into a
local directory and never into a database, the credential scan deliberately does not apply,
and the envelope is removed from the transit once received. See ADR-009.

## Data flow — merge mode

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
redaction metadata and trust-source identifier. `HMACKeyReference` plus an
injected `SecretResolver` keeps secret values outside configuration; the optional
OS-keyring adapter imports `keyring` only when used. The transport-independent
`verify_authenticated_snapshot` preflight verifies an explicit file pair without
opening SQLite or touching sync state. This is opt-in shared-key authentication;
key custody, rotation policy and freshness remain application concerns.

## Data flow — Republica mode

```text
local DB A --backup--> snapshot --curated SQL dump--> gzip --Fernet--> transport
                                                                          |
                                                                          v
                          republica_root/<node A>/<namespace>.sqlite  <-- decrypt, restore,
                          (read-only, outside the transport)             rebuild FTS

local DB B  ....................... untouched .......................
```

The key travels out of band and must live outside the transport; the same applies to
`republica_root`, since an imported replica holds decrypted foreign data.

## Components

- `SyncConfig`: resolves paths and defines node, namespace, timestamps and exclusions.
- `TransitSync`: publishes, discovers, verifies, pulls all or an explicit pending selection,
  prunes direct snapshots and records local state.
- `Snapshot`: immutable reference to a database snapshot and its manifest.
- `SnapshotAuthenticator`: optional canonical-manifest authentication boundary.
- `HMACKeyReference` / `SecretResolver`: non-secret key lookup boundary.
- `verify_authenticated_snapshot`: explicit read-only HMAC/hash/sidecar preflight.
- `MergePolicy`: application extension point.
- `TimestampMergePolicy`: safe generic baseline for timestamped rows with primary keys.
- `TombstoneMergePolicy`: opt-in explicit deletion reference policy.
- `ProjectionContract` / `verify_projection_database`: strict, read-only validation
  of an application-owned minimal projection; no transport, merge or state mutation.
- `SnapshotRetentionPolicy`: opt-in, ownership-aware age/count planning that
  retains foreign, pending, unknown and unverified artifacts by default.
- `RepublicaTransit`: adds `publish`, `available`, `import_republica` and sealed envelopes on the same safety gate.
- `RepublicaSnapshot` / `RepublicaImport` / `Envelope`: results of publication and import.
- `cli.py`: JSON interface for humans, agents and automations.

## Minimal read-only projection boundary

An application projection is not a merge target. One canonical application
adapter creates a closed SQLite file containing only contract-allowlisted
tables and columns. A consumer supplies its own identity, last accepted
checkpoint and reviewed maximum offline interval to the verifier. The verifier
opens the file read-only, checks closure and SQLite integrity, then validates
schema, values, provenance, loop protection, checkpoint progression and
tombstone retention. It returns a report and writes nothing.

This boundary composes with either carrier mode after the application has
authenticated and approved that transport. It does not choose source queries,
derive opaque identifiers, advance a source checkpoint, activate a scheduler or
authorize a production cutover. See `PROJECTION_CONTRACTS.md`.

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

### Snapshot retention contract

`SnapshotRetentionPolicy` consumes the fail-closed inventory exposed by
`TransitSync.retention_inventory()`. A caller must provide an age and/or count
criterion and an explicit acknowledgement callback. Eligibility requires the
configured namespace, the current owner node, a verified manifest/snapshot
pair, a non-pending pull state and a positive acknowledgement. Age expiry is
strict; count retention keeps the newest acknowledged entries. Every other
artifact is retained with an inspectable reason. `apply_retention()` defaults
to a dry-run and emits a versioned JSON report with exact paths, planned
reasons, deletions and errors. A mutating run re-verifies the pair immediately
before deleting the snapshot and manifest, never sidecars or a globbed set, and
can be safely repeated. Audit files must be outside transit.

## Trust boundary

Manifests and SHA-256 protect against partial transfer and accidental corruption.
They do not establish sender identity. Deployments with an untrusted transport must
add signatures or an authenticated transport before accepting snapshots.

Republica mode narrows this: Fernet's HMAC also detects deliberate modification, including
the case where the manifest hash was recomputed to match. What it still does not provide is
*sender identity* — any holder of the shared key can publish a valid snapshot. This is why
an imported replica stays a separate database and is never merged: content of unproven
origin must not change local rows.

## Relationship to BACH ProSync

BACH remains the production integration and owns BACH-specific table semantics,
startup/exit hooks, heartbeat, retention and secret handling. This module is the
neutral reusable core, including a conservative direct-snapshot cleanup mechanism.
The committed synthetic golden comparison is blocked until an authorized BACH result
exists; a future adapter can select one verified pending snapshot through `pull_selected`
without copying merge/state logic, and can replace duplicated generic mechanics only after
every scenario's compatibility and migration tests pass. No BACH runtime or private
implementation is imported here.
