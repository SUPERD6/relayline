"""`ccx report --daily`: one page per day from a fake ledger. No real CLI is called."""
import json
import unittest
from datetime import datetime, timezone, timedelta

from ccx import daily, ledger
from ccx.config import Paths
from test_ccx import Env

UTC = timezone.utc
E8 = timezone(timedelta(hours=8))


def ts(day, hh=12, mm=0, tz=UTC):
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hh, mm, tzinfo=tz).timestamp()


def run(rid, day="2026-11-10", hh=12, to="codex", cwd="/w/projA", status="done", ok=True, ae=0.10, cost=None,
        secs=60.0, label=None, tz=UTC, **kw):
    r = {"run_id": rid, "ts": ts(day, hh, tz=tz), "to": to, "cwd": cwd, "status": status, "ok": ok, "ae_usd": ae,
         "cost_usd": cost, "seconds": secs, "attempts": 1, "usage": {"input": 100, "cache_write": 0, "cached": 0, "output": 10},
         "rungs": [f"{to}:m:low"], "label": label or rid}
    r.update(kw)
    return r


def verify(rid, ok, day="2026-11-10", hh=13, soft=False, reason=None):
    r = {"type": "verify", "run_id": rid, "ok": ok, "ts": ts(day, hh)}
    if soft:
        r["soft"] = True
    if reason:
        r["reason"] = reason
    return r


