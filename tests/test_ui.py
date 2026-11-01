"""G1: `ccx ui`, the read-only live page, and the ui.lang setting (fake ledger, run records, queues; fake CLIs only)."""
import http.client
import json
import re
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import context, lang, quota, ui  # noqa: E402
from ccx import queue as wq  # noqa: E402
from ccx.config import Paths  # noqa: E402
from test_ccx import Env  # noqa: E402

STATIC = Path(ui.__file__).resolve().parent / "ui_static"
EVIL = '</script><script>alert(1)</script><img src=x onerror=alert(2)>'


def put_run(hub: Path, run_id: str, cwd: Path, **kw) -> dict:
    """A run record as ccx/delegate.py writes it (only the fields the page reads)."""
    rec = {"run_id": run_id, "label": None, "to": "codex", "caller": "claude", "mode": "write", "cwd": str(cwd), "tier": "T1",
           "session_id": None, "attempts": [{"agent": kw.get("to", "codex"), "rung": "codex:gpt-6-luna:low",
                                             "model": "gpt-6-luna", "effort": "low", "seconds": 12.0,
                                             "usage": {"input_tokens": 1000, "output_tokens": 200}, "ae_usd": 0.002}],
           "result": {"status": "done", "summary": "did it", "files_changed": ["a.py"], "verification": "ran tests"},
           "ok": True, "state": "finished", "kind": None, "ts": time.time() - 60, "lead_session": None,
           "first_rung": "codex:gpt-6-luna:low"}
    rec.update(kw)
    d = hub / "ccx" / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    (d / "prompt.md").write_text(f"[ccx sub-task] ...\nccx run id: {run_id}; lead: claude\n## Task\n{kw.get('brief', 'Add a parser')}\n\n## Finish\n...",
                                 encoding="utf-8")
    return rec


def pieces(data: dict) -> list[dict]:
    out = []
    for pr in data["projects"]:
        for t in pr["tasks"]:
            out += list(ui._walk(t["pieces"]))
    return out


