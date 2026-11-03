"""Upstream freshness through ccx run, outside the repo; local bare remotes and fake agents only."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from test_ccx import ROOT
from test_stop import StopEnv, wait_for

from ccx import workspace
from ccx.config import load_config, worktree_fetch, worktree_fetch_timeout
from ccx.runners import group_flags, kill_tree, pid_alive


REAL_RUN = subprocess.run
REAL_POPEN = subprocess.Popen


class TestWorktreeFetch(StopEnv):
    def setUp(self):
        super().setUp()
        self.work = workspace.canonical(self.work)
        self.remote = workspace.canonical(Path(self.tmp.name) / "remote.git")
        self.writer = workspace.canonical(Path(self.tmp.name) / "writer")
        self.launch = workspace.canonical(Path(self.tmp.name) / "outside")
        self.launch.mkdir()
        self.env["CCX_LEAD_VIEW"] = "line"
        self.git("init", "-q", "--bare", "--initial-branch=main", str(self.remote))
        self.git("init", "-q", "--initial-branch=main")
        (self.work / "a.txt").write_text("original\n", encoding="utf-8")
        (self.work / ".gitignore").write_text(".ccx/\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-qu", "origin", "main")
        self.git("clone", "-q", str(self.remote), str(self.writer))

    def tearDown(self):
        for line in self.git("worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                wt = workspace.canonical(line[9:])
                if wt != self.work:
                    self.assertTrue(wt.is_relative_to(workspace.canonical(self.tmp.name)))
                    self.git("worktree", "remove", "--force", str(wt))
        super().tearDown()

    def git(self, *args, cwd=None):
        r = REAL_RUN(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
                     cwd=cwd or self.work, check=True, capture_output=True, text=True, encoding="utf-8")
        return r.stdout.strip()

    def ccx(self, *args, env=None, stdin=None):
        return REAL_RUN([sys.executable, str(ROOT / "ccx.py"), *args], cwd=self.launch,
                        env={**self.env, **(env or {})}, capture_output=True, text=True,
                        input=stdin, encoding="utf-8")

    def setting(self, key, value):
        r = self.ccx("config", "set", "worktree." + key, value)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def completed(self, *flags):
        r = self.ccx("run", "--from", "user", "--to", "codex", "--tier", "T1", "--mode", "write",
                     "--cwd", str(self.work), "--worktree", "--review", "off", "--no-escalate",
                     "--no-fallback", "--no-ab", *flags, "edit a.txt",
                     env={"FAKE_WRITE": "a.txt=changed by agent"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        rec = self.record(out["run_id"])
        self.assertEqual((rec["state"], out["status"]), ("finished", "done"), r.stdout + r.stderr)
        wt = workspace.canonical(self.work.parent / ".ccx-worktrees" / self.work.name / out["run_id"])
        self.assertEqual(workspace.canonical(rec["cwd"]), wt)
        self.assertEqual(workspace.canonical(out["worktree"]), wt)
        return out, rec, r

    def advance(self, commits=1, branch="main"):
        for i in range(commits):
            (self.writer / "upstream.txt").write_text(f"remote {i}\n", encoding="utf-8")
            self.git("add", "upstream.txt", cwd=self.writer)
            self.git("commit", "-qm", f"remote {i}", cwd=self.writer)
        self.git("push", "-q", "origin", branch, cwd=self.writer)

    def test_behind_fetches_before_branching_and_records_in_results_and_full_show(self):
        base = self.git("rev-parse", "HEAD")
        self.advance(2)
        out, rec, r = self.completed()
        warning = ("ccx: warning: main is 2 commit(s) behind origin/main; the worktree starts from the "
                   "local HEAD (git pull first if you want the newer base)")
        self.assertEqual([x for x in r.stderr.splitlines() if x.startswith("ccx: warning:")], [warning])
        self.assertEqual(rec["base_behind"], 2)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=Path(rec["cwd"])), base)
        self.assertEqual(self.git("rev-parse", "HEAD"), base)
        self.assertFalse((Path(rec["cwd"]) / "upstream.txt").exists())
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(out["base_behind"], 2)
        for flags in ((), ("--full",)):
            shown = self.ccx("show", out["run_id"], *flags)
            self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
            data, _ = json.JSONDecoder().raw_decode(shown.stdout)
            self.assertEqual(data["base_behind"], 2)

    def test_up_to_date_records_zero_without_warning(self):
        out, rec, r = self.completed()
        self.assertEqual(rec["base_behind"], 0)
        self.assertEqual(out["base_behind"], 0)
        self.assertNotIn("behind upstream", out["recap"])
        self.assertNotIn("ccx: warning:", r.stderr)

    def test_no_upstream_omits_distance_and_does_not_warn(self):
        self.git("branch", "--unset-upstream")
        out, rec, r = self.completed()
        self.assertNotIn("base_behind", rec)
        self.assertNotIn("base_behind", out)
        self.assertNotIn("ccx: warning:", r.stderr)

    def test_fetch_false_is_settable_and_uses_cached_upstream_without_contacting_remote(self):
        self.assertEqual(self.setting("fetch", "false"), {"worktree.fetch": False})
        self.advance()
        self.git("remote", "set-url", "origin", str(self.remote.parent / "missing.git"))
        _, rec, r = self.completed()
        self.assertEqual(rec["base_behind"], 0)
        self.assertEqual(self.git("rev-parse", "origin/main"), self.git("rev-parse", "HEAD"))
        self.assertNotIn("ccx: warning:", r.stderr)

    def test_fetch_failure_warns_once_and_continues_without_a_distance(self):
        self.advance()
        self.git("remote", "set-url", "origin", str(self.remote.parent / "missing.git"))
        _, rec, r = self.completed()
        warnings = [x for x in r.stderr.splitlines() if x.startswith("ccx: warning:")]
        self.assertEqual(len(warnings), 1, r.stderr)
        self.assertIn("git fetch origin main failed:", warnings[0])
        self.assertIn("continuing from local HEAD", warnings[0])
        self.assertNotIn("base_behind", rec)
        self.assertNotIn("commit(s) behind", r.stderr)
        self.assertTrue((Path(rec["cwd"]) / "a.txt").is_file())

    def test_fetch_uses_upstream_branch_with_slashes_and_ignores_other_remote_branches(self):
        self.git("branch", "-m", "feature/topic", cwd=self.writer)
        self.git("push", "-q", "origin", "feature/topic", cwd=self.writer)
        self.git("fetch", "-q", "origin", "feature/topic")
        self.git("branch", "-m", "local-topic")
        self.git("branch", "--set-upstream-to=origin/feature/topic")
        self.git("branch", "unrelated", cwd=self.writer)
        self.git("push", "-q", "origin", "unrelated", cwd=self.writer)
        self.advance(branch="feature/topic")
        _, rec, r = self.completed()
        self.assertEqual(rec["base_behind"], 1)
        self.assertIn("local-topic is 1 commit(s) behind origin/feature/topic", r.stderr)
        self.assertEqual(self.git("branch", "-r", "--list", "origin/unrelated"), "")

    def test_fetch_false_never_calls_git_fetch(self):
        self.setting("fetch", "false")
        info = {}
        with mock.patch.object(workspace.subprocess, "Popen", wraps=REAL_POPEN) as popen:
            wt = workspace.make_worktree(self.work, "no-fetch", base_info=info)
        self.assertFalse(any(c.args[0][:2] == ["git", "fetch"] for c in popen.call_args_list))
        self.assertEqual(info, {"base_behind": 0})
        self.assertEqual(wt, workspace.canonical(self.work.parent / ".ccx-worktrees" / self.work.name / "no-fetch"))

    def test_timeout_warns_once_and_still_creates_the_worktree(self):
        self.assertEqual(self.setting("fetch_timeout", "2"), {"worktree.fetch_timeout": 2})
        fetches = []
        proc = mock.Mock(pid=12345)
        proc.communicate.side_effect = [subprocess.TimeoutExpired("git fetch", 2), ("", "")]

        def popen(args, *a, **kw):
            if args[:2] == ["git", "fetch"]:
                fetches.append((args, kw))
                return proc
            return REAL_POPEN(args, *a, **kw)

        info = {}
        with mock.patch.object(workspace.subprocess, "Popen", popen), mock.patch("sys.stderr") as err, \
                mock.patch("ccx.runners.kill_tree", return_value=True) as kill:
            wt = workspace.make_worktree(self.work, "timeout", base_info=info)
        self.assertEqual(len(fetches), 1)
        self.assertEqual(fetches[0][0], ["git", "fetch", "--", "origin", "main"])
        self.assertEqual(fetches[0][1]["stdin"], subprocess.DEVNULL)
        for key, value in group_flags().items():
            self.assertEqual(fetches[0][1][key], value)
        kill.assert_called_once_with(proc.pid)
        self.assertEqual(proc.communicate.call_args_list, [mock.call(timeout=2), mock.call(timeout=5)])
        warning = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertEqual(len(warning.splitlines()), 1)
        self.assertIn("timed out after 2s", warning)
        self.assertEqual(info, {})
        self.assertTrue((wt / "a.txt").is_file())

    def test_default_fetch_timeout_and_order(self):
        calls, fetches = [], []

        def popen(args, *a, **kw):
            calls.append(args)
            proc = REAL_POPEN(args, *a, **kw)
            if args[:2] == ["git", "fetch"]:
                proc.communicate = mock.Mock(wraps=proc.communicate)
                fetches.append(proc)
            return proc

        with mock.patch.object(workspace.subprocess, "Popen", popen):
            workspace.make_worktree(self.work, "order")
        fetch = next(i for i, args in enumerate(calls) if args[:2] == ["git", "fetch"])
        add = next(i for i, args in enumerate(calls) if args[:3] == ["git", "worktree", "add"])
        self.assertLess(fetch, add)
        fetches[0].communicate.assert_called_once_with(timeout=15)

    def test_same_named_branch_and_tag_use_the_full_upstream_reference(self):
        self.git("config", "core.warnAmbiguousRefs", "true")
        self.git("tag", "main")
        self.advance(2)
        out, rec, r = self.completed()
        self.assertEqual((rec["base_behind"], out["base_behind"]), (2, 2))
        self.assertIn("main is 2 commit(s) behind origin/main", r.stderr)

    def test_background_wait_and_show_wait_expose_the_behind_base(self):
        (self.work / "test_acceptance.py").write_text(
            "import unittest\nfrom pathlib import Path\n"
            "class Acceptance(unittest.TestCase):\n"
            "    def test_edit(self):\n"
            "        self.assertEqual(Path('a.txt').read_text(encoding='utf-8'), 'changed by agent')\n",
            encoding="utf-8")
        self.git("add", "test_acceptance.py")
        self.git("commit", "-qm", "acceptance check for the fake agent")
        self.advance()
        for flags in ((), ("--check", "python -m unittest test_acceptance")):
            with self.subTest(flags=flags):
                out, rec, _ = self.completed("--bg", "--wait", "30", *flags)
                try:
                    self.assertIn("base_behind", out)
                    self.assertEqual((out["base_behind"], rec["base_behind"]), (1, 1))
                    self.assertIn("base: 1 behind upstream", out["recap"])
                    shown = self.ccx("show", out["run_id"], "--wait", "30")
                    self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
                    data = json.loads(shown.stdout)
                    self.assertEqual(data["base_behind"], 1)
                    self.assertIn("base: 1 behind upstream", data["recap"])
                    if flags:
                        self.assertEqual(out["view"], "line")
                        self.assertEqual(data["view"], "line")
                        self.assertEqual(len(shown.stdout.strip().splitlines()), 1)
                finally:
                    self.reap(out["run_id"])

    @unittest.skipUnless(os.name == "nt", "Windows inherited-pipe timeout regression")
    def test_cli_fetch_timeout_kills_helpers_that_keep_the_pipes_open(self):
        ssh = self.launch / "hang_ssh.py"
        ssh.write_text(
            "import os, subprocess, sys, time\n"
            "from pathlib import Path\n"
            "root = Path(__file__).parent\n"
            "if sys.argv[1:2] == ['child']:\n"
            "    (root / 'child.pid').write_text(str(os.getpid()), encoding='utf-8')\n"
            "else:\n"
            "    (root / 'ssh.pid').write_text(str(os.getpid()), encoding='utf-8')\n"
            "    subprocess.Popen([sys.executable, __file__, 'child'], stdout=sys.stdout, stderr=sys.stderr)\n"
            "time.sleep(120)\n", encoding="utf-8")
        self.git("config", "core.sshCommand", f'"{Path(sys.executable).as_posix()}" "{ssh.as_posix()}"')
        self.git("config", "ssh.variant", "ssh")
        self.git("remote", "set-url", "origin", "ssh://example.invalid/repo.git")
        self.setting("fetch_timeout", "2")
        started = time.monotonic()
        proc = REAL_POPEN([sys.executable, str(ROOT / "ccx.py"), "run", "--from", "user", "--to", "codex",
                           "--tier", "T1", "--mode", "write", "--cwd", str(self.work), "--worktree",
                           "--review", "off", "--no-escalate", "--no-fallback", "--no-ab", "edit a.txt"],
                          cwd=self.launch, env={**self.env, "FAKE_WRITE": "a.txt=changed by agent"},
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                          **group_flags())
        try:
            stdout, stderr = proc.communicate(timeout=20)
            self.assertEqual(proc.returncode, 0, stdout + stderr)
            self.assertLess(time.monotonic() - started, 18)
            self.assertIn("timed out after 2s", stderr)
            self.assertEqual(stderr.count("ccx: warning:"), 1)
            out = json.loads(stdout)
            self.assertNotIn("base_behind", out)
            self.assertNotIn("base_behind", self.record(out["run_id"]))
            for name in ("ssh.pid", "child.pid"):
                f = self.launch / name
                self.assertTrue(f.is_file(), name + " was never started")
                self.assertTrue(wait_for(lambda: not pid_alive(int(f.read_text(encoding="utf-8"))), 5),
                                name + " survived the fetch timeout")
        finally:
            for name in ("ssh.pid", "child.pid"):
                f = self.launch / name
                if f.is_file() and pid_alive(int(f.read_text(encoding="utf-8"))):
                    kill_tree(int(f.read_text(encoding="utf-8")))
            if proc.poll() is None:
                kill_tree(proc.pid)
            proc.communicate(timeout=5)

    def test_configuration_defaults_and_validation(self):
        self.assertTrue(worktree_fetch({}))
        self.assertEqual(worktree_fetch_timeout({}), 15)
        self.assertTrue(worktree_fetch(load_config()))
        self.assertEqual(worktree_fetch_timeout(load_config()), 15)
        for value in ("false", 0, None):
            with self.subTest(fetch=value), self.assertRaisesRegex(ValueError, "worktree.fetch must"):
                worktree_fetch({"worktree": {"fetch": value}})
        for value in (0, -1, True, 1.5, "15", None):
            with self.subTest(timeout=value), self.assertRaisesRegex(ValueError, "positive integer"):
                worktree_fetch_timeout({"worktree": {"fetch_timeout": value}})
        self.setting("fetch_timeout", "3")
        for value in ("0", "-1", "1.5"):
            r = self.ccx("config", "set", "worktree.fetch_timeout", value)
            self.assertNotEqual(r.returncode, 0)
        r = self.ccx("config", "get", "worktree.fetch_timeout")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout), {"worktree.fetch_timeout": 3})
