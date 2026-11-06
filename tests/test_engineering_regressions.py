"""Cross-command regressions through ccx subprocesses outside the checkout.

Only fake agent CLIs are used. Socket handshakes test background latency by
causal ordering, rather than asserting a machine-dependent number of seconds.
"""
import json
import socket
import subprocess
import sys

import pytest

from test_ccx import Env, ROOT
from ccx.config import Paths
from ccx import sessionguard


class RegressionEnv(Env):
    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
            cwd=self.work, check=True, capture_output=True)

    def init_source(self):
        self.git("init", "-q")
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "a.py")
        self.git("commit", "-qm", "initial")

    def command(self, *args, env=None):
        result = self.ccx(*args, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def record(self, rid):
        return json.loads((Paths(self.hub).runs / rid / "run.json").read_text(encoding="utf-8"))


class TestOriginalTaskRegression(RegressionEnv):
    def test_user_words_file_reaches_independent_test_reviewer(self):
        self.init_source()
        tiers = Paths(self.hub).user_tiers
        tiers.parent.mkdir(parents=True, exist_ok=True)
        tiers.write_text('[review]\nmode = "tests"\nfix_rounds = 0\n', encoding="utf-8")
        words = "Original words: change x to 2 in a.py and keep the public interface."
        (self.work / "words.txt").write_text(words, encoding="utf-8")
        out = self.command(
            "run", "--from", "claude", "--to", "codex", "--tier", "T1", "--new",
            "--mode", "write", "--review", "on", "--context", "off", "--no-escalate", "--no-fallback",
            "--user-words-file", "words.txt", "change x to 2 in a.py",
            env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n"})
        self.assertEqual(out["review"]["verdict"], "pass")
        self.assertEqual(self.record(out["run_id"])["user_words"], {"source": "file", "chars": len(words)})
        reviewers = [c["prompt"] for c in self.calls() if "[ccx test review]" in c.get("prompt", "")]
        self.assertEqual(len(reviewers), 1)
        self.assertIn(words, reviewers[0])

    def test_both_files_survive_test_review_fix_and_explicit_resume_override(self):
        self.init_source()
        tiers = Paths(self.hub).user_tiers
        tiers.parent.mkdir(parents=True, exist_ok=True)
        tiers.write_text('[review]\nmode = "tests"\nfix_rounds = 1\n', encoding="utf-8")
        original = "Original request: change x to 2 in a.py.\n"
        words = "Keep the public interface. 保留接口。"
        (self.work / "task.txt").write_text(original, encoding="utf-8", newline="")
        (self.work / "words.txt").write_text(words, encoding="utf-8", newline="")
        out = self.command(
            "run", "--from", "claude", "--to", "codex", "--tier", "T1", "--new",
            "--mode", "write", "--review", "on", "--context", "off", "--no-escalate", "--no-fallback",
            "--user-task-file", "task.txt", "--user-words-file", "words.txt", "rewritten worker brief",
            env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 4\n",
                 "FAKE_WRITE_RESUMED": f"{self.work / 'a.py'}=x = 2\n"})
        fixed = self.record(out["run_id"])
        self.assertEqual(fixed["review_round"], 1, out)
        self.assertEqual(fixed["review"]["verdict"], "pass", fixed["review"])
        first = self.record(fixed["resumed_from"])
        for record in (first, fixed):
            self.assertEqual(record["user_task"], original)
            self.assertEqual(record["user_words"], {"source": "file", "chars": len(words)})
        builders = [c for c in self.calls() if c["agent"] == "codex" and c.get("prompt")]
        self.assertEqual(len(builders), 2)
        for call in builders:
            self.assertIn(words, call["prompt"])
        reviewers = [c["prompt"] for c in self.calls() if "[ccx test review]" in c.get("prompt", "")]
        self.assertGreaterEqual(len(reviewers), 2)
        for prompt in reviewers:
            self.assertIn(original, prompt)
            self.assertNotIn("rewritten worker brief", prompt)

        replacement = "Updated request: change x to 3 in a.py.\n"
        (self.work / "task.txt").write_text(replacement, encoding="utf-8", newline="")
        (self.work / "words.txt").write_text("Changed source must not replace saved wording", encoding="utf-8")
        start = len(self.calls())
        resumed = self.command("resume", fixed["run_id"], "finish the task", "--user-task-file", "task.txt",
                               "--review", "on", "--no-escalate",
                               env={"FAKE_WRITE_RESUMED": f"{self.work / 'a.py'}=x = 3\n",
                                    "FAKE_TEST_REVIEW": "no-tests"})
        rec = self.record(resumed["run_id"])
        self.assertEqual(rec["user_task"], replacement)
        self.assertEqual(rec["user_words"], {"source": "file", "chars": len(words)})
        calls = self.calls()[start:]
        self.assertIn(words, next(c["prompt"] for c in calls if c["agent"] == "codex"))
        self.assertIn(replacement, next(c["prompt"] for c in calls if "[ccx test review]" in c["prompt"]))


class TestCoreCommandChain(RegressionEnv):
    def test_run_show_verify_resume_stop_undo_and_generated_ui(self):
        self.init_source()
        started = self.command("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--new",
                               "--mode", "write", "--review", "off", "--no-escalate", "--no-fallback",
                               "change a.py", env={"FAKE_WRITE": "a.py=x = 2\n"})
        rid = started["run_id"]
        shown = self.command("show", rid)
        self.assertEqual((shown["run_id"], shown["status"]), (rid, "done"))
        self.command("verify", rid, "--ok", "1")
        self.assertTrue(self.record(rid)["verdict"]["ok"])
        resumed = self.command("resume", rid, "change x once more", "--review", "off", "--no-escalate",
                               env={"FAKE_WRITE_RESUMED": "a.py=x = 3\n"})
        follow = resumed["run_id"]
        self.assertEqual(self.record(follow)["resumed_from"], rid)
        self.assertEqual(self.record(follow)["session_id"], self.record(rid)["session_id"])
        self.assertEqual((self.work / "a.py").read_text(encoding="utf-8"), "x = 3\n")
        result = self.ccx("stop", follow)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        stopped = json.loads(result.stdout)
        self.assertEqual(stopped["state"], "finished")  # completed runs: safe no-op
        self.assertFalse(stopped["stopped"])
        undone = self.command("undo", follow, "--apply")
        self.assertTrue(undone["applied"])
        self.assertEqual((self.work / "a.py").read_text(encoding="utf-8"), "x = 1\n")
        # Board round-trips, memory and fuzzy project lookup already have real
        # subprocess coverage in test_board, test_ccx and test_projects.
        target = self.work / "snapshot.html"
        result = self.ccx("ui", "--export", str(target))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        html = target.read_text(encoding="utf-8")
        self.assertIn('id="ccx-snapshot"', html)
        self.assertIn(rid, html)


class TestArchiveCompletion(RegressionEnv):
    def test_hook_returns_before_real_archive_and_worker_finishes_after_release(self):
        p = Paths(self.hub)
        p.state.mkdir(parents=True, exist_ok=True)
        rid, sid = "old-finished", "old-session"
        folder = p.runs / rid
        folder.mkdir(parents=True)
        (folder / "run.json").write_text(json.dumps({
            "run_id": rid, "to": "codex", "state": "finished", "sessions": [sid],
            "attempts": [{"agent": "codex", "session_id": sid}]}), encoding="utf-8")
        p.ledger.write_text(json.dumps({"run_id": rid, "ts": 1, "to": "codex", "sessions": [sid],
                                        "usage4": {}, "ae_usd": 0}) + "\n", encoding="utf-8")
        support = self.work / "archive-support"
        support.mkdir()
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            server.settimeout(30)
            # Delay actual archive.auto, then run it unchanged. The final signal
            # is sent only after its journal and fake CLI effects are complete.
            (support / "sitecustomize.py").write_text(
                "import socket, sys\n"
                f"sys.path.insert(0, {str(ROOT)!r})\n"
                "from ccx import archive\n"
                "original = archive.auto\n"
                "def controlled(p):\n"
                f"    with socket.create_connection({server.getsockname()!r}, timeout=30) as s:\n"
                "        s.sendall(b'ready')\n"
                "        if s.recv(1) != b'1': return 0\n"
                "        result = original(p)\n"
                "        s.sendall(b'done')\n"
                "        return result\n"
                "archive.auto = controlled\n", encoding="utf-8")
            child = subprocess.Popen(
                [sys.executable, str(ROOT / "ccx.py"), "mem", "delta", "--as", "codex"],
                cwd=self.work, env={**self.env, "PYTHONPATH": str(support), "CCX_NO_AUTO_ARCHIVE": "0"},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                connection, _ = server.accept()
                with connection, connection.makefile("rb") as signals:
                    connection.settimeout(30)
                    try:
                        self.assertEqual(signals.read(5), b"ready")
                        stdout, stderr = child.communicate(timeout=20)
                        self.assertEqual(child.returncode, 0, (stdout, stderr))
                        self.assertFalse((p.state / "archived.jsonl").exists())
                        self.assertFalse(any(c["argv"][:1] == ["archive"] for c in self.calls()))
                    finally:
                        connection.sendall(b"1")
                    self.assertEqual(signals.read(4), b"done")
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=20)
        # This test deliberately needs the hook to return before releasing its
        # worker, so it cannot use the joining entry point. The 'done' signal
        # precedes archive_worker.run releasing its lock: wait for that release
        # before cleanup can remove a directory the worker is still writing.
        with sessionguard.lock(p, timeout=30):
            pass
        entries = [json.loads(line) for line in (p.state / "archived.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["run_id"] for e in entries], [rid])
        self.assertEqual(entries[0]["sessions"], [["codex", sid, None]])
        self.assertEqual([c["argv"][:2] for c in self.calls() if c["argv"][:1] == ["archive"]],
                         [["archive", sid]])
