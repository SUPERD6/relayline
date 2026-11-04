"""Sub-session lifecycle: auto-continue within one lead conversation, fork, one-shot runs, archiving."""
import json
import os
import time
import unittest

from test_adapters import AdapterEnv


class TestContinue(AdapterEnv):
    LEAD = {"CCX_LEAD_SESSION": "lead-1"}

    def argv(self):
        return self.calls()[-1]["argv"]

    def test_next_task_continues_same_sub_session(self):
        a = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "first task", env=self.LEAD)
        b = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "second task", env=self.LEAD)
        self.assertEqual(b["continued_from"], a["run_id"])
        av = self.argv()
        self.assertEqual(av[:2], ["exec", "resume"])
        sid = self.rec(a["run_id"])["session_id"]
        self.assertEqual(av[2], sid)
        self.assertIn("same session", self.calls()[-1]["prompt"])
        self.assertIn("second task", self.calls()[-1]["prompt"])

    def test_new_and_boundaries(self):
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "t1", env=self.LEAD)
        b = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "t2", env=self.LEAD)
        self.assertNotIn("continued_from", b)
        c = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "t3", env={"CCX_LEAD_SESSION": "other"})
        self.assertNotIn("continued_from", c)                         # another conversation
        d = self.j("run", "--from", "claude", "--to", "gemini", "--tier", "T2", "t4", env=self.LEAD)
        self.assertNotIn("continued_from", d)                         # another agent
        e = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "t5")
        self.assertNotIn("continued_from", e)                         # no lead id known

    def test_depth_limit(self):
        ids = [self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", f"t{i}", env=self.LEAD)
               for i in range(6)]
        self.assertNotIn("continued_from", ids[0])
        self.assertTrue(all("continued_from" in x for x in ids[1:5]))
        self.assertNotIn("continued_from", ids[5])                    # fresh after 5 in one session

    def test_quota_breaks_the_chain(self):
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--no-fallback", "t1",
               env={**self.LEAD, "FAKE_STATUS": "quota"}, code=2)
        b = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "t2", env=self.LEAD)
        self.assertNotIn("continued_from", b)

    def test_fork_only_claude_to_claude(self):
        env = {"CLAUDE_CODE_SESSION_ID": "lead-claude-sess"}
        out = self.j("run", "--from", "claude", "--to", "claude", "--tier", "T2", "--fork", "x", env=env)
        av = self.argv()
        self.assertEqual(av[av.index("--resume") + 1], "lead-claude-sess")
        self.assertIn("--fork-session", av)
        self.assertNotIn("--tools", av)
        self.assertNotIn("--disallowed-tools", av)                 # F9: a fork may use its own Agent tool
        self.assertTrue(self.rec(out["run_id"])["forked_from_lead"])
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--fork", "x", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertIn("same tool", r.stdout)


class TestOneShotAndArchive(AdapterEnv):
    def test_ask_and_selftest_leave_no_history(self):
        self.j("ask", "--from", "claude", "--to", "claude", "q")
        self.assertIn("--no-session-persistence", self.calls()[-1]["argv"])
        self.j("ask", "--from", "claude", "--to", "codex", "q")
        self.assertIn("--ephemeral", self.calls()[-1]["argv"])

    def test_archive_codex_and_claude(self):
        a = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "x")
        b = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "y")
        sid = self.rec(b["run_id"])["session_id"]
        tdir = self.home_claude / "projects" / "-work"
        tdir.mkdir(parents=True)
        (tdir / f"{sid}.jsonl").write_text("{}\n")
        dry = self.j("archive")
        self.assertFalse(dry["applied"])
        self.assertTrue((tdir / f"{sid}.jsonl").exists())
        out = self.j("archive", "--apply")
        acts = {r["agent"]: r["action"] for r in out["sessions"]}
        self.assertIn("-> ok", acts["codex"])
        self.assertFalse((tdir / f"{sid}.jsonl").exists())
        self.assertTrue((self.home_claude / "ccx-archive" / "-work" / f"{sid}.jsonl").exists())
        self.assertEqual(self.j("archive")["runs"], 0)               # nothing left to archive
        self.j("archive", "--restore", b["run_id"])
        self.assertTrue((tdir / f"{sid}.jsonl").exists())
        self.assertIn("archive", [c["argv"][0] for c in self.calls()])
        del a

    def test_archive_shared_session_once(self):
        env = {"CCX_LEAD_SESSION": "lead-1"}
        a = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "x", env=env)
        b = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "y", env=env)   # auto-continued
        self.assertEqual(self.rec(a["run_id"])["session_id"], self.rec(b["run_id"])["session_id"])
        out = self.j("archive", "--apply")
        acts = [r["action"] for r in out["sessions"]]
        self.assertEqual(sum("-> ok" in x for x in acts), 1)
        self.assertTrue(any("same session as" in x for x in acts))
        self.assertFalse(any("failed" in x for x in acts))
        self.assertEqual(sum(c["argv"][:1] == ["archive"] for c in self.calls()), 1)

    def test_auto_archive_at_session_start(self):
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "x")
        rows = (self.hub / "ccx" / "ledger.jsonl").read_text().splitlines()
        old = json.loads(rows[-1]); old["ts"] = time.time() - 3 * 3600
        (self.hub / "ccx" / "ledger.jsonl").write_text(json.dumps(old) + "\n")
        r = self.ccx("mem", "delta", "--as", "claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        # The hook schedules archival; a complete journal row signals that the
        # worker has finished the fake CLI call. Retry transient/partial reads.
        import threading
        deadline = time.monotonic() + 60
        pause = 0.01
        while True:
            try:
                text = (self.hub / "ccx" / "archived.jsonl").read_text(encoding="utf-8")
                if text.endswith("\n") and any(json.loads(line).get("run_id") == old["run_id"]
                                               for line in text.splitlines()):
                    break
            except (OSError, ValueError):
                pass
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, "background archival did not finish within 60 seconds")
            threading.Event().wait(min(pause, remaining))
            pause = min(pause * 2, 0.25)
        self.assertTrue((self.hub / "ccx" / "archived.jsonl").exists())
        self.assertEqual(self.calls()[-1]["argv"][0], "archive")


