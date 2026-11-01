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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ccx import Env  # noqa: E402

from ccx import wake  # noqa: E402

RID = "20261031-120000-abcd"


def _p(root: Path):
    return SimpleNamespace(state=root / "ccx", runs=root / "ccx" / "runs")


class TestNotify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = _p(Path(self.tmp.name))
        (self.p.runs / RID).mkdir(parents=True)
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, addr, token, msg):
        self.sent.append((addr, token, msg))

    def notify(self, cfg=None, lead="claude", session="s1", cwd="/w", env=None, send=None):
        return wake.notify(self.p, cfg or {}, RID, "ccx run x: status=done ok=true", lead, session, cwd,
                           env={} if env is None else env, send=send or self.send)

    def test_an_inbox_gets_the_line_there_only(self):
        out = self.notify(env={wake.SOCK: "a", wake.TOKEN: "t"})
        self.assertEqual(out["via"], "claude-inbox")
        (addr, token, msg), = self.sent
        self.assertEqual((addr, token), ("a", "t"))
        self.assertIn("status=done ok=true", msg)
        self.assertIn(f"run {RID} you started", msg)
        self.assertTrue(msg.startswith("[ccx board"))           # the hook knows a person did not type it
        self.assertEqual(wake.take(self.p, "claude", "s1"), [])  # not shown a second time
        self.assertEqual(json.loads((self.p.runs / RID / "wake.json").read_text())["via"], "claude-inbox")

    def test_no_inbox_leaves_it_for_the_hook_once(self):
        out = self.notify()
        self.assertEqual((out["via"], self.sent), ("hook", []))
        self.assertEqual(wake.take(self.p, "claude", "other-session"), [])     # another conversation: not its
        self.assertEqual(wake.take(self.p, "codex", "s1"), [])
        got = wake.take(self.p, "claude", "s1")
        self.assertEqual(len(got), 1)
        self.assertIn("status=done", got[0])
        self.assertEqual(wake.take(self.p, "claude", "s1"), [])                # once

    def test_any_failed_send_falls_back_to_the_hook(self):
        for exc in (OSError("no such pipe"), ValueError("embedded null byte")):
            def broken(*_, e=exc):
                raise e
            out = self.notify(env={wake.SOCK: "a"}, send=broken)
            self.assertEqual(out["via"], "hook")
            self.assertIn(type(exc).__name__, out["socket_error"])
            self.assertEqual(len(wake.take(self.p, "claude", "s1")), 1)

    def test_trust_socket_off_keeps_a_hook_copy(self):
        self.assertEqual(self.notify({"wake": {"trust_socket": False}}, env={wake.SOCK: "a"})["via"],
                         "claude-inbox+hook")

    def test_a_provider_lead_on_claude_code_is_claude_codes(self):
        # Claude Code on DeepSeek records its caller as "deepseek"; its hook still runs `ccx turn --as claude`
        self.notify(lead="deepseek")
        self.assertEqual(len(wake.take(self.p, "claude", "s1")), 1)
        self.notify(lead="deepseek-codex")
        self.assertEqual(wake.take(self.p, "claude", "s1"), [])
        self.assertEqual(len(wake.take(self.p, "codex", "s1")), 1)
        self.notify(lead="dsh")
        self.assertEqual(len(wake.take(self.p, "dsh", "s1")), 1)

    def test_off_and_waited_on_send_nothing(self):
        self.assertEqual(self.notify({"wake": {"enabled": False}}, env={wake.SOCK: "a"})["via"], "off")
        with wake.waiting(self.p, RID):
            self.assertEqual(self.notify(env={wake.SOCK: "a"})["via"], "waiter")
        self.assertEqual(list((self.p.runs / RID).glob("waiting.*")), [])   # the mark is gone after
        self.assertEqual(self.sent, [])

    def test_a_dead_waiters_mark_does_not_count(self):
        (self.p.runs / RID / "waiting.999999999").write_text("x")
        self.assertEqual(self.notify()["via"], "hook")

    def test_a_session_less_notice_goes_to_its_folder_only(self):
        self.notify(session=None, cwd=self.tmp.name)
        self.assertEqual(wake.take(self.p, "claude", None, Path(self.tmp.name) / "elsewhere"), [])
        self.assertEqual(len(wake.take(self.p, "claude", None, Path(self.tmp.name))), 1)

    def test_a_broken_notice_file_is_dropped_and_costs_nothing_else(self):
        d = self.p.state / "wake"
        d.mkdir(parents=True)
        (d / "a.json").write_text('{"ts": "soon", "lead": "claude"}')
        (d / "b.json").write_text("[1, 2]")
        (d / "c.json").write_text("{not json")
        self.notify()
        self.assertEqual(len(wake.take(self.p, "claude", "s1")), 1)
        self.assertEqual(list(d.iterdir()), [])

    def test_a_long_recap_stays_one_short_line(self):
        line = wake.text(RID, "x " * 2000)
        self.assertLess(len(line), wake.MAX_LINE + 200)
        self.assertNotIn("\n", line)

    def test_a_sub_agent_never_gets_the_leads_inbox(self):
        from ccx.delegate import _child_env
        with mock.patch.dict(os.environ, {wake.SOCK: "a", wake.TOKEN: "t"}):
            env = _child_env("codex", RID)
        self.assertNotIn(wake.SOCK, env)
        self.assertNotIn(wake.TOKEN, env)


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
    def wake_of(self, rid, tries=300):
        f = self.hub / "ccx" / "runs" / rid / "wake.json"
        for _ in range(tries):                     # the detached child writes wake.json last
            if f.exists():
                return json.loads(f.read_text())
            time.sleep(0.1)
        self.fail(f"no wake.json for {rid}")

    def turn(self):
        hook = json.dumps({"session_id": "lead-1", "cwd": str(self.work), "prompt": "go on"})
        return self.ccx("turn", "--as", "claude", stdin=hook).stdout

    def test_a_bg_run_leaves_its_line_for_the_leads_next_turn(self):
        env = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "lead-1"}
        r = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "read", "--bg", "explain a.py", env=env)
        rid = json.loads(r.stdout)["run_id"]
        self.assertEqual(self.wake_of(rid)["via"], "hook")
        t = self.turn()
        self.assertIn(f"background ccx run {rid} you started has finished", t)
        self.assertIn("status=done", t)
        self.assertNotIn(rid, self.turn())           # shown once

    def test_a_run_routing_keeps_with_the_lead_still_tells_it(self):
        # the detached child refuses after detaching (routing: do it yourself); the lead hears that too
        r = self.ccx("run", "--bg", "--from", "claude", "fix typo",
                     env={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "lead-1"})
        rid = json.loads(r.stdout)["run_id"]
        self.assertEqual(self.wake_of(rid)["via"], "hook")
        self.assertIn(rid, self.turn())

    def test_waiting_in_the_same_call_sends_no_notice(self):
        r = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "read", "--bg", "--wait", "90",
                     "explain a.py", env={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "lead-1"})
        rid = json.loads(r.stdout)["run_id"]
        self.assertEqual(self.wake_of(rid, 100)["via"], "waiter")
        self.assertNotIn(rid, self.turn())


class TestFixRoundChain(unittest.TestCase):
    """The notice names the run the lead started and is skipped while the lead waits on that id, even when a review
    fix round (another run id) is the final result."""

    def test_the_chain_is_reported_under_the_started_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = _p(Path(d))
            first, fix = RID, "20261031-120001-ef01"
            with mock.patch("ccx.ledger.load_run", side_effect=lambda _p, rid: {"run_id": rid, "caller": "claude"}), \
                    mock.patch("ccx.commands.records.follow_chain",
                               side_effect=lambda _p, rec: ({"run_id": fix, "state": "done"}, fix)), \
                    mock.patch("ccx.delegate.compact", return_value={}), \
                    mock.patch("ccx.delegate.recap", return_value=f"ccx run {fix}: status=done"), \
                    mock.patch("ccx.config.load_config", return_value={}), \
                    mock.patch.object(wake, "notify") as n:
                with wake.after_bg(p, first):
                    pass
            self.assertEqual(n.call_args[0][2], first)                # waiter marks and wake.json: the started id
            self.assertIn(fix, n.call_args[0][3])                     # its line: the fix round's final result


if __name__ == "__main__":
    unittest.main()
