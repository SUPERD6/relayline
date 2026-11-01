"""P0-9 `[routing] mode = auto | off`: off = ccx delegates no new work (route / propose say do it yourself; run,
batch, q run / resume and way refuse without --force) while ask, discuss, `run --mode read`, mem and the rest work
as before; auto = as before."""
import json
import unittest

from test_discuss import DiscussEnv

ROUTE = ("route", "--b", "4", "--to", "codex")


class TestRoutingMode(DiscussEnv):
    def off(self):
        self.j("config", "set", "routing.mode", "off")

    def test_auto_by_default(self):
        out = self.j(*ROUTE, "--files", "1")
        self.assertNotIn("routing_mode", out)
        self.assertNotIn("advice", out)
        self.assertEqual(self.j("config", "get", "routing.mode")["routing.mode"], "auto")

    def test_config_checks_the_value(self):
        self.j("config", "set", "routing.mode", "never", code=3)
        self.off()
        self.assertEqual(self.j("config", "get", "routing.mode")["routing.mode"], "off")
        self.j("config", "set", "routing.mode", "auto")
        self.assertNotIn("routing_mode", self.j(*ROUTE))

    def test_route_says_do_it_yourself(self):
        self.off()
        from ccx.commands.delegation import _route_summary
        for args in (ROUTE, ("route", "add a helper that parses the date strings and wire it into the report"),
                     (*ROUTE, "--lead", "claude:opus:high", "--lead-ctx", "0")):
            out = self.j(*args)
            self.assertEqual(out["routing_mode"], "off", args)
            self.assertIn("routing.mode=off", out["advice"])
            self.assertTrue(out["advice"].startswith("do-it-yourself"))
            self.assertEqual(_route_summary(out)[-1], "Next: do it yourself")
        out = self.j(*ROUTE, "--lead", "claude:opus:high", "--lead-ctx", "0")
        self.assertEqual(out["choice"]["recommend"], "self")
        self.assertIn("recommend_before", out["choice"])
        self.assertTrue(self.j(*ROUTE)["rung"].startswith("codex:"))    # the pick is still shown

    def test_off_wins_over_small_self_and_a_picked_tier(self):
        self.off()
        self.j("config", "set", "routing.small_self", "on")
        self.assertNotIn("small_self", self.j(*ROUTE, "--files", "1", "--lead", "claude:sonnet:medium"))
        self.j("config", "set", "policy.picked", "save")
        pr = self.j("propose", "--b", "4", "--to", "codex", "--files", "3", "--lead", "claude:opus:high",
                    "--lead-ctx", "0", "add a parser")
        self.assertEqual((pr["worth_offering"], pr["authorized"], pr["recommend"], pr["routing_mode"]),
                         (False, False, "self", "off"))
        self.assertIsNone(pr["say"])
        rows = [json.loads(x) for x in next(self.hub.rglob("ledger.jsonl")).read_text(encoding="utf-8").splitlines()]
        row = next(r for r in rows if r.get("proposal") == pr["proposal"] and r.get("type") == "proposal")
        self.assertNotIn("preauthorized", row)                     # nothing was pre-authorised for a later run
        self.assertEqual(row["routing_mode"], "off")

    def test_run_refuses_without_force(self):
        self.off()
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "add a parser")
        self.assertEqual((out["delegated"], out["routing_mode"]), (False, "off"))
        self.assertIn("--force", out["hint"])
        self.assertIn("routing.mode auto", out["hint"])
        self.assertEqual(list(self.hub.glob("runs/*/run.json")), [])               # nothing started
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "--bg", "add a parser")
        self.assertEqual(out["routing_mode"], "off")                # refused before detaching
        self.assertEqual(list(self.hub.glob("runs/*")), [])
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--b", "4", "--force", "add a parser")
        self.assertEqual(json.loads(r.stdout)["status"], "done", r.stdout)
        self.assertIn("routing.mode is off", r.stderr)
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "--mode", "read",
                     "review the parser")                           # a read-only second opinion still runs
        self.assertEqual(out["status"], "done", out)

    def test_batch_q_and_way_refuse_without_force(self):
        self.off()
        plan = self.work / "plan.json"
        plan.write_text(json.dumps({"tasks": [{"id": "a", "to": "codex", "tier": "T1", "brief": "fix a.py"}]}),
                        encoding="utf-8")
        self.assertEqual(self.j("batch", str(plan), "--from", "claude")["routing_mode"], "off")
        self.assertIn("results", self.j("batch", str(plan), "--from", "claude", "--force"))
        self.assertEqual(self.j("q", "run", "--cwd", str(self.work))["routing_mode"], "off")
        self.assertEqual(self.j("q", "resume", "--cwd", str(self.work))["routing_mode"], "off")
        self.assertEqual(self.j("way", "--from", "claude", "fix a.py")["routing_mode"], "off")
        self.assertNotIn("routing_mode", self.j("q", "run", "--cwd", str(self.work), "--force"))
        self.assertNotIn("routing_mode", self.j("way", "--from", "claude", "--dry-run", "fix a.py"))

    def test_discuss_and_mem_work_as_before(self):
        self.off()
        out = self.j("discuss", "--with", "codex,claude", "--rounds", "1", "x?")
        self.assertNotIn("routing_mode", out)
        self.assertIn("turns", out)
        self.j("mem", "add", "a note")
        self.assertNotIn("routing_mode", self.j("ask", "--to", "codex", "--from", "claude", "is this right?"))


if __name__ == "__main__":
    unittest.main()
