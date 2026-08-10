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
- eigenständige synthetische Tests

## Noch nicht integriert

- BACH nutzt weiterhin seine bewährte interne ProSync-Implementierung.
- Es gibt noch keinen Signatur-/Authentifizierungsadapter.
- Retention und Tombstones bleiben anwendungsspezifisch.

## Letzte Dokumentationsänderung

- 2026-08-10: Lokale Maintainer-Verifikation in `STATE.md`, `llms.txt` und
  `CHANGELOG.md` fortgeschrieben.
- 2026-07-11: `README.md` und `README_de.md` um den vollständigen Vergleich mit
  Distributed SQL, Vor-/Nachteile, Use Cases und Entscheidungshilfe ergänzt.

## Letzte Verifikation

- 2026-08-10: `python -m unittest discover -s tests -v` und
  `python -m pytest -q -ra` — jeweils 26/26 bestanden; `compileall` und Ruff
  bestanden ebenfalls. CLI-Help (`python -m sqlite_transit_sync --help` und
  `init --help`) sowie der Paket-Versions-Smoke (`__version__ == 0.2.0`)
  bestanden. Der globale CLI-Aufruf `--version` ist nicht definiert und wird
  nicht als unterstütztes Feature behauptet; keine Live-Datenbank oder kein
  Transport wurde verwendet.
- 2026-08-08: `python -m unittest discover -s tests -v` — 26/26 bestanden;
  der Arbeitsbaum blieb sauber. Pytest, `compileall` und der CLI-Smoke wurden
  in diesem Lauf nicht erneut ausgeführt.
- 2026-08-01: `python -m unittest discover -s tests -v` — 26/26 bestanden.
- 2026-08-01: `python -m pytest -q -ra` — 26/26 bestanden; `compileall` und
  der CLI-Smoke (`init --help`, Version `0.2.0`) ebenfalls erfolgreich.
