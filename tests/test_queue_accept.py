"""`ccx q accept`: landing worktree pieces in dependency order with a joint check after each merge, refusals,
conflicts and rollbacks; `--dep 1`; the compact `ccx q ls`; `ccx q done` of several ids (fakes and git only)."""
import json
import subprocess
import sys
from pathlib import Path

from ccx import queue as wq
from ccx.config import Paths
from ccx.workspace import make_worktree
from test_queue_pipeline import NEW_FILE, QEnv

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def git(cwd, *args):
    r = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


class AcceptEnv(QEnv):
    def repo(self):
        """A git project on a working branch (main/master are protected), with shared.txt."""
        git(self.work, "init", "-q")
        (self.work / "shared.txt").write_text("base\n", encoding="utf-8")
        (self.work / ".gitignore").write_text(".ccx/\n", encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "base")
        git(self.work, "checkout", "-q", "-b", "work")

    def piece(self, title, files, deps=(), check="python -c \"print(1)\"", record=None, status="done", base=None):
        """A queue item whose run worked in its own worktree and committed `files` there ({name: text})."""
        it = wq.add(self.work, title, title, deps=list(deps))
        run_id = f"20261029-1200{len(wq.load(self.work)['order']):02d}-{it['id']}"
        info: dict = {}
        wt = make_worktree(self.work, run_id, base=base, base_info=info)
        record = {**info, **(record or {})}
        for name, text in files.items():
            (wt / name).write_text(text, encoding="utf-8")
        if files:
            git(wt, "add", "-A")
            git(wt, "commit", "-qm", f"ccx run {run_id}: q:{it['id']} (ok)")
        rec = {"run_id": run_id, "label": f"q:{it['id']}", "cwd": str(wt), "mode": "write", "to": "codex",
               "ok": True, "kind": "ok", "state": "finished", "result": {"status": "done", "summary": "x"},
               "attempts": [{"agent": "codex", "model": "m", "effort": "low", "seconds": 12.0, "kind": "ok"}],
               **({"check": {"cmd": check, "passed": True}} if check else {}), **(record or {})}
        d = self.hub / "ccx" / "runs" / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")
        wq.update(self.work, it["id"], status=status, run=run_id, agent="codex", cost_usd=0.01, worktree=str(wt),
                  branch=f"ccx/{run_id}", verdict=None)
        return it["id"]

    def joint(self, fail_if=None):
        """A joint check that logs which files the merged tree has, and fails when `fail_if` is there."""
        log = self.work.parent / "joint.log"
        script = self.work.parent / "joint.py"
        script.write_text(
            "import json, os, sys\n"
            f"have = sorted(f for f in ('a.txt', 'b.txt', 'c.txt') if os.path.exists(f))\n"
            f"open({str(log)!r}, 'a').write(json.dumps(have) + '\\n')\n"
            f"sys.exit(1 if {fail_if!r} in have else 0)\n", encoding="utf-8")
        return f'"{sys.executable}" "{script}"', log

    def accept(self, *args, code=0):
        r = self.ccx("q", "accept", *args)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def ledger_rows(self, kind):
        p = Paths(self.hub)
        return [json.loads(x) for x in p.ledger.read_text(encoding="utf-8").splitlines()
                if json.loads(x).get("type") == kind] if p.ledger.exists() else []

    def batch(self):
        """q1, q2 (after q1) and q3, whose change to shared.txt conflicts with q1's."""
        self.repo()
        q1 = self.piece("base piece", {"a.txt": "a\n", "shared.txt": "A\n"})
        q2 = self.piece("after base", {"b.txt": "b\n"}, deps=[q1])
        q3 = self.piece("clashing piece", {"c.txt": "c\n", "shared.txt": "C\n"})
        return q1, q2, q3


