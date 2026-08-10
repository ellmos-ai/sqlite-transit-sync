from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent


class CliSmokeTests(unittest.TestCase):
    def run_cli(self, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, "-m", "sqlite_transit_sync", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return json.loads(completed.stdout)

    def test_help_smokes_are_available(self) -> None:
        for args in (("--help",), ("init", "--help")):
            completed = subprocess.run(
                [sys.executable, "-m", "sqlite_transit_sync", *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("usage:", completed.stdout.lower())

    def test_json_cli_roundtrip_smoke_uses_only_synthetic_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "node.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "CREATE TABLE items (id TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO items VALUES ('one', 'fixture', '2026-01-01T00:00:00Z')"
                )
                connection.commit()
            finally:
                connection.close()

            config = root / "node.json"
            transit = root / "transit"
            state = root / "state.json"
            initialized = self.run_cli(
                "init",
                "--config",
                str(config),
                "--database",
                str(database),
                "--transit",
                str(transit),
                "--state",
                str(state),
                "--node-id",
                "fixture-node",
                "--namespace",
                "fixture",
            )
            self.assertTrue(initialized["ok"])

            status = self.run_cli("status", "--config", str(config))
            self.assertTrue(status["result"]["database_exists"])
            pushed = self.run_cli("push", "--config", str(config))
            self.assertTrue(pushed["result"]["path"].endswith(".sqlite-snapshot"))
            listed = self.run_cli("list", "--config", str(config))
            self.assertEqual(1, len(listed["result"]))
            verified = self.run_cli("verify", "--config", str(config))
            self.assertEqual(1, verified["result"]["verified_snapshots"])
            dry_run = self.run_cli("pull", "--config", str(config), "--dry-run")
            self.assertEqual([], dry_run["result"])


if __name__ == "__main__":
    unittest.main()
