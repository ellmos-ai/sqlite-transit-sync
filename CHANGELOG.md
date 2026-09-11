# Changelog

- **Pfad B Marketing, Discoverability, Visual Architecture & Metadata Contract Parity Upgrade:** Standardized bilingual 15-point Quick Navigation (`🧭 Quick Navigation` / `🧭 Schnellnavigation`) with 100% matching GitHub anchor slugs across `README.md` and `README_de.md`; codified formal Governance & Runtime Invariants (`INV-LOCAL-01` through `INV-SLA-10`) in Invariants Matrix; added dedicated sections for Third-Party Licenses & Transparency (`#third-party-licenses--transparency` / `#drittanbieter-lizenzen--transparenz`) and Marketing & Target Personas (`#marketing--target-personas` / `#marketing--zielgruppen`); added third-party audited and marketing log badges; audited `THIRD_PARTY_LICENSES.md` (date 2026-09-11, 100% permissive licenses, zero external runtime dependencies); expanded `MARKETING-LOG.txt` with 4 detailed personas (Autonomous AI Agent Engineers, Multi-Device/Cloud-Sync Developers, Local-First/Zero-Egress Tool Builders, Enterprise Security & Compliance Officers), bilingual high-intent search queries, 4-way competitive matrix, and sibling ecosystem mapping; expanded PEP 621 extended URLs (`Third-Party Licenses`, `Marketing Log`, `LLM Ready`) and set verbose pytest flags (`addopts = "-ra -v"`) in `pyproject.toml`; updated `llms.txt` verification timestamp to 2026-09-11; expanded metadata contract test suite in `tests/test_metadata.py` with tests for 15-point navigation anchors, governance invariants parity, marketing log contract, PEP 621 extended URLs, and third-party license audit [G 2026-09-11].

- **Security & Dependency Audit, Editable Install Repair & PEP 639 License Inventory:** Repaired broken editable install in system Python environment (pointed to removed worktree `sqlite-transit-sync-T-20260903-836395493-accounts` which raised `ModuleNotFoundError` on import; repointed to canonical clone `C:\_Local_DEV\repos\sqlite-transit-sync`); created `THIRD_PARTY_LICENSES.md` formally establishing the 100% local-first Zero-Runtime-Dependency invariant for core operations (`dependencies = []` in `pyproject.toml`) and detailing optional `[crypto]` (`cryptography>=42`) and development dependencies (`pytest`, `ruff`, `tomli`, `setuptools`, `wheel`, PSF standard library) with full license texts (MIT, Apache-2.0, BSD-3-Clause, PSF); declared PEP 639 `license-files = ["LICENSE", "THIRD_PARTY_LICENSES.md"]` in `pyproject.toml`; hardened `.gitignore` against multi-host sync conflicts (`*-conflict-*`, `*-WORKSTATION-LG.*`, `*-ASUS-GEI.*`, `*-LAPTOP.*`), secret/credential patterns (`*.token`, `*.secret`, `.npmrc`, `.pypirc`, `credentials.json`, `secrets.json`, `id_rsa*`, `id_ed25519*`), certificate/key patterns (`*.pem`, `*.key`, `*.pfx`, `*.p12`, `*.crt`, `*.cert`), and merge residues (`*.orig`, `*.rej`); updated `llms.txt`, `README.md`, and `README_de.md`; expanded contract test suite in `tests/test_metadata.py` with automated tests for license inventory, PEP 639 license-files, and gitignore security patterns [G 2026-09-10].

- **Canonical path containment:** Re-resolved mutable key paths at the Republica
  boundary and made sealed-envelope target assertions robust to macOS path aliases
  such as `/var` and `/private/var` [F 2026-09-09].
- **PEP 639 packaging compatibility:** Kept the SPDX `MIT` project license and
  removed the superseded license classifier so current isolated setuptools
  builds can install the package across the CI matrix [F 2026-09-09].
- **Read-only account-balance projection contract:** Added the versioned
  `accounts-balance-projection.v1` allowlist, synthetic initial/resume fixtures,
  privacy-field exclusions and a negative full-IBAN guard for the
  accounts-core publisher/OCEAN consumer boundary. No live application data,
  adapter, transport activation or consumer state is included [C 2026-09-09].