class TestHandoff(AdapterEnv):
    def setUp(self):
        super().setUp()
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)

    def test_claude_hands_off_to_codex(self):
        text = "## Done\n- tasks 1-4: loader, tests, docs\n## Next\n- tasks 5-8"
        out = self.j("handoff", "--by", "claude", "--to", "codex", text, "--next", "task 5", "--next", "task 6")
        self.assertTrue(out["task"])
        first = self.ccx("mem", "delta", "--as", "codex").stdout
        self.assertIn("[ccx handoff to you from claude]", first)
        self.assertIn("tasks 1-4", first)
        self.assertIn("unfinished task", first)                    # the plan for tasks 5-6
        again = self.ccx("mem", "delta", "--as", "codex").stdout
        self.assertNotIn("handoff to you", again)                   # shown once
        self.assertNotIn("handoff to you", self.ccx("mem", "delta", "--as", "claude").stdout)   # not to the sender
        self.assertTrue(list((self.work / ".ccx" / "handoffs").glob("*-claude-to-codex.md")))

    def test_long_handoff_shows_only_what_is_next(self):
        history = "\n".join(f"- step {i}: long description of finished work " * 3 for i in range(40))
        text = (f"## Done\n{history}\n## Next\n- [x] old finished item\n  its detail line\n- [ ] write the parser\n"
                "## Key files\n- ccx/parser.py")
        self.j("handoff", "--by", "claude", "--to", "codex", text)
        first = self.ccx("mem", "delta", "--as", "codex").stdout
        self.assertIn("write the parser", first)
        self.assertIn("ccx/parser.py", first)
        self.assertNotIn("step 3:", first)                          # finished history left in the file
        self.assertNotIn("old finished item", first)
        self.assertNotIn("its detail line", first)
        self.assertRegex(first, r"full handoff is in \.ccx/handoffs/\S+-claude-to-codex\.md")

    def test_parallel_handoffs_are_all_shown(self):
        # two sessions hand over in the same project before the next one starts: neither handoff is lost (seen live,
        # 2026-10-24: the second overwrote the first's .ccx/handoff.md)
        self.j("handoff", "--by", "claude", "--to", "codex", "## Next\n- finish the parser")
        self.j("handoff", "--by", "claude", "--to", "codex", "## Next\n- fix the docs")
        files = sorted((self.work / ".ccx" / "handoffs").glob("*-claude-to-codex*.md"))
        self.assertEqual(len(files), 2)                              # same second: a second file, not overwritten
        first = self.ccx("mem", "delta", "--as", "codex").stdout
        self.assertIn("2 handoffs to you not seen yet", first)
        self.assertIn("fix the docs", first)                         # the newest in full
        self.assertIn("finish the parser", first)                    # the other one listed
        self.assertIn(files[0].name, first)
        self.assertNotIn("handoff", self.ccx("mem", "delta", "--as", "codex").stdout)   # each shown once

    def test_old_seen_format_still_counts(self):
        self.j("handoff", "--by", "claude", "--to", "codex", "## Next\n- old one")
        doc = (self.work / ".ccx" / "handoff.md").read_text(encoding="utf-8")
        ts = doc.split("ts=")[1].split(" ")[0]
        (self.work / ".ccx" / "handoff.seen.json").write_text(json.dumps({"codex": ts}), encoding="utf-8")
        self.assertNotIn("handoff to you", self.ccx("mem", "delta", "--as", "codex").stdout)

    def test_empty_handoff_writes_template(self):
        out = self.j("handoff", "--by", "codex", "--to", "claude")
        self.assertIn("template", out["note"])
        self.assertIn("## Decisions", (self.work / ".ccx" / "handoff.md").read_text())


