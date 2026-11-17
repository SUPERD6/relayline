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
             actual=["state.txt"], diff=DIFF, edited=[], self_checked=False, committed=False)


def unmet(rc=None, **kw):
    return review.clean_skip({"skip_when_clean": True, **(rc or {})}, **{**CLEAN, **kw})[0]


def test_default_off_and_registered(tmp_path):
    cfg = load_config(Paths(tmp_path))
    rc = cfg["review"]
    assert rc["skip_when_clean"] is False and rc["skip_max_files"] == 3 and rc["skip_max_lines"] == 50
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
    ({"check": {"passed": True, "sensitivity": "sensitive", "unchanged_tree": True}}, "check weak"),
    ({"check": {"passed": True}}, "sensitivity"),
    ({"check": {"passed": True, "sensitivity": "unknown"}}, "sensitivity"),
    ({"check": {"passed": True, "sensitivity": "insensitive"}}, "sensitivity"),
    ({"actual": ["a.py", "b.py", "c.py", "d.py"]}, "4 files"),
    ({"actual": []}, "no changes"),
    ({"edited": ["tests/test_a.py"]}, "edited tests"),
    ({"self_checked": True}, "self-authored"),
    ({"committed": True}, "committed"),
    ({"result": {"open_questions": ["is this right?"]}}, "open questions"),
])
def test_any_unmet_condition_keeps_the_review(kw, word):
    miss = unmet(**kw)
    assert miss and any(word in m for m in miss), miss


def test_thresholds_are_configurable():
    big = "--- a/a.py\n+++ b/a.py\n@@ -1 +1,60 @@\n" + "".join(f"+x{i}\n" for i in range(60))
    assert any("lines" in m for m in unmet(diff=big))                    # 60 > 50 by default
    assert unmet({"skip_max_lines": 100}, diff=big) == []
    assert any("files" in m for m in unmet({"skip_max_files": 0}))
    assert unmet({"skip_max_files": "x", "skip_max_lines": None}) == []   # a bad value falls back to the default


def test_receipt_and_line_view_say_skipped_and_why():
    rv = {"verdict": "skipped", "reason": "risk visible", "skipped": "clean: check passed and sensitive"}
    res = {"run_id": "r", "status": "done", "ok": True, "check": {"passed": True}, "recap": "ccx run r", "review": rv}
    assert leadview.clean(res)                                     # no review notes: still one line
    line = leadview.line(res)
    assert line["review"] == {"verdict": "skipped", "skipped": rv["skipped"]}
    assert leadview.receipt_status(res) == "done" and leadview.receipt_headline(res) == "DONE"
    assert len(json.dumps(line)) < 1000


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

    def go(self, skip=None, sensitivity="warn", scenario="sensitive", write="state.txt=fixed", *extra):
        if sensitivity:
            self.j("config", "set", "check.sensitivity", sensitivity)
        if skip is not None:
            self.j("config", "set", "review.skip_when_clean", skip)
        return self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--mode", "write",
                      "--risk", "visible", "--no-fallback", *extra,
                      "--check", f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_acceptance.py',
                      "fix state.txt",
                      env={"FAKE_WRITE": write, "CCX_TEST_SENSITIVITY": scenario,
                           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})

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
