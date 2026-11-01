"""v0.2 part 4: usage accounting, dashboard, settings knob, A/B self-run samples, publishing."""
import json
import subprocess
import time
import unittest
from datetime import datetime, timezone

from test_ccx import Env


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


class ReportEnv(Env):
    def j(self, *args, env=None, code=0):
        r = self.ccx(*args, env=env)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def claude_transcript(self, session, n=2, ts=None, model="claude-opus-5-5"):
        d = self.home_claude / "projects" / "-work"
        d.mkdir(parents=True, exist_ok=True)
        ts = ts or time.time()
        with open(d / f"{session}.jsonl", "a", encoding="utf-8") as f:
            for i in range(n):
                msg = {"type": "assistant", "sessionId": session, "timestamp": iso(ts + i * 0.01),
                       "message": {"id": f"{session}-m{i}", "model": model,
                                   "usage": {"input_tokens": 10, "cache_creation_input_tokens": 1000,
                                             "cache_read_input_tokens": 20000, "output_tokens": 500,
                                             "cache_creation": {"ephemeral_1h_input_tokens": 1000}}}}
                f.write(json.dumps(msg) + "\n")
                f.write(json.dumps(msg) + "\n")      # same message streamed twice -> counted once

    def codex_rollout(self, session, ts=None):
        d = self.home_codex / "sessions" / "2026" / "10" / "22"
        d.mkdir(parents=True, exist_ok=True)
        ts = ts or time.time()
        lines = [{"timestamp": iso(ts), "type": "session_meta", "payload": {"id": session}},
                 {"timestamp": iso(ts), "type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
                 {"timestamp": iso(ts + 1), "type": "event_msg", "payload": {
                     "type": "token_count",
                     "info": {"total_token_usage": {"input_tokens": 5000, "cached_input_tokens": 4000,
                                                    "output_tokens": 300},
                              "last_token_usage": {"input_tokens": 5000, "cached_input_tokens": 4000,
                                                   "output_tokens": 300}},
                     "rate_limits": {"primary": {"used_percent": 42.0, "window_minutes": 300}}}},
                 # Codex repeats token_count lines (e.g. a rate-limit refresh): must not count twice
                 {"timestamp": iso(ts + 2), "type": "event_msg", "payload": {
                     "type": "token_count",
                     "info": {"total_token_usage": {"input_tokens": 5000, "cached_input_tokens": 4000,
                                                    "output_tokens": 300},
                              "last_token_usage": {"input_tokens": 5000, "cached_input_tokens": 4000,
                                                   "output_tokens": 300}},
                     "rate_limits": {"primary": {"used_percent": 42.0, "window_minutes": 300}}}}]
        (d / f"rollout-{session}.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")


class TestReport(ReportEnv):
    def test_report_lead_and_sub_streams(self):
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "implement")
        self.j("verify", out["run_id"], "--ok", "1")
        out2 = self.j("run", "--from", "codex", "--to", "claude", "--tier", "T2", "review")
        sub_session = json.loads((self.hub / "ccx" / "runs" / out2["run_id"] / "run.json").read_text())["session_id"]
        self.claude_transcript("lead-1")
        self.claude_transcript(sub_session)          # sub-agent transcript: must not count as lead
        self.codex_rollout("codex-lead-1")
        res = self.j("report", "--days", "7")
        html = (self.hub / "ccx" / "report" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Spend per day", html)
        self.assertIn("prefers-color-scheme:dark", html)
        s = json.loads((self.hub / "ccx" / "report" / "summary.json").read_text(encoding="utf-8"))
        streams = {(x["agent"], x["role"]): x for x in s["streams"]}
        self.assertEqual(streams[("claude", "lead")]["events"], 2)        # de-duplicated, sub excluded
        self.assertEqual(streams[("claude", "lead")]["cached_input_tokens"], 40000)
        self.assertEqual(streams[("codex", "lead")]["input_tokens"], 1000)  # 5000 - 4000 cached
        self.assertEqual(streams[("codex", "sub")]["events"], 1)
        self.assertEqual(streams[("claude", "sub")]["events"], 1)
        self.assertEqual(s["totals"]["runs"], 2)
        self.assertEqual(s["totals"]["verified"], 1)
        self.assertIsNotNone(s["totals"]["saving"])
        self.assertEqual(s["quota"][0]["used_percent"], 42.0)
        self.assertGreater(res["totals"]["ae"], 0)
        st = self.j("stats", "--summary")
        self.assertIn("saving", st["totals"])
        self.assertEqual(st["totals"]["saving_kind"], "model")               # no trial yet: shown as a model
        self.assertIn("not measured yet", html)                              # P1-4: spend only until ccx trial
        self.assertNotIn("Estimated saving", html)

    def test_saving_from_a_trial_is_measured(self):
        import os
        from unittest import mock
        from ccx import report
        from ccx.config import paths
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "implement")
        self.j("verify", out["run_id"], "--ok", "1")
        arm = {"n": 10, "lead_tokens_mean": 1, "lead_usd_mean": 0.1, "sub_usd_mean": 0, "total_usd_mean": 0.1,
               "minutes_mean": 1, "ok_rate": 1.0}
        tr = {"trial": {"id": "t1"}, "enough": True, "saving_per_task_usd": 0.04, "saving_ci95": [0.01, 0.07],
              "arms": {"self": arm, "delegated": arm}, "running": False, "buckets": []}
        with mock.patch.dict(os.environ, self.env), mock.patch.object(report, "_trial", return_value=tr):
            p = paths()
            s = report.summarize(p, report.collect(p, 7, include_lead=False))
            html = report.render_html(s)
        self.assertEqual((s["totals"]["saving_kind"], s["totals"]["saving"], s["totals"]["saving_ci95"]),
                         ("measured", 0.04, [0.01, 0.07]))                   # one delegated run held up
        self.assertIn("Saving (measured)", html)

    def test_empty_report(self):
        self.j("report", "--no-lead")
        self.assertIn("No runs yet", (self.hub / "ccx" / "report" / "index.html").read_text(encoding="utf-8"))

    def test_publish_to_private_repo(self):
        remote = self.work.parent / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        clone = self.work.parent / "clone"
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            subprocess.run(["git", "config", k, v], cwd=clone, check=True)
        self.j("config", "set", "report.publish_dir", str(clone))
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "x")
        res = self.j("report", "--publish", "--no-lead")
        self.assertTrue(res["publish"]["committed"])
        self.assertTrue(res["publish"]["pushed"])
        self.assertTrue((clone / "usage" / "index.html").exists())

    def test_publish_needs_target(self):
        r = self.ccx("report", "--publish", "--no-lead")
        self.assertEqual(r.returncode, 3)
        self.assertIn("publish_dir", r.stdout)


