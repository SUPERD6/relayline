"""#379: why this vendor, model and effort; the planned and the actual first rung. Fake CLIs only."""
import json

from ccx import leadview
from ccx.plan import pick_reasons
from test_adapters import AdapterEnv
from test_ccx import FAKES

READ = ("--from", "user", "--to", "codex", "--tier", "T2", "--mode", "read", "--new", "--context", "off",
        "--no-ab", "--review", "off")


class TestDryRun(AdapterEnv):
    def test_dry_run_first_rung_matches_the_real_run(self):
        dry = self.j("run", *READ, "--dry-run", "Read the parser")
        self.assertTrue(dry["dry_run"])
        self.assertFalse(dry["delegated"])
        self.assertEqual(self.calls(), [])                       # nothing ran
        self.assertFalse((self.hub / "ccx" / "runs").exists() and any((self.hub / "ccx" / "runs").iterdir()))
        why = dry["rung_why"]
        for key in ("agent", "model", "effort"):
            self.assertTrue(why[key], key)
        self.assertIn("--to codex", why["agent"])
        self.assertIn("tiers.T2.codex", why["model"])
        self.assertEqual(dry["planned_first_rung"], dry["first_rung"])

        out = self.j("run", *READ, "Read the parser")
        rec = self.rec(out["run_id"])
        self.assertEqual(rec["planned_first_rung"], dry["planned_first_rung"])
        self.assertEqual(rec["actual_first_rung"], dry["first_rung"])
        self.assertEqual(rec["attempts"][0]["rung"], dry["first_rung"])
        self.assertEqual(rec["rung_why"]["agent"], why["agent"])
        self.assertEqual(out["planned_first_rung"], out["actual_first_rung"])
        self.assertEqual(out["rung_why"]["model"], why["model"])

    def test_dry_run_refuses_bg(self):
        r = self.ccx("run", *READ, "--dry-run", "--bg", "Read the parser")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--dry-run", r.stdout + r.stderr)
        self.assertEqual(self.calls(), [])

    def test_explicit_model_says_so(self):
        dry = self.j("run", "--from", "user", "--to", "codex", "--model", "gpt-6.1-sol", "--effort", "high",
                     "--mode", "read", "--dry-run", "Read the parser")
        self.assertEqual(dry["first_rung"], "codex:gpt-6.1-sol:high")
        self.assertIn("--model", dry["rung_why"]["model"])
        self.assertIn("--effort", dry["rung_why"]["effort"])


class TestDryRunEqualsRun(AdapterEnv):
    """dry-run's first rung == the real run's, across the ways a pick is made (review of PR #398)."""

    def same(self, args, brief="Read the parser", env=None):
        dry = self.j("run", *args, "--dry-run", brief, env=env)
        # read-only probes (`claude --version` while listing installed agents) may run; no task does
        self.assertEqual([c for c in self.calls() if c.get("argv") != ["--version"]], [])
        r = self.ccx("run", *args, brief, env=env)        # the check's outcome is not the point here
        out = json.loads(r.stdout)
        rec = self.rec(out["run_id"])
        self.assertEqual(rec["planned_first_rung"], dry["planned_first_rung"])
        self.assertEqual(rec["actual_first_rung"], dry["first_rung"])
        self.assertEqual(rec["attempts"][0]["rung"], dry["first_rung"])
        return dry, rec

    def test_task_routing_and_to_auto(self):
        dry, _ = self.same(("--from", "claude", "--files", "2", "--coupling", "one", "--clarity", "goal",
                            "--mode", "read", "--new", "--context", "off", "--no-ab", "--review", "off"))
        self.assertEqual(dry["route"]["source"], "task-routing")
        self.assertIn("task-routing", dry["rung_why"]["agent"])
        self.assertIn("b=", dry["rung_why"]["agent"])

    def test_keyword_route_to_auto_states_the_rule(self):
        dry, _ = self.same(("--from", "user", "--tier", "T2", "--mode", "read", "--new", "--context", "off",
                            "--no-ab", "--review", "off"))
        self.assertIn("codex unless the caller is codex, then claude (caller user: codex)", dry["rung_why"]["agent"])

    def test_cheap_first_planned_differs_from_actual(self):
        from test_check_baseline import repository
        import sys
        repository(self.work)
        self.j("config", "set", "dispatch.cheap_first", "true")
        check = f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_none.py'
        dry, rec = self.same(("--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--mode", "write",
                              "--review", "off", "--no-fallback", "--context", "off", "--no-ab", "--check", check),
                             brief="fix state.txt", env={"FAKE_WRITE": "state.txt=edited"})
        self.assertEqual(dry["planned_first_rung"], "codex:gpt-6.1-sol:medium")
        self.assertEqual(dry["first_rung"], "codex:gpt-6-luna:low")
        self.assertTrue(any("cheap-first" in c for c in dry["rung_why"]["changes"]))
        self.assertNotEqual(rec["planned_first_rung"], rec["actual_first_rung"])

    def test_role_reason_names_no_path(self):
        self.j("roles", "set", "build", "codex:gpt-6.1-sol:auto")
        dry, rec = self.same(("--from", "claude", "--role", "build", "--mode", "read", "--new", "--context", "off",
                              "--no-ab", "--review", "off", "--no-worktree"))
        agent = rec["rung_why"]["agent"]
        self.assertRegex(agent, r"^role build \((project|global) role table\)$")
        self.assertNotIn(str(self.hub), json.dumps(dry["rung_why"]))


