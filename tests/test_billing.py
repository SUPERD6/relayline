"""Two accounting bases; fake CLI calls and local fixture records only."""
import json
import time
import unittest
from pathlib import Path
from unittest import mock

from ccx import ledger, report, ui
from ccx.config import Paths, load_config
from test_ccx import Env


def api_sample_row():
    """The input used for the main-branch JSON golden; local noon makes its day independent of timezone."""
    return {"run_id": "api-golden", "label": "api-golden", "to": "codex", "caller": "user", "tier": "T1",
            "start_tier": "T1", "status": "done", "kind": "ok", "ok": True, "attempts": 1, "seconds": 1.0,
            "ts": time.mktime((2026, 10, 31, 12, 0, 0, 0, 0, -1)), "rungs": ["codex:gpt-6-luna:low"],
            "sessions": [], "ae_usd": 0.03, "ae_by_agent": {"codex": 0.03}, "cost_usd": 0.02,
            "usage": {"input": 140, "cache_write": 40, "cached": 20, "output": 10},
            "usage4": {"input_tokens": 100, "cache_write_tokens": 40, "cached_input_tokens": 20, "output_tokens": 10}}


class TestUnits(unittest.TestCase):
    def test_default_counts_each_bucket_once(self):
        u = {"input_tokens": 10, "cache_write_tokens": 20, "cache_write_1h_tokens": 15,
             "cached_input_tokens": 30, "output_tokens": 40, "reasoning_output_tokens": 25}
        self.assertEqual(ledger.quota_units({}, "claude", "opus", u), 100)
        self.assertEqual(ledger.row_quota({"usage": {"input": 30, "cache_write": 20,
                                                     "cached": 30, "output": 40}}), 100)

    def test_vendor_and_provider_model_precedence(self):
        cfg = {"providers": {"custom": {"vendor": "anthropic"}}, "billing": {
            "mode": "subscription", "quota_unit": 0.5,
            "vendors": {"anthropic": {"quota_unit": 2, "models": {"opus": 3}}},
            "providers": {"custom": {"quota_unit": 4, "models": {"opus": 5}}}}}
        u = {"input_tokens": 100, "output_tokens": 20}
        for agent, model, expected in (("unknown", "x", 60), ("claude", "x", 240),
                                       ("claude", "opus", 360), ("custom", "x", 480),
                                       ("custom", "opus", 600)):
            with self.subTest(agent=agent, model=model):
                self.assertEqual(ledger.quota_units(cfg, agent, model, u), expected)

    def test_invalid_settings_name_the_bad_key(self):
        for bad, key in (({"mode": "cash"}, "billing.mode"), ({"mode": None}, "billing.mode"),
                         ({"quota_unit": -1}, "billing.quota_unit"),
                         ({"quota_unit": True}, "billing.quota_unit"),
                         ({"quota_unit": float("inf")}, "billing.quota_unit"),
                         ({"quota_unit": float("nan")}, "billing.quota_unit"),
                         ({"quota_unit": "tokens"}, "billing.quota_unit"),
                         ({"vendors": []}, "billing.vendors"),
                         ({"providers": {"x": {"models": {"m": -1}}}}, "billing.providers.x.models.m")):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as err:
                ledger.billing_config({"billing": bad})
            self.assertIn(key, str(err.exception))

    def test_zero_weight_and_stored_zero_are_valid(self):
        self.assertEqual(ledger.quota_units({"billing": {"quota_unit": 0}}, "codex", "m",
                                            {"input_tokens": 100}), 0)
        self.assertEqual(ledger.row_quota({"quota_units": 0, "usage": {"input": 100}}), 0)


