---
name: Bug Report / Fehlerbericht
about: Report a bug or reproducible integrity/sync issue in sqlite-transit-sync
title: "[Bug]: "
labels: ["bug", "needs-triage"]
assignees: []
---

## Summary / Kurzbeschreibung
A clear and concise description of what went wrong.

## Environment / Umgebung
- **sqlite-transit-sync version:** `0.4.0`
- **Python version:** (e.g. `3.12`)
- **OS:** (e.g. Windows 11, Ubuntu 24.04, macOS)
- **Mode:** (`push`/`pull` core | `republica` | `verify-projection` | `cleanup`)

## Reproduction Steps / Schritte zur Reproduktion
1. Command or Python API snippet used (with synthetic data — **never paste secrets or private DB files**)
2. Expected behavior
3. Actual behavior / JSON output or traceback

## Safety & Local-First Checklist
- [ ] Live SQLite database and state file are outside the transit directory.
- [ ] Issue report contains no credentials, tokens, or personal file paths.
