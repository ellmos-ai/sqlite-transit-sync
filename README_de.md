# sqlite-transit-sync

<img src="assets/banner.png" width="100%" alt="Sqlite Transit Sync banner">

[![CI](https://github.com/ellmos-ai/sqlite-transit-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/ellmos-ai/sqlite-transit-sync/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.4.0-blue.svg)](CHANGELOG.md)
[![Code style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Tests](https://img.shields.io/badge/tests-123%20passed%20%7C%2015%20subtests%20%7C%20100%25%20green-brightgreen.svg)](#tests)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-informational.svg)](#)
[![Privacy](https://img.shields.io/badge/privacy-100%25%20Offline%20%7C%20Zero--Egress-brightgreen.svg)](#)
[![Security](https://img.shields.io/badge/security-Local--First%20%7C%20HMAC--Verified-blue.svg)](SECURITY.md)
[![Security SLA](https://img.shields.io/badge/security%20SLA-48h%20SLA-blue.svg)](SECURITY.md)
[![Third-Party: Audited](https://img.shields.io/badge/third--party-audited%20%7C%20100%25%20permissive-brightgreen.svg)](THIRD_PARTY_LICENSES.md)
[![Marketing Log: Active](https://img.shields.io/badge/marketing%20log-active-blue.svg)](MARKETING-LOG.txt)
[![License](https://img.shields.io/github/license/ellmos-ai/sqlite-transit-sync)](LICENSE)
[![Ecosystem: ellmos-ai](https://img.shields.io/badge/Ecosystem-ellmos--ai-blue.svg)](https://github.com/ellmos-ai)
[![Umbrella: open-bricks](https://img.shields.io/badge/Umbrella-open--bricks-purple.svg)](https://github.com/open-bricks)
[![llms.txt](https://img.shields.io/badge/llms.txt-available-informational.svg)](llms.txt)

> [!NOTE]
> **Kontext für LLMs und KI-Agenten**: Ein strukturierter maschinenlesbarer Verzeichnisbaum, ein Architekturüberblick und ein API-Leitfaden stehen unter [`llms.txt`](llms.txt) bereit.

**🇬🇧 [English Version](README.md)** | **🛡️ [Sicherheitsrichtlinie](SECURITY.md)** | **📝 [Changelog](CHANGELOG.md)** | **📋 [llms.txt](llms.txt)**

## 🧭 Schnellnavigation

- [Was ist sqlite-transit-sync?](#was-ist-sqlite-transit-sync)
- [Systemarchitektur & Topologie](#systemarchitektur-topologie)
- [End-to-End Snapshot- und Synchronisations-Lebenszyklus](#end-to-end-snapshot--und-synchronisations-lebenszyklus)
- [Governance- & Laufzeit-Invarianten-Matrix](#governance--laufzeit-invarianten-matrix)
- [Teil der ellmos-Stack-Familie](#teil-der-ellmos-stack-familie)
- [Eigenschaften & Kernfähigkeiten](#eigenschaften)
- [Installation & Voraussetzungen](#installation)
- [Kurzstart & Arbeitsablauf](#kurzstart)
- [Konfigurationsreferenz](#konfiguration)
- [Republica — die Schaufenster-Methode](#republica-die-schaufenster-methode)
- [Python-API & Erweiterungspunkte](#python-api)
- [Vergleich mit Distributed SQL](#vergleich-mit-distributed-sql)
- [Sicherheit und Grenzen](#sicherheit-und-grenzen)
- [Drittanbieter-Lizenzen & Transparenz](#drittanbieter-lizenzen--transparenz)
- [Marketing & Zielgruppen](#marketing--zielgruppen)

## Was ist sqlite-transit-sync?

Die Autorität für Version, Modulstatus, Sichtbarkeit und Prüfdatum steht in
[`METADATA_CONTRACT.md`](METADATA_CONTRACT.md); daraus folgt keine Freigabe
für Veröffentlichung oder Upload.

Local-first-Synchronisierung für unabhängige SQLite-Datenbanken über geprüfte
Snapshots und von der Anwendung wählbare Merge-Policies. Das Modul wurde aus der
BACH-ProSync-Architektur extrahiert und enthält keine Abhängigkeiten von BACH,
OneDrive, Rechnernamen oder Benutzerpfaden.

Dies ist **kein verteilter SQL-Server**. Jeder Knoten besitzt und öffnet nur seine
lokale Datenbank. Ein gemeinsamer Ordner, ein eingebundener Object Store, ein
Wechseldatenträger oder ein anderer Dateitransport überträgt geschlossene Snapshots
mit Manifesten. Beim Pull wird ein Snapshot geprüft und innerhalb einer Transaktion
in die lokale Datenbank zusammengeführt.

Passt gut zu [sync-master](https://github.com/dev-bricks/sync-master) aus derselben
Modulfamilie: Ein sync-master-Yard ist ein natürlicher Transit-Transport. Dazu wird
`--transit` auf eine werkzeugeigene Zone `db-transit/<namespace>/` im Yard gesetzt
(dort Protokollregel R9). sync-master transportiert die Dokumente, dieses Modul
verantwortet Datenbankintegrität und Merge; beide bleiben unabhängig.

## Systemarchitektur & Topologie

Das folgende Diagramm visualisiert die entkoppelte Multi-Knoten-Architektur, bei der lokale SQLite-Datenbanken ausschließlich über geschlossene, validierte Snapshot-Bündel im Transitspeicher synchronisiert werden:

```mermaid
flowchart TD
    subgraph NODE_A ["Publisher-Knoten (Host A)"]
        DB_A[("Lokale SQLite-DB<br/>(app.db)")]
        BACKUP_A["Online-Backup-API<br/>(sqlite3.backup)"]
        REDACT_A["Tabellen-Redaktion &<br/>VACUUM-Engine"]
        SHIELD_A["Credential-Shield-Scanner<br/>(13+ Erkennungsmuster)"]
        HMAC_A["HMAC-SHA256-Signierer<br/>(Schlüsselbund)"]
        STATE_A["Lokales Status-Ledger<br/>(node-state.json)"]
    end

    subgraph TRANSIT ["Geteilte Transit-Zone (Yard / Transport)"]
        SNAP["Geschlossener atomarer Snapshot<br/>(*.snapshot.sqlite)"]
        SIG["HMAC-Signatur-Umschlag<br/>(Kanonisches Manifest)"]
        HASH["SHA-256 Digest<br/>(*.manifest.json)"]
        RETENTION["Aufbewahrungs-Engine<br/>(Konservative Bereinigung)"]
    end

    subgraph NODE_B ["Subscriber-Knoten (Host B)"]
        GUARD_B["Pfad-Traversierungsschutz<br/>(Fail-Closed Root)"]
        VERIFY_B["Integritäts- & HMAC-Prüfer<br/>(SHA-256 + HMAC)"]
        SANITY_B["SQLite PRAGMA quick_check<br/>(Konsistenzprüfung)"]
        MERGE_B["Zeilenweises Merge-Engine<br/>(LWW / Tombstones / Drift)"]
        DB_B[("Lokale SQLite-DB<br/>(app.db)")]
        STATE_B["Lokales Status-Ledger<br/>(node-state.json)"]
    end

    subgraph SHOWCASE ["Showcase-Schicht (Republica-Modus)"]
        REP_EXP["SQL-Dump & Gzip<br/>(Kuratierter Export)"]
        REP_FER["Fernet-Verschlüsselung<br/>(AES-128-CBC + HMAC)"]
        REP_RO[("Read-Only Showcase-DB<br/>(republica_root/)")]
    end

    DB_A --> BACKUP_A
    BACKUP_A --> REDACT_A
    REDACT_A --> SHIELD_A
    SHIELD_A --> HMAC_A
    HMAC_A --> SNAP
    HMAC_A --> SIG
    HMAC_A --> HASH
    SNAP --- TRANSIT
    SIG --- TRANSIT
    HASH --- TRANSIT
    TRANSIT --> RETENTION

    SNAP --> GUARD_B
    SIG --> GUARD_B
    HASH --> GUARD_B
    GUARD_B --> VERIFY_B
    VERIFY_B --> SANITY_B
    SANITY_B --> MERGE_B
    MERGE_B --> DB_B
    MERGE_B --> STATE_B
    HMAC_A -.-> STATE_A

    DB_A -.-> REP_EXP
    REP_EXP --> REP_FER
    REP_FER --> REP_RO
```

## End-to-End Snapshot- und Synchronisations-Lebenszyklus

Der End-to-End-Lebenszyklus stellt sicher, dass Live-Datenbanken niemals Dateisystem-Sperren von Synchronisationsdiensten ausgesetzt werden und sämtliche knotenübergreifenden Daten kryptografisch verifiziert, geheimnisfrei und transaktional zusammengeführt werden:

```mermaid
sequenceDiagram
    autonumber
    participant App as Anwendung / Knoten A
    participant CoreA as sqlite-transit-sync (Push)
    participant Shield as Credential-Shield
    participant Transit as Shared Transit (db-transit)
    participant CoreB as sqlite-transit-sync (Pull)
    participant Target as Lokale DB / Knoten B

    Note over App,CoreA: Phase 1: Lokaler Online-Snapshot & Redaktion
    App->>CoreA: push(config, db)
    CoreA->>CoreA: Online-Snapshot via SQLite Backup API
    CoreA->>CoreA: Ausgeschlossene Tabellen leeren & VACUUM
    CoreA->>Shield: Inhalts-Scan auf Secret-Muster (credential-triggers.json)
    Shield-->>CoreA: Scan OK (0 Zugangsdaten erkannt)

    Note over CoreA,Transit: Phase 2: Kryptografische Versiegelung & atomare Publikation
    CoreA->>CoreA: SHA-256 Digest & HMAC-Umschlag berechnen
    CoreA->>Transit: Temporären Snapshot schreiben & atomarer os.replace
    CoreA->>Transit: Geprüftes Manifest schreiben (*.manifest.json)

    Note over Transit,CoreB: Phase 3: Transit-Erfassung & Grenzkontrolle
    CoreB->>Transit: Manifeste erkennen & Pfadgrenzen prüfen (Anti-Traversierung)
    CoreB->>CoreB: HMAC-Signatur & SHA-256 Digest verifizieren
    CoreB->>CoreB: PRAGMA quick_check auf isoliertem Snapshot ausführen

    Note over CoreB,Target: Phase 4: Transaktionales Zeilen-Merge & Status-Aktualisierung
    CoreB->>Target: BEGIN IMMEDIATE Transaktion starten
    CoreB->>Target: Zeilenweises Merge ausführen (LWW pro PK / Tombstones)
    CoreB->>Target: Schema-Drift bei gemeinsamen Spalten abgleichen
    CoreB->>Target: Transaktion mit COMMIT abschließen
    CoreB->>CoreB: Lokalen Status fortschreiben (node-state.json)
    Note over Target: Lokale Eventual Consistency garantiert
```

## Governance- & Laufzeit-Invarianten-Matrix

`sqlite-transit-sync` erzwingt 10 verbindliche Governance- und Laufzeit-Invarianten für verlässliche Datenintegrität, Isolation und Sicherheit:

| # | Invariante | Architektur-Ebene | Garantie & Durchsetzungs-Mechanismus |
|---|---|---|---|
| 1 | **INV-LOCAL-01: 100% Local-First & Zero-Egress** | Systemarchitektur | Arbeitet ausschließlich auf lokalen SQLite-Datenbankdateien (`app.db`). Keine Telemetrie, keine ausgehenden Netzwerkaufrufe, keine Cloud-Abhängigkeiten. |
| 2 | **INV-SNAP-02: Offline-Snapshot-Atomarität** | Transit-Veröffentlichung | Live-Datenbanken werden niemals über File-Sync geteilt. Snapshots entstehen via `sqlite3.backup` und werden per atomarem `os.replace` publiziert. |
| 3 | **INV-ROLL-03: Rollback-Journal & Sidecar-Bereinigung** | Sidecar-Schutz | Snapshots werden strikt im Rollback-Journal-Modus geschlossen; alle temporären SQLite-Sidecars (`-wal`, `-shm`, `-journal`) werden fail-closed vor Manifest-Erstellung bereinigt. |
| 4 | **INV-PATH-04: Strikte Pfadkapselung & Traversierungsschutz** | Dateisystemgrenze | Manifest- und Snapshot-Pfade müssen direkte reguläre Dateien im Transit-Wurzelordner sein. Traversierungsversuche (`../`), Symlinks und Reparse-Points scheitern fail-closed. |
| 5 | **INV-VERIFY-05: Zweistufige Integritäts- und Konsistenzprüfung** | Vorab-Validierung | Jeder empfangene Snapshot muss die kryptografische SHA-256-Prüfung sowie `PRAGMA quick_check` fehlerfrei durchlaufen, bevor Tabellen inspiziert oder zusammengeführt werden. |
| 6 | **INV-SHIELD-06: Inhaltsbezogener Zugangsdaten-Schutz (Credential Shield)** | Inhaltsprüfung | Snapshot-Inhalte werden vor Publikation auf 13+ Secret-Muster (`credential-triggers.json`) gescannt. Erkannte Secrets brechen den Push ab (`table.column`, ohne Preisgabe des Werts). |
| 7 | **INV-HMAC-07: HMAC-Authentifizierungs-Umschlag** | Identität & Nachweisbarkeit | Optionaler HMAC-SHA256-Signaturumschlag über kanonische Manifest-Payloads (Protokoll, Namespace, Absender, Dateiname, SHA-256, Größe, Redaktion) mit In-Memory-Schlüsselbund. |
| 8 | **INV-MERGE-08: Deterministisches zeilenweises Merge** | Daten-Konvergenz | Transaktionales Zeilen-Merge (LWW pro PK, Spaltenschnittmenge bei Schema-Drift, optionale Tombstone-Tabelle). Hash-Tie-Breaker sorgt für deterministische Konvergenz. |
| 9 | **INV-RET-09: Konservative Aufbewahrung & Autorisierung** | Bereinigung | Bereinigungsroutinen laufen standardmäßig als Dry-Run und beschränken sich auf den lokalen Knoten. Fremdknoten-Löschung (`--all-nodes`) erfordert explizite Autorisierung. |
| 10 | **INV-SLA-10: Unprivilegierte Ausführung & Multi-OS-Parität** | Plattform-Laufzeit | Läuft vollständig im Benutzermodus (RunAsInvoker). Strikte Plattformparität unter Linux, Windows und macOS ohne externe Binärabhängigkeiten mit 48h Sicherheits-SLA. |

## Teil der ellmos-Stack-Familie

`sqlite-transit-sync` ist ein Companion-Modul zu
[dev-bricks/sync-master](https://github.com/dev-bricks/sync-master) aus derselben
Modulfamilie: sync-master verantwortet den Dateitransport (`sync.files`), dieses
Modul die Datenbankintegrität und den Merge (`sync.database`). Beide sind
eigenständig oder als Teil von Stacks aus der
[ellmos-ai](https://github.com/ellmos-ai)-Familie nutzbar; siehe den
[ellmos-ai/stacks](https://github.com/ellmos-ai/stacks)-Katalog. Seine Rolle in
diesem Baukasten: kein Live-SQLite über Dateisynchronisierung, sondern ausschließlich
geprüfte Snapshots mit von der Anwendung wählbaren Merge-Policies.

## Eigenschaften

- konsistente Online-Snapshots über die SQLite-Backup-API;
- atomare Veröffentlichung über eine temporäre Datei und `os.replace`;
- geschlossene Snapshots im Rollback-Journal-Modus mit Fail-closed-Bereinigung aller
  temporären SQLite-Sidecars vor der Veröffentlichung;
- Manifest- und Snapshot-Pfade sind auf direkte reguläre Dateien im kanonischen
  Transit-Verzeichnis begrenzt; Traversierung, absolute Pfade, Symlinks und
  Reparse-Punkte werden vor Hash, Prüfung und Merge fail-closed abgewiesen;
- SHA-256-Manifest und Prüfung mit `PRAGMA quick_check`;
- optionale, per API injizierte HMAC-SHA256-Authentifizierung über kanonisches
  Manifest, Senderidentität, Protokollversion und Snapshot-Hash mit Schlüssel-IDs;
- lokaler Pull-Zustand je Knoten und idempotente Wiederholung;
- zeilenweises Last-write-wins pro Primärschlüssel für Tabellen mit Zeitstempel;
- eine optionale Referenz-Policy `TombstoneMergePolicy` für ausdrücklich
  gespeicherte Löschungen;
- Merge gemeinsamer Spalten für grundlegende Toleranz gegenüber Schema-Drift;
- konfigurierbare Tabellenausschlüsse und Snapshot-Redaktion mit anschließendem
  `VACUUM`;
- inhaltsbezogener Credential-Scan, der die Veröffentlichung abbricht, wenn ein
  Snapshot weiterhin zugangsdatenähnliche Werte enthält (standardmäßig aktiv;
  gemeldet wird `table.column`, niemals der Wert selbst);
- eigene `MergePolicy` für fachliche Regeln, Tombstones oder CRDTs;
- Bereinigung geprüfter Snapshots mit Dry-Run als Standard, standardmäßiger Begrenzung
  auf den lokalen Knoten sowie ausdrücklichen Freigaben für Löschung und Verwaltung
  fremder Knoten;
- strikte versionierte Read-only-Projektionsverträge mit exakten Schema- und
  Datenschutz-Allowlists sowie Provenienz-, Checkpoint-, Loop- und
  Offline-Tombstone-Prüfung;
- optionaler [Republica-Schaufenster-Modus](#republica--die-schaufenster-methode), der eine Datenbank
  einseitig als verschlüsselte Nutzlast verteilt und als eigenständige,
  schreibgeschütztes Schaufenster materialisiert, statt sie zu mergen;
- Python-API und JSON-CLI ohne zusätzliche Laufzeitabhängigkeiten (der Republica-Modus
  ergänzt `cryptography`).

## Installation

```bash
python -m pip install -e .
```

## Kurzstart

Auf jedem Knoten wird eine Konfiguration angelegt. Jeder Knoten verwendet seine
eigene Datenbank und Zustandsdatei, aber dasselbe Transit-Verzeichnis und denselben
Namespace.

```bash
sqlite-transit-sync init \
  --config node.json \
  --database ./app.db \
  --transit ./shared-transit \
  --node-id laptop \
  --namespace my-app

sqlite-transit-sync push --config node.json
sqlite-transit-sync pull --config node.json --dry-run
sqlite-transit-sync pull --config node.json
sqlite-transit-sync status --config node.json
sqlite-transit-sync verify --config node.json
sqlite-transit-sync cleanup --config node.json
# JSON-Plan prüfen und anschließend ausdrücklich anwenden:
sqlite-transit-sync cleanup --config node.json --apply
```

Das Anwendungsschema muss auf jedem Knoten bereits existieren. Ein automatisches
Erstkopieren ist absichtlich deaktiviert, weil ein generisches Modul nicht
entscheiden kann, welches Schema, welche Secrets, lokalen Tabellen oder Migrationen
zu einer Anwendung gehören.

## Read-only-Anwendungsprojektionen

`verify-projection` prüft eine geschlossene, anwendungseigene SQLite-Projektion,
ohne zu kopieren, zu mergen, zu migrieren, einen Scheduler zu starten oder
Zustand fortzuschreiben. Die Anwendung übergibt ihre Consumer-Identität und das
geprüfte maximale Offline-Intervall. Der Verifier weist Loops, veraltete
Checkpoints, zu kurze Tombstone-Aufbewahrung, nicht erlaubte Tabellen oder
Spalten sowie nicht opake Datensatzreferenzen zurück.

Mitgeliefert werden drei enge Verträge für Kontostandsübersichten,
Medikamenten-Fälligkeiten und Bestandswarnungen sowie für Routinen-Fälligkeiten
und Abschlussstatus: `accounts-balance-projection.v1`,
`mediplaner-reminder-projection.v1` und `routinika-reminder-projection.v1`. Die
Test-Fixtures sind synthetische JSON-Rezepte; Quell-IDs, vollständige IBANs,
Kontonummern, Inhaberdaten, Medikamentendetails, Notizen und Medien sind keine
Vertragsfelder. Siehe
[Read-only-Projektionsverträge](PROJECTION_CONTRACTS_de.md) und die
[englische Begleitdatei](PROJECTION_CONTRACTS.md).

```bash
sqlite-transit-sync verify-projection \
  --contract mediplaner-reminder-projection.v1 \
  --database ./closed-projection.sqlite \
  --consumer-id reminder-consumer \
  --minimum-offline-seconds 2592000 \
  --previous-checkpoint 41
```

## Konfiguration

```json
{
  "database": "./app.db",
  "transit": "./shared-transit",
  "state": "./node-state.json",
  "node_id": "laptop",
  "namespace": "my-app",
  "timestamp_columns": ["updated_at", "modified_at", "created_at"],
  "exclude_tables": ["secrets", "sqlite_sequence"],
  "snapshot_exclude_tables": ["secrets"],
  "scan_snapshot_for_secrets": true,
  "secret_scan_skip_tables": [],
  "secret_scan_extra_patterns": [],
  "secret_patterns_file": null
}
```

Relative Pfade werden vom Speicherort der Konfigurationsdatei aus aufgelöst. Die
aktive Datenbank darf niemals innerhalb des Transit-Verzeichnisses liegen; die
Zustandsdatei muss außerhalb des Transitbaums liegen. `SyncConfig`,
`from_file`, `from_bytes` und CLI-`init` weisen einen ungültigen Zustandspfad
vor jeder Transit- oder Zustandsdatei zurück und führen keine Migration aus.

Anwendungen, die einen Audit-Hash für genau die eingelesene Konfiguration benötigen,
können die Bytes einmal lesen und mit demselben quellrelativen Parser verwenden,
ohne die Datei ein zweites Mal einzulesen:

```python
import hashlib
from pathlib import Path

from sqlite_transit_sync import SyncConfig

config_path = Path("node.json").resolve()
payload = config_path.read_bytes()
config = SyncConfig.from_bytes(payload, source_path=config_path)
config_sha256 = hashlib.sha256(payload).hexdigest()
```

### Alle Schlüssel und ihre Standardwerte

| Schlüssel | Standardwert | Bedeutung |
|---|---|---|
| `database` | *(erforderlich)* | Aktive SQLite-Datenbank dieses Knotens |
| `transit` | *(erforderlich)* | Gemeinsames Verzeichnis für Snapshots und Manifeste |
| `state` | `./.sync-state.json` | Pull-Zustand dieses Knotens; außerhalb des Transits aufbewahren |
| `node_id` | Rechnername | Identifiziert den veröffentlichenden Knoten in Snapshot-Namen |
| `namespace` | `"default"` | Trennt unabhängige Datensätze innerhalb eines Transits |
| `timestamp_columns` | `["updated_at","modified_at","created_at"]` | Für Last-write-wins geprüfte Spalten |
| `exclude_tables` | `["secrets","sqlite_sequence"]` | Tabellen, die niemals in die lokale Datenbank **gemergt** werden |
| `snapshot_exclude_tables` | `["secrets"]` | Tabellen, deren Zeilen vor der Veröffentlichung aus dem Snapshot **gelöscht** werden, gefolgt von `VACUUM` |
| `scan_snapshot_for_secrets` | `true` | Bricht die Veröffentlichung ab, wenn der Snapshot-Inhalt weiterhin wie Zugangsdaten aussieht |
| `secret_scan_skip_tables` | `[]` | Tabellen, die der Scan auslässt; bei einer einzelnen störenden Tabelle besser als die vollständige Abschaltung |
| `secret_scan_extra_patterns` | `[]` | Zusätzliche reguläre Ausdrücke, ergänzend zur Trigger-Datei |
| `secret_patterns_file` | `null` (mitgelieferte Datei) | Pfad zu einer eigenen Trigger-Datei; **ersetzt** die eingebauten Muster |
| `key_file` | `null`, sonst `$SQLITE_TRANSIT_SYNC_KEY_FILE` | Fernet-Schlüssel für den Republica-Modus; muss außerhalb des Transits liegen |
| `republica_root` | `~/.republica` | Ablageort importierter Schaufenster; muss außerhalb des Transits liegen |
| `allow_key_in_synced_folder` | `false` | Hebt die Prüfung auf, die einen Schlüssel in einem Cloud-Ordner ablehnt |

Der `state`-Standardwert in dieser Tabelle gilt, wenn eine JSON-Konfiguration ohne
diesen Schlüssel geladen wird. `sqlite-transit-sync init` schreibt ohne `--state`
stattdessen `.<config-stem>-state.json` (für `node.json`: `.node-state.json`).

### Der Credential-Scan und wie man ihn abschaltet

`snapshot_exclude_tables` kann nur Tabellen entfernen, die bereits bekannt sind.
Der Scan beantwortet die darüber hinausgehende Frage: *Sind Zugangsdaten in einer
Freitextspalte gelandet* – etwa in einer Notiz, Logzeile oder Sitzungszusammenfassung?
Er läuft nach der Redaktion und vor der Veröffentlichung auf der Snapshot-Kopie.
Bei einem Treffer löst er einen `SyncError` mit `table.column` aus; der gefundene
Wert wird niemals ausgegeben und gelangt daher nicht in Logs, Tracebacks oder
CI-Ausgaben. Der unvollständige Snapshot wird verworfen, sodass nichts das
Transit-Verzeichnis erreicht.

**Das Abschalten ist eine legitime Entscheidung**, kein Notbehelf. Wer den
Transport selbst kontrolliert und ihm vertraut – eigener Server, EU-gehostetes
Volume unter eigenem Vertrag oder verschlüsselter Wechseldatenträger – und
Zugangsdaten bewusst mit den Daten transportieren möchte, setzt:

```json
{ "scan_snapshot_for_secrets": false }
```

Wenn nur eine Tabelle Fehlalarme erzeugt, sollte `secret_scan_skip_tables` verwendet
werden. Der Schutz bleibt dann für alle anderen Tabellen aktiv.

### Trigger anpassen

Die Muster liegen als Daten statt im Code unter
`sqlite_transit_sync/credential-triggers.json`. Dadurch lässt sich die Erkennung
verschärfen, ohne auf ein Release zu warten:

```json
{
  "version": 1,
  "patterns": [
    { "name": "github", "regex": "gh[pousr]_[A-Za-z0-9]{16,}", "prefilter": "gh" },
    { "name": "acme-internal", "regex": "ACME-[0-9]{4}", "prefilter": "ACME-" }
  ]
}
```

- `prefilter` ist ein optionales Literal für einen schnellen SQL-`LIKE`-Vorfilter,
  damit große Snapshots schnell bleiben. Es **muss** in jedem Wert vorkommen, auf
  den der reguläre Ausdruck passt; andernfalls werden Funde übersehen. Fehlt ein
  solches Literal, wird die gesamte Spalte gelesen, damit die Prüfung korrekt bleibt.
- Mit `secret_patterns_file` ersetzt eine eigene Datei die Standardmuster
  vollständig; `secret_scan_extra_patterns` ergänzt sie.

Die Muster sind bewusst herstellerpräfixiert. Eine allgemeine Regel für „lange
hexadezimale Zeichenfolgen“ würde Prüfsummen, UUIDs und Git-SHAs erfassen, obwohl
diese legitime Datenbankinhalte sind. Ein Scanner mit vielen Fehlalarmen wird
abgeschaltet und schützt dann gar nicht mehr. Ein sauberer Scan bedeutet „kein
bekanntes Muster gefunden“, niemals „dieser Snapshot enthält garantiert keine
Secrets“.

## Republica — die Schaufenster-Methode

Jede Maschine stellt ein **verschlüsseltes Schaufenster** ihrer Datenbank in eine geteilte
Dateifläche. Alle anderen können hineinsehen, niemand kann es verändern. Daher der Name: eine
Wiederveröffentlichung der Datenbank, lesbar nur für den, der den Schlüssel hat.

Zu verwenden, wenn `push`/`pull` nicht passt: Man möchte *lesen*, was ein anderer Knoten
weiß, ohne es in die eigenen Zeilen einzurechnen — oder die Maschinen teilen nichts als einen
Ordner (kein Server, keine offenen Ports, kein Vertrauens-Setup), und dieser Ordner soll die
Inhalte nicht im Klartext sehen.

### Zwei Betriebsarten, bewusst redundant

Republica ist **keine Übergangslösung, bis ein richtiger Tunnel steht.** Es ist die zweite
von zwei Betriebsarten, die nebeneinander laufen sollen, damit der Ausfall der einen die
andere nicht stoppt:

| Ausfall | Direkter Abgleich (`push`/`pull`) | Republica |
|---|---|---|
| Eine Maschine schläft oder ist offline | steht still (kein Gegenüber) | läuft weiter — jetzt ablegen, später abholen |
| VPN/SSH tot, Netz blockiert den Tunnel | steht still | läuft weiter über die Dateifläche |
| Schlüsselrotation oder Trust-Setup offen | steht still | läuft weiter mit dem geteilten Schlüssel |
| Geteilter Ordner kaputt, voll oder desynchron | läuft weiter | steht still |
| Keine Merge-Regel für einen Datensatz vereinbart | nicht anwendbar | läuft weiter — es wird nichts gemergt |

Der ganze Nutzen liegt darin, dass es an dem Tag funktioniert, an dem der andere Weg es nicht
tut. Also eingerichtet lassen und mitlaufen lassen, auch wenn der direkte Weg gerade
problemlos läuft.

### Einrichtungskosten: ein einziger Schlüsseltransfer

Der geteilte Schlüssel muss die anderen Maschinen über **irgendeinen Kanal erreichen, der
nicht der Transportweg selbst ist** — ein bestehender verschlüsselter Tunnel, ein
Passwortmanager, ein USB-Stick, telefonisch vorgelesen. Einmal. Danach genügt ein schlichter
geteilter Ordner, dauerhaft, selbst einer, dem man nicht vertraut.

```text
republica_root/
  laptop/my-app.sqlite      <- schreibgeschütztes Schaufenster der Laptop-Datenbank
  workstation/my-app.sqlite <- schreibgeschütztes Schaufenster der Workstation-Datenbank
```

```bash
# Einmalig, auf lokaler Platte - nie im Transit, nie in einem Cloud-Ordner.
# Diese Datei dann out-of-band auf die anderen Maschinen kopieren; dort NICHT keygen aufrufen.
sqlite-transit-sync keygen --key-file ~/.keys/republica.key

sqlite-transit-sync init --config node.json \
  --database ./app.db --transit ./shared-transit \
  --node-id laptop --namespace my-app \
  --key-file ~/.keys/republica.key

sqlite-transit-sync republica-publish --config node.json   # verschlüsseln und veröffentlichen
sqlite-transit-sync republica-list    --config node.json   # was andere Knoten anbieten
sqlite-transit-sync republica-import  --config node.json   # lokal materialisieren
```

Benötigt die optionale Verschlüsselung: `pip install 'sqlite-transit-sync[crypto]'`.

**Übertragen wird** keine Datenbankdatei, sondern ein kuratierter SQL-Dump, gzip-komprimiert
und Fernet-verschlüsselt. Bei einer realen 53,6-MB-Wissensdatenbank sind das 11,0 MB im
Transit, weil die Interna des Volltextindex beim Import neu aufgebaut statt mitgeschickt
werden (35.370 von 49.636 Dump-Anweisungen). Die Veröffentlichung durchläuft dieselbe
Prüfkette wie ein Merge-Snapshot: Redaktion, Credential-Scan, `quick_check`, Manifest.

**Was das schützt:** Der Transport sieht nur Chiffretext, und Fernets HMAC erkennt eine
absichtliche Änderung selbst dann, wenn der Manifest-Hash passend nachgerechnet wurde.

**Was nicht:** Fernet authentifiziert den *Schlüssel*, nicht den *Absender* – wer ihn
besitzt, kann einen gültigen Snapshot veröffentlichen. Genau deshalb bleibt eine Replica
getrennt und wird nie gemergt. Der Schlüssel gehört nicht in den Transportweg: ein Schlüssel
im Transitverzeichnis wird abgelehnt, ebenso einer in einem erkennbar synchronisierten
Ordner (abschaltbar über `allow_key_in_synced_folder`). Dasselbe gilt für `republica_root` –
eine entschlüsselte Replica im Transit würde im Klartext weiterverteilt.

**Grenze:** Ein Volltextindex ohne eigenen Inhalt (`content=''`) lässt sich nicht neu
aufbauen, weil die Quelle dafür fehlt. Solche Tabellen meldet das Manifest unter
`contentless_fts`, statt still leer anzukommen.

### Sealed Envelope: eine Datei, derselbe Kanal, niemals eine Datenbank

Das Henne-Ei-Problem: Zwei Maschinen teilen *noch* keinen sicheren Kanal — und genau deshalb
muss ein Zugangsdatum hinüber. Derselbe Schlüssel und derselbe Ordner befördern auch eine
einzelne verschlüsselte Datei.

```bash
sqlite-transit-sync envelope-send    --config node.json --file ./api-token.txt --label api-token
sqlite-transit-sync envelope-receive --config node.json --into ~/credentials
```

Die Datei kommt **als Datei** an (Rechte `0600`), benannt `<quellknoten>__<dateiname>`, und
landet **nie in einer Datenbank** — ein Geheimnis in einer Datenbank wird von jedem Backup,
jedem Index und jeder Synchronisierung weiterkopiert, die sie berührt. In Notizen gehört der
Fundort, niemals das Geheimnis selbst.

Zwei Regeln des Schaufensters sind hier bewusst umgekehrt: Der **Credential-Scan gilt nicht**
(er würde genau die Fracht blockieren, die befördert werden soll), und der Umschlag wird nach
dem Empfang **aus dem Transit entfernt**, damit ein Geheimnis nicht im geteilten Ordner liegen
bleibt. Das Entpacken in den Transit oder in einen erkennbar cloud-synchronisierten Ordner
wird verweigert, und der Dateiname wird beim Empfang erneut entschärft, damit ein
manipuliertes Manifest nicht außerhalb des Zielverzeichnisses schreiben kann.

Das ist ein Kurier, kein Passwort-Manager und keine Dateisynchronisierung — wenige, kleine
Umschläge.

## Das hier ist kein Passwort-Manager

Der Scan **entfernt** Zugangsdaten aus dem Synchronisierungsweg. Er **verteilt** sie
nicht. Wenn das eigentliche Problem lautet „meine Rechner benötigen dieselben
Passwörter oder API-Schlüssel“, ist dieses Modul das falsche Werkzeug – ebenso wie
jeder Dokumenten-Synchronisierungsordner. Stattdessen sollte einer der folgenden
Ansätze verwendet werden; alle halten Klartext von einem nicht selbst
kontrollierten Anbieter fern:

| Ansatz | Geeignet für | Hinweise |
|---|---|---|
| **Vaultwarden** (selbst gehostetes Bitwarden) | Menschen und CLI auf mehreren Rechnern | Läuft auf einem kleinen ständig aktiven Rechner; Zugriff über ein privates Netz wie WireGuard oder Tailscale statt über eine öffentliche Freigabe. Offizielle Bitwarden-Clients, Browser-Erweiterungen und die `bw`-CLI funktionieren damit, sodass auch Skripte und Agenten Secrets abrufen können. |
| **SOPS + age** | Secrets neben dem Code | Verschlüsselte Dateien können sicher committet oder in beliebige Synchronisierungsordner gelegt werden, weil nur Chiffrat übertragen wird. Unterstützt Schlüssel je Empfänger und eignet sich gut für Git-Reviews. |
| **`pass`** (GPG) + Git | Unix-orientierte Einzelnutzer und kleine Teams | Eine Datei pro Secret, normales Git-Remote, kein Server erforderlich. |
| **KeePassXC-Datenbank über Syncthing** | kein Server, kein Cloud-Konto | Peer-to-Peer-Dateisynchronisierung; der Tresor bleibt eine einzelne verschlüsselte Datei. |
| **Infisical / OpenBao (Vault-Fork)** | Teams, Maschinenidentitäten und Rotation | Echte Secret-Server mit Audit-Logs und dynamischen Zugangsdaten; mehr bewegliche Teile, als ein Haushalt benötigt. |
| **Plattformeigene Speicher** | ein Rechner, eine Anwendung | macOS-Schlüsselbund, Windows DPAPI/Anmeldeinformationsverwaltung, `systemd-creds` oder der Secret-Store der CI. Kein Abgleich, aber auch keine Offenlegung. |

Unabhängig von der Wahl bleibt dieselbe Trennung entscheidend: **ein Kanal für
Daten, ein anderer für Zugangsdaten.** Die Aufgabe dieses Moduls besteht darin,
sicherzustellen, dass der erste Kanal nicht unbemerkt zum zweiten wird – genau das
erzwingt der Scan.

## Python-API

```python
from sqlite_transit_sync import SyncConfig, TransitSync

sync = TransitSync(SyncConfig.from_file("node.json"))
snapshot = sync.push()
pending = sync.pending()
selected_reports = sync.pull_selected([pending[-1].path.name]) if pending else []
reports = sync.pull()
cleanup_plan = sync.cleanup()
print(
    snapshot.sha256,
    [report.as_dict() for report in reports],
    [report.as_dict() for report in selected_reports],
    cleanup_plan,
)
```

`pull_selected()` verarbeitet nur ausdrücklich benannte, aktuell ausstehende Snapshots und nutzt
dabei dieselben Prüf-, Merge- und State-Gates wie `pull()`. Damit können dünne Lebenszyklus-
Adapter beispielsweise bewusst nur den neuesten zulässigen Fremdstand ziehen, ohne die
Datenmechanik zu kopieren.

Wenn Timestamp-LWW nicht ausreicht, kann `TransitSync` ein Objekt erhalten, das
`MergePolicy.merge(local, remote, snapshot)` implementiert.

### Optionale authentifizierte Manifeste

Eine integrierende Anwendung kann einen eigenen Authenticator injizieren; JSON-
Konfiguration und CLI transportieren niemals Schlüsselmaterial:

```python
from sqlite_transit_sync import HMACKey, HMACSnapshotAuthenticator, TransitSync

auth = HMACSnapshotAuthenticator(
    keys={"node-a-v2": HMACKey(sender="node-a", secret=key_store.read_bytes())},
    active_key_id="node-a-v2",
    trusted_senders={"node-a"},
)
sync = TransitSync(config, authenticator=auth)
```

Die Referenzimplementierung nutzt Shared-Key-HMAC-SHA256, keine nicht
abstreitbaren Public-Key-Signaturen. Die kanonische Nutzlast umfasst Protokoll,
Namespace, Knoten, Snapshotname, SHA-256, Größe, Redaktionsliste sowie
Algorithmus-/Schlüssel-/Sender-/Vertrauensquellen-Header. Alte Schlüssel bleiben während einer
Rotation im Verifier-Keyring. Ein konfigurierter Verifier weist fehlende,
fehlerhafte, fremde oder nicht passende Signaturen vor Prüfung/Merge zurück;
ein bereits gepullter Replay ist über den State ein No-op, aber keine
Frischegarantie. Ein Leser ohne Adapter behauptet keine Authentizität.

### Tombstone-Referenz-Policy

Für fachliche Löschungen richtet die Anwendung mit `ensure_tombstone_table()`
explizit das Schema ein und verwendet `TombstoneMergePolicy`. Die reservierte
Tabelle speichert `table_name`, ein kanonisches JSON-Array der Primärschlüsselwerte
und `deleted_at` als Löschversion. Ein Tombstone gewinnt bei Gleichstand und gegen
ältere Zeilen; ein späterer Zeitstempel darf den Schlüssel wiederbeleben. Die
Policy leitet niemals aus einer fehlenden Zeile eine Löschung ab und bereinigt
Tombstones nicht automatisch. Aufbewahrung muss daher das maximale Offline-
Intervall abdecken; Schema-Migrationen werden nicht geraten.

### Opt-in-Aufbewahrung von Snapshots

Die Aufbewahrung ist ausdrücklich und standardmäßig ein Dry-Run. Eine Löschung
wird nie aus einem Dateinamen abgeleitet: Nur ein geprüfter Snapshot im
konfigurierten Namespace, im Besitz des aktuellen Knotens, nicht mehr pending
und durch den Callback `acknowledge` bestätigt, kann löschbar werden. Fremde,
unbekannte, unvollständige, ungeprüfte und nicht bestätigte Artefakte bleiben
erhalten. Die Altersgrenze ist strikt (`Alter > max_age`); `keep_latest` und
`max_age` dürfen kombiniert werden.

```python
from datetime import timedelta
from sqlite_transit_sync import SnapshotRetentionPolicy

policy = SnapshotRetentionPolicy(
    max_age=timedelta(days=30),
    keep_latest=3,
    acknowledge=lambda snapshot: application_has_acked(snapshot),
)
report = sync.apply_retention(policy, dry_run=True, audit_path="retention-report.json")
# Erst nach Prüfung der exakten Pfade und Gründe mutieren:
report = sync.apply_retention(policy, dry_run=False, audit_path="retention-report.json")
```

Vor jeder geplanten Löschung wird das Paar erneut gelesen und geprüft. Gelöscht
werden nur die beiden exakten Dateien; Fehler werden protokolliert, aber es gibt
keine breite Bereinigung. Wiederholte Läufe sind idempotent. Sidecars und
unvollständige Artefakte bleiben erhalten. Das ist ein neutraler Kernvertrag
und kein BACH-Retention-Adapter.

### Golden-Vergleich für BACH-Kompatibilität

Vor jedem BACH-Kompatibilitätsadapter wird der synthetische, versionierte
Vergleich ausgeführt:

```bash
python scripts/compare_bach_golden.py --output golden/bach_compatibility_report.json
```

Die sieben Fixtures decken geschlossenen Backup, Manifest-/Integritätsfehler,
Redaktion/Secret-Abbruch, Timestamp-/Schema-Merge, Pull-Bestätigung,
Rollback und Retention-Eigentum ab. Der Bericht bleibt bewusst
`blocked_no_authorized_bach_golden`, bis für jedes Szenario ein autorisiertes
BACH-Referenzergebnis vorliegt. Daraus folgt weder ein Adapter noch eine
Kompatibilitätsbehauptung.

## Vergleich mit Distributed SQL

| Aspekt | `sqlite-transit-sync` | Distributed SQL, zum Beispiel CockroachDB oder YugabyteDB |
|---|---|---|
| Grundmodell | Jeder Knoten besitzt eine unabhängige lokale SQLite-Datenbank | Alle Server bilden gemeinsam eine logische SQL-Datenbank |
| Schreibzugriff | Zunächst lokal, später synchronisiert | Direkt durch den Cluster koordiniert |
| Synchronisierung | Asynchroner Snapshot-Pull mit Zeilen-Merge | Laufende Replikation zwischen Clusterknoten |
| Konsistenz | Eventual Consistency nach erfolgreichem Austausch | Üblicherweise starke oder serialisierbare Konsistenz |
| Konsens und Quorum | Nicht erforderlich | Meist Raft-basierter Mehrheitskonsens |
| Globale Transaktionen | Nein | Ja, auch über mehrere Knoten oder Shards |
| Konfliktbehandlung | Anwendungsspezifische `MergePolicy`; standardmäßig Timestamp-LWW | Transaktionen, MVCC, Sperren und Konsens |
| Offline-Betrieb | Ein Knoten kann unabhängig weiter lesen und schreiben | Schreibzugriffe benötigen normalerweise ein erreichbares Quorum |
| Netzwerkausfall | Lokale Arbeit läuft weiter; die Synchronisierung wartet | Minderheitspartitionen können ihre Schreibfähigkeit verlieren |
| Ausfallsicherheit | Lokale Datenbanken bleiben nutzbar; Transit und Backups benötigen eigene Absicherung | Replikation und automatisches Failover, solange ein Quorum verfügbar ist |
| Sichtbarkeit | Änderungen werden nach Push und Pull gemeinsam sichtbar | Bestätigte Änderungen sind im Cluster unmittelbar autoritativ |
| Schemaänderungen | Die Anwendung migriert jede lokale Datenbank | Clusterweite SQL-Migrationen |
| Löschungen | Benötigen Tombstones oder eine eigene Policy | Normale transaktionale SQL-Löschungen |
| Infrastruktur | Python, SQLite und ein konfigurierbarer Dateitransport | Mehrere dauerhafte Datenbankserver, TLS, Monitoring und Backups |
| Mindestzahl ständig aktiver Server | Keine; ein Knoten genügt | Für Fehlertoleranz üblicherweise mindestens drei |
| Wichtigster Vorteil | Offline-first-Einfachheit, niedrige Kosten und fachliche Merge-Regeln | Starke Konsistenz, parallele Writer und Hochverfügbarkeit |
| Wichtigste Grenze | Keine globale ACID-Transaktion oder sofortige gemeinsame Wahrheit | Deutlich höherer Betriebs- und Ressourcenaufwand |

### Vorteile, Nachteile und typische Use Cases

| System | Vorteile | Nachteile | Geeignete Use Cases | Ungeeignete Use Cases |
|---|---|---|---|---|
| `sqlite-transit-sync` | Sehr geringer Ressourcenbedarf; offlinefähig; kein zentraler Server; lokale Datenhaltung; transportunabhängig; Merge-Regeln können der Fachdomäne folgen | Änderungen werden verzögert sichtbar; Konflikte, Löschungen, Zeitregeln und Migrationen bleiben Anwendungsverantwortung; keine globalen ACID-Transaktionen und kein Quorum-Failover | Persönliche Wissens- und Taskdatenbanken; lokale KI-Agenten; Laptop-, Workstation- und Serveraustausch; Außen- und Edge-Anwendungen; Desktop-Software mit optionaler Synchronisierung; Forschungsnotizen | Zahlungen, knappe Lagerbestände, Sitzplatzreservierungen, Echtzeit-Zusammenarbeit am selben Datensatz oder viele konkurrierende Writer |
| Distributed SQL | Gemeinsame autoritative Datenbank; starke Konsistenz; globale Transaktionen; koordinierte parallele Schreibzugriffe; automatische Replikation und Failover; horizontale Skalierung | Dauerhafte Server, Netzwerk, Zertifikate, Monitoring und Upgrades erforderlich; Quorum kann bei Partitionen Schreibzugriffe blockieren; höhere Latenz und Kosten | Finanz- und Buchungssysteme; SaaS-Plattformen; E-Commerce-Bestand; globale Benutzerkonten; Multiplayer-Backends; hochverfügbare Unternehmensdienste | Kleine persönliche Werkzeuge, zeitweise getrennte Geräte, Einzelbenutzer-Desktop-Anwendungen oder bereits zuverlässig durch lokale SQLite-Datenbanken abgedeckte Workloads |

### Schnelle Entscheidungshilfe

| Anforderung | Bevorzugter Ansatz |
|---|---|
| Knoten müssen offline weiterarbeiten | `sqlite-transit-sync` |
| Änderungen dürfen erst nach einem Synchronisierungsschritt sichtbar werden | `sqlite-transit-sync` |
| Daten sollen lokal bleiben und Konflikte sind selten | `sqlite-transit-sync` |
| Viele Clients verändern dieselben Datensätze gleichzeitig | Distributed SQL |
| Jeder Commit muss sofort global autoritativ sein | Distributed SQL |
| Globale Transaktionen oder automatisches Cluster-Failover sind Pflicht | Distributed SQL |

Für wenige zeitweise verbundene persönliche oder Edge-Geräte ist
`sqlite-transit-sync` meist die einfachere Lösung. Sobald echte konkurrierende
Writer entstehen, ist häufig eine zentrale PostgreSQL-Instanz der nächste sinnvolle
Schritt. Distributed SQL wird interessant, wenn starke Konsistenz zusätzlich den
Ausfall einzelner Server über mehrere dauerhaft betriebene Knoten überstehen muss.

## Sicherheit und Grenzen

- Eine aktive SQLite-Datenbank niemals aus einem Netzwerk- oder
  Cloud-Synchronisierungsordner öffnen.
- Zustandsdateien bleiben außerhalb des gemeinsamen Transits; gleiche oder
  untergeordnete Pfade werden vor jedem Verzeichnis-/Dateischreibzugriff
  zurückgewiesen.
- Manifeste dürfen nur einen einzelnen relativen Snapshot-Dateinamen nennen;
  Containment- und Link-/Reparse-Prüfungen laufen vor SHA-256, SQLite-Prüfung
  und Merge.
- SHA-256 erkennt Beschädigung, authentifiziert aber keinen feindlichen Transport.
- HMAC ist eine optionale Shared-Key-Identitätsprüfung, kein Secret-Manager,
  Frischeprotokoll oder Ersatz für Public-Key-Signaturen.
- Das standardmäßige LWW setzt vergleichbare Zeitstempel voraus und leitet keine
  Löschungen ab.
- Tombstone-Aufbewahrung, Uhren, Schlüsselablage und Anwendungsmigrationen
  bleiben Integrationsverantwortung.
- Gleiche Zeitstempel konvergieren über einen deterministischen Inhaltsvergleich.
  Dieser technische Fallback ersetzt keine fachlichen Konfliktregeln.
- Tabellen ohne Primärschlüssel oder Zeitstempelspalte werden übersprungen.
- Snapshot-Redaktion löscht gelistete Tabellen und führt anschließend `VACUUM` aus.
  Trotzdem muss jede Tabelle mit Zugangsdaten oder privaten Daten gelistet werden;
  das generische Modul kann fachliche Secrets nicht zuverlässig erkennen.
- Anwendungsmigrationen, Clock Policy, Aufbewahrungsparameter und Konfliktsemantik bleiben
  bei der integrierenden Anwendung. `cleanup` stellt nur den Mechanismus bereit: Jedes Paar
  wird geprüft, der Standard ist ein Dry-Run, die neuesten zehn Snapshots je Knoten bleiben
  erhalten und fremde Knoten werden nur mit ausdrücklichem `--all-nodes` verwaltet.
- Pro Knoten darf ohne zusätzlichen Prozess-Lock der Host-Anwendung nur ein
  Synchronisierungsprozess laufen.

Siehe [ARCHITECTURE.md](ARCHITECTURE.md), [README.md](README.md) und
[SECURITY.md](SECURITY.md).

## Drittanbieter-Lizenzen & Transparenz

`sqlite-transit-sync` steht für 100% lokale Datensouveränität ohne Telemetrie und ohne externe Laufzeitabhängigkeiten.

- **Keine externen Laufzeitabhängigkeiten**: Der Kern-Synchronisationsmotor benötigt **ausschließlich** die Python-Standardbibliothek (`>=3.10`).
- **Optionaler Schaufenster-Layer**: Der verschlüsselte Republica-Schaufenstermodus nutzt optional [`cryptography`](https://github.com/pyca/cryptography) (Apache-2.0 / BSD-3-Clause).
- **Audit & Invarianten**: Formell auditiert am 11.09.2026 mit 100% permissiven Lizenzen (MIT, Apache-2.0, BSD-3-Clause, PSFL). Gesteuert durch **INV-LOCAL-01** (Zero-Egress) und **INV-SLA-10** (RunAsInvoker-Ausführung im Benutzermodus mit 48h Sicherheits-SLA).
- **Vollständiges Inventar**: Vollständige Lizenztexte und Abhängigkeitsdetails sind in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) dokumentiert.

## Marketing & Zielgruppen

`sqlite-transit-sync` wurde für modulare, dezentrale Ökosysteme entwickelt und adressiert 4 Kern-Zielgruppen:

1. **Entwickler autonomer KI-Agenten**: Multi-Agenten-Schwärme auf Laptops, Workstations und Servern benötigen lokale Zustandsspeicherung ohne Dateisperren-Kollisionen. Entkoppelte Transit-Snapshots mit Credential Shielding verhindern Secret-Leaks in gemeinsame Speicher.
2. **Multi-Device- & Cloud-Sync-Entwickler**: Entwickler, die persönliche Notizen- und Aufgaben-Datenbanken über Sync-Ordner synchronisieren (z. B. sync-master, Syncthing, Nextcloud), vermeiden Dateikorruption und `-wal`-Sperren durch atomare Bereitstellung und transaktionalen Zeilen-Merge.
3. **Local-First- & Zero-Egress-Entwickler**: Desktop- und Air-Gapped-Softwarebauer, die Cloud-Lock-in, monatliche Hosting-Kosten und externen Netzwerkverkehr ausschließen.
4. **Enterprise-Sicherheits- & Compliance-Verantwortliche**: Sicherheitsteams profitieren von Regex-Prüfungen auf 13+ Secret-Familien vor der Veröffentlichung, HMAC-Authentizitätsumschlägen und unprivilegierter Ausführung im Benutzermodus.

Ausführliche Zielgruppenanalysen, Suchbegriffe und Wettbewerbsvergleiche sind in [MARKETING-LOG.txt](MARKETING-LOG.txt) dokumentiert.

## Ökosystem & Geschwister-Werkzeuge

`sqlite-transit-sync` ist Teil des lokalen **ellmos-ai**- und **open-bricks**-Software-Ökosystems. Zusammen mit den Schwester-Repositories bildet es einen modularen Baukasten für resiliente, offline-fähige Softwareentwicklung, Dokumentenverwaltung und Agenten-Orchestrierung:

| Repository | Fokus / Domäne | Beschreibung |
|---|---|---|
| [dev-bricks/sync-master](https://github.com/dev-bricks/sync-master) | Datei-Sync-Yard | Robuster Begleiter für lokalen Dateitransport (`sync.files`) und Bereitstellung von Transit-Zonen. |
| [ellmos-ai/policy-registry](https://github.com/ellmos-ai/policy-registry) | Policy Registry | Kryptografische Richtlinienprüfung und berechtigungsbasierte Agenten-Ausführung. |
| [ellmos-ai/system-gap-master](https://github.com/ellmos-ai/system-gap-master) | Systemtopologie | Drift-Inspektion, Sync-Yard-Integritätsaudit und Validierung der Systemtopologie. |
| [ellmos-ai/lock-master](https://github.com/ellmos-ai/lock-master) | Lock-Management | Multi-Agenten-Gleichzeitigkeitskoordination mit kooperativer Sperrung und Deadlock-Erkennung. |
| [ellmos-ai/ticket-master](https://github.com/ellmos-ai/ticket-master) | Aufgabenverwaltung | Lokales Ticket- und Meilenstein-Tracking ohne externe Server-Abhängigkeiten. |
| [ellmos-ai/clutch](https://github.com/ellmos-ai/clutch) | Prozessbrücke | Subprozess-Verwaltung, Stdio-Isolation und Prozessüberwachung für LLM-Tools. |
| [ellmos-ai/memoryhooker](https://github.com/ellmos-ai/memoryhooker) | Langzeitgedächtnis | Persistente Speicher- und Kontexthooks für wiederkehrende LLM-Interaktionen. |
| [ellmos-ai/workflowhooker](https://github.com/ellmos-ai/workflowhooker) | Workflow-Automatisierung | Ereignisgesteuerte Pipeline-Interzeption und automatisierte Lebenszyklus-Hooks. |
| [ellmos-ai/ellmos-controlcenter-mcp](https://github.com/ellmos-ai/ellmos-controlcenter-mcp) | Control Center MCP | Zentrales MCP-Gateway für Werkzeuge, KI-Modelle, Stacks und Subagenten. |
| [ellmos-ai/ellmos-filecommander-mcp](https://github.com/ellmos-ai/ellmos-filecommander-mcp) | File Commander MCP | Gehärtete Dateisystem-Operationen mit Audit-Logs und strenger Pfadgrenzen-Durchsetzung. |
| [ellmos-ai/ellmos-codecommander-mcp](https://github.com/ellmos-ai/ellmos-codecommander-mcp) | Code Commander MCP | MCP-Server für Quellcode-Analyse, AST-Transformationen und Import-Diagnostik. |
| [dev-bricks/automation-master](https://github.com/dev-bricks/automation-master) | Automations-Engine | Lokale, ereignisbasierte Automatisierungs-Pipeline mit projektionsbasierter Ausführung. |
| [dev-bricks/DevCenter](https://github.com/dev-bricks/DevCenter) | Entwickler-Cockpit | Desktop-GUI zur Verwaltung lokaler Projekte, Laufzeitumgebungen und Repositories. |
| [dev-bricks/CodeBox](https://github.com/dev-bricks/CodeBox) | Snippet-Verwaltung | Lokale Code-Bibliothek und AST-basierter Quellcode-Index. |
| [doc-bricks/PDFtoPDFocr](https://github.com/doc-bricks/PDFtoPDFocr) | Dokumenten-OCR | Lokale Konvertierung in durchsuchbare PDFs mit integrierter OCR-Schicht (Zero-Egress). |
| [open-bricks/open-bricks](https://github.com/open-bricks) | Dachorganisation | Dach-Repository und zentrale Dokumentation aller quelloffenen Bricks. |

<!-- BEGIN ELLMOS BUNDLE DISCOVERY DE -->

## Bundles und Partner

Geprüfte Discovery-Projektion für `module:sqlite-transit-sync` aus
`catalog:v4-bundles`
(`546290dafbaafd810df1d59ef5a3d7183738472b48cd5a8a81f1e8f2b64d852e`).
Das Ziel-Repository ist `public`. Die Bundle-Manifeste bleiben die Autorität
für Mitgliedschaften; dieser Abschnitt installiert oder aktiviert keine
Komponenten. Die Freigabe beruht auf einem öffentlichen Modul-Registry-Eintrag
und einer ausdrücklichen Default-deny-Allowlist für Bundles.

### `ellmos-sync-federation-bundle`

- Sichtbarkeit des Bundle-Rezepts: `private`; Rolle: `declared-component`;
  Anforderung: `recommended`.
- Modulpartner: `module:cloud-safe-exporter`, `module:direct-beam`,
  `module:receipt-validator`, `module:sync`, `module:system-explorer-export`,
  `module:system-gap-master`.
- Skill-Partner: `skill:agent-config-sync`, `skill:mcp-config-sync`,
  `skill:system-onboarding`.

Kompositions- und Runtime-Details werden bewusst nicht offengelegt.

<!-- END ELLMOS BUNDLE DISCOVERY DE -->

## Maschinenlesbarer Index

Für KI-Agenten, LLMs und automatisierte Werkzeuge steht unter [llms.txt](llms.txt)
ein strukturierter Verzeichnisbaum mit API-Index bereit.

## Tests

```bash
python -m unittest discover -s tests -v
python -m pytest -q -ra
python -m pytest --collect-only -q
```

Die Suite verwendet ausschließlich synthetische Datenbanken und temporäre
Transit-Verzeichnisse. Hilfe, Retention-Vertrag, Golden-Vergleich sowie der
JSON-Smoke für init/status/push/list/verify/pull gehören zur geprüften Sammlung
der Testsuite; keine echte Datenbank, BACH-Laufzeit oder externer Transport
werden verwendet.

## Herkunft

Das Modul wurde 2026 aus BACH `system/hub/db_sync.py` (ProSync) extrahiert. Die
eigenständige Fassung ersetzt BACH-spezifische Pfade, Handler, Secrets und
Tabellenannahmen durch Konfigurations- und Policy-Schnittstellen. Sie führt den
Merge außerdem je Primärschlüssel aus und ergänzt geprüfte Manifeste.

MIT – siehe [LICENSE](LICENSE) und [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
