"""End-to-end tests with fake codex/claude CLIs. Run: python -m unittest -v"""
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKES = ROOT / "tests" / "fakes"
sys.path.insert(0, str(ROOT))

from ccx import memory, router  # noqa: E402
from ccx.config import Paths, load_config  # noqa: E402
from ccx.sync import TOML_BEGIN, sync_all, upsert_block  # noqa: E402


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.hub, self.home_codex, self.home_claude = t / "hub", t / "codex", t / "claude"
        self.work, self.log = t / "work", t / "calls.jsonl"
        for d in (self.hub, self.home_codex, self.home_claude, self.work):
            d.mkdir()
        self.env = {**os.environ, "CCX_HUB": str(self.hub), "CODEX_HOME": str(self.home_codex),
                    "CLAUDE_CONFIG_DIR": str(self.home_claude), "DSH_HOME": str(t / "dsh"),
                    "CCX_CODEX_BIN": str(FAKES / "fake_codex.py"),
                    "CCX_CLAUDE_BIN": str(FAKES / "fake_claude.py"),
                    "FAKE_LOG": str(self.log), "CCX_AB_RATE": "0", "CCX_NO_BENCH_REFRESH": "1", "CCX_NO_QUOTA_PROBE": "1",
                    "CCX_CONFIG": str(t / "user-config.toml")}       # never the real ~/.ccx/config.toml
        for k in ("CCX_DEPTH", "CCX_ROLE", "FAKE_STATUS", "TASK_SPLIT_HOME", "TASK_ROUTING_HOME",
                  "CHECKPOINT_ROOT", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID",
                  "CCX_LEAD_SESSION", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CCX_LEAD", "DSH_SESSION_ID",
                  "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "CLAUDE_CODE_SIMPLE",
                  "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                  "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "ZAI_API_KEY", "DASHSCOPE_API_KEY", "OPENROUTER_API_KEY"):
            self.env.pop(k, None)          # no real keys or lead identity from the machine running the tests
        for k in [k for k in self.env if k.startswith("CODEX_") and k != "CODEX_HOME"]:
            self.env.pop(k)              # run as CI does: no lead tool around, unless a test sets one
        self._old = dict(os.environ)
        os.environ.update({k: v for k, v in self.env.items() if k.startswith(("CCX_", "CODEX_HOME", "CLAUDE_CONFIG", "DSH_HOME"))})

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old)
        import time
        for i in range(40):
            try:
                self.tmp.cleanup()
                return
            except PermissionError:
                # Windows: a background ccx (--bg) that just finished still holds the work folder as its cwd for a
                # moment; the folder can't go until it has exited
                if i == 39:
                    raise
                time.sleep(0.25)

    def ccx(self, *args, env=None, stdin=None):
        e = {**self.env, **(env or {})}
        r = subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args], cwd=self.work, env=e,
                           capture_output=True, text=True, input=stdin, encoding="utf-8")
        return r

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()]


