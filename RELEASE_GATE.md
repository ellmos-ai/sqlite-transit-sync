# Release Gate: sqlite-transit-sync

## Status

```
+------------------------------------------+
|                                          |
|           STATUS: LOCKED                 |
|                                          |
+------------------------------------------+
```

`LOCKED` means that this repository must remain private. A passing local test
or hygiene check does not publish, tag or change visibility. `UNLOCKED` may be
written only after a current gate receipt and an explicit responsible-person
sign-off.

## Authority and gate contract

- Package identity is defined by `pyproject.toml` and the contract in
  `METADATA_CONTRACT.md`.
- The reproducible local runner is `python -m pytest -q -ra`; its count is the
  number from `python -m pytest --collect-only -q` (without unittest subtests).
- The same clone must pass `python -m unittest discover -s tests -v`,
  `python -m compileall -q sqlite_transit_sync tests`, Ruff, the JSON CLI
  smoke tests and the public metadata/security checks.
- The historical hygiene helper is external to this repository. If it is used,
  it must be exactly `final_gate_check.py` from
  `modules-meta/rootdocs/_scripts` at commit
  `d8475c29c4da7a0008853e2755e1b6a012c9b791` (SHA-256
  `6AB2EB4012E4CE7F0E5EFE7516A5CC285844FE8F7FF0DBEB2C882138BA425965`).
  An unavailable or different helper is a gate failure, not a fallback.
- `.github/workflows/ci.yml` is the CI projection: supported Python 3.10–3.13,
  Linux/Windows matrix, full tests, static checks and synthetic CLI readback.

## Checklist

| # | Check | Current state | Evidence |
|---|---|---|---|
| 1 | Metadata/version/status contract | PASS after current readback | `METADATA_CONTRACT.md`, `tests/test_metadata.py` |
| 2 | Manifest/snapshot transit containment | PASS after current readback | `tests/test_sync.py`, `SECURITY.md`, `ARCHITECTURE.md` |
| 3 | Public static/privacy hygiene | PENDING current receipt | pinned external helper and tracked-file scan |
| 4 | Full test and CLI gate | PENDING current receipt | current commit-bound report below |
| 5 | Responsible sign-off | NOT GRANTED | required before `UNLOCKED` |

## Current gate receipt

This section is updated only after the commands have run against the final
commit. It must contain the commit, date, exact commands, exit codes, collected
test count and complete output or a linked immutable receipt. An older 8/8,
19/19 or 26/26 result is historical evidence and cannot unlock this gate.

## Sign-off

| Field | Value |
|---|---|
| Responsible person | Not granted in this maintenance bundle |
| Decision | LOCKED |
| Public upload/tag | Not performed |
