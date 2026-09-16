from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlite_transit_sync import (
    ProjectionContract,
    ProjectionContractError,
    bundled_projection_contracts,
    verify_projection_database,
)

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "projections"


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _create_projection(path: Path, contract: ProjectionContract, tables: dict[str, list[dict]]) -> None:
    connection = sqlite3.connect(path)
    try:
        for table in contract.tables:
            definitions = []
            primary_key = []
            for column in table.columns:
                definition = f"{_quote(column.name)} {column.sqlite_type}"
                if column.not_null:
                    definition += " NOT NULL"
                definitions.append(definition)
                if column.primary_key:
                    primary_key.append((column.primary_key, column.name))
            if primary_key:
                keys = ", ".join(_quote(name) for _, name in sorted(primary_key))
                definitions.append(f"PRIMARY KEY ({keys})")
            connection.execute(f"CREATE TABLE {_quote(table.name)} ({', '.join(definitions)})")
            expected_columns = [column.name for column in table.columns]
            for row in tables[table.name]:
                if set(row) != set(expected_columns):
                    raise AssertionError(f"Fixture columns do not match {table.name}")
                placeholders = ", ".join("?" for _ in expected_columns)
                columns = ", ".join(_quote(name) for name in expected_columns)
                connection.execute(
                    f"INSERT INTO {_quote(table.name)} ({columns}) VALUES ({placeholders})",
                    tuple(row[name] for name in expected_columns),
                )
        connection.commit()
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProjectionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _materialize(self, fixture_name: str, snapshot_index: int = 0) -> tuple[dict, dict, ProjectionContract, Path]:
        fixture = _load_fixture(fixture_name)
        snapshot = fixture["snapshots"][snapshot_index]
        contract = ProjectionContract.from_file(fixture["contract"])
        path = self.root / f"{Path(fixture_name).stem}-{snapshot_index}.sqlite"
        _create_projection(path, contract, snapshot["tables"])
        return fixture, snapshot, contract, path

    def _verify(self, fixture: dict, snapshot: dict, contract: ProjectionContract, path: Path):
        return verify_projection_database(
            path,
            contract,
            consumer_id=fixture["consumer_id"],
            minimum_offline_seconds=fixture["minimum_offline_seconds"],
            previous_checkpoint=snapshot["previous_checkpoint"],
        )

    def test_bundled_contracts_are_versioned_and_loadable(self) -> None:
        self.assertEqual(
            (
                "abotracker-subscription-status-projection.v1",
                "accounts-balance-projection.v1",
                "mediplaner-reminder-projection.v1",
                "routinika-reminder-projection.v1",
                "versicherungsmanager-deadline-projection.v1",
            ),
            bundled_projection_contracts(),
        )
        for name in bundled_projection_contracts():
            contract = ProjectionContract.from_file(name)
            self.assertEqual("1.0.0", contract.contract_version)
            self.assertNotEqual((), contract.record_tables)
            columns = {column.name for table in contract.tables for column in table.columns}
            self.assertTrue(
                columns.isdisjoint(
                    {
                        "client_name",
                        "account_number",
                        "bank_name",
                        "bic",
                        "billing_cycle",
                        "cancellation_url",
                        "diagnosis",
                        "dose",
                        "holder_name",
                        "iban",
                        "last_payment_date",
                        "mail_query",
                        "medication_name",
                        "model_name",
                        "note",
                        "notes",
                        "policy_area",
                        "policy_number",
                        "policy_title",
                        "premium_amount",
                        "provider",
                        "provider_name",
                        "quantity",
                        "routine_title",
                        "stock_level",
                        "subscription_price",
                        "valid_from",
                        "window_keywords",
                    }
                )
            )

    def test_abotracker_contract_excludes_identity_cost_and_inferred_deadlines(self) -> None:
        contract = ProjectionContract.from_file("abotracker-subscription-status-projection.v1")
        columns = {column.name for column in contract.table("subscription_status").columns}
        self.assertEqual(
            {
                "record_ref",
                "observed_at",
                "state",
                "record_version",
                "source_checkpoint",
                "publisher_instance",
            },
            columns,
        )
        self.assertTrue(
            columns.isdisjoint(
                {
                    "provider",
                    "model_name",
                    "price",
                    "billing_cycle",
                    "last_payment_date",
                    "valid_from",
                    "due_at",
                    "window_end_at",
                }
            )
        )

    def test_all_synthetic_initial_and_resume_fixtures_verify_without_mutation(self) -> None:
        fixture_names = (
            "accounts-balance-projection.v1.fixture.json",
            "abotracker-subscription-status-projection.v1.fixture.json",
            "mediplaner-reminder-projection.v1.fixture.json",
            "routinika-reminder-projection.v1.fixture.json",
            "versicherungsmanager-deadline-projection.v1.fixture.json",
        )
        for fixture_name in fixture_names:
            for index in (0, 1):
                with self.subTest(fixture=fixture_name, snapshot=index):
                    fixture, snapshot, contract, path = self._materialize(fixture_name, index)
                    before = _sha256(path)
                    report = self._verify(fixture, snapshot, contract, path)
                    self.assertEqual(before, _sha256(path))
                    self.assertTrue(report.read_only)
                    self.assertGreater(report.source_checkpoint, snapshot["previous_checkpoint"])
                    self.assertEqual(path.name, report.database_name)

    def test_cli_verifier_emits_json_and_does_not_require_sync_config(self) -> None:
        fixture, snapshot, _contract, path = self._materialize(
            "routinika-reminder-projection.v1.fixture.json", 1
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sqlite_transit_sync",
                "verify-projection",
                "--contract",
                fixture["contract"],
                "--database",
                str(path),
                "--consumer-id",
                fixture["consumer_id"],
                "--minimum-offline-seconds",
                str(fixture["minimum_offline_seconds"]),
                "--previous-checkpoint",
                str(snapshot["previous_checkpoint"]),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual("verified-read-only-projection", payload["result"]["status"])

    def test_table_and_column_allowlist_rejects_privacy_expansion(self) -> None:
        fixture, snapshot, contract, path = self._materialize(
            "mediplaner-reminder-projection.v1.fixture.json"
        )
        connection = sqlite3.connect(path)
        try:
            connection.execute("ALTER TABLE medication_due ADD COLUMN medication_name TEXT")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ProjectionContractError, "column allowlist"):
            self._verify(fixture, snapshot, contract, path)

        _path2 = self.root / "extra-table.sqlite"
        _create_projection(_path2, contract, snapshot["tables"])
        connection = sqlite3.connect(_path2)
        try:
            connection.execute("CREATE TABLE private_notes (note TEXT)")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ProjectionContractError, "table allowlist"):
            self._verify(fixture, snapshot, contract, _path2)

    def test_opaque_ids_enums_and_datetime_windows_fail_closed(self) -> None:
        fixture, snapshot, contract, path = self._materialize(
            "routinika-reminder-projection.v1.fixture.json"
        )
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "UPDATE routine_due SET record_ref = 'Morning routine', state = 'maybe', "
                "window_end_at = '2026-08-22T06:00:00Z'"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ProjectionContractError):
            self._verify(fixture, snapshot, contract, path)

    def test_accounts_contract_rejects_an_unmasked_iban_in_the_display_name(self) -> None:
        fixture, snapshot, contract, path = self._materialize(
            "accounts-balance-projection.v1.fixture.json"
        )
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "UPDATE account_balances SET name = 'Haushalt DE89370400440532013000'"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ProjectionContractError, "pattern"):
            self._verify(fixture, snapshot, contract, path)

    def test_provenance_checkpoint_and_loop_guard_fail_closed(self) -> None:
        fixture, snapshot, contract, path = self._materialize(
            "mediplaner-reminder-projection.v1.fixture.json"
        )
        with self.assertRaisesRegex(ProjectionContractError, "Loop guard"):
            verify_projection_database(
                path,
                contract,
                consumer_id="mediplaner-primary",
                minimum_offline_seconds=fixture["minimum_offline_seconds"],
                previous_checkpoint=snapshot["previous_checkpoint"],
            )
        with self.assertRaisesRegex(ProjectionContractError, "not newer"):
            verify_projection_database(
                path,
                contract,
                consumer_id=fixture["consumer_id"],
                minimum_offline_seconds=fixture["minimum_offline_seconds"],
                previous_checkpoint=41,
            )

        connection = sqlite3.connect(path)
        try:
            connection.execute("UPDATE medication_due SET source_checkpoint = 40")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ProjectionContractError, "checkpoint mismatch"):
            self._verify(fixture, snapshot, contract, path)

    def test_tombstones_cover_offline_horizon_and_block_stale_active_rows(self) -> None:
        fixture, snapshot, contract, path = self._materialize(
            "routinika-reminder-projection.v1.fixture.json", 1
        )
        with self.assertRaisesRegex(ProjectionContractError, "retention"):
            verify_projection_database(
                path,
                contract,
                consumer_id=fixture["consumer_id"],
                minimum_offline_seconds=90 * 24 * 60 * 60,
                previous_checkpoint=snapshot["previous_checkpoint"],
            )

        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "INSERT INTO routine_due VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "cccccccccccccccccccccccccccccccc",
                    "2026-08-22T09:00:00Z",
                    "2026-08-22T09:30:00Z",
                    "due",
                    2,
                    8,
                    "routinika-primary",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ProjectionContractError, "Tombstone conflicts"):
            self._verify(fixture, snapshot, contract, path)

    def test_unclosed_sidecar_is_rejected_before_sqlite_open(self) -> None:
        fixture, snapshot, contract, path = self._materialize(
            "mediplaner-reminder-projection.v1.fixture.json"
        )
        Path(f"{path}-wal").write_bytes(b"synthetic-sidecar")
        with self.assertRaisesRegex(ProjectionContractError, "not closed"):
            self._verify(fixture, snapshot, contract, path)


if __name__ == "__main__":
    unittest.main()
