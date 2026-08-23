"""Safety-scan coverage tests -- prove the extended secret scan actually
catches planted fake secrets in every required location (src/, tests/, docs/,
root script) and that the exclusion rules hold.

All planting happens inside throwaway TEMP trees; nothing is ever written
into this repository, so there is no probe to clean up afterwards. Fake
secret literals are assembled from fragments at runtime so this test file
itself never contains a complete matchable secret (the scanner scans tests/,
including this file).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.safety_scan import ROOT_FILE_SUFFIXES, SCAN_ROOTS, run_scan


def _openai_key() -> str:
    # "sk-" + 16 word-chars, assembled so the literal never appears whole in
    # this file's source (which the scanner itself scans).
    return "sk-" + "A" * 16


def _private_key_block() -> str:
    return "-----BEGIN RSA " + "PRIVATE KEY-----"


def _password_line() -> str:
    # password = '<8 chars>' with the quoted value assembled at runtime.
    return "password = '" + "z" * 8 + "'"


def _sqlserver_line() -> str:
    # Assembled so no contiguous "Server=...;...Database=" run exists in THIS
    # file's own source (the scanner scans tests/, including this file -- a
    # straightforward single-string literal would make gate 3 flag this test
    # itself in CI, found via a clean-checkout simulation on 2026-08-21).
    return "Ser" + "ver=" + "db.example.host;" + "Data" + "base=master;"


class SafetyScanCoverageTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="ocr-safety-scan-test-")
        self.root = Path(self._temp.name)
        for name in SCAN_ROOTS:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._temp.cleanup()

    def _paths(self, result):
        return {finding["path"] for finding in result["findings"]}

    def test_planted_secrets_are_caught_in_src_tests_docs_and_root_script(self):
        (self.root / "src" / "a.py").write_text("X = 1\n" + _openai_key() + "\n", encoding="utf-8")
        (self.root / "tests" / "b.py").write_text(_private_key_block() + "\n", encoding="utf-8")
        (self.root / "docs" / "c.md").write_text("note\n" + _password_line() + "\n", encoding="utf-8")
        (self.root / "d.ps1").write_text("$s = 1 # " + _sqlserver_line() + "\n", encoding="utf-8")
        (self.root / "e.py").write_text("placeholder = 1\n", encoding="utf-8")
        result = run_scan(self.root)
        paths = self._paths(result)
        self.assertEqual(
            paths,
            {"src/a.py", "tests/b.py", "docs/c.md", "d.ps1"},
        )
        kinds = {(f["path"], f["kind"]) for f in result["findings"]}
        self.assertIn(("src/a.py", "openai_key"), kinds)
        self.assertIn(("tests/b.py", "private_key"), kinds)
        self.assertIn(("docs/c.md", "password_literal"), kinds)
        self.assertIn(("d.ps1", "sqlserver_connection_string"), kinds)
        self.assertEqual(result["secret_scan"], "fail")

    def test_excluded_locations_and_suffixes_are_not_scanned(self):
        # None of these may produce a finding: excluded directories (walk
        # fallback prunes them), non-source suffixes (binary/image/PDF), and
        # root-level .md (deliberately outside the root-file suffix set).
        for excluded in ("output", ".venv", "environments", ".playwright-cli", "node_modules"):
            directory = self.root / excluded
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "leak.py").write_text(_openai_key() + "\n", encoding="utf-8")
        (self.root / "docs" / "sub").mkdir()
        (self.root / "docs" / "sub" / "__pycache__").mkdir()
        (self.root / "docs" / "sub" / "__pycache__" / "leak.py").write_text(_openai_key() + "\n", encoding="utf-8")
        (self.root / "docs" / "image.png").write_text(_openai_key() + "\n", encoding="utf-8")
        (self.root / "docs" / "scan.pdf").write_text(_openai_key() + "\n", encoding="utf-8")
        (self.root / "README-ish.md").write_text(_openai_key() + "\n", encoding="utf-8")
        result = run_scan(self.root)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["secret_scan"], "pass")

    def test_root_suffix_set_has_no_md(self):
        # Locks the deliberate root-level policy: .md is scanned inside docs/
        # (tracked documentation) but not as a loose root file.
        self.assertNotIn(".md", ROOT_FILE_SUFFIXES)

    def test_git_tracked_mode_ignores_untracked_files_and_is_used_when_git_exists(self):
        if shutil.which("git") is None:
            raise unittest.SkipTest("git binary not available")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        tracked = self.root / "src" / "tracked.py"
        untracked = self.root / "src" / "untracked.py"
        tracked.write_text("ok = 1\n", encoding="utf-8")
        untracked.write_text(_openai_key() + "\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "src/tracked.py"], check=True, capture_output=True)
        result = run_scan(self.root)
        # Untracked local files (developer scratch, handoffs, generated
        # output) are invisible to the scan, exactly like a clean CI checkout.
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["secret_scan"], "pass")

    def test_real_repo_scans_clean_with_no_suppression_mechanism(self):
        # Codex remediation (a): the REAL repository must scan clean, and the
        # scanner must not even carry a suppression mechanism that could hide
        # a future finding.
        from scripts import safety_scan

        self.assertFalse(hasattr(safety_scan, "SUPPRESSIONS"))
        result = safety_scan.run_scan(safety_scan.ROOT)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["secret_scan"], "pass")
        self.assertNotIn("suppressed", result)

    def test_two_fake_passwords_in_one_file_are_both_reported(self):
        # Codex remediation (b): per-match reporting (finditer), not just the
        # first hit per file.
        tree = self.root / "src"
        (tree / "double.py").write_text(
            "a = 1\n" + _password_line() + "\nb = 2\n" + _password_line() + "\n",
            encoding="utf-8",
        )
        result = run_scan(self.root)
        password_findings = [f for f in result["findings"] if f["path"] == "src/double.py"]
        self.assertEqual(len(password_findings), 2)
        self.assertEqual({f["line"] for f in password_findings}, {2, 4})

    def test_planted_secret_at_the_master_cache_test_path_is_still_flagged(self):
        # Codex remediation (c): there is no path-based exemption anywhere in
        # the scanner -- a planted password at the exact path that previously
        # held a suppressed fixture must be caught like anywhere else.
        target = self.root / "tests" / "test_master_cache.py"
        target.write_text("x = 1\n" + _password_line() + "\n", encoding="utf-8")
        result = run_scan(self.root)
        self.assertIn(
            {"kind": "password_literal", "path": "tests/test_master_cache.py", "line": 2},
            result["findings"],
        )


    def test_this_test_files_own_fragments_never_match_the_secret_patterns(self):
        # The scanner scans tests/ -- including this file. Its planted-secret
        # fragments are deliberately split so that no SECRET_PATTERN matches
        # this file's own source text; this guards that invariant directly,
        # committed-file or not.
        from scripts.safety_scan import SECRET_PATTERNS

        own_source = Path(__file__).read_text(encoding="utf-8")
        for name, pattern in SECRET_PATTERNS.items():
            self.assertIsNone(pattern.search(own_source), f"fragment for {name} assembled too eagerly in this file's source")


if __name__ == "__main__":
    unittest.main()
