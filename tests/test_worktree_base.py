"""What a `ccx run --worktree` starts from (#336): --base head|upstream and [worktree] base. Local bare remotes and
fake agents only."""
import json
import unittest
from pathlib import Path
from unittest import mock

from test_stop import wait_for
from test_worktree_fetch import UpstreamRepo

from ccx import workspace
from ccx.config import load_config, worktree_base

BEHIND = ("ccx: warning: main is 2 commit(s) behind origin/main; the worktree starts from the local HEAD "
          "(git pull first if you want the newer base)")


class TestWorktreeBase(UpstreamRepo):
    def head_of(self, path):
        return self.git("rev-parse", "HEAD", cwd=Path(path))

    def test_default_head_is_unchanged_and_warns_with_the_option_before_the_agent(self):
        base = self.git("rev-parse", "HEAD")
        self.advance(2)
        out, rec, r = self.completed()
        lines = r.stderr.splitlines()
        self.assertIn(BEHIND, lines)
        self.assertEqual(lines[lines.index(BEHIND) + 1], workspace.BASE_TIP)
        self.assertEqual(self.head_of(rec["cwd"]), base)
        self.assertEqual(rec["base_behind"], 2)
        self.assertNotIn("worktree_base", rec)        # the record of a default run carries what it always did
        self.assertIn("base: 2 behind upstream", out["recap"])

    def test_base_upstream_starts_from_the_fetched_upstream_without_tracking_it(self):
        self.advance(2)
        out, rec, r = self.completed("--base", "upstream")
        wt = Path(rec["cwd"])
        self.assertEqual(self.head_of(wt), self.git("rev-parse", "origin/main"))
        self.assertTrue((wt / "upstream.txt").is_file())
        self.assertEqual((rec["worktree_base"], rec["base_ref"], rec["base_behind"]), ("upstream", "origin/main", 0))
        self.assertEqual(rec["base_sha"], self.git("rev-parse", "origin/main"))
        self.assertNotIn("behind upstream", out["recap"])
        self.assertNotIn("ccx: warning:", r.stderr)
        branch = self.git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt)
        self.assertEqual(self.git("for-each-ref", "--format=%(upstream)", f"refs/heads/{branch}"), "")
        self.assertNotEqual(self.git("rev-parse", "HEAD"), self.head_of(wt))   # the main checkout did not move

    def test_config_base_upstream_and_flag_overrides_it(self):
        r = self.ccx("config", "set", "worktree.base", "upstream")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout), {"worktree.base": "upstream"})
        self.advance()
        _, rec, _ = self.completed()
        self.assertEqual(rec["worktree_base"], "upstream")
        self.assertTrue((Path(rec["cwd"]) / "upstream.txt").is_file())
        _, rec, r = self.completed("--base", "head")
        self.assertNotIn("worktree_base", rec)
        self.assertFalse((Path(rec["cwd"]) / "upstream.txt").exists())
        self.assertIn("commit(s) behind origin/main", r.stderr)

    def test_no_upstream_falls_back_to_head_with_a_note(self):
        self.git("branch", "--unset-upstream")
        base = self.git("rev-parse", "HEAD")
        _, rec, r = self.completed("--base", "upstream")
        self.assertEqual(self.head_of(rec["cwd"]), base)
        self.assertEqual((rec["worktree_base"], rec["worktree_base_fallback"]), ("head", "no upstream"))
        self.assertIn("ccx: note: base = upstream, but the current branch has no usable upstream", r.stderr)
        self.assertNotIn("ccx: warning:", r.stderr)
        self.assertNotIn("base_behind", rec)

    def test_upstream_warns_about_local_commits_left_out(self):
        (self.work / "local.txt").write_text("local\n", encoding="utf-8")
        self.git("add", "local.txt")
        self.git("commit", "-qm", "local only")
        _, rec, r = self.completed("--base", "upstream")
        self.assertEqual(rec["local_ahead"], 1)
        self.assertFalse((Path(rec["cwd"]) / "local.txt").exists())
        self.assertIn("main has 1 local commit(s) not in origin/main", r.stderr)

    def test_upstream_fetch_failure_uses_the_last_fetched_upstream(self):
        self.advance()
        self.git("fetch", "-q", "origin")
        self.git("remote", "set-url", "origin", str(self.remote.parent / "missing.git"))
        _, rec, r = self.completed("--base", "upstream")
        self.assertTrue((Path(rec["cwd"]) / "upstream.txt").is_file())
        self.assertEqual(rec["worktree_base"], "upstream")
        self.assertNotIn("base_behind", rec)          # the upstream may have moved since: no distance claimed
        self.assertIn("continuing from the last-fetched origin/main", r.stderr)

    def test_make_worktree_warns_before_git_worktree_add(self):
        self.advance(2)
        order = []
        real = workspace.subprocess.run

        def run(args, *a, **kw):
            if args[:3] == ["git", "worktree", "add"]:
                order.append(("add", args))
            return real(args, *a, **kw)

        with mock.patch.object(workspace.subprocess, "run", run), mock.patch("sys.stderr") as err:
            err.write.side_effect = lambda s: order.append(("stderr", s))
            workspace.make_worktree(self.work, "direct-upstream", base="upstream")
            workspace.make_worktree(self.work, "direct-head", base="head")
        adds = [i for i, (kind, _) in enumerate(order) if kind == "add"]
        self.assertEqual(order[adds[0]][1][3:6], ["--no-track", "-b", "ccx/direct-upstream"])
        self.assertEqual(order[adds[0]][1][-1], self.git("rev-parse", "origin/main"))   # the commit, not the ref
        warned = next(i for i, (kind, s) in enumerate(order) if kind == "stderr" and "commit(s) behind" in s)
        self.assertLess(adds[0], warned)              # upstream run: no behind warning; the head run's comes ...
        self.assertLess(warned, adds[1])              # ... before its own worktree (and so before any sub-agent)
        with self.assertRaisesRegex(ValueError, "--base must be head or upstream"):
            workspace.make_worktree(self.work, "bad", base="origin")

    def test_background_receipt_says_the_base_before_detaching(self):
        self.advance(2)
        self.git("fetch", "-q", "origin")             # the parent reads local refs only; the child fetches
        cases = (((), {"worktree_base": "head", "base_behind": 2}),
                 (("--base", "upstream"), {"worktree_base": "upstream", "base_ref": "origin/main"}))
        for flags, want in cases:
            with self.subTest(flags=flags):
                r = self.ccx("run", "--from", "user", "--to", "codex", "--tier", "T1", "--mode", "write",
                             "--cwd", str(self.work), "--worktree", "--review", "off", "--no-escalate",
                             "--no-fallback", "--no-ab", "--bg", *flags, "edit a.txt",
                             env={"FAKE_WRITE": "a.txt=changed by agent"})
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                bg = json.loads(r.stdout)
                try:
                    self.assertEqual(bg["state"], "started")
                    self.assertEqual({k: bg["base_preview"][k] for k in want}, want)
                    if flags:
                        self.assertNotIn("ccx: warning:", r.stderr)
                    else:
                        self.assertIn("main is 2 commit(s) behind origin/main (as of the last fetch)", r.stderr)
                        self.assertIn(workspace.BASE_TIP, r.stderr)
                    self.assertTrue(wait_for(lambda: self.record(bg["run_id"]).get("state") == "finished", 60))
                finally:
                    self.reap(bg["run_id"])

    def test_dirty_project_note_names_the_upstream_base(self):
        (self.work / "a.txt").write_text("uncommitted\n", encoding="utf-8")
        out, rec, _ = self.completed("--base", "upstream")
        self.assertEqual(rec["base_note"], "base: origin/main, uncommitted changes not included")
        self.assertEqual(out["base"], rec["base_note"])
        _, rec, _ = self.completed()
        self.assertEqual(rec["base_note"], "base: HEAD, uncommitted changes not included: commit first")

    def test_base_without_worktree_is_noted_and_ignored(self):
        r = self.ccx("run", "--from", "user", "--to", "codex", "--tier", "T1", "--mode", "read",
                     "--cwd", str(self.work), "--review", "off", "--no-escalate", "--no-fallback", "--no-ab",
                     "--base", "upstream", "look at a.txt")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ccx: note: --base only applies to a write run with --worktree; ignored", r.stderr)

    def test_configuration_default_and_validation(self):
        self.assertEqual(worktree_base({}), "head")
        self.assertEqual(worktree_base(load_config()), "head")
        for value in ("HEAD", "origin", "", None, True):
            with self.subTest(base=value), self.assertRaisesRegex(ValueError, "worktree.base must"):
                worktree_base({"worktree": {"base": value}})
        r = self.ccx("config", "set", "worktree.base", "origin")
        self.assertNotEqual(r.returncode, 0)
        r = self.ccx("run", "--to", "codex", "--worktree", "--base", "origin", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid choice", r.stderr)


if __name__ == "__main__":
    unittest.main()
