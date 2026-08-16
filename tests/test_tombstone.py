from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlite_transit_sync import (
    SyncConfig,
    SyncError,
    TombstoneMergePolicy,
    TransitSync,
    ensure_tombstone_table,
)

SCHEMA = """
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def create_db(path: Path, value: str, timestamp: str, *, with_tombstones: bool = True) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO items VALUES ('one', ?, ?)", (value, timestamp))
        if with_tombstones:
            ensure_tombstone_table(connection)
        else:
            connection.commit()
    finally:
        connection.close()


def item(path: Path, key: str = "one") -> tuple | None:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT * FROM items WHERE id = ?", (key,)).fetchone()
    finally:
        connection.close()


def add_tombstone(path: Path, key: str, deleted_at: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT OR REPLACE INTO __sqlite_transit_tombstones "
            "(table_name, primary_key, deleted_at) VALUES (?, ?, ?)",
            ("items", json.dumps([key], separators=(",", ":")), deleted_at),
        )
        connection.execute("DELETE FROM items WHERE id = ?", (key,))
        connection.commit()
    finally:
        connection.close()


class TombstonePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.transit = root / "transit"
        self.a_db = root / "a.db"
        self.b_db = root / "b.db"
        create_db(self.a_db, "A", "2025-01-01T00:00:00Z")
        create_db(self.b_db, "B", "2025-01-01T00:00:00Z")
        policy_a = TombstoneMergePolicy()
        policy_b = TombstoneMergePolicy()
        self.a = TransitSync(
            SyncConfig(self.a_db, self.transit, root / "a-state.json", "node-a", "demo"),
            policy=policy_a,
        )
        self.b = TransitSync(
            SyncConfig(self.b_db, self.transit, root / "b-state.json", "node-b", "demo"),
            policy=policy_b,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_tombstone_deletes_older_row_and_replay_is_idempotent(self) -> None:
        connection = sqlite3.connect(self.a_db)
        try:
            connection.execute("INSERT INTO items VALUES ('gone', 'old', '2025-01-01T00:00:00Z')")
            connection.commit()
        finally:
            connection.close()
        connection = sqlite3.connect(self.b_db)
        try:
            connection.execute("INSERT INTO items VALUES ('gone', 'old', '2025-01-01T00:00:00Z')")
            connection.commit()
        finally:
            connection.close()

        add_tombstone(self.a_db, "gone", "2026-01-01T00:00:00Z")
        snapshot = self.a.push()
        report = self.b.pull()[0]
        self.assertEqual(1, report.deleted)
        self.assertIsNone(item(self.b_db, "gone"))
        self.assertEqual([], self.b.pull())
        self.assertTrue(snapshot.path.exists())

    def test_later_update_resurrects_after_tombstone_and_older_update_does_not(self) -> None:
        add_tombstone(self.a_db, "one", "2026-01-01T00:00:00Z")
        self.a.push()
        self.b.pull()
        self.assertIsNone(item(self.b_db))

        connection = sqlite3.connect(self.b_db)
        try:
            connection.execute(
                "INSERT INTO items VALUES ('one', 'new', '2027-01-01T00:00:00Z')"
            )
            connection.commit()
        finally:
            connection.close()
        self.b.push()
        self.a.pull()
        self.assertEqual("new", item(self.a_db)[1])

        add_tombstone(self.a_db, "one", "2026-06-01T00:00:00Z")
        self.a.push()
        self.b.pull()
        self.assertEqual("new", item(self.b_db)[1])

    def test_policy_requires_reserved_table_in_local_schema(self) -> None:
        root = Path(self.temp.name)
        missing_db = root / "missing.db"
        create_db(missing_db, "missing", "2025-01-01T00:00:00Z", with_tombstones=False)
        missing = TransitSync(
            SyncConfig(missing_db, self.transit, root / "missing-state.json", "node-c", "demo"),
            policy=TombstoneMergePolicy(),
        )
        self.a.push()
        with self.assertRaisesRegex(SyncError, "requires"):
            missing.pull()
        self.assertFalse((root / "missing-state.json").exists())


if __name__ == "__main__":
    unittest.main()