- **Pfad B Marketing, System Architecture & Metadata Parity Upgrade:** Standardized bilingual 14-point Quick Navigation (`🧭 Quick Navigation` / `🧭 Schnellnavigation`) with 100% matching GitHub anchor slugs; dual syntactically hardened Mermaid diagrams (Flowchart TD decoupled multi-node architecture with credential shield & Republica showcase layers, and 14-step end-to-end snapshot publication, boundary guard & transactional row-merge lifecycle sequence diagram); bilingual 10 Governance & Runtime Invariants table formally specifying offline snapshot atomicity, rollback journal cleanup, strict transit path containment, two-stage integrity verification, pre-publication credential shielding, HMAC envelope authenticity, and deterministic row-level merge; formalized 48-hour response SLA and 5-business-day triage commitment in both English and German sections of `SECURITY.md`; refreshed `llms.txt` verification timestamp to 2026-09-09; created local `MARKETING-LOG.txt` tracking discoverability baseline and sibling ecosystem integration; expanded contract test suite in `tests/test_metadata.py` with 6 new tests covering quick navigation anchors, dual mermaid diagrams, governance invariants matrix, security SLA triage, local marketing log, and sibling tools matrix (109 passed, 9 subtests | 100% green) [G 2026-09-09].
- **Repository-Hygiene, CI-Matrix, Supported Versions & Contract Tests:** CI-Workflow `.github/workflows/ci.yml` um Concurrency-Gruppe mit automatischem Abbruch veralteter Läufe (`cancel-in-progress: true`) und Multi-OS Matrix (`ubuntu-latest`, `windows-latest`, `macos-latest` über Python 3.10-3.13) mit `actions/checkout@v4` und `actions/setup-python@v5` gehärtet; `pyproject.toml` um vollständige PEP 621 `[project.urls]` (`Changelog`, `Security`, `Parent Organization`, `Umbrella Ecosystem`) erweitert; zweisprachige `SECURITY.md` um strukturierte Supported-Versions-Matrix (`0.4.x`), 48h Reaktions-SLA und offizielle Sicherheitskontakte (`security@ellmos.ai`, `support@lukasgeiger.com`, `security@open-bricks.org`, `lukas@open-bricks.org`) ausgebaut; `.gitignore` um Synchronisationskonfliktmuster (`*.sync-conflict-*`, `*.conflict`), Lockdateien (`LOCK*.txt`) und `.ruff_cache/` ergänzt; erweiterte 13-teilige Metadaten- und CI-Vertragstestsuite in `tests/test_metadata.py` (103 passed, 9 subtests passed | 100% grün); Shields.io Badges in `README.md` & `README_de.md` und maschinenlesbaren Kontext in `llms.txt` synchronisiert [G 2026-08-24].
- **Minimal read-only projection contracts:** Added two bundled, versioned
  medication/routine reminder projection allowlists, a generic read-only
  SQLite verifier, JSON CLI, synthetic offline/resume/tombstone fixtures and
  fail-closed privacy, provenance, loop, checkpoint and retention tests. No
  application adapter, live database, scheduler, migration or production
  activation is included; the complete synthetic suite passes 110/110
  [C 2026-08-22].
- **Discoverability, README-Design, Badges, Security & Metadata Parity Check:** Synchronized Shields.io badges in `README.md` and `README_de.md` (CI, Python 3.10-3.13, Platform, Privacy 100% Offline/Zero-Egress, Security Local-First/HMAC-Verified, Ecosystem `ellmos-ai`, Umbrella `open-bricks`, version `0.4.0`, tests `101/101 passed`), integrated second bilingual Mermaid sequence diagram for full verification/redaction/merge lifecycle, implemented hardened bilingual `SECURITY.md` with direct security contacts (`security@ellmos.ai` & `support@lukasgeiger.com`), added 16-repo Ecosystem & Sibling Tools cross-linking matrix, updated `pyproject.toml` with PEP 621 Classifiers, expanded contract test suite in `tests/test_metadata.py` (11/11 metadata tests, 101/101 suite passed, 100% green), synchronized `llms.txt`, `ellmos-module.json`, `ellmos-module.v2.json`, `METADATA_CONTRACT.md`, and `CLAUDE.md` [G 2026-08-21].
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
