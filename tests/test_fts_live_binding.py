"""Real SQLite sidecar retirement without weakening live identity gates."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sqlite_transit_sync.core as c


class FtsLiveBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / "database.sqlite"
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE value(id INTEGER PRIMARY KEY,value TEXT)")
        db.commit()
        db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_commit_retires_journal_and_reopen_binds_next_transaction(self):
        bound = c._fts_live_bind(self.path)
        main_identity = bound[self.path]
        journal = self.path.with_name(self.path.name + "-journal")
        for index in (1, 2):
            db = sqlite3.connect(self.path)
            try:
                c._fts_live_check(bound, self.path)
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO value VALUES(?,?)", (index, "synthetic"))
                c._fts_live_check(bound, self.path)
                self.assertIsNotNone(bound[journal])
                self.assertTrue(journal.exists())
                db.commit()
                self.assertFalse(journal.exists(), "DELETE journal retires at commit, before close")
            finally:
                db.close()
            c._fts_live_check(bound, self.path, closed=True)
            self.assertIsNone(bound[journal])
            self.assertEqual(bound[self.path], main_identity)
        db = sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute("SELECT count(*) FROM value").fetchone(), (2,))
        finally:
            db.close()

    def test_disappearing_bound_sidecar_while_live_is_refused(self):
        journal = self.path.with_name(self.path.name + "-journal")
        journal.write_bytes(b"synthetic-journal")
        bound = c._fts_live_bind(self.path)
        journal.unlink()
        with self.assertRaisesRegex(c.SyncError, "disappeared"):
            c._fts_live_check(bound, self.path)
        self.assertIsNotNone(bound[journal])

    def test_missing_main_is_refused_even_after_close(self):
        bound = c._fts_live_bind(self.path)
        self.path.unlink()
        with self.assertRaisesRegex(c.SyncError, "disappeared"):
            c._fts_live_check(bound, self.path, closed=True)

    def test_sidecar_replacement_is_not_retirement(self):
        journal = self.path.with_name(self.path.name + "-journal")
        journal.write_bytes(b"synthetic-old")
        bound = c._fts_live_bind(self.path)
        journal.rename(self.root / "retained-original")
        journal.write_bytes(b"synthetic-new")
        for closed in (False, True):
            with self.subTest(closed=closed), self.assertRaisesRegex(c.SyncError, "identity changed"):
                c._fts_live_check(bound, self.path, closed=closed)
        self.assertEqual(journal.read_bytes(), b"synthetic-new")
        self.assertEqual((self.root / "retained-original").read_bytes(), b"synthetic-old")

    def test_sidecar_hardlink_is_not_admitted(self):
        bound = c._fts_live_bind(self.path)
        journal = self.path.with_name(self.path.name + "-journal")
        target = self.root / "other-file"
        target.write_bytes(b"synthetic")
        os.link(target, journal)
        with self.assertRaisesRegex(c.SyncError, "kind/link"):
            c._fts_live_check(bound, self.path, closed=True)

    def test_sidecar_symlink_is_not_admitted(self):
        bound = c._fts_live_bind(self.path)
        journal = self.path.with_name(self.path.name + "-journal")
        target = self.root / "other-file"
        target.write_bytes(b"synthetic")
        try:
            journal.symlink_to(target)
        except OSError:
            self.skipTest("platform cannot create own synthetic symlink")
        with self.assertRaisesRegex(c.SyncError, "alias"):
            c._fts_live_check(bound, self.path, closed=True)
