"""Per-PR notes fold into CHANGELOG.md and docs/DECISIONS.md, and the repo's notes are well formed."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("collect_changes", ROOT / "scripts" / "collect_changes.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

LOG = "# Changelog\n\n## Unreleased\n- old entry\n\n## 0.4.0 — 2026-10-24 (x)\n- released\n"
DECISIONS = ("# Decision log / 决策记录\n\nNewest first.\n\n"
             "| Date | Decision (EN) | 决定（中文） | Why / 原因 | Where / 位置 |\n"
             "|---|---|---|---|---|\n"
             "| 2026-10-24 | Existing decision | 既有决定 | Existing reason | `old.py` |\n")


def row(date, decision):
    return f"| {date} | {decision} | 决定 | Reason / 原因 | `code.py` |\n"


class TestCollectChanges(unittest.TestCase):
    def repo(self, d, notes, eol="\n"):
        root = Path(d)
        (root / "changes").mkdir()
        (root / "changes" / "README.md").write_text("not a note\n", encoding="utf-8")
        for name, text in notes.items():
            (root / "changes" / name).write_text(text, encoding="utf-8")
        (root / "CHANGELOG.md").write_bytes(LOG.replace("\n", eol).encode("utf-8"))
        return root

    def test_repo_notes_are_well_formed(self):
        self.assertEqual(cc.main(["--root", str(ROOT), "--check"]), 0)

    def test_unreleased_in_pr_order(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"22.md": "- twenty-two\n", "9.md": "- nine\n  more\n", "a-branch.md": "- branch\n"})
            self.assertEqual(cc.main(["--root", str(root), "--apply"]), 0)
            text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("## Unreleased\n- old entry\n- nine\n  more\n- twenty-two\n- branch\n\n## 0.4.0", text)
            self.assertEqual([p.name for p in (root / "changes").iterdir()], ["README.md"])

    def test_release_heading_and_line_endings(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "- new\n"}, eol="\r\n")
            cc.main(["--root", str(root), "--version", "0.5.0", "--title", "t", "--date", "2026-11-01", "--apply"])
            raw = (root / "CHANGELOG.md").read_bytes().decode("utf-8")
            self.assertNotIn("\n", raw.replace("\r\n", ""))
            self.assertIn("## Unreleased\r\n\r\n## 0.5.0 — 2026-11-01 (t)\r\n- old entry\r\n- new\r\n\r\n## 0.4.0",
                          raw)

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "- new\n"})
            cc.main(["--root", str(root)])
            self.assertEqual((root / "CHANGELOG.md").read_text(encoding="utf-8"), LOG)
            self.assertTrue((root / "changes" / "21.md").exists())

    def test_bad_note_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "no bullet\n"})
            self.assertEqual(cc.main(["--root", str(root), "--apply"]), 1)
            self.assertEqual((root / "CHANGELOG.md").read_text(encoding="utf-8"), LOG)


class TestCollectDecisions(unittest.TestCase):
    def repo(self, d, notes):
        root = Path(d) / "repo"
        root.mkdir()
        TestCollectChanges().repo(root, notes)
        (root / "docs").mkdir()
        (root / "docs" / "DECISIONS.md").write_text(DECISIONS, encoding="utf-8", newline="")
        return root

    def run_cli(self, root, *args):
        # Exercise the real entry point from outside both the source checkout and the fixture repo.
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "collect_changes.py"),
                               "--root", str(root), *args], cwd=root.parent, capture_output=True,
                              text=True, encoding="utf-8", timeout=30)

    def snapshot(self, root):
        return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def test_valid_decision_rows_and_changelog_notes_are_checked_separately(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "- change\n", "21.decision.md":
                                row("2026-11-01", r"One \| two") + row("2026-11-02", "Next<br>line")})
            self.assertEqual([p.name for p in cc.notes(root / "changes")], ["21.md"])
            self.assertEqual(cc.check_decision(root / "changes" / "21.decision.md"), [])
            before = self.snapshot(root)
            result = self.run_cli(root, "--check")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1 note(s) ok", result.stdout)
            self.assertIn("1 decision note(s) ok", result.stdout)
            self.assertEqual(self.snapshot(root), before)

    def test_bad_decision_rows_report_file_and_physical_line(self):
        good = row("2026-11-01", "Decision")
        cases = [
            ("", 1), (" \n", 1), ("\n" + good, 1),
            (good.lstrip("|"), 1), (good.rstrip("\n").rstrip("|") + "\n", 1),
            ("| 2026-11-01 | decision | why | where |\n", 1),
            ("| 2026-11-01 | decision | 中文 | why | where | extra |\n", 1),
            (row("2026-1-01", "Decision"), 1), (row("2026-02-30", "Decision"), 1),
            (row("Date", "Decision (EN)"), 1), ("|---|---|---|---|---|\n", 1),
            (good + row("2026-11-02", "Bare\nnewline"), 2),
            (good + "  continued cell\n", 2),
        ]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "7.decision.md"
            for text, lineno in cases:
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8", newline="")
                    problems = cc.check_decision(path)
                    self.assertTrue(problems)
                    self.assertIn(f"7.decision.md:{lineno}:", "\n".join(problems))

    def test_cli_reports_errors_in_both_note_types(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "no bullet\n", "21.decision.md":
                                row("2026-11-01", "Good") + row("bad date", "Bad")})
            before = self.snapshot(root)
            result = self.run_cli(root, "--check")
            self.assertEqual(result.returncode, 1)
            self.assertIn("21.md:1:", result.stderr)
            self.assertIn("21.decision.md:2:", result.stderr)
            self.assertEqual(self.snapshot(root), before)

    def test_apply_prepends_decisions_by_date_then_descending_pr(self):
        newest = row("2026-11-04", "Newest, PR 9")
        hundred = row("2026-11-03", "PR 100 first") + row("2026-11-03", "PR 100 second")
        twenty_two = row("2026-11-03", "PR 22")
        nine = row("2026-11-03", "PR 9")
        branch_a = row("2026-11-03", "Branch a")
        branch_z = row("2026-11-03", "Branch z")
        oldest = row("2026-11-02", "Older, PR 100")
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"22.md": "- change\n", "9.decision.md": nine + newest,
                                "22.decision.md": twenty_two, "100.decision.md": oldest + hundred,
                                "z-branch.decision.md": branch_z, "a-branch.decision.md": branch_a})
            result = self.run_cli(root, "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            separator = "|---|---|---|---|---|\n"
            expected = DECISIONS.replace(separator, separator + newest + hundred + twenty_two + nine
                                         + branch_a + branch_z + oldest)
            self.assertEqual((root / "docs" / "DECISIONS.md").read_bytes(), expected.encode("utf-8"))
            changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("- old entry\n- change\n", changelog)
            self.assertNotIn("|", changelog)
            self.assertEqual([p.name for p in (root / "changes").iterdir()], ["README.md"])

    def test_decision_preview_and_version_preview_change_nothing(self):
        decision = row("2026-11-01", "Preview decision")
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "- change\n", "21.decision.md": decision})
            before = self.snapshot(root)
            for args in [(), ("--version", "0.5.0", "--title", "Preview", "--date", "2026-11-03")]:
                with self.subTest(args=args):
                    result = self.run_cli(root, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("|---|---|---|---|---|\n" + decision, result.stdout)
                    self.assertIn("| 2026-10-24 | Existing decision", result.stdout)
                    changelog = result.stdout.split("# Decision log", 1)[0]
                    self.assertIn("- old entry\n- change\n", changelog)
                    self.assertNotIn("Preview decision", changelog)
                    if args:
                        self.assertIn("## 0.5.0 — 2026-11-03 (Preview)", changelog)
                    self.assertEqual(self.snapshot(root), before)

    def test_version_apply_folds_both_documents(self):
        decision = row("2026-11-01", "Release decision")
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "- release change\n", "21.decision.md": decision})
            result = self.run_cli(root, "--version", "0.5.0", "--title", "Release", "--date", "2026-11-03", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("## Unreleased\n\n## 0.5.0 — 2026-11-03 (Release)\n- old entry\n- release change\n", changelog)
            self.assertIn("|---|---|---|---|---|\n" + decision,
                          (root / "docs" / "DECISIONS.md").read_text(encoding="utf-8"))
            self.assertEqual([p.name for p in (root / "changes").iterdir()], ["README.md"])

    def test_invalid_decision_prevents_all_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "- change\n", "21.decision.md": row("bad date", "Bad")})
            before = self.snapshot(root)
            result = self.run_cli(root, "--apply")
            self.assertEqual(result.returncode, 1)
            self.assertIn("21.decision.md:1:", result.stderr)
            self.assertEqual(self.snapshot(root), before)

    def test_missing_decision_table_prevents_all_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.repo(d, {"21.md": "- change\n", "21.decision.md": row("2026-11-01", "Decision")})
            (root / "docs" / "DECISIONS.md").write_text("# No table\n", encoding="utf-8", newline="")
            before = self.snapshot(root)
            result = self.run_cli(root, "--apply")
            self.assertEqual(result.returncode, 1)
            self.assertIn("docs/DECISIONS.md has no five-column table separator", result.stderr)
            self.assertEqual(self.snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
