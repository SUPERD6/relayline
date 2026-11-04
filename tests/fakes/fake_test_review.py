"""Task-derived test-review responses. Writes tests; never fakes their execution."""
import json
import os
from pathlib import Path


def answer(prompt):
    if "[ccx test review]" not in prompt:
        return None
    scenario = os.environ.get("FAKE_TEST_REVIEW", "pass")
    out = {"status": "done", "summary": "independent test file prepared", "files_changed": [],
           "commands_run": [], "verification": "not-run", "open_questions": [], "next_step": ""}
    if "Actual test execution" in prompt:
        if os.environ.get("FAKE_TEST_CONFIRM_INVALID"):
            out["open_questions"] = ["null", "[]", "false", "invalid JSON"]
            return out
        if scenario not in ("wrong-test", "out-of-scope", "unconfirmed"):
            out["open_questions"] = [json.dumps({"file": "test_independent.py", "task_quote": os.environ.get("FAKE_CONFIRM_QUOTE", "x to 2"),
                                                  "test_correct": True})]
        return out
    checks = Path.cwd() / "checks"
    checks.mkdir(exist_ok=True)
    # Assert that neither the builder's tests nor hidden material survived the copy.
    files = [f.name for f in Path.cwd().rglob("*") if f.is_file()]
    if "test_builder.py" in files or "hidden-pytest.txt" in files or "secret_test.py" in files:
        raise RuntimeError("test contamination")
    if scenario == "no-tests":
        return out
    assertion = "self.assertEqual(a.x, 3)" if scenario == "wrong-test" else "self.assertEqual(a.x, 2)"
    if scenario == "error":
        assertion = "import missing_review_test_dependency"
    if scenario == "crash":
        assertion = "self.assertEqual(a.value(), 2)"
    if scenario == "skip":
        assertion = "self.skipTest('unavailable')"
    (checks / "test_independent.py").write_text("import unittest\nimport a\nclass Independent(unittest.TestCase):\n"
                                                 f"    def test_value(self):\n        {assertion}\n",
                                                 encoding="utf-8", newline="")
    quote = "x to 3" if scenario == "out-of-scope" else "x to 2"
    quote = os.environ.get("FAKE_TEST_QUOTE", quote)
    cases = [{"file": "test_independent.py", "task_quote": quote}]
    if scenario in ("duplicate", "invalid-duplicate"):
        cases.append({"file": "test_independent.py", "task_quote":
                      "x to 3" if scenario == "invalid-duplicate" else "x to 2 in a.py"})
    manifest = checks / "manifest.json" if scenario == "local-manifest" else Path("manifest.json")
    manifest.write_text(json.dumps({"cases": cases}), encoding="utf-8", newline="")
    if scenario == "malformed-root":
        (checks / "manifest.json").write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
        manifest.write_text("invalid JSON", encoding="utf-8")
    return out
