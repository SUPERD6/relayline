"""A --bg run that finishes tells its lead in one line (ccx/wake.py, P0-11 item 1): Claude Code's inbox, else the
next turn's hook; nothing while the lead waits on it. Fake CLIs and a fake inbox only; never a real claude/codex."""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ccx import Env  # noqa: E402

from ccx import wake  # noqa: E402


def _p(root: Path):
    return SimpleNamespace(state=root / "ccx", runs=root / "ccx" / "runs")


REC = {"run_id": "20261031-120000-abcd", "caller": "claude", "lead_session": "s1", "cwd": "/w"}


class TestNotify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = _p(Path(self.tmp.name))
        (self.p.runs / REC["run_id"]).mkdir(parents=True)
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, addr, token, msg):
        self.sent.append((addr, token, msg))

    def test_claude_lead_with_an_inbox_gets_the_line_there_only(self):
        out = wake.notify(self.p, {}, REC, "ccx run x: status=done ok=true", env={wake.SOCK: "a", wake.TOKEN: "t"},
                          send=self.send)
        self.assertEqual(out["via"], "claude-inbox")
        (addr, token, msg), = self.sent
        self.assertEqual((addr, token), ("a", "t"))
        self.assertIn("status=done ok=true", msg)
        self.assertTrue(msg.startswith("[ccx board"))           # the hook knows a person did not type it
        self.assertEqual(wake.take(self.p, "claude", "s1"), [])  # not shown a second time
        self.assertEqual(json.loads((self.p.runs / REC["run_id"] / "wake.json").read_text())["via"], "claude-inbox")

    def test_no_inbox_leaves_it_for_the_hook_once(self):
        out = wake.notify(self.p, {}, REC, "recap", env={}, send=self.send)
        self.assertEqual((out["via"], self.sent), ("hook", []))
        self.assertEqual(wake.take(self.p, "claude", "other-session"), [])     # another conversation: not its
        self.assertEqual(wake.take(self.p, "codex", "s1"), [])
        got = wake.take(self.p, "claude", "s1")
        self.assertEqual(len(got), 1)
        self.assertIn("recap", got[0])
        self.assertEqual(wake.take(self.p, "claude", "s1"), [])                # once

    def test_a_failed_send_falls_back_to_the_hook(self):
        def broken(*_):
            raise OSError("no such pipe")
        out = wake.notify(self.p, {}, REC, "recap", env={wake.SOCK: "a"}, send=broken)
        self.assertEqual(out["via"], "hook")
        self.assertIn("no such pipe", out["socket_error"])
        self.assertEqual(len(wake.take(self.p, "claude", "s1")), 1)

    def test_trust_socket_off_keeps_a_hook_copy(self):
        out = wake.notify(self.p, {"wake": {"trust_socket": False}}, REC, "recap", env={wake.SOCK: "a"},
                          send=self.send)
        self.assertEqual(out["via"], "claude-inbox+hook")

    def test_a_codex_lead_never_uses_claudes_inbox(self):
        out = wake.notify(self.p, {}, dict(REC, caller="codex"), "recap", env={wake.SOCK: "a"}, send=self.send)
        self.assertEqual((out["via"], self.sent), ("hook", []))

    def test_off_and_waited_on_send_nothing(self):
        self.assertEqual(wake.notify(self.p, {"wake": {"enabled": False}}, REC, "r", env={wake.SOCK: "a"},
                                     send=self.send)["via"], "off")
        with wake.waiting(self.p, REC["run_id"]):
            self.assertEqual(wake.notify(self.p, {}, REC, "r", env={wake.SOCK: "a"}, send=self.send)["via"],
                             "waiter")
        self.assertEqual(list((self.p.runs / REC["run_id"]).glob("waiting.*")), [])   # the mark is gone after
        self.assertEqual(self.sent, [])

    def test_a_dead_waiters_mark_does_not_count(self):
        (self.p.runs / REC["run_id"] / "waiting.999999999").write_text("x")
        self.assertEqual(wake.notify(self.p, {}, REC, "r", env={}, send=self.send)["via"], "hook")

    def test_a_session_less_notice_goes_to_its_folder_only(self):
        rec = dict(REC, lead_session=None, cwd=self.tmp.name)
        wake.notify(self.p, {}, rec, "r", env={})
        self.assertEqual(wake.take(self.p, "claude", None, Path(self.tmp.name) / "elsewhere"), [])
        self.assertEqual(len(wake.take(self.p, "claude", None, Path(self.tmp.name))), 1)

    def test_a_long_recap_stays_one_short_line(self):
        line = wake.text(REC, "x " * 2000)
        self.assertLess(len(line), wake.MAX_LINE + 200)
        self.assertNotIn("\n", line)


@unittest.skipUnless(hasattr(socket, "AF_UNIX") and os.name != "nt", "a Unix socket inbox (macOS / Linux)")
class TestUnixInbox(unittest.TestCase):
    def test_the_wire_is_an_auth_line_then_one_user_message(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "in.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(path)
            srv.listen(1)
            got = []

            def serve():
                c, _ = srv.accept()
                buf = b""
                while True:
                    b = c.recv(4096)
                    if not b:
                        break
                    buf += b
                got.append(buf)
                c.close()
            t = threading.Thread(target=serve, daemon=True)
            t.start()
            wake._send_socket(path, "tok", "hello ü")
            t.join(5)
            srv.close()
        a, m = got[0].decode("utf-8").splitlines()
        self.assertEqual(json.loads(a), {"type": "auth", "token": "tok"})
        self.assertEqual(json.loads(m), {"type": "user", "message": {"role": "user", "content": "hello ü"}})


class TestBgRunWakes(Env):
    def test_a_bg_run_leaves_its_line_for_the_leads_next_turn(self):
        env = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "lead-1"}
        r = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "read", "--bg", "explain a.py", env=env)
        rid = json.loads(r.stdout)["run_id"]
        f = self.hub / "ccx" / "runs" / rid / "wake.json"
        for _ in range(300):                       # the detached child writes wake.json last
            if f.exists():
                break
            time.sleep(0.1)
        self.assertEqual(json.loads(f.read_text())["via"], "hook")
        hook = json.dumps({"session_id": "lead-1", "cwd": str(self.work), "prompt": "go on"})
        t = self.ccx("turn", "--as", "claude", stdin=hook)
        self.assertIn(f"background ccx run {rid} you started has finished", t.stdout)
        self.assertIn("status=done", t.stdout)
        again = self.ccx("turn", "--as", "claude", stdin=hook)
        self.assertNotIn(rid, again.stdout)          # shown once

    def test_waiting_in_the_same_call_sends_no_notice(self):
        r = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "read", "--bg", "--wait", "90",
                     "explain a.py", env={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "lead-1"})
        rid = json.loads(r.stdout)["run_id"]
        f = self.hub / "ccx" / "runs" / rid / "wake.json"
        for _ in range(100):
            if f.exists():
                break
            time.sleep(0.1)
        self.assertEqual(json.loads(f.read_text())["via"], "waiter")
        self.assertFalse((self.hub / "ccx" / "wake").exists() and list((self.hub / "ccx" / "wake").iterdir()))


if __name__ == "__main__":
    unittest.main()
