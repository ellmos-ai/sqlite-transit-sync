import json
import re
import subprocess
import unittest
from pathlib import Path
import sqlite_transit_sync


ROOT = Path(__file__).parent.parent
VERSION = "0.2.0"
VERIFY_DATE = "2026-08-10"


class TestMetadata(unittest.TestCase):
    def test_version_consistency(self):
        """Verify that sqlite_transit_sync.__version__ is 0.2.0."""
        self.assertEqual(sqlite_transit_sync.__version__, "0.2.0")

    def test_llms_txt_version_parity(self):
        """Verify llms.txt reflects version 0.2.0 and has recent Last-checked date."""
        llms_file = ROOT / "llms.txt"
        self.assertTrue(llms_file.exists(), "llms.txt should exist in repository root")

        content = llms_file.read_text(encoding="utf-8")
        self.assertIn("- Version: 0.2.0", content, "llms.txt must declare Version: 0.2.0")

    def test_exports_present(self):
        """Verify all declared exports in __all__ are importable and non-None."""
        for item in sqlite_transit_sync.__all__:
            obj = getattr(sqlite_transit_sync, item, None)
            self.assertIsNotNone(obj, f"Exported symbol {item} should be present in module")

    def test_authoritative_version_contract_covers_all_surfaces(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project_version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
        self.assertIsNotNone(project_version)
        self.assertEqual(VERSION, project_version.group(1))

        legacy_manifest = json.loads((ROOT / "ellmos-module.json").read_text(encoding="utf-8"))
        v2_manifest = json.loads((ROOT / "ellmos-module.v2.json").read_text(encoding="utf-8"))
        self.assertEqual(VERSION, sqlite_transit_sync.__version__)
        self.assertEqual(VERSION, legacy_manifest["version"])
        self.assertEqual(VERSION, v2_manifest["version"])

        for filename in ("README.md", "README_de.md"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("tests-34%2F34%20passed", text)
            self.assertIn("METADATA_CONTRACT.md", text)
        llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
        self.assertIn(f"- Version: {VERSION}", llms)
        self.assertIn(f"- Last-checked: {VERIFY_DATE}", llms)

    def test_status_and_verification_contract_is_explicit_and_current(self):
        legacy = json.loads((ROOT / "ellmos-module.json").read_text(encoding="utf-8"))
        v2 = json.loads((ROOT / "ellmos-module.v2.json").read_text(encoding="utf-8"))
        self.assertEqual("development", legacy["status"])
        self.assertEqual("development", v2["status"])
        self.assertEqual("public-candidate", v2["visibility"])
        self.assertEqual(VERIFY_DATE, legacy["last_verified"])
        self.assertEqual(VERIFY_DATE, v2["last_verified"])

        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertRegex(claude, rf"(?m)^version:\s*{re.escape(VERSION)}\s*$")
        self.assertRegex(claude, rf"(?m)^last_verified:\s*[\"']?{VERIFY_DATE}[\"']?\s*$")
        self.assertRegex(claude, r'(?m)^release_status:\s*["\']development["\']\s*$')
        self.assertRegex(claude, r'(?m)^visibility:\s*["\']public-candidate["\']\s*$')

        contract = (ROOT / "METADATA_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("pyproject.toml", contract)
        self.assertIn("schema_version", contract)
        self.assertIn("public-candidate", contract)
        gate = (ROOT / "RELEASE_GATE.md").read_text(encoding="utf-8")
        self.assertIn("STATUS: LOCKED", gate)
        self.assertIn("UNLOCKED", gate)

    def test_tracked_public_view_has_no_local_artifact_or_path_leak(self):
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True, encoding="utf-8"
        ).splitlines()
        self.assertFalse([path for path in tracked if path.endswith((".db", ".sqlite", ".env"))])
        forbidden = (
            "C:" + "\\Users\\" + "lukas",
            "C:/Users/" + "lukas",
            "/home/" + "lukas",
            "/c/Users/" + "lukas",
        )
        findings = []
        for relative in tracked:
            path = ROOT / relative
            if path.suffix.lower() in {".png", ".jpg", ".gif", ".zip", ".db"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(marker.lower() in text.lower() for marker in forbidden):
                findings.append(relative)
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
