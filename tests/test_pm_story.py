"""PM review 2026-10-29, part A "honest story": the saving estimate no longer prices a sub-agent's start-up at the
lead's price and is never the headline; a write run without --check gets a one-line stderr nudge."""
import json
import os
import re
import time
import unittest
from pathlib import Path
from unittest import mock

from test_report import ReportEnv

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "ccx" / "ui_static"


class TestTaskSizedEstimate(ReportEnv):
    def _summary(self):
        from ccx import report
        from ccx.config import paths
        with mock.patch.dict(os.environ, self.env), mock.patch.object(report, "_trial", return_value=None):
            p = paths()
            s = report.summarize(p, report.collect(p, 7, include_lead=False))
            return p, s, report.render_html(s)

    def test_task_sized_keeps_fresh_input_and_output_only(self):
        from ccx.report import task_sized
        u = {"input_tokens": 1200, "cache_write_tokens": 20000, "cached_input_tokens": 90000, "output_tokens": 300}
        self.assertEqual(task_sized(u), {"input_tokens": 1200, "output_tokens": 300})
        self.assertEqual(task_sized(u, "claude"), {"input_tokens": 1200, "output_tokens": 300})  # start-up is cached
        self.assertEqual(task_sized({}), {"input_tokens": 0, "output_tokens": 0})

    def test_codex_start_up_read_fresh_is_not_task_sized(self):
        # warm-lanes round 1: a Codex run that starts a session reads 20.5-21.6k tokens fresh for a tiny piece
        from ccx.report import STARTUP_FRESH, task_sized
        cold = {"input_tokens": 21000, "cached_input_tokens": 78000, "output_tokens": 800}
        self.assertEqual(task_sized(cold, "codex"), {"input_tokens": 1000, "output_tokens": 800})
        self.assertEqual(task_sized({"input_tokens": 3000, "output_tokens": 1}, "codex")["input_tokens"], 0)
        self.assertEqual(task_sized(cold, "deepseek")["input_tokens"], 21000 - STARTUP_FRESH["codex"])  # unknown: like Codex

    def test_saving_prices_only_the_task_sized_tokens_and_keeps_the_old_one_for_comparison(self):
        from ccx import learn
        from ccx.report import task_sized
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "implement")
        self.j("verify", out["run_id"], "--ok", "1")
        p, s, html = self._summary()
        t = s["totals"]
        with mock.patch.dict(os.environ, self.env):
            [e] = [x for x in report_events(p) if x["role"] == "sub"]
            from ccx.config import load_config
            lead = load_config(p).get("lead", {}).get("claude", "")
            over = learn.price_usd(p, "claude", lead, {"input_tokens": 1500 + 4000, "output_tokens": 400}) or 0.0
            want = learn.price_usd(p, "claude", lead, task_sized(e["usage"], "codex")) - e["ae"] - over
            upper = learn.price_usd(p, "claude", lead, e["usage"]) - e["ae"] - over
        self.assertEqual(t["saving_kind"], "model")
        self.assertAlmostEqual(t["saving"], round(want, 4), places=4)
        self.assertAlmostEqual(t["saving_old_model"], round(upper, 4), places=4)
        self.assertNotIn("saving_upper", t)                            # not called a bound: nothing measured bounds it
        self.assertLessEqual(t["saving"], t["saving_old_model"])       # start-up no longer counted as lead spend
        self.assertIn("measured.md", t["saving_note"])
        self.assertIn("about even", t["saving_note"])

    def test_report_shows_spend_and_no_unmeasured_saving(self):
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "implement")
        self.j("verify", out["run_id"], "--ok", "1")
        _, s, html = self._summary()
        tiles = re.findall(r'<div class="k">([^<]+)</div>', html)
        self.assertEqual(tiles[-1], "Saving")                              # after every spend tile
        self.assertLess(tiles.index("Sub-agent spend"), tiles.index("Saving"))
        values = re.findall(r'<div class="v">([^<]*)</div>', html)
        self.assertEqual(len(values), len(tiles))
        self.assertEqual(values[tiles.index("Saving")], "not measured yet")  # P1-4: no model figure until ccx trial
        self.assertNotIn("Estimated saving", html)
        self.assertNotIn("est. saving", html)
        self.assertIsNotNone(s["totals"]["saving"])                        # the data keeps the model for scripts
        runs = html.split("<h2>Delegated runs</h2>", 1)[1].split("</table>", 1)[0]
        self.assertEqual(runs.split("</tr>", 1)[0].count("<th"), 7)          # day … tokens, AE$; no saving column
        for row in re.findall(r"<tr><td>.*?</tr>", runs):
            self.assertEqual(row.count("<td"), 7, row)
        self.assertIn("measured totals so far about even (docs/measured.md)", html)

    def test_stats_summary_puts_spend_first_and_labels_the_saving(self):
        out = self.j("run", "--from", "claude", "--to", "codex", "--b", "4", "implement")
        self.j("verify", out["run_id"], "--ok", "1")
        st = self.j("stats", "--summary")
        self.assertEqual(list(st)[:2], ["spend", "saving"])
        self.assertEqual(st["spend"]["runs"], 1)
        self.assertEqual(st["saving"]["kind"], "model")
        self.assertIn("model estimate", st["saving"]["note"])
        self.assertIn("docs/measured.md", st["saving"]["note"])
        self.assertIn("saving", st["totals"])                         # the old keys stay for scripts that read them
        self.assertNotIn("upper_bound_usd", st["saving"])              # the old model is not offered as a bound

    def test_realistic_codex_runs_are_not_estimated_far_above_their_spend(self):
        # A measured cold Codex run (warm-lanes round 1: ~21k fresh, ~78k cached, ~0.8k out) on a small task. Measured
        # totals so far were about even (docs/measured.md: self/ccx ratio 0.7-1.4 per success), so the model must not
        # claim a saving of several times what was spent; the old model did (start-up at the lead's price).
        from ccx import ledger
        from ccx.config import paths
        with mock.patch.dict(os.environ, self.env):
            p = paths()
            for i in range(5):
                rec = {"run_id": f"r-cold-{i}", "label": None, "to": "codex", "caller": "claude", "mode": "write",
                       "cwd": str(self.work), "tier": "T1", "session_id": None, "ts": time.time() - 60 * i,
                       "first_rung": "codex:gpt-6-luna:low",
                       "attempts": [{"agent": "codex", "rung": "codex:gpt-6-luna:low", "model": "gpt-6-luna",
                                     "effort": "low", "seconds": 60,
                                     "usage": {"input_tokens": 21000, "cached_input_tokens": 78000,
                                               "output_tokens": 800}, "ae_usd": None}],
                       "result": {"status": "done", "summary": "", "files_changed": [], "verification": ""},
                       "ok": True, "state": "finished", "kind": None}
                ledger.append(p, rec)
        _, s, _ = self._summary()
        t = s["totals"]
        self.assertEqual(t["saving_kind"], "model")
        self.assertGreater(t["sub_ae"], 0)
        self.assertLessEqual(t["saving"], 1.0 * t["sub_ae"], t)         # at most what was spent, not several times it
        self.assertGreater(t["saving_old_model"], t["saving"])


