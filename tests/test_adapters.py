"""v0.2 part 5: Gemini adapter, providers (DeepSeek), background runs, live-session send, selftest."""
import json
import os
import time
import unittest
from pathlib import Path

from test_ccx import FAKES, Env

from ccx.runners import parse_gemini


class AdapterEnv(Env):
    def setUp(self):
        super().setUp()
        self.env["CCX_GEMINI_BIN"] = str(FAKES / "fake_gemini.py")

    def j(self, *args, env=None, code=0):
        r = self.ccx(*args, env=env)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def rec(self, run_id):
        return json.loads((self.hub / "ccx" / "runs" / run_id / "run.json").read_text(encoding="utf-8"))


class TestGemini(AdapterEnv):
    def test_run_and_resume(self):
        out = self.j("run", "--from", "claude", "--to", "gemini", "--tier", "T2", "--mode", "read", "review x")
        self.assertEqual((out["agent"], out["status"]), ("gemini", "done"))
        c = self.calls()[-1]
        self.assertEqual(c["argv"][c["argv"].index("-m") + 1], "flash")
        self.assertIn("plan", c["argv"])                       # read-only approval mode
        self.assertIn("JSON schema", c["prompt"])              # schema travels in the prompt
        sid = self.rec(out["run_id"])["session_id"]
        self.assertEqual(sid, c["argv"][c["argv"].index("--session-id") + 1])
        self.assertEqual(out["tokens"]["cached"], 6000)
        self.assertEqual(out["tokens"]["input"], 3000)
        out2 = self.j("resume", out["run_id"], "one more thing")
        c2 = self.calls()[-1]
        self.assertEqual(c2["argv"][c2["argv"].index("--resume") + 1], sid)
        self.assertEqual(out2["agent"], "gemini")

    def test_brief_carries_related_notes(self):
        from ccx import memory
        from ccx.config import Paths
        p = Paths(self.hub)
        rel = memory.add(p, "the parser tests need the fixtures folder", "codex", topic="parser")
        memory.add(p, "billing exports run on Fridays", "claude")
        self.j("run", "--from", "claude", "--to", "gemini", "--tier", "T2", "--mode", "read", "fix the parser tests")
        prompt = self.calls()[-1]["prompt"]
        self.assertIn(f"#{rel['seq']} (parser)", prompt)
        self.assertNotIn("billing", prompt)                          # no shared word, not sent
        self.assertEqual(memory.usage(p)[rel["seq"]]["n"], 1)
        # tools with a start hook too: the hook's delta never reaches a sub-agent, so the brief is the only way in
        for to, frm in (("codex", "claude"), ("claude", "codex")):
            self.j("run", "--from", frm, "--to", to, "--tier", "T2", "--mode", "read", "fix the parser tests")
            prompt = self.calls()[-1]["prompt"]
            self.assertIn(f"#{rel['seq']} (parser): the parser tests need the fixtures folder", prompt, to)
            self.assertNotIn("billing", prompt)
        self.assertEqual(memory.usage(p)[rel["seq"]]["n"], 3)

    def test_escalates_flash_to_pro(self):
        out = self.j("run", "--from", "claude", "--to", "gemini", "--tier", "T2", "x",
                     env={"FAKE_STATUS": "blocked_then_done"})
        self.assertEqual(out["escalated"], "T2 -> T3")
        self.assertEqual(self.calls()[-1]["argv"][self.calls()[-1]["argv"].index("-m") + 1], "pro")

    def test_quota_falls_back(self):
        out = self.j("run", "--from", "user", "--to", "gemini", "--tier", "T2", "x",
                     env={"FAKE_STATUS_GEMINI": "quota"})
        self.assertEqual(out["agent"], "codex")
        self.assertEqual([a["kind"] for a in self.rec(out["run_id"])["attempts"]], ["quota", "ok"])

    def test_routing_sees_installed_gemini(self):
        out = self.j("route", "--to", "gemini", "--b", "3")
        self.assertTrue(out["rung"].startswith("gemini:"))

    def test_parse_gemini(self):
        lines = [{"type": "init", "session_id": "g1"},
                 {"type": "message", "role": "assistant", "content": '{"status": "done", ', "delta": True},
                 {"type": "message", "role": "assistant", "content": '"summary": "ok"}', "delta": True},
                 {"type": "result", "status": "success", "stats": {"input_tokens": 100, "cached": 40,
                                                                    "output_tokens": 5}}]
        oc = parse_gemini("\n".join(json.dumps(x) for x in lines), "", 0)
        self.assertTrue(oc.ok)
        self.assertEqual(oc.session_id, "g1")
        self.assertEqual((oc.usage["input_tokens"], oc.usage["cached_input_tokens"]), (60, 40))


