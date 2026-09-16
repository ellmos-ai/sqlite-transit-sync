# STATE.md

**Stand:** 2026-09-15
**Phase:** Alpha / neutrale Extraktion abgeschlossen (v0.4.0)

## Funktionsfähig

- Republica-Modus: verschlüsselte Einweg-Verteilung (`publish`/`republica-import`),
  separate schreibgeschützte Replica je Quellknoten, kein Merge (ADR-006 bis ADR-008)
- kuratierter SQL-Dump mit korrektem Wiederherstellen von FTS-Volltextindizes
- Konfigurierbare Python-API und JSON-CLI
- geprüfte SQLite-Snapshots mit Manifest und SHA-256
- lokaler Pull-State je Knoten
- Primärschlüssel-basierter Timestamp-Merge
- Schema-Drift über gemeinsame Spalten
- Merge-Ausschlüsse und Snapshot-Redaktion
- Credential-Scan des Snapshot-Inhalts vor Veröffentlichung (fail-closed, ADR-005)
- optionaler HMAC-Snapshot-Authenticator mit kanonischem Manifest und Key-Rotation
- geheimnisfreie HMAC-Key-Referenzen mit injiziertem Resolver oder optionalem,
  lazy geladenem OS-Keyring-Resolver
- expliziter read-only Auth-Preflight für Manifest/Snapshot ohne SQLite-Öffnung,
  Merge oder State-Fortschreibung
- explizite State-/Transit-Trennung beim Config-/CLI-Aufbau
- TombstoneMergePolicy als opt-in Referenz für fachliche Löschungen
- SnapshotRetentionPolicy als opt-in, eigentumsgebundener Dry-Run-/Audit-Vertrag
- direkte Snapshot-Aufbewahrung über verifizierendes `cleanup`, standardmäßig Dry-Run
  und auf den lokalen Knoten begrenzt (ADR-014)
- gezielter Pull eines ausdrücklich ausgewählten Pending-Ausschnitts für dünne
  Lebenszyklus-Adapter, mit denselben Prüf-, Transaktions- und State-Gates (ADR-015)
- Synthetischer BACH-Golden-Vergleich mit absichtlich blockiertem Adapterstatus
- sechs versionierte minimale Read-only-Projektionsverträge mit generischem
  Allowlist-Verifier und synthetischen Offline-/Resume-/Tombstone-Fixtures
- eigenständige synthetische Tests (136/136 bestanden, 15 Subtests, 100 % grün)

## Noch nicht integriert

- BACH nutzt weiterhin seine bewährte interne ProSync-Implementierung.
- BACH-Kompatibilitätsadapter, autorisierte Golden-Referenzen, Schlüsselablage,
  Frische und fachliche Tombstone-Aufbewahrung bleiben anwendungsspezifisch.
- Publisher-Adapter für konkrete Anwendungen bleiben in deren kanonischen
  Quell-Repositories; dieses Modul enthält keine Quellabfrage oder Aktivierung.

## Letzte Dokumentationsänderung

- 2026-09-16: HausLagerist-Nachfüllprojektion mit validem lokalem Kalenderdatum
  und ohne Artikel-, Bestands-, Mengen- oder Bedarfsdetails ergänzt.
- 2026-09-16: AboTracker-Statusprojektion ohne Identitäts-, Kosten- oder
  abgeleitete Fälligkeitsfelder ergänzt und die fünf Verträge synchronisiert.
- 2026-09-15: Neutraler Auth-Preflight mit geheimnisfreien Key-Referenzen,
  injizierbarem Resolver und optionalem OS-Keyring dokumentiert.
- 2026-09-10: Security & Dependency Audit: Broken Editable Install repariert, PEP 639 license-files deklariert, THIRD_PARTY_LICENSES.md angelegt & .gitignore gehärtet (122 Tests).
- 2026-08-16: Discoverability, README-Design, Badges & Metadata Parity Check (v0.4.0, 96 Tests).
- 2026-08-13: Eigentumsgebundene Retention, Golden-Vergleich und die
  53-Test-Verifikation dokumentiert.
- 2026-08-10: Version-/Status-/Verifikationsvertrag, Release-Gate
  und fail-closed Manifest-/Snapshot-Containment in Code, Tests und
  Maintainer-Dokumenten fortgeschrieben.
- 2026-08-08: Konservative Bereinigung direkter Snapshots samt CLI, Tests und
  zweisprachiger Dokumentation ergänzt; sichere `pull_selected`-API ergänzt.
- 2026-07-11: `README.md` und `README_de.md` um den vollständigen Vergleich mit
  Distributed SQL, Vor-/Nachteile, Use Cases und Entscheidungshilfe ergänzt.

## Letzte Verifikation

- 2026-09-16: Pytest und Unittest jeweils 136/136 bestanden; Projektions- und
  Metadatentests 37/37, Ruff, Compileall, JSON- und Diff-Prüfung ohne Befund.
- 2026-09-16: Pytest und Unittest jeweils 134/134 bestanden; Projektions- und
  Metadatentests 35/35, Ruff, Compileall, JSON- und Diff-Prüfung ohne Befund.
- 2026-09-15: Pytest und Unittest jeweils 131/131 bestanden; fokussierte
  Auth-Tests 11/11, Metadaten-Tests 25/25, Ruff und Compileall ohne Befund.
- 2026-09-10: Pytest 122/122 bestanden (15 Subtests, 100 % grün); Broken Editable Install auf kanonischem Klon repariert; Pip-Check 0 defekte Requirements; Ruff 100% sauber; AST- und Regex-Scan 0 Secrets, 0 Path Leaks.
- 2026-08-22: Unittest und Pytest jeweils 110/110 grün; Compileall, Ruff,
  JSON-CLI-Verifier, Diff-, Secret-, Pfad- und Mojibake-Prüfung ohne Befund.
- 2026-08-16: Pytest Testsuite (96/96 passed in 0.53s), `compileall` und Ruff 100% sauber.
- 2026-08-13: Retention-/Golden-Bundle synthetisch implementiert; die finale
  Test-, Ruff-, Compileall-, CLI- und Git-Readback-Verifikation durchgeführt.
- 2026-08-10: `python -m unittest discover -s tests -v` und `python -m pytest -q -ra` bestanden.
