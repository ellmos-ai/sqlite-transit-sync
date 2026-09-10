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
        """SECURITY.md must be bilingual and declare supported versions, 48h SLA, and contacts."""
        sec_file = ROOT / "SECURITY.md"
        self.assertTrue(sec_file.is_file(), "SECURITY.md must exist")
        content = sec_file.read_text(encoding="utf-8")
        self.assertIn("# Security", content)
        self.assertIn("## Supported Versions", content)
        self.assertIn("Sicherheitsrichtlinie (Deutsch)", content)
        self.assertIn("## Unterstützte Versionen", content)
        self.assertIn("0.4.x", content)
        self.assertIn("48 hours", content)
        self.assertIn("48 Stunden", content)
        self.assertIn("security@ellmos.ai", content)
        self.assertIn("support@lukasgeiger.com", content)
        self.assertIn("security@open-bricks.org", content)

    def test_projection_contract_docs_and_package_data_are_bilingual(self):
        """Projection docs, contract names, and package data must stay synchronized."""
        docs = [ROOT / "PROJECTION_CONTRACTS.md", ROOT / "PROJECTION_CONTRACTS_de.md"]
        readmes = [ROOT / "README.md", ROOT / "README_de.md"]
        for path in docs:
            self.assertTrue(path.is_file(), f"Missing projection documentation: {path.name}")
        for token in (
            "accounts-balance-projection.v1",
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
        """CI workflow must test Python 3.10-3.13 across triple OS matrix with concurrency."""
        ci_file = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci_file.is_file(), ".github/workflows/ci.yml must exist")
        content = ci_file.read_text(encoding="utf-8")
        for py in ["3.10", "3.11", "3.12", "3.13"]:
            self.assertIn(py, content, f"CI matrix should test Python {py}")
        self.assertIn("ubuntu-latest", content)
        self.assertIn("windows-latest", content)
        self.assertIn("macos-latest", content)
        self.assertIn("actions/checkout@v4", content)
        self.assertIn("actions/setup-python@v5", content)
        self.assertIn("cancel-in-progress: true", content)

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
        ]
        for rc in required_classifiers:
            self.assertIn(rc, classifiers, f"Classifier '{rc}' must be present in pyproject.toml")
        self.assertEqual(data["project"].get("license"), "MIT")
        self.assertFalse(
            any(item.startswith("License ::") for item in classifiers),
            "PEP 639 license expressions must not be duplicated by deprecated classifiers",
        )

    def test_pyproject_ecosystem_urls(self):
        """pyproject.toml must contain full ecosystem URLs."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        urls = data.get("project", {}).get("urls", {})
        self.assertIn("Homepage", urls)
        self.assertIn("Repository", urls)
        self.assertIn("Issues", urls)
        self.assertIn("Documentation", urls)
        self.assertIn("Changelog", urls)
        self.assertIn("Security", urls)
        self.assertEqual(urls.get("Parent Organization"), "https://github.com/ellmos-ai")
        self.assertEqual(urls.get("Umbrella Ecosystem"), "https://github.com/open-bricks")

    def test_gitignore_hygiene(self):
        """gitignore must ignore caches, conflict patterns and locks."""
        gi_file = ROOT / ".gitignore"
        self.assertTrue(gi_file.is_file(), ".gitignore must exist")
        content = gi_file.read_text(encoding="utf-8")
        for pattern in [".pytest_cache/", ".ruff_cache/", "*.sync-conflict-*", "*.conflict", "LOCK*.txt"]:
            self.assertIn(pattern, content, f"Pattern '{pattern}' should be in .gitignore")

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

    def test_quick_navigation_anchors(self):
        """Both README.md and README_de.md must have 14 matching navigation links."""
        for fname, nav_header in [
            ("README.md", "## 🧭 Quick Navigation"),
            ("README_de.md", "## 🧭 Schnellnavigation"),
        ]:
            content = (ROOT / fname).read_text(encoding="utf-8")
            self.assertIn(nav_header, content, f"Navigation header missing in {fname}")
            nav_match = re.search(
                rf"{re.escape(nav_header)}\s*\n\n((?:- \[.+\]\(#.+\)\s*\n)+)", content
            )
            self.assertIsNotNone(nav_match, f"Navigation block malformed in {fname}")
            links = re.findall(r"- \[(.+)\]\(#([^\)]+)\)", nav_match.group(1))
            self.assertEqual(
                14,
                len(links),
                f"Expected exactly 14 navigation links in {fname}, got {len(links)}",
            )
            headings = re.findall(r"^(#{1,3})\s+(.+)$", content, re.MULTILINE)
            slugs = []
            for _, h in headings:
                s = h.lower().strip()
                s = re.sub(r"[^\w\s-]", "", s)
                s = re.sub(r"\s+", "-", s)
                slugs.append(s)
            for title, anchor in links:
                self.assertIn(
                    anchor,
                    slugs,
                    f"Navigation link '{title}' -> #{anchor} has no matching heading slug in {fname}",
                )

    def test_dual_mermaid_diagrams(self):
        """Both READMEs must provide flowchart TD architecture and lifecycle sequence diagrams."""
        for fname in ["README.md", "README_de.md"]:
            content = (ROOT / fname).read_text(encoding="utf-8")
            mermaid_blocks = re.findall(r"```mermaid\s*\n(.*?)\n```", content, re.DOTALL)
            self.assertGreaterEqual(
                len(mermaid_blocks),
                2,
                f"Expected at least 2 Mermaid diagrams in {fname}, got {len(mermaid_blocks)}",
            )
            self.assertTrue(
                any("flowchart TD" in block for block in mermaid_blocks),
                f"Missing flowchart TD diagram in {fname}",
            )
            self.assertTrue(
                any("sequenceDiagram" in block for block in mermaid_blocks),
                f"Missing sequenceDiagram in {fname}",
            )

    def test_runtime_invariants_matrix(self):
        """Both READMEs must provide a 10-row Governance & Runtime Invariants Matrix."""
        for fname, heading in [
            ("README.md", "## Governance & Runtime Invariants Matrix"),
            ("README_de.md", "## Governance- & Laufzeit-Invarianten-Matrix"),
        ]:
            content = (ROOT / fname).read_text(encoding="utf-8")
            self.assertIn(heading, content, f"Missing Invariants heading in {fname}")
            for idx in range(1, 11):
                self.assertRegex(
                    content,
                    rf"\|\s*{idx}\s*\|",
                    f"Invariant #{idx} missing from matrix in {fname}",
                )

    def test_security_sla_and_triage(self):
        """SECURITY.md must guarantee 48-hour response SLA and 5-business-day triage commitment."""
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("48 hours", security)
        self.assertIn("5 business days", security)
        self.assertIn("48 Stunden", security)
        self.assertIn("5 Werktagen", security)

    def test_local_marketing_log_present(self):
        """Repository root must contain MARKETING-LOG.txt documenting baseline and upgrades."""
        mkt = ROOT / "MARKETING-LOG.txt"
        self.assertTrue(mkt.exists(), "MARKETING-LOG.txt must exist in repo root")
        text = mkt.read_text(encoding="utf-8")
        self.assertIn("ellmos-ai/sqlite-transit-sync", text)
        self.assertIn("PFAD B", text.upper())
        self.assertIn("DISCOVERABILITY", text.upper())

    def test_ecosystem_sibling_tools(self):
        """Both READMEs must include cross-links to at least 15 sibling ecosystem tools."""
        for fname in ["README.md", "README_de.md"]:
            content = (ROOT / fname).read_text(encoding="utf-8")
            self.assertIn("dev-bricks/sync-master", content)
            self.assertIn("ellmos-ai/stacks", content)
            github_links = re.findall(r"https://github\.com/([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)", content)
            unique_repos = {repo.lower() for repo in github_links}
            self.assertGreaterEqual(
                len(unique_repos),
                15,
                f"Expected >= 15 sibling repos linked in {fname}, found {len(unique_repos)}",
            )


if __name__ == "__main__":
    unittest.main()
