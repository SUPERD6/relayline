"""Original wording through real ccx subprocesses, using only the fake agent CLIs."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ccx import Env  # noqa: E402
from ccx import prompts, user_words  # noqa: E402
from ccx.config import Paths, load_config  # noqa: E402


class TestUserWords(Env):
    def start(self, *extra, env=None):
        result = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--new",
                          "--mode", "read", "--review", "off", "--context", "off", "--no-fallback",
                          *extra, "Read the interface", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rid = json.loads(result.stdout)["run_id"]
        folder = Paths(self.hub).runs / rid
        return folder, json.loads((folder / "run.json").read_text(encoding="utf-8"))

    def configure(self, enabled=True, cap=8000):
        f = Paths(self.hub).user_tiers
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"[delegate]\nuser_words = {str(enabled).lower()}\nuser_words_max_chars = {cap}\n",
                     encoding="utf-8")

    def transcript(self, events):
        folder = self.home_claude / "projects" / "fake-project"
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / "lead-words.jsonl"
        f.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
        return f

    def test_default_and_explicit_off_are_byte_identical_to_original_template(self):
        self.assertFalse(load_config(Paths(self.hub))["delegate"]["user_words"])
        for enabled in (None, False):
            if enabled is not None:
                self.configure(enabled)
            folder, record = self.start("--no-escalate")
            mode = ("read-only: read files and run commands that change nothing (your shell tool works), but do not "
                    "modify files. If finishing really needs edits, do not make them: stop "
                    "with status blocked and start the summary with NEEDS_WRITE: what you would change and why")
            expected = prompts.PROMPT.format(run_id=record["run_id"], caller="claude", cwd=self.work.resolve(),
                                             brief="Read the interface", mode_text=mode, selfcheck=prompts.SELFCHECK,
                                             lead_note="", context_line="", memory_line="")
            self.assertEqual((folder / "prompt.md").read_bytes(), expected.replace("\n", os.linesep).encode("utf-8"))
            self.assertNotIn(user_words.HEADER, self.calls()[-1]["prompt"])
            self.assertEqual(record["user_words"], {"source": None, "chars": 0})

    def test_file_overrides_config_and_survives_retry_and_resume(self):
        words = "Return parse_event(value, strict=False) unchanged. 保留接口。"
        f = self.work / "words.txt"
        f.write_text(words, encoding="utf-8")
        folder, record = self.start("--user-words-file", str(f), env={"FAKE_STATUS": "blocked_then_done"})
        calls = [c for c in self.calls() if c.get("prompt")]
        self.assertGreaterEqual(len(calls), 2)
        for call in calls:
            self.assertIn(words, call["prompt"])
            self.assertEqual(call["prompt"].count(user_words.HEADER), 1)
        self.assertEqual(record["user_words"], {"source": "file", "chars": len(words)})
        self.assertNotIn(words, (folder / "run.json").read_text(encoding="utf-8"))
        self.assertNotIn(words, Paths(self.hub).ledger.read_text(encoding="utf-8"))
        snapshot = (folder / "user-words.md").read_bytes()
        f.write_text("Changed after the run", encoding="utf-8")
        self.configure(False, 3)
        result = self.ccx("resume", record["run_id"], "Check again", "--review", "off", "--no-escalate")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(words, self.calls()[-1]["prompt"])
        resumed = Paths(self.hub).runs / json.loads(result.stdout)["run_id"]
        self.assertEqual((resumed / "user-words.md").read_bytes(), snapshot)

    def test_claude_last_real_message_and_missing_source(self):
        self.configure()
        self.transcript([
            user("old message"),
            user("Exact <return>tuple[str, int]</return>\n<pasted_content>omit</pasted_content>"),
            user("hook", isMeta=True), user("side", isSidechain=True),
            user("summary", isCompactSummary=True),
            user("[ccx board] injected"), user("<system-reminder>ignore</system-reminder>"),
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "result"}]}},
        ])
        _, record = self.start("--no-escalate", env={"CLAUDE_CODE_SESSION_ID": "lead-words"})
        prompt = self.calls()[-1]["prompt"]
        self.assertIn("Exact <return>tuple[str, int]</return>", prompt)
        self.assertNotIn("<pasted_content>", prompt)
        self.assertNotIn("old message", prompt)
        self.assertEqual(record["user_words"]["source"], "claude")
        _, missing = self.start("--no-escalate", env={"CLAUDE_CODE_SESSION_ID": "not-present"})
        self.assertEqual(missing["user_words"], {"source": None, "chars": 0})
        self.assertNotIn(user_words.HEADER, self.calls()[-1]["prompt"])

    def test_cap_redaction_and_missing_file_do_not_fail(self):
        self.configure(cap=8)
        f = self.work / "words.txt"
        f.write_text("1234567890", encoding="utf-8")
        _, record = self.start("--no-escalate", "--user-words-file", str(f))
        prompt = self.calls()[-1]["prompt"]
        self.assertIn("12345678\n[User's original words truncated at 8 characters.]", prompt)
        self.assertEqual(record["user_words"]["chars"], 8)
        _, record = self.start("--no-escalate", "--user-words-file", str(self.work / "missing"))
        self.assertEqual(record["user_words"], {"source": None, "chars": 0})

    def test_quota_fallback_keeps_words_on_both_vendors(self):
        f = self.work / "words.txt"
        f.write_text("parse_event must return (kind, value)", encoding="utf-8")
        result = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--new",
                          "--mode", "read", "--review", "off", "--context", "off", "--no-escalate",
                          "--user-words-file", "words.txt", "Read interface",
                          env={"FAKE_STATUS_CODEX": "quota"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [c for c in self.calls() if c.get("prompt")]
        self.assertEqual({c["agent"] for c in calls}, {"codex", "claude"})
        for call in calls:
            self.assertIn("parse_event must return (kind, value)", call["prompt"])
            self.assertEqual(call["prompt"].count(user_words.HEADER), 1)

    def test_config_commands_and_project_locator_without_session_id(self):
        for key, value in (("delegate.user_words", "true"), ("delegate.user_words_max_chars", "100")):
            result = self.ccx("config", "set", key, value)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.work.resolve()))
        folder = self.home_claude / "projects" / slug
        folder.mkdir(parents=True)
        (folder / "lead.jsonl").write_text(json.dumps(user("Return an empty tuple for None")), encoding="utf-8")
        _, record = self.start("--no-escalate")
        self.assertEqual(record["user_words"]["source"], "claude")
        self.assertIn("Return an empty tuple for None", self.calls()[-1]["prompt"])

    def test_cp936_stdio_preserves_utf8_artifacts_retry_resume_and_fallback(self):
        # Force the Python fake CLIs' Windows legacy pipe encoding on every OS,
        # even when the pytest process inherited PYTHONUTF8=1 from its launcher.
        words = "parse_event(value) 必须保留接口并返回元组。"
        legacy = {"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp936:replace"}
        for mode in ("retry", "fallback"):
            with self.subTest(mode=mode):
                start = len(self.calls())
                f = self.work / "words-cp936.txt"
                f.write_text(words, encoding="utf-8")
                result = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--new",
                                  "--mode", "read", "--review", "off", "--context", "off",
                                  "--user-words-file", str(f), "Read interface",
                                  env={**legacy, "FAKE_STATUS_CODEX": "blocked_then_done" if mode == "retry" else "quota"})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                rid = json.loads(result.stdout)["run_id"]
                folder = Paths(self.hub).runs / rid
                # Check product artifacts before the fake CLI's decoded prompt:
                # a decoder failure must not be mistaken for file corruption.
                for name in ("prompt.md", "user-words.md"):
                    self.assertIn(words, (folder / name).read_bytes().decode("utf-8"))
                calls = [c for c in self.calls()[start:] if c.get("prompt")]
                self.assertEqual(len(calls), 2)
                self.assertEqual({c["agent"] for c in calls},
                                 {"codex"} if mode == "retry" else {"codex", "claude"})
                for call in calls:
                    self.assertIn(words, call["prompt"])
                    self.assertEqual(call["prompt"].count(user_words.HEADER), 1)
                if mode == "retry":
                    snapshot = (folder / "user-words.md").read_bytes()
                    f.write_text("Source changed", encoding="utf-8")
                    resumed = self.ccx("resume", rid, "Check again", "--review", "off", "--no-escalate", env=legacy)
                    self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                    resumed_folder = Paths(self.hub).runs / json.loads(resumed.stdout)["run_id"]
                    self.assertEqual((resumed_folder / "user-words.md").read_bytes(), snapshot)
                    self.assertIn(words, self.calls()[-1]["prompt"])


def user(text, **flags):
    return {"type": "user", "message": {"content": text}, **flags}


def test_only_explicit_exclusions_change_words(tmp_path):
    raw = " Keep <api>f(x, y)</api> exactly.\n<pasted_content>private paste</pasted_content>\napi_key=sk-abcdefghijklmnopqrstuv "
    clean = user_words.sanitize(raw)
    assert clean == " Keep <api>f(x, y)</api> exactly.\n\n[redacted] "
    f = tmp_path / "session.jsonl"
    f.write_text(json.dumps(user("<system-reminder>hook</system-reminder>Keep this sentence.\n")), encoding="utf-8")
    assert user_words.latest_claude(f) == "Keep this sentence.\n"


def test_no_source_for_other_lead(tmp_path):
    from ccx.delegate import Request
    for caller, session in (("codex", None), ("codex", "some-session")):
        req = Request(to="codex", brief="brief", caller=caller, lead_session=session)
        assert user_words.capture(req, {"delegate": {"user_words": True}}, Paths(tmp_path), tmp_path, None) == (
            "", {"source": None, "chars": 0})


def test_without_session_id_uses_existing_project_locator(tmp_path, monkeypatch):
    from ccx import context_share
    from ccx.delegate import Request
    f = tmp_path / "current.jsonl"
    f.write_text(json.dumps(user("f(value) must return a tuple")), encoding="utf-8")
    os.utime(f, (100, 100))
    monkeypatch.setattr(user_words.time, "time", lambda: 101)
    seen = []
    monkeypatch.setattr(context_share, "find", lambda *args: seen.append(args) or f)
    monkeypatch.setattr(context_share, "_sub_sessions", lambda p: {"child"})
    req = Request(to="codex", brief="brief", caller="claude", cwd=tmp_path)
    block, meta = user_words.capture(req, {"delegate": {"user_words": True}}, Paths(tmp_path), tmp_path, None)
    assert "f(value) must return a tuple" in block and meta["source"] == "claude"
    assert seen[0][-1] == {"child"}
    monkeypatch.setattr(user_words.time, "time", lambda: 100 + context_share.RECENT_SEC + 1)
    assert user_words.capture(req, {"delegate": {"user_words": True}}, Paths(tmp_path), tmp_path, None)[0] == ""


def test_missing_resume_snapshot_never_recaptures(tmp_path, monkeypatch):
    from ccx import context_share
    from ccx.delegate import Request
    def forbidden(*args):
        raise AssertionError("a resume must not read a new transcript")
    monkeypatch.setattr(context_share, "find", forbidden)
    req = Request(to="codex", brief="brief", caller="claude")
    previous = {"run_id": "gone", "user_words": {"source": "claude", "chars": 20}}
    assert user_words.capture(req, {"delegate": {"user_words": True}}, Paths(tmp_path), tmp_path, previous) == (
        "", {"source": None, "chars": 0})