class TestProvider(AdapterEnv):
    def test_deepseek_through_claude(self):
        out = self.j("run", "--from", "codex", "--provider", "deepseek", "--model", "deepseek-v4-pro", "x",
                     env={"DEEPSEEK_API_KEY": "sk-test", "ANTHROPIC_AUTH_TOKEN": "caller-login",
                          "CLAUDE_CODE_OAUTH_TOKEN": "caller-oauth", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH": "1"})
        self.assertEqual(out["agent"], "deepseek")                  # its own agent: own rungs, prices, learning
        c = self.calls()[-1]
        self.assertEqual(c["base_url"], "https://api.deepseek.com/anthropic")
        self.assertEqual(c["api_key"], "sk-test")                   # only the provider's key goes to its server
        self.assertFalse(c["auth_token"])                            # the caller's login is not handed down
        self.assertEqual(c["host_auth"], [])
        self.assertIn("--bare", c["argv"])                           # no OAuth / keychain reads either
        self.assertEqual(c["argv"][c["argv"].index("--model") + 1], "deepseek-v4-pro")
        rec = self.rec(out["run_id"])
        self.assertEqual(rec["provider"], "deepseek")
        self.assertGreater(rec["attempts"][0]["ae_usd"], 0)        # priced from [model_prices]
        self.assertIsNone(rec["attempts"][0]["cost_usd"])           # the CLI's own figure uses Claude prices
        self.assertNotIn("sk-test", json.dumps(rec))                # the key is never stored

    def test_failed_deepseek_escalates_to_claude_without_the_key(self):
        out = self.j("run", "--from", "codex", "--to", "deepseek", "--model", "deepseek-flash", "--effort", "max", "x",
                     env={"DEEPSEEK_API_KEY": "sk-test", "FAKE_BLOCK_MODELS": "deepseek-flash"})   # top of its ladder
        self.assertEqual((out["agent"], out["status"]), ("claude", "done"))
        ds, cl = self.calls()[-2:]
        self.assertEqual((ds["api_key"], "--bare" in ds["argv"]), ("sk-test", True))
        self.assertIsNone(cl["api_key"])                             # Claude runs on the user's own login again
        self.assertNotIn("--bare", cl["argv"])
        self.assertNotIn("--resume", cl["argv"])                     # a fresh session, not DeepSeek's
        self.assertNotEqual(cl["base_url"], "https://api.deepseek.com/anthropic")
        line = json.loads((self.hub / "ccx" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(set(line["ae_by_agent"]), {"deepseek", "claude"})

    def test_daily_cap_stops_deepseek(self):
        led = self.hub / "ccx" / "ledger.jsonl"
        led.parent.mkdir(parents=True, exist_ok=True)
        led.write_text(json.dumps({"run_id": "old", "ts": __import__("time").time(), "to": "deepseek",
                                   "ae_by_agent": {"deepseek": 5.0}}) + "\n", encoding="utf-8")
        r = self.ccx("run", "--from", "codex", "--to", "deepseek", "--model", "deepseek-flash", "x",
                     env={"DEEPSEEK_API_KEY": "sk-test"})
        self.assertEqual(r.returncode, 3)
        self.assertIn("budget", r.stdout)

    def test_missing_key_is_a_clear_error(self):
        r = self.ccx("run", "--from", "codex", "--provider", "deepseek", "x")
        self.assertEqual(r.returncode, 3)
        self.assertIn("DEEPSEEK_API_KEY", r.stdout)


class TestBackgroundAndSend(AdapterEnv):
    def test_bg_run(self):
        out = self.j("run", "--bg", "--from", "claude", "--to", "codex", "--tier", "T2", "long task")
        self.assertEqual(out["state"], "started")
        f = self.hub / "ccx" / "runs" / out["run_id"] / "run.json"
        for _ in range(400):                 # up to 40 s: the detached process starts slowly under full-suite load
            try:
                if f.exists() and json.loads(f.read_text())["state"] == "finished":
                    break
            except (ValueError, OSError):    # caught mid-replace by the run writing it (Windows): look again
                pass
            time.sleep(0.1)
        log = f.parent / "bg.log"
        why = (f.read_text() if f.exists() else "no run.json") + "\n" + (log.read_text() if log.exists() else "no bg.log")
        self.assertTrue(f.exists(), why[-2000:])
        self.assertEqual(json.loads(f.read_text())["state"], "finished", why[-2000:])
        self.assertEqual(self.j("show", out["run_id"])["status"], "done")

    def test_show_while_running_says_running(self):
        from ccx.delegate import compact
        rec = {"run_id": "r", "to": "codex", "tier": "T2", "ok": False, "state": "running", "attempts": [], "cwd": ""}
        self.assertEqual(compact(rec)["status"], "running")                 # not "error" before any result
        self.assertEqual(compact({**rec, "state": "finished"})["status"], "error")

    def test_send_to_codex_session(self):
        d = self.home_codex / "sessions" / "2026" / "10" / "23"
        d.mkdir(parents=True)
        for tid, orig in (("thread-123", "Codex Desktop"), ("sub-456", "codex_exec")):
            (d / f"rollout-x-{tid}.jsonl").write_text(json.dumps(
                {"type": "session_meta", "payload": {"id": tid, "cwd": str(self.work), "originator": orig}}) + "\n",
                encoding="utf-8")
        listed = self.j("send", "--list")["threads"]
        self.assertEqual([t["thread"] for t in listed], ["thread-123"])       # ccx's own sub-agents left out
        self.assertEqual(listed[0]["cwd"], str(self.work))
        self.assertFalse(any(c["argv"][:1] == ["agents"] for c in self.calls()))   # needs a TTY: not used
        out = self.j("send", "--thread", "thread-123", "please also update the docs")
        self.assertTrue(out["ok"])
        c = self.calls()[-1]
        self.assertEqual(c["argv"][:3], ["queue", "--thread", "thread-123"])
        # a person typing in that conversation: the message is held, not pushed in
        import time as _t
        now = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())
        with open(d / "rollout-x-thread-123.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "event_msg", "timestamp": now, "payload": {"type": "user_message"}}) + "\n")
        held = self.j("send", "--thread", "thread-123", "--wait", "0", "later please", code=2)
        self.assertTrue(held["held"])
        self.assertIn("ago", held["why"])
        self.assertTrue(self.j("send", "--thread", "thread-123", "--force", "now")["ok"])

    def test_send_offers_codex_only(self):
        # the choices say what works: a Claude session has no way in for an outside message
        r = self.ccx("send", "--to", "claude", "--thread", "t", "hi")
        self.assertEqual(r.returncode, 2)
        self.assertIn("invalid choice: 'claude'", r.stderr)
        self.assertIn("ccx resume", self.ccx("send", "-h").stdout)
        self.assertFalse(any(c["argv"][:1] == ["queue"] for c in self.calls()))


class TestSelftest(AdapterEnv):
    def test_selftest_all_installed(self):
        out = self.j("selftest")
        agents = {r["agent"] for r in out["selftest"]}
        self.assertEqual(agents, {"codex", "claude", "gemini"})
        self.assertTrue(out["all_ok"])
        self.assertTrue(all(r["session"] for r in out["selftest"]))


class TestHubTools(AdapterEnv):
    def test_skills_find(self):
        out = self.j("skills", "find", "checkpoint", "resume")
        self.assertEqual(out[0]["skill"], "task-checkpoint")

    def test_improve_log(self):
        self.j("improve", "add", "task-split", "h50 too optimistic for refactors", "--fix", "lower prior", "--by", "claude")
        rows = self.j("improve", "list")
        self.assertEqual(rows[0]["target"], "task-split")

    def test_init_stamps_hub_format(self):
        out = self.j("init")
        self.assertTrue(out["migrated"])
        v = json.loads((self.hub / "ccx" / "version.json").read_text())
        self.assertEqual(v["hub_format"], 2)
        self.assertEqual(self.j("init")["migrated"], [])        # idempotent

    def test_init_hub_does_not_replace_the_hub_in_use_without_force(self):
        # a walkthrough's `ccx init --hub <temp>` once moved this machine's hub there without a word
        cfg = Path(self.env["CCX_CONFIG"])
        first, other = self.hub.parent / "hub-a", self.hub.parent / "hub-b"
        own = {"CCX_HUB": ""}                                   # the saved hub decides, as on a real machine
        self.j("init", "--hub", str(first), env=own)
        self.j("init", "--hub", str(first), env=own)            # the same hub again: fine
        before = cfg.read_text(encoding="utf-8")
        r = self.ccx("init", "--hub", str(other), env=own)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["hub_now"], out["asked"]), (str(first.resolve()), str(other.resolve())))
        self.assertIn("--force", out["ask"])
        self.assertEqual(cfg.read_text(encoding="utf-8"), before)   # nothing written
        self.assertFalse(other.exists())
        self.j("init", "--hub", str(other), "--force", env=own)
        self.assertIn(str(other.resolve()), cfg.read_text(encoding="utf-8"))
        self.assertTrue((first / "ccx").is_dir() and (other / "ccx").is_dir())   # the old hub stays where it was

    def test_init_hub_does_not_overwrite_a_config_that_does_not_parse(self):
        cfg = Path(self.env["CCX_CONFIG"])
        cfg.write_text('hub = "D:/hub\n', encoding="utf-8")       # the closing quote is missing: not valid TOML
        new = self.hub.parent / "hub-c"
        r = self.ccx("init", "--hub", str(new), env={"CCX_HUB": ""})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("does not parse", json.loads(r.stdout)["error"])
        self.assertEqual(cfg.read_text(encoding="utf-8"), 'hub = "D:/hub\n')
        self.j("init", "--hub", str(new), "--force", env={"CCX_HUB": ""})
        self.assertIn(str(new.resolve()), cfg.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "nt", "case-insensitive paths")
    def test_init_hub_same_folder_in_other_case_is_the_same_hub(self):
        hub = self.hub.parent / "Hub-D"
        self.j("init", "--hub", str(hub), env={"CCX_HUB": ""})
        self.j("init", "--hub", str(hub).lower(), env={"CCX_HUB": ""})   # no --force needed

    def test_init_does_not_replace_a_different_layout_without_force(self):
        self.j("init", "--snapshot", "AGENTS.md")
        lay = self.hub / "ccx" / "layout.toml"
        before = lay.read_text(encoding="utf-8")
        self.j("init", "--snapshot", "AGENTS.md")               # the same values again: fine
        r = self.ccx("init", "--external-sync", "my-sync")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["layout"], str(lay))
        self.assertEqual(lay.read_text(encoding="utf-8"), before)
        self.j("init", "--external-sync", "my-sync", "--force")
        self.assertIn("my-sync", lay.read_text(encoding="utf-8"))


class TestUndoAskTask(AdapterEnv):
    def git(self, *a):
        import subprocess
        return subprocess.run(["git", *a], cwd=self.work, check=True, capture_output=True, text=True).stdout

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        (self.work / "a.py").write_text("original\n")
        (self.work / "b.txt").write_text("committed\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        (self.work / "b.txt").write_text("my uncommitted edit\n")       # must survive the undo

    def test_undo_restores_and_moves_new_files_aside(self):
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "edit",
                     env={"FAKE_WRITE": "a.py=changed by agent;new.py=created"})
        self.assertEqual((self.work / "a.py").read_text(), "changed by agent")
        dry = self.j("undo", out["run_id"])
        self.assertEqual((dry["restore"], dry["move_aside"], dry["applied"]), (["a.py"], ["new.py"], False))
        self.j("undo", out["run_id"], "--apply")
        self.assertEqual((self.work / "a.py").read_text(), "original\n")
        self.assertEqual((self.work / "b.txt").read_text(), "my uncommitted edit\n")
        self.assertFalse((self.work / "new.py").exists())
        self.assertTrue((self.work / ".ccx" / "undo" / out["run_id"] / "new.py").exists())

    def test_read_run_has_no_undo(self):
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--mode", "read", "look")
        self.assertEqual(self.ccx("undo", out["run_id"]).returncode, 3)

    def test_ask(self):
        out = self.j("ask", "--from", "claude", "is this regex right?")
        self.assertEqual(out["agent"], "codex")
        argv = self.calls()[-1]["argv"]
        self.assertIn('model_reasoning_effort="low"', argv)
        self.assertIn('sandbox_mode="read-only"', argv)

    def checkpoint(self, *args):
        import subprocess, sys
        from test_delegate_v02 import CHECKPOINT
        return subprocess.run([sys.executable, str(CHECKPOINT), *args], cwd=self.work, capture_output=True,
                              text=True, env=self.env).stdout.strip()

    def test_task_resume_after_quota_hands_off(self):
        tid = self.checkpoint("init", "--title", "long job", "--step", "part a", "--step", "part b")
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--no-fallback", "--task", tid,
               "--step", "1", "part a", env={"FAKE_STATUS": "quota"}, code=2)
        out = self.j("task", "resume", tid)
        self.assertEqual(out["handoff"], "codex -> claude (quota)")
        self.assertIn("Resume brief", self.calls()[-1]["prompt"])
        self.j("verify", out["run_id"], "--ok", "1")
        st = self.ccx("task", "status", tid).stdout
        self.assertIn("1/2 steps done", st)

    def test_task_resume_after_the_process_was_killed(self):
        tid = self.checkpoint("init", "--title", "long job", "--step", "part a")
        # what a run killed mid-way leaves behind: a record with its session id, no attempts, no ledger row
        d = self.hub / "ccx" / "runs" / "20261023-000000-dead"
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({
            "run_id": "20261023-000000-dead", "to": "codex", "caller": "claude", "tier": "rung", "mode": "read",
            "cwd": str(self.work), "session_id": "th-killed", "attempts": [], "state": "running", "ok": False,
            "task": tid, "step": 1, "first_rung": "codex:gpt-6-luna:low", "ts": time.time()}), encoding="utf-8")
        out = self.j("task", "resume", tid)
        self.assertEqual(out["resumed"], "20261023-000000-dead")
        argv = self.calls()[-1]["argv"]
        self.assertEqual(argv[:3], ["exec", "resume", "th-killed"])       # same session, not a fresh one
        self.assertIn("gpt-6-luna", argv)                                    # and the model it started on

    def test_task_resume_restarts_a_run_killed_before_its_session(self):
        tid = self.checkpoint("init", "--title", "long job", "--step", "part a")
        # killed after 12 s in a real run: the record is there, but no session id yet and no ledger row
        d = self.hub / "ccx" / "runs" / "20261024-000000-early"
        d.mkdir(parents=True)
        (d / "brief.md").write_text("change x to 2 in a.py", encoding="utf-8")
        (d / "run.json").write_text(json.dumps({
            "run_id": "20261024-000000-early", "to": "codex", "caller": "claude", "tier": "rung", "mode": "write",
            "cwd": str(self.work), "session_id": None, "attempts": [], "state": "running", "ok": False,
            "task": tid, "step": 1, "first_rung": "codex:gpt-6-luna:low", "check_cmd": "python -c pass",
            "ts": time.time()}), encoding="utf-8")
        out = self.j("task", "resume", tid)
        self.assertEqual(out["restarted"], "20261024-000000-early")
        call = self.calls()[-1]
        self.assertNotEqual(call["argv"][:2], ["exec", "resume"])                # a fresh session
        self.assertIn("gpt-6-luna", call["argv"])
        self.assertIn("change x to 2 in a.py", call["prompt"])                   # the person's own brief
        self.assertIn("python -c pass", call["prompt"])                          # and its acceptance command

    def test_explicit_pick_says_whether_it_teaches_routing(self):
        bare = self.j("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                      "--mode", "read", "look at a.py")
        self.assertIn("--minutes", bare["route"]["learns"])
        sized = self.j("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                       "--mode", "read", "--minutes", "5", "--new", "look at a.py")
        self.assertNotIn("learns", sized["route"])
        self.assertIsNotNone(sized["route"]["b"])

    def test_failed_check_escalates_while_a_rung_is_left(self):
        # the check fails the first time it runs and passes after: a sub-agent that wrongly said "done"
        counter = self.work / "check-runs.txt"
        check = ('python -c "import pathlib,sys;f=pathlib.Path(r\'%s\');n=int(f.read_text()) if f.exists() else 0;'
                 'f.write_text(str(n+1));sys.exit(0 if n else 1)"' % counter)
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--review", "off", "--check", check,
                     "fix it")
        self.assertTrue(out["ok"])
        self.assertIn("->", out.get("escalated", ""))                     # climbed one rung
        self.assertEqual(counter.read_text(), "2")                         # once per attempt, not again at the end
        prompts = [c["prompt"] for c in self.calls() if c["agent"] == "codex"]
        self.assertIn("you said done, but", prompts[-1])
        rec = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["attempts"][0]["kind"], "check_failed")
        self.assertIsInstance(rec["attempts"][0]["check_seconds"], (int, float))   # that check's time is kept
        # #392: the passing check keeps its time too, on its own attempt (before, only a failed check did)
        self.assertIsInstance(rec["attempts"][-1]["check_seconds"], (int, float))
        self.assertIn("check_started_at", rec["attempts"][-1])
        self.assertTrue(rec["check"]["passed"])

    def test_failed_check_on_the_last_rung_stays_a_failure(self):
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--no-escalate", "--review", "off",
                     "--check", 'python -c "import sys;sys.exit(1)"', "fix it")
        self.assertEqual(out["kind"], "check_failed")
        self.assertEqual(len([c for c in self.calls() if c["agent"] == "codex"]), 1)

    def test_run_saves_its_brief(self):
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--mode", "read", "look at a.py")
        self.assertEqual((self.hub / "ccx" / "runs" / out["run_id"] / "brief.md").read_text(encoding="utf-8"),
                         "look at a.py")

    def test_task_resume_same_session(self):
        tid = self.checkpoint("init", "--title", "job", "--step", "x")
        first = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--no-escalate", "--task", tid,
                       "--step", "1", "x", env={"FAKE_STATUS": "blocked"})
        out = self.j("task", "resume", tid)
        self.assertEqual(out["resumed"], first["run_id"])
        self.assertEqual(self.calls()[-1]["argv"][:2], ["exec", "resume"])

    def record(self, run_id):
        return json.loads((self.hub / "ccx" / "runs" / run_id / "run.json").read_text(encoding="utf-8"))

    def reviews(self):
        return [c for c in self.calls() if "[ccx review" in c.get("prompt", "")]

    def test_resume_keeps_the_review_setting(self):
        # 2026-10-29: a run started with --review off was resumed with the default (auto) review
        w = {"FAKE_WRITE": "a.py=changed by agent"}
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--review", "off", "edit", env=w)
        res = self.j("resume", out["run_id"], "also this", env=w)
        self.assertEqual((self.record(out["run_id"])["review_mode"], self.record(res["run_id"])["review_mode"]),
                         ("off", "off"))
        self.assertEqual(self.reviews(), [])
        again = self.j("resume", "--review", "auto", res["run_id"], "and that", env=w)   # explicit wins
        self.assertEqual(self.record(again["run_id"])["review_mode"], "auto")

    def test_task_resume_keeps_the_review_setting(self):
        tid = self.checkpoint("init", "--title", "job", "--step", "x")
        first = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--no-escalate", "--review", "off",
                       "--task", tid, "--step", "1", "x", env={"FAKE_STATUS": "blocked"})
        out = self.j("task", "resume", tid, env={"FAKE_WRITE": "a.py=changed by agent"})
        self.assertEqual(out["resumed"], first["run_id"])
        self.assertEqual(self.record(out["run_id"])["review_mode"], "off")
        self.assertEqual(self.reviews(), [])

    def test_task_resume_restart_keeps_the_review_setting(self):
        tid = self.checkpoint("init", "--title", "long job", "--step", "part a")
        d = self.hub / "ccx" / "runs" / "20261024-000000-early"
        d.mkdir(parents=True)
        (d / "brief.md").write_text("change x to 2 in a.py", encoding="utf-8")
        (d / "run.json").write_text(json.dumps({
            "run_id": "20261024-000000-early", "to": "codex", "caller": "claude", "tier": "rung", "mode": "write",
            "cwd": str(self.work), "session_id": None, "attempts": [], "state": "running", "ok": False,
            "task": tid, "step": 1, "first_rung": "codex:gpt-6-luna:low", "review_mode": "off",
            "label": "eval:resume", "ts": time.time()}), encoding="utf-8")
        out = self.j("task", "resume", tid, env={"FAKE_WRITE": "a.py=changed by agent"})
        self.assertEqual(out["restarted"], "20261024-000000-early")
        self.assertEqual(self.record(out["run_id"])["review_mode"], "off")
        self.assertEqual(self.record(out["run_id"])["label"], "eval:resume")      # the same step keeps its label
        self.assertEqual(self.reviews(), [])

    def test_quota_hand_off_keeps_the_label(self):
        tid = self.checkpoint("init", "--title", "long job", "--step", "part a")
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--no-fallback", "--task", tid,
               "--step", "1", "--label", "eval:quota", "part a", env={"FAKE_STATUS": "quota"}, code=2)
        out = self.j("task", "resume", tid)
        self.assertEqual(out["handoff"], "codex -> claude (quota)")
        self.assertEqual(self.record(out["run_id"])["label"], "eval:quota")

    def test_fix_round_of_an_old_record_stores_auto(self):
        # a record from before review_mode was stored: its fix round (forced "on") must not pass "on" to a resume
        import os
        from unittest import mock
        from ccx.config import paths
        from ccx.delegate import Request, run
        d = self.hub / "ccx" / "runs" / "20261020-000000-old"
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({
            "run_id": "20261020-000000-old", "to": "codex", "caller": "claude", "tier": "T2", "mode": "read",
            "cwd": str(self.work), "session_id": "th-old", "attempts": [], "state": "done", "ok": True,
            "ts": time.time()}), encoding="utf-8")
        with mock.patch.dict(os.environ, self.env):
            rec = run(Request(to="codex", brief="fix this", resume_run="20261020-000000-old", caller="claude",
                              review="on", review_round=1), paths())
        self.assertEqual(rec["review_mode"], "auto")

    def test_skills_install_links_repo_skills(self):
        (self.hub / "skills" / "task-split").mkdir(parents=True)          # an older real copy
        dry = self.j("skills", "install", "--replace")
        self.assertFalse(dry["applied"])
        self.assertTrue(all(r["action"].startswith("[dry-run]") for r in dry["skills"]))
        self.assertFalse((self.hub / "skills" / "task-routing").exists())   # nothing changed
        out = self.j("skills", "install", "--apply")
        acts = {r["skill"]: r["action"] for r in out["skills"]}
        self.assertEqual(acts["task-routing"], "linked")
        self.assertIn("kept", acts["task-split"])
        out = self.j("skills", "install", "--replace", "--apply")
        acts = {r["skill"]: r["action"] for r in out["skills"]}
        self.assertEqual(acts["task-routing"], "already linked")
        self.assertIn("backed up", acts["task-split"])
        self.assertTrue((self.hub / "skills" / "task-split" / "SKILL.md").exists())
        self.assertEqual(sorted(d.name for d in (self.hub / "skills").iterdir() if "backup" in d.name), [])
        self.assertEqual(len(list((self.hub / "ccx" / "skill-backups").iterdir())), 1)

    def test_uninstall_removes_hub_links_and_restores_backups(self):
        from ccx.sync import _link
        own = self.hub / "skills" / "task-split"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text("mine", encoding="utf-8")                 # the user's own copy
        self.j("skills", "install", "--replace", "--apply")
        tool = self.home_claude / "skills"
        _link(self.hub / "skills" / "task-split", tool / "task-split")           # as a hub sync would link it
        _link(self.hub / "skills" / "agent-delegate", tool / "agent-delegate")
        r = self.ccx("uninstall", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((own / "SKILL.md").read_text(encoding="utf-8"), "mine")  # backup put back
        self.assertFalse((self.hub / "skills" / "agent-delegate").exists())
        self.assertFalse(os.path.lexists(tool / "agent-delegate"))                # would dangle: removed
        self.assertEqual((tool / "task-split" / "SKILL.md").read_text(encoding="utf-8"), "mine")  # kept


class TestStartupAndHeartbeat(AdapterEnv):
    def argv(self):
        return self.calls()[-1]["argv"]

    def test_claude_slim_start(self):
        self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "x")
        a = self.argv()
        self.assertEqual(a[a.index("--tools") + 1], "Read,Grep,Glob,Edit,Write,Bash,Agent")   # F12: its own sub-agents
        self.assertIn("--exclude-dynamic-system-prompt-sections", a)
        self.assertIn("--strict-mcp-config", a)                  # no MCP tool schemas by default
        self.assertNotIn("--disable-slash-commands", a)          # shared skills stay available
        self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--mode", "read", "--mcp", "x")
        a = self.argv()
        self.assertEqual(a[a.index("--tools") + 1], "Read,Grep,Glob,Bash")
        self.assertNotIn("--strict-mcp-config", a)
        self.j("run", "--from", "codex", "--to", "claude", "--tier", "T1", "x")    # lean tier
        self.assertIn("--disable-slash-commands", self.argv())

    def test_heartbeat_keeps_long_run_alive(self):
        import os, subprocess, sys
        from test_delegate_v02 import CHECKPOINT
        from ccx.config import Paths
        from ccx.delegate import _Heartbeat
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        tid = subprocess.run([sys.executable, str(CHECKPOINT), "init", "--title", "t", "--step", "a"], cwd=self.work,
                             capture_output=True, text=True, env=self.env).stdout.strip()
        lock = self.work / ".ccx" / "tasks" / tid / "lock.json"
        before = json.loads(lock.read_text())["heartbeat"] if lock.exists() else 0
        os.environ["CCX_BEAT_SEC"] = "0.2"
        try:
            hb = _Heartbeat(Paths(self.hub), self.work, tid, "codex")
            deadline = time.time() + 5          # slow CI machines: wait for the beat, don't assume 0.7 s
            while time.time() < deadline:
                time.sleep(0.1)
                if lock.exists() and json.loads(lock.read_text(encoding="utf-8")).get("heartbeat", 0) > before:
                    break
            hb.close()
        finally:
            os.environ.pop("CCX_BEAT_SEC", None)
        after = json.loads(lock.read_text(encoding="utf-8"))
        self.assertGreater(after["heartbeat"], before)
        self.assertEqual(after["agent"], "codex")


