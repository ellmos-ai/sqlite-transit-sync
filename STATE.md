# STATE.md

**Stand:** 2026-08-10
**Phase:** Alpha / neutrale Extraktion abgeschlossen

## Funktionsfähig

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
- eigenständige synthetische Tests

## Noch nicht integriert

- BACH nutzt weiterhin seine bewährte interne ProSync-Implementierung.
- Retention, Schlüsselablage, Frische und fachliche Tombstone-Aufbewahrung bleiben
  anwendungsspezifisch.

## Letzte Dokumentationsänderung

- 2026-08-10: Version-/Status-/Verifikationsvertrag, gesperrtes Release-Gate
  und fail-closed Manifest-/Snapshot-Containment in Code, Tests und
  Maintainer-Dokumenten fortgeschrieben.
- 2026-07-11: `README.md` und `README_de.md` um den vollständigen Vergleich mit
  Distributed SQL, Vor-/Nachteile, Use Cases und Entscheidungshilfe ergänzt.

## Letzte Verifikation

- 2026-08-10: `python -m unittest discover -s tests -v` und
  `python -m pytest -q -ra` — jeweils 45/45 bestanden; `python -m pytest
  --collect-only -q` sammelte 45 Tests (Auth 4, CLI 3, Metadaten 6, Sync 29,
  Tombstone 3). `compileall` und Ruff bestanden; CLI-Help, synthetische
  JSON-Smokes, State-/Transit-Fehlerfälle und die Multi-Node-Tombstone-/Auth-
  Fälle bestanden ebenfalls. Der vorgeschriebene externe Hygiene-Helper wurde nicht
  als bestanden gewertet: sein SHA-256 stimmt, aber der aktuelle
  `modules-meta`-Commit ist `89834a01d6d340d74aac96490f92dfd8706b10b9` statt
  des autorisierten Commits `d8475c29c4da7a0008853e2755e1b6a012c9b791`.
  Der aktuelle 45-Test-Receipt ist an den Implementierungs-Commit
  `0dc9935f5e2298e3b1867ef163a6dd4f478dd12c` gebunden; der frühere
  34-Test-Receipt auf `c946ea787b36c8c8caad5315c8ef88cd37f357cb` ist nur noch
  historische Evidenz.
  Der direkte Push-Versuch wurde nach Readback von `origin/main` mit
  `non-fast-forward` (Exit 1) abgewiesen; wegen der divergierenden fremden
  Historie wurden weder Pull, Merge, Rebase noch Force-Push ausgeführt. Keine
  Live-Datenbank, kein Transport, kein Release und kein Cloud-Upload.
- 2026-08-08: `python -m unittest discover -s tests -v` — 26/26 bestanden;
  der Arbeitsbaum blieb sauber. Pytest, `compileall` und der CLI-Smoke wurden
  in diesem Lauf nicht erneut ausgeführt.
- 2026-08-01: `python -m unittest discover -s tests -v` — 26/26 bestanden.
- 2026-08-01: `python -m pytest -q -ra` — 26/26 bestanden; `compileall` und
  der CLI-Smoke (`init --help`, Version `0.2.0`) ebenfalls erfolgreich.
