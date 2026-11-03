"""P0-17: quota routing and bounded refresh/fallback. CLI wiring runs outside the repo, with fakes only."""
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from test_ccx import Env, FAKES
from ccx import quota, ui
from ccx.config import Paths, load_config
from ccx.plan import quota_candidates


class TestQuotaRouting(Env):
    def setUp(self):
        super().setUp()
        for agent in ("gemini", "dsh"):
            key = f"CCX_{agent.upper()}_BIN"
            self.env[key] = os.environ[key] = str(FAKES / f"fake_{agent}.py")
        self.env["CCX_LEAD_VIEW"] = "line"
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
        self.assertEqual(set(out["quota_routing"]["eligible"]), {"claude", "codex", "gemini", "dsh"})
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
        self.assertIsNone(pr["pace"]["claude"]["five_hour"]["projected_at_reset"])
        self.assertAlmostEqual(pr["freshness"]["claude"], 10, delta=0.2)
        ranked = quota_candidates(self.p, load_config(self.p), ["claude", "codex"])
        self.assertEqual(ranked["eligible"], ["claude", "codex"])

    def test_auto_run_keeps_snapshot_in_record_without_extra_ledger_rows(self):
        self.claude()
        self.codex()
        out = self.j("run", "--from", "user", "--b", "4", "--review", "off", "implement parser")
        self.assertEqual(out["agent"], "codex")
        snap = self.record(out)["quota_at_start"]
        self.assertEqual(snap["pace"]["claude"]["five_hour"]["used"], 0.82)
        rows = [json.loads(x) for x in self.p.ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], out["run_id"])
        self.assertEqual(rows[0]["attempts"], 1)

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

    def test_never_used_subscriptions_are_not_automatically_probed(self):
        env = {"CCX_NO_QUOTA_PROBE": "0"}
        self.j("route", "--b", "4", env=env)
        self.assertEqual(self.model_calls(), [])
        out = self.j("run", "--from", "user", "--to", "codex", "--tier", "T1", "--review", "off", "x", env=env)
        self.assertEqual([c["agent"] for c in self.model_calls()], ["codex"])
        rec = self.record(out)
        self.assertEqual(rec["quota_at_start"]["freshness"], {"claude": None, "codex": None})
        self.assertEqual(len(rec["attempts"]), 1)
        rows = [json.loads(x) for x in self.p.ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempts"], 1)

    def test_latest_reading_controls_automatic_refresh(self):
        self.claude(0.2, age=70, window="seven_day")
        self.claude(0.2)
        self.j("route", "--b", "4", env={"CCX_NO_QUOTA_PROBE": "0"})
        self.assertEqual(self.model_calls(), [])
        self.assertLess(quota.pressure(self.p)["freshness"]["claude"], 1)

    def test_manual_probes_leave_existing_runs_and_ledger_unchanged(self):
        out = self.j("run", "--from", "user", "--to", "codex", "--tier", "T1", "--review", "off", "x")
        run_file = self.p.runs / out["run_id"] / "run.json"
        before_run, before_ledger = run_file.read_bytes(), self.p.ledger.read_bytes()
        before_dirs = sorted(d.name for d in self.p.runs.iterdir())
        result = self.j("quota", "--refresh", env={"FAKE_QUOTA_CLAUDE": json.dumps({
            "five_hour": {"utilization": 0.2, "resetsAt": self.reset}}), "FAKE_QUOTA_CODEX": json.dumps({
            "primary": {"used_percent": 16, "window_minutes": 300, "resets_at": self.reset}})})
        self.assertEqual(result["refresh"]["claude"]["cost_usd"], 0.0004)
        self.assertEqual(run_file.read_bytes(), before_run)
        self.assertEqual(self.p.ledger.read_bytes(), before_ledger)
        self.assertEqual(sorted(d.name for d in self.p.runs.iterdir()), before_dirs)
        log = [json.loads(x) for x in (self.p.state / "quota-refresh.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["agent"] for row in log], ["claude", "codex"])
        self.assertEqual(log[0]["cost_usd"], 0.0004)

    def test_quota_settings_round_trip_through_cli(self):
        cases = (("quota.auto_refresh_min", "30", 30), ("quota.avoid_above", "0.75", 0.75),
                 ("quota.routing", "off", "off"), ("quota.auto_refresh_min", "false", False))
        for key, raw, expected in cases:
            with self.subTest(key=key, raw=raw):
                self.assertEqual(self.j("config", "set", key, raw), {key: expected})
                self.assertEqual(self.j("config", "get", key), {key: expected})
        self.assertNotEqual(self.ccx("config", "set", "quota.routing", "maybe").returncode, 0)

    def test_probes_use_cli_login_without_inherited_credentials(self):
        env = {key: "fake-secret" for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY",
               "CODEX_API_KEY", "DEEPSEEK_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
        env.update(ANTHROPIC_BASE_URL="https://provider.invalid", OPENAI_BASE_URL="https://provider.invalid")
        self.j("quota", "--refresh", env=env)
        self.assertEqual([c["agent"] for c in self.model_calls()], ["claude", "codex"])
        for call in self.model_calls():
            self.assertEqual(call["credential_vars"], [])
            self.assertFalse(call.get("host_auth"))

    def test_keyword_route_keeps_main_candidates_without_quota_reason(self):
        out = self.j("route", "implement parser")
        self.assertIn("codex", out)
        self.assertIn("claude", out)
        self.assertNotIn("gemini", out)
        self.assertNotIn("dsh", out)
        self.assertNotIn("recommended_agent", out)
        # Main's keyword recommendation is not filtered by CLI discovery.
        from ccx.cli import parse
        from ccx.commands.delegation import _route
        with mock.patch("ccx.commands.delegation.installed_agents", return_value=["codex"]):
            out = _route(parse(["route", "implement parser"]))
        self.assertIn("claude", out)

    def test_switching_from_provider_to_subscription_strips_the_keys_too(self):
        from ccx.delegate import _child_env
        inherited = {"ANTHROPIC_BASE_URL": "https://provider.invalid", "ANTHROPIC_API_KEY": "fake-key",
                     "OPENAI_API_KEY": "fake-key", "OPENAI_BASE_URL": "https://provider.invalid",
                     "CLAUDE_CODE_OAUTH_TOKEN": "fake-token"}
        with mock.patch.dict(os.environ, inherited), mock.patch("ccx.delegate._provider_url", return_value=True):
            env = _child_env("claude", "quota-env-test")
        for key in inherited:
            self.assertNotIn(key, env)
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.home_claude))

    def test_quota_off_restores_rubric_candidates_and_keyword_target(self):
        from ccx.commands.common import cash_ready, installed_agents
        from ccx import learn
        self.config('[quota]\nrouting = "off"\n')
        self.claude(0.95)
        self.codex(0.96)
        cfg = load_config(self.p)
        candidates = installed_agents() + cash_ready(self.p, cfg, {})
        expected = learn.pick(self.p, 4, candidates, "save")
        out = self.j("route", "--b", "4")
        self.assertEqual(out["rung"], expected["rung"])
        self.assertEqual(out["quota_routing"]["candidates"], candidates)
        out = self.j("route", "implement parser")
        self.assertEqual([ag for ag in ("codex", "claude", "gemini", "dsh") if ag in out], ["codex", "claude"])
        self.assertNotIn("recommended_agent", out)
        out = self.j("run", "--from", "codex", "--tier", "T2", "--review", "off", "implement parser")
        self.assertEqual(out["agent"], "claude")

    def test_both_tight_never_pick_other_installed_clis_or_suggest_running(self):
        from ccx.commands.delegation import _route_summary
        self.claude(0.95)
        self.codex(0.96)
        for args in (("--b", "4"), ("--b", "4", "--lead", "claude:opus:max", "--lead-ctx", "1000"),
                     ("implement parser",)):
            out = self.j("route", *args)
            self.assertEqual(set(out["quota_routing"]["candidates"]), {"claude", "codex"})
            self.assertTrue(out["quota_routing"]["all_tight"])
            message = "\n".join(_route_summary(out))
            self.assertNotIn("ccx run", message)
            self.assertIn(f"建议自己做或等重置到 {quota.reset_text(self.reset)}", message)
            self.assertNotIn("ccx run", json.dumps(out.get("choice", {})))
        out = self.j("run", "--from", "codex", "--tier", "T2", "--review", "off", "implement parser")
        self.assertFalse(out["delegated"])
        self.assertEqual(self.model_calls(), [])

    def test_successful_compact_receipt_keeps_quota_fallback(self):
        out = self.j("run", "--from", "user", "--to", "claude", "--tier", "T2", "--review", "off",
                     "--check", "python -c pass", "implement parser", env={"FAKE_STATUS_CLAUDE": "quota"})
        self.assertEqual(out.get("view"), "line", out)
        self.assertIn("因 claude 限额改派 codex，重置", out["quota_fallback"]["message"])
        shown = self.j("show", out["run_id"], "--wait", "5")
        self.assertEqual(shown["quota_fallback"], out["quota_fallback"])

    def test_at_start_never_creates_or_updates_the_codex_cache(self):
        self.codex()
        before = sorted(self.hub.rglob("*"))
        self.assertEqual(quota.at_start(self.p)["pace"]["codex"]["primary"]["used"], 0.16)
        self.assertEqual(sorted(self.hub.rglob("*")), before)
        quota.codex_readings(p=self.p)
        cache = self.p.state / "codex-quota-cache.json"
        before = cache.read_bytes(), cache.stat().st_mtime_ns
        self.codex(0.4)
        self.assertEqual(quota.at_start(self.p)["pace"]["codex"]["primary"]["used"], 0.4)
        self.assertEqual((cache.read_bytes(), cache.stat().st_mtime_ns), before)

    def test_route_and_run_scan_each_vendor_once_per_call(self):
        self.claude(0.2)
        self.codex()
        counts = self.work / "quota-scans.json"
        for args in (("route", "--b", "4", "--lead", "claude:opus:max", "--lead-ctx", "1000"),
                     ("run", "--from", "user", "--b", "4", "--review", "off", "implement parser")):
            r = subprocess.run([sys.executable, str(FAKES / "quota_count_cli.py"), *args], cwd=self.work,
                               env={**self.env, "CCX_NO_QUOTA_PROBE": "0", "FAKE_QUOTA_SCANS": str(counts)},
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(counts.read_text(encoding="utf-8")), {"claude": 1, "codex": 1})

    def test_reading_cache_ends_with_the_call(self):
        self.codex()
        with quota.reading_scope():
            self.assertEqual(quota.at_start(self.p)["pace"]["codex"]["primary"]["used"], 0.16)
            self.codex(0.4)
            self.assertEqual(quota.at_start(self.p)["pace"]["codex"]["primary"]["used"], 0.16)
        with quota.reading_scope():
            self.assertEqual(quota.at_start(self.p)["pace"]["codex"]["primary"]["used"], 0.4)

    def test_ready_route_demotes_missing_login_before_cost_pick(self):
        from ccx.agents import cache_login
        cache_login(self.p, "codex", False)
        (self.home_claude / ".credentials.json").touch()
        out = self.j("route", "--b", "4")
        ranked = out["quota_routing"]
        self.assertEqual(ranked["candidates"], ["claude", "codex"])
        self.assertEqual(ranked["eligible"], ["claude"])
        self.assertIn("codex: installed, not logged in", ranked["why"])
        self.assertEqual(ranked["readiness"]["codex"]["state"], "not_logged_in")
        self.assertEqual(ranked["readiness"]["claude"]["state"], "ready")
        self.assertTrue(out["rung"].startswith("claude:"), out)
        self.assertEqual(self.calls(), [])

    def test_require_ready_false_keeps_original_candidates(self):
        self.config('[routing]\nrequire_ready = false\n')
        (self.home_claude / ".credentials.json").touch()
        out = self.j("route", "--b", "4")
        self.assertEqual(out["quota_routing"]["candidates"], ["codex", "claude"])
        self.assertEqual(out["quota_routing"]["eligible"], ["codex", "claude"])
        self.assertNotIn("readiness", out["quota_routing"])

    def test_all_unready_reports_missing_evidence_and_keeps_fallback(self):
        from ccx.agents import cache_login
        cache_login(self.p, "codex", False)
        cache_login(self.p, "claude", False)
        out = self.j("route", "--b", "4")
        ranked = out["quota_routing"]
        self.assertTrue(ranked["all_unready"])
        self.assertIn("all candidates lack readiness evidence", ranked["why"])
        self.assertEqual(ranked["eligible"], ["codex", "claude"])

    def test_named_route_and_run_refresh_only_the_named_candidate(self):
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        env = {"CCX_NO_QUOTA_PROBE": "0"}
        routed = self.ccx("route", "--to", "codex", "--b", "4", env=env)
        self.assertEqual(routed.returncode, 0, routed.stdout + routed.stderr)
        self.assertIn("refreshing codex quota", routed.stderr)
        self.assertIn("warning: codex quota refresh failed", routed.stderr)
        self.assertNotIn("refreshing claude quota", routed.stderr)
        self.j("run", "--from", "user", "--to", "codex", "--tier", "T1", "--review", "off", "x", env=env)
        self.assertEqual([c["agent"] for c in self.model_calls()], ["codex", "codex"])

    def test_auto_refresh_keeps_both_candidates_despite_negative_login_signal(self):
        from ccx.agents import cache_login
        cache_login(self.p, "codex", False)
        (self.home_claude / ".credentials.json").touch()
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        self.j("route", "--b", "4", env={"CCX_NO_QUOTA_PROBE": "0"})
        self.assertEqual([c["agent"] for c in self.model_calls()], ["claude", "codex"])

    def test_probe_timeout_is_configurable_and_only_warns(self):
        self.config('[quota]\nprobe_timeout = 0.2\n')
        start = time.monotonic()
        result = self.ccx("quota", "--probe", env={"FAKE_STATUS_CLAUDE": "hang", "FAKE_HANG_S": "10"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(time.monotonic() - start, 5)
        self.assertIn("warning: claude quota refresh failed: TimeoutExpired", result.stderr)
        state = json.loads((self.p.state / "quota-refresh.json").read_text(encoding="utf-8"))
        self.assertIn("TimeoutExpired", state["claude"]["error"])

    def test_readiness_and_timeout_settings_round_trip(self):
        for key, raw, expected in (("routing.require_ready", "false", False),
                                   ("quota.probe_timeout", "7.5", 7.5)):
            self.assertEqual(self.j("config", "set", key, raw), {key: expected})
            self.assertEqual(self.j("config", "get", key), {key: expected})
        for raw in ("0", "-1", "nan", "inf"):
            self.assertNotEqual(self.ccx("config", "set", "quota.probe_timeout", raw).returncode, 0)

    def test_other_role_refreshes_build_and_other_candidate_once(self):
        (self.home_claude / ".credentials.json").touch()
        (self.home_codex / "auth.json").touch()
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        self.j("roles", "set", "build", "codex:gpt-6.1-sol:auto")
        self.j("roles", "set", "review", "other:auto")
        out = self.j("route", "--role", "review", "--b", "4", env={"CCX_NO_QUOTA_PROBE": "0"})
        self.assertTrue(out["rung"].startswith("claude:"), out)
        self.assertCountEqual([c["agent"] for c in self.model_calls()], ["claude", "codex"])

    def test_keyword_route_refreshes_only_named_candidate(self):
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        expected = []
        for agent in ("codex", "claude", "gemini"):
            with self.subTest(agent=agent):
                out = self.j("route", "--to", agent, "implement parser", env={"CCX_NO_QUOTA_PROBE": "0"})
                if agent != "gemini":
                    expected.append(agent)
                self.assertEqual([c["agent"] for c in self.model_calls()], expected)
                self.assertEqual(out["quota_routing"]["candidates"], [agent])

    def test_auto_keyword_route_refreshes_both_subscriptions_with_one_tier_vendor(self):
        self.config('[tiers.T2]\nclaude = false\n')
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        out = self.j("route", "implement parser", env={"CCX_NO_QUOTA_PROBE": "0"})
        self.assertEqual([c["agent"] for c in self.model_calls()], ["claude", "codex"])
        self.assertEqual(out["quota_routing"]["candidates"], ["codex"])

    def test_keyword_run_uses_ready_candidate(self):
        from ccx.agents import cache_login
        cache_login(self.p, "codex", False)
        (self.home_claude / ".credentials.json").touch()
        out = self.j("run", "--from", "user", "--review", "off", "--no-escalate", "--no-fallback",
                     "implement parser")
        self.assertEqual(out["agent"], "claude")
        route = self.record(out)["route"]
        self.assertEqual(route["quota_routing"]["candidates"], ["claude", "codex"])
        self.assertIn("codex: installed, not logged in", route["why"]["readiness"])
        self.assertEqual([c["agent"] for c in self.model_calls()], ["claude"])

    def test_keyword_run_require_ready_false_keeps_original_target(self):
        self.config('[routing]\nrequire_ready = false\n')
        (self.home_claude / ".credentials.json").touch()
        out = self.j("run", "--from", "user", "--review", "off", "--no-escalate", "--no-fallback",
                     "implement parser")
        self.assertEqual(out["agent"], "codex")

    def test_named_run_alone_refreshes_only_its_candidate(self):
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        expected = []
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                out = self.j("run", "--from", "user", "--to", agent, "--tier", "T1", "--review", "off",
                             "--no-escalate", "--no-fallback", "implement parser", env={"CCX_NO_QUOTA_PROBE": "0"})
                self.assertEqual(out["agent"], agent)
                expected.extend([agent, agent])  # one quota probe, one task invocation
                self.assertEqual([c["agent"] for c in self.model_calls()], expected)

    def test_file_login_is_seen_immediately_within_refresh_interval(self):
        from ccx.agents import readiness
        cfg = load_config(self.p)
        for agent, auth in (("codex", self.home_codex / "auth.json"),
                            ("claude", self.home_claude / ".credentials.json")):
            with self.subTest(agent=agent):
                self.assertFalse(readiness(self.p, cfg, [agent])[agent]["ready"])
                auth.touch()
                self.assertTrue(readiness(self.p, cfg, [agent])[agent]["ready"])
                auth.unlink()
                self.assertFalse(readiness(self.p, cfg, [agent])[agent]["ready"])
        self.assertEqual(self.calls(), [])

    def test_only_doctor_result_is_cached_for_refresh_interval(self):
        from ccx.agents import cache_login, readiness
        cfg = load_config(self.p)
        cache_login(self.p, "codex", True)
        row = readiness(self.p, cfg, ["codex"])["codex"]
        self.assertTrue(row["ready"])
        self.assertEqual(row["source"], "doctor")
        with mock.patch("ccx.agents.time.time", return_value=time.time() + 3601):
            self.assertFalse(readiness(self.p, cfg, ["codex"])["codex"]["ready"])
        self.assertEqual(self.calls(), [])

    def test_no_login_evidence_does_not_drop_quota_fallback(self):
        (self.home_claude / ".credentials.json").touch()
        out = self.j("run", "--from", "user", "--to", "claude", "--tier", "T2", "--no-escalate",
                     "--review", "off", "implement parser", env={"FAKE_STATUS_CLAUDE": "quota"})
        record = self.record(out)
        self.assertEqual([a["agent"] for a in record["attempts"]], ["claude", "codex"])
        self.assertIn("keychain or env login possible", record["route"]["fallback"]["why"])

    def test_no_login_evidence_preserves_all_unready_fallback_order(self):
        from ccx.delegate import Request
        from ccx.plan import _fallback_plan
        req = Request(to="claude", brief="implement parser", route={})
        cfg = load_config(self.p)
        result = _fallback_plan(req, self.p, cfg, {"agent": "claude", "tier": "T2"})
        self.assertEqual(result["agent"], "codex")
        self.assertIn("keychain or env login possible", result["why"])

    def test_ready_quota_tight_keeps_unready_healthy_fallback(self):
        from ccx.agents import cache_login
        cache_login(self.p, "codex", False)
        (self.home_claude / ".credentials.json").touch()
        self.claude(0.95)
        self.codex(0.2)
        out = self.j("route", "--b", "4")
        self.assertFalse(out["quota_routing"]["all_tight"])
        self.assertEqual(out["quota_routing"]["eligible"], ["codex"])
        self.assertTrue(out["rung"].startswith("codex:"), out)
        self.assertIn("no login evidence for codex, trying anyway", out["quota_routing"]["why"])

    def test_auto_named_model_refreshes_both_subscriptions_once(self):
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        out = self.j("run", "--from", "user", "--model", "gpt-6-luna", "--effort", "low", "--review", "off",
                     "--no-escalate", "--no-fallback", "implement parser", env={"CCX_NO_QUOTA_PROBE": "0"})
        self.assertEqual(out["agent"], "codex")
        self.assertEqual([c["agent"] for c in self.model_calls()], ["claude", "codex", "codex"])

    def test_auto_keyword_run_refreshes_both_subscriptions_with_one_tier_vendor(self):
        self.config('[tiers.T2]\nclaude = false\n')
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        self.j("run", "--from", "user", "--review", "off", "--no-escalate", "--no-fallback",
               "implement parser", env={"CCX_NO_QUOTA_PROBE": "0"})
        self.assertEqual([c["agent"] for c in self.model_calls()], ["claude", "codex", "codex"])

    def test_fixed_role_refreshes_only_assigned_vendor(self):
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        self.j("roles", "set", "build", "codex:gpt-6.1-sol:auto")
        self.j("route", "--role", "build", "--b", "4", env={"CCX_NO_QUOTA_PROBE": "0"})
        self.assertEqual([c["agent"] for c in self.model_calls()], ["codex"])

    def test_named_keyword_route_preserves_other_vendor_fields(self):
        self.claude(0.2, age=70)
        self.codex(0.2, age=70)
        out = self.j("route", "--to", "codex", "implement parser", env={"CCX_NO_QUOTA_PROBE": "0"})
        self.assertIn("codex", out)
        self.assertIn("claude", out)
        self.assertEqual(out["quota_routing"]["candidates"], ["codex"])
        self.assertEqual([c["agent"] for c in self.model_calls()], ["codex"])

    def test_route_readiness_is_stable_when_internal_cache_timestamp_changes(self):
        from ccx.cli import parse
        from ccx.commands.delegation import _route
        for found in (None, str(FAKES / "fake_codex.py")):
            with self.subTest(installed=bool(found)), mock.patch("ccx.runners.find_bin", return_value=found):
                args = parse(["route", "--b", "4", "--to", "codex", "Fix a parser"])
                with mock.patch("ccx.agents.time.time", return_value=self.now):
                    before = _route(args)
                first_cache = json.loads((self.p.state / "agent-readiness.json").read_text(encoding="utf-8"))
                with mock.patch("ccx.agents.time.time", return_value=self.now + 5):
                    after = _route(args)
                second_cache = json.loads((self.p.state / "agent-readiness.json").read_text(encoding="utf-8"))
                self.assertNotEqual(first_cache["codex"]["ts"], second_cache["codex"]["ts"])
                self.assertEqual(before, after)
                row = after["quota_routing"]["readiness"]["codex"]
                self.assertEqual(set(row), {"state", "why"})
                self.assertEqual(row["state"], "unknown")
                self.assertIn("keychain or env login possible" if found else "not installed", row["why"])

    def test_route_command_output_is_identical_on_repeated_calls(self):
        for args in (("route", "--b", "4", "--to", "codex", "Fix a parser"),
                     ("route", "implement a parser")):
            with self.subTest(args=args):
                self.assertEqual(self.j(*args), self.j(*args))

    def test_route_outputs_stable_readiness_and_keeps_live_quota_projection(self):
        from test_ccx import ROOT
        self.claude(0.10, age=7 * 60, window="seven_day")
        self.claude(0.50, window="seven_day")
        self.codex()
        wrapper = self.work / "route-at-time.py"
        wrapper.write_text(
            "import runpy, sys\nfrom unittest import mock\n"
            "now, entry = float(sys.argv.pop(1)), sys.argv.pop(1)\n"
            "sys.argv[0] = entry\n"
            "with mock.patch('time.time', return_value=now):\n"
            "    runpy.run_path(entry, run_name='__main__')\n", encoding="utf-8")
        for args in (("route", "--b", "4"), ("route", "implement parser"),
                     ("route", "--b", "4", "--lead", "claude:sonnet:high", "--lead-ctx", "0")):
            with self.subTest(args=args):
                results = []
                for now in (self.now, self.now + 20 * 60):
                    result = subprocess.run([sys.executable, str(wrapper), str(now), str(ROOT / "ccx.py"), *args],
                                            cwd=self.work, env=self.env, capture_output=True, text=True,
                                            encoding="utf-8")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    results.append(json.loads(result.stdout))
                self.assertGreater(results[0]["quota_routing"]["tight"]["claude"]["projected_at_reset"], 1)
                before, after = (result["quota_routing"] for result in results)
                self.assertEqual(before["readiness"], after["readiness"])
                for row in after["readiness"].values():
                    self.assertEqual(set(row), {"state", "why"})
                # The projection already exists on main; preserve its real-time calculation.
                self.assertLess(after["tight"]["claude"]["projected_at_reset"],
                                before["tight"]["claude"]["projected_at_reset"])
                self.assertNotIn("freshness", before)
                self.assertNotIn("freshness", after)

    def test_explicit_tier_role_keeps_why_mapping_for_effort_receipt(self):
        self.j("roles", "set", "build", "codex:gpt-6.1-sol:auto")
        out = self.j("run", "--from", "user", "--role", "build", "--tier", "T2", "--mode", "read",
                     "--review", "off", "--no-escalate", "--no-fallback", "Read parser")
        route = self.record(out)["route"]
        self.assertIsInstance(route["why"], dict)
        self.assertIn("readiness", route["why"])
        self.assertIn("effort=auto", route["role_effort_reason"])

    @unittest.skipUnless(os.name == "nt", "Windows cmd shim process tree")
    def test_probe_timeout_kills_cmd_shim_descendants(self):
        from ccx.runners import pid_alive, kill_tree
        pid_file = self.work / "probe-child.pid"
        child = self.work / "probe-child.py"
        parent = self.work / "probe-parent.py"
        shim = self.work / "probe.cmd"
        child.write_text("import os, time\nfrom pathlib import Path\n"
                         f"Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
                         "time.sleep(20)\n", encoding="utf-8")
        parent.write_text("import subprocess, sys, time\n"
                          f"subprocess.Popen([sys.executable, {str(child)!r}])\ntime.sleep(20)\n", encoding="utf-8")
        shim.write_text(f'@echo off\n"{sys.executable}" "{parent}" %*\n', encoding="utf-8")
        self.config('[quota]\nprobe_timeout = 1.5\n')
        start = time.monotonic()
        result = self.ccx("quota", "--probe", env={"CCX_CLAUDE_BIN": str(shim)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(time.monotonic() - start, 8)
        self.assertTrue(pid_file.is_file(), result.stderr)
        pid = int(pid_file.read_text(encoding="utf-8"))
        try:
            deadline = time.monotonic() + 2
            while pid_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(pid_alive(pid), f"quota child {pid} survived timeout: {result.stderr}")
        finally:
            if pid_alive(pid):
                kill_tree(pid)
