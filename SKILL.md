---
name: sqlite-transit-sync
version: "0.4.0"
description: "Local-first SQLite synchronization through verified transit snapshots, configurable row-level merge policies, read-only projection verification, and optional encrypted Republica showcases."
license: MIT
author: "Lukas Geiger"
homepage: "https://github.com/ellmos-ai/sqlite-transit-sync"
---

# Product Skill: `sqlite-transit-sync`

> **Purpose:** Guide AI agents and human operators to safely initialize, publish, verify, merge, clean up, and inspect local-first SQLite synchronization using `sqlite-transit-sync` (`v0.4.0`), strictly respecting fail-closed containment, credential scanning, and dry-run authority boundaries.
> **Machine Index:** [`llms.txt`](llms.txt) (compatibility pointer: [`llm.txt`](llm.txt))
> **Projection Contracts:** [`PROJECTION_CONTRACTS.md`](PROJECTION_CONTRACTS.md) / [`PROJECTION_CONTRACTS_de.md`](PROJECTION_CONTRACTS_de.md)
> **Security Policy:** [`SECURITY.md`](SECURITY.md)

---

## 1. Scope & Capabilities

### What `sqlite-transit-sync` Does
- **Atomic Snapshot Sync (`push` / `pull` / `sync`):** Captures consistent online backups via `sqlite3.Connection.backup`, strips excluded tables + runs `VACUUM`, screens snapshot text against configured credential patterns (`credential-triggers.json`), writes atomic snapshots + SHA-256 manifests (`os.replace`), verifies `PRAGMA quick_check`, and applies transactional row-level merges (default: primary-key Last-Write-Wins, or custom `MergePolicy` / `TombstoneMergePolicy`).
- **Preflight & Status (`verify` / `status` / `list`):** Inspects local database, manifest SHA-256 digests, optional API-injected HMAC-SHA256 signatures (`verify_authenticated_snapshot`), and pending snapshots without mutating local rows.
- **Conservative Retention (`cleanup` / `apply_retention`):** Plans deletion of verified, non-pending local-node snapshots as a **dry-run by default**; actual deletion requires explicit `--apply` (or `dry_run=False`) and foreign-node scope requires `--all-nodes`.
- **Read-Only Application Projections (`verify-projection`):** Validates closed application-owned projection databases against bundled versioned allowlist contracts (`abotracker-subscription-status-projection.v1`, `accounts-balance-projection.v1`, `hauslagerist-replenishment-projection.v1`, `mediplaner-reminder-projection.v1`, `routinika-reminder-projection.v1`, `versicherungsmanager-deadline-projection.v1`).
- **Encrypted Showcase & Courier (`republica-publish` / `republica-list` / `republica-import` / `envelope-send` / `envelope-receive`):** Optional `[crypto]` mode using an out-of-band Fernet key (`keygen`) to publish read-only SQL/gzip/Fernet showcases (`republica_root`) or single `0600` sealed credential files.

### What `sqlite-transit-sync` Intentionally Does NOT Do
- Never opens or shares a live SQLite database (`.db`, `-wal`, `-shm`) directly inside a cloud-sync or transit folder.
- Never auto-creates missing application schemas or guesses database migrations.
- Never stores secrets or key material inside `node.json` or transit directories.
- Never provides global distributed transactions, automatic background convergence, or sender identity authentication unless an HMAC authenticator is explicitly injected via API.
- Never proves a snapshot is secret-free when the regex credential scan passes (vendor-prefixed patterns are a safety net, not exhaustive DLP).

---

## 2. Prerequisites & Installation

- **Python:** `>= 3.10` (core merge mode uses the Python Standard Library with **zero external runtime dependencies**).
- **Optional Extras:**
  - `[crypto]` (`cryptography>=42`) for `keygen`, `republica-*`, and `envelope-*` commands.
  - `[keyring]` (`keyring>=25`) for `OSKeyringSecretResolver`.

