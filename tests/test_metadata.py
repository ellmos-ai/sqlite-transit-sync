import json
import re
import subprocess
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility
    import tomli as tomllib

import sqlite_transit_sync

ROOT = Path(__file__).parent.parent


class TestMetadata(unittest.TestCase):
    """Metadata parity.

    These assertions compare the version *sources* against each other instead of
    against a literal. A hard-coded number turns every release into a test edit and
    silently passes when only one of the three places was bumped — which is the one
    failure this test exists to catch.
    """

    def _pyproject_version(self) -> str:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return data["project"]["version"]

    def test_version_consistency(self):
        """Package version matches the packaging metadata."""
        self.assertEqual(sqlite_transit_sync.__version__, self._pyproject_version())

    def test_llms_txt_version_parity(self):
        """llms.txt declares the same version the package reports."""
        llms_file = ROOT / "llms.txt"
        self.assertTrue(llms_file.exists(), "llms.txt should exist in repository root")

        content = llms_file.read_text(encoding="utf-8")
        declared = re.search(r"^- Version:\s*(\S+)", content, re.MULTILINE)
        self.assertIsNotNone(declared, "llms.txt must declare a '- Version:' line")
        self.assertEqual(sqlite_transit_sync.__version__, declared.group(1))

    def test_exports_present(self):
        """Verify all declared exports in __all__ are importable and non-None."""
        for item in sqlite_transit_sync.__all__:
            obj = getattr(sqlite_transit_sync, item, None)
            self.assertIsNotNone(obj, f"Exported symbol {item} should be present in module")

    def test_bilingual_readmes_exist(self):
        """Verify that English and German documentation files exist."""
        readme_en = ROOT / "README.md"
        readme_de = ROOT / "README_de.md"
        self.assertTrue(readme_en.is_file(), "README.md must exist")
        self.assertTrue(readme_de.is_file(), "README_de.md must exist")

    def test_ellmos_module_manifests(self):
        """Verify ellmos-module JSON manifests match package metadata."""
        m1_file = ROOT / "ellmos-module.json"
        if m1_file.exists():
            data1 = json.loads(m1_file.read_text(encoding="utf-8"))
            self.assertEqual(data1.get("version"), self._pyproject_version())

        m2_file = ROOT / "ellmos-module.v2.json"
        if m2_file.exists():
            data2 = json.loads(m2_file.read_text(encoding="utf-8"))
            self.assertEqual(data2.get("version"), self._pyproject_version())
            repo = data2.get("source_of_truth", {}).get("repository")
            self.assertEqual(repo, "https://github.com/ellmos-ai/sqlite-transit-sync")

    def test_llms_txt_date_parity(self):
        """llms.txt declares a valid Last-checked date."""
        llms_file = ROOT / "llms.txt"
        content = llms_file.read_text(encoding="utf-8")
        declared = re.search(r"^- Last-checked:\s*(\d{4}-\d{2}-\d{2})", content, re.MULTILINE)
        self.assertIsNotNone(declared, "llms.txt must declare a '- Last-checked: YYYY-MM-DD' line")

    def test_bilingual_security_exists_and_contacts(self):
        """SECURITY.md must be bilingual and declare direct contact channels."""
        sec_file = ROOT / "SECURITY.md"
        self.assertTrue(sec_file.is_file(), "SECURITY.md must exist")
        content = sec_file.read_text(encoding="utf-8")
        self.assertIn("# Security", content)
        self.assertIn("Sicherheitsrichtlinie (Deutsch)", content)
        self.assertIn("security@ellmos.ai", content)
        self.assertIn("support@lukasgeiger.com", content)

    def test_projection_contract_docs_and_package_data_are_bilingual(self):
        """Projection docs, contract names, and package data must stay synchronized."""
        docs = [ROOT / "PROJECTION_CONTRACTS.md", ROOT / "PROJECTION_CONTRACTS_de.md"]
        readmes = [ROOT / "README.md", ROOT / "README_de.md"]
        for path in docs:
            self.assertTrue(path.is_file(), f"Missing projection documentation: {path.name}")
        for token in (
            "mediplaner-reminder-projection.v1",
            "routinika-reminder-projection.v1",
            "verify-projection",
        ):
            for path in (*docs, *readmes):
                self.assertIn(token, path.read_text(encoding="utf-8"), f"{token} missing in {path.name}")
        package_data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "tool"
        ]["setuptools"]["package-data"]["sqlite_transit_sync"]
        self.assertIn("projection-contracts/*.json", package_data)

    def test_ci_workflow_integrity(self):
        """CI workflow must exist and test Python 3.10 through 3.13 across OS platforms."""
        ci_file = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci_file.is_file(), ".github/workflows/ci.yml must exist")
        content = ci_file.read_text(encoding="utf-8")
        for py in ["3.10", "3.11", "3.12", "3.13"]:
            self.assertIn(py, content, f"CI matrix should test Python {py}")
        self.assertIn("ubuntu-latest", content)
        self.assertIn("windows-latest", content)

    def test_pyproject_pep621_classifiers(self):
        """pyproject.toml must contain standard PEP 621 classifiers."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        classifiers = data.get("project", {}).get("classifiers", [])
        self.assertTrue(len(classifiers) >= 6, "pyproject.toml should have classifiers")
        required_classifiers = [
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
            "Programming Language :: Python :: 3.13",
            "Operating System :: OS Independent",
            "License :: OSI Approved :: MIT License",
        ]
        for rc in required_classifiers:
            self.assertIn(rc, classifiers, f"Classifier '{rc}' must be present in pyproject.toml")

    def test_badges_parity(self):
        """README.md and README_de.md must have synchronized essential badges."""
        readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_de = (ROOT / "README_de.md").read_text(encoding="utf-8")
        for badge_fragment in [
            "license/ellmos-ai/sqlite-transit-sync",
            "python-3.10",
            "platform-Windows",
            "actions/workflows/ci.yml/badge.svg",
            "privacy-100%25%20Offline",
            "security-Local--First",
            "Ecosystem-ellmos--ai",
            "Umbrella-open--bricks",
            "version-0.4.0",
            "llms.txt-available",
        ]:
            self.assertIn(badge_fragment, readme_en, f"Badge fragment '{badge_fragment}' missing in README.md")
            self.assertIn(badge_fragment, readme_de, f"Badge fragment '{badge_fragment}' missing in README_de.md")

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