class TestBillingReport(ReportEnv):
    def test_subscription_stats_puts_quota_before_api_equivalent_usd(self):
        (self.hub / "ccx").mkdir(parents=True, exist_ok=True)
        (self.hub / "ccx" / "tiers.toml").write_text('[billing.providers.codex]\nquota_unit = 2\n',
                                                      encoding="utf-8")
        self.j("config", "set", "billing.mode", "subscription")
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--no-ab", "read a file")
        r = self.ccx("stats")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cols, values = [line.split() for line in r.stdout.splitlines()]
        self.assertEqual(cols[-3:], ["quota_units", "api_equivalent_usd", "cost_usd"])
        row = dict(zip(cols, values))
        self.assertEqual(float(row["quota_units"]), 2700)
        self.assertGreater(float(row["api_equivalent_usd"]), 0)
        summary = self.j("stats", "--summary")
        self.assertEqual(summary["billing"]["mode"], "subscription")
        self.assertEqual(next(iter(summary["spend"])), "sub_agents_quota_units")
        self.assertEqual(summary["spend"]["sub_agents_quota_units"], 2700)
        self.assertEqual(summary["spend"]["cost_per_success_quota_units"], 2700)
        self.assertEqual(summary["spend"]["sub_agents_usd"], summary["totals"]["sub_ae"])
        self.j("config", "set", "billing.mode", "api")
        summary = self.j("stats", "--summary")
        self.assertEqual(next(iter(summary["spend"])), "sub_agents_usd")
        self.assertEqual(summary["spend"]["sub_agents_quota_units"], 2700)

    def test_api_table_keeps_its_existing_columns(self):
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--no-ab", "read a file")
        r = self.ccx("stats")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[0].split(),
                         ["agent", "tier", "runs", "done_rate", "escalated", "avg_input", "avg_cached",
                          "avg_output", "avg_seconds", "cost_usd"])
        self.j("report", "--no-lead")
        f = self.hub / "ccx" / "report" / "index.html"
        html = f.read_text(encoding="utf-8")
        self.assertIn("Total spend (AE$)", html)
        self.assertIn('<th class="r">tokens</th><th class="r">AE$</th>', html)
        self.assertNotIn('<th class="r">quota units</th>', html)

    def test_subscription_report_exposes_both_bases(self):
        (self.hub / "ccx").mkdir(parents=True, exist_ok=True)
        (self.hub / "ccx" / "tiers.toml").write_text(
            '[billing]\nmode = "subscription"\n[billing.providers.codex]\nquota_unit = 2\n', encoding="utf-8")
        self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--no-ab", "read a file")
        out = self.j("report", "--no-lead")
        self.assertEqual(out["billing"]["mode"], "subscription")
        self.assertEqual((out["totals"]["quota_units"], out["totals"]["sub_quota_units"]), (2700, 2700))
        html = (self.hub / "ccx" / "report" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Total usage (quota units)", html)
        self.assertIn("API-equivalent USD", html)
        self.assertIn('<th class="r">quota units</th><th class="r">AE$</th>', html)
        summary = json.loads((self.hub / "ccx" / "report" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["runs"][0]["quota_units"], 2700)
        self.assertEqual(summary["quota_days_series"][0]["codex:sub"], 2700)
        self.assertEqual(self.j("stats", "--summary")["totals"]["quota_units"], 2700)


class TestKnob(ReportEnv):
    def test_set_and_get(self):
        self.j("config", "set", "defaults.tradeoff", "0.3")
        self.assertEqual(self.j("config", "get", "defaults.tradeoff"), {"defaults.tradeoff": "0.3"})
        self.assertEqual(self.ccx("config", "set", "defaults.tradeoff", "2").returncode, 3)
        listing = self.j("config", "list")
        self.assertIn("defaults.ab_self_rate", listing)

    def test_knob_changes_target(self):
        cheap = self.j("route", "--b", "6", "--tradeoff", "save")
        self.j("config", "set", "defaults.tradeoff", "1")
        fast = self.j("route", "--b", "6")
        self.assertEqual(fast["tradeoff"], "1")
        self.assertGreaterEqual(fast["chain_p"] if "chain_p" in fast else fast["p"], cheap["p"])


class TestAB(ReportEnv):
    def test_sample_then_done(self):
        out = self.j("run", "--from", "claude", "--b", "4", "implement", env={"CCX_AB_RATE": "1"})
        self.assertFalse(out["delegated"])
        ab_id = out["route"]["ab"]
        self.assertIn("ab-sample", out["advice"])
        self.assertEqual(self.calls(), [])                       # nothing was delegated
        self.claude_transcript("lead-ab", ts=time.time())
        row = self.j("ab", "done", ab_id, "--ok", "1")
        self.assertEqual(row["type"], "selfrun")
        self.assertEqual(row["messages"], 2)
        self.assertGreater(row["ae_usd"], 0)
        self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "x")
        self.j("report", "--no-lead")
        s = json.loads((self.hub / "ccx" / "report" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(s["ab"][0]["self_n"], 1)
        self.assertEqual(s["ab"][0]["delegated_n"], 1)

    def test_opt_out(self):
        out = self.j("run", "--from", "claude", "--b", "4", "--no-ab", "implement", env={"CCX_AB_RATE": "1"})
        self.assertNotIn("delegated", out)


if __name__ == "__main__":
    unittest.main()


class TestMoneyFormat(unittest.TestCase):
    def test_negative_amounts_put_the_sign_first(self):
        from ccx.report import _usd
        self.assertEqual(_usd(-0.1382), "-$0.1382")
        self.assertEqual(_usd(-12.5), "-$12.50")
        self.assertEqual((_usd(0.0023), _usd(0), _usd(None)), ("$0.0023", "$0", "–"))
