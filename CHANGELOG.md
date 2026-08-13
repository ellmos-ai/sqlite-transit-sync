# Changelog

## Unreleased

- 2026-08-13: `SnapshotRetentionPolicy` und der versionierte
  `retention-report.v1`-Auditvertrag ergänzt. Die Policy ist opt-in und
  standardmäßig Dry-Run; nur verifizierte, eigene, nicht ausstehende und
  ausdrücklich bestätigte Snapshot-Paare können nach Alters-/Count-Regel
  geplant werden. Fremde, unbekannte, unvollständige und ungeprüfte Artefakte
  bleiben erhalten; Mutationen verifizieren direkt vor dem Löschen und sind
  idempotent. Synthetische Tests decken Grenzwerte, Restart, Audit und
  Löschfehler ab.
- 2026-08-13: Sieben synthetische BACH-Golden-Szenarien und der reproduzierbare
  Vergleich `scripts/compare_bach_golden.py` ergänzt. Der Bericht ist bis zu
  autorisierten BACH-Referenzergebnissen absichtlich
  `blocked_no_authorized_bach_golden`; kein Adapter oder BACH-Runtime-Zugriff
  wurde implementiert. Die lokale Sammlung umfasst 53 Tests.

- 2026-08-10: Optionalen `HMACSnapshotAuthenticator` mit kanonischer
  Manifest-Nutzlast, Sender-/Key-ID-Prüfung, Rotation und fail-closed
  Authentifizierungsfehlern ergänzt. `SyncConfig` weist State-Pfade im oder
  gleich dem Transit vor jedem Write zurück. `TombstoneMergePolicy` und die
  explizite `__sqlite_transit_tombstones`-Referenz mit Versions-/Retention-
  Vertrag bleiben von der Standard-LWW-Policy getrennt.
- Neue synthetische Adapter-, State-/CLI- und Multi-Node-Tombstone-Tests erhöhen
  die autoritative Sammlung auf 45; keine echten Schlüssel, Datenbanken,
  Transporte oder Veröffentlichungsaktionen verwendet.
- 2026-08-10: Version-, Status- und Verifikationsvertrag in
  `METADATA_CONTRACT.md` vereinheitlicht; Manifest-/Snapshot-Pfade werden vor
  Hash, SQLite-Prüfung und Merge auf direkten regulären Transit-Dateien
  begrenzt (inklusive Traversal-, Symlink- und Reparse-Regressionstests).
  Release-Gate, CI-Matrix und synthetische JSON-CLI-Smokes sind reproduzierbar
  beschrieben; der Gate-Status bleibt `LOCKED`, weil der vorgeschriebene
  externe Helper aktuell nicht auf dem autorisierten Commit steht.
- Vor dem Adapter-Bündel lag die Maintainer-Verifikation am 2026-08-10 bei
  34/34 Tests; sie ist durch den aktuellen 45-Test-Readback oben ersetzt.
- Maintainer-Verifikation am 2026-08-10: `unittest discover` und Pytest mit
  jeweils 26/26 bestanden, `compileall` und Ruff bestanden; CLI-Help
  (`--help`, `init --help`) sowie der Paket-Versions-Smoke
  (`__version__ == 0.2.0`) erfolgreich. Die CLI definiert keinen globalen
  `--version`-Schalter. Keine Live-Datenbank-, Transport-, Release- oder
  Cloud-Aktion.
- Maintainer-Verifikation am 2026-08-01: `unittest discover` und Pytest mit
  26/26 bestanden, `compileall` sowie CLI-Help und Versions-Smoke erfolgreich;
  `llms.txt`-Prüfdatum aktualisiert. Keine Release-Gate- oder Cloud-Aktion.
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