class TestPlanGaps(AdapterEnv):
    def test_self_vs_delegate(self):
        big = self.work / "big.log"
        big.write_text("x" * 400000)                     # ~100k tokens you'd carry for 10 more turns
        out = self.j("route", "--b", "4", "--to", "codex", "--lead", "claude:opus:high", "--ctx-files", str(big))
        sv = out["self_vs_delegate"]
        self.assertEqual(sv["ctx_tokens"], 100000)
        self.assertEqual(sv["recommend"], "delegate")
        small = self.j("route", "--b", "4", "--to", "codex", "--lead", "claude:haiku:low")
        self.assertEqual(small["self_vs_delegate"]["recommend"], "self")
        three = self.j("route", "--b", "3", "--lead", "claude:opus:high", "--ctx-tokens", "150000",
                       "--needs", "undo", "--quota", "claude=40")
        c = three["choice"]
        self.assertEqual(c["quota"]["claude"], 0.4)                          # 40 and 0.4 mean the same
        self.assertNotIn("builtin", {o["way"] for o in c["options"]})
        self.assertIn(c["recommend"], ("self", "delegate"))

    def test_skills_exclude(self):
        from ccx.config import Paths
        from ccx.sync import Plan, sync_skills
        (self.hub / "ccx").mkdir(exist_ok=True)
        (self.hub / "ccx" / "layout.toml").write_text('[layout]\nskills_exclude = ["task-split"]\n')
        plan = Plan(apply=False)
        sync_skills(Paths(self.hub), plan)
        text = "\n".join(plan.actions)
        self.assertIn("task-routing", text)
        self.assertNotIn("task-split", text)


