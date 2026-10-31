"""U6 `ccx demo` and U7 the switch-lead panel of `ccx ui`. The demo hub doubles as a headless smoke fixture: built
from ccx's own fake data in a temporary folder, served by the real server, every data endpoint read back. No agent
CLI is ever started (the one command run is `ccx handoff`, which only writes into the demo project)."""
import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import demo, ui  # noqa: E402
from ccx.config import Paths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
HAS_GIT = shutil.which("git") is not None


def get(srv, path):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    c.request("GET", path, headers={"Host": f"127.0.0.1:{srv.port}", "X-CCX-Token": srv.token})
    r = c.getresponse()
    body = r.read().decode("utf-8")
    return r.status, dict(r.getheaders()), body


def post(srv, path, body):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=120)
    c.request("POST", path, body=json.dumps(body).encode("utf-8"),
              headers={"Host": f"127.0.0.1:{srv.port}", "X-CCX-Token": srv.token, "Content-Type": "application/json",
                       "Origin": f"http://127.0.0.1:{srv.port}"})
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"{}")


HOMES = ("CCX_HUB", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "DSH_HOME")


def listing(env):
    return {k: sorted(str(f) for f in Path(env[k]).rglob("*")) for k in HOMES}


@pytest.fixture
def built(monkeypatch):
    """The demo in a new folder of the temporary folder (as `ccx demo` makes it: a short path, as Claude Code's own
    session folders need), built while this process still points at the test's own hub and tool homes (build()
    scopes its environment itself), then pointed at the demo. The own homes are kept to check nothing was written."""
    monkeypatch.setattr(ui, "_dsh_ready", lambda: False)        # whether this machine has dsh is no input
    own = {k: os.environ[k] for k in HOMES}
    before, env_before = listing(own), dict(os.environ)
    base = demo.new_base()
    try:
        p = demo.build(base)
        assert dict(os.environ) == env_before and listing(own) == before
        with mock.patch.dict(os.environ, demo.env(base)):
            yield base, p, own
    finally:
        assert demo.remove(base)
        assert not base.exists()


@pytest.fixture
def server(built):
    base, p, _ = built
    srv = ui.UI(p, idle_s=60)
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    yield srv, base, p
    srv.stop()
    t.join(5)


def walk(pieces):
    for pc in pieces:
        yield pc
        yield from walk(pc.get("children") or [])


def project(data, name):
    return next(pr for pr in data["projects"] if pr["name"] == name)


def test_demo_hub_is_marked_and_stays_in_its_folder(built):
    base, p, own = built
    assert demo.is_demo(p) and p.hub == base / "hub"
    assert list(Path(own["CCX_HUB"]).iterdir()) == []            # the hub the process had before: untouched
    assert sorted(x.name for x in base.iterdir()) == sorted(demo.DEMO_DIRS)
    assert "DEMO" in (p.hub / "README-DEMO.txt").read_text(encoding="utf-8")


def test_every_endpoint_returns_the_demo(server):
    srv, base, p = server
    stop = time.time() + 30
    while True:                                   # the month is read in the background: on a later poll
        code, headers, body = get(srv, "/api/data")
        d = json.loads(body)
        if d["month"] or time.time() > stop:
            break
        time.sleep(0.2)
    assert code == 200 and headers["X-Content-Type-Options"] == "nosniff"
    assert d["demo"] is True
    assert {pr["name"] for pr in d["projects"]} == {demo.SHOP, demo.DOCS}
    assert [o["name"] for o in d["others"]] == [demo.QUIET]
    assert len(d["running"]) == 1 and d["running"][0]["btn"]                 # the running strip, with its stop
    assert d["leads"] and d["leads"][0]["agent"] == "claude"                  # the fake lead conversation
    assert d["month"]["sub_usd"] > 0 and d["month"]["saving"] is not None     # a month of costs, and the estimate
    shop = project(d, demo.SHOP)
    whats = {pc["run_id"]: (pc["status"], (pc.get("act") or {}).get("what")) for t in shop["tasks"]
             for pc in walk(t["pieces"])}
    assert whats == {"demo-r-ok": ("done", None), "demo-r-review": ("decide", "a_review_failed"),
                     "demo-r-running": ("run", None), "demo-r-env": ("decide", "a_env")}
    docs = project(d, demo.DOCS)
    q = next(t for t in docs["tasks"] if t["kind"] == "queue")
    assert [pc["status"] for pc in q["pieces"]] == ["done", "review", "queued"]   # one piece not merged yet
    assert "ccx q done q2 --ok 1" in q["pieces"][1]["act"]["buttons"][0]["cmd"]
    conv = next(c for c in d["conversations"] if c["name"] == demo.SHOP)
    assert sorted(x["kind"] for x in conv["todos"]) == ["asks", "stuck"]
    # each page's own data endpoint
    code, _, body = get(srv, f"/api/conv/{conv['id']}")
    threads = json.loads(body)["threads"]
    assert code == 200 and {x["key"] for x in threads} == {"discount-errors", "release-0.4"}
    stuck = next(x for x in threads if x["key"] == "discount-errors")
    assert stuck["stuck"] and any("<OrderForm>" in m["text"] for m in stuck["messages"])   # data, the page escapes
    for rid in whats:
        code, _, body = get(srv, f"/api/run/{rid}")
        assert code == 200 and json.loads(body)["run_id"] == rid
    code, _, body = get(srv, "/api/judge/demo-r-review")
    j = json.loads(body)
    assert code == 200 and j["says"]["verification"] and j["ran"]["cmd"] == "pytest -q"
    if HAS_GIT:                                                   # the snapshots need git; the card's two columns
        assert {c["path"] for c in j["changed"]} == {"orders.py", "discounts.py", "checkout.py"}
        assert j["mismatch"] == {"said_not_changed": ["tests/test_discounts.py"], "changed_not_said": ["checkout.py"]}
        assert "+def is_expired" in j["diff"]
    for name in ("index.html", "app.js", "app.css", "strings.json"):
        assert get(srv, "/" + name)[0] == 200


