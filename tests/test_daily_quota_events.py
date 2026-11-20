"""`ccx report --daily --quota-events`: decision 3 (#411) applied to run records and relay packets. Fake ledger,
fake run.json and fake relay packets only; no real CLI is called."""
import json
import os
import unittest
from datetime import datetime, timezone

from ccx import daily, daily_quota
import test_daily
from test_daily import UTC, run, ts

DAY = "2026-11-19"
H = 3600


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestQuotaEvents(test_daily.TestDaily):
    T0 = ts(DAY, 10)                      # a run starting here, 60 s long, hits the limit at T0 + 60

    def q(self, now_h=10.0, workspaces=(), **kw):
        return daily.build(self.p, DAY, UTC, now=self.T0 + now_h * H, quota_events=True,
                           quota_workspaces=workspaces, **kw)["quota_events"]

    def ev(self, q, ident):
        return next(e for e in q["events"] if e["id"] == ident)

    def notes(self, *rows):
        f = daily_quota.notes_path(self.p)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    # ---- packets
    def packet(self, pid, state="quota_stopped", at=None, source="claude", session="s1", git=None, kind=None):
        folder = self.work / ".ccx" / "relay"
        folder.mkdir(parents=True, exist_ok=True)
        pk = {"id": pid, "state": state, "source": source, "source_session": session, "workspace": str(self.work),
              "captured_at": iso(at or self.T0), "git": git or {"head": "abc", "content_fingerprint": "f"},
              "quota_signal": {"kind": kind or ("quota" if state == "quota_stopped" else "rate_limit_unconfirmed")}}
        (folder / f"{pid}.json").write_text(json.dumps(pk), encoding="utf-8")

    def cont(self, pid, name="1", state="exited", start=None, end=None, **kw):
        f = self.work / ".ccx" / "relay" / f"{pid}.continue-{name}.json"
        rec = {"packet": pid, "to": "codex", "state": state, "exit_code": 0, "workspace_changed": False,
               "changes_observed": True, "started_at": iso(start or self.T0 + H), **kw}
        f.write_text(json.dumps(rec), encoding="utf-8")
        e = end or (self.T0 + 2 * H)
        os.utime(f, (e, e))

    PID = "a" * 32

    # ---- sub-agent events
    def test_default_page_has_no_quota_events_section(self):
        self.put(run("a", day=DAY, hh=10), runs={"a": {"quota_stop": {"agent": "codex"}}})
        d = daily.build(self.p, DAY, UTC)
        self.assertNotIn("quota_events", d)
        self.assertNotIn("额度事件（决定 3", daily.render(d))
        self.assertIn("quota_events", daily.build(self.p, DAY, UTC, quota_events=True))

    def test_fallback_that_finishes_is_success_and_names_both_sides(self):
        self.put(run("a", day=DAY, hh=10, secs=60),
                 runs={"a": {"quota_stop": {"agent": "codex"}, "quota_fallback": {"from": "codex", "to": "claude"}}})
        e = self.ev(self.q(), "a")
        self.assertEqual((e["verdict"], e["role"], e["from"], e["to"]), ("success", "sub_agent", "codex", "claude"))
        self.assertIn("quota_fallback", e["judged_by"]["machine"])

    def test_fallback_run_that_did_not_finish_is_failure_and_running_is_unknown(self):
        self.put(run("a", day=DAY, hh=10, ok=False, status="failed"), run("b", day=DAY, hh=11, status="running", ok=False),
                 runs={"a": {"quota_fallback": {"from": "codex", "to": "claude"}},
                       "b": {"quota_fallback": {"from": "codex", "to": "claude"}}})
        q = self.q()
        self.assertEqual(self.ev(q, "a")["verdict"], "failure")
        self.assertEqual(self.ev(q, "b")["verdict"], "unknown")

    def test_later_hard_verdict_wrong_turns_a_finished_fallback_into_failure(self):
        self.put(run("a", day=DAY, hh=10), {"type": "verify", "run_id": "a", "ok": False, "ts": self.T0 + H},
                 runs={"a": {"quota_fallback": {"from": "codex", "to": "claude"}}})
        self.assertEqual(self.ev(self.q(), "a")["verdict"], "failure")

    def test_stop_without_fallback_or_resume_fails_after_four_hours_and_is_pending_before(self):
        self.put(run("a", day=DAY, hh=10, secs=60), runs={"a": {"quota_stop": {"agent": "codex"}}})
        self.assertEqual(self.ev(self.q(now_h=3), "a")["verdict"], "unknown")
        late = self.ev(self.q(now_h=4.5), "a")
        self.assertEqual(late["verdict"], "failure")
        self.assertIn("既没改派也没接续", late["reason"])

    def test_resume_on_other_agent_within_four_hours_is_success_and_resume_is_not_a_new_event(self):
        self.put(run("a", day=DAY, hh=10, secs=60), run("b", day=DAY, hh=11, to="claude", secs=300, rungs=["claude:m:low"]),
                 runs={"a": {"quota_stop": {"agent": "codex"}}, "b": {"resumed_from": "a",
                       "quota_fallback": None}})
        q = self.q()
        self.assertEqual([e["id"] for e in q["events"]], ["a"])
        self.assertEqual((self.ev(q, "a")["verdict"], self.ev(q, "a")["continued_by"]), ("success", "b"))

    def test_resume_on_same_agent_and_model_is_not_a_continuation(self):
        self.put(run("a", day=DAY, hh=10), run("b", day=DAY, hh=11), runs={"a": {"quota_stop": {"agent": "codex"}},
                                                                            "b": {"resumed_from": "a"}})
        e = self.ev(self.q(), "a")
        self.assertEqual(e["verdict"], "failure")
        self.assertIn("没换家也没换模型", e["reason"])

    def test_resume_after_four_hours_is_failure(self):
        self.put(run("a", day=DAY, hh=10, secs=60), run("b", day=DAY, hh=15, to="claude", rungs=["claude:m:low"]),
                 runs={"a": {"quota_stop": {"agent": "codex"}}, "b": {"resumed_from": "a"}})
        self.assertEqual(self.ev(self.q(now_h=12), "a")["verdict"], "failure")

    def test_starting_the_same_task_again_is_a_redo_not_a_continuation(self):
        self.put(run("a", day=DAY, hh=10, label="task-x"), run("c", day=DAY, hh=11, to="claude", label="task-x"),
                 runs={"a": {"quota_stop": {"agent": "codex"}}, "c": {}})
        e = self.ev(self.q(), "a")
        self.assertEqual(e["verdict"], "failure")
        self.assertIn("重做", e["reason"])

    def test_continuation_inheriting_the_fallback_field_is_not_a_new_event(self):
        fb = {"from": "codex", "to": "claude"}
        self.put(run("a", day=DAY, hh=10), run("b", day=DAY, hh=11, to="claude"),
                 runs={"a": {"quota_fallback": fb}, "b": {"resumed_from": "a", "quota_fallback": fb}})
        self.assertEqual([e["id"] for e in self.q()["events"]], ["a"])

    def test_wait_note_is_not_attempted_and_not_counted_but_listed(self):
        self.put(run("a", day=DAY, hh=10, secs=60), runs={"a": {"quota_stop": {"agent": "codex"}}})
        self.notes({"kind": "wait", "id": "a", "ts": self.T0 + 600})
        q = self.q(now_h=9)
        e = self.ev(q, "a")
        self.assertEqual(e["verdict"], "not_attempted")
        self.assertEqual(e["judged_by"]["human"], ["wait"])
        self.assertEqual((q["summary"]["combined"]["counted"], q["summary"]["combined"]["not_attempted"]), (0, 1))
        self.notes({"kind": "wait", "id": "a", "ts": self.T0 + 9 * H})      # written long after: not "at the time"
        self.assertEqual(self.ev(self.q(now_h=9), "a")["verdict"], "failure")

    def test_before_the_rule_start_evals_internal_reviews_and_excluded_notes_are_not_events(self):
        self.put(run("old", day="2026-11-18", hh=10), run("ev", day=DAY, hh=10, label="eval-x"),
                 run("rv", day=DAY, hh=10, label="review:x"), run("ex", day=DAY, hh=10), run("ok", day=DAY, hh=10),
                 runs={k: {"quota_stop": {"agent": "codex"}} for k in ("old", "ev", "rv", "ex")})
        self.notes({"kind": "exclude", "id": "ex", "ts": self.T0, "note": "simulated"})
        q = self.q()
        self.assertEqual(q["events"], [])
        self.assertEqual(q["not_counted"]["excluded_by_note"], 1)

    def test_lost_work_note_fails_the_whole_claim_whatever_the_rate(self):
        rows, recs = [], {}
        for i in range(6):
            rows.append(run(f"r{i}", day=DAY, hh=10 + i // 2, mm=i))
            recs[f"r{i}"] = {"quota_fallback": {"from": "codex", "to": "claude"}}
        self.put(*rows, runs=recs)
        self.assertEqual(self.q()["summary"]["combined"]["verdict"], "Pass")
        self.notes({"kind": "lost", "id": "r3", "ts": self.T0 + H})
        s = self.q()["summary"]["combined"]
        self.assertEqual((s["verdict"], s["claim_fail"], s["success"]), ("Fail", True, 5))

    # ---- lead events
    def test_quota_stopped_packet_with_clean_continue_and_done_note_is_success(self):
        self.packet(self.PID)
        self.cont(self.PID)
        self.notes({"kind": "done", "id": self.PID, "ts": self.T0 + 2 * H + 60})
        q = self.q(workspaces=[self.work])
        e = self.ev(q, self.PID)
        self.assertEqual((e["verdict"], e["role"], e["from"], e["to"]), ("success", "lead", "claude", "codex"))
        self.assertEqual(e["judged_by"]["human"], ["done"])
        self.assertIn("continue record", e["judged_by"]["machine"])

    def test_lead_without_done_note_is_unknown_then_failure_after_four_hours(self):
        self.packet(self.PID)
        self.cont(self.PID)
        self.assertEqual(self.ev(self.q(now_h=3, workspaces=[self.work]), self.PID)["verdict"], "unknown")
        self.assertEqual(self.ev(self.q(now_h=7, workspaces=[self.work]), self.PID)["verdict"], "failure")

    def test_workspace_changed_needs_a_human_check_before_it_can_succeed(self):
        self.packet(self.PID)
        self.cont(self.PID, workspace_changed=True)
        self.notes({"kind": "done", "id": self.PID, "ts": self.T0 + 2 * H + 60})
        e = self.ev(self.q(workspaces=[self.work]), self.PID)
        self.assertEqual(e["verdict"], "unknown")
        self.assertIn("人工", e["reason"])
        self.notes({"kind": "done", "id": self.PID, "ts": self.T0 + 2 * H + 60}, {"kind": "intact", "id": self.PID, "ts": self.T0 + 3 * H})
        e = self.ev(self.q(workspaces=[self.work]), self.PID)
        self.assertEqual(e["verdict"], "success")
        self.assertEqual(sorted(e["judged_by"]["human"]), ["done", "intact"])

    def test_unknown_content_fingerprint_also_needs_a_human_check(self):
        self.packet(self.PID, git={"head": "abc", "content_fingerprint": "Unknown"})
        self.cont(self.PID)
        self.assertEqual(self.ev(self.q(workspaces=[self.work]), self.PID)["verdict"], "unknown")

    def test_lead_failures(self):
        a, b, c, d = "a" * 32, "b" * 32, "c" * 32, "d" * 32
        self.packet(a)                                                  # no continue record at all
        self.packet(b)
        self.cont(b, state="prepared")                                  # prepared is no continuation
        self.packet(c)
        self.cont(c, state="no_changes", changes_observed=False)        # continued but nothing was done
        self.packet(d, git={"head": "Unknown", "snapshot_status": "Unknown"})   # cannot be continued
        q = self.q(now_h=9, workspaces=[self.work])
        for pid in (a, b, c, d):
            self.assertEqual(self.ev(q, pid)["verdict"], "failure", pid)
        self.assertIn("没法接续", self.ev(q, d)["reason"])
        self.assertEqual(self.ev(self.q(now_h=1, workspaces=[self.work]), a)["verdict"], "unknown")

    def test_continue_after_four_hours_is_failure(self):
        self.packet(self.PID)
        self.cont(self.PID, start=self.T0 + 5 * H, end=self.T0 + 6 * H)
        self.assertEqual(self.ev(self.q(now_h=9, workspaces=[self.work]), self.PID)["verdict"], "failure")

    def test_second_packet_of_the_same_session_continued_is_failure(self):
        a, b = "a" * 32, "b" * 32
        self.packet(a, session="s9")
        self.packet(b, session="s9", at=self.T0 + 600)
        self.cont(a)
        self.cont(b, name="2")
        self.notes({"kind": "done", "id": a, "ts": self.T0 + 2 * H + 60}, {"kind": "done", "id": b, "ts": self.T0 + 2 * H + 60})
        q = self.q(workspaces=[self.work])
        self.assertEqual(self.ev(q, a)["verdict"], "failure")
        self.assertIn("另一个 packet", self.ev(q, a)["reason"])

    def test_unconfirmed_packet_counts_only_with_a_timely_human_confirmation(self):
        u = "e" * 32
        self.packet(u, state="rate_limit_unconfirmed")
        q = self.q(workspaces=[self.work])
        self.assertEqual((q["events"], q["not_counted"]["unconfirmed_packets"]), ([], 1))
        self.notes({"kind": "confirm", "id": u, "ts": self.T0 + 2 * H, "basis": "window_full"})     # too late
        self.assertEqual(self.q(workspaces=[self.work])["events"], [])
        self.notes({"kind": "confirm", "id": u, "ts": self.T0 + 600, "basis": "reset_ge_1h"})
        e = self.ev(self.q(workspaces=[self.work]), u)
        self.assertEqual(e["role"], "lead")
        self.assertIn("confirm", e["judged_by"]["human"])
        self.notes({"kind": "confirm", "id": u, "ts": self.T0 + 600, "basis": "felt like it"})
        self.assertEqual(self.q(workspaces=[self.work])["events"], [])

    def test_confirmation_after_the_continuation_started_does_not_count(self):
        u = "e" * 32
        self.packet(u, state="rate_limit_unconfirmed")
        self.cont(u, start=self.T0 + 300)
        self.notes({"kind": "confirm", "id": u, "ts": self.T0 + 600, "basis": "window_full"})
        self.assertEqual(self.q(workspaces=[self.work])["events"], [])

    def test_workspaces_come_from_ledger_cwds_too(self):
        self.put(run("x", day=DAY, hh=9, cwd=str(self.work)))
        self.packet(self.PID)
        self.assertEqual([e["id"] for e in self.q()["events"]], [self.PID])

    # ---- summary
    def test_summary_thresholds_roles_and_lower_bound(self):
        rows, recs = [], {}
        for i in range(5):
            rows.append(run(f"s{i}", day=DAY, hh=10, mm=i, ok=(i != 4), status="done" if i != 4 else "failed"))
            recs[f"s{i}"] = {"quota_fallback": {"from": "codex", "to": "claude"}}
        self.put(*rows, runs=recs)
        s = self.q()["summary"]
        c = s["combined"]
        self.assertEqual((c["counted"], c["success"], c["meets_min_events"], c["meets_min_rate"], c["verdict"]),
                         (5, 4, True, True, "Pass"))
        self.assertAlmostEqual(c["lower_bound_95"], 0.343, places=2)
        self.assertEqual((s["by_role"]["sub_agent"]["counted"], s["by_role"]["lead"]["counted"]), (5, 0))
        self.assertIn("Unknown", s["lead_note"])
        self.assertIn("codex", " ".join(s["by_pair"]))

    def test_fewer_than_five_events_is_unknown_and_unreachable_rate_is_fail(self):
        self.put(*[run(f"s{i}", day=DAY, hh=10, mm=i) for i in range(4)],
                 runs={f"s{i}": {"quota_fallback": {"from": "codex", "to": "claude"}} for i in range(4)})
        self.assertEqual(self.q()["summary"]["combined"]["verdict"], "Unknown")
        rows = [run(f"f{i}", day=DAY, hh=10, mm=i, ok=False, status="failed") for i in range(5)]
        self.put(*rows, runs={f"f{i}": {"quota_fallback": {"from": "codex", "to": "claude"}} for i in range(5)})
        self.assertEqual(self.q()["summary"]["combined"]["verdict"], "Fail")

    def test_lead_and_sub_events_are_pooled_but_reported_apart(self):
        rows, recs = [], {}
        for i in range(3):
            rows.append(run(f"s{i}", day=DAY, hh=9, mm=i, cwd=str(self.work)))
            recs[f"s{i}"] = {"quota_fallback": {"from": "codex", "to": "claude"}}
        self.put(*rows, runs=recs)
        for i, pid in enumerate(("1" * 32, "2" * 32)):
            self.packet(pid, session=f"s{i}")
            self.cont(pid, name=str(i))
            self.notes(*[{"kind": "done", "id": x, "ts": self.T0 + 2 * H + 60} for x in ("1" * 32, "2" * 32)])
        s = self.q()["summary"]
        self.assertEqual((s["combined"]["counted"], s["combined"]["success"], s["combined"]["verdict"]), (5, 5, "Pass"))
        self.assertEqual((s["by_role"]["lead"]["counted"], s["by_role"]["sub_agent"]["counted"]), (2, 3))
        self.assertIsNone(s["lead_note"])

    def test_two_period_rule_needs_five_in_each_period(self):
        rows, recs = [], {}
        for d, n in (("2026-11-19", 5), ("2026-11-20", 5)):
            for i in range(n):
                rid = f"{d}-{i}"
                rows.append(run(rid, day=d, hh=10, mm=i))
                recs[rid] = {"quota_fallback": {"from": "codex", "to": "claude"}}
        self.put(*rows, runs=recs)
        now = ts("2026-11-21", 12)
        q = daily.build(self.p, "2026-11-20", UTC, now=now, quota_events=True)["quota_events"]
        self.assertFalse(q["summary"]["two_periods"]["ok"] is True)          # no split given: cannot tell
        self.assertIsNone(q["summary"]["two_periods"]["ok"])
        q = daily.build(self.p, "2026-11-20", UTC, now=now, quota_events=True, quota_split="2026-11-20")["quota_events"]
        self.assertTrue(q["summary"]["two_periods"]["ok"])
        q = daily.build(self.p, "2026-11-20", UTC, now=now, quota_events=True, quota_split="2026-11-21")["quota_events"]
        self.assertFalse(q["summary"]["two_periods"]["ok"])                  # second period empty

    # ---- output
    def test_markdown_section_marks_machine_and_human_sources(self):
        self.packet(self.PID)
        self.cont(self.PID)
        self.notes({"kind": "done", "id": self.PID, "ts": self.T0 + 2 * H + 60})
        md = daily.render(daily.build(self.p, DAY, UTC, now=self.T0 + 10 * H, quota_events=True,
                                      quota_workspaces=[self.work]))
        self.assertIn("## 额度事件（决定 3", md)
        self.assertIn("| 机器 | 人工 |", md)
        self.assertIn(self.PID, md)
        self.assertIn("relay packet,continue record", md)

    def test_cli_option_adds_the_section_and_other_flags_need_the_option(self):
        self.put(run("a", day=DAY, hh=10), runs={"a": {"quota_fallback": {"from": "codex", "to": "claude"}}})
        r = self.ccx("report", "--daily", DAY, "--tz", "UTC", "--quota-events", "--quota-workspace", str(self.work))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["quota_events"]["events"][0]["verdict"], "success")
        self.assertIn("额度事件（决定 3", (self.hub / "ccx" / "daily" / f"{DAY}.md").read_text(encoding="utf-8"))
        plain = json.loads(self.ccx("report", "--daily", DAY, "--tz", "UTC").stdout)
        self.assertNotIn("quota_events", plain)
        self.assertNotEqual(self.ccx("report", "--quota-events").returncode, 0)

    def test_bad_notes_and_unreadable_records_do_not_raise(self):
        daily_quota.notes_path(self.p).parent.mkdir(parents=True, exist_ok=True)
        daily_quota.notes_path(self.p).write_text('not json\n[1]\n{"kind": 3}\n{"kind":"wait","id":"a","ts":"junk"}\n', encoding="utf-8")
        self.put(run("a", day=DAY, hh=10), run("b", day=DAY, hh=10))
        (self.work / ".ccx" / "relay").mkdir(parents=True)
        (self.work / ".ccx" / "relay" / (self.PID + ".json")).write_text("{bad", encoding="utf-8")
        self.assertEqual(self.q(workspaces=[self.work])["events"], [])


if __name__ == "__main__":
    unittest.main()