if __name__ == "__main__":
    unittest.main()


class TestSetupWizard(AdapterEnv):
    def test_not_on_a_terminal_changes_nothing(self):
        hub = self.hub.parent / "newhub"
        r = self.ccx("setup", "--hub", str(hub), stdin="")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Nothing was changed", r.stdout)
        self.assertFalse(hub.exists())
        self.assertFalse((self.home_claude / "settings.json").exists())

    def test_yes_runs_every_step(self):
        hub = self.hub.parent / "newhub"
        r = self.ccx("setup", "--yes", "--hub", str(hub), env={"CCX_HUB": ""})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n in range(1, 8):                     # STEPS = 7: the counter said [n/6] for seven steps
            self.assertIn(f"[{n}/7]", r.stdout)
        self.assertNotIn("/6]", r.stdout)
        self.assertNotIn("not valid TOML", r.stderr)          # the hub it saved reads back
        self.assertTrue((hub / "ccx").is_dir())
        self.assertIn("mem delta", (self.home_claude / "settings.json").read_text(encoding="utf-8"))
        self.assertIn("ccx:begin hooks", (self.home_codex / "config.toml").read_text(encoding="utf-8"))
        self.assertIn("/hooks", r.stdout)                                     # Codex trust reminder
        self.assertRegex(r.stdout, r"codex\s+ok")                              # selftest ran (fake CLIs)
        self.assertIn("ccx verify", r.stdout)


