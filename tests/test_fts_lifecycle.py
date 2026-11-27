"""Synthetic FTS destination lifecycle and security regression checks."""

import hashlib
import inspect
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlite_transit_sync.core as c


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root):
    root = Path(root).resolve()
    for name in ("transit", "source-private", "target-private", "source-state", "target-state", "replicas"):
        directory = root / name
        directory.mkdir(mode=0o700)
        if os.name != "nt":
            directory.chmod(0o700)
    schema = (
        "CREATE TABLE entries(id INTEGER PRIMARY KEY,body TEXT NOT NULL,updated_at TEXT NOT NULL);"
        'CREATE TABLE "fts:ordinary"(id INTEGER PRIMARY KEY,body TEXT NOT NULL,updated_at TEXT NOT NULL);'
        f'CREATE TABLE "{c.TOMBSTONE_TABLE}"(table_name TEXT NOT NULL,primary_key TEXT NOT NULL,deleted_at TEXT NOT NULL,PRIMARY KEY(table_name,primary_key));'
        "CREATE VIRTUAL TABLE search USING fts5(body,content='entries',content_rowid='id');"
    )
    for side in ("source", "target"):
        db = sqlite3.connect(root / (side + ".sqlite"))
        try:
            db.executescript(schema)
            rows = (
                [(1, "autumn apple", "2026-01-02"), (2, "beacon birch", "2026-01-02")]
                if side == "source"
                else [(1, "old apple", "2025-01-01"), (3, "old cedar", "2025-01-01")]
            )
            db.executemany("INSERT INTO entries VALUES(?,?,?)", rows)
            db.execute('INSERT INTO "fts:ordinary" VALUES(1,?,?)', ("ordinary relation", "2026-01-02"))
            db.execute(
                f'INSERT INTO "{c.TOMBSTONE_TABLE}" VALUES(?,?,?)',
                ("entries", "[3]", "2026-01-03" if side == "source" else "2024-01-01"),
            )
            db.execute("INSERT INTO search(rowid,body) SELECT id,body FROM entries")
            db.commit()
            objects = c._fts_schema(db)
            profile = c.FtsSQLiteProfile(
                sqlite3.sqlite_version,
                db.execute("SELECT sqlite_source_id()").fetchone()[0],
                tuple(sorted(r[0] for r in db.execute("PRAGMA compile_options"))),
            )
        finally:
            db.close()
    descriptor = c.Fts5Descriptor("search", (c.Fts5Column("body"),), content_table="entries", content_rowid="id")
    auth = c.HMACSnapshotAuthenticator(
        keys={"unit": c.HMACKey("source", bytes(range(32)))}, active_key_id="unit", trusted_senders=("source",)
    )
    policy = c.TombstoneMergePolicy(timestamp_columns=("updated_at",), exclude_tables=())
    syncs = []
    for side in ("source", "target"):
        config = c.SyncConfig(
            database=root / (side + ".sqlite"),
            transit=root / "transit",
            state=root / (side + "-state") / "state.json",
            node_id=side,
            namespace="unit-lifecycle",
            timestamp_columns=("updated_at",),
            exclude_tables=(),
            snapshot_exclude_tables=(),
            key_file=root / "synthetic-key",
            republica_root=root / "replicas",
        )
        contract = c.FtsSnapshotContract(
            "unit-fts-schema", root / (side + "-private"), profile, objects, (descriptor,), 0, ()
        )
        merge = c.FtsMergeContract("unit-fts-schema", tuple(sorted(("entries", "fts:ordinary", c.TOMBSTONE_TABLE))))
        syncs.append(
            c.TransitSync(
                config,
                policy,
                auth,
                fts_contract=contract,
                **({"fts_merge_contract": merge} if side == "target" else {}),
            )
        )
    return *syncs, auth


class FtsLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_retained_binary_input_preserves_crlf_and_control_z(self):
        path = self.root / "binary-input.bin"
        payload = b"alpha\r\nbeta\x1agamma\n\r\n"
        path.write_bytes(payload)
        reader = c._FtsBoundInput(path, len(payload))
        try:
            self.assertEqual(reader.read(c._FtsBudget(c.FtsReceiveLimits())), payload)
            self.assertEqual(reader.read(c._FtsBudget(c.FtsReceiveLimits())), payload)
        finally:
            reader.close()

    def test_positive_transit_commits_and_acknowledges_after_journal_retirement(self):
        source, target, _ = fixture(self.root)
        before = digest(source.config.database)
        published = source.push()
        self.assertEqual(digest(source.config.database), before)
        self.assertEqual(len(target.snapshots(verify=True)), 1)
        self.assertTrue(target.verify()["payload_checked"])
        reports = target.pull()
        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].committed)
        db = sqlite3.connect(target.config.database)
        try:
            self.assertEqual(
                db.execute("SELECT id,body FROM entries ORDER BY id").fetchall(),
                [(1, "autumn apple"), (2, "beacon birch")],
            )
            self.assertEqual(db.execute("SELECT rowid FROM search WHERE search MATCH 'beacon'").fetchall(), [(2,)])
            self.assertEqual(
                db.execute(f'SELECT deleted_at FROM "{c.TOMBSTONE_TABLE}" WHERE table_name=?', ("entries",)).fetchone(),
                ("2026-01-03",),
            )
        finally:
            db.close()
        state = json.loads(target.config.state.read_text())
        self.assertEqual(state["last_pulled"]["source"], published.created_at)
        self.assertEqual(target.pending(), [])
        self.assertEqual(list((self.root / "source-private").iterdir()), [])
        self.assertEqual(list((self.root / "target-private").iterdir()), [])

    def test_F1_ordinary_fts_prefix_does_not_bypass_plaintext_scan(self):
        source, _, _ = fixture(self.root)
        db = sqlite3.connect(source.config.database)
        db.execute('UPDATE "fts:ordinary" SET body=?', ("FORBIDDEN_FIXTURE_VALUE",))
        db.commit()
        db.close()
        patterns = (*c.load_secret_patterns(), c.SecretPattern("unit-marker", re.compile("FORBIDDEN_FIXTURE_VALUE")))
        with patch.object(c, "load_secret_patterns", return_value=patterns), self.assertRaises(c.SyncError):
            source.push()
        self.assertEqual(list((self.root / "source-private").iterdir()), [])
        self.assertEqual(list((self.root / "transit").iterdir()), [])

    def test_F2_strict_json_and_exact_types_remain_fail_closed(self):
        for payload in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.subTest(payload=payload), self.assertRaises(c.SyncError):
                c._fts_json(payload)
        self.assertFalse(c._fts_json_exact_equal({"x": True}, {"x": 1}))
        self.assertFalse(c._fts_json_exact_equal({"x": 1.0}, {"x": 1}))
        source, target, auth = fixture(self.root)
        snap = source.push()
        metadata = json.loads(snap.manifest_path.read_bytes())
        metadata["additional"] = "synthetic"
        metadata["auth"] = dict(auth.sign(metadata))
        with self.assertRaises(c.SyncError):
            c._fts_authenticate_manifest(target, metadata)
        self.assertEqual(list((self.root / "target-private").iterdir()), [])

    def test_hmac_tamper_is_rejected_before_private_processing(self):
        source, target, _ = fixture(self.root)
        snap = source.push()
        metadata = json.loads(snap.manifest_path.read_bytes())
        metadata["created_at"] = "2026-01-01T00:00:00Z"
        snap.manifest_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises(c.SyncError):
            target.snapshots(verify=True)
        self.assertEqual(list((self.root / "target-private").iterdir()), [])
        self.assertEqual(c._fts_state(target)["last_pulled"], {})

    def _owner_failure(self, close_failure):
        source, target, _ = fixture(self.root)
        source.push()
        snapshot = target.snapshots(verify=False)[0]
        before = digest(target.config.database)
        aborted = []
        closed = []
        actual_abort = c._FtsPreparedArtifactOwner.abort
        actual_close = c._fts_close_connections

        def abort(owner, **kw):
            aborted.append(True)
            return actual_abort(owner, **kw)

        def close(connections, **kw):
            actual_close(connections, **kw)
            if close_failure and inspect.currentframe().f_back.f_code.co_name == "_fts_merge_received_snapshot":
                closed.append(True)
                raise c.SyncError("synthetic close failure")

        committed = [False]
        with (
            patch.object(c._FtsPreparedArtifactOwner, "abort", abort),
            patch.object(c, "_fts_close_connections", close),
            patch.object(c, "_fts_live_bind", side_effect=OSError("synthetic first bind failure")),
        ):
            with self.assertRaises((c.SyncError, OSError)):
                c._fts_merge_received_snapshot(target, snapshot, committed)
        self.assertTrue(aborted)
        self.assertEqual(bool(closed), close_failure)
        self.assertFalse(committed[0])
        self.assertEqual(digest(target.config.database), before)
        self.assertEqual(c._fts_state(target)["last_pulled"], {})
        self.assertEqual(list((self.root / "target-private").iterdir()), [])

    def test_F4_first_live_binding_failure_aborts_owner(self):
        self._owner_failure(False)

    def test_F4_R1_close_failure_still_aborts_owner(self):
        self._owner_failure(True)

    def test_F3_replica_post_replace_failure_restores_exact_old_target(self):
        import sqlite_transit_sync as package
        import sqlite_transit_sync.republica as rep

        source, target, auth = fixture(self.root)
        source.config.key_file.write_bytes(package.generate_key())
        publisher = rep.RepublicaTransit(
            source.config, source.policy, authenticator=auth, fts_contract=source._fts_contract
        )
        receiver = rep.RepublicaTransit(
            target.config, target.policy, authenticator=auth, fts_contract=target._fts_contract
        )
        publisher.publish()
        destination = receiver._republica_path("source")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            destination.parent.chmod(0o700)
        shutil.copyfile(target.config.database, destination)
        destination.chmod(0o444)
        before, mode = digest(destination), destination.stat().st_mode
        replaced = []
        injected = []
        actual_replace = rep.os.replace
        actual_validate = rep._fts_validate_input

        def replace(src, dst):
            result = actual_replace(src, dst)
            if Path(dst) == destination:
                replaced.append(digest(destination))
            return result

        def validate(owner, path, **kw):
            if replaced and Path(path) == destination and not injected:
                injected.append(True)
                raise c.SyncError("synthetic post-install verification failure")
            return actual_validate(owner, path, **kw)

        with patch.object(rep.os, "replace", replace), patch.object(rep, "_fts_validate_input", validate):
            with self.assertRaises(c.SyncError):
                receiver.import_republica("source")
        self.assertTrue(injected)
        self.assertNotEqual(replaced[0], before)
        self.assertEqual(digest(destination), before)
        self.assertEqual(destination.stat().st_mode, mode)
        self.assertEqual(list((self.root / "target-private").iterdir()), [])

    def test_post_commit_failure_keeps_partial_error_and_no_ack(self):
        source, target, _ = fixture(self.root)
        source.push()
        original = c._fts_live_check
        injected = []

        def fail_closed_check(bound, database, **kw):
            if Path(database) == target.config.database and kw.get("closed") and not injected:
                injected.append(True)
                raise c.SyncError("synthetic post-commit proof failure")
            return original(bound, database, **kw)

        with patch.object(c, "_fts_live_check", fail_closed_check):
            with self.assertRaises(c.FtsCommittedPartialError):
                target.pull()
        self.assertTrue(injected)
        db = sqlite3.connect(target.config.database)
        try:
            self.assertEqual(db.execute("SELECT id FROM entries ORDER BY id").fetchall(), [(1,), (2,)])
        finally:
            db.close()
        self.assertEqual(c._fts_state(target)["last_pulled"], {})
        self.assertEqual(len(target.pending()), 1)
