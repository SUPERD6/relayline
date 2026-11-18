"""#427 [review] skip_when_clean (experimental, default off): a run that is mechanically "clean" starts no independent
review. Clean = the review would have been an automatic one (not --review on, not a fix round, not risk critical),
ccx's --check passed and its sensitivity shows it failed before the change, the change is within
skip_max_files / skip_max_lines, no pre-existing test was edited, the check basis is not self-authored, the sub-agent
raised no open questions and did not commit. Any condition unmet: reviewed as before. Off: nothing changes."""
import json
import sys

import pytest

from ccx import leadview, review
from ccx.config import SETTINGS, Paths, load_config, set_setting
from test_adapters import AdapterEnv
from test_check_baseline import git, repository

DIFF = "--- a/state.txt\n+++ b/state.txt\n@@ -1 +1 @@\n-old\n+fixed\n"
CLEAN = dict(mode="auto", risk=None, result={}, check={"passed": True, "sensitivity": "sensitive"},
             actual=["state.txt"], diff=DIFF, edited=[], self_checked=False, committed=False, claimed=["state.txt"],
             unread=[])
# a failing test file renamed out of collection: git shows the new name only, 0 changed lines
RENAMED = ("diff --git a/test_acceptance.py b/acceptance_off.py\nsimilarity index 100%\n"
           "rename from test_acceptance.py\nrename to acceptance_off.py\n")
DELETED = ("diff --git a/tests/test_old.py b/tests/test_old.py\ndeleted file mode 100644\nindex 1..0\n"
           "--- a/tests/test_old.py\n+++ /dev/null\n")
SKIP_MARK = ("diff --git a/test_acceptance.py b/test_acceptance.py\n--- a/test_acceptance.py\n"
             "+++ b/test_acceptance.py\n@@ -2,0 +3 @@\n+" + "@pytest.mark.skip\n")   # split: not an e-mail


def unmet(rc=None, **kw):
    return review.clean_skip({"skip_when_clean": True, **(rc or {})}, **{**CLEAN, **kw})[0]


def test_default_off_and_registered(tmp_path):
    cfg = load_config(Paths(tmp_path))
    rc = cfg["review"]
    assert rc["skip_when_clean"] is False and rc["skip_max_files"] == 3 and rc["skip_max_lines"] == 49
    assert rc["skip_max_lines"] < rc["min_lines"]        # a review due for its size is not skipped by default
    assert review.SKIP_MAX_LINES == rc["skip_max_lines"] and review.SKIP_MAX_FILES == rc["skip_max_files"]
    assert not review.skip_when_clean(rc) and not review.skip_when_clean({})
    for key in ("review.skip_when_clean", "review.skip_max_files", "review.skip_max_lines"):
        assert key in SETTINGS
    assert "experimental" in SETTINGS["review.skip_when_clean"][1]


def test_config_roundtrip_and_validation(tmp_path):
    p = Paths(tmp_path)
    set_setting(p, "review.skip_when_clean", "true")
    set_setting(p, "review.skip_max_files", "1")
    set_setting(p, "review.skip_max_lines", "0")
    rc = load_config(p)["review"]
    assert rc["skip_when_clean"] is True and rc["skip_max_files"] == 1 and rc["skip_max_lines"] == 0
    for key in ("review.skip_max_files", "review.skip_max_lines"):
        with pytest.raises(ValueError):
            set_setting(p, key, "-1")
    with pytest.raises(ValueError):
        set_setting(p, "review.skip_when_clean", "maybe")


def test_clean_run_meets_every_condition():
    miss, text = review.clean_skip({"skip_when_clean": True}, **CLEAN)
    assert miss == []
    assert "sensitive" in text and "1 file" in text and "2 lines" in text and len(text) <= 120


