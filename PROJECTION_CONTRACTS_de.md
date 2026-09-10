# Read-only-Projektionsverträge

[English](PROJECTION_CONTRACTS.md) | [Deutsch](PROJECTION_CONTRACTS_de.md)

Anwendungseigene Projektionen erlauben einer kanonischen Anwendung, nur den
kleinen Zustand zu veröffentlichen, den ein Koordinator benötigt. Dadurch wird
`sqlite-transit-sync` weder zu einer zweiten Fachdatenbank noch zu einer
Multi-Writer-Engine.

## Grenze

- Genau ein kanonischer Anwendungsadapter veröffentlicht eine geschlossene
  Projektion.
- Consumer prüfen und öffnen die Projektion read-only. Sie schreiben niemals
  Fachzeilen, Checkpoints oder Tombstones zurück.
- Der Verifier kopiert, veröffentlicht, mergt oder migriert nicht, startet
  keinen Scheduler und schreibt weder Aktivierungs- noch Consumer-Zustand fort.
- Produktionsadapter, Live-Datenbanken, Hostpfade, Zugangsdaten und
  Cutover-Konfiguration sind nicht Bestandteil dieses Repositories.

Die drei mitgelieferten Verträge sind bewusst eng:

| Vertrag | Erlaubte Datentabellen | Ausdrücklich nicht enthalten |
|---|---|---|
| `accounts-balance-projection.v1` | `account_balances` | Quell-IDs, vollständige IBANs, Kontonummern, Bank-/BIC-/Inhaberdaten, Notizen |
| `mediplaner-reminder-projection.v1` | `medication_due`, `inventory_warning` | Namen, Klienten, Diagnosen, Dosierungen, Mengen, Bestandswerte, Notizen |
| `routinika-reminder-projection.v1` | `routine_due` | Titel, Definitionen, Schritte, Notizen, Medienpfade, sachfremde Einstellungen |

Alle drei verlangen zusätzlich genau eine Zeile in `projection_metadata` sowie eine
ausdrückliche Tabelle `projection_tombstones`. Stabile Referenzen sind opake
Hex-Tokens in Kleinschreibung. Wie eine Anwendung sie ableitet, bestimmt der
Vertrag nicht.

## Verifikation

```bash
sqlite-transit-sync verify-projection \
  --contract mediplaner-reminder-projection.v1 \
  --database ./closed-projection.sqlite \
  --consumer-id reminder-consumer \
  --minimum-offline-seconds 2592000 \
  --previous-checkpoint 41
```

Der Befehl gibt JSON aus und öffnet die Datenbank mit SQLite-`mode=ro` sowie
`immutable=1`. Vor dem Öffnen weist er Sidecars zurück, führt
`PRAGMA quick_check` aus und erzwingt anschließend:

1. die exakte Tabellen- und geordnete Spalten-Allowlist einschließlich Typ,
   Nullbarkeit und Primärschlüsselreihenfolge;
2. Vertrags-ID, Version, Publisher-Komponente und -Instanz sowie genau eine
   Metadatenzeile;
3. opake Kennungen, UTC-Zeitstempel, erlaubte Zustände, nicht negative
   Checkpoints und gültige Zeitfenster;
4. übereinstimmende Publisher- und Checkpoint-Provenienz in jeder Datenzeile;
5. einen Loop-Schutz (`consumer_id != publisher_instance`);
6. einen strikt neueren Quell-Checkpoint, wenn `previous_checkpoint` angegeben
   ist;
7. eine Tombstone-Aufbewahrung, die das von der Anwendung angegebene maximale
   Offline-Intervall abdeckt, sowie die Ablehnung gleich alter oder älterer
   aktiver Zeilen.

Das neutrale Modul rät das Offline-Intervall ausdrücklich nicht. Die Anwendung
muss ihren geprüften Wert bei jeder Verifikation angeben. Ein erfolgreicher
Bericht belegt nur diese geschlossene Datei; er ist weder
Absenderauthentifizierung noch eine über den angegebenen Checkpoint hinausgehende
Frischegarantie oder Produktionsaktivierung.

## Synthetische Fixtures

`tests/fixtures/projections/` enthält JSON-Rezepte, keine SQLite-Datenbanken. Die
Tests materialisieren sie ausschließlich in temporären Ordnern. Für jeden
Vertrag gibt es einen Anfangsstand und einen späteren Offline-Resume-Stand mit
übersprungenem Checkpoint und ausdrücklich aufbewahrtem Tombstone. Negativtests
decken Datenschutzerweiterungen, unbekannte Tabellen oder Spalten, ungültige
Kennungen und Zustände, Provenienzabweichungen, Replay, Loops, zu kurze
Tombstone-Aufbewahrung, veraltete aktive Zeilen und nicht geschlossene Sidecars
ab. Es werden keine Live-Anwendungsdaten verwendet.

## Übergabe an Anwendungsadapter

Ein Anwendungsadapter darf nur im kanonischen Quell-Repository der betreffenden
Anwendung implementiert werden. Er muss die Projektion transaktional erstellen,
den Quell-Checkpoint erst nach dem Commit fortschreiben, die Datei schließen und
sie danach einem authentifizierten oder anderweitig freigegebenen Transport
übergeben. Dieses Modul stellt Verifier und Carrier-Mechanik bereit. Es erfindet
weder Quellabfragen, opake ID-Ableitung, Offline-Horizont noch
Aktivierungsrichtlinie der Anwendung.
