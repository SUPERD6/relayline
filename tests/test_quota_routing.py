"""P0-17: quota routing and bounded refresh/fallback. CLI wiring runs outside the repo, with fakes only."""
import json
import time
from datetime import datetime, timezone

from test_ccx import Env
from ccx import quota, ui
from ccx.config import Paths, load_config
from ccx.plan import quota_candidates


class TestQuotaRouting(Env):
    def setUp(self):
        super().setUp()
        self.p = Paths(self.hub)
        self.now = time.time()
        self.reset = int(self.now + 86400)

    def config(self, text):
        self.p.state.mkdir(parents=True, exist_ok=True)
        (self.p.state / "tiers.toml").write_text(text, encoding="utf-8")

    def claude(self, used=0.82, age=0, window="five_hour"):
        self.p.state.mkdir(parents=True, exist_ok=True)
        with open(self.p.state / "quota.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self.now - age * 60, "agent": "claude", "window": window,
                                "used": used, "resets_at": self.reset}) + "\n")

    def codex(self, used=0.16, age=0):
        f = self.home_codex / "sessions" / "2026" / "11" / "01" / "rollout-quota.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"timestamp": datetime.fromtimestamp(self.now - age * 60, timezone.utc).isoformat(),
            "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {"primary": {
                "used_percent": used * 100, "window_minutes": 300, "resets_at": self.reset}}}}) + "\n",
            encoding="utf-8")

    def j(self, *args, env=None, code=0):
        r = self.ccx(*args, env=env)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def record(self, out):
        return json.loads((self.p.runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))

    def model_calls(self):
        return [c for c in self.calls() if "-p" in c["argv"] or c["argv"][:1] == ["exec"]]

    def test_route_demotes_any_tight_window_and_names_alternative(self):
        self.claude(0.10)
        self.claude(0.82, window="seven_day")
        self.codex()
        out = self.j("route", "--b", "4")
        self.assertTrue(out["rung"].startswith("codex:"), out)
        self.assertEqual(out["quota_routing"]["candidates"], ["codex", "claude"])
        self.assertIn("82%", out["quota_note"])
        self.assertIn("codex", out["quota_note"])
        self.assertEqual(self.calls(), [])

    def test_explicit_quota_flags_reach_route(self):
        out = self.j("route", "--b", "4", "--quota", "claude=0.82", "--quota", "codex=0.16")
        self.assertTrue(out["rung"].startswith("codex:"))
        self.assertIn("82%", out["quota_note"])

    def test_keyword_route_and_run_use_the_same_order(self):
        self.claude()
        self.codex()
        out = self.j("route", "implement parser")
        self.assertEqual(out["recommended_agent"], "codex")
        self.assertEqual(out["quota_routing"]["candidates"], ["codex", "claude"])
        run = self.j("run", "--from", "user", "--tier", "T2", "--review", "off", "implement parser")
        self.assertEqual(run["agent"], "codex")

    def test_routing_off_disables_cli_partition(self):
        self.config('[quota]\nrouting = "off"\n')
        self.claude()
        self.codex()
        out = self.j("route", "--b", "4")
        self.assertEqual(out["quota_routing"]["tight"], {})
        self.assertEqual(set(out["quota_routing"]["eligible"]), {"claude", "codex"})
        self.assertNotIn("quota_note", out)

    def test_route_all_tight_names_the_reset(self):
        self.claude(0.9)
        self.codex(0.91)
        out = self.j("route", "--b", "4")
        self.assertTrue(out["quota_routing"]["all_tight"])
        self.assertIn("all quotas tight", out["quota_note"])
        self.assertEqual(out["quota_routing"]["resets_at"], self.reset)

    def test_projection_demotes_before_current_usage_is_high(self):
        self.claude(0.10, age=7 * 60, window="seven_day")
        self.claude(0.50, window="seven_day")
        self.codex()
        out = self.j("route", "--b", "4")
        self.assertGreater(out["quota_routing"]["tight"]["claude"]["projected_at_reset"], 1)
        self.assertTrue(out["rung"].startswith("codex:"))

    def test_all_tight_shows_reset_and_does_not_run(self):
        self.claude(0.9)
        self.codex(0.91)
        out = self.j("run", "--from", "user", "--b", "4", "implement parser")
        self.assertFalse(out["delegated"])
        self.assertIn("all quotas tight", out["advice"])
        self.assertIn(quota.reset_text(self.reset), out["advice"])
        self.assertEqual(self.calls(), [])

    def test_off_retains_candidates_and_exact_threshold_is_allowed(self):
        self.claude(0.8)
        ranked = quota_candidates(self.p, load_config(self.p), ["claude", "codex"])
        self.assertEqual(ranked["eligible"], ["claude", "codex"])
        self.claude(0.99)
        ranked = quota_candidates(self.p, {"quota": {"routing": "off"}}, ["claude", "codex"])
        self.assertEqual(ranked["eligible"], ["claude", "codex"])

    def test_unknown_and_expired_readings_do_not_become_zero(self):
        self.reset = int(self.now - 30)
        self.claude(0.99, age=10)
        pr = quota.pressure(self.p)
        self.assertIsNone(pr["pace"]["claude"]["five_hour"]["used"])
        self.assertAlmostEqual(pr["freshness"]["claude"], 10, delta=0.2)
        ranked = quota_candidates(self.p, load_config(self.p), ["claude", "codex"])
        self.assertEqual(ranked["eligible"], ["claude", "codex"])

    def test_auto_run_and_snapshot_in_record_and_ledger(self):
        self.claude()
        self.codex()
        out = self.j("run", "--from", "user", "--b", "4", "--review", "off", "implement parser")
        self.assertEqual(out["agent"], "codex")
        snap = self.record(out)["quota_at_start"]
        self.assertEqual(snap["pace"]["claude"]["five_hour"]["used"], 0.82)
        rows = [json.loads(x) for x in self.p.ledger.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(r.get("run_id") == out["run_id"] and r.get("quota_at_start") == snap for r in rows))

    def test_named_model_is_kept_even_when_tight(self):
        self.claude()
        out = self.j("run", "--from", "user", "--to", "claude", "--model", "haiku", "--effort", "low",
                     "--review", "off", "x")
        self.assertEqual(out["agent"], "claude")

    def test_limit_fallback_has_evidence_reset_and_only_one_retry(self):
        out = self.j("run", "--from", "user", "--to", "claude", "--tier", "T2", "--review", "off", "x",
                     env={"FAKE_STATUS": "quota"}, code=2)
        rec = self.record(out)
        self.assertEqual([a["agent"] for a in rec["attempts"]], ["claude", "codex"])
        self.assertEqual(rec["attempts"][0]["quota_stop"]["by"], "rate_limit_event")
        self.assertEqual(out["quota_fallback"]["resets_at"], 1798000000)
        self.assertIn("claude -> codex", out["quota_fallback"]["message"])
        self.assertEqual(len(self.model_calls()), 2)

    def test_tight_alternative_is_not_retried(self):
        self.claude(0.95)
        out = self.j("run", "--from", "user", "--to", "codex", "--tier", "T2", "--review", "off", "x",
                     env={"FAKE_STATUS_CODEX": "quota"}, code=2)
        self.assertEqual(len(self.record(out)["attempts"]), 1)

    def test_auth_error_does_not_fallback(self):
        out = self.j("run", "--from", "user", "--to", "codex", "--tier", "T2", "--review", "off", "x",
                     env={"FAKE_STATUS_CODEX": "auth"}, code=2)
        self.assertNotIn("quota_stop", self.record(out))
        self.assertEqual(len(self.model_calls()), 1)

    def test_refresh_cli_reads_and_probes_without_project_context(self):
        windows = {"five_hour": {"utilization": 0.21, "resetsAt": self.reset}}
        codex = {"primary": {"used_percent": 16, "window_minutes": 300, "resets_at": self.reset}}
        out = self.j("quota", "--refresh", env={"FAKE_QUOTA_CLAUDE": json.dumps(windows),
                                               "FAKE_QUOTA_CODEX": json.dumps(codex)})
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(out["windows"]["claude"]["five_hour"]["used"], 0.21)
        self.assertEqual(out["windows"]["codex"]["primary"]["used"], 0.16)
        self.assertLess(out["refresh"]["claude"]["cost_usd"], 0.005)
        self.assertIsNotNone(out["refresh"]["codex"]["ae_usd"])
        call = self.calls()[0]
        self.assertIn("--tools", call["argv"])
        self.assertIn("--system-prompt", call["argv"])
        self.assertIn("--no-session-persistence", call["argv"])
        self.assertNotIn("Do only this task", call["prompt"])
        self.assertIn("claude", out["freshness"])
        again = self.j("quota", "--refresh", env={"FAKE_QUOTA_CLAUDE": json.dumps(windows)})
        self.assertEqual(again["refresh"]["codex"]["source"], "session_files")
        self.assertEqual(again["refresh"]["codex"]["cost_usd"], 0)
        self.assertEqual(len(self.calls()), 3)

    def test_stale_route_refreshes_once(self):
        self.claude(0.82, age=70)
        self.codex(age=70)
        env = {"CCX_NO_QUOTA_PROBE": "0", "FAKE_QUOTA_CLAUDE": json.dumps({
            "five_hour": {"utilization": 0.20, "resetsAt": self.reset}}),
            "FAKE_QUOTA_CODEX": json.dumps({"primary": {
                "used_percent": 16, "window_minutes": 300, "resets_at": self.reset}})}
        self.j("route", "--b", "4", env=env)
        self.assertEqual([c["agent"] for c in self.model_calls()], ["claude", "codex"])
        self.j("route", "--b", "4", env=env)
        self.assertEqual(len(self.model_calls()), 2)
        self.assertLess(quota.pressure(self.p)["freshness"]["claude"], 1)
        self.assertLess(quota.pressure(self.p)["freshness"]["codex"], 1)

    def test_stale_run_refreshes_before_picking_and_takes_new_snapshot(self):
        self.claude(0.20, age=70)
        self.codex()
        out = self.j("run", "--from", "user", "--b", "4", "--review", "off", "implement parser",
                     env={"CCX_NO_QUOTA_PROBE": "0", "FAKE_QUOTA_CLAUDE": json.dumps({
                         "five_hour": {"utilization": 0.9, "resetsAt": self.reset}})})
        self.assertEqual(out["agent"], "codex")
        self.assertEqual([c["agent"] for c in self.model_calls()], ["claude", "codex"])
        self.assertEqual(self.record(out)["quota_at_start"]["pace"]["claude"]["five_hour"]["used"], 0.9)

    def test_legacy_probe_option_uses_the_minimal_request(self):
        out = self.j("quota", "--probe", env={"FAKE_QUOTA_CLAUDE": json.dumps({
            "five_hour": {"utilization": 0.2, "resetsAt": self.reset}})})
        self.assertEqual(out["probe_readings"], 1)
        self.assertEqual(len(self.model_calls()), 1)
        self.assertIn("--max-budget-usd", self.model_calls()[0]["argv"])

    def test_probe_and_refresh_together_do_not_probe_claude_twice(self):
        self.codex()
        out = self.j("quota", "--probe", "--refresh", env={"FAKE_QUOTA_CLAUDE": json.dumps({
            "five_hour": {"utilization": 0.2, "resetsAt": self.reset}})})
        self.assertEqual(out["probe_readings"], 1)
        self.assertEqual(len(self.model_calls()), 1)

    def test_refresh_failure_is_visible_and_has_cooldown(self):
        self.claude(0.82, age=70)
        self.codex()
        env = {"CCX_NO_QUOTA_PROBE": "0"}
        self.j("route", "--b", "4", env=env)
        self.j("route", "--b", "4", env=env)
        state = json.loads((self.p.state / "quota-refresh.json").read_text(encoding="utf-8"))
        self.assertIn("no quota windows", state["claude"]["error"])
        self.assertGreater(quota.pressure(self.p)["freshness"]["claude"], 60)
        self.assertEqual(len(self.calls()), 1)

    def test_refresh_can_be_disabled_for_route_and_run(self):
        self.config('[quota]\nauto_refresh_min = 0\n')
        env = {"CCX_NO_QUOTA_PROBE": "0"}
        self.j("route", "--b", "4", env=env)
        self.j("run", "--from", "user", "--to", "codex", "--tier", "T1", "--review", "off", "x", env=env)
        self.assertEqual(len(self.calls()), 1)

    def test_data_and_doctor_expose_freshness_without_probes(self):
        self.claude()
        self.codex()
        data = ui.quota_view(ui.Reader(self.p))
        self.assertTrue(all("freshness" in row and "resets_at" in row for row in data))
        self.assertTrue(any(row["agent"] == "claude" for row in data))
        r = self.ccx("doctor")
        self.assertIn("subscription quota", r.stdout)
        self.assertIn("five_hour 82%", r.stdout)
        self.assertTrue(all(c["argv"] in (["--version"], ["auth", "status"], ["login", "status"])
                            or c["argv"][:2] == ["mcp", "get"] for c in self.calls()))

    def test_quota_fallback_receipt_uses_requested_chinese_sentence(self):
        out = self.j("run", "--from", "user", "--to", "claude", "--tier", "T2", "--review", "off", "x",
                     env={"FAKE_STATUS_CLAUDE": "quota"})
        message = out["quota_fallback"]["message"]
        self.assertTrue(message.startswith(f"因 claude 限额改派 codex，重置时间 {quota.reset_text(1798000000)}"),
                        message)

    def test_stale_codex_route_probes_once_and_uses_new_reading(self):
        self.claude(0.2)
        self.codex(0.16, age=70)
        env = {"CCX_NO_QUOTA_PROBE": "0", "FAKE_QUOTA_CODEX": json.dumps({"primary": {
            "used_percent": 90, "window_minutes": 300, "resets_at": self.reset}})}
        out = self.j("route", "--b", "4", env=env)
        self.assertTrue(out["rung"].startswith("claude:"), out)
        self.j("route", "--b", "4", env=env)
        self.assertEqual([c["agent"] for c in self.model_calls()], ["codex"])
        self.assertLess(quota.pressure(self.p)["freshness"]["codex"], 1)

    def test_codex_refresh_obeys_configured_reading_age(self):
        self.config('[quota]\nauto_refresh_min = 30\n')
        self.codex(0.16, age=40)
        out = self.j("quota", "--refresh", env={"FAKE_QUOTA_CODEX": json.dumps({"primary": {
            "used_percent": 20, "window_minutes": 300, "resets_at": self.reset}})})
        self.assertEqual(out["refresh"]["codex"]["source"], "probe")
        self.assertLess(out["freshness"]["codex"], 1)
        self.assertEqual(out["windows"]["codex"]["primary"]["used"], 0.2)

    def test_codex_failed_probe_keeps_old_age_and_cooldown(self):
        self.claude(0.2)
        self.codex(0.16, age=70)
        env = {"CCX_NO_QUOTA_PROBE": "0"}
        self.j("route", "--b", "4", env=env)
        self.j("route", "--b", "4", env=env)
        state = json.loads((self.p.state / "quota-refresh.json").read_text(encoding="utf-8"))
        self.assertEqual(state["codex"]["source"], "probe")
        self.assertEqual(state["codex"]["readings"], 0)
        self.assertIn("no quota windows", state["codex"]["error"])
        self.assertGreater(quota.pressure(self.p)["freshness"]["codex"], 60)
        self.assertEqual([c["agent"] for c in self.model_calls()], ["codex"])