@pytest.mark.parametrize("kw,word", [
    ({"mode": "on"}, "review asked"),
    ({"risk": "critical"}, "risk critical"),
    ({"check": None}, "no check"),
    ({"check": {"passed": False, "sensitivity": "sensitive"}}, "check not passed"),
    ({"check": {"passed": True, "sensitivity": "sensitive", "weak": True}}, "check weak"),
    ({"check": {"passed": True, "sensitivity": "sensitive", "broken": "no tests"}}, "check weak"),
    ({"check": {"passed": True}}, "sensitivity"),
    ({"check": {"passed": True, "sensitivity": "unknown"}}, "sensitivity"),
    ({"check": {"passed": True, "sensitivity": "insensitive"}}, "sensitivity"),
    ({"actual": ["a.py", "b.py", "c.py", "d.py"]}, "4 files"),
    ({"actual": []}, "no changes"),
    ({"edited": ["tests/test_a.py"]}, "edited tests"),
    ({"self_checked": True}, "self-authored"),
    ({"committed": True}, "committed"),
    ({"result": {"open_questions": ["is this right?"]}}, "open questions"),
    # review #434 item 1: ways around edited_tests, which sees only `-` lines of test files
    ({"diff": DIFF + RENAMED, "actual": ["state.txt", "acceptance_off.py"]}, "renamed or deleted tests"),
    ({"diff": DIFF + DELETED, "actual": ["state.txt", "tests/test_old.py"]}, "renamed or deleted tests"),
    ({"diff": DIFF + SKIP_MARK, "actual": ["state.txt", "test_acceptance.py"]}, "lines added to existing tests"),
    ({"actual": ["state.txt", "pytest.ini"]}, "test configuration"),
    ({"actual": ["state.txt", "pyproject.toml"]}, "test configuration"),
    ({"actual": ["state.txt", "setup.cfg"]}, "test configuration"),
    ({"actual": ["state.txt", "tox.ini"]}, "test configuration"),
    ({"actual": ["state.txt", "sub/conftest.py"]}, "test configuration"),
    # item 4: what reason() reviews for when nothing earlier fired
    ({"claimed": ["other.py"]}, "claimed files don't match"),
    ({"claimed": []}, "no files reported"),
    # binary or long new files: their lines are not fully counted
    ({"unread": ["blob.bin"]}, "not fully counted"),
])
def test_any_unmet_condition_keeps_the_review(kw, word):
    miss = unmet(**kw)
    assert miss and any(word in m for m in miss), miss


def test_thresholds_are_configurable():
    big = "--- a/a.py\n+++ b/a.py\n@@ -1 +1,60 @@\n" + "".join(f"+x{i}\n" for i in range(60))
    assert any("lines" in m for m in unmet(diff=big))                    # 60 > 49 by default
    assert unmet({"skip_max_lines": 100}, diff=big) == []
    assert any("files" in m for m in unmet({"skip_max_files": 0}))
    assert unmet({"skip_max_files": "x", "skip_max_lines": None}) == []   # a bad value falls back to the default


def test_moved_tests_and_unreadable(tmp_path):
    assert review.moved_tests(RENAMED) == ["test_acceptance.py"]
    assert review.moved_tests(DELETED) == ["tests/test_old.py"]
    assert review.moved_tests(DIFF) == [] and review.moved_tests(SKIP_MARK) == []
    (tmp_path / "blob.bin").write_bytes(b"ab\x00cd")
    (tmp_path / "long.py").write_text("x" * 5000, encoding="utf-8")
    (tmp_path / "short.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tracked.py").write_text("y" * 5000, encoding="utf-8")
    tracked = "diff --git a/tracked.py b/tracked.py\n--- a/tracked.py\n+++ b/tracked.py\n"
    # changes() appends untracked files as "--- /dev/null / +++ b/<name>" without a diff --git header
    untracked = "\n--- /dev/null\n+++ b/long.py\n+xxx\n"
    got = review.unreadable(tmp_path, ["blob.bin", "long.py", "short.py", "tracked.py", "gone.py"],
                            tracked + untracked)
    assert got == ["blob.bin", "long.py"]


def test_git_rename_of_a_test_file_is_seen(tmp_path):
    # the reviewer's reproduction: `git mv` of the failing test out of collection gives git diff the new name only,
    # 0 changed lines and edited_tests empty; moved_tests must still see it in the real diff text
    from ccx.workspace import undo_snapshot as snapshot
    repo = tmp_path / "r"
    repository(repo)
    (repo / "test_acceptance.py").write_text("def test_requirement():\n    assert False\n", encoding="utf-8")
    git(repo, "add", "test_acceptance.py")
    git(repo, "commit", "-qm", "base")
    snap = snapshot(repo)
    git(repo, "mv", "test_acceptance.py", "acceptance_off.py")
    actual, diff = review.changes(repo, snap)
    assert review.edited_tests(diff) == [] and review.changed_lines(diff) == 0
    assert review.moved_tests(diff) == ["test_acceptance.py"]
    miss = unmet(actual=actual, diff=diff, claimed=actual)
    assert any("renamed or deleted tests" in m for m in miss), miss


def test_ledger_row_marks_a_skipped_review():
    from ccx import ledger
    att = {"started_at": "2026-11-17T00:00:00Z", "startup_seconds": 1.0, "seconds": 3.0}
    skipped = {"attempts": [att], "review": {"verdict": "skipped", "reason": "risk visible", "skipped": "clean: x"}}
    t = ledger.timing_fields(skipped)
    assert "review_timing" not in t                       # not counted in handover_overhead's check_review wall
    assert ledger.timing_fields({"attempts": [att]}) == t   # same timings as a run that needed no review


