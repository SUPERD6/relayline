"""P2-10: `ccx ui`'s home page, one project on one map. The data behind it (ui.project_map in /api/data's `maps`):
the agents and what went between them, shared memory linked to the runs whose brief carried a note, the receipts
(with P1-10's covers / basis_changed), this week's spend from the records only, and the page's own wiring (the old
overview and every other page keep their address). The demo seed fills every part."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import demo, ui  # noqa: E402
from ccx.config import Paths  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "ccx" / "ui_static"


@pytest.fixture(scope="module")
def data():
    base = demo.new_base()
    try:
        p = demo.build(base)
        with mock.patch.dict(os.environ, demo.env(base)):
            yield p, ui.collect(p, quota_wait=False)
    finally:
        demo.remove(base)


def the_map(d, name):
    return next(m for m in d["maps"] if m["name"] == name)


def test_demo_fills_every_part_of_the_map(data):
    _, d = data
    m = the_map(d, demo.SHOP)
    assert set(m["agents"]) == {"claude", "codex", "deepseek"}
    edge = next(e for e in m["edges"] if (e["from"], e["to"]) == ("claude", "codex"))
    assert edge["sent"] == 2 and edge["said"] == 3                  # two runs sent, three board messages
    assert {t["key"]: t["wait"] for t in m["threads"]} == {"discount-errors": "stuck", "release-0.4": "asks"}
    assert [x["id"] for x in m["talks"]] == ["demo-talk-1"] and m["talks"][0]["turns"] == 3
    assert m["memory"]["total"] == 4 and m["memory"]["here"] == 2 and m["memory"]["carried"] == 2
    assert {r["run_id"] for r in m["receipts"]} == {"demo-r-ok", "demo-r-review", "demo-r-running", "demo-r-env"}
    assert m["spend"]["runs"] == 4 and m["spend"]["rungs"]
    assert d["measured_ref"]["id"] == "hc1" and len(d["measured_ref"]["rows"]) == 3


def test_note_links_to_the_runs_that_carried_it_and_how_they_ended(data):
    """Which run used which note comes from the brief (prompt.md), and right / wrong from the verdict: #1 was in the
    accepted /health run and in the discount run nobody judged yet; #2 only in the discount run."""
    _, d = data
    notes = {n["seq"]: n for n in the_map(d, demo.SHOP)["memory"]["notes"]}
    assert (notes[1]["runs"], notes[1]["right"], notes[1]["wrong"], notes[1]["open"]) == (2, 1, 0, 1)
    assert notes[1]["last_run"] == "demo-r-review" and "integer cents" in notes[1]["text"]
    assert (notes[2]["runs"], notes[2]["open"]) == (1, 1) and notes[2]["by"] == "claude"
    assert (notes[4]["right"], notes[4]["last_run"]) == (1, "demo-r-ok")
    docs = {n["seq"]: n for n in the_map(d, demo.DOCS)["memory"]["notes"]}
    assert (docs[3]["runs"], docs[3]["right"], docs[3]["open"]) == (2, 1, 1)


def test_brief_notes_reads_only_the_notes_block(tmp_path):
    rd = ui.Reader(Paths(tmp_path / "hub"))
    d = tmp_path / "run"
    d.mkdir()
    (d / "prompt.md").write_text("Run x\n" + ui.NOTES_HEAD + " (facts):\n- #3 (shop-api): money in cents\n"
                                 "- #12 (general): run pytest\n\n## Task\nfix - #9 (x): not a note\n\n## Finish\n"
                                 "- #44 (later): not in the block\n", encoding="utf-8")
    assert ui.brief_notes(rd, d) == [3, 12]
    # the person's brief quoting the notes line (below "## Task") is not a note the brief carried
    (d / "prompt.md").write_text("Run x\n## Task\n" + ui.NOTES_HEAD + ":\n- #7 (x): quoted\n", encoding="utf-8")
    assert ui.brief_notes(rd, d) == []
    (d / "prompt.md").write_text("## Task\nno notes\n", encoding="utf-8")
    assert ui.brief_notes(rd, d) == []
    assert ui.brief_notes(rd, tmp_path / "missing") == []


def test_receipts_show_tier_rung_check_cover_and_basis_change(data):
    _, d = data
    rs = {r["run_id"]: r for r in the_map(d, demo.SHOP)["receipts"]}
    ok, rv, env = rs["demo-r-ok"], rs["demo-r-review"], rs["demo-r-env"]
    assert (ok["from"], ok["to"], ok["tier"], ok["rung"]) == ("claude", "codex", "T1", "codex:gpt-6-luna:low")
    assert ok["usd"] == 0.0051 and ok["review"] == "pass" and ok["verdict"] is True and ok["outcome"] == "right"
    assert ok["check"]["n"] == 2 and "basis_changed" not in ok["check"]
    assert rv["check"]["basis_changed"] == ["tests/test_orders.py"] and rv["review"] == "issues"
    assert rv["outcome"] == "open" and rv["notes"] == [1, 2]
    assert env["outcome"] == "open"                   # stopped by its machine: says nothing about the notes it carried
    q1 = next(r for r in the_map(d, demo.DOCS)["receipts"] if r["run_id"] == "demo-q1")
    assert q1["check"]["unknown"] and q1["outcome"] == "right"
    assert rs["demo-r-running"]["running"] and rs["demo-r-running"]["check"] is None


