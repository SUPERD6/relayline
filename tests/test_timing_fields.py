"""#392: handover timings in run.json and the ledger (CLI launch -> first event, every check's time, the review's start
and end), read by scripts/eval/handover_overhead.py. Fake CLIs only."""
import copy
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ccx import Env  # noqa: E402

from ccx import delegate, leadview, ledger  # noqa: E402
from ccx.config import Paths  # noqa: E402
from ccx.runners import Invocation, execute, wall_now  # noqa: E402

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import handover_overhead as H  # noqa: E402

ATTEMPT_KEYS = ("started_at", "first_event_at", "startup_seconds")
REVIEW_KEYS = ("started_at", "ended_at", "seconds", "background")


def when(text):
    return datetime.fromisoformat(text)


def strip_timing(rec):
    """The record as it was before #392: no timing keys anywhere."""
    rec = copy.deepcopy(rec)
    for a in rec.get("attempts") or []:
        for k in (*ATTEMPT_KEYS, "check_started_at"):
            a.pop(k, None)
        if a.get("kind") != "check_failed":
            a.pop("check_seconds", None)
    for k in REVIEW_KEYS:
        (rec.get("review") or {}).pop(k, None)
    return rec


class TestRunRecordsTimings(Env):
    def setUp(self):
        super().setUp()
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*g, "add", "a.py"], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "init"], cwd=self.work, check=True)

    def go(self, *extra, code=0):
        check = f'"{sys.executable}" -c "import sys; sys.exit({code})"'
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_REVIEW": "pass"}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--risk", "visible", "--check", check, *extra, "change x to 2 in a.py", env=env)
        self.assertIn(r.returncode, (0, 2), r.stderr)
        out = json.loads(r.stdout)
        p = Paths(self.hub)
        rec = json.loads((p.runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        rows = [json.loads(x) for x in p.ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
        row = next(x for x in rows if x.get("run_id") == out["run_id"])
        return out, rec, row, rows

    def test_attempt_check_and_review_timings_are_all_there(self):
        out, rec, row, rows = self.go()
        self.assertTrue(out["check"]["passed"], out)
        a = rec["attempts"][0]
        for k in ATTEMPT_KEYS:
            self.assertIsNotNone(a.get(k), k)
        self.assertGreaterEqual(a["startup_seconds"], 0)
        self.assertLessEqual(when(a["started_at"]), when(a["first_event_at"]))
        self.assertIsNotNone(when(a["started_at"]).tzinfo)             # UTC with an offset, readable back
        # a passed check keeps its seconds too (before: only a failed one)
        self.assertIsInstance(a["check_seconds"], (int, float))
        self.assertLessEqual(when(a["started_at"]), when(a["check_started_at"]))
        rv = rec["review"]
        self.assertEqual(rv["verdict"], "pass")
        for k in REVIEW_KEYS:
            self.assertIn(k, rv)
        self.assertIs(rv["background"], True)                           # it ran beside the check
        self.assertLessEqual(when(rv["started_at"]), when(rv["ended_at"]))
        self.assertGreaterEqual(rv["seconds"], 0)
        # the ledger row carries them for handover_overhead.py
        self.assertEqual(row["startup_seconds"], a["startup_seconds"])
        self.assertEqual(row["check_timing"], [{"started_at": a["check_started_at"], "seconds": a["check_seconds"]}])
        self.assertEqual(row["check_seconds"], a["check_seconds"])
        self.assertEqual(row["review_timing"], {k: rv[k] for k in REVIEW_KEYS})
        # the review run's own row has its startup too
        rev = next(x for x in rows if x.get("label") == f"review:{out['run_id']}")
        self.assertIsNotNone(rev.get("startup_seconds"))
        # and the script uses them instead of Unknown
        res = H.analyze([{"task": "t", "arm": "ccx", "lead_usd": 0.0, "side_cost_status": "Pass",
                          "unknown_side_usd": 0.0,
                          "side_ledger": [{k: x[k] for k in ("run_id", "label", "ae_usd") if k in x} for x in rows]}],
                        None, rows)
        u = res["per_unit"][0]
        self.assertIsNotNone(u["wall"]["startup"]["value"])
        self.assertIsNotNone(u["wall"]["check_review"]["value"])

    def test_receipts_do_not_grow(self):
        out, rec, row, rows = self.go()
        old = strip_timing(rec)
        self.assertEqual(delegate.compact(rec), delegate.compact(old))
        full, base = delegate.compact(rec), delegate.compact(old)
        for res in (full, base):
            res["recap"] = "x"
        new_line = leadview.dumps(leadview.line(full), True)
        old_line = leadview.dumps(leadview.line(base), True)
        self.assertEqual(len(new_line), len(old_line))
        for k in ("startup_seconds", "first_event_at", "check_started_at", "ended_at"):
            self.assertNotIn(k, new_line)

    def test_review_off_records_no_review_timing(self):
        out, rec, row, rows = self.go("--review", "off")
        self.assertNotIn("review", rec)
        self.assertNotIn("review_timing", row)
        self.assertEqual(len(row["check_timing"]), 1)

    def test_failed_check_keeps_its_seconds_and_drops_the_review(self):
        out, rec, row, rows = self.go(code=1)
        self.assertEqual(rec["kind"], "check_failed")
        self.assertIsInstance(rec["attempts"][-1]["check_seconds"], (int, float))
        self.assertNotIn("review_timing", row)


class TestTimedReview:
    def call(self, monkeypatch, review, record=None):
        monkeypatch.setattr(delegate, "_review", review)
        record = {"run_id": "r1"} if record is None else record
        delegate._timed_review(None, None, {}, record, Path("."), Path("."))
        return record

    def test_sync_review_is_timed(self, monkeypatch):
        rec = self.call(monkeypatch, lambda req, p, cfg, record, *a: record.update(review={"verdict": "pass"}))
        assert rec["review"]["background"] is False
        assert when(rec["review"]["started_at"]) <= when(rec["review"]["ended_at"])

    def test_no_review_due_records_nothing(self, monkeypatch):
        rec = self.call(monkeypatch, lambda *a, **k: None)
        assert "review" not in rec

    def test_a_crashed_review_is_not_run_and_timed(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no")
        rec = self.call(monkeypatch, boom)
        assert rec["review"]["verdict"] == "not-run" and "RuntimeError" in rec["review"]["error"]
        assert "seconds" in rec["review"]

    def test_an_earlier_review_is_not_restamped(self, monkeypatch):
        old = {"verdict": "pass"}
        rec = self.call(monkeypatch, lambda *a, **k: None, {"run_id": "r1", "review": old})
        assert rec["review"] is old and "started_at" not in old


def test_execute_measures_launch_to_first_event(tmp_path):
    code = "import sys, time; sys.stdin.read(); time.sleep(0.3); print('{}'); sys.stdout.flush()"
    oc, so, _ = execute("codex", Invocation([sys.executable, "-c", code], "", tmp_path), 60, None)
    assert oc.startup_seconds is not None and oc.startup_seconds >= 0.25
    assert when(oc.started_at) <= when(oc.first_event_at)


def test_execute_without_any_event_has_no_startup(tmp_path):
    oc, so, _ = execute("codex", Invocation([sys.executable, "-c", "import sys; sys.stdin.read()"], "", tmp_path),
                        60, None)
    assert oc.started_at is not None
    assert oc.first_event_at is None and oc.startup_seconds is None


def test_execute_that_cannot_start_has_no_timing(tmp_path):
    oc, _, _ = execute("codex", Invocation([str(tmp_path / "missing-cli-392")], "", tmp_path), 60, None)
    assert oc.started_at is None and oc.startup_seconds is None


def test_ledger_row_of_an_old_record_has_no_timing_fields():
    rec = {"attempts": [{"rung": "codex:m:low", "seconds": 3.0, "check_seconds": 1.0, "kind": "check_failed"}],
           "review": {"verdict": "pass"}}
    assert ledger.timing_fields(rec) == {}


def test_ledger_row_sums_and_marks_unknown_startup():
    rec = {"attempts": [{"started_at": wall_now(), "startup_seconds": 1.5, "check_started_at": wall_now(),
                         "check_seconds": 2.0},
                        {"started_at": wall_now(), "startup_seconds": 0.5, "check_started_at": wall_now(),
                         "check_seconds": None}]}
    out = ledger.timing_fields(rec)
    assert out["startup_seconds"] == 2.0 and out["check_seconds"] == 2.0 and len(out["check_timing"]) == 2
    assert "review_timing" not in out
    rec["attempts"][1]["startup_seconds"] = None                      # an attempt that saw no event
    assert ledger.timing_fields(rec)["startup_seconds"] is None


# --- handover_overhead.py: the fields used when present, Unknown when not
def unit_row():
    return {"task": "t1", "arm": "ccxlong", "lead_usd": 1.0, "side_cost_status": "Pass", "unknown_side_usd": 0.0,
            "side_ledger": [{"run_id": "a", "label": "", "ae_usd": 0.5},
                            {"run_id": "b", "label": "review:a", "ae_usd": 0.1}]}


def test_script_uses_timings_and_counts_overlap_once():
    led = [{"run_id": "a", "seconds": 120.0, "startup_seconds": 4.0,
            "check_timing": [{"started_at": "2026-11-17T10:00:00+00:00", "seconds": 10.0},
                             {"started_at": "2026-11-17T10:05:00+00:00", "seconds": 20.0}],
            # background review from 10:05:00 for 30 s overlaps the second check's 20 s: union 30 s
            "review_timing": {"started_at": "2026-11-17T10:05:00Z", "ended_at": "2026-11-17T10:05:30Z",
                              "seconds": 30.0, "background": True}},
           {"run_id": "b", "seconds": 25.0, "startup_seconds": 2.0}]
    u = H.analyze([unit_row()], None, led)["per_unit"][0]
    assert u["wall"]["startup"]["value"] == pytest.approx(4.0)
    assert u["wall"]["agent"]["value"] == pytest.approx(116.0) and u["wall"]["agent"]["startup_subtracted"]
    assert u["wall"]["check_review"]["value"] == pytest.approx(10.0 + 30.0)
    assert u["cost"]["startup"]["value"] is None          # start-up tokens sit inside the first request


def test_script_timings_from_side_ledger_entries_without_ledger():
    row = unit_row()
    row["side_ledger"][0].update(startup_seconds=3.0, check_timing=[{"started_at": "2026-11-17T10:00:00Z",
                                                                     "seconds": 5.0}])
    u = H.analyze([row], None, None)["per_unit"][0]
    assert u["wall"]["startup"]["value"] == pytest.approx(3.0)
    assert u["wall"]["check_review"]["value"] == pytest.approx(5.0)    # no review on that run


def test_script_old_rows_stay_unknown():
    led = [{"run_id": "a", "seconds": 120.0}, {"run_id": "b", "seconds": 25.0}]
    u = H.analyze([unit_row()], None, led)["per_unit"][0]
    assert u["wall"]["startup"]["value"] is None and "#392" in u["wall"]["startup"]["unknown"]
    assert u["wall"]["check_review"]["value"] is None and "check_timing" in u["wall"]["check_review"]["unknown"]
    assert u["wall"]["agent"]["value"] == 120.0 and not u["wall"]["agent"]["startup_subtracted"]
    text = H.report(H.analyze([unit_row()], None, led))
    assert "Unknown" in text


def test_summary_does_not_mix_agent_wall_with_and_without_startup():
    new = {**unit_row(), "task": "new"}
    old = {**unit_row(), "task": "old", "side_ledger": [{"run_id": "c", "label": "", "ae_usd": 0.5}]}
    led = [{"run_id": "a", "seconds": 100.0, "startup_seconds": 10.0, "check_timing": []},
           {"run_id": "b", "seconds": 5.0}, {"run_id": "c", "seconds": 60.0}]
    res = H.analyze([new, old], None, led)
    assert res["per_unit"][0]["wall"]["agent"]["value"] == 90.0          # per unit: startup taken out where known
    agent = res["all"]["wall"]["agent"]
    assert agent["sum"] == 160.0                                          # summary: startup kept in both units
    assert agent["startup_subtracted_units"] == 0 and agent["startup_known_units"] == 1 and agent["note"]
    assert "unit(s) have startup" in H.report(res)
    only_new = H.analyze([new], None, led)["all"]["wall"]["agent"]
    assert only_new["sum"] == 90.0 and only_new["startup_subtracted_units"] == 1 and only_new["note"] is None