class TestBuiltinVerdict(AdapterEnv):
    def test_verify_builtin_learns_ability_and_real_cost(self):
        d = self.home_claude / "projects" / "-work" / "sess-1" / "subagents"
        d.mkdir(parents=True)
        (d / "agent-abc.jsonl").write_text(json.dumps({
            "type": "assistant", "isSidechain": True, "sessionId": "sess-1",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600)),   # inside the 7-day window
            "message": {"id": "m1", "model": "claude-haiku-5-5", "usage": {
                "input_tokens": 4, "cache_creation_input_tokens": 58000, "cache_read_input_tokens": 0,
                "output_tokens": 160}}}) + "\n", encoding="utf-8")
        import os
        os.utime(d / "agent-abc.jsonl")                                # recent, so the reader looks at it
        out = self.j("verify", "--builtin", "claude-builtin:haiku:low", "--b", "2", "--ok", "1",
                     "--agent-id", "abc")
        self.assertGreater(out["cost_usd"], 0)
        self.assertAlmostEqual(out["learned"]["theta_now"], 2.5, delta=0.2)   # starts from Haiku, not 5.0
        st = json.loads((self.hub / "ccx" / "routing-state.json").read_text(encoding="utf-8"))
        self.assertIn("claude-builtin:haiku:low", st["cost_factor"])
        r = self.ccx("verify", "--builtin", "claude-builtin:haiku:low", "--ok", "1")
        self.assertEqual(r.returncode, 3)                               # --b is required


