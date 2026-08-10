# TODO

- [x] Optionalen Authentifizierungsadapter für nicht vollständig vertrauenswürdige Transporte als API-Referenz mit HMAC-Key-Rotation ergänzen.
- [x] Referenzadapter für Tombstone-basierte Löschsynchronisation ergänzen.
- [x] Trennung von Node-State und Transitverzeichnis fail-closed erzwingen.
- [ ] BACH-Kompatibilitätsadapter erst nach goldenem Vergleichstest evaluieren.
- [ ] Retention als austauschbare Policy ergänzen, ohne fremde Snapshots unkontrolliert zu löschen.
- [x] Paket- und Release-Gates vor einer öffentlichen Veröffentlichung durchführen.

---

## STATUS

| Category | Status | Notes |
|----------|--------|-------|
| Secrets | :yellow_circle: | Local tracked-file checks pass; pinned external helper receipt is pending because its authorized commit is not current |
| Private Data (PII) | :green_circle: | No PII patterns found |
| .gitignore | :green_circle: | Minimum entries present |
| Language (English) | :green_circle: | README.md in English; README_de.md as companion |
| BACH Internals | :green_circle: | No BACH-internal files |
| Database Files | :green_circle: | No .db files tracked |
| README.md | :green_circle: | Present, English |
| LICENSE | :green_circle: | MIT |
| **Overall** | **LOCKED** | Current local gates must be re-read against the final commit; no public release or sign-off is implied. |

**Audit Date:** 2026-08-10
**Gate Check Exit Code:** `PENDING` — authorized helper commit mismatch
(current `89834a01d6d340d74aac96490f92dfd8706b10b9`, required
`d8475c29c4da7a0008853e2755e1b6a012c9b791`).

