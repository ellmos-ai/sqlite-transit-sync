# Security

## Supported use

Use the module only with local live databases and a transport whose participants are
trusted. Keep node state outside the shared transport. Restrict filesystem access to
database, state and transit paths.

`SyncConfig` rejects a state path equal to or below the canonical transit directory
before `TransitSync` creates either directory. The same rule applies to absolute and
config-file-relative paths and to CLI `init`; there is no silent migration of an
existing state file.

### Private preparation before publication

Publication prepares raw SQLite, redaction/scan and Republica plaintext SQL/gzip in
a per-call temporary directory under the configured state parent, outside the
canonical transit. That parent must be trusted, local and private. Only checked
snapshot bytes or already encrypted Republica bytes are copied to an exclusively
created transit temporary file, size/hash verified and renamed in that filesystem.
The manifest is written last; this is not an atomic transaction across both files.

Paths and node identity are captured for the call; changed configurations or
redirected publication directories fail closed. Cleanup failures propagate.
POSIX temporary directories restrict group/other access; no new Windows ACL
guarantee or isolation from the same OS account, other configured sync roots,
crashes, or physical media recovery is claimed. Inspect crash leftovers locally;
do not delete historical or foreign artifacts automatically.

### Transit path and manifest boundary

Readers accept only a direct regular manifest in the canonical transit
directory. The manifest may name exactly one relative snapshot filename;
absolute paths, traversal components, nested paths, symlinks and Windows
reparse points fail closed before hashing, SQLite `quick_check` or merge. A
successful SHA-256 check therefore means that the bytes match the manifest,
not that the sender or transport is authenticated. Add signatures or an
authenticated transport when the transit is not fully trusted.

### Optional authentication adapter

`TransitSync(..., authenticator=...)` is an opt-in API boundary. The bundled
`HMACSnapshotAuthenticator` signs a canonical JSON payload containing protocol,
namespace, sender/node, snapshot filename, SHA-256, size, redaction list and
the algorithm/key/sender/trust-source header. It uses an application-owned in-memory key
ring; no secret is written to a manifest, transit file, log or JSON config.
`HMACKeyReference` stores only service/account/sender locators. Secret bytes are
resolved exclusively through an injected `SecretResolver` or the lazy optional
`OSKeyringSecretResolver`; a missing resolver result or keyring dependency fails
closed without exposing key material.
Keep old key IDs available to verifiers during rotation and change only the
active signing key. A configured verifier rejects missing, malformed, unknown,
foreign or mismatched envelopes before checksum/SQLite verification or merge.
`verify_authenticated_snapshot()` is the narrower read-only boundary for an
explicit manifest/snapshot pair: it checks identity, HMAC, sidecars, size and
SHA-256 without opening SQLite and without reading or advancing sync state.
Without an adapter, the module remains compatible but makes no authenticity
claim. Duplicate delivery after `last_pulled` is an idempotent state behavior,
not a freshness or anti-replay service.

### Tombstone reference policy

`TombstoneMergePolicy` is deliberately opt-in and requires the integrating
application to create `__sqlite_transit_tombstones` with
`ensure_tombstone_table()`. Each row identifies a target table, a canonical JSON
array of primary-key values and a `deleted_at` version. Tombstones win ties and
older rows; a later row version may resurrect a key. Missing rows never imply a
delete, unknown target tables are not guessed, and tombstones are never pruned
automatically. Retention, clocks and schema migration remain application duties.

### Cleanup and retention safety

`cleanup` verifies each managed snapshot and manifest before selecting it. It is a dry-run
and local-node-only operation by default. Treat `--apply --all-nodes` as administrative
authority over other publishers' artifacts, and review the JSON plan before granting it.

## Required application review

Before deployment, define:

1. every table that must be excluded from merge;
2. every table whose rows must be removed from published snapshots;
3. timestamp and clock policy;
4. deletion/tombstone behavior;
5. transport authentication and retention;
6. database migrations and rollback.