class TestModeInference(AdapterEnv):
    def test_infer_mode_examples(self):
        from ccx.modes import infer_mode
        cases = {"fix the parser bug": "write", "Add a test for parse()": "write", "update the docs": "write",
                 "把 foo 改成 bar": "write", "重构数据加载模块": "write", "check the tests and fix what fails": "write",
                 "Review the change in a.py and explain it": "read", "explain the latest update": "read",
                 "分析为什么测试失败": "read", "解释一下这个写法": "read", "给出改进建议": "read",
                 "审查这次提交的改动": "read", "只读：检查配置": "read", "do not modify anything, add notes": "read"}
        for text, want in cases.items():
            self.assertEqual(infer_mode(text)[0], want, text)
        self.assertEqual(infer_mode("hello")[0], "write")                  # unclear: the old default

    def test_run_uses_inferred_mode_and_explicit_wins(self):
        out = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "explain the parser")
        self.assertIn("dontAsk", self.calls()[-1]["argv"])
        rec = self.rec(out["run_id"])
        self.assertEqual((rec["mode"], rec["mode_source"]), ("read", "inferred"))
        self.assertEqual(out["route"]["mode"]["mode"], "read")
        self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--mode", "write", "--new",
               "explain the parser")
        self.assertIn("acceptEdits", self.calls()[-1]["argv"])            # explicit --mode wins
        line = json.loads((self.hub / "ccx" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(line["mode_source"], "explicit")

    def test_route_recommends_mode(self):
        out = self.j("route", "--files", "1", "--coupling", "one", "--clarity", "goal", "--risk", "low",
                     "--novelty", "pattern", "分析", "为什么", "测试失败")
        self.assertEqual((out["mode"]["mode"], out["mode"]["source"]), ("read", "inferred"))

    def test_read_only_run_that_needs_edits_goes_back_to_the_lead(self):
        out = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T1", "--mode", "read", "look at x",
                     env={"FAKE_STATUS": "blocked", "FAKE_SUMMARY": "NEEDS_WRITE: x.py has the bug on line 3"})
        self.assertEqual(out["kind"], "needs_write")
        self.assertIn("--mode write", out["hint"])
        self.assertNotIn("escalated", out)                                # a stronger read-only model won't help
        self.assertIn("NEEDS_WRITE", self.calls()[-1]["prompt"])          # the sub-agent was told how to say so


class TestDifficultyFromMinutes(AdapterEnv):
    def test_minutes_alone_switch_on_routing_and_signals_fill_the_rubric(self):
        (self.work / "pkg").mkdir()
        (self.work / "pkg" / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        (self.work / "lib").mkdir()
        (self.work / "lib" / "b.py").write_text("y = 2\n", encoding="utf-8")
        out = self.j("route", "--minutes", "30", "--clarity", "goal", "--risk", "low", "--novelty", "pattern",
                     "fix", "pkg/a.py", "and", "lib/b.py")
        self.assertEqual(out["objective"]["files_named"], 2)
        self.assertEqual(out["rubric"]["coupling"], "cross")              # two top-level folders
        self.assertIn("minutes", out["difficulty"])
        run = self.j("run", "--from", "codex", "--to", "claude", "--minutes", "8", "rename x in pkg/a.py")
        self.assertEqual(self.rec(run["run_id"])["route"]["difficulty"]["minutes"], 3.0)


class TestQuotaPace(AdapterEnv):
    """Quota by pace: readings since the last reset, the last 48 h's rate projected to the reset."""
    def test_projection_reset_and_too_early(self):
        from ccx.quota import pace
        now, h = 1_800_000_000, 3600
        reset = now + 48 * h
        rs = [{"ts": now - 24 * h, "window": "seven_day", "used": 0.20, "resets_at": reset},
              {"ts": now, "window": "seven_day", "used": 0.40, "resets_at": reset}]
        w = pace(rs, now)["seven_day"]
        self.assertAlmostEqual(w["per_day"], 0.2)
        self.assertAlmostEqual(w["projected"], 0.8)                       # 40% + 2 days x 20%/day
        old = [{"ts": now - 30 * h, "window": "seven_day", "used": 0.9, "resets_at": now - 2 * h}]
        fresh = [{"ts": now - h, "window": "seven_day", "used": 0.05, "resets_at": reset}]
        w = pace(old + fresh, now)["seven_day"]                            # the old window doesn't count
        self.assertEqual((w["used"], w["projected"]), (0.05, 0.05))
        self.assertIn("too early", w["note"])
        dropped = [{"ts": now - 20 * h, "window": "five_hour", "used": 0.9, "resets_at": None},
                   {"ts": now - 10 * h, "window": "five_hour", "used": 0.1, "resets_at": None},
                   {"ts": now, "window": "five_hour", "used": 0.3, "resets_at": None}]
        self.assertEqual(pace(dropped, now)["five_hour"]["used"], 0.3)    # a drop means a new window
        gone = [{"ts": now - 8 * h, "window": "five_hour", "used": 0.7, "resets_at": now - h}]
        self.assertIsNone(pace(gone, now)["five_hour"]["used"])           # reset since the reading

    def test_claude_windows_are_kept_from_a_run(self):
        from ccx import quota
        from ccx.config import paths
        import os
        os.environ["CCX_HUB"] = str(self.hub)
        p = paths()
        import time as _t
        n = quota.save_claude(p, [{"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
            "five_hour": {"utilization": 0.72, "resetsAt": _t.time() + 3600},
            "seven_day": {"utilization": 0.36, "resetsAt": _t.time() + 86400}}}}])
        self.assertEqual(n, 2)
        self.assertEqual({r["window"] for r in quota.claude_readings(p)}, {"five_hour", "seven_day"})
        pr = quota.pressure(p, {"codex": 0.5})
        self.assertEqual(pr["quota"]["codex"], 0.5)                       # given values win
        self.assertEqual(pr["quota"]["claude"], 0.72)                     # tightest window, too early to project

    def test_quota_command(self):
        out = self.j("quota")
        self.assertIn("projected_at_reset", out)