def test_receipt_and_token_page_have_every_part(server):
    """P2-2: what the launch shows. One hand-off's receipt (what it cost, the check ccx ran, who reviewed, the change
    from ccx's own snapshots) and the token page (the published table, per-request numbers, a Codex helper session
    under its run; the review runs, ephemeral as ccx records them, are not listed there)."""
    srv, base, p = server
    code, _, body = get(srv, "/api/run/demo-r-ok")
    r = json.loads(body)
    assert code == 200 and r["check"]["passed"] and (r["review"]["verdict"], r["review"]["by"]) == ("pass", "claude:haiku:low")
    assert r["agent"] == "codex" and r["ok"] and r["tokens"]
    d = json.loads(get(srv, "/api/data")[2])
    pc = next(pc for pr in d["projects"] for t in pr["tasks"] for pc in walk(t["pieces"]) if pc["run_id"] == "demo-r-ok")
    assert pc["usd"] == 0.0051                                  # the receipt: the run ($0.0040) and its review ($0.0011)
    j = json.loads(get(srv, "/api/judge/demo-r-ok")[2])
    assert j["ran"]["cmd"] == "pytest -q" and j["ran"]["passed"]
    if HAS_GIT:                                   # the receipt's change comes from snapshots, not from what it said
        assert {c["path"] for c in j["changed"]} == {"health.py", "tests/test_health.py"} and not j["mismatch"]
    code, _, body = get(srv, "/api/tokens?period=7d")
    tok = json.loads(body)
    assert code == 200 and tok["measured"]["source"] == "docs/measured.md"
    runs = {r["run_id"]: (t, r) for t in tok["tasks"] for r in t["runs"]}
    assert runs["demo-r-ok"][1]["requests"] == 5
    assert not any(r.startswith("demo-rv-") for r in runs)                   # ephemeral, as real reviews are
    rv = json.loads((p.runs / "demo-rv-r-ok" / "run.json").read_text(encoding="utf-8"))
    assert rv["ephemeral"] and rv["caller"] == "ccx-review" and rv["label"] == "review:demo-r-ok"   # review.py's shape
    kids = runs["demo-q2"][1]["children"]
    assert len(kids) == 1 and kids[0]["vendor"] == "codex" and kids[0]["tokens"]["total"] > 0


def _browser() -> str | None:
    """A Chrome, Chromium or Edge to render the page headless; None skips. CCX_TEST_BROWSER names one."""
    for name in (os.environ.get("CCX_TEST_BROWSER"), "google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome", "msedge"):
        if name and shutil.which(name):
            return shutil.which(name)
    for f in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if Path(f).is_file():
            return f
    return None


