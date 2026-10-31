"""Warm lanes (ccx/lanes.py): small pieces for one agent share a few sessions, one piece after another."""
import json
import subprocess

from test_adapters import AdapterEnv

FAIL = 'python -c "import sys; sys.exit(1)"'
NEW_FILE = 'python -c "import uuid; open(uuid.uuid4().hex + \'.txt\', \'w\').write(\'x\')"'


class TestLanes(AdapterEnv):
    def batch(self, tasks, *flags, code=None):
        f = self.work / "plan.json"
        f.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        r = self.ccx("batch", str(f), "--from", "claude", *flags)
        if code is not None:
            self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def pieces(self, n, **extra):
        return [{"id": f"p{i}", "to": "codex", "tier": "T1", "mode": "read", "brief": f"read piece {i}", **extra}
                for i in range(n)]

    def sid(self, run_id):
        return self.rec(run_id)["session_id"]

    def codex_calls(self):
        return [c for c in self.calls() if c["agent"] == "codex" and c["argv"][:1] == ["exec"]]

    def test_off_by_default(self):
        out = self.batch(self.pieces(3), code=0)
        self.assertNotIn("lanes", out)
        self.assertEqual(len({self.sid(r["run_id"]) for r in out["results"]}), 3)    # a session each, as before
        self.assertFalse(any(c["argv"][:2] == ["exec", "resume"] for c in self.codex_calls()))

    def test_an_environment_failure_starts_no_later_piece(self):
        # every later piece meets the same wall on this machine (2026-10-31 eval pg1): one attempt, then none
        self.env["FAKE_STATUS"] = "env_uac"
        out = self.batch(self.pieces(3), "--lanes", "1", code=2)
        res = out["results"]
        self.assertEqual(len(self.codex_calls()), 1, res)
        self.assertEqual(res[0]["kind"], "env")
        self.assertTrue(all("environment problem" in r["skipped"] for r in res[1:]), res)

    def test_lanes_share_sessions_in_order(self):
        out = self.batch(self.pieces(5), "--lanes", "2", code=0)
        self.assertEqual(out["lanes"], 2)
        res = out["results"]
        self.assertEqual([r["lane"] for r in res], [0, 0, 0, 1, 1])                  # 3 + 2, order kept
        self.assertEqual([r["warm"] for r in res], [False, True, True, False, True])
        sids = [self.sid(r["run_id"]) for r in res]
        self.assertEqual(len(set(sids[:3])), 1)                                      # one session per lane
        self.assertEqual(len(set(sids[3:])), 1)
        self.assertNotEqual(sids[0], sids[3])
        self.assertEqual(res[1]["continued_from"], res[0]["run_id"])
        # each piece is its own run: own ledger row, own tokens (the session's running total is not re-counted)
        from ccx import ledger
        from ccx.config import Paths
        rows = [r for r in ledger.rows(Paths(self.hub)) if not r.get("type")]
        self.assertEqual(len({r["run_id"] for r in rows}), 5)
        self.assertEqual(len({json.dumps(r["tokens"], sort_keys=True) for r in res}), 1)
        self.assertTrue(all(self.rec(r["run_id"])["continued"] == r["warm"] for r in res))

    def test_groups_by_agent_and_mode(self):
        tasks = self.pieces(2) + [{"id": "c", "to": "claude", "tier": "T1", "mode": "read", "brief": "read c"}]
        out = self.batch(tasks, "--lanes", "1", code=0)
        self.assertEqual(out["lanes"], 2)                    # codex pieces in one lane, the claude piece in another
        by = {r["label"] if "label" in r else r["run_id"]: r for r in out["results"]}
        self.assertEqual(sorted(r["agent"] for r in out["results"]), ["claude", "codex", "codex"])
        self.assertEqual(sum(r["warm"] for r in by.values()), 1)

    def test_failed_piece_hands_the_next_a_fresh_session(self):
        tasks = self.pieces(3)
        tasks[1]["check"] = FAIL
        out = self.batch(tasks, "--lanes", "1")
        res = out["results"]
        self.assertEqual([r["ok"] for r in res][0], True)
        self.assertEqual(res[1].get("kind"), "check_failed")
        self.assertTrue(res[1]["warm"])                       # it was continued...
        self.assertIn("fresh", res[1]["lane_next"])
        self.assertFalse(res[2]["warm"])                      # ...but the next one starts over
        self.assertNotEqual(self.sid(res[2]["run_id"]), self.sid(res[0]["run_id"]))

    def test_limits_start_a_new_session(self):
        self.ccx("config", "set", "lanes.max_blocks", "2")
        out = self.batch(self.pieces(5), "--lanes", "1", code=0)
        self.assertEqual([r["warm"] for r in out["results"]], [False, True, False, True, False])
        self.assertIn("2 pieces", out["results"][1]["lane_next"])
        self.ccx("config", "set", "lanes.max_blocks", "5")
        self.ccx("config", "set", "lanes.max_tokens", "100")  # every piece is over it
        out = self.batch(self.pieces(3), "--lanes", "1", code=0)
        self.assertEqual([r["warm"] for r in out["results"]], [False, False, False])

    def test_default_from_config(self):
        self.ccx("config", "set", "lanes.default", "1")
        out = self.batch(self.pieces(2), code=0)
        self.assertEqual([r["warm"] for r in out["results"]], [False, True])
        # one lane, so the fake CLI's call log has no parallel writers (Windows can drop concurrent appends)
        sid = self.sid(out["results"][0]["run_id"])
        resumed = [c["argv"][2] for c in self.codex_calls() if c["argv"][:2] == ["exec", "resume"]]
        self.assertEqual(resumed, [sid])                                            # the warm piece resumed it
        out = self.batch(self.pieces(2), "--lanes", "0", code=0)      # the flag turns it off again
        self.assertNotIn("lanes", out)

    def test_worktree_lane_commits_each_piece(self):
        self.env["FAKE_TOUCH"] = "1"        # the builder changes something (a write run that changes nothing is no_changes)
        for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                     "-m", "init"]):
            subprocess.run(["git", *args], cwd=self.work, check=True, capture_output=True)
        tasks = [{"id": f"w{i}", "to": "codex", "tier": "T1", "mode": "write", "review": "off",
                  "brief": f"write piece {i}", "check": NEW_FILE, "cwd": str(self.work)} for i in range(3)]
        out = self.batch(tasks, "--lanes", "1", code=0)
        res = out["results"]
        self.assertEqual(len({r["worktree"] for r in res}), 1)        # the lane works in one worktree
        self.assertEqual(len({r["commit"] for r in res}), 3)          # one commit per piece
        wt = res[0]["worktree"]
        log = subprocess.run(["git", "log", "--format=%s", "-3"], cwd=wt, capture_output=True, text=True).stdout
        for r in res:
            self.assertIn(r["run_id"], log)
        # each piece keeps its own undo snapshot
        self.assertTrue(all((self.hub / "ccx" / "runs" / r["run_id"] / "undo.json").exists() for r in res))


class TestQueueLanes(AdapterEnv):
    def q(self, *args, env=None, code=0):
        return self.j("q", *args, env=env, code=code)

    def test_queue_items_share_a_warm_session(self):
        ids = [self.q("add", f"x{i}", "--brief", f"look at x{i}", "--minutes", "5", "--to", "codex",
                      "--mode", "read")["id"] for i in range(3)]
        out = self.q("run", "--lanes", "1")
        res = out["results"]
        self.assertEqual([r["id"] for r in res], ids)
        self.assertEqual([r["warm"] for r in res], [False, True, True])
        self.assertTrue(all(r["status"] == "done" for r in res))
        sids = {self.rec(r["run"])["session_id"] for r in res}
        self.assertEqual(len(sids), 1)

    def test_queue_default_is_unchanged(self):
        for i in range(2):
            self.q("add", f"x{i}", "--brief", f"look at x{i}", "--minutes", "5", "--to", "codex", "--mode", "read")
        res = self.q("run")["results"]
        self.assertTrue(all("warm" not in r for r in res))
        for r in res:                                  # a failed row says why (it once flaked on Windows CI)
            self.assertIn("run", r, json.dumps(r))
        self.assertEqual(len({self.rec(r["run"])["session_id"] for r in res}), 2)
