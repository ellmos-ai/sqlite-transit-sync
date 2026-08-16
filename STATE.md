# STATE.md

**Stand:** 2026-08-16
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
- explizite State-/Transit-Trennung beim Config-/CLI-Aufbau
- TombstoneMergePolicy als opt-in Referenz für fachliche Löschungen
- SnapshotRetentionPolicy als opt-in, eigentumsgebundener Dry-Run-/Audit-Vertrag
- direkte Snapshot-Aufbewahrung über verifizierendes `cleanup`, standardmäßig Dry-Run
  und auf den lokalen Knoten begrenzt (ADR-014)
- gezielter Pull eines ausdrücklich ausgewählten Pending-Ausschnitts für dünne
  Lebenszyklus-Adapter, mit denselben Prüf-, Transaktions- und State-Gates (ADR-015)
- Synthetischer BACH-Golden-Vergleich mit absichtlich blockiertem Adapterstatus
- eigenständige synthetische Tests (96/96 passed, 100% grün)

## Noch nicht integriert

- BACH nutzt weiterhin seine bewährte interne ProSync-Implementierung.
- BACH-Kompatibilitätsadapter, autorisierte Golden-Referenzen, Schlüsselablage,
  Frische und fachliche Tombstone-Aufbewahrung bleiben anwendungsspezifisch.

## Letzte Dokumentationsänderung

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

- 2026-08-16: Pytest Testsuite (96/96 passed in 0.53s), `compileall` und Ruff 100% sauber.
- 2026-08-13: Retention-/Golden-Bundle synthetisch implementiert; die finale
  Test-, Ruff-, Compileall-, CLI- und Git-Readback-Verifikation durchgeführt.
- 2026-08-10: `python -m unittest discover -s tests -v` und `python -m pytest -q -ra` bestanden.