Since 0.2.0 a second, independent guard runs before publication:
`scan_snapshot_for_secrets` (default **on**) inspects snapshot *content* and aborts the push
when a credential-shaped value is found, naming `table.column` but never the value. It exists
because the table rule below can only drop tables you already anticipated, while credentials
in practice end up pasted into free-text columns. It is a safety net, not a guarantee:
patterns are vendor-prefixed, so a bespoke or unprefixed secret still passes. Treat a clean
scan as "no known pattern matched", never as "this snapshot is free of secrets". Disable it
only with `scan_snapshot_for_secrets = false`, and prefer `secret_scan_skip_tables` when a
single table produces false positives.

The default `snapshot_exclude_tables = ["secrets"]` is only a safety baseline. It
cannot identify application-specific private or regulated data.

When a listed table exists, sqlite-transit-sync deletes its rows from the
snapshot and runs `VACUUM` before publishing. This reduces residual bytes in the
snapshot file, but it is not a substitute for a complete application-specific
redaction list.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| < 0.4.0 | :x:                |

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly:
- **Email (Direct Security Contact)**: [security@ellmos.ai](mailto:security@ellmos.ai)
- **Secondary Contact**: [support@lukasgeiger.com](mailto:support@lukasgeiger.com)
- **Umbrella Security**: [security@open-bricks.org](mailto:security@open-bricks.org)
- **Maintainer**: [lukas@open-bricks.org](mailto:lukas@open-bricks.org)
- **GitHub Advisory**: Use the [Private Vulnerability Reporting](https://github.com/ellmos-ai/sqlite-transit-sync/security/advisories/new) tab on GitHub.

We acknowledge receipt of valid reports within **48 hours** and provide triage assessments within **5 business days**, with regular progress updates until a patch is released.
Do not include live databases, actual credentials, or personal records in a report. Provide a minimal synthetic database and redacted manifest instead.

---

# Sicherheitsrichtlinie (Deutsch)

## Unterstützte Versionen

| Version | Unterstützt        |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| < 0.4.0 | :x:                |

## Unterstützte Nutzung & Local-First Invarianten

Verwenden Sie das Modul ausschließlich mit lokalen Live-Datenbanken und einem vertrauenswürdigen Transportweg. Der Knotenzustand (`state`) muss strikt außerhalb des geteilten Transitverzeichnisses liegen. Dateisystem-Zugriffsrechte sollten auf Datenbank-, Zustands- und Transitpfade beschränkt sein.

`SyncConfig` weist Zustandspfade, die gleich oder unterhalb des kanonischen Transitverzeichnisses liegen, vor der Verzeichniserstellung fail-closed ab. Dies gilt für absolute wie relative Pfade sowie CLI-`init`.

### Private Vorbereitung vor der Veröffentlichung

Rohbackups, Redaktion/Scan und Republica-Klartext-SQL/gzip entstehen pro Aufruf in
einem temporären Verzeichnis beim lokalen Zustandsordner, außerhalb des kanonischen
Transitordners. Dieser Elternordner muss vertrauenswürdig, lokal und privat sein.
Erst geprüfte Snapshotbytes oder bereits verschlüsselte Republica-Daten werden in
eine exklusiv erzeugte Transitdatei kopiert, nach Größe/Hash geprüft und innerhalb
des Zieldateisystems umbenannt. Das Manifest folgt; das Paar ist nicht gemeinsam atomar.

Geänderte Pfade/Knotenidentitäten und umgeleitete Veröffentlichungsordner schlagen
fail-closed fehl. Private Aufräumfehler propagieren. POSIX-Arbeitsordner schließen
Gruppen-/Fremdzugriff aus; keine zusätzliche Windows-ACL-Garantie, Isolation vom
selben OS-Konto, anderen Syncwurzeln, Abstürzen oder physischer Datenwiederherstellung.
Absturzreste lokal prüfen; historische oder fremde Artefakte nicht automatisch löschen.

### Transitpfad- und Manifest-Isolationsgrenzen

Empfänger akzeptieren ausschließlich direkte, reguläre Manifestdateien im kanonischen Transitordner. Das Manifest darf exakt einen relativen Snapshot-Dateinamen angeben. Absolute Pfade, Directory-Traversal (`../`), geschachtelte Pfade, Symlinks und Windows-Reparse-Points werden vor dem Hashen, SQLite-`quick_check` oder Merge fail-closed blockiert. Eine erfolgreiche SHA-256-Prüfung garantiert die Datenintegrität des Manifests, stellt jedoch ohne kryptografischen Adapter keine Absenderauthentifizierung dar.

### Optionaler HMAC-Authentifizierungs-Adapter

`TransitSync(..., authenticator=...)` stellt eine optionale Sicherheitsgrenze dar. Der integrierte `HMACSnapshotAuthenticator` signiert ein kanonisches JSON-Payload (Protokoll, Namespace, Sender/Knoten, Snapshot-Dateiname, SHA-256-Hash, Dateigröße, Redaktionsliste und Schlüssel-Header). Verwendet wird ein anwendungseigener In-Memory-Schlüsselbund; keine Geheimnisse werden in Manifeste, Transit-Dateien, Logs oder JSON-Konfigurationen geschrieben. `HMACKeyReference` speichert nur Service-/Account-/Sender-Referenzen. Schlüsselbytes kommen ausschließlich aus einem injizierten `SecretResolver` oder dem optionalen, lazy geladenen `OSKeyringSecretResolver`; fehlende Resolver-Ergebnisse oder die fehlende Keyring-Abhängigkeit schlagen fail-closed fehl. `verify_authenticated_snapshot()` prüft ein explizites Manifest-/Snapshot-Paar auf Identität, HMAC, Sidecars, Größe und SHA-256, ohne SQLite zu öffnen oder Sync-State zu lesen beziehungsweise fortzuschreiben.

### Inhaltsbezogener Zugangsdaten-Schutzscan (Credential Shield)

Standardmäßig prüft `scan_snapshot_for_secrets = true` den *Inhalt* jedes Snapshots vor dem Schreiben in das Transitverzeichnis auf zugangsdatenähnliche Muster (OpenAI, Anthropic, Google, GitHub, GitLab, AWS, Slack, PEM-Schlüssel). Bei einem Fund wird die Veröffentlichung mit einem Fehler abgebrochen, der lediglich `table.column` benennt, jedoch niemals das Geheimnis selbst preisgibt.

### Bereinigungs- und Aufbewahrungssicherheit

Die `cleanup`-Routine verifiziert jedes geplante Snapshot- und Manifestpaar einzeln vor einer Löschung. Standardmäßig läuft sie als Dry-Run und ist strikt auf den lokalen Knoten beschränkt. Das Flag `--apply --all-nodes` erfordert explizite administrative Autorisierung über Artefakte fremder Knoten.

## Sicherheitskontakt & Schwachstellenmeldung

Sicherheitsrelevante Schwachstellen bitte vertraulich melden:
- **E-Mail (Sicherheitskontakt)**: [security@ellmos.ai](mailto:security@ellmos.ai)
- **Sekundärkontakt**: [support@lukasgeiger.com](mailto:support@lukasgeiger.com)
- **Dachorganisation Security**: [security@open-bricks.org](mailto:security@open-bricks.org)
- **Maintainer**: [lukas@open-bricks.org](mailto:lukas@open-bricks.org)
- **GitHub Advisory**: Über [Private Vulnerability Reporting](https://github.com/ellmos-ai/sqlite-transit-sync/security/advisories/new).

Wir bestätigen den Eingang valider Sicherheitsberichte innerhalb von **48 Stunden** und stellen eine verbindliche Triage-Einschätzung innerhalb von **5 Werktagen** bereit, begleitet von regelmäßigen Fortschrittsberichten bis zur Veröffentlichung eines Patches.
Fügen Sie Meldungen niemals Live-Datenbanken, echte Zugangsdaten oder persönliche Daten bei. Nutzen Sie stattdessen eine minimale synthetische Testdatenbank und ein anonymisiertes Manifest.