```bash
# Core installation (zero external runtime dependencies)
python -m pip install -e .

# With encrypted Republica showcase and OS keyring support
python -m pip install -e ".[crypto,keyring]"
```

Verify installation:

```bash
sqlite-transit-sync --help
python -m sqlite_transit_sync --help
```

---

## 3. Safe CLI Workflows (JSON Output & Readback)

Every CLI subcommand emits structured JSON on stdout (`{"ok": true, ...}` on success, exit code `0`). Always inspect the JSON output rather than assuming success from exit status alone.

### A. Initialize Node Configuration
Keep `database` and `state` strictly outside `transit`:

```bash
sqlite-transit-sync init \
  --config node.json \
  --database ./app.db \
  --transit ./shared-transit \
  --node-id laptop \
  --namespace my-app
```

### B. Publish, Verify, Dry-Run, and Merge
Run `--dry-run` before committing a `pull` when inspecting unfamiliar transit state:

```bash
sqlite-transit-sync push --config node.json
sqlite-transit-sync verify --config node.json
sqlite-transit-sync status --config node.json
sqlite-transit-sync pull --config node.json --dry-run
sqlite-transit-sync pull --config node.json
```

### C. Conservative Retention Cleanup
`cleanup` is always a dry-run unless `--apply` is explicitly passed:

```bash
# Step 1: Inspect planned deletions (safe read-only dry-run)
sqlite-transit-sync cleanup --config node.json --keep-days 7 --keep-per-node 10

# Step 2: Apply only after verifying the JSON plan
sqlite-transit-sync cleanup --config node.json --keep-days 7 --keep-per-node 10 --apply
```

### D. Read-Only Projection Verification
Does not require `node.json` and never opens or mutates sync state:

```bash
sqlite-transit-sync verify-projection \
  --contract mediplaner-reminder-projection.v1 \
  --database ./closed-projection.sqlite \
  --consumer-id reminder-consumer \
  --minimum-offline-seconds 2592000 \
  --previous-checkpoint 41
```

### E. Optional Republica Encrypted Showcase (`[crypto]`)
Generate the Fernet key on a local, non-synced filesystem and transfer it out of band:

```bash
sqlite-transit-sync keygen --key-file ~/.keys/republica.key
sqlite-transit-sync republica-publish --config node.json
sqlite-transit-sync republica-list --config node.json
sqlite-transit-sync republica-import --config node.json
```

---

## 4. Python API Usage

```python
from sqlite_transit_sync import SyncConfig, TransitSync

config = SyncConfig.from_file("node.json")
sync = TransitSync(config)

snapshot = sync.push()
reports = sync.pull()
cleanup_plan = sync.cleanup(keep_days=7, keep_per_node=10)
```

For optional sender authentication without secrets in `node.json`, use `HMACKeyReference`, `load_hmac_authenticator(...)`, and `verify_authenticated_snapshot(...)` (see [`README.md`](README.md#python-api)).

---

## 5. Guardrails, Side Effects & Error Handling

- **Fail-Closed Path Containment:** Symlinks, reparse points, absolute manifest paths, and `..` traversal inside `transit` raise `SyncError` before hashing or opening SQLite.
- **Credential-Pattern Abort:** On match, `push` aborts publication and names only `table.column` (never the secret value). If a table contains intentional non-secret tokens that match a prefix, prefer `secret_scan_skip_tables` over disabling `scan_snapshot_for_secrets` globally.
- **Process Serialization:** Run only one sync process per node unless the calling application holds an external process lock.
- **Exit Codes:** `0` = command completed and JSON printed; non-zero (`1` / `2`) = validation, containment, integrity, or CLI argument error (read stderr/JSON error payload and stop without retrying destructive steps).
- **Documentation & Governance Boundaries:** This `SKILL.md` covers product usage. For repository contributor and development rules, consult [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md).
