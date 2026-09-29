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
| .gitignore | :green_circle: | All minimum release and lock entries present |
| README.md | :green_circle: | Present in English; bilingual README_de.md companion |
| LICENSE | :green_circle: | MIT license verified |
| Database Files | :green_circle: | No .db files tracked |
| Environment Files | :green_circle: | No .env files tracked |
| Secrets | :green_circle: | Tracked-file checks pass; zero secret patterns found |
| Personal Paths | :green_circle: | Zero hardcoded personal paths found |
| Private Data (PII) | :green_circle: | Zero PII patterns found |
| BACH Internals | :green_circle: | Zero BACH-internal documents |
| TODO.md | :green_circle: | Standardized status table, release gates & roadmap codified |
| **Overall** | **CLEAN** | 10/10 Final Gate Check PASS, 150+ tests passed, 100% metadata parity |

**Audit Date:** 2026-09-29
**Gate Check Exit Code:** `0`