class TestData(Env):
    def setUp(self):
        super().setUp()
        self.p = Paths(self.hub)
        (self.work / ".git").mkdir()

    def test_whole_page_from_fake_records(self):
        put_run(self.hub, "r-review", self.work, lead_session="lead1", brief="Add restock")
        put_run(self.hub, "r-nw", self.work, lead_session="lead1", mode="read", kind="needs_write", ok=True,
                result={"status": "blocked", "summary": "NEEDS_WRITE: x.py line 3"})
        put_run(self.hub, "r-rf", self.work, lead_session="lead1", kind="review_failed",
                review={"verdict": "issues", "issues": ["[must] size 0 returns []"], "by": "claude:haiku:low"})
        put_run(self.hub, "r-ok", self.work, lead_session="lead1", verdict={"ok": True})
        put_run(self.hub, "r-run", self.work, lead_session="lead1", state="running", result=None, ok=False,
                ts=time.time() - 30, attempts=[])
        put_run(self.hub, "r-new", self.work, to="newbot", lead_session="lead1",
                attempts=[{"agent": "newbot", "rung": "newbot:m1:low", "model": "m1", "seconds": 3, "ae_usd": 0.001}])
        put_run(self.hub, "r-probe", self.work, label="quota-probe")             # internal: never shown
        put_run(self.hub, "r-eph", self.work, ephemeral=True)
        wq.add(self.work, "Big job", "do it")
        wq.add(self.work, "part A", "a", parent="q1")
        wq.add(self.work, "part B", "b", parent="q1")
        wq.update(self.work, "q1", status="split")
        put_run(self.hub, "r-q2", self.work, label="q:q2")
        wq.update(self.work, "q2", status="done", run="r-q2", agent="codex", cost_usd=0.002)
        wq.update(self.work, "q3", status="needs_write", summary="needs b.py")
        data = ui.collect(self.p)
        self.assertEqual(len(data["projects"]), 1)
        pr = data["projects"][0]
        self.assertEqual(pr["name"], self.work.name)
        kinds = sorted(t["kind"] for t in pr["tasks"])
        self.assertEqual(kinds, ["lead", "queue"])
        lead = next(t for t in pr["tasks"] if t["kind"] == "lead")
        by = {p["run_id"]: p for p in lead["pieces"]}
        self.assertEqual(set(by), {"r-review", "r-nw", "r-rf", "r-ok", "r-run", "r-new"})   # no probe, no ephemeral
        self.assertEqual((by["r-review"]["status"], by["r-review"]["act"]["kind"]), ("review", "review"))
        self.assertEqual(by["r-review"]["act"]["buttons"][0]["cmd"], "ccx verify r-review --ok 1")
        self.assertEqual(by["r-review"]["title"], "Add restock")
        self.assertEqual((by["r-nw"]["status"], by["r-nw"]["act"]["what"]), ("decide", "a_needs_write"))
        self.assertEqual(by["r-rf"]["act"]["what"], "a_review_failed")
        self.assertEqual((by["r-ok"]["status"], by["r-ok"]["act"]), ("done", None))
        self.assertEqual((by["r-run"]["status"], by["r-run"]["live"]), ("run", True))
        self.assertIn("newbot", data["agents"])                                # a new agent: its own column
        q = next(t for t in pr["tasks"] if t["kind"] == "queue")
        top = q["pieces"][0]
        self.assertEqual([c["title"] for c in top["children"]], ["part A", "part B"])
        a, b = top["children"]
        self.assertEqual((a["status"], a["act"]["kind"]), ("review", "review"))
        self.assertIn("ccx q done q2 --ok 1", a["act"]["buttons"][0]["cmd"])
        self.assertEqual((b["status"], b["act"]["what"]), ("decide", "a_q_needs_write"))
        wq.add(self.work, "after B", "c", deps=["q3"])
        wq.update(self.work, "q4", status="dep_blocked", blocked_by=["q3"])
        pr = ui.collect(self.p)["projects"][0]
        after = next(t for t in pr["tasks"] if t["kind"] == "queue")["pieces"][-1]
        self.assertEqual((after["status"], after["act"]["what"]), ("decide", "a_q_dep_blocked"))   # not "queued"
        self.assertNotIn("r-q2", by)                                          # queue runs live on the queue page
        json.dumps(data)                                                      # the page gets plain JSON

    def test_verdict_and_fix_round_fold_into_one_piece(self):
        put_run(self.hub, "r1", self.work, kind="review_issues", ts=time.time() - 300)
        put_run(self.hub, "r2", self.work, review_of="r1", resumed_from="r1", ts=time.time() - 200)
        data = ui.collect(self.p)
        ps = pieces(data)
        self.assertEqual(len(ps), 1)
        self.assertEqual((ps[0]["run_id"], ps[0]["rounds"]), ("r2", 2))
        (self.hub / "ccx" / "ledger.jsonl").write_text(json.dumps({"type": "verify", "run_id": "r2", "ok": True}) + "\n",
                                                       encoding="utf-8")
        self.assertEqual(pieces(ui.collect(self.p))[0]["status"], "done")

    def test_stale_run_needs_a_look(self):
        rec = put_run(self.hub, "r-stuck", self.work, state="running", result=None, ok=False, attempts=[],
                      ts=time.time() - 3600)
        old = time.time() - 30 * 60
        import os
        for f in (self.hub / "ccx" / "runs" / "r-stuck" / "run.json", self.hub / "ccx" / "runs" / "r-stuck"):
            os.utime(f, (old, old))
        p = pieces(ui.collect(self.p))[0]
        self.assertEqual(p["act"]["what"], "a_stale")
        self.assertEqual(rec["run_id"], p["run_id"])

    def test_live_tokens_from_the_sub_agents_session_file(self):
        sid = "019a0000-0000-7000-8000-000000000001"
        put_run(self.hub, "r-live", self.work, state="running", result=None, ok=False, attempts=[], session_id=sid)
        d = self.home_codex / "sessions" / "2026" / "10" / "24"
        d.mkdir(parents=True)
        f = d / f"rollout-2026-10-24T10-00-00-{sid}.jsonl"
        line = lambda n: json.dumps({"timestamp": "2026-10-24T10:00:00Z", "type": "event_msg", "payload": {  # noqa: E731
            "type": "token_count", "info": {"total_token_usage": {"input_tokens": n, "output_tokens": 10}}}}) + "\n"
        f.write_text(line(1000), encoding="utf-8")
        rd = ui.Reader(self.p)
        self.assertEqual(pieces(ui.collect(self.p, rd=rd))[0]["tokens"], 1010)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line(5000))
        self.assertEqual(pieces(ui.collect(self.p, rd=rd))[0]["tokens"], 5010)      # read on, not from the top

    def test_provider_reads_the_session_file_of_the_cli_it_runs_on(self):
        sid = "5f0c0000-0000-4000-8000-00000000d5ee"
        put_run(self.hub, "r-ds", self.work, to="deepseek", provider="deepseek", state="running", result=None,
                ok=False, attempts=[], session_id=sid)
        f = self.home_claude / "projects" / "work" / f"{sid}.jsonl"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "model": "deepseek-flash", "usage": {
            "input_tokens": 700, "output_tokens": 50}}}) + "\n", encoding="utf-8")
        self.assertEqual(pieces(ui.collect(self.p))[0]["tokens"], 750)

    def test_never_calls_a_model_or_the_quota_probe(self):
        put_run(self.hub, "r1", self.work)
        boom = mock.Mock(side_effect=AssertionError("must not run"))
        with mock.patch.object(quota, "probe", boom), mock.patch("ccx.delegate.run", boom), \
                mock.patch("ccx.runners.execute", boom), mock.patch("subprocess.Popen", boom), \
                mock.patch("subprocess.run", boom):
            ui.collect(self.p)
            srv = ui.UI(self.p, idle_s=30)
            threading.Thread(target=srv.serve, daemon=True).start()
            try:
                code, _, body = get(srv, "/api/data", token=srv.token)
                self.assertEqual(code, 200)
                self.assertIn("r1", body)
            finally:
                srv.stop()
        boom.assert_not_called()
        self.assertFalse((self.hub / "ccx" / "quota.jsonl").exists())

    def test_export_keeps_hostile_text_inside_the_data(self):
        put_run(self.hub, "r-evil", self.work, label=EVIL, result={"status": "done", "summary": EVIL})
        out = ui.export(self.p, self.work / "snap.html")
        page = out.read_text(encoding="utf-8")
        self.assertEqual(page.count("<script"), 3)                 # strings, data, the page's own script
        self.assertEqual(page.count("</script>"), 3)
        self.assertNotIn("<img src=x", page)
        snap = re.search(r'id="ccx-snapshot">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(json.loads(snap)["projects"][0]["tasks"][0]["pieces"][0]["title"], EVIL)

    def test_project_filter_and_worktree_folds_into_repo(self):
        other = self.work.parent / "other"
        (other / ".git").mkdir(parents=True)
        wt = self.work.parent / ".ccx-worktrees" / self.work.name / "r2"
        wt.mkdir(parents=True)
        put_run(self.hub, "r1", self.work)
        put_run(self.hub, "r2", wt)
        put_run(self.hub, "r3", other)
        data = ui.collect(self.p)
        self.assertEqual(sorted(pr["name"] for pr in data["projects"]), sorted([self.work.name, "other"]))
        only = ui.collect(self.p, project=self.work)
        self.assertEqual([pr["name"] for pr in only["projects"]], [self.work.name])
        self.assertEqual(len(pieces(only)), 2)


def get(srv, path, token=None, host=None, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{srv.port}"}
    if token is not None:
        headers["X-CCX-Token"] = token
    c.request(method, path, headers=headers)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read().decode("utf-8")


class TestServer(Env):
    def setUp(self):
        super().setUp()
        self.p = Paths(self.hub)
        put_run(self.hub, "r1", self.work)
        self.srv = ui.UI(self.p, idle_s=30)
        self.t = threading.Thread(target=self.srv.serve, daemon=True)
        self.t.start()

    def tearDown(self):
        self.srv.stop()
        self.t.join(5)
        super().tearDown()

    def test_token_and_host_are_checked(self):
        self.assertEqual(get(self.srv, "/api/data")[0], 403)                        # no token
        self.assertEqual(get(self.srv, "/api/data", token="wrong")[0], 403)
        self.assertEqual(get(self.srv, "/api/data", token=self.srv.token, host="evil.example:80")[0], 403)
        self.assertEqual(get(self.srv, "/", host=f"attacker.test:{self.srv.port}")[0], 403)   # DNS rebinding
        self.assertEqual(get(self.srv, "/api/alive", token="wrong", method="POST")[0], 403)
        code, headers, body = get(self.srv, "/api/data", token=self.srv.token)
        self.assertEqual(code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(json.loads(body)["v"], 1)
        code, headers, _ = get(self.srv, "/api/data", token=self.srv.token, host=f"localhost:{self.srv.port}")
        self.assertEqual(code, 200)

    def test_page_is_static_and_locked_down(self):
        code, headers, body = get(self.srv, "/")
        self.assertEqual(code, 200)
        self.assertNotIn(self.srv.token, body)                         # the page itself holds no secret
        csp = headers["Content-Security-Policy"]
        self.assertIn("script-src 'self';", csp)                       # no inline script, ever
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        for name in ("app.js", "app.css", "strings.json"):
            self.assertEqual(get(self.srv, "/" + name)[0], 200)
        self.assertEqual(get(self.srv, "/../ccx/ui.py")[0], 404)
        self.assertEqual(get(self.srv, "/api/run/..%2f..%2fx", token=self.srv.token)[0], 404)
        self.assertTrue(self.srv.url.startswith(f"http://127.0.0.1:{self.srv.port}/#k="))
        self.assertEqual(self.srv.httpd.server_address[0], "127.0.0.1")

    def test_suggested_notes_yes_and_no_same_origin_only(self):
        from ccx import memory, memsuggest
        memsuggest.add(self.p, [{"kind": "preference", "text": "keep PR text in Chinese", "by": "user", "source": "s1"},
                                {"kind": "pitfall", "text": EVIL, "by": "claude", "source": "s1"}])
        code, _, body = get(self.srv, "/api/data", token=self.srv.token)
        sugs = json.loads(body)["suggestions"]
        self.assertEqual([s["text"] for s in sugs], ["keep PR text in Chinese", EVIL])   # data, escaped by the page
        a, b = sugs[0]["id"], sugs[1]["id"]
        origin = f"http://127.0.0.1:{self.srv.port}"

        def post(body, token=self.srv.token, origin=origin, ctype="application/json", site=None, host=None):
            c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
            h = {"Host": host or f"127.0.0.1:{self.srv.port}", "X-CCX-Token": token, "Content-Type": ctype}
            if origin:
                h["Origin"] = origin
            if site:
                h["Sec-Fetch-Site"] = site
            c.request("POST", "/api/suggestion", body=json.dumps(body), headers=h)
            r = c.getresponse()
            return r.status, json.loads(r.read() or b"{}")

        self.assertEqual(post({"id": a, "accept": True}, origin=None)[0], 403)              # no Origin
        self.assertEqual(post({"id": a, "accept": True}, origin="http://evil.example")[0], 403)
        self.assertEqual(post({"id": a, "accept": True}, origin="http://127.0.0.1:1")[0], 403)   # another port
        self.assertEqual(post({"id": a, "accept": True}, site="cross-site")[0], 403)
        self.assertEqual(post({"id": a, "accept": True}, token="wrong")[0], 403)
        self.assertEqual(post({"id": a, "accept": True}, host="evil.example:80")[0], 403)
        self.assertEqual(post({"id": a, "accept": True}, ctype="text/plain")[0], 415)       # no simple form post
        self.assertEqual(post({"id": a, "accept": "yes"})[0], 400)
        self.assertEqual(memory.entries(self.p), [])                                        # nothing written yet
        code, out = post({"id": a, "accept": True}, site="same-origin")
        self.assertEqual((code, out["status"]), (200, "accepted"))
        self.assertEqual(memory.entries(self.p)[0]["text"], "keep PR text in Chinese")
        self.assertEqual(post({"id": a, "accept": False})[0], 409)                          # already decided
        self.assertEqual(post({"id": b, "accept": False}, origin=f"http://localhost:{self.srv.port}")[1]["status"],
                         "rejected")
        self.assertEqual(len(memory.entries(self.p)), 1)
        self.assertEqual(json.loads(get(self.srv, "/api/data", token=self.srv.token)[2])["suggestions"], [])

    def test_run_detail(self):
        code, _, body = get(self.srv, "/api/run/r1", token=self.srv.token)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["run_id"], "r1")


class TestHeartbeat(Env):
    def test_exits_without_heartbeat_and_stays_with_it(self):
        p = Paths(self.hub)
        srv = ui.UI(p, idle_s=1.0, first_beat_s=1.0)
        t = threading.Thread(target=srv.serve, daemon=True)
        t.start()
        stop = time.time() + 3.5
        while time.time() < stop:                                     # the page says "still open"
            self.assertEqual(get(srv, "/api/alive", token=srv.token, method="POST")[0], 200)
            time.sleep(0.3)
        self.assertTrue(t.is_alive())
        t.join(6)                                                     # then the page is gone
        self.assertFalse(t.is_alive())
        self.assertEqual(srv.why_stopped, "page closed")

    def test_never_opened(self):
        srv = ui.UI(Paths(self.hub), idle_s=0.5, first_beat_s=0.5)
        t = threading.Thread(target=srv.serve, daemon=True)
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(srv.why_stopped, "page never opened")


class TestStrings(unittest.TestCase):
    def setUp(self):
        self.s = json.loads((STATIC / "strings.json").read_text(encoding="utf-8"))

    def test_both_languages_have_every_word(self):
        zh, en = self.s["zh"], self.s["en"]
        self.assertEqual(set(zh) - set(en), set())
        self.assertEqual(set(en) - set(zh), set())
        for k in en:
            a, b = zh[k], en[k]
            self.assertTrue(a and b, k)
            if isinstance(a, list):
                self.assertEqual(len(a), len(b), k)
                continue
            self.assertEqual(set(re.findall(r"\{(\w+)\}", a)), set(re.findall(r"\{(\w+)\}", b)), k)

    def test_every_key_the_code_uses_exists(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        used = {k for k in re.findall(r'\bt\("([a-z_0-9]+)"', js) if not k.endswith("_")}    # t("r_" + x): below
        py = (Path(ui.__file__)).read_text(encoding="utf-8")
        used |= {k for k in re.findall(r'"((?:a|w|b|h)_[a-z_0-9]+)"', py) if not k.endswith("_")}
        used |= {f"a_q_{s}" for s in ("needs_write", "blocked", "failed")} | {f"w_q_{s}" for s in ("needs_write", "blocked", "failed")}
        used |= {f"h_review_{v}" for v in ("pass", "issues", "unclear")} | {f"rv_{v}" for v in ("pass", "issues", "unclear")}
        used |= {f"h_{k}" for k in ("needs_write", "check_failed", "review_failed", "quota", "timeout", "over_budget")}
        used |= {f"r_{r}_note" for r in ("unfinished", "wrong", "overreach", "other")}
        for mod in ("queue.py", "context.py", "commands/memory.py"):
            used |= set(re.findall(r'say\("(hint_\w+)"', (Path(ui.__file__).parent / mod).read_text(encoding="utf-8")))
        self.assertIn("hint_queue", used)
        for k in sorted(used):
            for lg in ("zh", "en"):
                self.assertTrue(k in self.s[lg], f"{lg}: {k} missing")

    def test_one_word_for_the_lead_in_chinese_and_new_words_in_both(self):
        """zh: the lead is 主导 everywhere on the page (not 组长 / 主智能体); every new word exists in both languages."""
        for k, v in self.s["zh"].items():
            text = " ".join(v) if isinstance(v, list) else v
            self.assertNotIn("组长", text, k)
            self.assertNotIn("主智能体", text, k)
        for k in ("k_decide", "k_review", "k_answer", "ago_d", "ago_w", "b_undo", "b_accept_anyway", "b_q_merge",
                  "paste_lead", "act_undo_note", "act_merge_note", "next_wait", "queue_box", "ov_lead"):
            for lg in ("zh", "en"):
                self.assertIn(k, self.s[lg], f"{lg}: {k}")
        self.assertIn("(dsh)", self.s["en"]["b_cont_dsh"])
        self.assertIn("(dsh)", self.s["zh"]["b_cont_dsh"])
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('dsh: "DeepSeek (dsh)"', js)
        # the queue's top box: the whole `const top = ...;` statement, both branches; no invented quote of the person
        top = js.split('const top = tk.kind === "queue"', 1)[1].split(";", 1)[0]
        q_branch = top.split("\n", 1)[0]                     # `? (queue: budget ? box_b : box)`, then `: you_asked`
        self.assertIn('t("queue_box_b"', q_branch)
        self.assertIn('t("queue_box"', q_branch)
        self.assertNotIn("you_asked", q_branch)
        for k in ("undo_restore", "undo_aside", "undo_chain", "act_started_bg"):
            for lg in ("zh", "en"):
                self.assertIn(k, self.s[lg], f"{lg}: {k}")

    def test_no_inline_handlers_in_the_page(self):
        for name in ("index.html", "app.js"):
            text = (STATIC / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\son[a-z]+\s*=\s*[\"']", text), name)    # the CSP would block them anyway
            self.assertNotIn("http://", text.replace("http://127.0.0.1", ""))
            self.assertNotIn("https://", text)                                     # no CDN


class TestLang(Env):
    def test_setting_switches_the_hints(self):
        p = Paths(self.hub)
        wq.add(self.work, "x", "x")
        self.assertIn("open item(s)", wq.unfinished_line(self.work))
        r = self.ccx("config", "set", "ui.lang", "zh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(lang.current(p), "zh")
        self.assertIn("块没做完", wq.unfinished_line(self.work))
        text = context.advice({"agent": "claude", "turns": 30, "last_turn_tokens": 401_000, "usd_per_turn": 0.12})
        self.assertIn("约 401k token", text)
        self.assertEqual(ui.collect(p)["lang"], "zh")                          # the page's default too
        bad = self.ccx("config", "set", "ui.lang", "fr")
        self.assertNotEqual(bad.returncode, 0)

    def test_page_shows_the_first_three_suggestions(self):
        from ccx import memsuggest
        p = Paths(self.hub)
        memsuggest.add(p, [{"kind": "pitfall", "text": f"pitfall {i} long enough", "by": "claude", "source": "s"}
                           for i in range(4)] + [{"kind": "preference", "text": "always X", "by": "user", "source": "s"}])
        d = ui.collect(p, quota_wait=False)
        self.assertEqual((len(d["suggestions"]), d["suggestions_total"]), (3, 5))
        self.assertEqual(d["suggestions"][0]["text"], "always X")

    def test_start_count_leaves_out_evaluation_runs(self):
        p = Paths(self.hub)
        put_run(self.hub, "r-real", self.work)                                      # done, nobody judged it
        self.assertEqual(ui.waiting(p), 1)
        put_run(self.hub, "r-eval", self.work, label="eval-7c:r1:memory:1:mem-log:hubmem")
        put_run(self.hub, "r-noab", self.work, route={"no_ab": True})
        put_run(self.hub, "r-probe", self.work, label="quota-probe")
        self.assertEqual(ui.waiting(p), 1)

    def test_tests_and_evaluations_are_marked_and_left_out(self):
        p = Paths(self.hub)
        (self.work / ".git").mkdir()
        scratch = self.work.parent / "scratch"
        (scratch / "r" / ".git").mkdir(parents=True)
        (self.work / ".ccx" / "f1-trial" / "repo2" / ".git").mkdir(parents=True)
        put_run(self.hub, "r-real", self.work, label="feature")
        put_run(self.hub, "r-two", self.work, label="two-way-c2x")
        put_run(self.hub, "r-tmp", scratch / "r", label="fix-review-real")
        put_run(self.hub, "r-trial", self.work / ".ccx" / "f1-trial" / "repo2")
        put_run(self.hub, "r-ab", self.work, label="eval-7c:func:budget:codex")
        with mock.patch.object(ui, "scratch_roots", return_value=[scratch.resolve()]),                 mock.patch.object(ui, "leads", return_value=[
                    {"agent": "claude", "model": "m", "session": "s1", "cwd": str(scratch / "route-1-x"), "last": 1,
                     "helpers": []},
                    {"agent": "codex", "model": "m", "session": "s2", "cwd": str(self.work), "last": 1, "helpers": []}]):
            self.assertEqual(ui.waiting(p), 1)                  # the session-start count: real work only
            d = ui.collect(p, quota_wait=False)
        by = {pc["run_id"]: pc["test"] for pc in pieces(d)}
        self.assertEqual(by, {"r-real": False, "r-two": True, "r-tmp": True, "r-trial": True, "r-ab": True})
        tests = {pr["name"]: pr["test"] for pr in d["projects"]}
        self.assertFalse(tests[self.work.name])                 # a real project keeps its real pieces ...
        self.assertTrue(tests["r"] and tests["repo2"])          # ... the scratch ones are set apart
        self.assertEqual([l["test"] for l in d["leads"]], [True, False])
        with mock.patch.object(ui, "scratch_roots", return_value=[scratch.resolve()]),                 mock.patch("ccx.discuss.recent", return_value=[{"id": "d1", "cwd": str(scratch / "q")},
                                                               {"id": "d2", "cwd": str(self.work)}]):
            talks = ui.collect(p, quota_wait=False)["discussions"]
        self.assertEqual([x["test"] for x in talks], [True, False])
        js = (STATIC / "app.js").read_text(encoding="utf-8")    # the page leaves them out unless asked
        self.assertIn('data-do="tests"', js)
        self.assertIn("function view(d)", js)
        self.assertIn('localStorage.getItem("ccx-tests")', js)

    def test_hub_in_the_temp_folder_sets_nothing_apart(self):
        import tempfile
        with mock.patch.object(tempfile, "gettempdir", return_value=str(self.hub.parent)):
            self.assertEqual(ui.scratch_roots(Paths(self.hub)), [])
        with mock.patch.object(tempfile, "gettempdir", return_value=str(self.work)):
            self.assertEqual(ui.scratch_roots(Paths(self.hub)), [self.work.resolve()])

    def test_session_start_points_at_ccx_ui(self):
        r = self.ccx("run", "--to", "codex", "--tier", "T1", "--mode", "write", "--review", "off", "change x")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        out = self.ccx("mem", "delta", "--as", "claude", "--peek").stdout
        self.assertIn("`ccx ui`", out)
        self.ccx("config", "set", "ui.lang", "zh")
        self.assertIn("件派出去的活等你处理", self.ccx("mem", "delta", "--as", "claude", "--peek").stdout)


class TestRealRuns(Env):
    """Run records written by real ccx runs (fake CLIs) read back as the page expects."""

    def test_fake_cli_runs(self):
        ok = json.loads(self.ccx("run", "--to", "codex", "--tier", "T1", "--mode", "write", "--review", "off",
                                 "--label", "first", "change x").stdout)
        nw = json.loads(self.ccx("run", "--to", "claude", "--tier", "T1", "--mode", "read", "--label", "second",
                                 "look at x", env={"FAKE_STATUS": "blocked",
                                                   "FAKE_SUMMARY": "NEEDS_WRITE: x.py line 3"}).stdout)
        data = ui.collect(Paths(self.hub))
        by = {p["run_id"]: p for p in pieces(data)}
        self.assertEqual(by[ok["run_id"]]["act"]["kind"], "review")
        self.assertEqual(by[ok["run_id"]]["title"], "first")
        self.assertEqual(by[nw["run_id"]]["act"]["what"], "a_needs_write")
        self.assertIn("--mode write", by[nw["run_id"]]["act"]["buttons"][1]["cmd"])
        snap = self.ccx("ui", "--export", str(self.work / "s.html"))
        self.assertEqual(snap.returncode, 0, snap.stderr)
        self.assertTrue((self.work / "s.html").exists())


if __name__ == "__main__":
    unittest.main()
