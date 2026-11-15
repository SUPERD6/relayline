"""A write run that says done/partial but changed nothing is labelled kind=no_changes (not a success, the lead
decides); `--worktree` on a project with uncommitted changes says the run starts from HEAD (fake CLIs only)."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx.config import Paths  # noqa: E402
from test_ccx import Env  # noqa: E402
from test_queue_pipeline import QEnv  # noqa: E402

G = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


class TestNoChanges(Env):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        # no background gc/maintenance: on macOS it wrote objects/maintenance.lock while a test removed .git
        for k, v in (("gc.auto", "0"), ("maintenance.auto", "false")):
            subprocess.run(["git", "config", k, v], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*G, "add", "a.py"], cwd=self.work, check=True)
        subprocess.run([*G, "commit", "-qm", "init"], cwd=self.work, check=True)

    def run_ccx(self, *extra, mode="write", env=None):
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", mode,
                     "--no-fallback", "--review", "off", *extra, "change x to 2 in a.py", env=env)
        self.assertIn(r.returncode, (0, 2), r.stderr)
        return json.loads(r.stdout)

    def record(self, run_id):
        return json.loads((Paths(self.hub).runs / run_id / "run.json").read_text(encoding="utf-8"))

    def ledger_row(self, run_id):
        rows = [json.loads(x) for x in Paths(self.hub).ledger.read_text(encoding="utf-8").splitlines()]
        return [x for x in rows if x.get("run_id") == run_id and not x.get("type")][-1]

    def test_partial_with_no_change_is_not_a_success(self):
        # r5: a builder whose patch never applied was reported ok, and its check passed on the untouched tree
        out = self.run_ccx("--check", "exit 0", env={"FAKE_STATUS": "partial"})
        self.assertEqual((out["status"], out["kind"], out["ok"]), ("partial", "no_changes", False), out)
        self.assertTrue(out["needs_lead"].startswith("no_changes:"), out)
        self.assertEqual((out["check"]["passed"], out["check"]["status"]), (None, "ran on unchanged tree"))
        self.assertIn("changed nothing", out["hint"])
        self.assertIn("check=ran-on-unchanged-tree", out["recap"])
        self.assertIn("needs_lead=no_changes", out["recap"])
        rec = self.record(out["run_id"])
        self.assertTrue(rec["no_changes"] and rec["check"]["unchanged_tree"])
        self.assertTrue(rec["check"]["passed"])                 # what the command did stays recorded as it was
        self.assertIsNone(rec["learned"])                       # neither a success nor a failure to learn from
        row = self.ledger_row(out["run_id"])
        self.assertEqual((row["kind"], row["check"]["unchanged_tree"]), ("no_changes", True))

    def test_done_with_no_change_and_no_check(self):
        out = self.run_ccx()
        self.assertEqual((out["kind"], out["ok"]), ("no_changes", False), out)
        self.assertNotIn("check", out)
        self.assertNotIn("its check", out["hint"])

    def test_own_commit_is_a_change(self):
        # the builder committed its work: the tree matches HEAD, but HEAD moved, so it did change something
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_COMMIT": "x is 2"}
        out = self.run_ccx("--check", "exit 0", env=env)
        self.assertEqual((out["status"], out["ok"]), ("done", True), out)
        self.assertNotIn("kind", out)
        self.assertNotIn("needs_lead", out)
        self.assertTrue(out["check"]["passed"])
        self.assertNotIn("no_changes", self.record(out["run_id"]))

    def test_an_edit_is_a_change(self):
        out = self.run_ccx(env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n"})
        self.assertEqual((out["ok"], out.get("kind")), (True, None), out)

    def test_new_file_and_edited_untracked_file_are_changes(self):
        (self.work / "notes.txt").write_text("old\n", encoding="utf-8")        # untracked before the run
        out = self.run_ccx(env={"FAKE_WRITE": f"{self.work / 'new.py'}=y = 1\n"})
        self.assertEqual(out.get("kind"), None, out)
        out = self.run_ccx(env={"FAKE_WRITE": f"{self.work / 'notes.txt'}=new\n"})
        self.assertEqual(out.get("kind"), None, out)

    def test_read_run_is_untouched(self):
        out = self.run_ccx(mode="read")
        self.assertEqual((out["ok"], out.get("kind")), (True, None), out)
        self.assertNotIn("no_changes", self.record(out["run_id"]))

    def test_not_a_git_repo_claims_nothing(self):
        import os
        import shutil
        import stat

        def writable(fn, path, _exc):              # git's objects are read-only on Windows
            try:
                os.chmod(path, stat.S_IWRITE)
                fn(path)
            except FileNotFoundError:              # a git process removed it meanwhile (its lock file)
                pass
        shutil.rmtree(self.work / ".git", onerror=writable)
        out = self.run_ccx()
        self.assertEqual((out["ok"], out.get("kind")), (True, None), out)

    def test_deleting_an_untracked_file_is_a_change(self):
        # "remove the stray tmp.log": the only change is that a file which was there (untracked) is gone
        (self.work / "tmp.log").write_text("junk\n", encoding="utf-8")
        out = self.run_ccx(env={"FAKE_DELETE": str(self.work / "tmp.log")})
        self.assertEqual((out["ok"], out.get("kind")), (True, None), out)

    def test_non_ascii_untracked_file_does_not_hide_the_label(self):
        # git C-quotes non-ASCII names (core.quotepath): the mtime check must still find the file on disk
        (self.work / "笔记.txt").write_text("old\n", encoding="utf-8")
        out = self.run_ccx()
        self.assertEqual((out["kind"], out["ok"]), ("no_changes", False), out)
        out = self.run_ccx(env={"FAKE_WRITE": f"{self.work / '笔记.txt'}=new\n"})
        self.assertEqual(out.get("kind"), None, out)

    def test_check_that_writes_a_file_on_a_ladder_keeps_the_label(self):
        # with a rung left, ccx runs the check inside the attempt loop: a file the check writes is not the builder's
        check = 'python -c "open(\'check-out.log\', \'w\').write(\'x\')"'
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--mode", "write", "--no-fallback",
                     "--review", "off", "--check", check, "change x to 2 in a.py")
        self.assertIn(r.returncode, (0, 2), r.stderr)
        out = json.loads(r.stdout)
        rec = self.record(out["run_id"])
        self.assertEqual(rec["first_rung"], rec["attempts"][0]["rung"])
        self.assertTrue((self.work / "check-out.log").exists())
        self.assertEqual((out["kind"], out["ok"]), ("no_changes", False), out)
        self.assertEqual(len(rec["attempts"]), 1)


class TestUnquote(unittest.TestCase):
    def test_git_quoted_names(self):
        from ccx.workspace import _unquote
        self.assertEqual(_unquote('"\\347\\254\\224\\350\\256\\260.txt"'), "笔记.txt")
        self.assertEqual(_unquote('"a\\"b.txt"'), 'a"b.txt')
        self.assertEqual(_unquote("plain.txt"), "plain.txt")


class TestNoChangesDownstream(unittest.TestCase):
    """ccx ui and the lanes treat no_changes as not finished cleanly (the queue: TestQueueNoChanges)."""
    REC = {"run_id": "r1", "kind": "no_changes", "state": "finished", "ok": True, "to": "codex",
           "result": {"status": "done", "summary": "done"}, "attempts": []}

    def test_ui_asks_the_person(self):
        import time
        from ccx import ui
        act = ui._act(dict(self.REC), None, time.time(), None)
        self.assertEqual((act["kind"], act["what"]), ("decide", "a_no_changes"))
        self.assertEqual([b["label"] for b in act["buttons"]], ["b_see", "b_make_change", "b_already_met"])
        self.assertEqual(ui.hist_of_run(dict(self.REC), "t")[-1]["k"], "h_no_changes")
        strings = json.loads((Path(ui.__file__).parent / "ui_static" / "strings.json").read_text(encoding="utf-8"))
        for lang in strings.values():
            for k in ("a_no_changes", "w_no_changes", "b_make_change", "b_already_met", "h_no_changes"):
                self.assertIn(k, lang)

    def test_lane_starts_fresh(self):
        from ccx import lanes
        self.assertIn("no_changes", lanes.BAD_KINDS)


class TestWorktreeBase(Env):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*G, "add", "a.py"], cwd=self.work, check=True)
        subprocess.run([*G, "commit", "-qm", "init"], cwd=self.work, check=True)

    def go(self):
        wt_write = "a.py=x = 2\n"                  # relative: the fake runs in the worktree
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", "off", "--worktree", "change x to 2 in a.py",
                     env={"FAKE_WRITE": wt_write})
        self.assertIn(r.returncode, (0, 2), r.stderr)
        out = json.loads(r.stdout)
        rec = json.loads((Paths(self.hub).runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        return out, rec

    def test_dirty_project_gets_a_base_note(self):
        (self.work / "a.py").write_text("x = 5\n", encoding="utf-8")          # uncommitted: the worktree lacks it
        out, rec = self.go()
        note = "base: HEAD, uncommitted changes not included: commit first"
        self.assertIn("worktree", out)
        self.assertEqual((out["base"], rec["base_note"]), (note, note))

    def test_clean_project_has_none(self):
        out, rec = self.go()
        self.assertIn("worktree", out)
        self.assertNotIn("base", out)
        self.assertNotIn("base_note", rec)


class TestWorktreeCommit(Env):
    """#334: Codex's workspace-write sandbox cannot write a worktree's git directory, so ccx tells every sub-agent
    not to commit (even when the brief says to) and its receipt lists what is left uncommitted for the lead."""

    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*G, "add", "a.py"], cwd=self.work, check=True)
        subprocess.run([*G, "commit", "-qm", "init"], cwd=self.work, check=True)

    def go(self, brief="change x to 2 in a.py and commit it", **env):
        log = self.work.parent / "codex-log.jsonl"
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", "off", "--worktree", brief,
                     env={"FAKE_WRITE": "a.py=x = 2\n;new.py=y = 1\n", "FAKE_LOG": str(log), **env})
        self.assertIn(r.returncode, (0, 2), r.stderr)
        out = json.loads(r.stdout)
        rec = json.loads((Paths(self.hub).runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        calls = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        return out, rec, calls

    def test_prompt_says_not_to_commit_and_no_writable_root_is_added(self):
        out, rec, calls = self.go()
        first = calls[0]
        self.assertIn("do not commit, push or switch branches, even if the task says to", first["prompt"])
        self.assertIn("leave your changes uncommitted", first["prompt"])
        argv = " ".join(first["argv"])
        self.assertNotIn("--add-dir", argv)                    # option B: the sandbox is not widened to .git
        self.assertNotIn("writable_roots", argv)
        self.assertNotIn("danger-full-access", argv)

    def test_receipt_lists_uncommitted_files(self):
        out, rec, _ = self.go()
        c = out["commit"]
        self.assertEqual(c["state"], "uncommitted", out)
        self.assertEqual(sorted(c["files"]), ["a.py", "new.py"])
        self.assertIn("git -C", c["next"])
        self.assertIn(f"ccx autonomy merge {out['run_id']}", c["next"])
        self.assertNotIn("note", c)
        self.assertEqual(sorted(rec["commit_state"]["uncommitted"]), ["a.py", "new.py"])
        self.assertFalse(rec["commit_state"]["committed"])
        wt = Path(out["worktree"])                              # ccx itself committed nothing
        log = subprocess.run(["git", "log", "--oneline"], cwd=wt, capture_output=True, text=True).stdout
        self.assertEqual(len(log.splitlines()), 1, log)

    def test_a_sub_agent_that_commits_anyway_is_flagged(self):
        out, rec, _ = self.go(FAKE_COMMIT="sub-agent commit")
        c = out["commit"]
        self.assertEqual((c["state"], c["files"]), ("committed", []), out)
        self.assertIn("although told not to", c["note"])
        self.assertTrue(rec["commit_state"]["committed"])

    def test_no_commit_entry_outside_a_worktree(self):
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", "off", "change x to 2 in a.py", env={"FAKE_WRITE": "a.py=x = 2\n"})
        out = json.loads(r.stdout)
        self.assertNotIn("commit", out)
        self.assertNotIn("worktree", out)


class TestQueueNoChanges(QEnv):
    def test_dependent_does_not_start_on_work_never_made(self):
        self.git_init()
        a = self.q("add", "a", "--brief", "write piece a", "--minutes", "5", "--mode", "write", "--to", "codex")
        b = self.q("add", "b", "--brief", "write piece b", "--minutes", "5", "--mode", "write", "--to", "codex",
                   "--dep", a["id"])
        out = self.q("run")
        self.assertEqual([(r["id"], r["status"]) for r in out["results"]], [(a["id"], "failed")], out)
        self.assertEqual(out["dep_blocked"], {b["id"]: [a["id"]]})


if __name__ == "__main__":
    unittest.main()
