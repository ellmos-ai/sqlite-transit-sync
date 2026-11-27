"""FTS paths must retain main's security gates and untyped Republica compatibility."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_fts_lifecycle import fixture

import sqlite_transit_sync.core as core
import sqlite_transit_sync.republica as republica


class FtsIntegrationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        for path in self.root.rglob("*.sqlite"):
            try:
                path.chmod(0o600)
            except OSError:
                pass
        self.temp.cleanup()

    def test_fts_republica_rechecks_key_containment_before_dispatch(self):
        source, _, auth = fixture(self.root)
        replica = republica.RepublicaTransit(source.config, authenticator=auth,
                                             fts_contract=source._fts_contract)
        key = source.config.transit / 'synthetic.key'
        key.write_bytes(b'not-a-real-key')
        replica.config.key_file = key
        with patch.object(republica, '_fts_republica_publish') as dispatch:
            with self.assertRaises(core.SyncError):
                replica.publish()
        dispatch.assert_not_called()

    def test_fts_push_refuses_changed_transit_after_preparation(self):
        source, _, _ = fixture(self.root)
        original = source.config.transit
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir(mode=0o700)
        prepare = core._FtsPreparedArtifactOwner.prepare_live

        def mutate(owner):
            result = prepare(owner)
            owner.sync.config.transit = elsewhere
            return result

        with patch.object(core._FtsPreparedArtifactOwner, 'prepare_live', mutate):
            with self.assertRaises(core.SyncError):
                source.push()
        self.assertEqual([], list(original.iterdir()))
        self.assertEqual([], list(elsewhere.iterdir()))

    def test_fts_push_cleans_own_artifacts_if_identity_changes_after_link(self):
        source, _, _ = fixture(self.root)
        original = source.config.transit
        publish_link = core._fts_publish_link

        def mutate_after_link(*args, **kwargs):
            result = publish_link(*args, **kwargs)
            source.config.namespace = 'changed'
            return result

        with patch.object(core, '_fts_publish_link', mutate_after_link):
            with self.assertRaises(core.SyncError):
                source.push()
        self.assertEqual([], list(original.iterdir()))

    def test_fts_republica_refuses_key_change_during_preparation(self):
        source, _, auth = fixture(self.root)
        source.config.key_file.write_bytes(republica.generate_key())
        replica = republica.RepublicaTransit(source.config, authenticator=auth,
                                             fts_contract=source._fts_contract)
        prepare = core._FtsPreparedArtifactOwner.prepare_live

        def mutate(owner):
            result = prepare(owner)
            owner.sync.config.key_file = owner.sync.config.transit / 'moved.key'
            return result

        with patch.object(core._FtsPreparedArtifactOwner, 'prepare_live', mutate):
            with self.assertRaises(core.SyncError):
                replica.publish()
        self.assertEqual([], [path for path in source.config.transit.rglob('*') if path.is_file() or path.is_symlink()])


class UntypedRepublicaFtsSecurityTests(unittest.TestCase):
    """Untyped Republica supports verified external-content FTS5 without relaxing C1."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transit = self.root / 'transit'
        self.key_file = self.root / 'keys' / 'replica.key'
        self.key_file.parent.mkdir(parents=True)
        self.key_file.write_bytes(republica.generate_key())
        self.a_db = self.root / 'a.db'
        self.b_db = self.root / 'b.db'

    def tearDown(self):
        for path in self.root.rglob("*.sqlite"):
            try:
                path.chmod(0o600)
            except OSError:
                pass
        self.temp.cleanup()

    def _config(self, db_path: Path, node_id: str, **extra) -> core.SyncConfig:
        return core.SyncConfig(
            database=db_path,
            transit=self.transit,
            state=self.root / f'{node_id}-state.json',
            node_id=node_id,
            namespace='compat-fts',
            key_file=self.key_file,
            republica_root=self.root / 'replicas',
            **extra,
        )

    def _create_base_db(self, db_path: Path, fts_ddl: str) -> None:
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE items(id TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE secrets(id TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE items_data(id TEXT PRIMARY KEY, note TEXT NOT NULL);
                """
                + fts_ddl
            )
            conn.execute("INSERT INTO items VALUES('r1', 'alpha synthetic note', '2026-01-01T00:00:00Z')")
            conn.execute("INSERT INTO items_data VALUES('d1', 'ordinary table ending in _data')")
            conn.execute("INSERT INTO secrets VALUES('s1', 'never-published-marker', '2026-01-01T00:00:00Z')")
            conn.commit()
        finally:
            conn.close()

    def test_untyped_push_still_refuses_external_fts5(self):
        self._create_base_db(
            self.a_db,
            """
            CREATE VIRTUAL TABLE items_fts USING fts5(value, content=items, content_rowid=rowid);
            INSERT INTO items_fts(items_fts) VALUES('rebuild');
            """,
        )
        # Rebuild after insert so FTS5 index is completely synced; push() must still refuse.
        conn = sqlite3.connect(self.a_db)
        try:
            conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            conn.commit()
        finally:
            conn.close()
        sync = core.TransitSync(self._config(self.a_db, 'node-a'))
        with self.assertRaisesRegex(core.SyncError, r"\[virtual-or-shadow\]"):
            sync.push()

    def test_untyped_republica_roundtrip_preserves_custom_fts5_and_ordinary_data_table(self):
        self._create_base_db(
            self.a_db,
            """
            CREATE VIRTUAL TABLE items_fts USING fts5(value, content="items", content_rowid=rowid, tokenize='porter');
            """,
        )
        conn = sqlite3.connect(self.a_db)
        try:
            conn.execute("INSERT INTO items_fts(items_fts, rank) VALUES('pgsz', 1024)")
            conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            conn.commit()
        finally:
            conn.close()
        self._create_base_db(self.b_db, "")

        pub = republica.RepublicaTransit(self._config(self.a_db, 'node-a'))
        imp = republica.RepublicaTransit(self._config(self.b_db, 'node-b'))
        pub.publish()
        reports = imp.import_republica()
        self.assertEqual(1, len(reports))
        self.assertEqual(["items_fts"], reports[0].rebuilt_indexes)

        ro = sqlite3.connect(f"file:{Path(reports[0].replica_path).as_posix()}?mode=ro", uri=True)
        try:
            self.assertEqual(0, ro.execute("SELECT count(*) FROM secrets").fetchone()[0])
            self.assertEqual(
                [("d1", "ordinary table ending in _data")],
                ro.execute("SELECT id, note FROM items_data").fetchall(),
            )
            self.assertEqual(1, ro.execute("SELECT count(*) FROM items_fts WHERE items_fts MATCH 'synthet'").fetchone()[0])
        finally:
            ro.close()

    def test_untyped_republica_refuses_stale_and_orphaned_fts_tokens(self):
        self._create_base_db(
            self.a_db,
            "CREATE VIRTUAL TABLE items_fts USING fts5(value, content=items, content_rowid=rowid);",
        )
        conn = sqlite3.connect(self.a_db)
        try:
            conn.execute("INSERT INTO items VALUES('r2', ?, '2026-01-01T00:00:00Z')", ("ghp_" + "Z" * 24,))
            conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            # Delete base row without updating FTS -> leaves orphaned secret token in shadow pages.
            conn.execute("DELETE FROM items WHERE id='r2'")
            conn.commit()
        finally:
            conn.close()
        pub = republica.RepublicaTransit(self._config(self.a_db, 'node-a'))
        with self.assertRaisesRegex(core.SyncError, r"\[fts-integrity\]"):
            pub.publish()
        self.assertEqual([], list(self.transit.rglob('*.republica')))

    def test_untyped_republica_refuses_disallowed_virtual_and_manipulated_shadow_tables(self):
        cases = [
            (
                "contentless",
                "CREATE VIRTUAL TABLE items_fts USING fts5(value, content='');",
            ),
            (
                "internal-fts5",
                "CREATE VIRTUAL TABLE items_fts USING fts5(value);",
            ),
            (
                "fts3",
                "CREATE VIRTUAL TABLE items_fts USING fts3(value);",
            ),
            (
                "redacted-content-table",
                "CREATE VIRTUAL TABLE items_fts USING fts5(value, content=secrets, content_rowid=rowid);",
            ),
        ]
        for label, ddl in cases:
            with self.subTest(case=label):
                db_path = self.root / f"{label}.db"
                self._create_base_db(db_path, ddl)
                pub = republica.RepublicaTransit(self._config(db_path, f"node-{label}"))
                with self.assertRaisesRegex(core.SyncError, r"\[virtual-or-shadow\]"):
                    pub.publish()

        # Manipulated shadow schema (extra column on shadow table) must also fail closed.
        tampered = self.root / "tampered-shadow.db"
        self._create_base_db(
            tampered,
            "CREATE VIRTUAL TABLE items_fts USING fts5(value, content=items, content_rowid=rowid);",
        )
        conn = sqlite3.connect(tampered)
        try:
            conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute(
                "UPDATE sqlite_schema SET sql = 'CREATE TABLE ''items_fts_data''(id INTEGER PRIMARY KEY, block BLOB, extra TEXT)' "
                "WHERE name = 'items_fts_data'"
            )
            conn.commit()
        finally:
            conn.close()
        pub = republica.RepublicaTransit(self._config(tampered, "node-tampered"))
        with self.assertRaises(core.SyncError):
            pub.publish()

    def test_untyped_republica_blocks_credentials_in_schema_trigger_and_fts_config(self):
        token = "ghp_" + "M" * 24
        # 1. Credential in trigger DDL
        trig_db = self.root / "trig.db"
        self._create_base_db(
            trig_db,
            f"""
            CREATE VIRTUAL TABLE items_fts USING fts5(value, content=items, content_rowid=rowid);
            CREATE TRIGGER items_ai AFTER INSERT ON items BEGIN
                -- {token}
                INSERT INTO items_fts(rowid, value) VALUES (new.rowid, new.value);
            END;
            """,
        )
        conn = sqlite3.connect(trig_db)
        try:
            conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            conn.commit()
        finally:
            conn.close()
        pub = republica.RepublicaTransit(self._config(trig_db, "node-trig"))
        with self.assertRaises(core.SyncError) as caught:
            pub.publish()
        self.assertIn("schema#", str(caught.exception))
        self.assertNotIn(token, str(caught.exception))

        # 2. Credential in FTS config rank expression
        cfg_db = self.root / "cfg.db"
        self._create_base_db(
            cfg_db,
            "CREATE VIRTUAL TABLE items_fts USING fts5(value, content=items, content_rowid=rowid);",
        )
        conn = sqlite3.connect(cfg_db)
        try:
            conn.execute("INSERT INTO items_fts(items_fts, rank) VALUES('rank', ?)", (f"bm25() /* {token} */",))
            conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            conn.commit()
        finally:
            conn.close()
        pub_cfg = republica.RepublicaTransit(self._config(cfg_db, "node-cfg"))
        with self.assertRaises(core.SyncError) as caught_cfg:
            pub_cfg.publish()
        self.assertIn("items_fts_config.v", str(caught_cfg.exception))
        self.assertNotIn(token, str(caught_cfg.exception))


if __name__ == '__main__':
    unittest.main()
