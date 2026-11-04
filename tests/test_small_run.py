"""Opt-in run gate and strict starting floor, using the existing fake CLIs."""
import json
from unittest.mock import patch

from test_report import ReportEnv
from ccx.config import Paths, load_config
from ccx.delegate import Request
from ccx.plan import _plan


class TestSmallRun(ReportEnv):
    def run_small(self, *extra, env=None):
        return self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--files", "1",
                      "--mode", "write", "--review", "off", *extra, "rename value", env=env)

    def test_default_and_explicit_off_same_route(self):
        before = self.run_small()
        self.j("config", "set", "routing.small_self_run", "off")
        self.j("config", "set", "routing.strict_escalate", "off")
        after = self.run_small()
        self.assertEqual(json.dumps(before["route"]), json.dumps(after["route"]))
        self.assertEqual(before["status"], after["status"])
        self.assertNotIn("small_self", after)

    def test_on_refuses_before_background(self):
        self.j("config", "set", "routing.small_self_run", "on")
        out = self.run_small("--bg", "--wait", "1")
        self.assertEqual(out["state"], "small_self")
        self.assertFalse(out["delegated"])
        self.assertTrue(out["small_self"]["applied"])
        self.assertEqual(self.calls(), [])
        self.assertIn("--force", out["hint"])

    def test_force_bypasses(self):
        self.j("config", "set", "routing.small_self_run", "on")
        self.assertEqual(self.run_small("--force")["status"], "done")
        self.assertTrue(self.calls())

    def test_only_lead(self):
        from ccx.small_tasks import run_advice
        from ccx.cli import parse
        a = parse(["run", "--files", "1", "rename value"])
        cfg = {"routing": {"small_self_run": True}}
        with patch.dict("os.environ", {"CCX_DEPTH": "1", "CCX_ROLE": "subagent"}):
            self.assertIsNone(run_advice(None, cfg, a, "rename value", "claude", None))

    def test_strict_fake_cli_without_check(self):
        self.j("config", "set", "routing.strict_escalate", "on")
        out = self.run_small()
        self.assertTrue(out["route"]["strict_escalate"]["unchecked_write"])
        self.assertNotIn('model_reasoning_effort="low"', self.calls()[0]["argv"])

    def test_strict_fake_cli_with_check_stays(self):
        self.j("config", "set", "routing.strict_escalate", "on")
        self.run_small("--check", "python -c pass")
        self.assertIn('model_reasoning_effort="low"', self.calls()[0]["argv"])

    def test_strict_interface_fake_cli_even_with_check(self):
        self.j("config", "set", "routing.strict_escalate", "on")
        out = self.run_small("--check", "python -c pass", "must return the exact output")
        record = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertTrue(record["route"]["strict_escalate"]["strict_interface"])
        self.assertNotIn('model_reasoning_effort="low"', self.calls()[0]["argv"])

    def test_read_and_worktree_keep_delegating(self):
        self.j("config", "set", "routing.small_self_run", "on")
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--files", "1",
                     "--mode", "read", "--review", "off", "read the file")
        self.assertEqual(out["status"], "done")
        from ccx.small_tasks import run_advice
        from ccx.commands.delegation import _small_self
        from ccx.cli import parse
        a = parse(["run", "--files", "1", "--worktree", "rename value"])
        cfg = load_config(Paths(self.hub))
        self.assertIsNone(run_advice(Paths(self.hub), cfg, a, "rename value", "claude", _small_self))

    def test_interface_even_with_check_and_no_escalation(self):
        cfg = load_config(Paths(self.hub))
        cfg["routing"]["strict_escalate"] = True
        req = Request(to="codex", tier="T1", brief="must return exactly the specified output", check="pytest")
        out = _plan(req, Paths(self.hub), cfg, 0)
        self.assertNotEqual(out[0]["rung"], "codex:gpt-6-luna:low")
        self.assertTrue(req.route["strict_escalate"]["strict_interface"])

    def test_read_without_check_stays(self):
        cfg = load_config(Paths(self.hub))
        cfg["routing"]["strict_escalate"] = True
        req = Request(to="codex", tier="T1", mode="read", brief="read the file")
        self.assertEqual(_plan(req, Paths(self.hub), cfg, 0)[0]["rung"], "codex:gpt-6-luna:low")

    def test_strict_without_routing_skill_uses_configured_floor(self):
        cfg = load_config(Paths(self.hub))
        cfg["routing"]["strict_escalate"] = True
        req = Request(to="codex", tier="T1", brief="rename value")
        with patch("ccx.plan.learn.ladder_after", side_effect=FileNotFoundError("no skill")):
            self.assertEqual(_plan(req, Paths(self.hub), cfg, 0)[0]["model"], cfg["tiers"]["T2"]["codex"]["model"])
