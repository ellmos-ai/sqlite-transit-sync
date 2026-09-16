# TODO

- [x] Optionalen Authentifizierungsadapter für nicht vollständig vertrauenswürdige Transporte als API-Referenz mit HMAC-Key-Rotation ergänzen.
- [x] Referenzadapter für Tombstone-basierte Löschsynchronisation ergänzen.
- [x] Trennung von Node-State und Transitverzeichnis fail-closed erzwingen.
- [x] Synthetischen Golden-Vergleich für BACH-Kompatibilität ergänzen; der
      Bericht bleibt ohne autorisierte Referenz absichtlich blockiert.
- [x] Retention als austauschbare Policy ergänzen, ohne fremde Snapshots
      unkontrolliert zu löschen (`SnapshotRetentionPolicy` und `TransitSync.cleanup`).
- [ ] Retention für Replica-Snapshots: alte `*.republica` je Knoten im Transit aufräumen.
- [ ] Inhaltslose FTS-Indizes (`content=''`) im Replica-Modus: heute nur im Manifest gemeldet.
- [ ] BACH-Kompatibilitätsadapter erst nach autorisiertem goldenem Vergleichstest evaluieren.
- [ ] Konkrete Publisher-Adapter erst in autoritativ registrierten Plan-D-App-Repositories
      implementieren; keine Adapterkopie oder Quellabfrage im neutralen Carrier pflegen.
- [x] Paket- und Release-Gates vor einer öffentlichen Veröffentlichung durchführen.

---

## STATUS

| Category | Status | Notes |
|----------|--------|-------|
| Secrets | :green_circle: | Local tracked-file checks and credential triggers pass |
| Private Data (PII) | :green_circle: | No PII patterns found |
| .gitignore | :green_circle: | Minimum entries present |
| Language (English) | :green_circle: | README.md in English; README_de.md as companion |
| BACH Internals | :green_circle: | No BACH-internal files |
| Database Files | :green_circle: | No .db files tracked |
| README.md | :green_circle: | Present, English |
| LICENSE | :green_circle: | MIT |
| **Overall** | **CLEAN** | 134/134 tests passed, metadata parity 100% synchronized |

**Audit Date:** 2026-09-16
**Gate Check Exit Code:** `0`