class TestPlannedAndActual(AdapterEnv):
    def test_capacity_fallback_records_both(self):
        env = {"CCX_CODEX_BIN": str(FAKES / "fake_capacity.py"), "FAKE_CAPACITY_MODELS": "gpt-6.1-sol"}
        dry = self.j("run", *READ, "--dry-run", "Read the parser", env=env)
        out = self.j("run", *READ, "Read the parser", env=env)
        rec = self.rec(out["run_id"])
        self.assertEqual(rec["planned_first_rung"], dry["planned_first_rung"])
        self.assertTrue(rec["planned_first_rung"].startswith("codex:gpt-6.1-sol:"))
        self.assertEqual(rec["actual_first_rung"], rec["attempts"][1]["rung"])
        self.assertNotEqual(rec["planned_first_rung"], rec["actual_first_rung"])
        self.assertEqual((out["planned_first_rung"], out["actual_first_rung"]),
                         (rec["planned_first_rung"], rec["actual_first_rung"]))
        one = leadview.line({**out, "check": {}})
        self.assertEqual((one["planned_first_rung"], one["actual_first_rung"]),
                         (rec["planned_first_rung"], rec["actual_first_rung"]))

    def test_strict_escalate_raises_the_start(self):
        self.j("config", "set", "routing.strict_escalate", "on")
        args = ("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--files", "1", "--mode", "write",
                "--review", "off", "--context", "off", "--no-ab")
        dry = self.j(*args, "--dry-run", "rename value")
        self.assertEqual(dry["planned_first_rung"], "codex:gpt-6-luna:low")
        self.assertNotEqual(dry["first_rung"], dry["planned_first_rung"])
        self.assertTrue(any("strict_escalate" in c for c in dry["rung_why"]["changes"]))
        out = self.j(*args, "rename value")
        rec = self.rec(out["run_id"])
        self.assertEqual(rec["planned_first_rung"], "codex:gpt-6-luna:low")
        self.assertEqual(rec["actual_first_rung"], dry["first_rung"])
        self.assertNotEqual(rec["planned_first_rung"], rec["actual_first_rung"])


PASSED = {"run_id": "r1", "agent": "codex", "model": "gpt-6.1-sol/medium", "effort": "medium", "ok": True,
          "status": "done", "summary": "did it", "files_changed": ["a.py"], "check": {"cmd": "pytest", "passed": True,
          "exit": 0}, "recap": "ccx run r1: status=done ok=true check=passed review=none cost=~$0.0100; next: ccx show r1"}


def test_line_receipt_stays_short():
    base = leadview.dumps(leadview.line(PASSED), True)
    same = {**PASSED, "planned_first_rung": "codex:gpt-6.1-sol:medium", "actual_first_rung": "codex:gpt-6.1-sol:medium",
            "rung_why": {"agent": "x" * 300, "model": "y" * 300, "effort": "z" * 300}}
    assert leadview.dumps(leadview.line(same), True) == base              # same rungs: not one byte more
    moved = {**same, "actual_first_rung": "claude:sonnet:medium"}
    grown = leadview.dumps(leadview.line(moved), True)
    assert len(grown) - len(base) <= 120
    assert "rung_why" not in grown


def test_task_routing_reasons_name_their_signals():
    route = {"source": "task-routing", "b": 0.42, "p": 0.81, "tradeoff": "save", "rung": "claude:sonnet:medium",
             "quota_routing": {"eligible": ["claude", "codex"], "tight": {}}}
    why = pick_reasons(route, {"to": "claude", "model": "sonnet", "effort": "medium"}, "user", {})
    assert "b=0.42" in why["agent"] and "p=0.81" in why["agent"]
    assert "claude, codex" in why["agent"]
    assert "task-routing" in why["model"] and "task-routing" in why["effort"]


def test_role_where_drops_paths():
    from ccx.plan import _role_where
    assert _role_where(r"C:\Users\someone\proj\.ccx\roles.toml") == "project"
    assert _role_where("/home/someone/.ccx-hub/ccx/tiers.toml") == "global"
    assert _role_where("global") == "global"


def test_strict_then_budget_keeps_both_reasons():
    from ccx.plan import plan_changes
    routed = {"rung": "codex:gpt-6.1-sol:medium", "raised_from": "codex:gpt-6-luna:low"}
    out = plan_changes("codex:gpt-6-luna:low", [{"rung": "claude:sonnet:medium"}], False, routed,
                       [routed, {"rung": "claude:sonnet:medium"}])
    assert any("strict_escalate" in c for c in out) and any("daily budget" in c for c in out)


def test_dry_run_skips_the_quota_probe(monkeypatch):
    import os
    from ccx.commands import delegation
    seen = {}
    monkeypatch.delenv("CCX_NO_QUOTA_PROBE", raising=False)
    monkeypatch.setattr(delegation, "_cmd_run", lambda a: seen.setdefault("probe", os.environ.get("CCX_NO_QUOTA_PROBE")) and 0)
    monkeypatch.delenv("CCX_RUN_ID", raising=False)

    class A:
        dry_run = True
    delegation.cmd_run(A())
    assert seen["probe"] == "1" and "CCX_NO_QUOTA_PROBE" not in os.environ


def test_line_receipt_skips_a_null_actual():
    res = {**PASSED, "planned_first_rung": "codex:gpt-6.1-sol:medium", "actual_first_rung": None}
    assert "planned_first_rung" not in leadview.line(res)


def test_quota_swap_in_keyword_routing_is_named():
    route = {"source": "keywords", "tier": "T2", "quota_note": "codex quota 95%, projected 120%; prefer claude",
             "quota_routing": {"eligible": ["claude"], "tight": {"codex": {}}}}
    why = pick_reasons(route, {"to": "claude", "tier": "T2"}, "user", {})
    assert "quota" in why["agent"] and "codex" in why["agent"]