class TestSelfCheck(AdapterEnv):
    def test_the_sub_agent_is_asked_to_check_itself(self):
        self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "fix x")
        self.assertIn("check your own work", self.calls()[-1]["prompt"])

    def test_ccx_runs_the_check_again_and_a_failure_counts(self):
        ok = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--check", "python -c \"print(1)\"",
                    "fix x")
        self.assertIn("python -c", self.calls()[-1]["prompt"])           # the sub-agent was given the command
        self.assertTrue(ok["check"]["passed"])
        bad = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--new",
                     "--check", "python -c \"import sys; sys.exit(3)\"", "fix x")
        self.assertEqual((bad["check"]["exit"], bad["kind"]), (3, "check_failed"))
        self.assertIn("check failed", bad["hint"])


def test_codex_gets_the_windows_shell_note(tmp_path, monkeypatch):
    """Round 5: Codex read a UTF-8 file with plain Get-Content (PowerShell 5.1), saw mojibake and gave up."""
    import os
    from pathlib import Path
    from ccx.agents.codex import WINDOWS_SHELL, codex_invocation
    monkeypatch.setenv("CCX_CODEX_BIN", str(Path(__file__).parent / "fakes" / "fake_codex.py"))   # CI has no codex
    new = codex_invocation(model="m", effort="low", perm=[], cwd=tmp_path, prompt="do x", run_dir=tmp_path)
    again = codex_invocation(model="m", effort="low", perm=[], cwd=tmp_path, prompt="more", run_dir=tmp_path,
                             resume_id="s1")
    assert new.stdin.startswith(WINDOWS_SHELL) == (os.name == "nt")
    assert new.stdin.endswith("do x")
    assert WINDOWS_SHELL not in again.stdin         # the session already has it
    assert again.stdin.endswith("more")
    assert "-Encoding UTF8" in WINDOWS_SHELL


