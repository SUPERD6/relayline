"""Replay scrubbed real Claude refusals and probe observations; no live CLI or paid request.

Codex refusal coverage remains synthetic: no real Codex quota error was found in the source hub.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from test_ccx import Env, FAKES, ROOT
from test_repo_hygiene import find_personal_data
from ccx import quota
from ccx.config import Paths
from ccx.runners import parse_claude


DATA = Path(__file__).parent / "data" / "real_signals"


def fixture_lines(name):
    return [line for line in (DATA / name).read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")]


class TestRealQuotaSignals(Env):
    def setUp(self):
        super().setUp()
        self.env["CCX_LEAD_VIEW"] = "line"
        self.p = Paths(self.hub)

    def test_real_refusal_replays_verbatim_and_classifies_even_with_zero_exit(self):
        lines = fixture_lines("claude_rate_limit_20261031.jsonl")
        r = subprocess.run([sys.executable, str(FAKES / "fake_claude.py"), "-p", "--output-format",
                            "stream-json", "--verbose"], cwd=self.work,
                           env={**self.env, "FAKE_STATUS_CLAUDE": "real_quota", "PYTHONIOENCODING": "utf-8"},
                           input="Reply OK.", capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[1:], lines)
        evidence = quota.stop_evidence("claude", r.stdout, r.stderr, None)
        self.assertEqual(evidence, {"by": "rate_limit_event", "event": {
            "status": "rejected", "rateLimitType": "five_hour", "resetsAt": 1793509200,
            "overageStatus": "rejected", "isUsingOverage": False}})
        parsed = parse_claude(r.stdout, r.stderr, r.returncode, None)
        self.assertFalse(parsed.ok)
        self.assertEqual(parsed.kind, "quota")
        self.assertEqual(parsed.retry_after, 1793509200)
        # 2026-11-01 01:00 in America/New_York (still UTC-04 before the DST transition).
        self.assertEqual(datetime.fromtimestamp(parsed.retry_after, timezone.utc).isoformat(),
                         "2026-11-01T05:00:00+00:00")
        self.assertEqual(json.loads(lines[1])["message"]["content"][0]["text"],
                         "You've hit your 5-hour limit · resets 1am (America/New_York)")

    def test_real_refusal_falls_back_once_and_receipt_preserves_reset(self):
        r = self.ccx("run", "--from", "user", "--to", "claude", "--tier", "T2", "--review", "off", "x",
                     env={"FAKE_STATUS_CLAUDE": "real_quota"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        rec = json.loads((self.p.runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual([a["agent"] for a in rec["attempts"]], ["claude", "codex"])
        self.assertEqual(rec["attempts"][0]["kind"], "quota")
        self.assertEqual(rec["attempts"][0]["quota_stop"]["by"], "rate_limit_event")
        self.assertEqual(rec["attempts"][0]["quota_stop"]["event"]["resetsAt"], 1793509200)
        self.assertEqual(out["quota_fallback"]["resets_at"], 1793509200)
        self.assertEqual(out["quota_fallback"]["message"],
                         f"因 claude 限额改派 codex，重置时间 {quota.reset_text(1793509200)}（claude -> codex）")
        self.assertEqual(rec["quota_fallback"], out["quota_fallback"])
        calls = [c["agent"] for c in self.calls() if "-p" in c["argv"] or c["argv"][:1] == ["exec"]]
        self.assertEqual(calls, ["claude", "codex"])
        shown = self.ccx("quota")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        stop = json.loads(shown.stdout)["recent_quota_stops"][-1]
        self.assertEqual((stop["agent"], stop["event"]["resetsAt"]), ("claude", 1793509200))

    def test_real_probe_costs_and_cli_pace_match_hand_calculation(self):
        probes = [json.loads(s, parse_float=Decimal) for s in fixture_lines("quota_refresh_20261101.jsonl")]
        lines = fixture_lines("claude_probe_readings_20261101.jsonl")
        readings = [json.loads(s) for s in lines]
        self.assertEqual(len(probes), 4)
        self.assertEqual(len(readings), 8)
        self.assertEqual([p["ae_usd"] for p in probes], [Decimal(s) for s in (
            "0.0001826", "0.0001834", "0.0001844", "0.000185")])
        self.p.state.mkdir(parents=True, exist_ok=True)
        # quota-refresh records carry costs/counts, not utilization: replay the paired quota.jsonl readings.
        # First two snapshots span <6 h. Third weekly window spans 10.206574 h with +0.09 use:
        # per_day = 0.09*86400/36743.6680814 = 0.2116283; at last+600 s projected = 1.1710552.
        # Fourth snapshot starts a new weekly reset, so neither window has enough history again.
        expected = [((0.04, 0.83), None), ((0.17, 0.85), None),
                    ((0.09, 1.171), 0.212), ((0.34, 0.05), None)]
        for i, (probe, (projected, per_day)) in enumerate(zip(probes, expected)):
            with self.subTest(probe=i + 1):
                self.assertEqual((probe["agent"], probe["source"], probe["readings"], probe["exit_code"]),
                                 ("claude", "probe", 2, 0))
                self.assertGreater(probe["cost_usd"], 0)
                self.assertLess(probe["cost_usd"], Decimal("0.005"))
                self.assertLess(probe["ae_usd"], Decimal("0.005"))
                self.assertLess(abs(probe["cost_usd"] - probe["ae_usd"]), Decimal("1e-18"))
                last = readings[2 * i]
                self.assertGreater(last["ts"], float(probe["ts"]))
                self.assertLess(last["ts"] - float(probe["ts"]), 6)
                (self.p.state / "quota.jsonl").write_text("\n".join(lines[:2 * (i + 1)]) + "\n", encoding="utf-8")
                # Invoke the actual CLI in a separate process outside the repo, only freezing historical time.
                runner = self.work / "quota_snapshot.py"
                runner.write_text("import runpy, sys\nfrom unittest.mock import patch\n"
                                  f"sys.path.insert(0, {str(ROOT)!r})\n"
                                  f"sys.argv = [{str(ROOT / 'ccx.py')!r}, 'quota']\n"
                                  f"with patch('time.time', return_value={last['ts'] + 600!r}):\n"
                                  f"    runpy.run_path({str(ROOT / 'ccx.py')!r}, run_name='__main__')\n",
                                  encoding="utf-8")
                r = subprocess.run([sys.executable, str(runner)], cwd=self.work, env=self.env,
                                   capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual(out["freshness"], {"claude": 10.0, "codex": None})
                for win, projection in zip(("five_hour", "seven_day"), projected):
                    row = out["windows"]["claude"][win]
                    self.assertEqual(row["freshness"], 10.0)
                    self.assertEqual(row["projected"], projection)
                    self.assertEqual(row["projected_at_reset"], projection)
                    if win == "seven_day" and per_day is not None:
                        self.assertEqual(row["per_day"], per_day)
                    else:
                        self.assertNotIn("per_day", row)
                self.assertEqual(out["projected_at_reset"]["claude"], max(projected))
        self.assertEqual(self.calls(), [])  # historical reads only: no probe is launched

    def test_synthetic_codex_429_still_classifies_as_hint(self):
        # Synthetic wording from fake_codex.py; not a captured Codex response.
        text = "429 Too Many Requests: usage limit reached, try again at 18:00"
        evidence = quota.stop_evidence("codex", json.dumps({"type": "error", "message": text}), "", None)
        self.assertEqual((evidence["by"], evidence["hint"]), ("hint", "429"))
        self.assertIn(text, evidence["text"])


def test_real_signal_fixtures_have_no_personal_data_even_before_git_add():
    for path in DATA.glob("*.jsonl"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not find_personal_data(line), f"{path.name}:{i}"
