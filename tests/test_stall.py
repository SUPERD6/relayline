"""#330: run.stall_minutes (experimental, default off). A sub-CLI that printed events and then went quiet is stopped
near the threshold and recorded as a timeout marked `stalled`; off (0) leaves the run exactly as before. Fake CLIs
only; thresholds are a few seconds (stall_minutes accepts fractions)."""
import time
import unittest

from test_delegate_v02 import V02

from ccx.delegate import stall_seconds


class TestStallSeconds(unittest.TestCase):
    def test_off_unless_positive(self):
        self.assertEqual(stall_seconds({}), 0.0)
        self.assertEqual(stall_seconds({"run": {}}), 0.0)
        self.assertEqual(stall_seconds({"run": {"stall_minutes": 0}}), 0.0)
        self.assertEqual(stall_seconds({"run": {"stall_minutes": -1}}), 0.0)
        self.assertEqual(stall_seconds({"run": {"stall_minutes": "x"}}), 0.0)
        self.assertEqual(stall_seconds({"run": {"stall_minutes": 2}}), 120.0)
        self.assertEqual(stall_seconds({"run": {"stall_minutes": 0.05}}), 3.0)

    def test_shipped_default_is_off(self):
        from test_ccx import ROOT
        import tomllib
        cfg = tomllib.loads((ROOT / "config" / "tiers.toml").read_text(encoding="utf-8"))
        self.assertEqual(cfg["run"]["stall_minutes"], 0)


class TestStallRun(V02):
    def tiers(self, text):
        (self.hub / "ccx").mkdir(exist_ok=True)
        (self.hub / "ccx" / "tiers.toml").write_text(text, encoding="utf-8")

    def test_on_stops_a_quiet_cli_near_the_threshold(self):
        # 3 s of silence after the first events; the whole-attempt timeout (60 s) and the hang (40 s) are far off
        self.tiers("[defaults]\ntimeout_sec = 60\n[run]\nstall_minutes = 0.05\n")
        t0 = time.monotonic()
        out = self.run_json("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--no-fallback", "long job",
                            env={"FAKE_STATUS": "hang", "FAKE_HANG_S": "40"}, code=2)
        took = time.monotonic() - t0
        self.assertEqual(out["kind"], "timeout")
        self.assertTrue(out.get("stalled"))
        self.assertIn("stall detection", out["hint"])
        self.assertIn("ccx resume", out["hint"])
        self.assertLess(took, 30)                     # stopped by the stall check, not by the 40 s hang
        rec = self.record(out["run_id"])
        self.assertTrue(rec["stalled"])
        self.assertTrue(rec["session_id"])            # still resumable
        self.assertEqual(len(rec["attempts"]), 1)     # a timeout: no climb, no retry (rules unchanged)
        a = rec["attempts"][0]
        self.assertEqual(a["kind"], "timeout")
        self.assertEqual(a["agent"], "claude")
        self.assertTrue(a["stalled"])
        self.assertIn("stalled: no event from claude", a["error"])
        self.assertGreaterEqual(a["seconds"], 2.5)    # not before the threshold

    def test_off_is_unchanged(self):
        self.tiers("[defaults]\ntimeout_sec = 5\n[run]\nstall_minutes = 0\n")
        out = self.run_json("run", "--from", "claude", "--tier", "T2", "--no-fallback", "long job",
                            env={"FAKE_STATUS": "hang", "FAKE_HANG_S": "30"}, code=2)
        self.assertEqual(out["kind"], "timeout")
        self.assertNotIn("stalled", out)
        rec = self.record(out["run_id"])
        self.assertNotIn("stalled", rec)
        self.assertNotIn("stalled", rec["attempts"][0])
        self.assertIn("timed out after 5s", rec["attempts"][0]["error"])

    def test_on_leaves_a_slow_but_talking_cli_alone(self):
        # an event every 1 s for 8 s with a 6 s threshold (room for a cold start on a slow runner): finishes normally
        self.tiers("[defaults]\ntimeout_sec = 60\n[run]\nstall_minutes = 0.1\n")
        out = self.run_json("run", "--from", "codex", "--to", "claude", "--tier", "T2", "--no-fallback", "--no-escalate", "slow job",
                            env={"FAKE_STATUS": "trickle", "FAKE_HANG_S": "8"}, code=0)
        self.assertEqual(out["status"], "done")
        rec = self.record(out["run_id"])
        self.assertNotIn("stalled", rec)
        self.assertEqual(rec["attempts"][0]["kind"], "ok")
        self.assertEqual(rec["attempts"][0]["agent"], "claude")   # the fake that trickles
        self.assertGreater(rec["attempts"][0]["seconds"], 6.5)   # ran past the 6 s threshold

    def test_config_set_accepts_fractions(self):
        r = self.ccx("config", "set", "run.stall_minutes", "0.5")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.ccx("config", "get", "run.stall_minutes")
        self.assertIn("0.5", r.stdout)


if __name__ == "__main__":
    unittest.main()
