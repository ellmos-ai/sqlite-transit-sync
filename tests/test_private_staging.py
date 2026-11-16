"""Observe raw/plaintext artifacts during publication, not just after cleanup."""
from __future__ import annotations

import gzip
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlite_transit_sync import RepublicaTransit, SyncConfig, SyncError, TransitSync, core, generate_key, republica


class PrivateStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.transit = self.root / "transit"
        self.database = self.root / "source.db"
        db = sqlite3.connect(self.database)
        try:
            db.executescript("CREATE TABLE items(id TEXT PRIMARY KEY, value TEXT);"
                             "CREATE TABLE secrets(id TEXT PRIMARY KEY, value TEXT);")
            db.execute("INSERT INTO items VALUES('one', 'ordinary synthetic payload')")
            db.execute("INSERT INTO secrets VALUES('one', 'excluded-synthetic-marker')")
            db.commit()
        finally:
            db.close()
        self.key = self.root / "key"
        self.key.write_bytes(generate_key())

    def sync(self, encrypted=False):
        self.transit = self.root / ("encrypted-transit" if encrypted else "transit")
        config = SyncConfig(self.database, self.transit, self.root / "state.json",
                            node_id="node", namespace="staging", key_file=self.key,
                            republica_root=self.root / "replicas")
        return RepublicaTransit(config) if encrypted else TransitSync(config)

    def files(self):
        return sorted(p for p in self.transit.rglob("*") if p.is_file())

    def assert_private(self, path):
        self.assertNotEqual(self.transit.resolve(), Path(path).resolve())
        self.assertNotIn(self.transit.resolve(), Path(path).resolve().parents)

    def test_raw_backup_and_scan_run_outside_transit(self):
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                sync = self.sync(encrypted)
                original_redact = sync._redact_snapshot
                original_scan = sync._scan_snapshot_for_secrets
                observed = []

                def redact(path):
                    self.assert_private(path)
                    if os.name == "posix":
                        self.assertEqual(0, stat.S_IMODE(Path(path).parent.stat().st_mode) & 0o077)
                    self.assertEqual([], self.files())
                    self.assertIn(b"excluded-synthetic-marker", Path(path).read_bytes())
                    observed.append(Path(path).parent)
                    return original_redact(path)

                def scan(path):
                    self.assert_private(path)
                    self.assertEqual([], self.files())
                    self.assertNotIn(b"excluded-synthetic-marker", Path(path).read_bytes())
                    return original_scan(path)

                with mock.patch.object(sync, "_redact_snapshot", side_effect=redact), \
                     mock.patch.object(sync, "_scan_snapshot_for_secrets", side_effect=scan):
                    result = sync.publish() if encrypted else sync.push()
                self.assertTrue(result.path.is_file())
                self.assertTrue(observed)
                self.assertFalse(observed[0].exists())
                for path in self.files():
                    path.unlink()

    def test_rejected_scan_never_places_raw_database_in_transit(self):
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                sync = self.sync(encrypted)
                sync.config.secret_scan_extra_patterns = ("ordinary synthetic payload",)
                original_scan = sync._scan_snapshot_for_secrets
                observed = []

                def scan(path):
                    observed.append(Path(path).parent)
                    self.assert_private(path)
                    self.assertEqual([], self.files())
                    return original_scan(path)

                with mock.patch.object(sync, "_scan_snapshot_for_secrets", side_effect=scan):
                    with self.assertRaisesRegex(SyncError, "credential-looking"):
                        sync.publish() if encrypted else sync.push()
                self.assertEqual([], self.files())
                self.assertFalse(observed[0].exists())

    def test_republica_sql_and_gzip_stay_private_until_encryption(self):
        sync = self.sync(True)
        original = sync._write_payload
        observed = []

        def write_payload(database, compressed):
            self.assert_private(database)
            self.assert_private(compressed)
            result = original(database, compressed)
            self.assertIn(b"ordinary synthetic payload", gzip.decompress(Path(compressed).read_bytes()))
            self.assertEqual([], self.files())
            observed.append(Path(compressed).parent)
            return result

        with mock.patch.object(sync, "_write_payload", side_effect=write_payload):
            result = sync.publish()
        self.assertFalse(observed[0].exists())
        self.assertNotIn(b"ordinary synthetic payload", result.path.read_bytes())

    def test_config_mutated_to_transit_state_fails_before_backup(self):
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                sync = self.sync(encrypted)
                sync.config.state = self.transit / "state.json"
                with self.assertRaisesRegex((SyncError, ValueError), "state|State"):
                    sync.publish() if encrypted else sync.push()
                self.assertEqual([], self.files())

    def test_config_mutation_during_scan_does_not_publish_to_either_target(self):
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                sync = self.sync(encrypted)
                original = sync._scan_snapshot_for_secrets
                elsewhere = self.root / "other-transit"

                def scan(path):
                    value = original(path)
                    sync.config.transit = elsewhere
                    return value

                with mock.patch.object(sync, "_scan_snapshot_for_secrets", side_effect=scan):
                    with self.assertRaisesRegex(SyncError, "changed"):
                        sync.publish() if encrypted else sync.push()
                self.assertEqual([], self.files())
                self.assertFalse(elsewhere.exists())

    def test_unrelated_predictable_partial_file_is_preserved(self):
        created_at = "20261103T000000000000Z"
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                sync = self.sync(encrypted)
                parent = self.transit / "node" if encrypted else self.transit
                parent.mkdir(parents=True, exist_ok=True)
                suffix = ".republica" if encrypted else ".sqlite-snapshot"
                foreign = parent / f".staging__node__{created_at}{suffix}.partial"
                foreign.write_bytes(b"foreign synthetic sentinel")
                module = republica if encrypted else core
                with mock.patch.object(module, "_utc_token", return_value=created_at):
                    sync.publish() if encrypted else sync.push()
                self.assertEqual(b"foreign synthetic sentinel", foreign.read_bytes())
                for path in self.files():
                    path.unlink()

    def test_rename_sources_remain_in_target_filesystem(self):
        sync = self.sync()
        original = os.replace
        observed = []

        def replace(source, target):
            self.assertEqual(Path(source).parent.resolve(), Path(target).parent.resolve())
            observed.append((source, target))
            return original(source, target)

        with mock.patch.object(core.os, "replace", side_effect=replace):
            sync.push()
        self.assertEqual(2, len(observed))

    def test_transit_temp_environment_does_not_move_plaintext_staging(self):
        sync = self.sync()
        original = sync._redact_snapshot

        def redact(path):
            self.assert_private(path)
            return original(path)

        with mock.patch.dict(os.environ, {key: str(self.transit) for key in ("TEMP", "TMP", "TMPDIR")}), \
             mock.patch.object(sync, "_redact_snapshot", side_effect=redact):
            sync.push()


    def test_foreign_manifest_temp_survives_real_manifest_write_failure(self):
        created_at = "20261103T000000000001Z"
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                sync = self.sync(encrypted)
                parent = self.transit / "node" if encrypted else self.transit
                parent.mkdir(parents=True, exist_ok=True)
                suffix = ".republica" if encrypted else ".sqlite-snapshot"
                name = f"staging__node__{created_at}{suffix}.json"
                foreign = parent / f".{name}.foreign.tmp"
                foreign.write_bytes(b"foreign manifest sentinel")
                module = republica if encrypted else core
                with mock.patch.object(module, "_utc_token", return_value=created_at), \
                     mock.patch.object(core.json, "dump", side_effect=OSError("manifest failure")):
                    with self.assertRaisesRegex(OSError, "manifest failure"):
                        sync.publish() if encrypted else sync.push()
                self.assertEqual([foreign], self.files())
                self.assertEqual(b"foreign manifest sentinel", foreign.read_bytes())

    def test_relative_mutated_transit_cannot_hide_key_in_transport(self):
        sync = self.sync(True)
        key = self.transit / "transport.key"
        key.write_bytes(self.key.read_bytes())
        sync.config.key_file = key
        sync.config.transit = Path(os.path.relpath(self.transit, Path.cwd()))
        with mock.patch.object(sync, "_backup_to", wraps=sync._backup_to) as backup:
            with self.assertRaisesRegex(SyncError, "key must not live inside"):
                sync.publish()
        backup.assert_not_called()
        self.assertEqual([key], self.files())

    def test_target_files_are_never_overwritten_or_removed_on_refusal(self):
        created_at = "20261103T000000000002Z"
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                sync = self.sync(encrypted)
                parent = self.transit / "node" if encrypted else self.transit
                parent.mkdir(parents=True, exist_ok=True)
                suffix = ".republica" if encrypted else ".sqlite-snapshot"
                target = parent / f"staging__node__{created_at}{suffix}"
                manifest = target.with_suffix(target.suffix + ".json")
                target.write_bytes(b"existing snapshot")
                manifest.write_bytes(b"existing manifest")
                module = republica if encrypted else core
                with mock.patch.object(module, "_utc_token", return_value=created_at):
                    with self.assertRaisesRegex(SyncError, "already exists"):
                        sync.publish() if encrypted else sync.push()
                self.assertEqual(b"existing snapshot", target.read_bytes())
                self.assertEqual(b"existing manifest", manifest.read_bytes())

    def test_io_failures_do_not_publish_or_leave_private_workspaces(self):
        for encrypted in (False, True):
            for phase in ("copy", "fsync", "integrity", "rename", "manifest", "cleanup"):
                with self.subTest(encrypted=encrypted, phase=phase):
                    sync = self.sync(encrypted)
                    if phase == "copy":
                        patch = mock.patch.object(core.shutil, "copyfileobj", side_effect=OSError("copy failure"))
                    elif phase == "fsync":
                        patch = mock.patch.object(core.os, "fsync", side_effect=OSError("fsync failure"))
                    elif phase == "integrity":
                        original_hash = core._sha256

                        def corrupt_hash(path):
                            return "0" * 64 if Path(path).suffix == ".partial" else original_hash(path)

                        patch = mock.patch.object(core, "_sha256", side_effect=corrupt_hash)
                    elif phase == "rename":
                        patch = mock.patch.object(core.os, "replace", side_effect=OSError("rename failure"))
                    elif phase == "manifest":
                        patch = mock.patch.object(core.json, "dump", side_effect=OSError("manifest failure"))
                    else:
                        original_cleanup = tempfile.TemporaryDirectory.cleanup

                        def cleanup_then_fail(directory):
                            original_cleanup(directory)
                            raise OSError("cleanup failure")

                        patch = mock.patch.object(tempfile.TemporaryDirectory, "cleanup", cleanup_then_fail)
                    with patch, self.assertRaises((OSError, SyncError)):
                        sync.publish() if encrypted else sync.push()
                    self.assertEqual([], self.files())
                    self.assertEqual([], list(self.root.glob(".sqlite-transit-stage-*")))

    def test_republica_payload_and_encryption_failures_stay_private(self):
        sync = self.sync(True)
        for phase in ("payload", "encrypt"):
            with self.subTest(phase=phase):
                if phase == "payload":
                    patch = mock.patch.object(sync, "_write_payload", side_effect=OSError("payload failure"))
                else:
                    cipher = mock.Mock()
                    cipher.encrypt.side_effect = OSError("encryption failure")
                    patch = mock.patch.object(republica, "_load_fernet", return_value=cipher)
                with patch, self.assertRaises(OSError):
                    sync.publish()
                self.assertEqual([], self.files())
                self.assertEqual([], list(self.root.glob(".sqlite-transit-stage-*")))

    def test_config_change_after_snapshot_rename_removes_only_own_publication(self):
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                sync = self.sync(encrypted)
                original_replace = os.replace

                def replace_then_mutate(source, target):
                    result = original_replace(source, target)
                    if Path(target).suffix in (".sqlite-snapshot", ".republica"):
                        sync.config.namespace = "changed"
                    return result

                with mock.patch.object(core.os, "replace", side_effect=replace_then_mutate):
                    with self.assertRaisesRegex(SyncError, "changed"):
                        sync.publish() if encrypted else sync.push()
                self.assertEqual([], self.files())

    @unittest.skipUnless(os.name == "posix" and Path("/dev/shm").is_dir(), "POSIX shared-memory filesystem")
    def test_actual_different_filesystems_publish_checked_and_encrypted_snapshots(self):
        with tempfile.TemporaryDirectory(prefix="sqlite-staging-test-", dir="/dev/shm") as shared:
            transit = Path(shared)
            if transit.stat().st_dev == self.root.stat().st_dev:
                self.skipTest("No second filesystem available")
            self.transit = transit
            for encrypted in (False, True):
                with self.subTest(encrypted=encrypted):
                    config = SyncConfig(self.database, transit, self.root / "state.json",
                                        node_id="node", namespace="cross-device", key_file=self.key,
                                        republica_root=self.root / "replicas")
                    sync = RepublicaTransit(config) if encrypted else TransitSync(config)
                    original_redact = sync._redact_snapshot
                    observed = []

                    def redact(path):
                        self.assertNotEqual(Path(path).stat().st_dev, transit.stat().st_dev)
                        observed.append(Path(path))
                        return original_redact(path)

                    with mock.patch.object(sync, "_redact_snapshot", side_effect=redact):
                        result = sync.publish() if encrypted else sync.push()
                    self.assertTrue(result.path.is_file())
                    self.assertTrue(observed)
                    self.assertFalse(observed[0].exists())

    @unittest.skipUnless(os.name == "posix", "POSIX symlink creation")
    def test_state_symlink_into_transit_is_rejected_before_backup(self):
        sync = self.sync()
        alias = self.root / "state-alias"
        alias.symlink_to(self.transit, target_is_directory=True)
        sync.config.state = alias / "state.json"
        with mock.patch.object(sync, "_backup_to", wraps=sync._backup_to) as backup:
            with self.assertRaisesRegex(SyncError, "state"):
                sync.push()
        backup.assert_not_called()
        self.assertEqual([], self.files())


if __name__ == "__main__":
    unittest.main()
