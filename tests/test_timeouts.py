"""Timeout receipts through external ccx processes with isolated Git repos and fake CLIs."""
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from test_ccx import Env, FAKES
from ccx.timeouts import MESSAGE_CHARS, deadline_prompt, last_assistant_message, timeout_context


class TestTimeouts(Env):
    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.com")
        for name, body in (("a.py", "x = 1\n"), ("delete.txt", "remove me\n"), (".gitignore", ".ccx/\n")):
            (self.work / name).write_text(body, encoding="utf-8")
        self.git("add", "--", "a.py", "delete.txt", ".gitignore")
        self.git("commit", "-qm", "base")
        self.setting("defaults.timeout_sec", "1")
        self.setting("worktree.fetch", "false")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.work, check=True, capture_output=True,
                              text=True, encoding="utf-8").stdout.strip()

    def setting(self, key, value):
        r = self.ccx("config", "set", key, value)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)[key], {"true": True, "false": False}.get(value, int(value) if value.isdigit() else value))

    def timed_run(self, agent="codex", worktree=False, env=None):
        args = ["run", "--from", "user", "--to", agent, "--tier", "T1", "--mode", "write",
                "--review", "off", "--no-escalate", "--no-fallback", "--no-ab"]
        if worktree:
            args.append("--worktree")
        r = self.ccx(*args, "edit a.py", env={f"CCX_{agent.upper()}_BIN": str(FAKES / "fake_timeout.py"),
                                            **(env or {})})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        record = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        return out, record

    def assert_timeout(self, out, record):
        self.assertEqual((out["kind"], out["ok"], out["status"]), ("timeout", False, "error"))
        self.assertEqual(record["attempts"][-1]["kind"], "timeout")
        self.assertIn("timed out after 1s", out["summary"])
        detail = out["timeout_context"]
        self.assertEqual(set(detail["files_changed"]), {"a.py", "delete.txt", "new file.txt"})
        self.assertTrue(detail["last_assistant_message"].startswith("Partial result:"))
        self.assertNotIn("tool output", detail["last_assistant_message"])
        self.assertFalse(detail["last_assistant_message_truncated"])
        self.assertEqual(detail, record["timeout_context"])
        self.assertEqual(detail, record["attempts"][-1]["timeout_context"])
        self.assertEqual(out["files_changed"], [])  # existing field remains the worker's reported files
        self.assertIn("1 new untracked file", out["diffstat"])
        shown = self.ccx("show", out["run_id"])
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["timeout_context"], detail)

    def test_timeout_preserves_partial_work_in_current_checkout(self):
        # The pre-existing dirty file is part of the start snapshot, not attributed to this run.
        (self.work / "preexisting.txt").write_text("keep", encoding="utf-8")
        (self.work / "unrelated.txt").write_text("before", encoding="utf-8")
        self.git("add", "--", "unrelated.txt")
        self.git("commit", "-qm", "unrelated baseline")
        (self.work / "unrelated.txt").write_text("already dirty", encoding="utf-8")
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                # Restore only test-owned files between the two independent runs.
                self.git("restore", "--", "a.py", "delete.txt")
                (self.work / "new file.txt").unlink(missing_ok=True)
                out, record = self.timed_run(agent)
                self.assert_timeout(out, record)
                self.assertEqual((self.work / "a.py").read_text(encoding="utf-8"), "x = 2\n")

    def test_timeout_preserves_partial_work_in_worktree(self):
        self.setting("defaults.timeout_reminder", "true")
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                out, record = self.timed_run(agent, worktree=True)
                wt = Path(out["worktree"]).resolve()
                self.assertTrue(wt.is_relative_to(Path(self.tmp.name).resolve()))
                try:
                    self.assert_timeout(out, record)
                    self.assertEqual((wt / "a.py").read_text(encoding="utf-8"), "x = 2\n")
                    self.assertEqual((self.work / "a.py").read_text(encoding="utf-8"), "x = 1\n")
                    self.assertIn("time limit of 0.0166667 minutes (1 seconds)", self.calls()[-1]["prompt"])
                finally:
                    self.git("worktree", "remove", "--force", str(wt))

    def test_reminder_default_and_configured_limit_apply_to_run_and_resume(self):
        r = self.ccx("config", "get", "defaults.timeout_reminder")
        self.assertEqual(json.loads(r.stdout), {"defaults.timeout_reminder": False})
        self.setting("defaults.timeout_sec", "2400")
        args = ["run", "--from", "user", "--to", "codex", "--tier", "T1", "--mode", "read",
                "--review", "off", "--no-escalate", "--no-fallback", "--no-ab", "read a.py"]
        first = self.ccx(*args)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertNotIn("[ccx time limit]", self.calls()[-1]["prompt"])
        self.assertNotIn("timeout_context", json.loads(first.stdout))
        self.setting("defaults.timeout_reminder", "true")
        resumed = self.ccx("resume", json.loads(first.stdout)["run_id"], "continue")
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertIn("time limit of 40 minutes (2400 seconds)", self.calls()[-1]["prompt"])
        self.assertIn("write a partial result first", self.calls()[-1]["prompt"])

    def test_unavailable_git_evidence_is_unknown(self):
        from ccx.workspace import undo_snapshot
        from ccx.review import changes
        snap = undo_snapshot(self.work)
        snap["base"] = "missing-base-object"
        # Preserve the old review fallback, but timeout recovery must distinguish failure from no changes.
        self.assertEqual(changes(self.work, snap), ([], ""))
        self.assertIsNone(timeout_context("codex", "", snap)["files_changed"])

    def test_timeout_then_success_keeps_evidence_only_in_failed_attempt(self):
        from ccx.delegate import compact
        self.setting("dispatch.cheap_first", "true")
        acceptance = self.work / "test_recovery_acceptance.py"
        acceptance.write_text("from pathlib import Path\ndef test_recovered():\n"
                              "    assert Path('a.py').read_text().strip() == 'x = 2'\n", encoding="utf-8")
        self.git("add", "--", acceptance.name)
        self.git("commit", "-qm", "independent recovery check")
        r = self.ccx("run", "--from", "user", "--to", "codex", "--tier", "T2", "--mode", "write",
                     "--review", "off", "--no-fallback", "--no-ab", "--new", "--check",
                     f'"{sys.executable}" -m pytest -q -p no:cacheprovider {acceptance.name}', "edit a.py",
                     env={"CCX_CODEX_BIN": str(FAKES / "fake_timeout.py"),
                          "FAKE_TIMEOUT_ONCE": str(self.work.parent / "first-timeout"),
                          "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        record = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual([a["kind"] for a in record["attempts"]], ["timeout", "ok"])
        self.assertEqual([a["tier"] for a in record["attempts"]], ["T1", "T2"])
        self.assertTrue(out["ok"], out)
        self.assertNotIn("timeout_context", record)
        self.assertNotIn("timeout_context", out)
        self.assertNotIn("timeout_context", record["attempts"][1])
        detail = record["attempts"][0]["timeout_context"]
        self.assertIn("a.py", detail["files_changed"])
        self.assertTrue(detail["last_assistant_message"].startswith("Partial result:"))
        shown = self.ccx("show", out["run_id"])
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertNotIn("timeout_context", json.loads(shown.stdout))
        # Old receipts can contain a stale top-level field; compact/show must also guard those.
        self.assertNotIn("timeout_context", compact({**record, "timeout_context": detail}))

    def test_large_untracked_file_is_listed_without_reading_its_contents(self):
        from ccx.workspace import undo_snapshot
        (self.work / "before.bin").write_bytes(b"already untracked")
        (self.work / "a.py").write_text("already dirty\n", encoding="utf-8")
        snap = undo_snapshot(self.work)
        large = self.work / "large binary.bin"
        with large.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024)
        original_open = Path.open

        def no_content_reads(path, *args, **kwargs):
            if path.resolve() == large.resolve():
                raise AssertionError("timeout recovery must never open the large untracked file")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", no_content_reads):
            detail = timeout_context("codex", "", snap)
        self.assertEqual(detail["files_changed"], [large.name])

    def test_killed_run_ignores_an_incomplete_final_json_line(self):
        out, record = self.timed_run(env={"FAKE_TIMEOUT_PARTIAL_JSON": "1"})
        self.assert_timeout(out, record)
        events = (self.hub / "ccx" / "runs" / out["run_id"] / "events.0.log").read_text(encoding="utf-8")
        self.assertTrue(events.endswith('{"type":"item.completed","item":'))


@pytest.mark.parametrize("agent,events", [
    ("codex", [{"type": "item.completed", "item": {"type": "agent_message", "text": "old"}},
               {"type": "item.completed", "item": {"type": "assistant_message", "text": "latest"}},
               {"type": "item.completed", "item": {"type": "command_execution", "text": "tool"}}]),
    ("claude", [{"type": "assistant", "message": {"content": [{"type": "text", "text": "latest"},
                                                                   {"type": "thinking", "thinking": "secret"}]}},
                {"type": "user", "message": {"content": "tool"}}]),
    ("gemini", [{"type": "message", "role": "assistant", "content": "latest"},
                {"type": "message", "role": "user", "content": "tool"}]),
    ("dsh", [{"type": "text", "text": "old"}, {"type": "final", "text": "latest"},
             {"type": "error", "message": "tool"}]),
])
def test_last_assistant_event_only(agent, events):
    stream = "\n".join(json.dumps(e) for e in events) + '\n{"incomplete":\n[]\n'
    assert last_assistant_message(agent, stream) == "latest"


def test_missing_evidence_is_unknown_and_long_message_is_bounded():
    assert timeout_context("codex", "", None) == {
        "files_changed": None, "last_assistant_message": None, "last_assistant_message_truncated": False}
    text = "progress " * 1000
    stream = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}})
    detail = timeout_context("codex", stream, None)
    assert detail["last_assistant_message"] == text[-MESSAGE_CHARS:]
    assert detail["last_assistant_message_truncated"] is True
    assert deadline_prompt("task", {}, 1800) == "task"
    assert deadline_prompt("task", {"defaults": {"timeout_reminder": "true"}}, 1800) == "task"


def test_malformed_assistant_content_does_not_break_timeout_receipt():
    stream = json.dumps({"type": "assistant", "message": {"content": 123}})
    assert timeout_context("claude", stream, None)["last_assistant_message"] is None


def test_gemini_deltas_form_the_last_message():
    events = [{"type": "message", "role": "assistant", "content": "earlier"},
              {"type": "message", "role": "user", "content": "next turn"},
              {"type": "message", "role": "assistant", "delta": True, "content": "partial "},
              {"type": "message", "role": "assistant", "delta": True, "content": "result"}]
    assert last_assistant_message("gemini", "\n".join(json.dumps(e) for e in events)) == "partial result"


def test_truncation_keeps_the_partial_result_at_the_end():
    message = "earlier reasoning\n" * 400 + "PARTIAL RESULT: changed a.py; next run the independent checks."
    stream = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": message}})
    detail = timeout_context("codex", stream, None)
    assert detail["last_assistant_message"] == message[-MESSAGE_CHARS:]
    assert detail["last_assistant_message"].endswith("next run the independent checks.")
    assert detail["last_assistant_message_truncated"] is True
