from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlite_transit_sync import (
    HMACKey,
    HMACKeyReference,
    HMACSnapshotAuthenticator,
    OSKeyringSecretResolver,
    SecretResolutionError,
    SyncError,
    load_hmac_authenticator,
    verify_authenticated_snapshot,
)


class MappingResolver:
    def __init__(self, values: dict[tuple[str, str], bytes | str | None]) -> None:
        self.values = values
        self.calls: list[dict[str, str]] = []

    def resolve_secret(self, reference: HMACKeyReference) -> bytes | str | None:
        self.calls.append(reference.as_dict())
        return self.values.get((reference.service, reference.account))


class AuthPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_ref = HMACKeyReference("node-a-v1", "ocean-sync", "node-a-v1", "node-a")
        self.new_ref = HMACKeyReference("node-a-v2", "ocean-sync", "node-a-v2", "node-a")
        self.resolver = MappingResolver(
            {
                ("ocean-sync", "node-a-v1"): b"A" * 32,
                ("ocean-sync", "node-a-v2"): b"B" * 32,
            }
        )
        self.verifier = load_hmac_authenticator(
            [self.old_ref, self.new_ref],
            active_key_id="node-a-v2",
            resolver=self.resolver,
            trusted_senders={"node-a"},
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_pair(
        self,
        signer: HMACSnapshotAuthenticator,
        *,
        payload: bytes = b"opaque projection bytes",
        sender: str = "node-a",
        auth: object = True,
    ) -> tuple[Path, Path]:
        created_at = "20260915T010203000000Z"
        name = f"demo__{sender}__{created_at}.sqlite-snapshot"
        snapshot = self.root / name
        manifest_path = self.root / f"{name}.json"
        snapshot.write_bytes(payload)
        manifest: dict[str, object] = {
            "protocol": 1,
            "namespace": "demo",
            "node_id": sender,
            "created_at": created_at,
            "snapshot": name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "redacted_tables": [],
        }
        if auth is True:
            manifest["auth"] = dict(signer.sign(manifest))
        elif auth is not False:
            manifest["auth"] = auth
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path, snapshot

    def test_references_are_secret_free_and_rotation_accepts_old_key(self) -> None:
        old_signer = load_hmac_authenticator(
            [self.old_ref], active_key_id="node-a-v1", resolver=self.resolver
        )
        manifest, snapshot = self._write_pair(old_signer)

        verified = verify_authenticated_snapshot(
            manifest, snapshot, authenticator=self.verifier
        )

        self.assertEqual(snapshot, verified.path)
        self.assertEqual(
            {"key_id", "service", "account", "sender"}, set(self.old_ref.as_dict())
        )
        self.assertNotIn("secret", self.old_ref.as_dict())

    def test_unknown_key_and_sender_fail_closed(self) -> None:
        unknown_key = HMACSnapshotAuthenticator(
            keys={"node-a-v3": HMACKey("node-a", b"C" * 32)},
            active_key_id="node-a-v3",
            trust_source="secret-resolver",
        )
        manifest, snapshot = self._write_pair(unknown_key)
        with self.assertRaisesRegex(SyncError, "Unknown snapshot authentication key"):
            verify_authenticated_snapshot(manifest, snapshot, authenticator=self.verifier)

        foreign_ref = HMACKeyReference("node-z-v1", "ocean-sync", "node-z-v1", "node-z")
        foreign_resolver = MappingResolver({("ocean-sync", "node-z-v1"): b"Z" * 32})
        foreign_signer = load_hmac_authenticator(
            [foreign_ref], active_key_id="node-z-v1", resolver=foreign_resolver
        )
        foreign_verifier = load_hmac_authenticator(
            [foreign_ref],
            active_key_id="node-z-v1",
            resolver=foreign_resolver,
            trusted_senders={"node-a"},
        )
        manifest.unlink()
        snapshot.unlink()
        manifest, snapshot = self._write_pair(foreign_signer, sender="node-z")
        with self.assertRaisesRegex(SyncError, "sender is not trusted"):
            verify_authenticated_snapshot(manifest, snapshot, authenticator=foreign_verifier)

    def test_manifest_and_snapshot_tamper_fail_closed(self) -> None:
        manifest, snapshot = self._write_pair(self.verifier)
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["size"] += 1
        manifest.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(SyncError, "signature mismatch"):
            verify_authenticated_snapshot(manifest, snapshot, authenticator=self.verifier)

        manifest.unlink()
        snapshot.unlink()
        manifest, snapshot = self._write_pair(self.verifier)
        snapshot.write_bytes(b"tampered")
        with self.assertRaisesRegex(SyncError, "checksum mismatch"):
            verify_authenticated_snapshot(manifest, snapshot, authenticator=self.verifier)

    def test_missing_or_malformed_inputs_fail_closed(self) -> None:
        missing_manifest = self.root / "missing.sqlite-snapshot.json"
        missing_snapshot = self.root / "missing.sqlite-snapshot"
        with self.assertRaisesRegex(SyncError, "Manifest"):
            verify_authenticated_snapshot(
                missing_manifest, missing_snapshot, authenticator=self.verifier
            )

        manifest, snapshot = self._write_pair(self.verifier)
        snapshot.unlink()
        with self.assertRaisesRegex(SyncError, "Snapshot"):
            verify_authenticated_snapshot(manifest, snapshot, authenticator=self.verifier)

        manifest, snapshot = self._write_pair(self.verifier, auth=False)
        with self.assertRaisesRegex(SyncError, "Incomplete authenticated manifest"):
            verify_authenticated_snapshot(manifest, snapshot, authenticator=self.verifier)

        manifest.unlink()
        snapshot.unlink()
        manifest, snapshot = self._write_pair(self.verifier, auth="not-an-envelope")
        with self.assertRaisesRegex(SyncError, "missing or malformed"):
            verify_authenticated_snapshot(manifest, snapshot, authenticator=self.verifier)

    def test_sidecar_is_rejected_without_mutation(self) -> None:
        manifest, snapshot = self._write_pair(self.verifier)
        sidecar = snapshot.with_name(snapshot.name + "-wal")
        sidecar.write_bytes(b"synthetic sidecar")
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}

        with self.assertRaisesRegex(SyncError, "sidecars"):
            verify_authenticated_snapshot(manifest, snapshot, authenticator=self.verifier)

        after = {path.name: path.read_bytes() for path in self.root.iterdir()}
        self.assertEqual(before, after)

    def test_success_does_not_open_sqlite_or_mutate_state_or_files(self) -> None:
        manifest, snapshot = self._write_pair(self.verifier, payload=b"not a SQLite database")
        database = self.root / "application.sqlite"
        database.write_bytes(b"application database sentinel")
        state = self.root / "state.json"
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}

        with patch("sqlite_transit_sync.core.sqlite3.connect") as connect:
            verify_authenticated_snapshot(manifest, snapshot, authenticator=self.verifier)

        connect.assert_not_called()
        after = {path.name: path.read_bytes() for path in self.root.iterdir()}
        self.assertEqual(before, after)
        self.assertFalse(state.exists())

    def test_resolver_none_and_missing_optional_keyring_fail_closed(self) -> None:
        empty = MappingResolver({})
        with self.assertRaisesRegex(SecretResolutionError, "No secret found"):
            load_hmac_authenticator(
                [self.old_ref], active_key_id="node-a-v1", resolver=empty
            )

        with patch(
            "sqlite_transit_sync.auth.importlib.import_module",
            side_effect=ModuleNotFoundError("keyring"),
        ):
            with self.assertRaisesRegex(SecretResolutionError, "optional 'keyring'"):
                OSKeyringSecretResolver().resolve_secret(self.old_ref)


if __name__ == "__main__":
    unittest.main()
