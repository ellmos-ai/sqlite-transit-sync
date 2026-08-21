# Version, Status und Verifikation

Dieses Dokument trennt die drei Metadatenachsen des Moduls. Eine sichtbare
Versionszahl ist kein Beleg für eine Veröffentlichung.

## Autoritative Release-Version

Die einzige Release-Quelle ist `pyproject.toml`, Feld
`[project].version`. Beim aktuellen Readback ist sie `0.4.0`. Diese Zahl wird
byte-/wertgleich gespiegelt in:

- `sqlite_transit_sync.__version__`
- `ellmos-module.json.version`
- `ellmos-module.v2.json.version`
- `llms.txt` und den Test-Badges in `README.md` und `README_de.md`
- dem `version`-Feld im Frontmatter von `CLAUDE.md`

`schema_version` in `ellmos-module.json` und `schema` in
`ellmos-module.v2.json` sind Formatversionen. Sie sind keine alternativen
Paket- oder Release-Versionen.

## Status und Sichtbarkeit

`status: development` beschreibt den Entwicklungsstand der Modulquelle.
`visibility: public-candidate` in der v2-Projektion beschreibt eine mögliche
öffentliche Katalogsicht; es veröffentlicht oder aktiviert nichts. Die
Freigabeachse ist unabhängig: `RELEASE_GATE.md` bleibt `LOCKED`, solange kein
aktueller Gate-Nachweis und kein ausdrücklicher Sign-off vorliegen.

## Verifikationsdatum

`2026-08-21` ist der gemeinsame Stand des aktuellen lokalen Readbacks. Er wird
in `llms.txt`, beiden Modulmanifesten und dem Frontmatter von `CLAUDE.md`
geführt. `STATE.md` und `CHANGELOG.md` beschreiben die ausgeführten Befehle,
Testanzahl und Grenzen. `tests/test_metadata.py` liest diese Artefakte und
blockiert künftig Versions-, Status- oder Datumsdrift.

## Reproduzierbarer Nachweis

Die autoritative Testzählung ist die Zahl der von
`python -m pytest --collect-only -q` gesammelten Tests (ohne unittest-
Subtests). Der Release-Gate-Bericht führt zusätzlich denselben Lauf mit
`python -m unittest discover -s tests -v`, `compileall`, Ruff und den JSON-
CLI-Smokes auf. Ein grüner Testlauf ist weder ein Public-Upload noch ein
Release-Tag; der aktuelle Gate-Status bleibt bis zum Sign-off gesperrt.
