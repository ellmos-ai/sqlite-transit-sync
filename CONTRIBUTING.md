# Contributing to sqlite-transit-sync / Mitwirken an sqlite-transit-sync

[English](#english) | [Deutsch](#deutsch)

---

<a id="english"></a>
## English

Thank you for your interest in contributing to **sqlite-transit-sync** (`ellmos-ai/sqlite-transit-sync`), a local-first SQLite synchronization engine through snapshots checked against SHA-256 manifests and SQLite `PRAGMA quick_check`, with configurable row-level merge policies, built with the Python 3.10+ standard library.

### 1. Architectural Principles & 10 Governance Invariants

All contributions must strictly adhere to our core architectural invariants:

1. **Local SQLite Processing & Configured Transit (`INV-LOCAL-01`)**: Reads local SQLite databases and exchanges snapshot files through the configured filesystem path. The path may be shared or network-mounted; host, mount and transport behavior are outside this module.
2. **Offline Snapshot Atomicity (`INV-SNAP-02`)**: Online consistent snapshot capture via `sqlite3.backup`, published through atomic `os.replace`. Live operational databases are never synced directly.
3. **Rollback Journal Clean Isolation (`INV-ROLL-03`)**: Snapshots are closed cleanly in rollback-journal mode; fail-closed purge of temporary `-wal`, `-shm`, and `-journal` sidecars before publication.
4. **Strict Transit Path Containment (`INV-PATH-04`)**: Absolute rejection of directory traversal (`../`), absolute paths, symbolic links, and reparse points in manifests and snapshots.
5. **Two-Stage Integrity & Sanity (`INV-VERIFY-05`)**: Pre-merge validation via cryptographic SHA-256 manifest matching and SQLite `PRAGMA quick_check`.
6. **Pre-Publication Credential Pattern Scan (`INV-SHIELD-06`)**: By default, snapshot content is checked against configured vendor-prefixed patterns. A match aborts publication and reports `table.column`, not the value. This is a safety net, not a guarantee; bespoke or unprefixed secrets can pass, and a clean scan means only that no known pattern matched. See `SECURITY.md`.
7. **Optional HMAC Sender Authentication (`INV-HMAC-07`)**: An API-injected shared-key HMAC-SHA256 authenticator can verify the canonical manifest and sender when configured. Without it, SHA-256 verifies only that the snapshot bytes match the manifest; it does not authenticate the sender. HMAC is not a freshness protocol or a public-key signature.
8. **Deterministic Row-Level Merge (`INV-MERGE-08`)**: Transactional row-level merge (Last-Write-Wins per primary key, shared column union for schema drift, explicit tombstone policy).
9. **Conservative Retention Scoping (`INV-RET-09`)**: Snapshot cleanup is dry-run by default, scoped strictly to authorized local-node artifacts.
10. **Process Permissions & Security Policy (`INV-SLA-10`)**: The process inherits the operating-system permissions of its launcher; this project does not enforce standard-user mode or request elevation. Valid reports can be sent to security@ellmos.ai, security@open-bricks.org, or support@lukasgeiger.com. `SECURITY.md` acknowledges valid reports within 48 hours and provides triage assessments within 5 business days, with progress updates until a patch is released.

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

<a id="5-statutory-notice-521-bgb-zero-copyleft-on-user-data"></a>
### 5. Statutory Notice (§ 521 BGB) & Project License Scope

This software is provided free of charge under the permissive MIT License. In accordance with German statutory law (**§ 521 BGB** — *Haftung des Schenkers*), liability for defects in quality and title is strictly limited to intentional misconduct (*Vorsatz*) and gross negligence (*grobe Fahrlässigkeit*).

**Project license inventory and user data:** The repository’s dependency inventory lists declared package-license identifiers. It does not determine licensing obligations, if any, for an integrating application’s databases, schemas, exports, or snapshots. It is not a legal opinion or a guarantee about user data; review obligations for your use case.

---

<a id="deutsch"></a>
## Deutsch

Vielen Dank für dein Interesse an einer Mitwirkung bei **sqlite-transit-sync** (`ellmos-ai/sqlite-transit-sync`), einer Local-First-Synchronisations-Engine für SQLite-Datenbanken mit SHA-256-Manifest- und SQLite-`PRAGMA quick_check`-Prüfungen sowie konfigurierbaren zeilenbasierten Merge-Policies, implementiert mit der Python-3.10+-Standardbibliothek.

### 1. Architektur-Prinzipien & 10 Governance-Invarianten

Alle Beiträge müssen unsere verbindlichen Kern-Invarianten strikt einhalten:

1. **Lokale SQLite-Verarbeitung & konfigurierter Transit (`INV-LOCAL-01`)**: Liest lokale SQLite-Datenbanken und tauscht Snapshot-Dateien über den konfigurierten Dateisystempfad aus. Dieser kann freigegeben oder netzwerkgestützt sein; Host, Mount und Transport liegen außerhalb des Moduls.
2. **Offline Snapshot-Atomizität (`INV-SNAP-02`)**: Konsistente Online-Snapshot-Erstellung mittels `sqlite3.backup`, atomare Bereitstellung über `os.replace`. Live-Datenbanken werden niemals direkt synchronisiert.
3. **Rollback-Journal Isolierung (`INV-ROLL-03`)**: Snapshots werden im Rollback-Journal-Modus sauber geschlossen; Fail-Closed Bereinigung temporärer `-wal`, `-shm` und `-journal` Sidecars vor der Veröffentlichung.
4. **Strikte Transit-Pfadeindämmung (`INV-PATH-04`)**: Striktes Abweisen von Directory Traversal (`../`), absoluten Pfaden, symbolischen Links und Reparse Points in Manifesten und Snapshots.
5. **Zweistufige Integritätsprüfung (`INV-VERIFY-05`)**: Vor dem Merge erfolgt eine Validierung über kryptografische SHA-256 Manifest-Abgleiche und SQLite `PRAGMA quick_check`.
6. **Scan konfigurierter Credential-Muster (`INV-SHIELD-06`)**: Snapshot-Inhalte werden standardmäßig anhand konfigurierter, präfixbasierter Muster geprüft. Bei einem Treffer wird die Veröffentlichung abgebrochen und `table.column`, nicht der Wert, gemeldet. Der Scan ist ein Sicherheitsnetz, keine Garantie; individuelle oder nicht präfixierte Geheimnisse können unentdeckt bleiben. Ein sauberer Scan bedeutet nur, dass kein bekanntes Muster passte. Siehe `SECURITY.md`.
7. **Optionale HMAC-Absenderauthentifizierung (`INV-HMAC-07`)**: Ein per API injizierter Shared-Key-HMAC-SHA256-Authenticator kann das kanonische Manifest und den Absender bei entsprechender Konfiguration prüfen. Ohne ihn stellt SHA-256 nur fest, dass die Snapshot-Bytes mit dem Manifest übereinstimmen; der Absender wird dadurch nicht authentifiziert. HMAC ist kein Frischeprotokoll und keine Public-Key-Signatur.
8. **Deterministischer zeilenbasierter Merge (`INV-MERGE-08`)**: Transaktionaler zeilenbasierter Merge (Last-Write-Wins je Primärschlüssel, Schnittmengen-Spaltenabgleich bei Schema-Drift, explizite Tombstone-Policy).
9. **Konservative Aufbewahrungs-Scoping (`INV-RET-09`)**: Bereinigung erfolgt standardmäßig als Dry-Run und ist strikt auf autorisierte lokale Knotenartefakte begrenzt.
10. **Prozessrechte & Sicherheitsrichtlinie (`INV-SLA-10`)**: Der Prozess übernimmt die Betriebssystemrechte seines Aufrufers; das Projekt erzwingt keinen Standardbenutzermodus und fordert keine Rechteerhöhung an. Gültige Meldungen können an security@ellmos.ai, security@open-bricks.org oder support@lukasgeiger.com gesendet werden. `SECURITY.md` sagt zu, gültige Meldungen innerhalb von 48 Stunden zu bestätigen und innerhalb von 5 Werktagen eine Triage-Einschätzung zu geben, mit regelmäßigen Statusmeldungen bis zur Veröffentlichung eines Patches.

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

<a id="5-gesetzlicher-hinweis-521-bgb-zero-copyleft-auf-nutzerdaten"></a>
### 5. Gesetzlicher Hinweis (§ 521 BGB) & Lizenzumfang des Projekts

Diese Software wird unentgeltlich unter der permissiven MIT-Lizenz bereitgestellt. Gemäß **§ 521 BGB** (*Haftung des Schenkers*) ist die Haftung für Sach- und Rechtsmängel auf Vorsatz und grobe Fahrlässigkeit beschränkt.

**Projektinventar und Nutzerdaten:** Das Abhängigkeitsinventar des Repositorys erfasst Lizenzkennzeichen deklarierter Pakete. Es legt nicht fest, welche Lizenzpflichten für Datenbanken, Schemata, Exporte oder Snapshots einer integrierenden Anwendung gelten. Es ist weder Rechtsgutachten noch Zusicherung zur Lizenzlage von Nutzerdaten; prüfe die für deinen Anwendungsfall geltenden Verpflichtungen.
