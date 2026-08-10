from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlite_transit_sync import (
    HMACKey,
    HMACSnapshotAuthenticator,
    SyncConfig,
    SyncError,
    TransitSync,
)


SCHEMA = """
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def create_db(path: Path, value: str, timestamp: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO items VALUES ('one', ?, ?)", (value, timestamp))
        connection.commit()
    finally:
        connection.close()


class AuthenticatedSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.transit = root / "transit"
        self.a_db = root / "a.db"
        self.b_db = root / "b.db"
        create_db(self.a_db, "A", "2026-01-01T00:00:00Z")
        create_db(self.b_db, "B", "2025-01-01T00:00:00Z")
        self.a_auth = HMACSnapshotAuthenticator(
            keys={
                "node-a-v1": HMACKey("node-a", b"A" * 32),
                "node-a-v2": HMACKey("node-a", b"B" * 32),
            },
            active_key_id="node-a-v2",
            trusted_senders={"node-a"},
        )
        self.b_auth = HMACSnapshotAuthenticator(
            keys={
                "node-a-v1": HMACKey("node-a", b"A" * 32),
                "node-a-v2": HMACKey("node-a", b"B" * 32),
            },
            active_key_id="node-a-v2",
            trusted_senders={"node-a"},
        )
        self.a = TransitSync(
            SyncConfig(self.a_db, self.transit, root / "a-state.json", "node-a", "demo"),
            authenticator=self.a_auth,
        )
        self.b = TransitSync(
            SyncConfig(self.b_db, self.transit, root / "b-state.json", "node-b", "demo"),
            authenticator=self.b_auth,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_signature_covers_manifest_and_snapshot_hash(self) -> None:
        snapshot = self.a.push()
        envelope = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))["auth"]
        self.assertEqual("HMAC-SHA256", envelope["algorithm"])
        self.assertEqual("node-a-v2", envelope["key_id"])
        reports = self.b.pull()
        self.assertEqual(1, reports[0].updated)

    def test_tamper_sender_or_version_fails_before_state_write(self) -> None:
        for field, value in (
            ("sender", "node-z"),
            ("version", 99),
            ("trust_source", "other-key-ring"),
        ):
            snapshot = self.a.push()
            original = snapshot.manifest_path.read_bytes()
            manifest = json.loads(original.decode("utf-8"))
            manifest["auth"][field] = value
            snapshot.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            try:
                with self.assertRaises(SyncError):
                    self.b.pull()
                self.assertFalse((Path(self.temp.name) / "b-state.json").exists())
            finally:
                snapshot.manifest_path.write_bytes(original)
                snapshot.path.unlink(missing_ok=True)
                snapshot.manifest_path.unlink(missing_ok=True)
                (Path(self.temp.name) / "b-state.json").unlink(missing_ok=True)

    def test_tamper_signed_manifest_and_missing_signature_fail_closed(self) -> None:
        snapshot = self.a.push()
        original = snapshot.manifest_path.read_bytes()
        manifest = json.loads(original.decode("utf-8"))
        manifest["sha256"] = "0" * 64
        snapshot.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        try:
            with self.assertRaisesRegex(SyncError, "signature"):
                self.b.pull()
            self.assertFalse((Path(self.temp.name) / "b-state.json").exists())
        finally:
            snapshot.manifest_path.write_bytes(original)
            snapshot.path.unlink(missing_ok=True)
            snapshot.manifest_path.unlink(missing_ok=True)

        unsigned = TransitSync(
            SyncConfig(
                self.a_db,
                self.transit,
                Path(self.temp.name) / "unsigned-state.json",
                "node-a",
                "demo",
            )
        )
        unsigned_snapshot = unsigned.push()
        with self.assertRaisesRegex(SyncError, "authentication is required"):
            self.b.pull()
        self.assertFalse((Path(self.temp.name) / "b-state.json").exists())
        self.assertFalse((Path(self.temp.name) / "unsigned-state.json").exists())
        unsigned_snapshot.path.unlink(missing_ok=True)
        unsigned_snapshot.manifest_path.unlink(missing_ok=True)

    def test_duplicate_signed_snapshot_is_idempotent_and_key_rotation_verifies(self) -> None:
        snapshot = self.a.push()
        self.assertEqual(1, len(self.b.pull()))
        self.assertEqual([], self.b.pull())

        manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
        old = HMACSnapshotAuthenticator(
            keys={"node-a-v1": HMACKey("node-a", b"A" * 32)},
            active_key_id="node-a-v1",
        )
        envelope = old.sign(manifest)
        self.b_auth.verify(manifest, envelope)


if __name__ == "__main__":
    unittest.main()