class TestDaily(Env):
    def setUp(self):
        super().setUp()
        self.p = Paths(self.hub)

    def put(self, *rows, runs=None):
        self.p.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.p.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        for rid, rec in (runs or {}).items():
            (self.p.runs / rid).mkdir(parents=True, exist_ok=True)
            (self.p.runs / rid / "run.json").write_text(json.dumps(rec), encoding="utf-8")

    def build(self, day="2026-11-10", **kw):
        return daily.build(self.p, day, kw.pop("tz", UTC), **kw)

    def test_empty_or_missing_ledger_gives_a_page_of_zeros(self):
        d = self.build()                                    # no ledger file at all
        self.assertEqual(d["total"]["runs"], 0)
        md = daily.render(d)
        self.assertIn("0/0", md)
        self.assertIn("2026-11-10", md)
        self.put()                                          # an empty file
        self.assertEqual(self.build()["total"]["runs"], 0)

    def test_outcomes_with_numerators_and_denominators(self):
        self.put(run("a"), run("b"), run("c"), run("d", status="failed", ok=False), run("e"),
                 verify("a", True), verify("b", False, reason="wrong"), verify("e", True, soft=True))
        t = self.build()["total"]
        self.assertEqual((t["runs"], t["right"], t["failed"], t["unverified"]), (5, 1, 2, 2))
        self.assertEqual(t["failed_by_verdict"], 1)
        self.assertEqual(t["probable_right"], 1)            # a probable verdict is not "right"
        md = daily.render(self.build())
        self.assertIn("做对 1/5 (20%)", md)
        self.assertIn("失败 2/5 (40%)", md)
        self.assertIn("未验证 2/5 (40%)", md)

    def test_later_hard_verdict_overrides_earlier_and_probable(self):
        self.put(run("a"), verify("a", False, hh=13), verify("a", True, hh=14), verify("a", False, soft=True, hh=15))
        self.assertEqual(self.build()["total"]["right"], 1)

    def test_multi_project_and_agent_split_and_cost(self):
        self.put(run("a", cwd="C:\\x\\alpha", ae=0.5, cost=0.4, secs=100), run("b", cwd="/w/beta", to="claude", ae=1.0, secs=30),
                 run("c", cwd="/w/beta/", to="claude", ae=None, secs=20))
        d = self.build()
        self.assertEqual(set(d["by_project"]), {"alpha", "beta"})
        self.assertEqual(d["by_project"]["beta"]["runs"], 2)
        self.assertEqual(set(d["by_agent"]), {"codex", "claude"})
        t = d["total"]
        self.assertAlmostEqual(t["ae_usd"], 1.5)
        self.assertEqual((t["ae_known"], t["cost_known"]), (2, 1))   # a missing price is not counted as $0
        self.assertEqual(t["seconds"], 150)
        md = daily.render(d)
        self.assertIn("API 等价 $1.50（2/3 次有记录）", md)
        self.assertNotIn("C:\\x", md)                         # the folder name only, never the path

    def test_days_split_across_days(self):
        self.put(run("a", day="2026-11-09"), run("b", day="2026-11-10"), run("c", day="2026-11-10"), run("d", day="2026-11-11"),
                 verify("a", True, day="2026-11-10"))
        self.assertEqual(self.build("2026-11-09")["total"]["right"], 1)    # the verdict lands on the run's day
        self.assertEqual(self.build("2026-11-10")["total"]["runs"], 2)
        self.assertEqual(self.build("2026-11-12")["total"]["runs"], 0)

    def test_timezone_boundary(self):
        # 2026-11-10 23:30 UTC is 2026-11-11 07:30 in +08:00
        self.put(run("a", day="2026-11-10", hh=23))
        self.assertEqual(self.build("2026-11-10", tz=UTC)["total"]["runs"], 1)
        self.assertEqual(self.build("2026-11-11", tz=UTC)["total"]["runs"], 0)
        self.assertEqual(self.build("2026-11-10", tz=E8)["total"]["runs"], 0)
        self.assertEqual(self.build("2026-11-11", tz=E8)["total"]["runs"], 1)
        self.assertEqual(daily.resolve_day("today", E8, now=ts("2026-11-10", 20)), "2026-11-11")
        self.assertEqual(daily.resolve_day("yesterday", UTC, now=ts("2026-11-10", 20)), "2026-11-09")

    def test_parse_tz(self):
        self.assertIsNone(daily.parse_tz(None))
        self.assertEqual(daily.parse_tz("+08:00"), E8)
        self.assertEqual(daily.parse_tz("-5").utcoffset(None), timedelta(hours=-5))
        self.assertEqual(daily.parse_tz("UTC"), UTC)
        for bad in ("Mars", "+25:00", "+08:99"):
            with self.assertRaises(ValueError):
                daily.parse_tz(bad)
        with self.assertRaises(ValueError):
            daily.resolve_day("11/10", UTC)

    def test_evals_dismissed_and_reviews_are_kept_apart(self):
        self.put(run("a"), run("e", label="eval-x"), run("n", no_ab=True), run("g"), {"type": "dismiss", "run_id": "g", "ts": ts("2026-11-10", 15)},
                 run("r", label="review:a", ae=0.25, secs=40))
        d = self.build()
        self.assertEqual(d["total"]["runs"], 1)
        self.assertEqual((d["evals_excluded"], d["reviews"]), (3, 1))
        self.assertAlmostEqual(d["review_cost"]["ae_usd"], 0.25)
        self.assertEqual(self.build(include_evals=True)["total"]["runs"], 4)

    def test_quota_events_from_run_records_and_unreadable_records_are_unknown(self):
        self.put(run("a"), run("b"), run("c"), run("d"),
                 runs={"a": {"quota_stop": {"agent": "codex"}, "quota_fallback": {"from": "codex", "to": "claude"}},
                       "b": {"attempts": [{"kind": "quota"}]}, "c": {"attempts": [{"kind": "ok"}]}})
        q = self.build()["quota"]
        self.assertEqual((q["readable"], q["runs"], q["hit"], q["relayed"]), (3, 4, 2, 1))
        md = daily.render(self.build())
        self.assertIn("run.json 读不到：1/4", md)
        self.assertIn("2/3 (67%)", md)

    def test_hand_marked_problems_are_listed_on_the_day_of_the_mark(self):
        self.put(run("a", cwd="/w/alpha"), run("b"), verify("a", False, day="2026-11-11", reason="wrong|bad"),
                 verify("b", True, day="2026-11-11"), verify("b", False, soft=True, day="2026-11-11"),
                 {"type": "dismiss", "run_id": "b", "note": "test run", "ts": ts("2026-11-11", 9)})
        self.assertEqual(self.build("2026-11-10")["flagged"], [])
        fl = self.build("2026-11-11")["flagged"]
        self.assertEqual([(f["run_id"], f["what"]) for f in fl], [("a", "marked wrong"), ("b", "dismissed")])
        self.assertIn("wrong/bad", daily.render(self.build("2026-11-11")))      # a pipe would break the table

    def test_planned_first_rung_is_used_when_present_and_absent_is_fine(self):
        self.put(run("a", planned_first_rung="codex:m:low"), run("b", planned_first_rung="claude:x:high"), run("c"))
        pf = self.build()["planned_first"]
        self.assertEqual((pf["with_field"], pf["kept"]), (2, 1))
        self.assertIn("1/2 (50%)", daily.render(self.build()))
        self.put(run("c"))
        self.assertNotIn("planned_first_rung", daily.render(self.build()))

    def test_bad_ledger_lines_do_not_break_the_page(self):
        self.p.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.p.ledger.write_text("not json\n" + json.dumps(run("a")) + "\n{broken\n" + json.dumps({"type": "verify"}) + "\n",
                                 encoding="utf-8")
        self.assertEqual(self.build()["total"]["runs"], 1)

    def test_cli_writes_under_hub_and_leaves_the_dashboard_alone(self):
        self.put(run("a", day="2026-11-10"), verify("a", True))
        r = self.ccx("report", "--daily", "2026-11-10", "--tz", "UTC")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        f = self.hub / "ccx" / "daily" / "2026-11-10.md"
        self.assertEqual(out["daily"], str(f))
        self.assertTrue(f.exists())
        self.assertIn("做对 1/1 (100%)", f.read_text(encoding="utf-8"))
        self.assertFalse((self.hub / "ccx" / "report").exists())
        r2 = self.ccx("report", "--daily", "--out", str(self.work / "x.md"), "--tz", "bogus")
        self.assertNotEqual(r2.returncode, 0)

    def test_worktree_runs_fold_into_their_repo(self):
        self.put(run("a", cwd="/w/alpha"), run("b", cwd="/w/alpha/.ccx/worktrees/20261110-1-abcd"),
                 run("c", cwd="/w/.ccx-worktrees/alpha/20261110-2-abcd"))
        d = self.build()
        self.assertEqual(list(d["by_project"]), ["alpha"])
        self.assertEqual(d["by_project"]["alpha"]["runs"], 3)

    def test_internal_runs_are_left_out_like_the_ui_does(self):
        from ccx import ui
        self.assertTrue(set(ui.INTERNAL) <= set(daily.INTERNAL))
        self.put(run("a"), run("h", label="handoff-from-transcript"), run("d", label="discuss:x"), run("w", label="way:y"),
                 run("p", label="quota-probe"), run("k", ephemeral=True))
        d = self.build()
        self.assertEqual((d["total"]["runs"], d["internal_excluded"], d["evals_excluded"]), (1, 4, 1))   # quota-probe is an eval probe

    def test_evaluation_scripts_verdicts_are_not_hand_marked_problems(self):
        self.put(run("e", label="eval-r2-x"), run("a"), verify("e", False, reason="eval-wrong"), verify("a", False, reason="mine"))
        self.assertEqual([f["run_id"] for f in self.build()["flagged"]], ["a"])
        self.assertEqual([f["run_id"] for f in self.build(include_evals=True)["flagged"]], ["e", "a"])

    def test_dismiss_judged_again_later_is_not_listed(self):
        self.put(run("a"), run("b"), {"type": "dismiss", "run_id": "a", "ts": ts("2026-11-10", 14)},
                 {"type": "dismiss", "run_id": "b", "ts": ts("2026-11-10", 14)}, verify("a", True, hh=15))
        self.assertEqual([f["run_id"] for f in self.build()["flagged"]], ["b"])

    def test_day_is_normalised(self):
        self.assertEqual(daily.resolve_day("2026-1-5", UTC), "2026-01-05")
        self.put(run("a", day="2026-01-05"))
        self.assertEqual(self.build("2026-1-5")["total"]["runs"], 1)
        self.assertEqual(self.build("2026-1-5")["day"], "2026-01-05")

    def test_running_runs_are_not_failures(self):
        self.put(run("a", status="running", ok=False), run("b"), run("c", status="failed", ok=False))
        t = self.build()["total"]
        self.assertEqual((t["runs"], t["running"], t["failed"], t["unverified"]), (3, 1, 1, 1))
        self.assertIn("还在运行 1/3", daily.render(self.build()))

    def test_bad_timestamps_and_run_records_do_not_raise(self):
        bad = run("x")
        bad["ts"] = "yesterday"
        self.put(bad, run("a"), run("b"), run("c"), verify("a", False), {"type": "verify", "run_id": "a", "ok": False, "ts": "no"},
                 runs={"b": [1, 2], "c": {"attempts": "oops"}})
        d = self.build()
        self.assertEqual(d["total"]["runs"], 3)
        self.assertEqual(d["quota"]["readable"], 1)

    def test_local_time_zone_from_the_tz_environment_variable(self):
        import os
        import time
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset is not available on Windows")
        old = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Asia/Shanghai"
            time.tzset()
            self.put(run("a", day="2026-11-10", hh=23))          # 2026-11-11 07:00 in Shanghai
            self.assertEqual(daily.build(self.p, "2026-11-11", None)["total"]["runs"], 1)
            self.assertEqual(daily.build(self.p, "2026-11-10", None)["total"]["runs"], 0)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_cli_refuses_publish_with_daily_and_tz_without_it(self):
        self.put(run("a"))
        self.assertNotEqual(self.ccx("report", "--daily", "2026-11-10", "--publish").returncode, 0)
        self.assertNotEqual(self.ccx("report", "--tz", "UTC").returncode, 0)

    def test_read_only_on_the_ledger(self):
        self.put(run("a"))
        before = self.p.ledger.read_bytes()
        daily.write(self.p, "2026-11-10", tz=UTC)
        self.assertEqual(self.p.ledger.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
