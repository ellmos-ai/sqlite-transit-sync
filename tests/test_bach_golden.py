from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from compare_bach_golden import compare_fixtures  # noqa: E402


class BachGoldenTests(unittest.TestCase):
    def test_synthetic_comparison_stays_blocked_without_private_inputs(self) -> None:
        fixture = ROOT / "golden" / "bach_compatibility_fixtures.json"
        report = compare_fixtures(fixture)
        self.assertEqual("blocked_no_authorized_bach_golden", report["status"])
        self.assertEqual(7, report["fixture_count"])
        for scenario in report["scenarios"]:
            for field in (
                "input_contract",
                "expected_bach_semantics",
                "standalone_result",
                "intentional_deviation",
                "migration_risk",
            ):
                self.assertIn(field, scenario)
            rendered = json.dumps(scenario, ensure_ascii=False)
            self.assertNotIn("C:" + "\\Users\\" + "lukas", rendered)
            self.assertNotIn("/" + "home/" + "lukas", rendered)
            self.assertNotIn("OneDrive", rendered)
            self.assertNotIn("db_sync.py", rendered)

    def test_cli_writes_reproducible_report(self) -> None:
        output = ROOT / "golden" / ".test-bach-report.json"
        try:
            subprocess.run(
                [sys.executable, "scripts/compare_bach_golden.py", "--output", str(output)],
                cwd=ROOT,
                check=True,
            )
            generated = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("blocked_no_authorized_bach_golden", generated["status"])
            self.assertEqual(7, generated["fixture_count"])
        finally:
            output.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
