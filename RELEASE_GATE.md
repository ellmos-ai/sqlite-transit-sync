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
| 3 | Public static/privacy hygiene | PENDING external helper authorization | pinned external helper and tracked-file scan |
| 4 | Full test and CLI gate | PASS for tested code commit | current commit-bound report below |
| 5 | Responsible sign-off | NOT GRANTED | required before `UNLOCKED` |

## Current gate receipt

This section is updated only after the commands have run against the final
commit. It must contain the commit, date, exact commands, exit codes, collected
test count and complete output or a linked immutable receipt. An older 8/8,
19/19 or 26/26 result is historical evidence and cannot unlock this gate.

### Receipt 2026-08-13 (tested code commit `4ba9be1`)

The local readback covers the opt-in retention policy, synthetic BACH golden
comparison, documentation and the existing authentication/state/tombstone
contracts. No live database, BACH runtime, external transport or remote write
was used.

| Command | Exit | Output/readback |
|---|---:|---|
| `python -m unittest discover -s tests -v` | 0 | `Ran 53 tests in 11.987s` / `OK` |
| `python -m pytest -q -ra` | 0 | `..................................................... [100%]` |
| `python -m pytest --collect-only -q` | 0 | Auth 4; BACH golden 2; CLI 3; metadata 6; retention 6; sync 29; tombstone 3 |
| `python -m compileall -q sqlite_transit_sync tests scripts` | 0 | no output |
| `python -m ruff check sqlite_transit_sync tests scripts` | 0 | `All checks passed!` |
| `python -m sqlite_transit_sync --help` | 0 | usage for `init,status,push,pull,sync,verify,list` |
| `python -m sqlite_transit_sync init --help` | 0 | required config/database/transit options shown |
| `python scripts/compare_bach_golden.py --output golden/bach_compatibility_report.json` | 0 | `blocked_no_authorized_bach_golden`, 7 scenarios |
| `git diff --check` | 0 | no whitespace errors |

The local branch after this commit is `ahead 12, behind 14` relative to the
divergent `origin/main`; no pull, merge, rebase, push or release action was
performed. The external hygiene helper remains a separate locked-gate
dependency and was not substituted.

### Receipt 2026-08-10 (tested code commit `0dc9935f5e2298e3b1867ef163a6dd4f478dd12c`)

The local readback was run from the TASKSOLVER implementation commit (the
untracked TASKSOLVER lock is not part of the commit). This receipt covers the
authentication, state/transit separation and opt-in tombstone bundle:

| Command | Exit | Output/readback |
|---|---:|---|
| `python -m unittest discover -s tests -v` | 0 | `Ran 45 tests in 7.931s` / `OK` |
| `python -m pytest -q -ra` | 0 | `............................................. [100%]` |
| `python -m pytest --collect-only -q` | 0 | `tests/test_auth.py: 4`; `tests/test_cli.py: 3`; `tests/test_metadata.py: 6`; `tests/test_sync.py: 29`; `tests/test_tombstone.py: 3` |
| `python -m compileall -q sqlite_transit_sync tests` | 0 | no output |
| `python -m ruff check sqlite_transit_sync tests` | 0 | `All checks passed!` |
| `python -m sqlite_transit_sync --help` | 0 | usage for `init,status,push,pull,sync,verify,list` |
| `python -m sqlite_transit_sync init --help` | 0 | usage with required `--config`, `--database`, `--transit` and optional `--state` |
| `git diff --check` | 0 | no whitespace errors |
| tracked-file secret/path scan | 0 | `TRACKED_ARTIFACTS=0`; `PERSONAL_PATH_FINDINGS=0`; no credential-pattern findings |

The synthetic CLI roundtrip is included in the 45-test collection and covers
`init/status/push/list/verify/pull --dry-run`; no live database or transport was
used. The tracked-file readback found `TRACKED_ARTIFACTS=0` and
`PERSONAL_PATH_FINDINGS=0`.

The required external helper was checked without substituting another helper:

```
HELPER_EXPECTED_COMMIT=d8475c29c4da7a0008853e2755e1b6a012c9b791
HELPER_CURRENT_COMMIT=89834a01d6d340d74aac96490f92dfd8706b10b9
HELPER_SHA256=6AB2EB4012E4CE7F0E5EFE7516A5CC285844FE8F7FF0DBEB2C882138BA425965
EXTERNAL_HELPER_GATE=FAIL_COMMIT_MISMATCH (exit 2)
```

The helper's matching SHA does not override its commit mismatch, so checklist
item 3 remains pending. The local test/CLI gate (item 4) passes, but the gate
stays `LOCKED`; no upload, tag or visibility change was performed.

The preceding 34-test receipt on `c946ea787b36c8c8caad5315c8ef88cd37f357cb`
is historical only.

### Remote push gate

After a fresh `git fetch --prune origin main`, the local branch was `ahead 9,
behind 14` and `origin/main` read back as `7648a20b11ca958e9622d2b5d8a13fd02613e92a`.
The one allowed non-forcing push attempt for this bundle, `git push origin
main`, returned exit 1 (`non-fast-forward`). No pull, merge, rebase or force
push was performed, so the foreign remote history remains untouched.

## Sign-off

| Field | Value |
|---|---|
| Responsible person | Not granted in this maintenance bundle |
| Decision | LOCKED |
| Public upload/tag | Not performed |