def report_events(p):
    from ccx import report
    return report.collect(p, 7, include_lead=False)["events"]


class TestUiWording(unittest.TestCase):
    def setUp(self):
        self.strings = json.loads((STATIC / "strings.json").read_text(encoding="utf-8"))
        self.js = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_only_a_measured_saving_is_shown_and_the_rest_links_the_measurements(self):
        for lang in ("en", "zh"):
            s = self.strings[lang]
            self.assertIn("{link}", s["month_unmeasured"], lang)
            self.assertIn("ccx trial", s["month_unmeasured"], lang)
            for k in ("month_saving_m", "month_extra_m"):
                self.assertIn(k, s, (lang, k))
            for k in ("month_saving", "month_extra", "month_model"):      # P1-4: the model estimate is not shown
                self.assertNotIn(k, s, (lang, k))
        self.assertIn("about even", self.strings["en"]["month_unmeasured"])
        self.assertIn("基本持平", self.strings["zh"]["month_unmeasured"])
        self.assertNotIn("Relative estimate", json.dumps(self.strings))
        saving = self.js.split("function monthSavingHTML()", 1)[1].split("\n  }", 1)[0]
        self.assertIn('m.kind !== "measured"', saving)
        self.assertLess(saving.index("month_unmeasured"), saving.index("usd(Math.abs(m.saving))"))
        for lang in ("en", "zh"):
            self.assertTrue(self.strings[lang]["measured_url"].endswith("relayline/blob/main/docs/measured.md"))
        self.assertIn('t("measured_url")', self.js)

    def test_spend_comes_first_and_the_estimate_is_not_bold(self):
        body = self.js.split("function weekHTML()", 1)[1].split("\n  }", 1)[0]
        self.assertLess(body.index("monthSpentHTML()"), body.index("week_spent"))
        self.assertLess(body.index("week_spent"), body.index("monthSavingHTML()"))
        saving = self.js.split("function monthSavingHTML()", 1)[1].split("\n  }", 1)[0]
        self.assertNotIn("<b>", saving)