class TestBilling(Env):
    def setUp(self):
        super().setUp()
        self.p = Paths(self.hub)

    def billing(self, text):
        self.p.user_tiers.parent.mkdir(parents=True, exist_ok=True)
        self.p.user_tiers.write_text(text, encoding="utf-8")

    def fake_run(self):
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--no-ab", "read a file")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_config_mode_cli_switches_and_lists_the_setting(self):
        for mode in ("subscription", "api"):
            r = self.ccx("config", "set", "billing.mode", mode)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(r.stdout), {"billing.mode": mode})
            r = self.ccx("config", "get", "billing.mode")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(r.stdout), {"billing.mode": mode})
        r = self.ccx("config", "list")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["billing.mode"]["value"], "api")
        self.assertEqual(self.calls(), [])

    def test_config_mode_cli_rejects_invalid_values_without_changing_settings(self):
        self.assertEqual(self.ccx("config", "set", "billing.mode", "subscription").returncode, 0)
        before = self.p.settings.read_bytes()
        for mode in ("cash", "", "API"):
            with self.subTest(mode=mode):
                r = self.ccx("config", "set", "billing.mode", mode)
                self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
                self.assertIn("billing.mode must be api or subscription", r.stdout + r.stderr)
                self.assertEqual(self.p.settings.read_bytes(), before)
        self.assertEqual(self.calls(), [])

    def test_default_writes_both_bases_and_keeps_dollars(self):
        self.assertEqual(load_config(self.p)["billing"]["mode"], "api")
        out = self.fake_run()
        r = ledger.rows(self.p)[0]
        self.assertEqual(r["quota_units"], 1350)  # fake Codex: 400 fresh + 800 cached + 150 output
        self.assertEqual(r["quota_by_agent"], {"codex": 1350})
        self.assertIn("ae_usd", r)
        self.assertIn("cost_usd", r)
        self.assertEqual(ledger.chain_cost(self.p, [out["run_id"]])["quota_units"], 1350)
        st = ledger.stats(self.p)[0]
        self.assertEqual((st["quota_units"], st["ae_usd"]), (1350, r["ae_usd"]))

    def test_subscription_records_weighted_units_without_repricing_history(self):
        self.billing('[billing]\nmode = "subscription"\n[billing.providers.codex]\nquota_unit = 2.5\n')
        self.fake_run()
        r = ledger.rows(self.p)[0]
        self.assertEqual(r["quota_units"], 3375)
        self.billing('[billing]\nmode = "api"\nquota_unit = 99\n')
        s = report.summarize(self.p, report.collect(self.p, include_lead=False))
        self.assertEqual(s["totals"]["quota_units"], 3375)
        self.assertEqual(s["totals"]["sub_ae"], round(r["ae_usd"], 4))

    def test_attempts_use_their_own_model_and_vendor(self):
        cfg = {"billing": {"vendors": {"anthropic": {"models": {"opus": 3}}},
                            "providers": {"codex": {"quota_unit": 0.5}}}}
        rec = {"to": "claude", "attempts": [
            {"agent": "codex", "model": "m", "seconds": 1, "usage": {"input_tokens": 100}, "ae_usd": 0.01},
            {"agent": "claude", "rung": "claude:opus:high", "seconds": 2,
             "usage": {"output_tokens": 20}, "ae_usd": 0.02}]}
        r = ledger._slim(rec, cfg)
        self.assertEqual((r["quota_units"], r["quota_by_agent"]), (110, {"codex": 50, "claude": 60}))
        r.update(run_id="fallback", start_tier="T1", status="done", ts=time.time())
        ledger.append_event(self.p, r)
        s = report.summarize(self.p, report.collect(self.p, include_lead=False))
        streams = {x["agent"]: x["quota_units"] for x in s["streams"] if x["role"] == "sub"}
        self.assertEqual((s["totals"]["quota_units"], streams["codex"], streams["claude"]), (110, 50, 60))

    def test_cross_provider_success_counts_once_for_110_units_per_success(self):
        self.billing('[billing]\nmode = "subscription"\n')
        rec = {"to": "claude", "attempts": [
            {"agent": "codex", "rung": "codex:m:low", "seconds": 1, "usage": {"input_tokens": 100},
             "ae_usd": 0.01},
            {"agent": "claude", "rung": "claude:opus:high", "seconds": 2, "usage": {"output_tokens": 20},
             "ae_usd": 0.02}]}
        cfg = {"billing": {"vendors": {"anthropic": {"models": {"opus": 3}}},
                            "providers": {"codex": {"quota_unit": 0.5}}}}
        r = ledger._slim(rec, cfg)
        r.update(run_id="cross-provider", start_tier="T1", status="done", ts=time.time())
        ledger.append_event(self.p, r)
        ledger.append_event(self.p, {"type": "verify", "run_id": r["run_id"], "ok": True, "ts": time.time()})
        s = report.summarize(self.p, report.collect(self.p, include_lead=False))
        self.assertEqual((s["totals"]["runs"], s["totals"]["done_rate"], s["totals"]["verified"]), (1, 1.0, 1))
        self.assertEqual((s["totals"]["quota_units"], s["totals"]["quota_units_per_success"]), (110, 110))
        self.assertEqual((len(s["runs"]), s["runs"][0]["quota_units"], s["runs"][0]["ae"]), (1, 110, 0.03))
        self.assertEqual(s["totals"]["cps"], 0.03)

    def test_api_json_matches_complete_main_golden(self):
        golden = json.loads((Path(__file__).parent / "data" / "billing_api_main.json").read_text(encoding="utf-8"))
        for case in ("empty", "one_run"):
            with self.subTest(case=case):
                if case == "one_run":
                    ledger.append_event(self.p, api_sample_row())
                r = self.ccx("stats", "--summary", "--days", "36500")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(json.loads(r.stdout), golden["cases"][case]["stats"])
                r = self.ccx("report", "--no-lead", "--days", "36500")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                actual = json.loads(r.stdout)
                expected = golden["cases"][case]["report"]
                # Output paths and the generated timestamp are the only machine/time-dependent values.
                expected["report"] = str(self.p.state / "report" / "index.html")
                expected["summary"] = str(self.p.state / "report" / "summary.json")
                self.assertEqual(actual, expected)
                actual = json.loads(Path(actual["summary"]).read_text(encoding="utf-8"))
                expected = golden["cases"][case]["summary"]
                expected["generated"] = actual["generated"]
                self.assertEqual(actual, expected)
        self.assertEqual(self.calls(), [])

    def test_unpriced_attempt_units_do_not_add_an_api_run(self):
        rec = {"to": "claude", "attempts": [
            {"agent": "codex", "rung": "codex:m:low", "seconds": 1, "usage": {"input_tokens": 100}},
            {"agent": "claude", "rung": "claude:opus:high", "seconds": 2,
             "usage": {"output_tokens": 20}, "ae_usd": 0.02}]}
        r = ledger._slim(rec)
        r.update(run_id="partially-priced", start_tier="T1", status="done", ts=time.time())
        ledger.append_event(self.p, r)
        s = report.summarize(self.p, report.collect(self.p, include_lead=False))
        self.assertEqual((s["totals"]["runs"], s["totals"]["ae"], s["totals"]["quota_units"]), (1, 0.02, 120))
        streams = {x["agent"]: x["quota_units"] for x in s["streams"] if x["role"] == "sub"}
        self.assertEqual((streams["codex"], streams["claude"]), (100, 20))

    def test_legacy_rows_use_unweighted_tokens_and_are_not_rewritten(self):
        self.billing('[billing]\nmode = "subscription"\nquota_unit = 99\n')
        rows = [{"run_id": "old", "to": "codex", "start_tier": "T1", "status": "done", "ts": time.time(),
                 "usage": {"input": 30, "cache_write": 20, "cached": 30, "output": 40}, "ae_usd": 0.01},
                {"run_id": "missing", "to": "codex", "start_tier": "T1", "usage": {}, "ts": time.time()},
                {"type": "verify", "run_id": "old", "ok": True}]
        self.p.ledger.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        before = self.p.ledger.read_bytes()
        got = ledger.rows(self.p)
        self.assertEqual([r.get("quota_units") for r in got], [100, 0, None])
        s = report.summarize(self.p, report.collect(self.p, include_lead=False))
        self.assertEqual(s["totals"]["quota_units"], 100)
        self.assertEqual(self.p.ledger.read_bytes(), before)

    def test_invalid_toml_settings_fail_through_report_command(self):
        for text, key in (('[billing]\nmode = "cash"\n', "billing.mode"),
                          ('[billing.providers.codex]\nquota_unit = -2\n', "billing.providers.codex.quota_unit")):
            with self.subTest(key=key):
                self.billing(text)
                r = self.ccx("report", "--no-lead")
                self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
                self.assertIn(key, r.stdout + r.stderr)
        self.assertEqual(self.calls(), [])

    def test_ui_data_adds_billing_and_quota_without_rewriting_usd(self):
        self.billing('[billing]\nmode = "subscription"\nquota_unit = 2\n')
        out = self.fake_run()
        self.billing('[billing]\nmode = "subscription"\nquota_unit = 99\n')
        d = ui.run_detail(self.p, out["run_id"])
        self.assertEqual((d["billing"]["mode"], d["quota_units"]), ("subscription", 2700))
        with mock.patch.object(ui, "quota_view", return_value=[]), \
                mock.patch.object(ui, "leads", return_value=[]):
            d = ui.collect(self.p)
        self.assertEqual((d["billing"]["mode"], d["week"]["quota_units"]), ("subscription", 2700))
        srv = ui.UI(self.p)
        try:
            d = srv.token_flow("all", tests=True)
            self.assertEqual((d["billing"]["mode"], d["totals"]["quota_units"]), ("subscription", 2700))
            self.assertEqual(d["tasks"][0]["runs"][0]["quota_units"], 2700)
            self.assertGreater(d["totals"]["usd"], 0)
        finally:
            srv.httpd.server_close()  # data-only call: serve_forever was never started

    def test_real_month_and_project_map_follow_mode_changes_on_the_same_reader(self):
        self.billing('[billing]\nquota_unit = 2\n')
        out = self.fake_run()
        rec = ledger.load_run(self.p, out["run_id"])
        rd = ui.Reader(self.p)
        pr = {"id": "billing", "name": "billing", "path": str(self.work), "tasks": []}
        api_spend = None
        for mode in ("api", "subscription", "api"):
            with self.subTest(mode=mode):
                r = self.ccx("config", "set", "billing.mode", mode)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                # Keep the same reader and its cached config/month across immediate mode switches.
                rd.cfg()
                month = ui.month_view(rd)
                self.assertEqual((month["billing"]["mode"], month["runs"], month["quota_units"]), (mode, 1, 2700))
                self.assertEqual(ui.month_view(rd, wait=False)["billing"]["mode"], mode)
                m = ui.project_map(rd, self.p, pr, [rec], {}, {}, None, [], 0)
                if api_spend is None:
                    api_spend = m["spend"]
                expected = {**api_spend, "quota_units": 2700} if mode == "subscription" else api_spend
                self.assertEqual(m["spend"], expected)