class TestRouting(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(router.classify("fix typo").tier, "T0")
        self.assertEqual(router.classify("rename the variable foo to bar in utils and reformat the file").tier, "T1")
        self.assertEqual(router.classify("implement a function that parses dates and add tests").tier, "T2")
        self.assertIn(router.classify("refactor the scheduler across modules, intermittent race condition", 6).tier, ("T3", "T4"))
        self.assertEqual(router.classify("security review of the auth and crypto code for production, prove correctness").tier, "T4")
        self.assertEqual(router.classify("重构整个仓库的数据加载模块，性能优化，偶发死锁", 9).tier, "T4")

    def test_config_models(self):
        cfg = load_config(Paths(Path(tempfile.mkdtemp())))
        self.assertEqual(cfg["tiers"]["T2"]["codex"]["model"], "gpt-6.1-sol")
        self.assertFalse(cfg["tiers"]["T0"]["delegate"])


class TestDelegation(Env):
    def test_run_ends_with_a_recap_line(self):
        r = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "write", "--check", "python -c pass",
                     "rename foo to bar in a.py")
        out = json.loads(r.stdout)
        self.assertEqual(list(out)[-1], "recap")                     # last key: still there after `| tail -5`
        rid = out["run_id"]
        self.assertIn(f"ccx run {rid}: status=done ok=true check=passed review=", out["recap"])
        self.assertTrue(out["recap"].endswith(f"next: ccx show {rid}"))
        self.assertIn(rid, "\n".join(r.stdout.splitlines()[-3:]))

    def test_claude_to_codex(self):
        r = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "write",
                     "rename foo to bar in a.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["agent"], out["status"], out["tier"]), ("codex", "done", "T1"))
        # codex reports cached inside input; ccx normalizes to fresh (400) + cached (800)
        self.assertEqual(out["tokens"], {"input": 400, "cache_write": 0, "cached": 800, "output": 150})
        c = self.calls()[-1]
        self.assertIn("gpt-6-luna", c["argv"])
        self.assertIn('model_reasoning_effort="low"', c["argv"])
        self.assertIn('sandbox_mode="workspace-write"', c["argv"])
        self.assertIn("--output-schema", c["argv"])
        self.assertEqual(c["depth"], "1")
        self.assertIn("Do only this task", c["prompt"])
        self.assertNotIn("--disable", c["argv"])                       # its own sub-agents are allowed (F9),
        self.assertFalse(any(x.startswith("agents.") for x in c["argv"]))  # how many and which model: Codex's (F10, F13)

    def test_no_subagents_turns_codex_multi_agent_off(self):
        self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--no-subagents", "x")
        argv = self.calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("--disable") + 1], "multi_agent")
        self.assertIn("multi_agent_v2", argv)
        self.assertIn("do not start sub-agents of your own", self.calls()[-1]["prompt"])

    def test_runaway_sub_agents_are_stopped(self):
        (self.hub / "ccx").mkdir(parents=True, exist_ok=True)
        (self.hub / "ccx" / "tiers.toml").write_text("[subagents]\nmax_usd = 0.5\nwatch_every_sec = 0.3\n",
                                                     encoding="utf-8")
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "x",
                     env={"FAKE_BIG_CHILD": "1", "FAKE_STATUS": "hang"})
        out = json.loads(r.stdout)
        self.assertEqual(out["kind"], "over_budget")
        self.assertIn("cap $0.50", out["hint"])

    def test_lean_codex_keeps_windows_sandbox(self):
        self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "read", "read x")
        self.assertNotIn('windows.sandbox="elevated"', self.calls()[-1]["argv"])       # nothing to keep
        (self.home_codex / "config.toml").write_text('model = "m"\n[windows]\nsandbox = "elevated"\n', encoding="utf-8")
        self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "read", "read x")
        argv = self.calls()[-1]["argv"]
        self.assertIn("--ignore-user-config", argv)
        self.assertIn('windows.sandbox="elevated"', argv)

    def test_codex_to_claude_env_and_flags(self):
        r = self.ccx("run", "--from", "codex", "--tier", "T2", "check the parser",
                     env={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "parent"})
        out = json.loads(r.stdout)
        self.assertEqual(out["agent"], "claude")
        c = self.calls()[-1]
        self.assertIn("sonnet", c["argv"])
        self.assertIn("--json-schema", c["argv"])
        schema = json.loads(c["argv"][c["argv"].index("--json-schema") + 1])
        self.assertEqual(schema["required"], ["status", "summary"])     # a missing optional key is not re-sent
        self.assertIn("open_questions", schema["properties"])
        self.assertIn("dontAsk", c["argv"])          # "check the parser": inferred read-only
        self.assertIn("stream-json", c["argv"])      # session id arrives early
        self.assertIn("--verbose", c["argv"])
        self.assertIsNone(c["env_claudecode"])       # parent session vars stripped

    def test_t1_claude_is_lean(self):
        self.ccx("run", "--from", "codex", "--tier", "T1", "reformat x")
        self.assertIn("--strict-mcp-config", self.calls()[-1]["argv"])

    def test_t0_not_delegated(self):
        r = self.ccx("run", "--from", "claude", "fix typo")
        self.assertFalse(json.loads(r.stdout)["delegated"])
        self.assertEqual(self.calls(), [])

    def test_auto_escalates_in_same_session(self):
        r = self.ccx("run", "--from", "claude", "--tier", "T2", "implement thing",
                     env={"FAKE_STATUS": "blocked_then_done"})
        out = json.loads(r.stdout)
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["escalated"], "T2 -> T3")
        first, second = self.calls()[-2:]
        self.assertEqual(second["argv"][:2], ["exec", "resume"])
        thread = second["argv"][2]
        self.assertTrue(thread)
        self.assertIn('model_reasoning_effort="high"', second["argv"])
        self.assertIn("escalation", second["prompt"])

    def test_sandbox_policy_block_retries_same_rung(self):
        r = self.ccx("run", "--from", "claude", "--tier", "T2", "--mode", "read", "read the readme",
                     env={"FAKE_STATUS": "policy_then_done"})
        out = json.loads(r.stdout)
        self.assertEqual(out["status"], "done")
        self.assertNotIn("escalated", out)
        self.assertEqual(out["policy_blocked"], 1)
        first, second = self.calls()[-2:]
        self.assertEqual(second["argv"][:2], ["exec", "resume"])
        self.assertEqual([a for a in first["argv"] if "effort" in a], [a for a in second["argv"] if "effort" in a])
        self.assertIn("blocked by policy", second["prompt"])
        rec = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual([a["kind"] for a in rec["attempts"]], ["policy", "ok"])

    def test_repeated_policy_block_then_escalates(self):
        out = json.loads(self.ccx("run", "--from", "claude", "--tier", "T2", "--mode", "read", "read the readme",
                                  env={"FAKE_STATUS": "policy"}).stdout)
        self.assertEqual(out["policy_blocked"], 3)     # T2, its one retry, then T3 (the fake always blocks)
        self.assertEqual(out["escalated"], "T2 -> T3")
        self.assertEqual(len(self.calls()), 3)

    def test_lead_session_follows_the_caller(self):
        both = {"CLAUDE_CODE_SESSION_ID": "claude-lead", "CODEX_THREAD_ID": "codex-lead"}   # Codex inside Claude
        for caller, want in (("codex", "codex-lead"), ("claude", "claude-lead")):
            out = json.loads(self.ccx("run", "--from", caller, "--to", "claude" if caller == "codex" else "codex",
                                      "--tier", "T2", "--new", "x", env=both).stdout)
            rec = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(rec["lead_session"], want)

    def test_resumed_codex_usage_counts_only_the_growth(self):
        one = {"input_tokens": 400, "cached_input_tokens": 800, "output_tokens": 150}
        pick = lambda u: {k: u[k] for k in one}                                        # noqa: E731
        out = json.loads(self.ccx("run", "--from", "claude", "--tier", "T2", "implement thing",
                                  env={"FAKE_STATUS": "blocked_then_done"}).stdout)
        rec = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual([pick(a["usage"]) for a in rec["attempts"]], [one, one])     # not 1x then 2x
        self.assertEqual(rec["attempts"][1]["codex_total"], {"input": 2400, "cached": 1600, "output": 300})
        out2 = json.loads(self.ccx("resume", out["run_id"], "also add a docstring").stdout)
        rec2 = json.loads((self.hub / "ccx" / "runs" / out2["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(pick(rec2["attempts"][0]["usage"]), one)                       # not the 3-turn total

    def test_codex_sub_agents_own_children_are_counted(self):
        env = {"FAKE_CHILD": "1", "FAKE_STATUS": "blocked_then_done"}             # 2 attempts, same session
        out = json.loads(self.ccx("run", "--from", "claude", "--tier", "T2", "x", env=env).stdout)
        rec = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        u = [a["usage"] for a in rec["attempts"]]
        # parent 400 fresh + 800 cached each turn; the child adds 400 fresh + 100 cached + 20 out per turn, once
        self.assertEqual([(x["input_tokens"], x["cached_input_tokens"], x["output_tokens"]) for x in u],
                         [(800, 900, 170), (800, 900, 170)])
        self.assertEqual(list(rec["codex_children"].values()), [{"input": 1000, "cached": 200, "output": 40}])
        # the lead's dashboard must not count that child as the lead's own usage
        from ccx.usage import codex_events
        ev, _ = codex_events(0, {rec["session_id"]}, home=self.home_codex)
        self.assertEqual(ev, [])
        ev, _ = codex_events(0, set(), home=self.home_codex)                      # unknown parent: built-in
        self.assertEqual({e["role"] for e in ev}, {"builtin"})

    def test_repair_recounts_records_from_before_the_fix(self):
        out = json.loads(self.ccx("run", "--from", "claude", "--tier", "T2", "implement thing",
                                  env={"FAKE_STATUS": "blocked_then_done"}).stdout)
        f = self.hub / "ccx" / "runs" / out["run_id"] / "run.json"
        rec = json.loads(f.read_text(encoding="utf-8"))
        a = rec["attempts"][1]                       # make it look like the old code wrote it: the running total
        a["usage"].update(input_tokens=800, cached_input_tokens=1600, output_tokens=300)   # 2400 in, 1600 cached
        del a["codex_total"]
        for x in rec["attempts"]:
            x.pop("codex_total", None)
        f.write_text(json.dumps(rec), encoding="utf-8")
        dry = json.loads(self.ccx("repair").stdout)
        self.assertEqual((dry["applied"], dry["runs_fixed"]), (False, 1))
        self.assertNotIn("codex_total", json.loads(f.read_text(encoding="utf-8"))["attempts"][1])   # untouched
        done = json.loads(self.ccx("repair", "--apply").stdout)
        self.assertEqual(done["runs_fixed"], 1)
        u = json.loads(f.read_text(encoding="utf-8"))["attempts"][1]["usage"]
        self.assertEqual((u["input_tokens"], u["cached_input_tokens"], u["output_tokens"]), (400, 800, 150))
        row = [json.loads(l) for l in (self.hub / "ccx" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()][-1]
        self.assertEqual(row["usage4"]["cached_input_tokens"], 1600)                # ledger row rebuilt: 800 + 800
        self.assertEqual(json.loads(self.ccx("repair").stdout)["runs_fixed"], 0)    # idempotent

    def test_auth_failure_not_escalated(self):
        r = self.ccx("run", "--from", "claude", "--tier", "T2", "implement thing",
                     env={"FAKE_STATUS": "auth"})
        out = json.loads(r.stdout)
        self.assertEqual(r.returncode, 2)
        self.assertIn("hint", out)
        self.assertEqual(len(self.calls()), 1)

    def test_resume_follow_up(self):
        out = json.loads(self.ccx("run", "--from", "claude", "--tier", "T2", "implement thing").stdout)
        r = self.ccx("resume", out["run_id"], "also add a docstring")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = self.calls()[-1]
        self.assertEqual(c["argv"][:2], ["exec", "resume"])
        self.assertIn("follow-up", c["prompt"])

    def test_resume_keeps_label_check_and_risk(self):
        # round 5 pilot: a lead's `ccx resume` lost the label and never ran the acceptance command again
        out = json.loads(self.ccx("run", "--from", "claude", "--tier", "T2", "--label", "q:abc", "--risk", "visible",
                                  "--review", "off", "--check", "python -c pass", "implement thing").stdout)
        r = self.ccx("resume", "--review", "off", out["run_id"], "also add a docstring")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res = json.loads(r.stdout)
        rec = json.loads((self.hub / "ccx" / "runs" / res["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual((rec["label"], rec["check_cmd"], rec["risk"]), ("q:abc", "python -c pass", "visible"))
        self.assertTrue(res["check"]["passed"], res)

    def test_resume_refuses_while_its_session_is_busy(self):
        # round 5: the lead's Bash call timed out during ccx's fix round, it resumed the same session meanwhile and
        # Codex refused ("thread already has an active writer"); ccx now says to wait instead of starting a run
        import subprocess
        out = json.loads(self.ccx("run", "--from", "claude", "--tier", "T2", "--review", "off", "implement thing").stdout)
        runs = self.hub / "ccx" / "runs"
        first = json.loads((runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            d = runs / "29991231-235959-fix1"                  # a fix round of it, still checking
            d.mkdir()
            (d / "run.json").write_text(json.dumps({"run_id": d.name, "state": "running", "ccx_pid": alive.pid,
                                                    "session_id": first["session_id"],
                                                    "resumed_from": out["run_id"]}), encoding="utf-8")
            n = len(self.calls())
            r = self.ccx("resume", out["run_id"], "also add a docstring")
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            self.assertIn(f"ccx show {d.name}", json.loads(r.stdout)["error"])
            self.assertEqual(len(self.calls()), n)                   # nothing started
        finally:
            alive.kill()
            alive.wait()
        r = self.ccx("resume", out["run_id"], "also add a docstring")   # its process is gone: resume as usual
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_depth_guard(self):
        r = self.ccx("run", "--from", "codex", "--tier", "T2", "x y z w", env={"CCX_DEPTH": "1"})
        self.assertEqual(r.returncode, 3)
        self.assertIn("refusing", r.stdout)

    def test_context_file_referenced(self):
        self.ccx("ctx", "init")
        self.ccx("run", "--from", "claude", "--tier", "T2", "implement thing")
        self.assertIn(".ccx", self.calls()[-1]["prompt"])

    def test_stats(self):
        self.ccx("run", "--from", "claude", "--tier", "T2", "implement thing")
        r = self.ccx("stats")
        self.assertIn("codex", r.stdout)
        self.assertIn("T2", r.stdout)

    def test_batch(self):
        plan = {"tasks": [
            {"id": "a", "to": "codex", "tier": "T1", "brief": "reformat a.py"},
            {"id": "b", "to": "claude", "tier": "T2", "brief": "review b.py"},
            {"id": "c", "brief": "fix typo"}]}
        f = self.work / "plan.json"
        f.write_text(json.dumps(plan))
        out = json.loads(self.ccx("batch", str(f), "--from", "claude").stdout)
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual([d["id"] for d in out["do_yourself"]], ["c"])

    def test_batch_passes_review_and_risk(self):
        # a plan can turn review off (or on) per task, as `ccx run --review` does
        import argparse
        from unittest import mock
        from ccx.commands import delegation
        plan = {"tasks": [{"id": "a", "to": "codex", "tier": "T1", "brief": "fix a.py", "review": "off"},
                          {"id": "b", "to": "codex", "tier": "T1", "brief": "fix b.py", "risk": "visible"}]}
        f = self.work / "plan.json"
        f.write_text(json.dumps(plan))
        seen = []
        fake = {"run_id": "r", "ok": True}
        with mock.patch.dict(os.environ, {"CCX_HUB": str(self.hub)}), \
                mock.patch.object(delegation, "run", side_effect=lambda r, p: seen.append(r) or fake), \
                mock.patch.object(delegation, "compact", side_effect=lambda rec: rec), \
                mock.patch.object(delegation, "_out"):
            delegation.cmd_batch(argparse.Namespace(plan=str(f), caller="claude"))
        got = {r.label: (r.review, r.risk) for r in seen}
        self.assertEqual(got, {"a": ("off", None), "b": ("auto", "visible")})


class TestMemory(Env):
    def P(self):
        return Paths(self.hub)

    def test_incremental_delta(self):
        p = self.P()
        memory.ensure(p)
        # both sides start: nothing new
        self.assertEqual(memory.delta(p, "codex"), [])
        self.assertEqual(memory.delta(p, "claude"), [])
        memory.add(p, "user prefers plain Chinese", by="claude")       # "+2"
        new = memory.delta(p, "codex")
        self.assertEqual([e["text"] for e in new], ["user prefers plain Chinese"])
        self.assertEqual(memory.delta(p, "codex"), [])                 # not re-read
        self.assertEqual(memory.delta(p, "claude"), [])                # own entry not echoed
        memory.add(p, "datasets live in ~/data", by="codex")
        self.assertEqual(len(memory.delta(p, "claude")), 1)

    def test_compact_folds_and_moves_cursor(self):
        p = self.P()
        memory.ensure(p)
        memory.add(p, "fact one", by="claude", topic="prefs")
        memory.add(p, "fact two", by="codex", topic="paths")
        res = memory.compact(p)
        self.assertEqual(res["folded"], 2)
        snap = p.memory_index.read_text(encoding="utf-8")
        self.assertIn("fact one", snap)
        self.assertIn("### paths", snap)
        self.assertEqual(memory.snapshot_seq(p), 2)
        self.assertEqual(memory.entries(p), [])
        # a side that never read the delta gets nothing now: it's in the snapshot
        self.assertEqual(memory.delta(p, "codex"), [])
        memory.add(p, "fact three", by="claude")
        self.assertEqual(memory.add(p, "fact three", by="claude")["duplicate"], True)
        self.assertEqual([e["seq"] for e in memory.delta(p, "codex")], [3])

    def test_cli_delta_silent_when_empty_and_for_subagents(self):
        self.ccx("init")
        self.assertEqual(self.ccx("mem", "delta", "--as", "codex").stdout, "")
        self.ccx("mem", "add", "hello", "world", "--by", "claude")
        r = self.ccx("mem", "delta", "--as", "codex", env={"CCX_ROLE": "subagent"})
        self.assertEqual(r.stdout, "")
        r = self.ccx("mem", "delta", "--as", "codex")
        self.assertIn("hello world", r.stdout)
        self.assertEqual(self.ccx("mem", "delta", "--as", "codex").stdout, "")


class TestSync(Env):
    def test_dry_run_changes_nothing_then_apply(self):
        (self.home_codex / "config.toml").write_text(
            'model = "gpt-6-astra"\n[hooks.state]\n\n[mcp_servers.docs-search]\ncommand = "node"\nargs = ["docs.mjs", "mcp"]\n'
            '[mcp_servers.node_repl]\ncommand = "node_repl.exe"\n', encoding="utf-8")
        (self.home_codex / "AGENTS.md").write_text("# my rules\n", encoding="utf-8")
        sk = self.home_codex / "skills" / "python-patterns"
        sk.mkdir(parents=True)
        (sk / "SKILL.md").write_text("---\nname: python-patterns\ndescription: x\n---\n")
        (self.home_codex / "skills" / ".system").mkdir()
        p = Paths(self.hub)
        before = (self.home_codex / "config.toml").read_text()
        plan = sync_all(p, apply=False, parts=["skills", "memory", "hooks", "mcp"])
        self.assertTrue(plan.actions)
        self.assertEqual((self.home_codex / "config.toml").read_text(), before)
        self.assertFalse((self.home_claude / "skills").exists())

        plan = sync_all(p, apply=True, parts=["skills", "memory", "hooks", "mcp"])
        # skills: codex skill visible in claude, bridge skill visible in both, .system skipped
        self.assertTrue((self.home_claude / "skills" / "python-patterns" / "SKILL.md").exists())
        self.assertTrue((self.home_claude / "skills" / "agent-delegate" / "SKILL.md").exists())
        self.assertTrue((self.home_codex / "skills" / "agent-delegate" / "SKILL.md").exists())
        self.assertFalse((self.home_claude / "skills" / ".system").exists())
        # memory blocks
        self.assertIn("@", (self.home_claude / "CLAUDE.md").read_text(encoding="utf-8"))
        agents = (self.home_codex / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(agents.startswith("# my rules"))
        self.assertIn("Shared memory", agents)
        self.assertIn(p.memory_index.as_posix(), agents)                 # names the hub original (I6)
        from ccx.sync import memory_targets
        self.assertEqual({a for a, _ in memory_targets()}, {"claude", "codex"})   # leads only: not gemini
        # hooks
        st = json.loads((self.home_claude / "settings.json").read_text(encoding="utf-8"))
        self.assertIn("mem delta --as claude", st["hooks"]["SessionStart"][0]["hooks"][0]["command"])
        self.assertIn("turn --as claude", st["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"])
        conf = (self.home_codex / "config.toml").read_text(encoding="utf-8")
        self.assertIn(TOML_BEGIN, conf)
        parsed = tomllib.loads(conf)
        self.assertIn("mem delta --as codex", parsed["hooks"]["SessionStart"][0]["hooks"][0]["command"])
        self.assertIn("turn --as codex", parsed["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"])
        self.assertEqual(parsed["model"], "gpt-6-astra")
        # backups made
        self.assertTrue(list(self.home_codex.glob("config.toml.ccx-backup-*")))
        # mcp: portable server imported, node_repl excluded
        reg = json.loads(p.mcp_registry.read_text(encoding="utf-8"))
        self.assertIn("docs-search", reg["servers"])
        self.assertNotIn("node_repl", reg["servers"])
        # idempotent
        again = sync_all(p, apply=True, parts=["skills", "memory", "hooks"])
        self.assertEqual(again.actions, [])

    def test_codex_hooks_use_the_call_operator_on_windows(self):
        """H7: Codex runs hook commands through PowerShell on Windows; a quoted path first is a string, not a call."""
        from ccx.sync import TOML_END, codex_hook_command, codex_hook_needs_call_operator, ccx_command
        self.assertEqual(codex_hook_command("mem", "delta", windows=True), "& " + ccx_command("mem", "delta"))
        self.assertEqual(codex_hook_command("mem", "delta", windows=False), ccx_command("mem", "delta"))
        old = f"x = 1\n{TOML_BEGIN}\ncommand = '{ccx_command('mem', 'delta')}'\n{TOML_END}\n"
        self.assertTrue(codex_hook_needs_call_operator(old))
        self.assertFalse(codex_hook_needs_call_operator(old.replace("command = '", "command = '& ")))
        self.assertFalse(codex_hook_needs_call_operator("command = '\"x\" y'\n"))       # not ccx's block
        ct = self.home_codex / "config.toml"
        ct.write_text(old, encoding="utf-8")                                             # a block from before the fix
        sync_all(Paths(self.hub), apply=True, parts=["hooks"])
        conf = tomllib.loads(ct.read_text(encoding="utf-8"))
        for ev in ("SessionStart", "UserPromptSubmit"):
            self.assertEqual(conf["hooks"][ev][0]["hooks"][0]["command"].startswith("& "), os.name == "nt", ev)
        # elsewhere the quoted path stays (no PowerShell), which is why doctor only checks this on Windows
        self.assertEqual(codex_hook_needs_call_operator(ct.read_text(encoding="utf-8")), os.name != "nt")
        ct.write_text(old, encoding="utf-8")
        line = next(x for x in self.ccx("doctor").stdout.splitlines() if x.startswith("Codex SessionStart hook"))
        self.assertIn("WARN" if os.name == "nt" else "ok", line)

    def test_codex_hook_output_does_not_start_with_a_bracket(self):
        """H7: Codex reads hook output starting with '[' or '{' as JSON and drops the hook when it isn't."""
        memory.add(Paths(self.hub), "the parser tests need the fixtures folder", "claude")
        cx = self.ccx("mem", "delta", "--as", "codex", "--peek").stdout
        self.assertIn("[ccx shared memory", cx)
        self.assertNotIn(cx.lstrip()[:1], ("[", "{"))
        memory.add(Paths(self.hub), "billing exports run on Fridays", "codex")
        self.assertTrue(self.ccx("mem", "delta", "--as", "claude", "--peek").stdout.startswith("[ccx"))   # unchanged
        from ccx.commands.common import hook_text
        self.assertEqual(hook_text("plain text", "codex"), "plain text")
        self.assertEqual(hook_text("[x]", "claude"), "[x]")

    def test_upsert_block(self):
        t = upsert_block("a\n", "x", "one")
        t2 = upsert_block(t, "x", "two")
        self.assertEqual(t2.count("ccx:begin x"), 1)
        self.assertIn("two", t2)
        self.assertNotIn("one", t2)


class TestExternalLayout(Env):
    """A hub that already has its own shared AGENTS.md + sync script (an existing personal setup)."""

    def setUp(self):
        super().setUp()
        (self.hub / "AGENTS.md").write_text("# shared rules\n- be concise\n", encoding="utf-8")
        # Codex reads the very same file through a hard link; Claude imports it with one line
        os.link(self.hub / "AGENTS.md", self.home_codex / "AGENTS.md")
        (self.home_claude / "CLAUDE.md").write_text("@" + (self.hub / "AGENTS.md").as_posix(), encoding="utf-8")
        (self.hub / "mcp").mkdir()
        (self.hub / "mcp" / "servers.json").write_text(json.dumps(
            {"version": 1, "mcpServers": {"rea": {"command": "node", "args": ["rea.mjs"]}}}))
        marker = self.hub / "synced.txt"
        r = self.ccx("init", "--snapshot", "AGENTS.md", "--external-sync",
                     f'"{sys.executable}" -c "open(r\'{marker}\',\'w\').write(\'ok\')"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.marker = marker

    def test_no_blocks_written_and_external_sync_used(self):
        r = self.ccx("sync", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("is external", r.stdout)
        self.assertEqual((self.home_claude / "CLAUDE.md").read_text(encoding="utf-8"),
                         "@" + (self.hub / "AGENTS.md").as_posix())          # untouched: still exactly one line
        self.assertNotIn("ccx:begin", (self.hub / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertTrue(self.marker.exists(), "external sync should have run instead of ccx's own linking")
        self.assertFalse((self.home_claude / "skills" / "agent-delegate").exists())

    def test_compact_writes_notes_in_place_and_keeps_hard_link(self):
        self.ccx("mem", "add", "prefers plain Chinese", "--by", "claude", "--topic", "prefs")
        r = self.ccx("mem", "delta", "--as", "codex")
        self.assertIn("prefers plain Chinese", r.stdout)
        r = self.ccx("mem", "compact")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        shared = (self.hub / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(shared.startswith("# shared rules"))
        self.assertIn("ccx:notes begin seq=1", shared)
        self.assertIn("- prefers plain Chinese", shared)
        self.assertTrue(os.path.samefile(self.hub / "AGENTS.md", self.home_codex / "AGENTS.md"),
                        "hard link to Codex's AGENTS.md must survive")
        # a second compact merges, doesn't duplicate the section
        self.ccx("mem", "add", "uses Windows", "--by", "codex", "--topic", "env")
        self.ccx("mem", "compact")
        shared = (self.hub / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(shared.count("ccx:notes begin"), 1)
        self.assertIn("seq=2", shared)
        self.assertIn("### env", shared)

    def test_registry_reads_mcpServers_format(self):
        from ccx.sync import load_registry
        reg = load_registry(Paths(self.hub))
        self.assertEqual(reg["_format"], "mcpServers")
        self.assertIn("rea", reg["servers"])


class TestUninstall(Env):
    def test_uninstall_removes_only_what_ccx_added(self):
        (self.home_codex / "config.toml").write_text('model = "x"\n', encoding="utf-8")
        (self.home_claude / "settings.json").write_text(json.dumps({"language": "zh"}), encoding="utf-8")
        (self.home_claude / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
        p = Paths(self.hub)
        sync_all(p, apply=True, parts=["skills", "memory", "hooks"])
        self.assertTrue((self.home_claude / "skills" / "agent-delegate").exists())
        r = self.ccx("uninstall")
        self.assertIn("dry run", r.stdout)
        self.assertTrue((self.home_claude / "skills" / "agent-delegate").exists())
        r = self.ccx("uninstall", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.home_claude / "skills" / "agent-delegate").exists())
        self.assertEqual(json.loads((self.home_claude / "settings.json").read_text(encoding="utf-8")),
                         {"language": "zh"})
        self.assertNotIn("ccx", (self.home_codex / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual((self.home_claude / "CLAUDE.md").read_text(encoding="utf-8").strip(), "# mine")
        self.assertIn("ccx skills install --replace --apply", r.stdout)               # how to put it back

    def test_uninstall_then_sync_gives_back_the_same_codex_config(self):
        # J12 live run (2026-10-24): the round trip turned the user's LF config.toml into CRLF and moved ccx's block
        # behind the user's own hooks — Codex keeps hook trust by position, so they'd need trusting again
        p = Paths(self.hub)
        for nl in ("\n", "\r\n"):
            with self.subTest(newline=repr(nl)):
                ct = self.home_codex / "config.toml"
                ct.write_bytes('model = "x"\n'.replace("\n", nl).encode())
                sync_all(p, apply=True, parts=["hooks"])
                mine = ('\n# my own hook\n[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\ntype = "command"\n'
                        'command = "echo hi"\n').replace("\n", nl)
                ct.write_bytes(ct.read_bytes() + mine.encode())
                before = ct.read_bytes()
                self.assertEqual(self.ccx("uninstall", "--apply").returncode, 0)
                self.assertNotIn(b"ccx", ct.read_bytes())
                self.assertEqual(b"\r\n" in ct.read_bytes(), nl == "\r\n")            # line endings kept
                sync_all(p, apply=True, parts=["hooks"])
                self.assertEqual(ct.read_bytes(), before)                             # same place, same bytes


class TestProjectLayer(Env):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        r = self.ccx("project", "init")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_init_files_and_ignores(self):
        self.assertTrue((self.work / ".ccx" / "context.md").exists())
        gi = (self.work / ".gitignore").read_text()
        self.assertIn(".ccx/inbox/", gi)
        self.assertIn(".ccx/tasks/", gi)

    def test_init_adds_no_ignores_git_already_has(self):
        other = self.work / "other"
        other.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=other, check=True)
        (other / ".gitignore").write_text(".ccx/\n", encoding="utf-8")       # the whole folder is ignored
        r = self.ccx("project", "--cwd", str(other), "init")
        self.assertEqual(json.loads(r.stdout)["gitignore_added"], [], r.stdout + r.stderr)
        self.assertEqual((other / ".gitignore").read_text(encoding="utf-8"), ".ccx/\n")

    def test_file_given_to_claude_is_one_line_for_codex(self):
        mail = self.work / "advisor.eml"
        mail.write_text("Please rerun the baseline with batch size 64.", encoding="utf-8")
        r = self.ccx("inbox", "advisor asks to rerun baseline with batch 64", "--file", str(mail), "--by", "claude")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        saved = json.loads(r.stdout)["saved"]
        self.assertTrue((self.work / saved).exists())
        out = self.ccx("mem", "delta", "--as", "codex").stdout
        self.assertIn("advisor asks to rerun baseline with batch 64", out)
        self.assertIn(saved, out)
        self.assertNotIn("Please rerun", out, "only the one-line summary, not the email body")
        self.assertEqual(self.ccx("mem", "delta", "--as", "codex").stdout, "", "second session: nothing new")
        self.assertEqual(self.ccx("mem", "delta", "--as", "claude").stdout, "", "own entry is not echoed")

    def test_project_mem_add_and_compact_into_context(self):
        self.ccx("mem", "add", "decided: use parquet not csv", "--project", "--by", "codex", "--topic", "decisions")
        self.assertIn("parquet", self.ccx("mem", "delta", "--as", "claude").stdout)
        r = self.ccx("project", "compact")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("- decided: use parquet not csv", (self.work / ".ccx" / "context.md").read_text(encoding="utf-8"))

    def test_hook_reports_unfinished_task_and_is_silent_otherwise(self):
        self.assertEqual(self.ccx("mem", "delta", "--as", "claude").stdout, "")
        cp = ROOT / "skills" / "task-checkpoint" / "scripts" / "checkpoint.py"
        tid = subprocess.run([sys.executable, str(cp), "init", "--title", "Big refactor", "--step", "a", "--step", "b"],
                             cwd=self.work, capture_output=True, text=True).stdout.strip()
        subprocess.run([sys.executable, str(cp), "fail", tid, "1", "--reason", "quota"], cwd=self.work, check=True,
                       capture_output=True)
        out = self.ccx("mem", "delta", "--as", "claude").stdout
        self.assertIn("unfinished task", out)
        self.assertIn("Big refactor", out)


if __name__ == "__main__":
    unittest.main()