def test_autonomy_says_skipped_not_failed():
    import inspect
    from ccx import autonomy
    assert "skipped as clean" in inspect.getsource(autonomy)


def test_ui_shows_skipped_neutral_with_text():
    from ccx import ui
    strings = json.loads((ui.STATIC / "strings.json").read_text(encoding="utf-8"))
    langs = [v for v in strings.values() if isinstance(v, dict) and "rv_pass" in v]
    assert len(langs) == 2 and all(lang.get("rv_skipped") for lang in langs)
    js = (ui.STATIC / "app.js").read_text(encoding="utf-8")
    assert 'p.review.verdict === "skipped" ? ""' in js          # neutral colour, not "fail"
    assert "p.review.skipped" in js and 'rv.verdict === "skipped"' in js and "rv.skipped" in js


def test_receipt_and_line_view_say_skipped_and_why():
    rv = {"verdict": "skipped", "reason": "risk visible", "skipped": "clean: check passed and sensitive"}
    res = {"run_id": "r", "status": "done", "ok": True, "check": {"passed": True}, "recap": "ccx run r", "review": rv}
    assert leadview.clean(res)                                     # no review notes: still one line
    line = leadview.line(res)
    assert line["review"] == {"verdict": "skipped", "skipped": rv["skipped"]}
    assert leadview.receipt_status(res) == "done" and leadview.receipt_headline(res) == "DONE"
    assert len(json.dumps(line)) < 1000


@pytest.mark.parametrize("review_mode,risk,beside", [("auto", "visible", False), ("on", "visible", True),
                                                     ("auto", "critical", True)])
def test_review_waits_for_the_check_only_when_it_could_be_skipped(monkeypatch, review_mode, risk, beside):
    import os
    from unittest.mock import patch
    from ccx import check_baseline as baseline, delegate
    env = AdapterEnv()
    env.setUp()
    try:
        repository(env.work)
        (env.work / "acceptance.py").write_text(
            "from pathlib import Path\nassert Path('state.txt').read_text() == 'fixed'\n",
            encoding="utf-8", newline="")
        git(env.work, "add", "acceptance.py")
        git(env.work, "commit", "-qm", "independent acceptance")
        paths = Paths(env.hub)
        set_setting(paths, "check.sensitivity", "warn")
        set_setting(paths, "review.skip_when_clean", "true")
        events = []

        def start(*args):
            events.append("review")
            return object()

        def finish(future, record, paths, keep=True):
            record["review"] = {"verdict": "pass"}

        def deferred(req, paths, cfg, record, *args, **kw):
            events.append("review")
            record["review"] = {"verdict": "pass"}
        actual_check = baseline.Checks.__call__

        def check(self, *args, **kwargs):
            events.append("check")
            return actual_check(self, *args, **kwargs)
        monkeypatch.setattr(delegate, "_start_review", start)
        monkeypatch.setattr(delegate, "_finish_review", finish)
        monkeypatch.setattr(delegate, "_review", deferred)
        monkeypatch.setattr(baseline.Checks, "__call__", check)
        with patch.dict(os.environ, {**env.env, "FAKE_WRITE": "state.txt=fixed"}, clear=True):
            delegate.run(delegate.Request(to="codex", caller="claude", brief="fix state.txt", cwd=env.work,
                                          tier="T1", mode="write", review=review_mode, risk=risk, fallback=False,
                                          check=f'"{sys.executable}" acceptance.py'), paths)
        assert (events.index("review") < events.index("check")) is beside, events
    finally:
        env.tearDown()