def render(srv, route, tmp_path):
    """The page as a headless browser leaves it after its scripts ran (--dump-dom), in English, as text."""
    import re
    prof = tmp_path / f"profile-{abs(hash(route))}"
    # Linux runners (Ubuntu 24.04) refuse Chrome's own sandbox to an unprivileged user (the page is ours, on
    # 127.0.0.1) and have no keyring; macOS would ask the keychain for a new profile
    extra = (["--no-sandbox", "--password-store=basic"] if sys.platform.startswith("linux") else
             ["--use-mock-keychain"] if sys.platform == "darwin" else [])
    named = bool(os.environ.get("CCX_TEST_BROWSER"))      # a browser named for the test must work: no skip
    try:
        r = subprocess.run([_browser(), "--headless=new", "--disable-gpu", "--no-first-run",
                            "--no-default-browser-check", *extra, f"--user-data-dir={prof}", "--lang=en-US",
                            "--virtual-time-budget=10000", "--dump-dom",
                            f"http://127.0.0.1:{srv.port}/#k={srv.token}&{route}"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    except subprocess.TimeoutExpired:
        if named:
            raise
        pytest.skip("headless browser did not finish in 90 s")
    if r.returncode != 0 and "<main" not in r.stdout:      # the browser itself did not start: not the page's fault
        if named:
            pytest.fail(f"CCX_TEST_BROWSER did not start: {r.stderr[-300:]}")
        pytest.skip(f"headless browser did not start: {r.stderr[-300:]}")
    main = r.stdout[r.stdout.find("<main"):]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", main)).replace("&amp;", "&")


@pytest.mark.skipif(_browser() is None, reason="no Chrome / Chromium / Edge to render the page")
def test_headless_browser_renders_the_demo(server, tmp_path):
    """P2-2: the same seed, rendered for real (the page's own script against the real server): the overview, the
    token page and one receipt show their parts, and no placeholder or JS value leaks into the text."""
    import re
    srv, base, p = server
    en = json.loads((REPO / "ccx" / "ui_static" / "strings.json").read_text(encoding="utf-8"))["en"]
    hc1 = next(t for t in json.loads((REPO / "ccx" / "data" / "measured.json").read_text(encoding="utf-8"))["tables"]
               if t["id"] == "hc1")["rows"]                  # the published table, whatever its numbers are
    d = json.loads(get(srv, "/api/data")[2])
    shop = project(d, demo.SHOP)
    t = next(t for t in shop["tasks"] if any(pc["run_id"] == "demo-r-ok" for pc in walk(t["pieces"])))
    pc = next(pc for pc in walk(t["pieces"]) if pc["run_id"] == "demo-r-ok")
    pages = {
        # P2-10: the home page is one project's map (the one where most waits for the person); the overview moved
        "/": [en["demo_banner"][:40], "shop-api: one map", "Discount codes for the shop API", "docs-site",
              "This week's spend here", "codex:gpt-6-luna:low", "Receipts", "basis changed: the run edited",
              "tests/test_orders.py", "review by claude · haiku: pass", "Shared memory", "integer cents", "1 right",
              "discount-errors", "Where should discount codes be checked", "Who is good at what",
              en["map_skill_none"], *(f"${r['usd_per_success']}" for r in hc1)],
        "/all": [en["demo_banner"][:40], "Discount codes for the shop API", "docs-site", en["ov_title"]],
        "/map/" + project(d, demo.DOCS)["id"]: ["docs-site: one map", "which tests it ran is not known",
                                                "no external services"],
        "/tokens": [*(f"${r['usd_per_success']}" for r in hc1), *(r["right"] for r in hc1), "019a0d3m"],
        f"/{shop['id']}/{t['id']}?sel={pc['id']}": ["Add a /health endpoint", "pytest -q", "6 passed in 0.41s",
                                                   "health.py", "haiku", "$0.0051"],
    }
    for route, want in pages.items():
        text = render(srv, route, tmp_path)
        for w in want:
            assert w in text, (route, w, text[:600])
        for bad in ("undefined", "NaN", "[object Object]"):
            assert bad not in text, (route, bad)
        assert not re.search(r"\{[a-z_]+\}", text), (route, re.search(r"\{[a-z_]+\}", text))


def test_snapshot_keeps_board_text_as_escaped_data(built, tmp_path):
    _, p, _ = built
    out = ui.export(p, tmp_path / "snap.html")
    html = out.read_text(encoding="utf-8")
    assert "\\u003cOrderForm\\u003e" in html and "<OrderForm>" not in html
    assert '"demo": true' in html


def test_same_records_every_time(tmp_path):
    now = time.time()

    def shape(base):
        with mock.patch.dict(os.environ, demo.env(base)):
            p = demo.build(base, now=now)
            d = ui.collect(p, now=now)
        rows = [{k: v for k, v in r.items() if k != "cwd"} for r in
                (json.loads(x) for x in p.ledger.read_text(encoding="utf-8").splitlines())]
        pieces = sorted((pc["title"], pc["status"]) for pr in d["projects"] for t in pr["tasks"] for pc in walk(t["pieces"]))
        return rows, pieces, d["month"]["sub_usd"]

    assert shape(tmp_path / "a") == shape(tmp_path / "b")


def test_rebuild_in_the_same_folder_starts_again(built):
    base, p, _ = built
    with mock.patch.dict(os.environ, demo.env(base)):
        demo.build(base)                                         # no doubled queue or board (it would hit the cap)
        d = ui.collect(Paths(base / "hub"))
    q = next(t for t in project(d, demo.DOCS)["tasks"] if t["kind"] == "queue")
    assert len(q["pieces"]) == 3


def test_not_a_demo_hub_is_refused(tmp_path):
    (tmp_path / "x" / "hub").mkdir(parents=True)
    with pytest.raises(ValueError):
        demo.build(tmp_path / "x")


def test_a_folder_with_other_files_is_refused_and_kept(tmp_path):
    mine = tmp_path / "x" / "projects" / "mine" / "keep.txt"
    mine.parent.mkdir(parents=True)
    mine.write_text("mine", encoding="utf-8")
    for _ in range(2):                                           # a first build and a "rebuild" both refuse
        with pytest.raises(ValueError):
            demo.build(tmp_path / "x")
    assert mine.read_text(encoding="utf-8") == "mine" and not (tmp_path / "x" / "hub").exists()
    assert not demo.remove(tmp_path / "x") and mine.exists()    # not a demo: remove() leaves it
    (tmp_path / "empty").mkdir()
    with mock.patch.dict(os.environ, demo.env(tmp_path / "empty")):
        assert demo.is_demo(demo.build(tmp_path / "empty"))      # an empty folder is fine


@pytest.mark.skipif(os.name != "nt", reason="the 260-character limit is Windows'")
def test_remove_deletes_a_demo_past_260_characters(tmp_path):
    base = tmp_path / ("d" * max(10, 140 - len(str(tmp_path))))
    with mock.patch.dict(os.environ, demo.env(base)):
        demo.build(base)
    assert demo.remove(base) and not base.exists()


def test_switch_lead_panel_and_timeline(server):
    srv, base, p = server
    d = json.loads(get(srv, "/api/data")[2])
    shop = project(d, demo.SHOP)
    sw = shop["lead_switch"]
    assert sw["current"] == "claude"
    assert [x["agent"] for x in sw["periods"]] == ["codex", "claude"]           # from the handoff record
    assert [b["label"] for b in sw["ctl"]] == ["b_cont_codex"]                   # dsh: patched as not installed
    assert "handoff --to codex --by claude --cwd" in sw["ctl"][0]["cmd"] and sw["ctl"][0]["run"]
    lead_task = next(t for t in shop["tasks"] if t["kind"] == "lead")
    assert any(h["k"] == "h_lead_at" and h["p"]["w"] == "claude" for h in lead_task["hist"])
    assert project(d, demo.DOCS)["lead_switch"]["current"] == "codex"            # the queue's lead


def test_hand_over_from_the_page(server):
    srv, base, p = server
    d = json.loads(get(srv, "/api/data")[2])
    shop = project(d, demo.SHOP)
    code, prep = post(srv, "/api/act/prepare", {"project": shop["id"], "task": "_lead", "piece": None, "btn": "c0"})
    assert code == 200 and prep["nonce"] and not prep["spends"]
    assert "--from-transcript claude --no-model --cwd" in prep["cmd"]          # the Claude conversation file is there
    assert prep["transcript"].endswith(f"{demo.LEAD_SESSION}.jsonl")
    code, out = post(srv, "/api/act/run", {"nonce": prep["nonce"]})
    assert code == 200 and out["ok"], out
    h = out["handoff"]
    f = Path(h["file"])
    assert f.is_file() and base.resolve() in f.resolve().parents and h["to"] == "codex"
    assert h["paste"].startswith("Continue the work described in the handoff at .ccx/handoffs/")
    assert h["blank"] is False and h["shown_at_start"] is True
    assert "from=claude to=codex" in f.read_text(encoding="utf-8")
    assert post(srv, "/api/act/run", {"nonce": prep["nonce"]})[0] == 409          # once
    d = json.loads(get(srv, "/api/data")[2])
    sw = project(d, demo.SHOP)["lead_switch"]
    assert sw["current"] == "codex" and [b["label"] for b in sw["ctl"]] == ["b_cont_claude"]
    lead_task = next(t for t in project(d, demo.SHOP)["tasks"] if t["kind"] == "lead")
    assert any(x["k"] == "h_lead_switch" and (x["p"]["w"], x["p"]["w2"]) == ("claude", "codex") for x in lead_task["hist"])


def test_demo_shows_but_never_runs_a_command_that_starts_an_agent(server):
    srv, base, p = server
    d = json.loads(get(srv, "/api/data")[2])
    shop = project(d, demo.SHOP)
    t = next(t for t in shop["tasks"] if any(pc["run_id"] == "demo-r-review" for pc in walk(t["pieces"])))
    pc = next(pc for pc in walk(t["pieces"]) if pc["run_id"] == "demo-r-review")
    i = next(i for i, b in enumerate(pc["act"]["buttons"]) if b["label"] == "b_one_more")   # one more round starts an agent
    code, prep = post(srv, "/api/act/prepare", {"project": shop["id"], "task": t["id"], "piece": pc["id"], "btn": f"a{i}"})
    assert code == 200 and prep["demo"] and prep["nonce"] is None and "ccx resume demo-r-review" in prep["cmd"]
    assert len(list(p.runs.iterdir())) == 8                                       # nothing was started (6 + 2 reviews)


def test_demo_server_refuses_a_spending_job_even_if_prepared(server):
    srv, base, p = server
    srv.pending["forged"] = {"argv": ["ccx", "resume", "demo-r-env"], "spends": True, "until": time.time() + 60}
    code, out = post(srv, "/api/act/run", {"nonce": "forged"})
    assert code == 409 and "demo" in json.dumps(out)
    assert len(list(p.runs.iterdir())) == 8


def test_handoff_without_a_conversation_file_says_it_is_blank(server):
    """docs-site is led by Codex and the demo seeds no Codex session file: the handoff is the blank template, and the
    page is told so before (no transcript) and after (blank)."""
    srv, base, p = server
    d = json.loads(get(srv, "/api/data")[2])
    docs = project(d, demo.DOCS)
    i = next(i for i, b in enumerate(docs["lead_switch"]["ctl"]) if b["label"] == "b_cont_claude")
    code, prep = post(srv, "/api/act/prepare", {"project": docs["id"], "task": "_lead", "piece": None, "btn": f"c{i}"})
    assert code == 200 and "transcript" in prep and prep["transcript"] is None
    code, out = post(srv, "/api/act/run", {"nonce": prep["nonce"]})
    assert code == 200 and out["ok"], out
    assert out["handoff"]["blank"] is True


@pytest.mark.parametrize("to,shown", [("claude", True), ("codex", True), ("any", True), ("dsh", False),
                                      ("gemini", False)])
def test_paste_line_matches_what_the_tool_reads_at_start(to, shown):
    from ccx.commands.memory import paste_line
    line = paste_line(to, ".ccx/handoffs/x.md")
    assert ".ccx/handoffs/x.md" in line and ("shown at start-up" in line) is shown
    r = ui.handoff_result(["ccx", "handoff", "--to", to, "--by", "claude", "--cwd", "."],
                          json.dumps({"handoff": "x.md", "paste": line}))
    assert r["shown_at_start"] is shown and r["blank"] is False


def test_lead_periods_follow_a_task_led_after_the_last_handoff(tmp_path):
    rd = ui.Reader(Paths(tmp_path / "hub"))
    from ccx import project as proj
    proj.handoff(tmp_path, "claude", "codex", "done: x")
    t_handoff = ui.handoff_history(rd, tmp_path)[-1]["ts"]
    sw = ui.lead_switch(rd, tmp_path, [{"last": t_handoff + 3600, "lead": {"agent": "claude"}}])
    assert sw["current"] == "claude"
    assert [(x["agent"], x["until"] is None) for x in sw["periods"]] == [("claude", False), ("codex", False),
                                                                         ("claude", True)]


def test_lead_switch_without_a_known_lead_offers_nothing(tmp_path):
    rd = ui.Reader(Paths(tmp_path / "hub"))
    sw = ui.lead_switch(rd, tmp_path, [])
    assert sw == {"current": None, "ctl": [], "periods": [], "switches": []}


def test_deepseek_is_offered_when_dsh_is_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("CCX_DSH_BIN", str(tmp_path / "dsh"))
    rd = ui.Reader(Paths(tmp_path / "hub"))
    sw = ui.lead_switch(rd, tmp_path, [{"last": time.time(), "lead": {"agent": "claude"}}])
    assert [b["label"] for b in sw["ctl"]] == ["b_cont_codex", "b_cont_dsh"]
    assert sw["ctl"][1]["argv"][:4] == ["ccx", "handoff", "--to", "dsh"]


def test_cli_demo_export_writes_only_the_demo(tmp_path):
    own_hub = Path(os.environ["CCX_HUB"])
    out = tmp_path / "demo.html"
    r = subprocess.run([sys.executable, str(REPO / "ccx.py"), "demo", "--dir", str(tmp_path / "d"), "--export", str(out)],
                       capture_output=True, text=True, encoding="utf-8", timeout=180, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert '"demo": true' in out.read_text(encoding="utf-8")
    assert demo.is_demo(Paths(tmp_path / "d" / "hub"))
    assert list(own_hub.iterdir()) == []
    r = subprocess.run([sys.executable, str(REPO / "ccx.py"), "handoff", "-h"], capture_output=True, text=True,
                       encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL)
    assert "--cwd" in r.stdout


def test_cli_demo_export_without_dir_leaves_no_folder(tmp_path):
    tmp = tmp_path / "t"
    tmp.mkdir()
    env = {**os.environ, "TEMP": str(tmp), "TMP": str(tmp), "TMPDIR": str(tmp)}
    out = tmp_path / "demo.html"
    r = subprocess.run([sys.executable, str(REPO / "ccx.py"), "demo", "--export", str(out)], capture_output=True,
                       text=True, encoding="utf-8", timeout=180, stdin=subprocess.DEVNULL, env=env)
    assert r.returncode == 0, r.stderr
    assert '"demo": true' in out.read_text(encoding="utf-8")
    assert not list(tmp.glob("ccx-demo-*"))                      # the export needs no folder afterwards


# ---- PM review, part B: undo and "the review is wrong" on the card, the queue's order, small text bugs
def _review_piece(d):
    shop = project(d, demo.SHOP)
    t = next(t for t in shop["tasks"] if any(pc["run_id"] == "demo-r-review" for pc in walk(t["pieces"])))
    return shop, t, next(pc for pc in walk(t["pieces"]) if pc["run_id"] == "demo-r-review")


@pytest.mark.skipif(not HAS_GIT, reason="the undo snapshot needs git")
def test_undo_this_run_from_the_page_puts_the_files_back(server):
    """A finished write run with ccx's snapshot offers "Undo this run": prepare shows `ccx undo <id> --apply`
    (records, starts nothing, so a demo hub runs it), the second click puts the files back once; afterwards the
    piece says it was undone and offers no undo."""
    srv, base, p = server
    shop, t, pc = _review_piece(json.loads(get(srv, "/api/data")[2]))
    i = next(i for i, b in enumerate(pc["ctl"]) if b["label"] == "b_undo")
    b = pc["ctl"][i]
    assert b["run"] and not b["spends"] and b["argv"] == ["ccx", "undo", "demo-r-review", "--apply"]
    assert b["note"] == "act_undo_note"
    root = Path(shop["path"])
    assert "apply" in (root / "orders.py").read_text(encoding="utf-8")
    code, prep = post(srv, "/api/act/prepare", {"project": shop["id"], "task": t["id"], "piece": pc["id"], "btn": f"c{i}"})
    assert code == 200 and prep["nonce"] and not prep.get("demo") and prep["cmd"] == "ccx undo demo-r-review --apply"
    # the confirm box lists what `ccx undo`'s own dry run would do: exactly the run's files
    assert prep["undo"] == {"restore": ["orders.py"], "move_aside": ["checkout.py", "discounts.py"], "chain_from": None}
    code, out = post(srv, "/api/act/run", {"nonce": prep["nonce"]})
    assert code == 200 and out["ok"], out
    assert (root / "orders.py").read_text(encoding="utf-8").startswith("def total(items):")
    assert not (root / "discounts.py").exists() and (root / ".ccx" / "undo" / "demo-r-review" / "discounts.py").exists()
    _, _, pc = _review_piece(json.loads(get(srv, "/api/data")[2]))
    assert pc.get("undone") and not any(b["label"] == "b_undo" for b in pc["ctl"])
    assert pc["act"] and pc["act"]["what"] == "a_review_failed"       # undo is not a verdict: it still waits for yours


@pytest.mark.skipif(not HAS_GIT, reason="the undo snapshot needs git")
def test_undo_from_the_page_refuses_when_it_would_revert_other_work(server):
    """`ccx undo` puts back every file that differs from the run's base: a later edit of a file the run never
    touched (or a later commit, or another run's work) would be reverted too. The page refuses then, at prepare
    and again at run (an edit made between the two clicks), and says to use `ccx undo <id>` in a terminal."""
    srv, base, p = server
    shop, t, pc = _review_piece(json.loads(get(srv, "/api/data")[2]))
    i = next(i for i, b in enumerate(pc["ctl"]) if b["label"] == "b_undo")
    root = Path(shop["path"])
    want = {"project": shop["id"], "task": t["id"], "piece": pc["id"], "btn": f"c{i}"}
    code, prep = post(srv, "/api/act/prepare", want)
    assert code == 200 and prep["nonce"]
    readme = root / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nan edit of the person's own\n", encoding="utf-8")
    code, out = post(srv, "/api/act/run", {"nonce": prep["nonce"]})          # checked again before it runs
    assert code != 200 and "README.md" in json.dumps(out), out
    code, out = post(srv, "/api/act/prepare", want)
    assert code != 200 and "README.md" in json.dumps(out) and "ccx undo demo-r-review" in json.dumps(out), out
    assert "apply" in (root / "orders.py").read_text(encoding="utf-8")        # nothing was put back
    assert "an edit of the person's own" in readme.read_text(encoding="utf-8")
    assert not (p.runs / "demo-r-review" / "undone.json").exists()


def test_undo_preview_refuses_while_a_run_goes_on_from_it(tmp_path):
    """A resume or review fix round of the run that is running: undo would change files under a working agent."""
    p = Paths(tmp_path / "hub")
    for rid, rec in (("r1", {"run_id": "r1", "state": "done", "mode": "write"}),
                     ("r2", {"run_id": "r2", "state": "running", "mode": "write", "resumed_from": "r1"})):
        (p.runs / rid).mkdir(parents=True)
        (p.runs / rid / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(LookupError, match="r2"):
        ui.undo_preview(p, "r1")
    (p.runs / "r2" / "run.json").write_text(json.dumps({"run_id": "r2", "state": "running", "mode": "write"}),
                                             encoding="utf-8")
    (p.runs / "r2" / "undo.json").write_text(json.dumps({"chain_from": "r1"}), encoding="utf-8")
    with pytest.raises(LookupError, match="r2"):
        ui.undo_preview(p, "r1")
    (p.runs / "r1" / "undone.json").write_text("{}", encoding="utf-8")
    with pytest.raises(LookupError, match="undone already"):
        ui.undo_preview(p, "r1")


def test_review_is_wrong_on_a_queue_piece_is_a_queue_verdict(tmp_path):
    """On a queue piece whose run failed its review, overruling the review (or handling it by hand) is `ccx q done`,
    which records the run's verdict too: a run verdict alone would leave the piece failed, hidden and unmergeable."""
    wt = tmp_path / "wt"
    wt.mkdir()
    rec = {"run_id": "r1", "state": "done", "mode": "write", "kind": "review_failed", "to": "codex", "attempts": [],
           "result": {"status": "done"}, "review": {"verdict": "issues", "issues": ["[must] x"], "by": "claude:sonnet"}}
    q = {"items": {"q1": {"id": "q1", "title": "x", "status": "failed", "run": "r1", "worktree": str(wt),
                          "agent": "codex"}}, "order": ["q1"]}
    rd = ui.Reader(Paths(tmp_path / "hub"))
    pc = ui._queue_pieces(rd, tmp_path, q, {"r1": rec}, {}, time.time())[0]
    assert pc["status"] == "decide" and pc["act"]["what"] == "a_review_failed"
    bs = {b["label"]: b for b in pc["act"]["buttons"]}
    assert bs["b_accept_anyway"]["argv"][:6] == ["ccx", "q", "done", "q1", "--ok", "1"]
    assert bs["b_myself"]["argv"][:6] == ["ccx", "q", "done", "q1", "--ok", "0"]
    assert "--cwd" in bs["b_accept_anyway"]["argv"] and ui._op(bs["b_accept_anyway"]["argv"]) == "record"
    assert pc["act"]["then"] == "ccx q accept q1"
    q["items"]["q1"].update(status="done", verdict=True)            # what `ccx q done q1 --ok 1` writes
    rec["verdict"] = {"ok": True}
    pc = ui._queue_pieces(rd, tmp_path, q, {"r1": rec}, {}, time.time())[0]
    assert pc["act"] is None and pc["ctl"][0]["label"] == "b_q_merge"   # the merge comes next


def test_merge_button_refusal_comes_back_when_prepared(server):
    """`ccx q accept` runs in the background, so prepare runs its --dry-run first: a refusal (a protected branch,
    uncommitted changes, a missing worktree...) is said on the page at once, not only in the job's log."""
    srv, base, p = server
    docs = project(json.loads(get(srv, "/api/data")[2]), demo.DOCS)
    with pytest.raises(LookupError, match="q2"):
        ui.merge_preview(p, ["ccx", "q", "accept", "q2", "--cwd", docs["path"]])


def test_review_is_wrong_accept_records_an_ok_verdict(server):
    srv, base, p = server
    shop, t, pc = _review_piece(json.loads(get(srv, "/api/data")[2]))
    labels = [b["label"] for b in pc["act"]["buttons"]]
    assert labels == ["b_see", "b_lead_fixes", "b_one_more", "b_accept_anyway", "b_myself"]
    lead = pc["act"]["buttons"][1]
    assert lead.get("prose") and not lead["run"]                   # a message for the lead, labelled so on the page
    i = labels.index("b_accept_anyway")
    b = pc["act"]["buttons"][i]
    assert b["run"] and not b["spends"] and b["argv"][:5] == ["ccx", "verify", "demo-r-review", "--ok", "1"]
    code, prep = post(srv, "/api/act/prepare", {"project": shop["id"], "task": t["id"], "piece": pc["id"], "btn": f"a{i}"})
    assert code == 200 and prep["nonce"]
    code, out = post(srv, "/api/act/run", {"nonce": prep["nonce"]})
    assert code == 200 and out["ok"], out
    _, _, pc = _review_piece(json.loads(get(srv, "/api/data")[2]))
    assert pc["act"] is None and pc["verdict"]["ok"] is True


def test_queue_piece_says_the_merge_comes_after_the_verdict(server):
    srv, base, p = server
    docs = project(json.loads(get(srv, "/api/data")[2]), demo.DOCS)
    q2 = next(pc for t in docs["tasks"] for pc in walk(t["pieces"]) if pc.get("qid") == "q2")
    assert q2["act"]["buttons"][0]["argv"][:4] == ["ccx", "q", "done", "q2"]
    assert q2["act"]["then"] == "ccx q accept q2"
    queue = next(t for t in docs["tasks"] if t["kind"] == "queue")
    assert queue["budget"]                                          # the page's top box: "Work queue: 3 pieces (budget $0.05)"


def test_env_failure_without_a_reason_has_no_empty_brackets(server):
    srv, base, p = server
    shop = project(json.loads(get(srv, "/api/data")[2]), demo.SHOP)
    pc = next(pc for t in shop["tasks"] for pc in walk(t["pieces"]) if pc["run_id"] == "demo-r-env")
    key, params = pc["act"]["why"]
    strings = json.loads((REPO / "ccx" / "ui_static" / "strings.json").read_text(encoding="utf-8"))
    if params["err"]:
        assert key in ("w_env", "w_env_codex")
    else:
        assert key in ("w_env_noerr", "w_env_codex_noerr")
        for lg in ("zh", "en"):
            assert "{err}" not in strings[lg][key] and "（）" not in strings[lg][key] and "()" not in strings[lg][key]


def test_merge_button_after_the_verdict_runs_q_accept_in_the_background(tmp_path):
    from ccx import queue as wq
    wt = tmp_path / "wt"
    wt.mkdir()
    q = {"items": {"q1": {"id": "q1", "title": "x", "status": "done", "verdict": True, "worktree": str(wt),
                          "agent": "codex"}}, "order": ["q1"]}
    rd = ui.Reader(Paths(tmp_path / "hub"))
    pc = ui._queue_pieces(rd, tmp_path, q, {}, {}, time.time())[0]
    b = pc["ctl"][0]
    assert b["label"] == "b_q_merge" and b["argv"][:4] == ["ccx", "q", "accept", "q1"] and b["style"] == "primary"
    assert b["run"] and not b["spends"] and b["bg"] and ui._op(b["argv"]) == "long"
    q["items"]["q1"]["merged"] = "abc"                               # merged: nothing more to press
    assert not ui._queue_pieces(rd, tmp_path, q, {}, {}, time.time())[0]["ctl"]
    q["items"]["q1"].pop("merged")
    wt.rmdir()                                                       # worktree gone: no button that can only fail
    assert not ui._queue_pieces(rd, tmp_path, q, {}, {}, time.time())[0]["ctl"]
    assert wq.children(q, "q1") == []


def test_cli_demo_says_what_to_open_next(tmp_path):
    out = tmp_path / "demo.html"
    r = subprocess.run([sys.executable, str(REPO / "ccx.py"), "demo", "--dir", str(tmp_path / "d"), "--export", str(out)],
                       capture_output=True, text=True, encoding="utf-8", timeout=180, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert f"next: open {out}" in r.stderr
    assert json.loads(r.stdout)["snapshot"] == str(out)              # stdout stays the JSON
