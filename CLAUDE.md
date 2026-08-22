---
name: "sqlite-transit-sync"
type: project-docs
profile: "STANDARD"
version: 0.4.0
created: "2026-07-11"
updated: "2026-08-22"
reason_last_change: "Versionierte minimale Read-only-Projektionsverträge und Verifier"
last_verified: "2026-08-22"
release_status: "development"
visibility: "public-candidate"
author: "Lukas Geiger / ellmos / BACH Contributors"
anthropic_compatible: true
description: |
  Agent instructions for the standalone sqlite-transit-sync module.
---

# CLAUDE.md

## Projekt

Nutzerneutrales Python-Modul für lokalen SQLite-Abgleich über geprüfte
Transit-Snapshots und anpassbare Merge-Policies.

## Einstieg

1. `START.md`, `STATE.md` und `TODO.md` lesen.
2. Aktive `LOCK*.txt` beachten.
3. `python -m unittest discover -s tests -v` und `python -m pytest -q -ra`
   vor und nach Änderungen ausführen; die synthetischen JSON-CLI-Smokes gehören
   zur Testsuite.

## Harte Regeln

- Lebende SQLite-, WAL- oder SHM-Dateien niemals in einen Transportordner legen.
- Keine Benutzerpfade, Hostnamen, Datenbanken oder Credentials einbauen.
- Kein automatisches Erstkopieren einer fremden DB und keine Schema-Migration raten.
- Merge-State erst nach erfolgreichem Commit fortschreiben.
- Änderungen an Merge-Semantik in `DECISIONS.md` dokumentieren.
- Deutsche Dokumente verwenden echte Umlaute.

