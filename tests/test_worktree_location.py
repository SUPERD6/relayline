"""Worktree placement through the CLI, launched outside this checkout; fake agents only."""
import json
import subprocess
from pathlib import Path

from test_ccx import FAKES
from test_stop import StopEnv, wait_for

from ccx.config import Paths, load_config
from ccx.workspace import canonical


class TestWorktreeLocation(StopEnv):
    def setUp(self):
        super().setUp()
        self.work = canonical(self.work)
        self.env.update({"CCX_GEMINI_BIN": str(FAKES / "fake_gemini.py"),
                         "CCX_DSH_BIN": str(FAKES / "fake_dsh.py")})
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.com")
        (self.work / "a.txt").write_text("original\n", encoding="utf-8")
        (self.work / ".gitignore").write_text(".ccx/\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def tearDown(self):
        for rid in getattr(self, "_bg", []):
            self.reap(rid)
        self._bg = []
        for line in self.git("worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                wt = canonical(line[9:])
                if wt != canonical(self.work):
                    # Only remove test worktrees within this test's temporary directory.
                    self.assertTrue(wt.is_relative_to(canonical(self.tmp.name)))
                    self.git("worktree", "remove", "--force", str(wt))
        super().tearDown()

    def git(self, *args, cwd=None):
        r = subprocess.run(["git", *args], cwd=cwd or self.work, check=True,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip()

    def j(self, *args, env=None):
        r = self.ccx(*args, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def location(self, value):
        return self.j("config", "set", "worktree.location", value)

    def piece(self, *flags, agent="codex", env=None):
        return self.ccx("run", "--from", "user", "--to", agent, "--tier", "T1", "--mode", "write",
                        "--worktree", "--review", "off", "--no-escalate", "--no-fallback", "--no-ab",
                        *flags, "edit a.txt", env={"FAKE_WRITE": "a.txt=changed by agent", **(env or {})})

    def completed(self, *flags, agent="codex", env=None):
        r = self.piece(*flags, agent=agent, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        rec = self.record(out["run_id"])
        self.assertEqual((rec["state"], out["status"]), ("finished", "done"), r.stdout + r.stderr)
        return out, rec, r

    def test_default_keeps_sibling_layout_and_codex_arguments(self):
        self.assertEqual(self.j("config", "get", "worktree.location"), {"worktree.location": "sibling"})
        out, rec, r = self.completed()
        wt = self.work.parent / ".ccx-worktrees" / self.work.name / out["run_id"]
        self.assertEqual(Path(rec["cwd"]), wt)
        self.assertEqual(Path(out["worktree"]), wt)
        self.assertNotIn("warning: worktree.location", r.stderr)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual((wt / "a.txt").read_text(encoding="utf-8"), "changed by agent")
        argv = self.calls()[-1]["argv"]
        self.assertIn("--skip-git-repo-check", argv)
        self.assertEqual(Path(argv[argv.index("-C") + 1]), wt)
        self.assertIn("workspace-write", " ".join(argv))

    def test_explicit_sibling_keeps_the_same_layout(self):
        self.location("sibling")
        (self.work / ".gitignore").unlink()
        out, rec, r = self.completed()
        self.assertEqual(Path(rec["cwd"]),
                         self.work.parent / ".ccx-worktrees" / self.work.name / out["run_id"])
        self.assertNotIn("warning: worktree.location", r.stderr)

    def test_inside_uses_real_worktrees_for_both_agents_and_keeps_main_clean(self):
        self.location("inside")
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                out, rec, r = self.completed(agent=agent)
                wt = self.work / ".ccx" / "worktrees" / out["run_id"]
                self.assertEqual(Path(rec["cwd"]), wt)
                self.assertEqual(self.git("rev-parse", "--show-toplevel", cwd=wt), wt.as_posix())
                self.assertEqual(self.git("branch", "--show-current", cwd=wt), "ccx/" + out["run_id"])
                self.assertEqual((wt / "a.txt").read_text(encoding="utf-8"), "changed by agent")
                self.assertEqual((self.work / "a.txt").read_text(encoding="utf-8"), "original\n")
                self.assertEqual(self.git("status", "--porcelain"), "")
                self.assertNotIn("warning: worktree.location", r.stderr)
                argv = self.calls()[-1]["argv"]
                if agent == "codex":
                    self.assertIn("--skip-git-repo-check", argv)
                    self.assertEqual(Path(argv[argv.index("-C") + 1]), wt)
                    self.assertIn("workspace-write", " ".join(argv))
                else:
                    self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")

    def test_inside_from_a_subdirectory_uses_the_repository_root(self):
        self.location("inside")
        sub = self.work / "sub"
        sub.mkdir()
        out, rec, _ = self.completed("--cwd", str(sub))
        self.assertEqual(Path(rec["cwd"]), self.work / ".ccx" / "worktrees" / out["run_id"])

    def test_hub_override_and_config_set_precedence(self):
        p = Paths(self.hub)
        p.user_tiers.parent.mkdir(parents=True, exist_ok=True)
        p.user_tiers.write_text('[worktree]\nlocation = "inside"\n', encoding="utf-8")
        out, rec, _ = self.completed()
        self.assertEqual(Path(rec["cwd"]), self.work / ".ccx" / "worktrees" / out["run_id"])
        self.location("sibling")
        self.assertEqual(load_config(p)["worktree"]["location"], "sibling")
        _, rec, _ = self.completed()
        self.assertEqual(Path(rec["cwd"]).parent, self.work.parent / ".ccx-worktrees" / self.work.name)

    def test_invalid_setting_is_rejected_without_changing_the_saved_value(self):
        self.location("inside")
        r = self.ccx("config", "set", "worktree.location", "elsewhere")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("worktree.location must be sibling or inside", r.stdout + r.stderr)
        self.assertEqual(self.j("config", "get", "worktree.location"), {"worktree.location": "inside"})

    def test_invalid_hand_edited_setting_creates_no_worktree(self):
        p = Paths(self.hub)
        p.user_tiers.parent.mkdir(parents=True, exist_ok=True)
        p.user_tiers.write_text('[worktree]\nlocation = "elsewhere"\n', encoding="utf-8")
        r = self.piece()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("worktree.location must be sibling or inside", r.stdout + r.stderr)
        self.assertFalse((self.work / ".ccx" / "worktrees").exists())
        self.assertFalse((self.work.parent / ".ccx-worktrees").exists())
        self.assertEqual(self.calls(), [])

    def test_inside_warns_before_creation_without_editing_gitignore(self):
        self.location("inside")
        gi = self.work / ".gitignore"
        for contents in (None, ".ccx/inbox/\n", ".ccx/\n!.ccx/\n"):
            with self.subTest(contents=contents):
                if contents is None:
                    gi.unlink()
                else:
                    gi.write_text(contents, encoding="utf-8")
                _, rec, r = self.completed()
                self.assertIn("warning: worktree.location = inside", r.stderr)
                self.assertIn("Add .ccx/", r.stderr)
                self.assertEqual(gi.read_text(encoding="utf-8") if gi.exists() else None, contents)
                self.assertTrue(Path(rec["cwd"]).is_dir())

    def test_doctor_explains_both_locations_and_rejects_invalid_config(self):
        for location, path, explanation in (
                ("sibling", ".ccx-worktrees", "keeps the existing directory layout"),
                ("inside", ".ccx/worktrees", "ignore .ccx/ in .gitignore")):
            self.location(location)
            r = self.ccx("doctor")
            row = next(x for x in r.stdout.splitlines() if x.startswith("worktree location"))
            self.assertIn("ok", row)
            self.assertIn(location + ":", row)
            self.assertIn(path, row)
            self.assertIn(explanation, row)
        Paths(self.hub).settings.write_text('[worktree]\nlocation = "elsewhere"\n', encoding="utf-8")
        r = self.ccx("doctor")
        self.assertNotEqual(r.returncode, 0)
        row = next(x for x in r.stdout.splitlines() if x.startswith("worktree location"))
        self.assertIn("FAIL", row)
        self.assertIn("worktree.location must be sibling or inside", row)

    def test_inside_undo_uses_the_recorded_path_after_location_changes(self):
        self.location("inside")
        out, rec, _ = self.completed(env={"FAKE_WRITE": "a.txt=changed;new.txt=created"})
        wt = Path(rec["cwd"])
        self.location("sibling")
        dry = self.j("undo", out["run_id"])
        self.assertEqual((dry["restore"], dry["move_aside"], dry["applied"]), (["a.txt"], ["new.txt"], False))
        self.assertTrue(self.j("undo", out["run_id"], "--apply")["applied"])
        self.assertEqual((wt / "a.txt").read_text(encoding="utf-8"), "original\n")
        self.assertEqual((wt / ".ccx" / "undo" / out["run_id"] / "new.txt").read_text(encoding="utf-8"), "created")
        self.assertFalse((wt / "new.txt").exists())
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_inside_stop_and_resume_keep_the_recorded_worktree(self):
        self.location("inside")
        r = self.piece("--bg", env={"FAKE_STATUS": "hang", "FAKE_HANG_S": "90"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rid = json.loads(r.stdout)["run_id"]
        self._bg = [rid]
        rec = wait_for(lambda: (x := self.record(rid)).get("pid") and x.get("session_id") and x)
        self.assertTrue(rec, "the fake agent never started")
        wt = self.work / ".ccx" / "worktrees" / rid
        self.assertEqual(Path(rec["cwd"]), wt)
        self.location("sibling")
        stopped = self.j("stop", rid)
        self.assertEqual((stopped["state"], stopped["kind"]), ("stopped", "user_stopped"))
        self.reap(rid)
        resumed = self.j("resume", rid, "continue", env={"FAKE_WRITE": "a.txt=resumed"})
        self.assertEqual(Path(self.record(resumed["run_id"])["cwd"]), wt)
        self.assertEqual((wt / "a.txt").read_text(encoding="utf-8"), "resumed")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_inside_archive_and_git_cleanup_use_saved_paths(self):
        self.location("inside")
        out, rec, _ = self.completed()
        wt = Path(rec["cwd"])
        self.location("sibling")
        archived = self.j("archive", out["run_id"], "--apply")
        self.assertTrue(archived["applied"])
        self.assertTrue(any(c["argv"][:2] == ["archive", rec["session_id"]] for c in self.calls()))
        self.assertTrue(wt.is_relative_to(self.work / ".ccx" / "worktrees"))
        self.git("worktree", "remove", "--force", str(wt))
        self.assertFalse(wt.exists())
        self.assertNotIn(wt.as_posix(), self.git("worktree", "list", "--porcelain"))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_inside_compact_reports_the_worktree(self):
        self.location("inside")
        out, rec, _ = self.completed()
        self.assertEqual(Path(out["worktree"]), self.work / ".ccx" / "worktrees" / out["run_id"])
        self.assertEqual(out["worktree"], rec["cwd"])

    def test_inside_consumers_keep_the_project_after_location_changes(self):
        from ccx import handoff, ledger, ui
        from ccx.commands.workqueue import _here
        from ccx.workspace import worktree_repo

        self.location("inside")
        out, rec, _ = self.completed()
        wt = Path(rec["cwd"])
        self.location("sibling")
        self.assertEqual(worktree_repo(wt), self.work)
        self.assertTrue(_here(wt, self.work))
        sub = self.work / "sub"
        sub.mkdir()
        self.assertTrue(_here(wt, sub))
        other = self.work.parent / "other"
        other.mkdir()
        self.assertFalse(_here(wt, other))
        self.assertEqual(ui.project_root(str(wt)), self.work)
        self.assertEqual(ledger.check_key("python check.py", str(wt)),
                         ledger.check_key("python check.py", str(self.work)))
        self.assertIn(out["run_id"], [r["run_id"] for r in handoff._recent_runs(Paths(self.hub), self.work)])

    def touch_check(self):
        (self.work / "check.py").write_text(
            'from pathlib import Path\n'
            'assert any(p.read_text(encoding="utf-8") == "touched\\n" for p in Path(".").glob("fake-*.txt"))\n',
            encoding="utf-8")
        self.git("add", "check.py")
        self.git("commit", "-qm", "check the fake builder's output")
        self.env["FAKE_TOUCH"] = "1"

    def test_inside_queue_tracks_commits_and_accepts_worktrees(self):
        self.location("inside")
        self.git("checkout", "-qb", "work")
        self.touch_check()
        ids = [self.j("q", "add", f"piece {i}", "--brief", f"write piece {i}", "--minutes", "5",
                      "--mode", "write", "--to", "codex", "--check", "python check.py")["id"] for i in range(2)]
        after = self.j("q", "add", "after", "--brief", "read the combined result", "--mode", "read",
                       "--to", "codex", "--dep", ids[0], "--dep", ids[1])["id"]
        out = self.j("q", "run", "--from", "claude")
        self.assertEqual({r["id"] for r in out["results"]}, set(ids))
        self.assertEqual(out["waiting"][0]["id"], after)
        for r in out["results"]:
            wt = self.work / ".ccx" / "worktrees" / r["run"]
            self.assertEqual(Path(r["worktree"]), wt)
            self.assertEqual(r["branch"], "ccx/" + r["run"])
            self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), r["commit"])
            self.assertIn(r["run"], self.git("log", "-1", "--format=%s", cwd=wt))
        self.location("sibling")
        accepted = self.j("q", "accept", *ids)
        self.assertEqual({r["id"] for r in accepted["accepted"]}, set(ids))
        items = {it["id"]: it for it in self.j("q", "ls", "--long")["items"]}
        self.assertTrue(all(items[i]["verdict"] is True for i in ids))
        self.assertEqual(len(list(self.work.glob("fake-*.txt"))), 2)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_inside_lane_commits_each_piece_in_the_same_worktree(self):
        self.location("inside")
        self.touch_check()
        plan = self.work / ".ccx" / "plan.json"
        plan.parent.mkdir(exist_ok=True)
        plan.write_text(json.dumps({"tasks": [
            {"id": f"piece-{i}", "to": "codex", "tier": "T1", "mode": "write", "review": "off",
             "worktree": True, "brief": f"write piece {i}", "check": "python check.py", "cwd": str(self.work)}
            for i in range(2)]}), encoding="utf-8")
        out = self.j("batch", str(plan), "--from", "claude", "--lanes", "1")
        res = out["results"]
        self.assertEqual(len(res), 2)
        wt = self.work / ".ccx" / "worktrees" / res[0]["run_id"]
        self.assertEqual({r["worktree"] for r in res}, {str(wt)})
        self.assertEqual(len({r["commit"] for r in res}), 2)
        self.assertEqual([r["warm"] for r in res], [False, True])
        log = self.git("log", "-2", "--format=%s", cwd=wt)
        self.assertTrue(all(r["run_id"] in log for r in res))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_inside_autonomy_merge_recognizes_the_recorded_worktree(self):
        self.location("inside")
        self.git("checkout", "-qb", "work")
        out, rec, _ = self.completed()
        self.location("sibling")
        r = self.ccx("autonomy", "merge", out["run_id"])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)  # L1, no check or review: existing gates still apply
        dry = json.loads(r.stdout)
        self.assertEqual(Path(dry["repo"]), self.work)
        self.assertEqual(dry["into"], "work")
        self.assertIn("a.txt", dry["files"])
        self.assertFalse(dry["merged"])
        self.assertFalse(any("not a --worktree" in why for why in dry["why_not"]))
        self.assertEqual(Path(rec["cwd"]), self.work / ".ccx" / "worktrees" / out["run_id"])