class TestHelpWording(unittest.TestCase):
    def test_help_does_not_promise_a_saving(self):
        from ccx import cli
        text = " ".join(cli.build_parser().format_help().split())
        for promise in ("this month's saving", "spend and savings", "quota and savings"):
            self.assertNotIn(promise, text)


class TestDocsAgree(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_skill_count_is_the_same_everywhere(self):
        n = len([d for d in (ROOT / "skills").iterdir() if (d / "SKILL.md").exists()])
        word = {4: "four", 5: "five", 6: "six"}[n]
        market = json.loads(self.read(".claude-plugin/marketplace.json"))["plugins"][0]["description"]
        codex = json.loads(self.read(".codex-plugin/plugin.json"))["description"]
        for text in (market, codex):
            self.assertIn(f"The {word} relayline skills", text)

    def test_readme_leads_with_the_job_and_the_honest_comparison(self):
        for name, hold in (("README.md", ("Hold-out set (hc1", "default usage", "$0.063", "2026-10-29-hc1-holdout.md")),
                           ("README.zh.md", ("留出集（hc1", "默认用法", "$0.063", "2026-10-29-hc1-holdout.zh.md"))):
            s = self.read(name)
            first = s.split("## ", 2)[1]                           # the first section: the eight layers, two results first
            for must in hold:                                      # the hold-out row is filled, with its qualifier
                self.assertIn(must, first, (name, must))
            self.assertNotIn("pending", first.lower(), name)
            self.assertNotIn("待测", first, name)
            for must in ("12/30", "25/30", "3.1"):                 # P2-10: the pg1 result beside the hold-out one
                self.assertIn(must, first, (name, must))
            for must in ("builtin2", "$0.114", "$0.135", "$0.116–0.135"):   # the dev set: in the comparison below
                self.assertIn(must, s, (name, must))
            self.assertNotIn("Four pillars", s)
            self.assertNotIn("四根柱子", s)
            quick = s.split("```bash", 2)[2]
            self.assertIn("--check", quick.split("```", 1)[0], name)

    def test_best_case_numbers_live_in_measured(self):
        for name in ("docs/measured.md", "docs/measured.zh.md"):
            s = self.read(name)
            self.assertIn("36/36", s)
            self.assertIn("builtin2", s)
            self.assertNotIn("README's four numbers", s)

    def test_faq_has_the_builtin_row_and_no_discuss_contradiction(self):
        en, zh = self.read("docs/faq.md"), self.read("docs/faq.zh.md")
        self.assertIn("| Claude Code's built-in sub-agent", en)
        self.assertIn("| Claude Code 自带的子智能体", zh)
        self.assertNotIn("One way, for now", en)
        self.assertNotIn("现在能做的是单向的", zh)
        self.assertNotIn("multi-provider consensus", en)


class TestNoCheckNudge(ReportEnv):
    def test_write_run_without_check_gets_one_stderr_line(self):
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--mode", "write", "add a helper")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sum("no --check" in ln for ln in r.stderr.splitlines()), 1, r.stderr)
        self.assertEqual(json.loads(r.stdout)["status"], "done")      # stdout is still the one JSON result
        self.assertNotIn("no --check", r.stdout)

    def test_bg_write_run_without_check_gets_one_line_and_the_same_json(self):
        r = self.ccx("run", "--bg", "--from", "claude", "--to", "codex", "--tier", "T1", "--mode", "write", "add a helper")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sum("no --check" in ln for ln in r.stderr.splitlines()), 1, r.stderr)
        out = json.loads(r.stdout)                                     # plain --bg's record, unchanged
        self.assertEqual(set(out), {"run_id", "state", "peek", "log", "next"})
        self.assertNotIn("no --check", r.stdout)
        self.ccx("show", out["run_id"], "--wait", "90")                 # let the child finish before the temp dir goes
        r = self.ccx("run", "--bg", "--wait", "90", "--from", "claude", "--to", "codex", "--tier", "T1",
                     "--mode", "write", "add another helper")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sum("no --check" in ln for ln in r.stderr.splitlines()), 1, r.stderr)
        out = json.loads(r.stdout)                                     # one JSON document: the final result
        self.assertEqual(out["status"], "done", out)
        self.assertNotIn("no --check", r.stdout)

    def test_no_nudge_with_a_check_or_for_a_read_run(self):
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--mode", "write",
                     "--check", "python -c pass", "add a helper")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("no --check", r.stderr)
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--mode", "read", "explain x")
        self.assertNotIn("no --check", r.stderr)


if __name__ == "__main__":
    unittest.main()
