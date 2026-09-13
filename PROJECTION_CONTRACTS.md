# Read-only projection contracts

[English](PROJECTION_CONTRACTS.md) | [Deutsch](PROJECTION_CONTRACTS_de.md)

Application-owned projections let one canonical application publish only the
small state a coordinator needs. They do not turn `sqlite-transit-sync` into a
second domain database or a multi-writer engine.

## Boundary

- Exactly one canonical application adapter publishes a closed projection.
- Consumers validate and open the projection read-only. They never write domain
  rows, checkpoints, or tombstones back to it.
- The verifier does not copy, publish, merge, migrate, schedule, activate, or
  advance consumer state.
- Production adapters, live databases, host paths, credentials, and cutover
  configuration are not included in this repository.

The four bundled contracts are deliberately narrow:

| Contract | Allowed record tables | Explicitly absent |
|---|---|---|
| `accounts-balance-projection.v1` | `account_balances` | source IDs, full IBANs, account numbers, bank/BIC/holder data, notes |
| `mediplaner-reminder-projection.v1` | `medication_due`, `inventory_warning` | names, clients, diagnoses, doses, quantities, stock values, notes |
| `routinika-reminder-projection.v1` | `routine_due` | titles, definitions, steps, notes, media paths, unrelated settings |
| `versicherungsmanager-deadline-projection.v1` | `policy_deadline_due` | policy titles, providers, policy numbers, insurance areas, premiums, contacts, documents, notes |

All four also require one `projection_metadata` row and an explicit
`projection_tombstones` table. Stable references are opaque lowercase hex
tokens; the contract does not define how an application derives them.

## Verification

```bash
sqlite-transit-sync verify-projection \
  --contract mediplaner-reminder-projection.v1 \
  --database ./closed-projection.sqlite \
  --consumer-id reminder-consumer \
  --minimum-offline-seconds 2592000 \
  --previous-checkpoint 41
```

The command emits JSON and opens the database with SQLite `mode=ro` plus
`immutable=1`. It rejects sidecars before opening, runs `PRAGMA quick_check`,
and then enforces:

1. the exact table and ordered-column allowlist, including type, nullability,
   and primary-key order;
2. contract ID, version, publisher component, publisher instance, and a single
   metadata row;
3. opaque identifiers, UTC timestamps, enums, non-negative checkpoints, and
   valid time windows;
4. matching publisher/checkpoint provenance on every record;
5. a loop guard (`consumer_id != publisher_instance`);
6. a strictly newer source checkpoint when `previous_checkpoint` is supplied;
7. tombstone retention that covers the application-supplied maximum offline
   interval, plus rejection of an equal or older active row.

The offline interval is deliberately not guessed by the neutral module. An
application must supply its reviewed value at verification time. A successful
report is evidence about this closed file only; it is not sender authentication,
freshness beyond the supplied checkpoint, or production activation.

## Synthetic fixtures

`tests/fixtures/projections/` contains JSON recipes, not SQLite databases. Tests
materialise them only in temporary directories. Each contract has an initial
snapshot and a later offline-resume snapshot with a skipped checkpoint and an
explicit retained tombstone. Negative tests cover privacy expansion, unknown
tables/columns, malformed identifiers and states, provenance drift, replay,
looping, inadequate tombstone retention, stale active rows, and unclosed
sidecars. No live application data is used.

## Adapter hand-off

An application adapter may be implemented only in that application's canonical
source repository. It must construct the projection transactionally, advance
the source checkpoint only after commit, close the file, and then hand the
closed file to an authenticated or otherwise approved transport. This module
supplies the verifier and carrier mechanics; it does not infer the application's
source queries, opaque-ID derivation, offline horizon, or activation policy.
