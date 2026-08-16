# Changelog

- **Discoverability, README-Design & Metadata Parity Check:** Synchronized Shields.io badges in `README.md` and `README_de.md` (`Ecosystem: ellmos-ai`, `Umbrella: open-bricks`, `version-0.4.0`, `tests-96/96 passed`), synchronized `llms.txt`, `ellmos-module.json`, `ellmos-module.v2.json`, and dynamic metadata parity tests in `tests/test_metadata.py` (96/96 passed, 100% green) [G 2026-08-16].
- **Code-Hygiene & Linting:** Added Ruff configuration to `pyproject.toml`, modernized type annotations (`collections.abc.Sequence`, `collections.abc.Iterator`, `re.Pattern[str]`), cleaned unused imports, and formatted test assertions.
- **Snapshot Retention Policy:** `SnapshotRetentionPolicy` and versioned `retention-report.v1` audit contract added. Opt-in and dry-run by default; verified, owner-scoped, non-pending, explicitly acknowledged snapshot pairs planned by age/count rules.
- **BACH Golden Compatibility Comparison:** Added 7 synthetic BACH golden scenarios and reproducible comparison via `scripts/compare_bach_golden.py` (`blocked_no_authorized_bach_golden` status without authorized reference inputs).
- **Authenticated Manifests:** Added optional `HMACSnapshotAuthenticator` with canonical manifest envelope, sender/key verification, and rotation.
- **Tombstone Reference Policy:** Added `TombstoneMergePolicy` with explicit `__sqlite_transit_tombstones` tracking.
- **Selected Pending Pull:** Added `TransitSync.pull_selected()` for lifecycle adapters to process explicit pending snapshots safely.
- **Conservative Direct-Snapshot Cleanup:** Added `TransitSync.cleanup()` and CLI `cleanup` with verified age and per-node retention planning.
- **Discoverability:** Corrected canonical repository owner to `ellmos-ai` in package metadata, `llms.txt`, and release documentation.
- **Republica Mode:** One-way encrypted showcase distribution mode (`republica.py`, `RepublicaTransit`, `publish` / `republica-import`) and sealed envelopes (`envelope-send` / `envelope-receive`).
- **FTS Virtual Table Restoration:** Curated SQL dump handling and automatic full-text index rebuilding on import.
- **Credential Scan Left-Anchoring:** Left-anchored regex prefix triggers with `(?<![A-Za-z0-9])` in `credential-triggers.json` (v2) to eliminate false-positive substring blocking on clean words.
- Close every backup into `DELETE` journal mode before publication and remove the
  complete temporary SQLite artifact family on backup, redaction, credential-scan,
  verification, or manifest failure. WAL source databases can no longer leave
  unmanifested `-wal`, `-shm`, `-journal`, or similar sidecars in transit.
- Add `SyncConfig.from_bytes(payload, source_path=...)` so callers can hash and
  parse the exact same config bytes. `from_file()` delegates to this parser and
  keeps identical source-relative path semantics.

## 0.2.0 — 2026-07-29

- **Dokumentation, SEO & Discoverability**: `llms.txt` Verifikations-Timestamp auf 2026-07-30 aktualisiert, GFM LLM Note Callout (`> [!NOTE]`) in `README.md` & `README_de.md` integriert, 19/19 Pytest-Tests verifiziert [G 2026-07-30].
- **CI/CD & Automation**: Added `.github/workflows/ci.yml` for automated GitHub Actions testing on Python 3.10, 3.11, 3.12, 3.13.
- **Tests & Metadata**: Added `tests/test_metadata.py` checking version parity, exports, and `llms.txt` integrity (19/19 passed).
- **Dokumentation & Hygiene**: `llms.txt` Last-checked Datum auf 2026-07-29 und Version auf 0.2.0 angeglichen, Badges in `README.md` & `README_de.md` auf 19/19 grüne Pytest-Tests aktualisiert [G 2026-07-29].
- **Credential scan before publication (`scan_snapshot_for_secrets`, default on).** Snapshots are
  now checked for credential-shaped values in their *content* before they reach the transit
  directory; a match aborts the push with a `SyncError` naming `table.column`, never the value.
  Complements `snapshot_exclude_tables`, which can only drop a table you already know about —
  the scan catches credentials pasted into free-text columns (notes, logs, session summaries).
  Patterns are vendor-prefixed (OpenAI, Anthropic, OpenRouter, GitHub, GitLab, Google, Slack,
  npm, AWS and PEM key blocks); checksums, UUIDs and git SHAs deliberately do **not** match.
  New config keys: `scan_snapshot_for_secrets`, `secret_scan_extra_patterns`,
  `secret_scan_skip_tables`, `secret_patterns_file`. Rationale in `DECISIONS.md` (ADR-005).
- **Triggers are data, not code.** Patterns now live in
  `sqlite_transit_sync/credential-triggers.json` and can be replaced via
  `secret_patterns_file`, so detection can be tightened over time without a release.
  Entries carry an optional `prefilter` literal for the SQL pre-filter; a pattern without
  one falls back to a full column read rather than silently missing rows.
- **Documented the escape hatch and the alternatives.** README (en/de) now lists every
  config key with its default, states that disabling the scan is a legitimate choice when
  you control the transit yourself, and points at real secret-distribution tools
  (Vaultwarden, SOPS+age, pass, KeePassXC over Syncthing, Infisical/OpenBao, platform
  keystores) so users stop trying to make a sync yard do that job.
- Added `[tool.setuptools.package-data]` so the trigger file reaches installed wheels.
- Version 0.2.0; `__version__` had drifted at 0.1.0 and now tracks `pyproject.toml`.

- **Dokumentation, SEO & Hygiene**: `llms.txt` Verifikations-Timestamp auf 2026-07-27 aktualisiert, Shields.io Badges in `README.md` & `README_de.md` auf 16/16 grüne Pytest-Tests angehoben, 100% grün verifiziert [G 2026-07-27].
- **Dokumentation & Hygiene**: `llms.txt` Verifikations-Timestamp (2026-07-26) aktualisiert, Testsuite-Verifizierung durchgeführt (8/8 Pytest passed).

## 0.1.1 — 2026-07-25

- Added root `llms.txt` for AI agent discovery, architecture context, and search index.
- Enhanced `README.md` & `README_de.md` with Shields.io badges, language switcher, and Mermaid sequence diagrams.
- Added `pythonpath = "."` to `[tool.pytest.ini_options]` in `pyproject.toml` for seamless test execution.
- Expanded GitHub topics and metadata URLs for improved discoverability.


## 0.1.0 — 2026-07-11

- Neutrale Extraktion aus BACH ProSync.
- SQLite-Backup-Snapshots, Manifest, SHA-256 und Integritätsprüfung.
- Primärschlüssel-basierter Timestamp-Merge mit Schema-Drift-Toleranz.
- Anpassbare Merge-Policy, Tabellen-Ausschlüsse und Snapshot-Redaktion.
- Python-API, JSON-CLI und eigenständige Tests.
- Englische und deutsche Vergleichstabellen zu Distributed SQL einschließlich
  Vor-/Nachteilen, Use Cases und Entscheidungshilfe ergänzt.
