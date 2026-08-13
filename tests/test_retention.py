from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sqlite_transit_sync import (
    RetentionEntry,
    SnapshotRetentionPolicy,
    SyncConfig,
    TransitSync,
)


def make_db(path: Path, value: str = "value") -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE items (id TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        connection.execute("INSERT INTO items VALUES ('one', ?, '2026-01-01T00:00:00Z')", (value,))
        connection.commit()
    finally:
        connection.close()


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transit = self.root / "transit"
        self.db = self.root / "owner.db"
        make_db(self.db)
        self.sync = TransitSync(
            SyncConfig(self.db, self.transit, self.root / "owner-state.json", "owner", "demo")
        )
        self.now = datetime(2026, 1, 10, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def set_created(manifest: Path, created_at: str) -> None:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        raw["created_at"] = created_at
        manifest.write_text(json.dumps(raw), encoding="utf-8")

    def test_policy_requires_criterion_and_nonnegative_values(self) -> None:
        with self.assertRaises(ValueError):
            SnapshotRetentionPolicy()
        with self.assertRaises(ValueError):
            SnapshotRetentionPolicy(max_age=timedelta(seconds=-1))
        with self.assertRaises(ValueError):
            SnapshotRetentionPolicy(keep_latest=-1)
        with self.assertRaises(ValueError):
            SnapshotRetentionPolicy(keep_latest=True)

    def test_age_boundary_is_strict_and_keep_latest_is_deterministic(self) -> None:
        entries = [
            RetentionEntry(
                self.root / f"m{index}.json",
                self.root / f"s{index}",
                "demo",
                "owner",
                created,
                True,
                snapshot=object(),
            )
            for index, created in enumerate(
                ("20260108T000000000000Z", "20260109T000000000000Z", "20260110T000000000000Z")
            )
        ]
        policy = SnapshotRetentionPolicy(
            max_age=timedelta(days=2), keep_latest=1, acknowledge=lambda _: True
        )
        decisions = policy.plan(entries, owner_node_id="owner", namespace="demo", now=self.now)
        self.assertEqual(["delete", "delete", "retain"], [item.action for item in decisions])
        self.assertIn("outside-keep-latest", decisions[0].reason)
        # Exactly two days old is retained when it is the newest kept item.
        boundary = SnapshotRetentionPolicy(max_age=timedelta(days=2), acknowledge=lambda _: True)
        boundary_decision = boundary.plan(
            [entries[0]], owner_node_id="owner", namespace="demo", now=datetime(2026, 1, 10, tzinfo=timezone.utc)
        )[0]
        self.assertEqual("retain", boundary_decision.action)

    def test_acknowledgement_is_explicit_and_foreign_pending_is_retained(self) -> None:
        self.sync.push()
        entry = next(item for item in self.sync.retention_inventory() if item.verified)
        self.assertTrue(entry.verified)
        no_ack = SnapshotRetentionPolicy(keep_latest=0)
        self.assertEqual("not-acknowledged", no_ack.plan(
            [entry], owner_node_id="owner", namespace="demo", now=self.now
        )[0].reason)

        foreign_db = self.root / "foreign.db"
        make_db(foreign_db, "foreign")
        foreign = TransitSync(
            SyncConfig(foreign_db, self.transit, self.root / "foreign-state.json", "foreign", "demo")
        )
        foreign_snapshot = foreign.push()
        foreign_entry = next(
            item for item in self.sync.retention_inventory()
            if item.manifest_path == foreign_snapshot.manifest_path
        )
        decision = SnapshotRetentionPolicy(keep_latest=0, acknowledge=lambda _: True).plan(
            [foreign_entry], owner_node_id="owner", namespace="demo", now=self.now
        )[0]
        self.assertEqual("retain", decision.action)
        self.assertEqual("pending-foreign", decision.reason)
        # Acknowledging the pull changes only pending status; foreign ownership
        # remains non-deletable.
        self.sync._save_state({"last_pulled": {"foreign": foreign_snapshot.created_at}})
        foreign_entry = next(
            item for item in self.sync.retention_inventory()
            if item.manifest_path == foreign_snapshot.manifest_path
        )
        self.assertFalse(foreign_entry.pending)
        decision = SnapshotRetentionPolicy(keep_latest=0, acknowledge=lambda _: True).plan(
            [foreign_entry], owner_node_id="owner", namespace="demo", now=self.now
        )[0]
        self.assertEqual("foreign-node", decision.reason)

    def test_dry_run_apply_restart_and_audit_are_idempotent(self) -> None:
        snapshot = self.sync.push()
        self.set_created(snapshot.manifest_path, "20260101T000000000000Z")
        policy = SnapshotRetentionPolicy(
            max_age=timedelta(days=1), acknowledge=lambda _: True
        )
        audit = self.root / "audit" / "retention.json"
        dry = self.sync.apply_retention(policy, now=self.now, dry_run=True, audit_path=audit)
        self.assertTrue(dry.dry_run)
        self.assertEqual(1, len(dry.planned))
        self.assertTrue(snapshot.path.exists())
        self.assertEqual("sqlite-transit-sync.retention-report.v1", json.loads(audit.read_text())["schema"])

        applied = self.sync.apply_retention(policy, now=self.now, dry_run=False, audit_path=audit)
        self.assertEqual([snapshot.path, snapshot.manifest_path], applied.deleted)
        self.assertFalse(snapshot.path.exists())
        self.assertFalse(snapshot.manifest_path.exists())
        restarted = TransitSync(
            SyncConfig(self.db, self.transit, self.root / "owner-state.json", "owner", "demo")
        )
        second = restarted.apply_retention(policy, now=self.now, dry_run=False)
        self.assertEqual([], second.deleted)
        self.assertEqual([], second.errors)

    def test_unknown_unverified_and_foreign_namespace_artifacts_are_retained(self) -> None:
        snapshot = self.sync.push()
        snapshot.path.write_bytes(snapshot.path.read_bytes() + b"tamper")
        (self.transit / "notes.sidecar").write_text("keep", encoding="utf-8")
        foreign_manifest = self.transit / "foreign.sqlite-snapshot.json"
        foreign_manifest.write_text(
            json.dumps(
                {
                    "protocol": 1,
                    "namespace": "other",
                    "node_id": "outside",
                    "created_at": "20250101T000000000000Z",
                    "snapshot": "foreign.sqlite-snapshot",
                    "sha256": "0" * 64,
                    "size": 1,
                }
            ),
            encoding="utf-8",
        )
        decisions = SnapshotRetentionPolicy(keep_latest=0, acknowledge=lambda _: True).plan(
            self.sync.retention_inventory(), owner_node_id="owner", namespace="demo", now=self.now
        )
        reasons = {decision.reason for decision in decisions if decision.action == "retain"}
        self.assertIn("unverified", reasons)
        self.assertIn("unrecognized-artifact", reasons)
        self.assertIn("foreign-namespace", reasons)
        self.assertFalse(any(decision.action == "delete" for decision in decisions))

    def test_delete_error_is_reported_without_broad_cleanup(self) -> None:
        snapshot = self.sync.push()
        self.set_created(snapshot.manifest_path, "20260101T000000000000Z")
        policy = SnapshotRetentionPolicy(max_age=timedelta(days=1), acknowledge=lambda _: True)
        original_unlink = Path.unlink

        def fail_target(path: Path, *args, **kwargs):
            if Path(path) == snapshot.path:
                raise OSError("synthetic delete failure")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", new=fail_target):
            report = self.sync.apply_retention(policy, now=self.now, dry_run=False)
        self.assertEqual([], report.deleted)
        self.assertEqual(1, len(report.errors))
        self.assertTrue(snapshot.path.exists())
        self.assertTrue(snapshot.manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
