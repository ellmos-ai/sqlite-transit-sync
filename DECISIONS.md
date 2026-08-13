# Decisions

## ADR-001: Snapshot-Transit statt gemeinsam geöffneter Datenbank

Jeder Knoten besitzt eine lokale SQLite-Datenbank. Nur geschlossene, geprüfte
Snapshots werden transportiert. Das erhält SQLite-Lokalität und vermeidet WAL über
Netzwerk- oder Cloud-Dateisysteme.

## ADR-002: Anwendungsschema muss vor Pull existieren

Das Modul kopiert keinen fremden Snapshot als erste lokale Datenbank. Schema,
Migrationen, lokale Tabellen und Geheimnisse sind fachliche Entscheidungen der
Anwendung und dürfen nicht generisch geraten werden.

## ADR-003: Policy-Schnittstelle statt universeller Konfliktbehauptung

Timestamp-LWW ist nur die sichere Baseline. Löschungen, Tombstones, CRDTs,
Zeitabweichungen und fachliche Validierung gehören in eine anwendungsspezifische
`MergePolicy`.

## ADR-005: Der Credential-Scan bricht ab, statt zu löschen

`snapshot_exclude_tables` setzt voraus, dass man die betroffene Tabelle bereits kennt.
Das deckt den geplanten Fall ab, nicht den häufigeren: ein Zugangsdatum, das jemand in
ein Freitextfeld geschrieben hat — eine Notiz, eine Logzeile, eine Sitzungszusammenfassung.
Deshalb prüft `scan_snapshot_for_secrets` (standardmäßig aktiv) den Snapshot-Inhalt, bevor
er das Transitverzeichnis erreicht.

**Der Fund führt zum Abbruch, nicht zur automatischen Bereinigung.** Das folgt ADR-002:
Welche Daten geheim sind, ist eine fachliche Entscheidung der Anwendung, die dieses Modul
nicht raten darf. Es darf aber die Veröffentlichung verweigern und den Fundort melden —
Anhalten ist die einzige Reaktion, die keine fremde Entscheidung vorwegnimmt. Stilles
Löschen würde zudem verschleiern, dass ein Geheimnis überhaupt in der Quelldatenbank liegt;
das Problem gehört dort behoben, nicht im Snapshot kaschiert.

**Die Muster sind bewusst herstellerpräfixiert** (`sk-`, `ghp_`, `AKIA` und PEM-Key-Header
und weitere). Eine generische Regel wie „langer Hex-String" würde Prüfsummen, UUIDs und
Content-Hashes markieren, die in Datenbanken völlig legitim sind. Ein Scanner mit hoher
Fehlalarmrate wird abgeschaltet — und ein abgeschalteter Scanner schützt nichts.

**Fehlermeldungen nennen nie den gefundenen Wert**, nur `tabelle.spalte`. Andernfalls
wanderte das Geheimnis in Logs, Tracebacks und CI-Ausgaben, also genau dorthin, wovor
die Prüfung schützen soll.

## ADR-004: Integrität ist nicht Authentizität

SHA-256 und Manifest erkennen Übertragungsfehler. Ein feindlicher Transport benötigt
zusätzlich Signaturen oder einen authentifizierten Kanal.

## ADR-006: Optionale kanonische Snapshot-Authentifizierung

Die Baseline bleibt ohne Authenticator kompatibel und behauptet keine
Senderauthentizität. Anwendungen können `HMACSnapshotAuthenticator` in
`TransitSync` injizieren. Er signiert eine kanonische JSON-Nutzlast aus
Protokoll-/Manifestfeldern und einem Header aus Algorithmus, Schlüssel-ID und
Sender sowie Vertrauensquellen-ID. Der SHA-256-Wert ist dadurch Bestandteil der authentifizierten Aussage;
eine manipulierte Nutzlast, ein fremder Sender, eine unbekannte Schlüssel-ID oder
eine andere Authentifizierungs-Version wird vor Hash-/SQLite-Prüfung und Merge
fail-closed abgewiesen.

HMAC ist bewusst als Shared-Key-Referenzadapter benannt und ersetzt keine
Public-Key-Signatur, keinen Secret-Manager und kein Frischeprotokoll. Die
Anwendung verwaltet Schlüsselmaterial und Rotation: alte Schlüssel bleiben
während der Übergangszeit im Verifier-Keyring, nur die aktive ID signiert neue
Manifeste. Ein wiederholtes bereits gepulltes Manifest bleibt über den lokalen
Pull-State idempotent, nicht durch eine behauptete globale Replay-Uhr.

## ADR-007: Explizite Tombstones statt impliziter Löschung

Die Standard-`TimestampMergePolicy` leitet weiterhin niemals aus einer fehlenden
Zeile eine Löschung ab. Die optionale `TombstoneMergePolicy` definiert dafür die
Referenztabelle `__sqlite_transit_tombstones` mit `table_name`, kanonischem JSON-
Array der Primärschlüssel und `deleted_at` als Versionszeitpunkt. Ein Tombstone
gewinnt bei Gleichstand und gegen ältere Zeilen; ein späterer Zeilenzeitpunkt
darf wiederbeleben. Tombstones werden nicht automatisch bereinigt, weil ihre
Aufbewahrung das maximale Offline-Intervall und die fachliche Retention kennen
muss. Fehlende Tabellen oder unbekannte Ziele werden nicht erraten.

## ADR-008: Opt-in-Retention mit explizitem Eigentum

Snapshot-Aufbewahrung ist eine separate, austauschbare Policy und niemals ein
globales Transit-Cleanup. `SnapshotRetentionPolicy` darf nur einen verifizierten
Snapshot im konfigurierten Namespace und im Eigentum des aktuellen Knotens
planen, der nicht mehr pending ist und über einen expliziten
Anwendungs-Callback bestätigt wurde. Alters- und Count-Grenzen werden
deterministisch ausgewertet; der Standard ist Dry-Run.

Fremde, unbekannte, unvollständige, ungeprüfte, ausstehende oder nicht
bestätigte Artefakte bleiben mit einem Grund erhalten. Sidecars und sonstige
Artefakte gehören nicht zum Löschvertrag. Eine Mutation liest jedes Paar vor
dem Löschen erneut und prüft Manifest, Hash, Größe, Namespace, Knoten und
Zeitstempel; Fehler werden im Audit-Bericht sichtbar und führen nicht zu
breiter Bereinigung. BACH-spezifische Retention und Autorität bleiben außerhalb
des neutralen Moduls.