class TestAccept(AcceptEnv):
    def test_merges_in_dep_order_reports_the_conflict_and_checks_after_each_merge(self):
        q1, q2, q3 = self.batch()
        cmd, log = self.joint()
        dry = self.accept("--all-ready", "--check", cmd, "--dry-run")
        self.assertEqual([x["id"] for x in dry["plan"]], [q1, q2, q3])
        self.assertFalse(log.exists())                                      # a dry run changes nothing
        self.assertEqual(git(self.work, "log", "--format=%s", "-1"), "base")
        out = self.accept("--all-ready", "--check", cmd, code=2)
        self.assertEqual([x["id"] for x in out["accepted"]], [q1, q2])
        self.assertEqual(out["into"], "work")
        self.assertEqual([c["id"] for c in out["conflict"]], [q3])
        self.assertEqual(out["conflict"][0]["conflicts"], ["shared.txt"])
        self.assertIn("conflict in shared.txt", out["conflict"][0]["why"])
        # the joint check ran once after each merge, on the tree with that merge in it
        self.assertEqual([json.loads(x) for x in log.read_text().splitlines()], [["a.txt"], ["a.txt", "b.txt"]])
        self.assertEqual((self.work / "shared.txt").read_text(encoding="utf-8"), "A\n")
        self.assertFalse((self.work / "c.txt").exists())
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=no"), "")   # no merge left open
        items = wq.load(self.work)["items"]
        self.assertEqual([items[i].get("verdict") for i in (q1, q2, q3)], [True, True, None])
        self.assertEqual([u["id"] for u in wq.unmerged(wq.load(self.work))], [q3])
        rows = self.ledger_rows("q_accept")
        self.assertEqual([(r["id"], r["result"]) for r in rows], [(q1, "merged"), (q2, "merged"), (q3, "conflict")])
        self.assertTrue(rows[0]["check"]["passed"])
        verdict = self.rec(items[q1]["run"])["verdict"]
        self.assertTrue(verdict["ok"])
        self.assertIn("joint check passed", verdict["note"])
        self.assertTrue((self.hub / "ccx" / "runs" / items[q2]["run"] / "merge.json").exists())

    def test_a_failing_joint_check_rolls_that_merge_back(self):
        q1, q2, q3 = self.batch()
        cmd, _ = self.joint(fail_if="b.txt")
        head0 = git(self.work, "rev-parse", "HEAD")
        out = self.accept(q1, q2, "--check", cmd, code=2)
        self.assertEqual([x["id"] for x in out["accepted"]], [q1])
        self.assertEqual([x["id"] for x in out["rolled_back"]], [q2])
        self.assertIn("rolled back", out["rolled_back"][0]["why"])
        self.assertNotEqual(git(self.work, "rev-parse", "HEAD"), head0)
        self.assertEqual(git(self.work, "rev-parse", "HEAD"), wq.load(self.work)["items"][q1]["merged"])
        self.assertFalse((self.work / "b.txt").exists())
        self.assertIsNone(wq.load(self.work)["items"][q2].get("verdict"))
        self.assertEqual([r["result"] for r in self.ledger_rows("q_accept")], ["merged", "rolled_back"])

    def dirtying_check(self, name):
        """A joint check that edits the tracked file `name` and fails."""
        script = self.work.parent / "dirty.py"
        script.write_text(f"open({name!r}, 'a').write('edited by the check\\n')\nraise SystemExit(1)\n",
                          encoding="utf-8")
        return f'"{sys.executable}" "{script}"'

    def test_a_rollback_that_fails_stops_the_batch(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        q2 = self.piece("two", {"b.txt": "b\n"})
        out = self.accept(q1, q2, "--check", self.dirtying_check("a.txt"), code=2)
        self.assertEqual(out["accepted"], [])
        bad = out["rollback_failed"][0]
        self.assertEqual(bad["id"], q1)
        self.assertTrue(bad["head"] and bad["prev"])
        self.assertNotIn("rolled_back", out)
        self.assertEqual(out["refused"][0]["id"], q2)                       # nothing merged on top of it
        self.assertIn("stopped", out["refused"][0]["why"])
        self.assertFalse((self.work / "b.txt").exists())
        items = wq.load(self.work)["items"]
        self.assertEqual([items[i].get("verdict") for i in (q1, q2)], [None, None])
        self.assertEqual([r["result"] for r in self.ledger_rows("q_accept")], ["rollback_failed"])

    def test_a_check_that_leaves_edits_stops_the_batch(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        q2 = self.piece("two", {"b.txt": "b\n"})
        out = self.accept(q1, q2, "--check", self.dirtying_check("shared.txt"), code=2)   # not a merged file
        self.assertEqual([x["id"] for x in out["rolled_back"]], [q1])
        self.assertEqual(out["dirty_after"][0]["files"], ["shared.txt"])
        self.assertEqual(out["refused"][0]["id"], q2)
        self.assertFalse((self.work / "b.txt").exists())

    def test_a_run_you_rejected_is_refused_even_with_a_check(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"}, record={"verdict": {"ok": False, "note": "wrong"}})
        cmd, _ = self.joint()
        for args in ((q1,), (q1, "--check", cmd)):
            out = self.accept(*args, code=2)
            self.assertIn("you rejected this run", out["refused"][0]["why"])
        self.assertIsNone(wq.load(self.work)["items"][q1].get("verdict"))

    def test_done_before_the_merge_is_still_landed_by_accept(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        out = json.loads(self.ccx("q", "done", q1, "--ok", "1").stdout)
        self.assertEqual(out["not_merged"]["ids"], [q1])                    # recorded, with a pointer to accept
        ls = self.ccx("q", "ls").stdout
        self.assertIn(f"{q1} unmerged", ls)
        self.assertIn(f"next: ccx q accept {q1}", ls)                        # the verdict is in: the merge is next
        self.assertNotIn(f"ccx q done {q1}", ls)
        out = self.accept("--all-ready")
        self.assertEqual([x["id"] for x in out["accepted"]], [q1])
        self.assertTrue((self.work / "a.txt").exists())
        out = self.accept(q1, code=2)
        self.assertIn("already accepted", out["refused"][0]["why"])

    def test_done_after_a_merge_by_hand_is_not_merged_again(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        git(self.work, "merge", "-q", "--no-ff", "-m", "by hand", wq.load(self.work)["items"][q1]["branch"])
        out = json.loads(self.ccx("q", "done", q1, "--ok", "1").stdout)
        self.assertNotIn("not_merged", out)
        self.assertNotIn("unmerged", self.ccx("q", "ls").stdout)
        out = self.accept(q1, code=2)
        self.assertIn("already accepted", out["refused"][0]["why"])

    def test_compact_ls_for_two_unmerged_worktree_pieces(self):
        self.repo()
        for t in ("first piece with a fairly long title here", "second piece with a fairly long title"):
            self.piece(t, {f"{t[:5]}.txt": "x\n"})
        ls = self.ccx("q", "ls").stdout
        self.assertEqual(ls.count("unmerged"), 2)
        self.assertLess(len(ls.encode("utf-8")), 400)

    def test_dependency_order_and_a_dependency_left_out(self):
        q1, q2, _ = self.batch()
        out = self.accept(q2, code=2)                                       # q1 is not accepted and not here
        self.assertEqual(out["refused"][0]["id"], q2)
        self.assertIn(f"waits on {q1}", out["refused"][0]["why"])
        out = self.accept(q2.lstrip("q"), q1, "--dry-run")                  # `2` means q2; q1 still goes first
        self.assertEqual([x["id"] for x in out["plan"]], [q1, q2])

    def test_a_conflict_skips_what_waits_on_it(self):
        self.repo()
        q1 = self.piece("first", {"shared.txt": "one\n"})
        q2 = self.piece("second", {"shared.txt": "two\n"})
        q3 = self.piece("after second", {"b.txt": "b\n"}, deps=[q2])
        out = self.accept("--all-ready", code=2)
        self.assertEqual([x["id"] for x in out["accepted"]], [q1])
        self.assertEqual([x["id"] for x in out["conflict"]], [q2])
        self.assertEqual([x["id"] for x in out["skipped"]], [q3])

    def test_refusals(self):
        self.repo()
        nc = self.piece("changed nothing", {}, status="failed", record={"kind": "no_changes", "ok": True})
        rf = self.piece("review failed", {"r.txt": "r\n"}, status="failed", record={"kind": "review_failed"})
        un = self.piece("not verified", {"u.txt": "u\n"}, check=None)
        rv = self.piece("review running", {"v.txt": "v\n"})
        run = wq.load(self.work)["items"][rv]["run"]
        d = self.hub / "ccx" / "runs" / "20261029-130000-rev"
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({"run_id": d.name, "label": f"review:{run}", "state": "running"}),
                                    encoding="utf-8")
        go = wq.add(self.work, "still running", "x")["id"]
        wq.update(self.work, go, status="doing", live="20261029-140000-live")
        out = self.accept(nc, rf, un, rv, go, code=2)
        why = {r["id"]: r["why"] for r in out["refused"]}
        self.assertIn("changed nothing", why[nc])
        self.assertIn("review failed", why[rf])
        self.assertIn("not verified", why[un])
        self.assertIn("review is still running", why[rv])
        self.assertIn("still running", why[go])
        self.assertEqual(out["accepted"], [])
        self.assertEqual(self.ledger_rows("q_accept"), [])
        # a joint check given here is evidence enough for the unverified piece
        cmd, _ = self.joint()
        out = self.accept(un, "--check", cmd)
        self.assertEqual([x["id"] for x in out["accepted"]], [un])

    def test_never_into_a_protected_branch_without_a_yes(self):
        q1, _, _ = self.batch()
        git(self.work, "checkout", "-q", "-b", "main")
        out = self.accept(q1, code=2)
        self.assertIn("protected", out["refused"][0]["why"])
        out = self.accept(q1, "--into-protected")
        self.assertEqual([x["id"] for x in out["accepted"]], [q1])

    def test_uncommitted_changes_stop_it(self):
        q1, _, _ = self.batch()
        (self.work / "shared.txt").write_text("edited\n", encoding="utf-8")
        out = self.accept(q1, code=2)
        self.assertIn("uncommitted", out["refused"][0]["why"])

    def test_upstream_based_piece_is_not_landed_on_a_branch_that_trails_the_upstream(self):
        """#349: merging it would also bring in the upstream's commits, a pull nobody asked for."""
        self.repo()
        remote, other = self.work.parent / "remote.git", self.work.parent / "other"
        git(self.work.parent, "init", "-q", "--bare", str(remote))
        git(self.work, "remote", "add", "origin", str(remote))
        git(self.work, "push", "-qu", "origin", "work")
        git(self.work.parent, "clone", "-q", "-b", "work", str(remote), str(other))
        (other / "up.txt").write_text("someone else's\n", encoding="utf-8")
        git(other, "add", "up.txt")
        git(other, "commit", "-qm", "upstream work")
        git(other, "push", "-q", "origin", "work")
        q1 = self.piece("on upstream", {"a.txt": "a\n"}, base="upstream")
        before = git(self.work, "rev-parse", "HEAD")
        out = self.accept(q1, code=2)
        self.assertIn("work is missing 1 commit(s) that this run started from (origin/work at ",
                      out["refused"][0]["why"])
        self.assertIn("pull first (`git pull`)", out["refused"][0]["why"])
        self.assertEqual(git(self.work, "rev-parse", "HEAD"), before)
        self.assertFalse((self.work / "up.txt").exists())
        git(self.work, "merge", "-q", "--ff-only", "origin/work")          # the person pulls; now it lands
        out = self.accept(q1)
        self.assertEqual([x["id"] for x in out["accepted"]], [q1])
        self.assertTrue((self.work / "a.txt").exists())

    def test_a_piece_whose_start_cannot_be_told_is_refused(self):
        """#349: a resume chain that breaks (the record it resumed is gone) is not taken for a head-based run."""
        self.repo()
        q1 = self.piece("resumed", {"a.txt": "a\n"}, record={"resumed_from": "20261029-gone"})
        before = git(self.work, "rev-parse", "HEAD")
        out = self.accept(q1, code=2)
        self.assertIn("cannot tell where this run started", out["refused"][0]["why"])
        self.assertIn("20261029-gone", out["refused"][0]["why"])
        self.assertEqual(git(self.work, "rev-parse", "HEAD"), before)


class TestAcceptBranch(AcceptEnv):
    """#384: accept merges the branch the piece's worktree has checked out, only when it is ccx/<id> of its run or of
    a run up its resume chain (autonomy.run_branch, #374), never the name the queue noted when the run ended."""

    def item(self, q):
        return wq.load(self.work)["items"][q]

    def resume(self, q, branch="keep"):
        """The piece was resumed: run <first>-r2 (resumed_from the first) worked on in the same worktree and
        committed r.txt there; the item now names that run. branch: what the queue noted ("keep" = unchanged)."""
        it = self.item(q)
        first = self.rec(it["run"])
        r2 = f"{it['run']}-r2"
        (Path(it["worktree"]) / "r.txt").write_text("r\n", encoding="utf-8")
        git(it["worktree"], "add", "-A")
        git(it["worktree"], "commit", "-qm", f"ccx run {r2}")
        d = self.hub / "ccx" / "runs" / r2
        d.mkdir(parents=True)
        own = {k: v for k, v in first.items() if k not in ("worktree_base", "base_sha", "base_ref")}  # a resume
        (d / "run.json").write_text(json.dumps({**own, "run_id": r2, "resumed_from": it["run"]}),  # records none
                                    encoding="utf-8")
        fields = {"run": r2} if branch == "keep" else {"run": r2, "branch": branch}
        wq.update(self.work, q, **fields)
        return r2

    def assert_refused(self, q, words):
        before = git(self.work, "rev-parse", "HEAD")
        out = self.accept(q, code=2)
        self.assertEqual(out["accepted"], [])
        self.assertIn(words, out["refused"][0]["why"])
        self.assertEqual(git(self.work, "rev-parse", "HEAD"), before)          # nothing merged
        self.assertIsNone(self.item(q).get("verdict"))
        self.assertFalse(self.item(q).get("merged"))
        self.assertEqual(self.ledger_rows("q_accept"), [])
        return out

    def test_a_detached_worktree_noted_as_HEAD_is_refused_not_merged_into_itself(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        git(self.item(q1)["worktree"], "checkout", "-q", "--detach")
        wq.update(self.work, q1, branch="HEAD")             # what `git rev-parse --abbrev-ref HEAD` noted
        self.assert_refused(q1, "detached HEAD")
        self.assertEqual(self.accept(q1, "--dry-run", code=2).get("plan", []), [])

    def test_a_piece_noted_as_HEAD_with_a_verdict_is_not_taken_for_landed(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        wq.update(self.work, q1, branch="HEAD", verdict=True)
        out = self.accept("--all-ready")                    # its worktree is on ccx/<run>: that branch lands
        self.assertEqual([x["id"] for x in out["accepted"]], [q1])
        self.assertTrue((self.work / "a.txt").exists())

    def test_a_worktree_moved_to_another_branch_is_refused(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        wt = self.item(q1)["worktree"]
        git(wt, "checkout", "-q", "-b", "elsewhere")
        (Path(wt) / "x.txt").write_text("x\n", encoding="utf-8")   # left uncommitted
        self.assert_refused(q1, "the worktree is on elsewhere")
        self.assertEqual(git(wt, "status", "--porcelain"), "?? x.txt")        # not committed to elsewhere either
        self.assertFalse((self.work / "a.txt").exists())

    def test_a_resumed_piece_lands_the_first_runs_branch(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        first = self.item(q1)["run"]
        self.resume(q1, branch=None)                        # the queue noted no branch: ccx/<r2> would not exist
        dry = self.accept(q1, "--dry-run")
        self.assertEqual(dry["plan"][0]["branch"], f"ccx/{first}")
        out = self.accept(q1)
        self.assertEqual([x["id"] for x in out["accepted"]], [q1])
        self.assertTrue((self.work / "a.txt").exists() and (self.work / "r.txt").exists())
        self.assertEqual(self.ledger_rows("q_accept")[0]["branch"], f"ccx/{first}")

    def test_a_resumed_piece_whose_worktree_is_detached_is_refused(self):
        self.repo()
        q1 = self.piece("one", {"a.txt": "a\n"})
        self.resume(q1)
        git(self.item(q1)["worktree"], "checkout", "-q", "--detach")
        self.assert_refused(q1, "detached HEAD")

    def upstream(self):
        remote = self.work.parent / "remote.git"
        git(self.work.parent, "init", "-q", "--bare", str(remote))
        git(self.work, "remote", "add", "origin", str(remote))
        git(self.work, "push", "-qu", "origin", "work")

    def test_an_upstream_based_piece_moved_to_another_branch_is_refused(self):
        self.repo()
        self.upstream()
        q1 = self.piece("on upstream", {"a.txt": "a\n"}, base="upstream")
        self.assertEqual(self.rec(self.item(q1)["run"]).get("worktree_base"), "upstream")
        git(self.item(q1)["worktree"], "checkout", "-q", "-b", "elsewhere")
        self.assert_refused(q1, "the worktree is on elsewhere")

    def test_a_resumed_upstream_based_piece_lands_the_first_runs_branch(self):
        self.repo()
        self.upstream()
        q1 = self.piece("on upstream", {"a.txt": "a\n"}, base="upstream")
        first = self.item(q1)["run"]
        self.resume(q1, branch=None)
        out = self.accept(q1)
        self.assertEqual([x["id"] for x in out["accepted"]], [q1])
        self.assertEqual(self.ledger_rows("q_accept")[0]["branch"], f"ccx/{first}")
        self.assertTrue((self.work / "r.txt").exists())


class TestPipelineEndToEnd(AcceptEnv):
    def why(self) -> dict:
        """Each item's status, summary and its run's kind and attempts (CI failures used to show only `failed`)."""
        out = {}
        for i, x in self.items().items():
            try:
                rec = self.rec(x["run"])
                ran = (rec.get("kind"), [(a.get("kind"), a.get("error")) for a in rec.get("attempts") or []])
            except (KeyError, TypeError, OSError, ValueError):
                ran = None
            out[i] = (x["status"], x.get("summary"), ran)
        return out

    def test_q_run_then_ls_then_accept_then_the_dependent_runs(self):
        self.env["FAKE_TOUCH"] = "1"
        self.repo()
        w = [self.q("add", f"w{i}", "--brief", f"write piece {i}", "--minutes", "5", "--mode", "write", "--to",
                    "codex", "--check", NEW_FILE)["id"] for i in range(2)]
        after = self.q("add", "after", "--brief", "write the glue", "--minutes", "5", "--mode", "write",
                       "--to", "codex", "--dep", "1", "--dep", w[1])               # `1` means q1
        self.assertEqual(self.items()[after["id"]]["deps"], w)
        out = self.q("run")
        self.assertEqual({r["id"] for r in out["results"]}, set(w))
        why = self.why()                                                    # what to read when one did not finish
        ls = self.ccx("q", "ls").stdout
        self.assertLess(len(ls.encode("utf-8")), 400 + 80)                  # 3 lines of pieces + the queue line
        for i in w:
            self.assertIn(f"{i} unmerged codex", ls, why)
            self.assertIn(f"next: ccx q done {i} --ok 1, then ccx q accept {i}", ls)   # verdict first, as in ccx ui
        acc = self.accept("--all-ready")
        self.assertEqual([x["id"] for x in acc["accepted"]], w)
        self.assertIn("ccx q run", acc["next"])
        self.assertNotIn("unmerged", self.ccx("q", "ls").stdout)
        out = self.q("run")
        self.assertEqual([r["id"] for r in out["results"]], [after["id"]])


class TestLsAndDone(QEnv):
    def test_compact_ls_for_two_pieces(self):
        a = self.q("add", "look at the parser module", "--brief", "x", "--minutes", "5")
        self.q("add", "and its tests", "--brief", "y", "--minutes", "5", "--dep", a["id"])
        self.q("run")
        r = self.ccx("q", "ls")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 3)                                     # one per piece + the queue line
        self.assertLess(len(r.stdout.encode("utf-8")), 400)
        self.assertTrue(lines[0].startswith(f"{a['id']} done "))
        self.assertIn("$", lines[0])
        self.assertIn("spent $", lines[-1])
        self.assertEqual(len(self.q("ls", "--long")["items"]), 2)          # the full JSON is one flag away

    def test_dep_given_as_a_number(self):
        a = self.q("add", "a", "--brief", "x", "--minutes", "5")
        b = self.q("add", "b", "--brief", "y", "--dep", a["id"].lstrip("q"))
        self.assertEqual(b["deps"], [a["id"]])
        r = self.ccx("q", "add", "c", "--dep", "9")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("q9", r.stdout + r.stderr)

    def test_done_of_several_ids_needs_evidence_for_each(self):
        ids = [self.q("add", f"p{i}", "--brief", f"look at {i}", "--minutes", "5")["id"] for i in range(2)]
        self.q("run")
        r = self.ccx("q", "done", *ids, "--ok", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("evidence for each", r.stdout + r.stderr)
        self.assertTrue(all(i.get("verdict") is None for i in self.q("ls", "--long")["items"]))
        r = self.ccx("q", "done", *ids, "--ok", "1", "--note", f"{ids[0]}: read the diff")
        self.assertNotEqual(r.returncode, 0)                                 # the second one still has none
        out = self.q("done", ids[0], ids[1].lstrip("q"), "--ok", "1", "--note", f"{ids[0]}: read the diff",
                     "--note", f"{ids[1].lstrip('q')}: ran it")
        self.assertEqual(out["ids"], ids)
        self.assertEqual(self.rec(self.items()[ids[1]]["run"])["verdict"]["note"], "ran it")
        one = self.q("add", "p2", "--brief", "z", "--minutes", "5")["id"]
        self.assertEqual(self.q("done", one, "--ok", "1")["id"], one)        # one id: as before
