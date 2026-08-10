# START.md

1. `CLAUDE.md` lesen.
2. Locks und Arbeitsbaum prüfen.
3. `STATE.md`, `TODO.md` und die letzte Änderung in `CHANGELOG.md` lesen.
4. Tests ausführen: `python -m unittest discover -s tests -v` und
   `python -m pytest -q -ra`.
5. Nach Änderungen dieselben Tests, `compileall`, Ruff und die synthetischen
   JSON-CLI-Smokes wiederholen.

