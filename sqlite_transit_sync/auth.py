"""Transport-independent HMAC key resolution and snapshot preflight.

This module deliberately operates on explicit manifest and snapshot paths.  It
does not construct :class:`TransitSync`, open SQLite, merge rows, or read/write
sync state.  Secret material enters only through an injected resolver and is
kept in the in-memory :class:`HMACSnapshotAuthenticator` key ring.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .core import (
    PROTOCOL_VERSION,
    HMACKey,
    HMACSnapshotAuthenticator,
    Snapshot,
    SnapshotAuthenticator,
    SyncError,
    _assert_no_sqlite_sidecars,
    _assert_transit_regular_file,
    _parse_utc_token,
    _safe_identifier,
    _sha256,
    _snapshot_filename,
)


class SecretResolutionError(SyncError):
    """A referenced HMAC secret could not be resolved safely."""


@dataclass(frozen=True, slots=True)
class HMACKeyReference:
    """Non-secret locator for one application-owned HMAC key."""

    key_id: str
    service: str
    account: str
    sender: str

    def __post_init__(self) -> None:
        for field_name in ("key_id", "service", "account", "sender"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ValueError(f"HMAC key reference {field_name} must be a non-empty string")
        if _safe_identifier(self.sender, "sender") != self.sender:
            raise ValueError("HMAC key reference sender must be a safe identifier")

    def as_dict(self) -> dict[str, str]:
        """Return the serializable reference; secret material is never included."""

        return {
            "key_id": self.key_id,
            "service": self.service,
            "account": self.account,
            "sender": self.sender,
        }


class SecretResolver(Protocol):
    """Application boundary for resolving one non-secret key reference."""

    def resolve_secret(self, reference: HMACKeyReference) -> bytes | str | None:
        """Return secret bytes/text, or ``None`` when the reference is unknown."""


_SECRET_BACKEND_FAILURE = object()


def _call_secret_backend(operation: Callable[[], Any]) -> Any:
    """Call a secret backend without retaining its exception or traceback."""

    try:
        return operation()
    except Exception:
        return _SECRET_BACKEND_FAILURE


class OSKeyringSecretResolver:
    """Resolve references through the optional ``keyring`` package, loaded lazily."""

    def resolve_secret(self, reference: HMACKeyReference) -> str | None:
        keyring = _call_secret_backend(lambda: importlib.import_module("keyring"))
        if keyring is _SECRET_BACKEND_FAILURE:
            raise SecretResolutionError(
                "OS keyring resolution requires the optional 'keyring' package"
            )
        secret = _call_secret_backend(
            lambda: keyring.get_password(reference.service, reference.account)
        )
        if secret is _SECRET_BACKEND_FAILURE:
            raise SecretResolutionError(
                f"OS keyring lookup failed for HMAC key reference {reference.key_id!r}"
            )
        return secret


def load_hmac_authenticator(
    references: Iterable[HMACKeyReference],
    *,
    active_key_id: str,
    resolver: SecretResolver,
    trusted_senders: Iterable[str] | None = None,
    trust_source: str = "secret-resolver",
) -> HMACSnapshotAuthenticator:
    """Resolve key references into the existing in-memory HMAC authenticator.

    Configuration contains only ``service``/``account``/``sender`` references.
    Raw secret values are accepted only as resolver return values and are never
    serialized, logged, or included in an exception.
    """

    if resolver is None or not callable(getattr(resolver, "resolve_secret", None)):
        raise TypeError("resolver must implement resolve_secret(reference)")
    refs = list(references)
    if not refs:
        raise SecretResolutionError("At least one HMAC key reference is required")
    by_id: dict[str, HMACKeyReference] = {}
    for reference in refs:
        if not isinstance(reference, HMACKeyReference):
            raise TypeError("references must contain only HMACKeyReference values")
        if reference.key_id in by_id:
            raise SecretResolutionError(f"Duplicate HMAC key reference: {reference.key_id!r}")
        by_id[reference.key_id] = reference
    if active_key_id not in by_id:
        raise SecretResolutionError(f"Unknown active HMAC key reference: {active_key_id!r}")

    keys: dict[str, HMACKey] = {}
    for key_id, reference in by_id.items():
        secret = _call_secret_backend(lambda: resolver.resolve_secret(reference))
        if secret is _SECRET_BACKEND_FAILURE:
            raise SecretResolutionError(
                f"Secret resolver failed for HMAC key reference {key_id!r}"
            )
        if isinstance(secret, str):
            material = secret.encode("utf-8")
        elif isinstance(secret, bytes):
            material = secret
        elif secret is None:
            raise SecretResolutionError(f"No secret found for HMAC key reference {key_id!r}")
        else:
            raise SecretResolutionError(
                f"Secret resolver returned an invalid value for HMAC key reference {key_id!r}"
            )
        if not material:
            raise SecretResolutionError(f"Empty secret for HMAC key reference {key_id!r}")
        keys[key_id] = HMACKey(sender=reference.sender, secret=material)

    return HMACSnapshotAuthenticator(
        keys=keys,
        active_key_id=active_key_id,
        trusted_senders=trusted_senders,
        trust_source=trust_source,
    )


def verify_authenticated_snapshot(
    manifest_path: str | Path,
    snapshot_path: str | Path,
    *,
    authenticator: SnapshotAuthenticator,
) -> Snapshot:
    """Authenticate and hash-check an explicit snapshot without opening SQLite.

    Both files must be direct regular siblings.  The function performs no merge,
    creates no files, and never reads or advances a sync-state document.
    """

    manifest_path = Path(manifest_path)
    snapshot_path = Path(snapshot_path)
    root = manifest_path.parent.resolve()
    _assert_transit_regular_file(manifest_path, root, "Manifest")
    _assert_transit_regular_file(snapshot_path, root, "Snapshot")
    _assert_no_sqlite_sidecars(snapshot_path)
    if authenticator is None or not callable(getattr(authenticator, "verify", None)):
        raise TypeError("authenticator must implement verify(manifest, envelope)")

    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyncError(f"Invalid manifest {manifest_path}: {error}") from error
    if not isinstance(manifest, dict):
        raise SyncError(f"Invalid manifest object: {manifest_path}")
    required = {
        "protocol",
        "namespace",
        "node_id",
        "created_at",
        "snapshot",
        "sha256",
        "size",
        "auth",
    }
    if not required.issubset(manifest):
        raise SyncError(f"Incomplete authenticated manifest: {manifest_path}")
    if type(manifest["protocol"]) is not int or manifest["protocol"] != PROTOCOL_VERSION:
        raise SyncError(f"Unsupported protocol in {manifest_path}")
    if not all(
        isinstance(manifest[key], str)
        for key in ("namespace", "node_id", "created_at", "snapshot", "sha256")
    ):
        raise SyncError(f"Invalid manifest value types: {manifest_path}")
    namespace = _safe_identifier(manifest["namespace"], "namespace")
    node_id = _safe_identifier(manifest["node_id"], "node")
    if namespace != manifest["namespace"] or node_id != manifest["node_id"]:
        raise SyncError(f"Unsafe manifest identity in {manifest_path}")
    try:
        _parse_utc_token(manifest["created_at"])
    except ValueError as error:
        raise SyncError(f"Invalid snapshot timestamp in {manifest_path}") from error
    expected_name = _snapshot_filename(namespace, node_id, manifest["created_at"])
    if (
        manifest["snapshot"] != expected_name
        or snapshot_path.name != expected_name
        or manifest_path.name != f"{expected_name}.json"
        or snapshot_path.parent.resolve() != root
    ):
        raise SyncError(f"Manifest and explicit snapshot identity do not match: {manifest_path}")
    if not isinstance(manifest["auth"], Mapping):
        raise SyncError("Snapshot authentication envelope is missing or malformed")
    if not isinstance(manifest["sha256"], str) or len(manifest["sha256"]) != 64:
        raise SyncError(f"Invalid SHA-256 in {manifest_path}")
    try:
        int(manifest["sha256"], 16)
    except ValueError as error:
        raise SyncError(f"Invalid SHA-256 in {manifest_path}") from error
    if type(manifest["size"]) is not int or manifest["size"] < 0:
        raise SyncError(f"Invalid snapshot size in {manifest_path}")

    try:
        authenticator.verify(manifest, manifest["auth"])
    except SyncError:
        raise
    except Exception as error:
        raise SyncError("Snapshot authentication failed") from error
    if snapshot_path.stat().st_size != manifest["size"] or _sha256(snapshot_path) != manifest["sha256"]:
        raise SyncError(f"Snapshot checksum mismatch: {snapshot_path}")

    return Snapshot(
        path=snapshot_path,
        manifest_path=manifest_path,
        node_id=node_id,
        namespace=namespace,
        created_at=manifest["created_at"],
        sha256=manifest["sha256"],
        size=manifest["size"],
    )