def test_spend_is_the_records_own_sum_never_an_estimate(data):
    p, d = data
    m = the_map(d, demo.SHOP)
    recs = [json.loads((p.runs / r / "run.json").read_text(encoding="utf-8")) for r in
            ("demo-r-ok", "demo-r-review", "demo-r-env", "demo-r-running")]
    assert m["spend"]["usd"] == round(sum(ui._usd(r) for r in recs), 4)
    assert round(sum(x["usd"] for x in m["spend"]["rungs"]), 6) == round(sum(ui._usd(r) for r in recs), 6)
    review = [x for x in m["spend"]["rungs"] if x.get("review")]
    assert {x["rung"] for x in review} == {"claude:haiku:low", "claude:sonnet:medium"}


def test_an_ordinary_note_journal_and_run_without_notes_gives_an_empty_memory_column(tmp_path):
    p = Paths(tmp_path / "hub")
    root = tmp_path / "proj"
    rec = {"run_id": "r1", "to": "codex", "caller": "claude", "tier": "T2", "ts": 1.0, "state": "finished", "ok": True,
           "attempts": [{"rung": "codex:m:low", "ae_usd": 0.01}]}
    (p.runs / "r1").mkdir(parents=True)
    (p.runs / "r1" / "prompt.md").write_text("## Task\nx\n", encoding="utf-8")
    pr = {"id": "pid", "name": "proj", "path": str(root), "tasks": []}
    m = ui.project_map(ui.Reader(p), p, pr, [rec], {}, {}, None, [], 0.0)
    assert m["memory"] == {"total": 0, "here": 0, "carried": 0, "notes": []}
    assert m["receipts"][0]["rung"] == "codex:m:low" and m["receipts"][0]["check"] is None
    assert m["spend"] == {"usd": 0.01, "runs": 1, "rungs": [{"rung": "codex:m:low", "tier": "T2", "usd": 0.01, "runs": 1}]}
    assert m["threads"] == [] and m["talks"] == [] and m["agents"] == ["claude", "codex"]


def test_page_keeps_every_old_entry_and_has_both_languages():
    """Core features stay: the overview moved to #/all and is in the nav; tokens, discussions, boards, projects,
    tasks and pieces keep their routes; every map string exists in both languages."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for route in ('r[0] === "all"', 'r[0] === "discuss"', 'r[0] === "conv"', 'r[0] === "tokens"', "renderProject(pr)",
                  "renderTask(pr, tk", 'href="#/all"', 'href="#/tokens"', "renderMap("):
        assert route in js, route
    s = json.loads((STATIC / "strings.json").read_text(encoding="utf-8"))
    keys = {k for k in s["en"] if k.startswith("map_")}
    assert keys and keys == {k for k in s["zh"] if k.startswith("map_")}
    import re
    used = {k for k in re.findall(r'"(map_[a-z_]+)"', js) if not k.endswith("_")}      # "map_rv_" + verdict: a prefix
    assert used <= keys | {k[:-2] for k in keys if k.endswith("_1")}, used - keys


def test_only_the_persons_own_verdict_and_a_real_failure_count():
    """An automatic (soft) verdict is not the person's; a dismissed run, or one stopped by the person, a budget, a
    policy or its machine, says nothing about whether the work was right."""
    done = {"run_id": "r", "state": "finished", "ok": False, "kind": "check_failed"}
    assert ui._outcome(done, None) == "wrong"
    assert ui._outcome({**done, "ok": True}, {"ok": True, "soft": True}) == "open"
    assert ui._outcome(done, {"ok": True}) == "right"
    assert ui._outcome({**done, "dismissed": True}, None) == "open"
    for kind in ("user_stopped", "over_budget", "policy", "needs_write", "timeout", "no_answer", "env", "quota"):
        assert ui._outcome({**done, "kind": kind}, None) == "open", kind


def test_receipt_takes_the_last_attempts_tier_and_ignores_a_soft_verdict(tmp_path):
    p = Paths(tmp_path / "hub")
    rec = {"run_id": "r", "state": "finished", "ok": True, "tier": "T1",
           "attempts": [{"rung": "codex:a:low", "tier": "T1"}, {"rung": "codex:b:high", "tier": "T3"}]}
    row = ui.receipt_row(ui.Reader(p), p, rec, {"ok": True, "soft": True}, {})
    assert row["verdict"] is None and row["outcome"] == "open"
    assert (row["tier"], row["rung"]) == ("T3", "codex:b:high")          # the tier the last attempt really ran on


def test_map_leaves_out_test_runs_and_the_week_counts_a_review_once():
    """An evaluation run in a real project is not on its map; a review (an ephemeral run of its own) is counted in
    its run's spend only, so the week line is the maps' sum here."""
    base = demo.new_base()
    try:
        p = demo.build(base)
        with mock.patch.dict(os.environ, demo.env(base)):
            src = json.loads((p.runs / "demo-r-ok" / "run.json").read_text(encoding="utf-8"))
            ev = {**src, "run_id": "eval-x", "label": "eval-hc1-x", "ts": src["ts"] + 1,
                  "attempts": [{**src["attempts"][0], "ae_usd": 5.0}]}
            (p.runs / "eval-x").mkdir()
            (p.runs / "eval-x" / "run.json").write_text(json.dumps(ev), encoding="utf-8")
            assert ui.is_test(ev, ui.scratch_roots(p))
            d = ui.collect(p, quota_wait=False)
    finally:
        demo.remove(base)
    m = the_map(d, demo.SHOP)
    assert "eval-x" not in {r["run_id"] for r in m["receipts"]} and m["spend"]["usd"] < 1
    assert round(d["week"]["usd"] - ui._usd(ev), 4) == round(sum(x["spend"]["usd"] for x in d["maps"]), 4)