class TestBuiltinSubagents(AdapterEnv):
    def test_counted_and_compared(self):
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "x")
        d = self.home_claude / "projects" / "-work" / "lead-1" / "subagents"
        d.mkdir(parents=True)
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        msg = {"type": "assistant", "isSidechain": True, "sessionId": "lead-1", "timestamp": ts,
               "message": {"id": "m1", "model": "claude-haiku-5-5",
                           "usage": {"input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 50}}}
        (d / "agent-abc.jsonl").write_text(json.dumps(msg) + "\n")
        self.j("report", "--days", "1")
        s = json.loads((self.hub / "ccx" / "report" / "summary.json").read_text(encoding="utf-8"))
        streams = {(x["agent"], x["role"]): x for x in s["streams"]}
        self.assertEqual(streams[("claude", "builtin")]["events"], 1)
        self.assertEqual(streams[("claude", "lead")]["events"], 0)
        kinds = {c["kind"] for c in s["compare"]}
        self.assertEqual(kinds, {"Claude built-in sub-agent", "ccx → codex"})
        self.assertIn("built-in sub-agents vs ccx", (self.hub / "ccx" / "report" / "index.html").read_text(encoding="utf-8"))


class TestRealWorldFixes(AdapterEnv):
    """Found by the first real two-way test on Windows (2026-10-23)."""
    def test_unsupported_model_is_swapped_and_remembered(self):
        env = {"FAKE_UNSUPPORTED": "gpt-6-luna"}
        out = self.j("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                     "--mode", "read", "x", env=env)
        self.assertTrue(out["ok"])
        rec = self.rec(out["run_id"])
        self.assertEqual(rec["attempts"][0]["kind"], "model")
        self.assertNotIn("gpt-6-luna", rec["attempts"][1]["model"])          # no pointless same-model escalation
        self.assertEqual(rec["attempts"][1]["substituted_for"], "codex:gpt-6-luna:low")
        out2 = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--new", "y", env=env)
        self.assertEqual(len(self.rec(out2["run_id"])["attempts"]), 1)       # known now: swapped before running
        self.assertNotIn("gpt-6-luna", self.calls()[-1]["argv"])
        routed = self.j("route", "--to", "codex", "--b", "1")
        self.assertNotIn("gpt-6-luna", routed.get("rung", ""))
        # the CLI was upgraded: the mark no longer counts and the model is tried again
        out3 = self.j("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                      "--mode", "read", "--new", "z", env={"FAKE_CODEX_VERSION": "codex-cli 0.164.0"})
        self.assertEqual(self.rec(out3["run_id"])["attempts"][0]["model"], "gpt-6-luna")

    def test_doctor_reads_claude_json_login(self):
        r = self.ccx("doctor", env={"FAKE_CLAUDE_AUTH": json.dumps({"loggedIn": False})})
        self.assertIn("not logged in", r.stdout)

    def test_codex_copied_history_not_counted(self):
        from datetime import datetime, timezone
        from ccx.usage import codex_events
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: E731
        now = time.time()
        d = self.home_codex / "sessions" / "x"
        d.mkdir(parents=True)
        tot = lambda i, c, o: {"type": "event_msg", "payload": {"type": "token_count", "info": {  # noqa: E731
            "total_token_usage": {"input_tokens": i, "cached_input_tokens": c, "output_tokens": o}}}}
        lines = [{"timestamp": iso(now - 5), "type": "session_meta", "payload": {"id": "fork-1", "timestamp": iso(now - 5)}},
                 {**tot(90000, 80000, 900), "timestamp": iso(now - 3600)},   # copied from the parent session
                 {**tot(100000, 88000, 1000), "timestamp": iso(now - 2)}]    # this session's own turn
        (d / "rollout-fork-1.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
        ev, _ = codex_events(now - 7200, set(), home=self.home_codex)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["usage"]["cached_input_tokens"], 8000)
        self.assertEqual(ev[0]["usage"]["input_tokens"], 2000)


if __name__ == "__main__":
    unittest.main()


class TestSeats(AdapterEnv):
    def test_a_named_seat_keeps_its_session_and_is_not_archived(self):
        a = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--seat", "reviewer", "review a.py")
        b = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--seat", "reviewer", "review b.py")
        self.assertEqual(b.get("continued_from"), a["run_id"])            # same seat, same session
        c = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--seat", "reviewer", "--new", "x")
        self.assertNotIn("continued_from", c)                              # --new starts it over
        from ccx.archive import finished_runs
        from ccx.config import paths
        import os
        os.environ["CCX_HUB"] = str(self.hub)
        self.assertNotIn(a["run_id"], finished_runs(paths()))              # auto-archive leaves seats alone
