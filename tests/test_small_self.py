"""P0-6 routing.small_self: `ccx route` / `ccx propose` advise doing a small task yourself (off by default).
By files (default): the #200 rule; by cost: what doing it yourself costs vs delegating's fixed cost."""
import unittest

from test_report import ReportEnv

ROUTE = ("route", "--b", "4", "--to", "codex")
SONNET = ("--lead", "claude:sonnet:medium", "--lead-ctx", "0")


class TestSmallSelf(ReportEnv):
    def on(self, by="cost"):
        self.j("config", "set", "routing.small_self", "on")
        if by:
            self.j("config", "set", "routing.small_self_by", by)

    def test_off_by_default(self):
        out = self.j(*ROUTE, "--files", "1", *SONNET)
        self.assertNotIn("small_self", out)
        self.assertNotIn("advice", out)
        self.assertTrue(out["rung"].startswith("codex:"))

    def test_cheap_task_is_do_it_yourself(self):
        self.on()
        out = self.j(*ROUTE, "--files", "1", *SONNET)
        ss = out["small_self"]
        self.assertEqual((ss["applied"], ss["by"], ss["files"], ss["files_from"]), (True, "cost", 1, "--files"))
        est = ss["self_cost"]
        self.assertLess(est["usd"], est["overhead_usd"])
        self.assertEqual((est["requests"], est["requests_from"], est["ctx_from"]), (3.5, "files", "default"))
        self.assertTrue(out["advice"].startswith("do-it-yourself: doing it yourself costs about $"))
        self.assertTrue(out["rung"].startswith("codex:"))           # routing itself is unchanged
        from ccx.commands.delegation import _route_summary
        self.assertEqual(_route_summary(out)[-1], "Next: do it yourself")

    def test_dear_task_keeps_delegating(self):
        self.on()
        for extra in (("--files", "3"), ("--files", "1", "--requests", "12")):
            out = self.j(*ROUTE, *extra, *SONNET)
            ss = out["small_self"]
            self.assertFalse(ss["applied"], extra)
            self.assertGreaterEqual(ss["self_cost"]["usd"], ss["self_cost"]["overhead_usd"], extra)
            self.assertIn("not less than delegating", ss["why"])
            self.assertNotIn("advice", out, extra)
        self.assertNotIn("small_self", self.j(*ROUTE, *SONNET))     # nothing to size it by

    def test_requests_and_lead_context(self):
        self.on()
        out = self.j(*ROUTE, "--requests", "2", *SONNET)           # --requests alone sizes it
        self.assertEqual(out["small_self"]["self_cost"]["requests_from"], "--requests")
        self.assertTrue(out["small_self"]["applied"])
        for files, applied in (("1", True), ("3", False)):
            big = self.j(*ROUTE, "--files", files, "--lead", "claude:sonnet:medium", "--lead-ctx", "120000")
            est = big["small_self"]["self_cost"]
            self.assertEqual((est["ctx_tokens"], est["ctx_from"]), (120000, "lead"))
            # delegating's own requests re-read the long conversation too: what decides is how many more you make
            self.assertGreater(est["overhead_usd"], 0.035)
            self.assertEqual(big["small_self"]["applied"], applied, files)
        self.j(*ROUTE, "--requests", "0", *SONNET, code=3)

    def test_overhead_scales_with_the_leads_price(self):
        self.on()
        s = self.j(*ROUTE, "--files", "1", *SONNET)["small_self"]["self_cost"]
        o = self.j(*ROUTE, "--files", "1", "--lead", "claude:opus:high", "--lead-ctx", "0")["small_self"]["self_cost"]
        self.assertAlmostEqual(o["usd"] / s["usd"], o["overhead_usd"] / s["overhead_usd"], places=1)
        self.assertEqual(s["overhead_usd"], 0.035)
        self.j("config", "set", "routing.small_self_overhead_usd", "0.001")
        self.assertFalse(self.j(*ROUTE, "--files", "1", *SONNET)["small_self"]["applied"])

    def test_plain_terminal_is_priced_on_the_reference(self):
        self.on()
        out = self.j(*ROUTE, "--files", "1")
        self.assertTrue(out["small_self"]["applied"])
        self.assertEqual(out["small_self"]["self_cost"]["model"], "claude:sonnet (reference)")

    def test_exceptions_keep_delegating(self):
        self.on()
        for extra, word in ((("--needs", "undo", *SONNET), "--needs"),
                            (("--lead", "claude:sonnet:medium", "--lead-ctx", "200000"), "context is large"),
                            (("--lead", "claude:sonnet:medium", "--lead-ctx", "0", "--quota", "claude=0.95"),
                             "quota is tight")):
            out = self.j(*ROUTE, "--files", "1", *extra)
            self.assertFalse(out["small_self"]["applied"], extra)
            self.assertIn(word, out["small_self"]["why"])
            self.assertNotIn("advice", out, extra)
        self.j("config", "set", "policy.picked", "save")          # the person's tier wins
        out = self.j(*ROUTE, "--files", "1", *SONNET)
        self.assertFalse(out["small_self"]["applied"])
        self.assertIn("policy.picked", out["small_self"]["why"])

    def test_by_files_keeps_the_200_rule(self):
        self.on(None)                                               # files is the default
        out = self.j(*ROUTE, "--files", "1")                        # no price needed
        self.assertEqual((out["small_self"]["applied"], out["small_self"]["by"]), (True, "files"))
        self.assertTrue(out["advice"].startswith("do-it-yourself: small task"))
        self.assertNotIn("small_self", self.j(*ROUTE, "--files", "2"))
        self.j("config", "set", "routing.small_self_files", "2")
        self.assertTrue(self.j(*ROUTE, "--files", "2")["small_self"]["applied"])

    def test_config_checks_the_values(self):
        self.j("config", "set", "routing.small_self_by", "lines", code=3)
        self.j("config", "set", "routing.small_self_by", "files")

    def test_keyword_route(self):
        self.on()
        text = "add a helper that parses the date strings and wire it into the report command output"
        self.assertNotEqual(self.j("route", text)["tier"], "T0")
        self.assertNotIn("small_self", self.j("route", *SONNET, text))
        out = self.j("route", "--files", "1", *SONNET, text)
        self.assertTrue(out["small_self"]["applied"])
        from ccx.commands.delegation import _route_summary
        self.assertEqual(_route_summary(out)[-1], "Next: do it yourself")

    def test_brief_named_file(self):
        self.on()
        (self.work / "mod.py").write_text("x = 1\n", encoding="utf-8")
        out = self.j(*ROUTE, "--risk", "low", *SONNET, "change mod.py so x is 2")
        self.assertEqual((out["small_self"]["files"], out["small_self"]["files_from"]), (1, "brief"))

    def test_propose_and_run(self):
        self.on()
        pr = self.j("propose", "--b", "4", "--to", "codex", "--files", "1", *SONNET, "add a parser")
        self.assertEqual((pr["worth_offering"], pr["recommend"]), (False, "self"))
        self.assertTrue(pr["small_self"]["applied"])
        long = self.j("propose", "--minutes", "30", "--to", "codex", "--files", "1", *SONNET,
                      "add a parser")                                 # the offer path passes 15+ minutes
        self.assertTrue(long["small_self"]["applied"])
        rt = self.j(*ROUTE, "--files", "1", *SONNET)
        self.assertEqual(rt["choice"]["recommend"], "self")
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "--files", "1", "add a parser")
        self.assertEqual(out["status"], "done", out)             # an explicit `ccx run` still delegates


if __name__ == "__main__":
    unittest.main()