def test_windows_shell_note_matches_powershell_5_1(monkeypatch):
    """Round 5: `python -c` lost its inner quotes, `pytest tests/*.py` found nothing, `&&` and double-quoted rg
    patterns failed. The note must not recommend python -c any more."""
    import ccx.agents.codex as cx
    note = cx.WINDOWS_SHELL
    assert "use `python -c`" not in note and "not `python -c`" in note
    assert "`;`" in note and "`&&` does not work" in note
    assert "does not expand `*`" in note
    assert "temporary .py file" in note and "here-strings" in note
    assert "rg patterns in single quotes" in note
    assert "Get-Content -Encoding UTF8" in note                 # the UTF-8 line stays


def test_codex_exec_note_on_every_system_and_on_resume(tmp_path, monkeypatch):
    """Round 5: 85% of exec_command calls printed only r.output; pytest outlived the 30 s yield, its session_id was
    lost and the same tests were started again. The note goes to fresh exec and exec resume, on any system."""
    from pathlib import Path
    import ccx.agents.codex as cx
    monkeypatch.setenv("CCX_CODEX_BIN", str(Path(__file__).parent / "fakes" / "fake_codex.py"))
    new = cx.codex_invocation(model="m", effort="low", perm=[], cwd=tmp_path, prompt="do x", run_dir=tmp_path)
    again = cx.codex_invocation(model="m", effort="low", perm=[], cwd=tmp_path, prompt="more", run_dir=tmp_path,
                                resume_id="s1")
    for inv, tail in ((new, "do x"), (again, "more")):
        assert cx.EXEC_NOTE in inv.stdin and inv.stdin.endswith(tail)
    assert again.stdin == cx.EXEC_NOTE + "more"          # not tied to the Windows note
    for words in ("text(JSON.stringify(r))", "exit_code", "session_id", "write_stdin({session_id, chars: ''})",
                  "do not start the same command again"):
        assert words in cx.EXEC_NOTE


def test_rules_do_not_forbid_the_sub_agents_a_task_asks_for():
    """Round 5: 'do not delegate to other agents' next to 'you are explicitly asked to use sub-agents' made a Codex
    sub-agent stop with status blocked; the rule is about handing the task on to another CLI."""
    from ccx.prompts import PROMPT
    assert "do not delegate to other agents" not in PROMPT
    assert "your own sub-agents are fine when this task asks for them" in PROMPT


class TestClaudeSessionGone(AdapterEnv):
    def test_errors_reach_run_json_and_resume_says_use_new(self):
        """hub run 20261024-213453-6292: a resume whose session was gone showed only error_during_execution."""
        out = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--mode", "read", "--no-fallback",
                     "look at x")
        r = self.ccx("resume", out["run_id"], "--no-escalate", "one more thing", env={"FAKE_STATUS_CLAUDE": "gone"})
        res = json.loads(r.stdout)
        self.assertFalse(res["ok"], r.stdout)
        self.assertIn("ccx run --new", res.get("hint", ""), r.stdout)
        errs = [x.get("error") or "" for x in self.rec(res["run_id"])["attempts"]]
        self.assertTrue(any("No conversation found with session ID" in e for e in errs), errs)


def test_parse_claude_keeps_errors_list():
    from ccx.agents.claude import parse_claude
    line = json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": "s",
                       "errors": ["No conversation found with session ID: s"]})
    oc = parse_claude(line, "", 1)
    assert not oc.ok
    assert "error_during_execution" in oc.error and "No conversation found with session ID: s" in oc.error
    plain = parse_claude(json.dumps({"type": "result", "subtype": "error", "is_error": True, "result": "boom"}), "", 1)
    assert plain.error == "boom"                       # no errors[]: as before


def test_session_gone_reads_only_the_final_cause():
    from ccx.commands.delegation import _session_gone
    gone = "error_during_execution: No conversation found with session ID: s"
    assert _session_gone({"error": gone, "attempts": [{"error": gone}]})
    assert _session_gone({"error": None, "attempts": [{"error": gone}]})
    # resumed, fell back to a fresh rung, then failed its check: that hint stays, no --new advice
    assert not _session_gone({"error": "check failed", "attempts": [{"error": gone}, {"error": "check failed"}]})
    assert not _session_gone({"error": None, "attempts": [{"error": gone}, {"error": None}]})
