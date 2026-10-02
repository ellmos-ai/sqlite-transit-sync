# Contributing to sqlite-transit-sync / Mitwirken an sqlite-transit-sync

[English](#english) | [Deutsch](#deutsch)

---

<a id="english"></a>
## English

Thank you for your interest in contributing to **sqlite-transit-sync** (`ellmos-ai/sqlite-transit-sync`), a local-first SQLite synchronization engine through verified snapshots and configurable row-level merge policies built with Python 3.10+ standard library.

### 1. Architectural Principles & 10 Governance Invariants

All contributions must strictly adhere to our core architectural invariants:

1. **Local-First & Zero Egress (`INV-LOCAL-01`)**: 100% offline-ready operation. Zero outbound telemetry, network tracking, analytics, or mandatory cloud infrastructure. All data remains exclusively within local SQLite databases and local transit directories.
2. **Offline Snapshot Atomicity (`INV-SNAP-02`)**: Non-locking consistent snapshot capture via `sqlite3.backup`, published through atomic `os.replace`. Live operational databases are never synced directly.
3. **Rollback Journal Clean Isolation (`INV-ROLL-03`)**: Snapshots are closed cleanly in rollback-journal mode; fail-closed purge of temporary `-wal`, `-shm`, and `-journal` sidecars before publication.
4. **Strict Transit Path Containment (`INV-PATH-04`)**: Absolute rejection of directory traversal (`../`), absolute paths, symbolic links, and reparse points in manifests and snapshots.
5. **Two-Stage Integrity & Sanity (`INV-VERIFY-05`)**: Pre-merge validation via cryptographic SHA-256 manifest matching and SQLite `PRAGMA quick_check`.
6. **Pre-Publication Credential Shield (`INV-SHIELD-06`)**: Content-level regex scanning across 13+ secret families (`credential-triggers.json`) with mandatory push abort upon secret detection.
7. **HMAC Authenticity Envelope (`INV-HMAC-07`)**: Optional HMAC-SHA256 signature envelope over canonical manifest payload, sender ID, and trust anchors.
8. **Deterministic Row-Level Merge (`INV-MERGE-08`)**: Transactional row-level merge (Last-Write-Wins per primary key, shared column union for schema drift, explicit tombstone policy).
9. **Conservative Retention Scoping (`INV-RET-09`)**: Snapshot cleanup is dry-run by default, scoped strictly to authorized local-node artifacts.
10. **Non-Elevation & Multi-OS Parity (`INV-SLA-10`)**: Pure `RunAsInvoker` unprivileged execution across Linux, Windows, and macOS without administrative elevation. Binding 48-hour security response SLA via `security@ellmos.ai`, `security@open-bricks.org`, and `support@lukasgeiger.com`.

### 2. Plan D Local Development Workflow

In accordance with our cross-system architecture (Plan D), the local git repository at `C:\_Local_DEV\repos\sqlite-transit-sync` serves as the authoritative **Source of Truth**. Development, testing, and commits must take place exclusively in the canonical local clone. Cloud mirrors (e.g. OneDrive) serve solely as gitless read projections.

```bash
# Clone or navigate to the canonical local clone
cd C:\_Local_DEV\repos\sqlite-transit-sync

# Verify git status and branch
git status
git branch --show-current

# Run full test suite with isolated basetemp
pytest

# Verify code formatting and linting
ruff check .
```

### 3. Version Freeze Discipline (`T-20260920-167562623`)

sqlite-transit-sync operates under strict version-freeze discipline. The version identifier (`0.4.0` in `pyproject.toml`, `sqlite_transit_sync/__init__.py`, and manifests) must not be arbitrarily incremented. All improvements, bug fixes, and hygiene adjustments are documented under `## [Unreleased]` in `CHANGELOG.md`.

### 4. Quality Gates

Before submitting a pull request or pushing commits, verify all local quality gates:

1. `pytest`: 100% green test execution across all unit, contract, projection, and regression suites.
2. `ruff check .`: Zero lint errors.
3. `python -m compileall -q .`: Zero bytecode compilation errors.
4. `git diff --check`: Zero whitespace or line-ending anomalies.
5. `git diff -G"version = "`: Zero unauthorized version modifications.

### 5. Statutory Notice (§ 521 BGB) & Zero-Copyleft on User Data

This software is provided free of charge under the permissive MIT License. In accordance with German statutory law (**§ 521 BGB** — *Haftung des Schenkers*), liability for defects in quality and title is strictly limited to intentional misconduct (*Vorsatz*) and gross negligence (*grobe Fahrlässigkeit*).

**Zero-Copyleft Guarantee:** Processing, synchronizing, redacting, or validating databases using sqlite-transit-sync does **not** subject user databases, schema definitions, or exported snapshots to any viral or copyleft licensing obligation. All user data remains 100% private and proprietary.

---

<a id="deutsch"></a>
## Deutsch

Vielen Dank für dein Interesse an einer Mitwirkung bei **sqlite-transit-sync** (`ellmos-ai/sqlite-transit-sync`), einer Local-First-Synchronisations-Engine für SQLite-Datenbanken über verifizierte Snapshots und konfigurierbare zeilenbasierte Merge-Policies, implementiert mit der Python 3.10+ Standardbibliothek.

### 1. Architektur-Prinzipien & 10 Governance-Invarianten

Alle Beiträge müssen unsere verbindlichen Kern-Invarianten strikt einhalten:

1. **Local-First & Zero Egress (`INV-LOCAL-01`)**: 100% Offline-Betrieb. Keine ausgehende Telemetrie, kein Tracking, keine Analyse-Dienste und keine Cloud-Pflicht. Alle Daten verbleiben ausnahmslos in lokalen SQLite-Datenbanken und lokalen Transit-Verzeichnissen.
2. **Offline Snapshot-Atomizität (`INV-SNAP-02`)**: Sperrfreie konsistente Snapshot-Erstellung mittels `sqlite3.backup`, atomare Bereitstellung über `os.replace`. Live-Datenbanken werden niemals direkt synchronisiert.
3. **Rollback-Journal Isolierung (`INV-ROLL-03`)**: Snapshots werden im Rollback-Journal-Modus sauber geschlossen; Fail-Closed Bereinigung temporärer `-wal`, `-shm` und `-journal` Sidecars vor der Veröffentlichung.
4. **Strikte Transit-Pfadeindämmung (`INV-PATH-04`)**: Striktes Abweisen von Directory Traversal (`../`), absoluten Pfaden, symbolischen Links und Reparse Points in Manifesten und Snapshots.
5. **Zweistufige Integritätsprüfung (`INV-VERIFY-05`)**: Vor dem Merge erfolgt eine Validierung über kryptografische SHA-256 Manifest-Abgleiche und SQLite `PRAGMA quick_check`.
6. **Credential-Schutz vor Veröffentlichung (`INV-SHIELD-06`)**: Regex-Inhaltsscan über 13+ Secret-Familien (`credential-triggers.json`) mit zwingendem Push-Abbruch bei Funden.
7. **HMAC-Authentizitätsumschlag (`INV-HMAC-07`)**: Optionaler HMAC-SHA256 Signaturumschlag über kanonische Manifest-Nutzdaten, Absender-IDs und Vertrauensanker.
8. **Deterministischer zeilenbasierter Merge (`INV-MERGE-08`)**: Transaktionaler zeilenbasierter Merge (Last-Write-Wins je Primärschlüssel, Schnittmengen-Spaltenabgleich bei Schema-Drift, explizite Tombstone-Policy).
9. **Konservative Aufbewahrungs-Scoping (`INV-RET-09`)**: Bereinigung erfolgt standardmäßig als Dry-Run und ist strikt auf autorisierte lokale Knotenartefakte begrenzt.
10. **Rechtefreier Betrieb & Multi-OS-Parität (`INV-SLA-10`)**: Reiner `RunAsInvoker`-Betrieb unter Linux, Windows und macOS ohne Administratorrechte. Verbindliche 48-Stunden-Sicherheitsreaktions-SLA via `security@ellmos.ai`, `security@open-bricks.org` und `support@lukasgeiger.com`.

### 2. Plan D Lokaler Entwicklungsworkflow

Gemäß unserer systemweiten Architektur (Plan D) bildet das lokale Git-Repository unter `C:\_Local_DEV\repos\sqlite-transit-sync` die alleinige maßgebliche **Source of Truth**. Entwicklung, Tests und Commits finden ausschließlich im kanonischen lokalen Klon statt. Cloud-Spiegel (z. B. OneDrive) dienen rein als gitlose Leseprojektionen.

```bash
# Kanonischen lokalen Klon verwenden
cd C:\_Local_DEV\repos\sqlite-transit-sync

# Git-Status und Branch prüfen
git status
git branch --show-current

# Testsuite mit isoliertem basetemp ausführen
pytest

# Code-Qualität und Linting prüfen
ruff check .
```

### 3. Version Freeze Disziplin (`T-20260920-167562623`)

sqlite-transit-sync unterliegt einer strikten Version-Freeze-Disziplin. Der Versionsbezeichner (`0.4.0` in `pyproject.toml`, `sqlite_transit_sync/__init__.py` und Manifesten) darf nicht eigenmächtig erhöht werden. Sämtliche Verbesserungen, Fehlerbehebungen und Hygiene-Anpassungen werden unter `## [Unreleased]` in `CHANGELOG.md` erfasst.

### 4. Qualitäts-Tore

Vor dem Erstellen eines Pull Requests oder dem Pushen von Commits müssen alle lokalen Qualitäts-Tore erfolgreich durchlaufen werden:

1. `pytest`: 100% grün über alle Unit-, Contract-, Projektions- und Regressionssuiten.
2. `ruff check .`: Null Linting-Fehler.
3. `python -m compileall -q .`: Null Bytecode-Kompilierungsfehler.
4. `git diff --check`: Null Whitespace- oder Zeilenumbruch-Probleme.
5. `git diff -G"version = "`: Null unautorisierte Versionsänderungen.

### 5. Gesetzlicher Hinweis (§ 521 BGB) & Zero-Copyleft auf Nutzerdaten

Diese Software wird unentgeltlich unter der permissiven MIT-Lizenz bereitgestellt. Gemäß **§ 521 BGB** (*Haftung des Schenkers*) ist die Haftung für Sach- und Rechtsmängel auf Vorsatz und grobe Fahrlässigkeit beschränkt.

**Zero-Copyleft Garantie:** Das Verarbeiten, Synchronisieren oder Bereinigen von Datenbanken mit sqlite-transit-sync unterwirft Anwendungsdatenbanken, Schemata oder exportierte Snapshots **keiner** Copyleft-Lizenzpflicht. Alle Nutzerdaten bleiben zu 100% privat und geschützt.
