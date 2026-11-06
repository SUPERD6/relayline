"""Issue #282: standalone pending lists and opt-in filters (no real agent CLIs)."""
import json
from pathlib import Path
from unittest import mock

from ccx import ledger, verdicts
from ccx.config import Paths
from ccx.verify_list import matches, pending
from test_ccx import Env


class TestVerifyList(Env):
    NOW = 2000000000

    def record(self, rid, *, age=1, cwd=None, status="done", **extra):
        p = Paths(self.hub)
        rec = {"run_id": rid, "ts": self.NOW - age * 86400, "state": "finished",
               "cwd": str(cwd or self.work), "label": "work", "attempts": [],
               "result": {"status": status, "summary": rid}, **extra}
        directory = p.runs / rid
        directory.mkdir(parents=True, exist_ok=True)
        ledger.write_record(directory, rec)
        ledger.append_event(p, {"run_id": rid, "ts": rec["ts"], "cwd": rec["cwd"],
                                "status": status, "label": rec["label"]})
        return rec

    def listing(self, *args):
        # Env.ccx starts a separate process outside the repository, with an isolated hub.
        result = self.ccx("verify", "--list", *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)["pending"]

    def test_standalone_cli_lists_pending_without_writing(self):
        self.record("waiting")
        self.record("judged", verdict={"ok": True})
        self.record("soft", verdict={"ok": True, "soft": True})
        self.record("dismissed", dismissed={"note": "probe"})
        self.record("running", state="running")
        self.record("temporary", ephemeral=True)
        self.record("evaluation", label="eval-probe")
        self.record("internal", label="review:waiting")
        self.record("ledger-judged")
        ledger.append_event(Paths(self.hub), {"type": "verify", "run_id": "ledger-judged", "ok": False})
        p = Paths(self.hub)
        before = {str(f): f.read_bytes() for f in p.state.rglob("*") if f.is_file()}
        self.assertEqual([r["run_id"] for r in self.listing("--days", "0")], ["waiting"])
        after = {str(f): f.read_bytes() for f in p.state.rglob("*") if f.is_file()}
        self.assertEqual(before, after)
        self.assertEqual({r["run_id"] for r in self.listing("--days", "0", "--include-evals")},
                         {"waiting", "evaluation", "internal"})

    def test_empty_list_and_filters_through_cli(self):
        self.assertEqual(self.listing(), [])
        self.record("one", status="done")
        self.record("two", status="partial", cwd=self.work / "other")
        self.assertEqual([r["run_id"] for r in self.listing("--days", "0", "--project", "work",
                                                          "--state", "done")], ["one"])
        self.assertEqual([r["run_id"] for r in self.listing("--days", "0", "--project", str(self.work / "other"),
                                                          "--state", "partial")], ["two"])
        self.assertEqual(self.listing("--days", "0", "--state", "failed"), [])

    def test_default_list_finds_a_fake_cli_run(self):
        result = self.ccx("run", "--to", "codex", "--tier", "T1", "--mode", "read", "--review", "off", "look")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rid = json.loads(result.stdout)["run_id"]
        self.assertEqual([r["run_id"] for r in self.listing()], [rid])

    def test_days_default_extended_and_all(self):
        self.record("recent", age=2)
        self.record("older", age=8)
        self.record("ancient", age=40)
        p = Paths(self.hub)
        with mock.patch("ccx.verify_list.time.time", return_value=self.NOW):
            self.assertEqual([r["run_id"] for r in pending(p)], ["recent"])
            self.assertEqual([r["run_id"] for r in pending(p, days=30)], ["recent", "older"])
            self.assertEqual(len(pending(p, days=0)), 3)
        for invalid in ("-1", "nan", "inf"):
            result = self.ccx("verify", "--list", "--days", invalid)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("finite non-negative", result.stdout + result.stderr)

    def test_sample_filters_and_existing_json_shape(self):
        p = Paths(self.hub)
        for rid, age, cwd in (("old", 10, self.work), ("other", 1, self.work / "other")):
            rec = self.record(rid, age=age, cwd=cwd, verdict={"ok": True, "soft": True})
            ledger.append_event(p, {"type": "verify", "run_id": rid, "ts": rec["ts"], "soft": True, "ok": True})
        with mock.patch("ccx.verdicts.time.time", return_value=self.NOW):
            self.assertEqual([r["run_id"] for r in verdicts.sample_soft(p)], ["other"])
            self.assertEqual([r["run_id"] for r in verdicts.sample_soft(p, days=30, project="work", state="done")],
                             ["old"])
        result = self.ccx("verify", "--sample", "5", "--list", "--days", "0", "--project", "work", "--state", "done")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual([r["run_id"] for r in output["sample"]], ["old"])
        self.assertEqual(output["sample"][0]["probable"], "right")

    def test_list_rejects_verdict_arguments_without_changing_records(self):
        self.record("waiting")
        p = Paths(self.hub)
        before = {str(f): f.read_bytes() for f in p.state.rglob("*") if f.is_file()}
        for args in (("waiting",), ("--ok", "1"), ("--ok", "0"), ("--dismiss",),
                     ("waiting", "--ok", "1"), ("waiting", "--dismiss"),
                     ("--sample", "5", "waiting", "--ok", "0")):
            result = self.ccx("verify", "--list", *args)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--list cannot be combined", result.stdout + result.stderr)
        after = {str(f): f.read_bytes() for f in p.state.rglob("*") if f.is_file()}
        self.assertEqual(before, after)

    def test_project_folds_saved_worktrees_back_to_repository(self):
        repo = self.work / "app"
        repo.mkdir()
        (repo / ".git").mkdir()
        sibling = self.work / ".ccx-worktrees" / "app" / "piece-1" / "src"
        inside = repo / ".ccx" / "worktrees" / "piece-2" / "src"
        self.record("sibling", cwd=sibling)
        self.record("inside", cwd=inside)
        for selector in ("app", str(repo)):
            self.assertEqual({r["run_id"] for r in self.listing("--days", "0", "--project", selector)},
                             {"sibling", "inside"})

    def test_project_missing_cwd_and_invalid_paths_do_not_match(self):
        for cwd in (None, ""):
            self.assertFalse(matches({"cwd": cwd}, ".", None))
        with mock.patch("ccx.verify_list.Path.resolve", side_effect=ValueError("bad path")):
            self.assertFalse(matches({"cwd": str(self.work)}, "work", None))
        for error in (OSError("bad path"), RuntimeError("symlink loop")):
            with mock.patch("ccx.ui.project_root", side_effect=error):
                self.assertFalse(matches({"cwd": str(self.work)}, "work", None))
        self.record("good")
        self.record("bad", cwd="invalid\x00path")
        self.assertEqual([r["run_id"] for r in self.listing("--days", "0", "--project", "work")], ["good"])

    def test_project_same_name_groups_and_path_disambiguates(self):
        first, second = self.work / "one" / "app", self.work / "two" / "app"
        self.record("first", cwd=first)
        self.record("second", cwd=second)
        self.assertEqual({r["run_id"] for r in self.listing("--days", "0", "--project", "app")},
                         {"first", "second"})
        self.assertEqual([r["run_id"] for r in self.listing("--days", "0", "--project", str(first))], ["first"])

    def test_windows_project_name_and_path_are_case_insensitive(self):
        rec = {"cwd": str(self.work / "MyApp")}
        with mock.patch("ccx.verify_list._WINDOWS", True):
            self.assertTrue(matches(rec, "myapp", None))
            self.assertTrue(matches(rec, str(self.work / "MyApp").upper(), None))
        with mock.patch("ccx.verify_list._WINDOWS", False):
            self.assertFalse(matches(rec, "myapp", None))

    def test_unreadable_record_count_is_visible_in_cli(self):
        self.record("good")
        self.record("broken")
        (Paths(self.hub).runs / "broken" / "run.json").write_text("{", encoding="utf-8")
        result = self.ccx("verify", "--list", "--days", "0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual([r["run_id"] for r in output["pending"]], ["good"])
        self.assertEqual(output["unreadable"], 1)
        self.assertIn("could not read 1", output["note"])

    def test_record_reader_retries_and_counts_permanent_failure(self):
        self.record("waiting")
        p = Paths(self.hub)
        real_read = Path.read_text
        failures = [True]

        def transient_read(path, *args, **kwargs):
            if path.name == "run.json" and failures:
                failures.pop()
                raise PermissionError("replacing run.json")
            return real_read(path, *args, **kwargs)

        counts = {}
        with mock.patch.object(Path, "read_text", transient_read), mock.patch("ccx.ledger.time.sleep") as sleep:
            self.assertEqual([r["run_id"] for r in pending(p, days=0, counts=counts)], ["waiting"])
            self.assertEqual(counts["unreadable"], 0)
            sleep.assert_called_once_with(0.05)
        with mock.patch("ccx.ledger.read_record", side_effect=PermissionError("locked")):
            self.assertEqual(pending(p, days=0, counts=counts), [])
            self.assertEqual(counts["unreadable"], 1)
