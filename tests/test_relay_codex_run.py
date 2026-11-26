"""#525: a Codex session that ccx itself started (`ccx run --to codex`) ends on a usage-limit refusal -> a relay packet
is saved -> it can be continued on Claude. Fake CLIs only; the real exec --json envelope is Unknown (see docs/relay.md)."""
import json
import subprocess

from test_ccx import Env, FAKES

LUNA = ["--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--no-fallback"]


class TestCodexRunRelay(Env):
    def setUp(self):
        super().setUp()
        self.env.update(CCX_CLAUDE_BIN=str(FAKES / "fake_relay.py"))
        for args in (("init",), ("config", "user.email", "t@example.invalid"), ("config", "user.name", "T")):
            subprocess.run(["git", *args], cwd=self.work, check=True, capture_output=True)
        (self.work / ".gitignore").write_text(".ccx/\n", encoding="utf-8")
        (self.work / "tracked.txt").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.work, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.work, check=True, capture_output=True)

    def enable(self):
        r = self.ccx("config", "set", "relay.enabled", "true")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def run_quota(self, status="quota_real"):
        r = self.ccx("run", *LUNA, "finish the parser", env={"FAKE_STATUS": status})
        return json.loads(r.stdout)

    def test_quota_stop_saves_a_packet_that_continues_on_claude(self):
        self.enable()
        out = self.run_quota()
        notice = out["relay"]
        packet_file = self.work / ".ccx" / "relay" / (notice["packet"] + ".json")
        packet = json.loads(packet_file.read_text(encoding="utf-8"))
        self.assertEqual((packet["source"], packet["state"]), ("codex", "quota_stopped"))
        self.assertEqual(packet["quota_signal"]["kind"], "quota")
        self.assertIn("finish the parser", packet["goal"])
        self.assertIn("--to claude", notice["continue_command"])
        self.assertTrue(packet_file.with_suffix(".notification.json").exists())
        r = self.ccx("relay", "continue", notice["packet"], "--to", "claude", "--budget-seconds", "30",
                     "--old-stopped", "--launch")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["state"], "exited")
        call = json.loads((self.work / "relay-fake-call.json").read_text(encoding="utf-8"))
        self.assertIn("finish the parser", call["prompt"])

    def test_synthetic_wording_also_counts(self):
        self.enable()
        self.assertIn("relay", self.run_quota("quota"))

    def test_off_by_default(self):
        out = self.run_quota()
        self.assertNotIn("relay", out)
        self.assertFalse((self.work / ".ccx" / "relay").exists())

    def test_other_stops_save_no_packet(self):
        self.enable()
        for status in ("auth", "blocked"):
            self.assertNotIn("relay", self.run_quota(status))
        self.assertFalse(list((self.work / ".ccx" / "relay").glob("*.json")) if (self.work / ".ccx" / "relay").exists() else [])