class TestSkipWhenCleanCLI(AdapterEnv):
    def setUp(self):
        super().setUp()
        repository(self.work)
        (self.work / "test_acceptance.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "def test_requirement():\n"
            "    if os.environ.get('CCX_TEST_SENSITIVITY') == 'sensitive':\n"
            "        assert Path('state.txt').read_text() == 'fixed'\n",
            encoding="utf-8", newline="")
        git(self.work, "add", "test_acceptance.py")
        git(self.work, "commit", "-qm", "independent acceptance")

    def go(self, skip=None, sensitivity="warn", scenario="sensitive", write="state.txt=fixed", *extra,
           claimed="state.txt"):
        if sensitivity:
            self.j("config", "set", "check.sensitivity", sensitivity)
        if skip is not None:
            self.j("config", "set", "review.skip_when_clean", skip)
        return self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--mode", "write",
                      "--risk", "visible", "--no-fallback", *extra,
                      "--check", f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_acceptance.py',
                      "fix state.txt",
                      env={"FAKE_WRITE": write, "CCX_TEST_SENSITIVITY": scenario, "FAKE_FILES_CHANGED": claimed,
                           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})

    def ledger_row(self, run_id):
        rows = [json.loads(x) for x in Paths(self.hub).ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r.get("run_id") == run_id][-1]

    def reviewer_calls(self):
        return [c for c in self.calls() if "[ccx review" in c.get("prompt", "")]

    def test_on_and_clean_skips_the_review(self):
        out = self.go("true")
        rec = self.rec(out["run_id"])
        assert self.reviewer_calls() == []
        assert out["view"] == "line"                                    # nothing else to look at: one line
        assert set(out["review"]) == {"verdict", "skipped"} and out["review"]["verdict"] == "skipped"
        assert out["review"]["skipped"].startswith("clean:") and "sensitive" in out["review"]["skipped"]
        assert "review=skipped" in out["recap"]
        assert rec["review"]["verdict"] == "skipped" and rec["review"]["reason"] == "risk visible"
        assert "started_at" not in rec["review"]                        # no review ran: no review timing
        full = self.j("show", out["run_id"])
        assert full["review"]["skipped"] == out["review"]["skipped"] and full["review"]["reason"] == "risk visible"
        assert rec["review_skip"]["unmet"] == []
        assert out["status"] == "done" and out["ok"] is True
        row = self.ledger_row(out["run_id"])
        assert row["review_skipped"] is True and "review_timing" not in row

    def test_on_with_claimed_files_not_matching_is_reviewed(self):
        out = self.go("true", claimed="a.py")
        assert len(self.reviewer_calls()) == 1 and out["review"]["verdict"] == "pass"
        assert "claimed files don't match the diff" in self.rec(out["run_id"])["review_skip"]["unmet"]
        assert "review_skipped" not in self.ledger_row(out["run_id"])

    def test_on_with_skip_marker_added_is_reviewed(self):
        marked = ("test_acceptance.py=import pytest" + chr(10) + "@pytest.mark.skip" + chr(10)
                  + "def test_requirement(): assert False")
        out = self.go("true", write="state.txt=fixed;" + marked)
        assert len(self.reviewer_calls()) == 1 and out["review"]["verdict"] == "pass"

    def test_on_with_test_config_changed_is_reviewed(self):
        out = self.go("true", write="state.txt=fixed;pytest.ini=[pytest]", claimed="state.txt;pytest.ini")
        assert len(self.reviewer_calls()) == 1
        assert any("test configuration" in m for m in self.rec(out["run_id"])["review_skip"]["unmet"])

    def test_on_but_insensitive_check_is_reviewed(self):
        out = self.go("true", scenario="passed_before")
        assert len(self.reviewer_calls()) == 1
        assert out["review"]["verdict"] == "pass" and "skipped" not in out["review"]
        assert any("sensitivity" in m for m in self.rec(out["run_id"])["review_skip"]["unmet"])

    def test_on_without_sensitivity_is_reviewed(self):
        out = self.go("true", sensitivity=None)
        assert len(self.reviewer_calls()) == 1 and out["review"]["verdict"] == "pass"

    def test_on_with_review_asked_is_reviewed(self):
        out = self.go("true", "warn", "sensitive", "state.txt=fixed", "--review", "on")
        assert len(self.reviewer_calls()) == 1 and out["review"]["verdict"] == "pass"

    def test_on_over_threshold_is_reviewed(self):
        self.j("config", "set", "review.skip_max_files", "0")
        out = self.go("true")
        assert len(self.reviewer_calls()) == 1 and out["review"]["verdict"] == "pass"

    def test_on_with_edited_test_is_reviewed(self):
        out = self.go("true", write="state.txt=fixed;test_acceptance.py=def test_requirement(): pass\n")
        assert len(self.reviewer_calls()) == 1
        assert out["review"]["verdict"] == "pass" and out["edited_tests"] == ["test_acceptance.py"]

    def test_off_is_unchanged(self):
        default = self.go()
        rec = self.rec(default["run_id"])
        assert len(self.reviewer_calls()) == 1
        assert default["review"]["verdict"] == "pass" and "skipped" not in default["review"]
        assert "review_skip" not in rec and "started_at" in rec["review"]
        git(self.work, "checkout", "-q", "--", "state.txt")          # the same change again
        explicit = self.go("false")
        assert len(self.reviewer_calls()) == 2
        assert "review_skip" not in self.rec(explicit["run_id"])
        assert set(explicit) == set(default) and explicit["review"] == default["review"]
        volatile = ("stdout_path", "stderr_path", "sensitivity_seconds")
        same = lambda c: {k: v for k, v in c.items() if k not in volatile}
        assert same(explicit["check"]) == same(default["check"])
