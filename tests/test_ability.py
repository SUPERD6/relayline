"""P0-12: fake ledgers, public measurements and actual command/API wiring; never run an agent CLI."""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import pytest

from ccx import ability, cli, ledger, ui
from ccx.commands import delegation
from ccx.config import Paths

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def p():
    return Paths(Path(os.environ["CCX_HUB"]))


def add(p, rid, *, kind="ok", brief="Implement a parser", model="gpt-6-luna", effort="low", **kw):
    row = {"run_id": rid, "to": "codex", "kind": kind, "ok": True, "mode": "write", "brief": brief,
           "rungs": [f"codex:{model}:{effort}"], "ae_usd": 0.2, "cost_usd": None, "seconds": 10, "ts": 100}
    row.update(kw)
    ledger.append_event(p, row)
    return row


def process(tmp_path, *args, check=True):
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, "-X", "utf8", str(REPO / "ccx.py"), *args], cwd=outside,
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    if check:
        assert r.returncode == 0, (r.stdout, r.stderr)
    return r


@pytest.mark.parametrize("brief,kwargs,expected", [
    ("Fix the tests", {"mode": "read"}, "read"),
    ("Implement the feature", {"mode": "read", "label": "review:r1"}, "review"),
    ("Add API", {"review": True}, "review"),
    ("Design a parser then implement it", {}, "plan"),
    ("Implement the parser and add tests", {}, "code"),
    ("Fix a regression and test it", {}, "fix"),
    ("Add tests for a parser", {"task_type": "test"}, "test"),
    ("Add tests for a parser", {}, "test"),
    ("Add docs for a parser", {}, "docs"),
    ("Fix a bug", {"route": {"kind": "code"}}, "fix"),
    ("Test the parser", {}, "test"),
    ("Review the diff", {}, "review"),
    ("Docs: update the command reference", {}, "docs"),
    ("Explain the pipeline", {}, "read"),
    ("修复解析错误并添加测试", {}, "fix"),
    ("编写文档", {}, "docs"),
    ("规划下一阶段", {}, "plan"),
    ("实现新命令", {}, "code"),
    ("", {"route": {"rubric": {"clarity": "unknown", "novelty": "new"}}}, "plan"),
    ("", {"route": {"rubric": {"files": 12, "risk": "critical", "coupling": "system"}}}, "code"),
    ("Fix it", {"route": {"mode": {"mode": "read"}}}, "read"),
])
def test_infer_task(brief, kwargs, expected):
    assert ability.infer_task(brief, **kwargs) == expected


def test_aggregation_and_real_medians(p):
    for i, cost in enumerate((0.1, 0.2, 0.9)):
        add(p, str(i), ae_usd=cost, seconds=i * 10, effort="high" if i == 2 else "low", ts=100 + i)
    add(p, "self", kind="ok_self_checked", ae_usd=0.01, seconds=30, ts=103)
    cell = ability.table(p, vendor="codex", task="code")["rows"][0]
    assert (cell["n"], cell["ok"], cell["ok_self_checked"], cell["success_rate"]) == (4, 3, 1, 0.75)
    assert cell["median_usd_per_success"] == 0.2
    assert cell["cost_basis"] == "ae_usd"
    assert cell["median_wall_s"] == 15
    assert cell["efforts"] == {"high": 1, "low": 3}
    assert cell["updated"] == 103 and cell["insufficient_data"]
    add(p, "bad", kind="check_failed", ok=False, ae_usd=8, seconds=400)
    cell = ability.table(p, vendor="codex", task="code")["rows"][0]
    assert (cell["n"], cell["failed"], cell["success_rate"]) == (5, 1, 0.6)
    assert not cell["insufficient_data"] and cell["median_usd_per_success"] == 0.2


def test_verdicts_correct_existing_samples_and_self_check_stays_separate(p):
    add(p, "s", kind="ok_self_checked")
    add(p, "u", kind=None)
    ledger.append_event(p, {"type": "verify", "run_id": "s", "ok": True, "ts": 200})
    ledger.append_event(p, {"type": "verify", "run_id": "u", "ok": True, "soft": True, "ts": 201})
    cell = ability.refresh(p)["cells"][0]
    assert (cell["ok"], cell["ok_self_checked"], cell["unverified"]) == (0, 1, 1)
    ledger.append_event(p, {"type": "verify", "run_id": "u", "ok": True, "ts": 202})
    cell = ability.refresh(p)["cells"][0]
    assert (cell["n"], cell["ok"], cell["unverified"]) == (2, 1, 0)
    ledger.append_event(p, {"type": "verify", "run_id": "u", "ok": False, "ts": 203})
    cell = ability.refresh(p)["cells"][0]
    assert (cell["n"], cell["ok"], cell["failed"], cell["updated"]) == (2, 0, 1, 203)


def test_incremental_matches_rebuild_and_only_changed_run_is_loaded(p):
    add(p, "a")
    add(p, "b", brief="Fix the bug")
    ability.refresh(p)
    with mock.patch.object(ability, "_observation", wraps=ability._observation) as read:
        ability.refresh(p)
        assert read.call_count == 0
        ledger.append_event(p, {"type": "verify", "run_id": "a", "ok": False, "ts": 200})
        incremental = ability.refresh(p)
        assert read.call_count == 1
        assert read.call_args.args[1]["run_id"] == "a"
    assert incremental == ability.refresh(p, rebuild=True)
    # A repaired/truncated ledger removes observations as well.
    p.ledger.write_text(json.dumps(add_row := {"run_id": "new", "to": "claude", "model": "opus",
        "mode": "read", "kind": "ok", "ok": True, "ts": 1}) + "\n", encoding="utf-8")
    assert ability.refresh(p) == ability.refresh(p, rebuild=True)
    assert ability.refresh(p)["cells"][0]["model"] == add_row["model"]


def test_dismissed_evaluation_and_probe_runs_do_not_train(p):
    add(p, "eval", label="eval-example")
    add(p, "probe", label="quota-probe")
    add(p, "noab", no_ab=True)
    add(p, "dismissed")
    ledger.append_event(p, {"type": "dismiss", "run_id": "dismissed"})
    assert ability.refresh(p)["cells"] == []
    ledger.append_event(p, {"type": "verify", "run_id": "dismissed", "ok": True})
    assert ability.refresh(p)["cells"][0]["n"] == 1


def test_run_metadata_final_provider_and_missing_values(p):
    add(p, "fallback", brief="", ae_usd=None, seconds=None)
    d = p.runs / "fallback"
    d.mkdir(parents=True)
    (d / "brief.md").write_text("Fix the bug", encoding="utf-8")
    (d / "run.json").write_text(json.dumps({"attempts": [
        {"agent": "codex", "model": "gpt-6-luna", "rung": "codex:gpt-6-luna:low"},
        {"agent": "dsh", "model": "deepseek-flash", "effort": "high"}],
        "route": {"rubric": {"novelty": "new"}}}), encoding="utf-8")
    cell = ability.refresh(p)["cells"][0]
    assert (cell["vendor"], cell["model"], cell["task"], cell["efforts"]) == (
        "deepseek", "deepseek-flash", "fix", {"high": 1})
    assert cell["median_usd_per_success"] is None and cell["median_wall_s"] is None
    # Metadata edits invalidate an incremental entry, including its task type and group.
    (d / "brief.md").write_text("Docs: expand the CLI reference", encoding="utf-8")
    state = ability.refresh(p)
    assert len(state["cells"]) == 1 and state["cells"][0]["task"] == "docs"
    assert state == ability.refresh(p, rebuild=True)


def test_distinct_cost_bases_and_zero_are_not_fabricated_or_mixed():
    base = {"vendor": "codex", "model": "m", "task": "test", "verdict": "ok"}
    cells = ability.aggregate([{**base, "ae_usd": 0.0, "cost_usd": 8, "wall_s": 0},
        {**base, "cost_usd": 2, "wall_s": None}, {**base, "ae_usd": float("nan"), "usd": 99}])
    c = cells[0]
    assert c["median_usd_per_success"] == 0 and c["cost_basis"] == "ae_usd"
    assert c["cost_medians"] == {"ae_usd": {"median": 0, "n": 1},
        "cost_usd": {"median": 5, "n": 2}, "usd": {"median": 99, "n": 1}}
    assert c["median_wall_s"] == 0 and c["wall_n"] == 1


def test_overrides_win_without_changing_evidence_and_preserve_comments(p):
    add(p, "a")
    f = p.state / "ability-overrides.toml"
    f.write_text('# my notes\n[claude.opus]\nplan = "prefer" # keep this\n\n'
                 '[codex."gpt-6.1-sol"]\ncode = "avoid"\n', encoding="utf-8")
    ability.set_override(p, "codex.gpt-6-luna", "code", "avoid")
    c = ability.table(p, vendor="openai", task="code")["rows"]
    luna = next(r for r in c if r["model"] == "gpt-6-luna")
    assert (luna["preference"], luna["preference_source"], luna["success_rate"]) == ("avoid", "user", 1)
    ability.set_override(p, "claude.opus", "plan", "avoid")
    ability.set_override(p, "claude.opus", "review", "prefer")
    assert "# my notes" in f.read_text(encoding="utf-8") and "# keep this" in f.read_text(encoding="utf-8")
    assert ability.overrides(p)[("codex", "gpt-6.1-sol", "code")] == "avoid"
    assert ability.overrides(p)[("claude", "opus", "review")] == "prefer"
    ability.set_override(p, "claude.opus", "plan", "clear")
    assert ("claude", "opus", "plan") not in ability.overrides(p)
    assert ability.overrides(p)[("claude", "opus", "review")] == "prefer"


def test_override_with_no_final_newline(p):
    p.state.mkdir(parents=True)
    f = p.state / "ability-overrides.toml"
    f.write_text('[claude.opus]\nplan = "prefer"', encoding="utf-8")
    ability.set_override(p, "claude.opus", "review", "avoid")
    assert ability.overrides(p)[("claude", "opus", "review")] == "avoid"


def test_concurrent_cache_and_override_updates_are_not_lost(p):
    add(p, "r")
    with ThreadPoolExecutor(max_workers=3) as ex:
        jobs = [ex.submit(ability.set_override, p, "claude.opus", t, "prefer") for t in ("plan", "code")]
        jobs.append(ex.submit(ability.refresh, p))
        for job in jobs:
            job.result(timeout=15)
    assert len(ability.overrides(p)) == 2
    assert ability.refresh(p) == ability.refresh(p, rebuild=True)


def test_seed_has_only_published_workflow_numbers_and_stays_separate(p):
    seeds = ability.load_seed()
    by = {(s["id"], s["arm"]): s for s in seeds}
    # These are the exact per-arm figures in docs/measured.md; they are not per-success medians.
    expected = {("hc1", "self"): ("29/30", .090, 21), ("hc1", "builtin"): ("27/28", .103, 123),
        ("hc1", "ccx2"): ("29/30", .063, 60.7), ("r5", "self"): ("19/20", .211, 94),
        ("r5", "builtin"): ("19/20", .155, 278), ("r5d", "builtin2"): ("17/20", .114, 276),
        ("r5f", "builtin"): ("17/20", .202, 316), ("r5e", "ccx2"): ("19/20", .131, 251),
        ("r5f", "ccx2"): ("20/20", .116, 267), ("r5g", "ccx2"): ("18/20", None, None),
        ("r5h", "ccx2"): ("19/20", .135, 236), ("pg1", "self"): ("25/30", .037, 11),
        ("pg1", "ccx2"): ("12/30", .115, 57), ("pg1", "direct"): ("9/30", .021, 44),
        ("r4", "ccx2"): (None, .595, None), ("r4", "self"): (None, .567, None)}
    assert set(by) == set(expected)
    for key, values in expected.items():
        s = by[key]
        assert (s["right"], s["usd_per_success"], s["wall_median_s"]) == values
        assert (REPO / s["source"].split("#")[0]).is_file()
    assert by[("r4", "ccx2")]["n"] is None and by[("hc1", "builtin")]["model"] is None
    row = ability.table(p, vendor="codex", task="code")["rows"][0]
    assert row["n"] == 0 and row["success_rate"] is None and row["insufficient_data"]
    assert row["seed"] and row["median_usd_per_success"] is None
    assert ability.table(p, task="plan")["rows"] == []


def test_real_commands_from_outside_repository(tmp_path, p):
    add(p, "a", brief="Fix a parser")
    output = process(tmp_path, "ability", "show", "--vendor", "codex", "--task", "fix").stdout
    assert "gpt-6-luna" in output and "数据不足" in output
    doc = json.loads(process(tmp_path, "ability", "--json", "show", "--task", "fix").stdout)
    assert len(doc["rows"]) == 1 and doc["rows"][0]["n"] == 1
    doc = json.loads(process(tmp_path, "ability", "rebuild", "--json").stdout)
    assert doc["rows"] and (p.state / "ability.json").is_file()
    process(tmp_path, "ability", "set", "claude.opus", "plan", "prefer")
    doc = json.loads(process(tmp_path, "ability", "show", "--task", "plan", "--json").stdout)
    assert doc["rows"][0]["preference_source"] == "user"
    assert "用户设定" in process(tmp_path, "ability", "show", "--task", "plan").stdout
    process(tmp_path, "ability", "set", "claude.opus", "plan", "clear", "--json")
    assert "ability" in process(tmp_path, "advanced").stdout
    assert json.loads(process(tmp_path, "ability", "--json").stdout)["rows"]
    assert process(tmp_path, "ability", "set", "bad", "code", "avoid", check=False).returncode == 3


def test_real_verify_updates_cache_without_changing_ledger_format(tmp_path, p):
    row = add(p, "verified", kind=None, brief="Fix a bug")
    d = p.runs / "verified"
    d.mkdir(parents=True)
    # No route difficulty: record_outcomes does no routing-skill training and no real CLI runs.
    (d / "run.json").write_text(json.dumps({**row, "route": {}, "attempts": [], "state": "finished"}),
                               encoding="utf-8")
    out = json.loads(process(tmp_path, "verify", "verified", "--ok", "1").stdout)
    assert out["verdict"] is True
    state = json.loads((p.state / "ability.json").read_text(encoding="utf-8"))
    assert state["cells"][0]["ok"] == 1
    assert ledger.rows(p)[-1]["type"] == "verify" and "ability" not in ledger.rows(p)[-1]
    process(tmp_path, "verify", "verified", "--ok", "0")
    assert json.loads((p.state / "ability.json").read_text(encoding="utf-8"))["cells"][0]["failed"] == 1


def test_route_only_adds_ability_and_preferences_do_not_change_the_pick(p, capsys):
    args = cli.parse(["route", "--b", "4", "--to", "codex", "Fix a parser"])
    before = delegation._route(args)
    ability.set_override(p, "codex.gpt-6-luna", "fix", "avoid")
    assert delegation.cmd_route(args) == 0
    after = json.loads(capsys.readouterr().out)
    summary = after.pop("ability")
    assert after == before
    assert summary["task"] == "fix" and summary["advisory_only"]
    assert any(r["model"] == "gpt-6-luna" and r["preference"] == "avoid" for r in summary["rows"])
    assert not (p.state / "ability.json").exists()  # route's extra field is read-only


def test_real_route_exposes_the_summary(tmp_path, p):
    add(p, "r", brief="Fix a parser")
    out = json.loads(process(tmp_path, "route", "--b", "3", "--to", "codex", "Fix a parser").stdout)
    assert out["ability"]["task"] == "fix"
    assert any(r["n"] == 1 for r in out["ability"]["rows"])


def test_corrupt_override_does_not_break_route_or_replace_the_pick(p, capsys):
    p.state.mkdir(parents=True)
    (p.state / "ability-overrides.toml").write_text("broken [", encoding="utf-8")
    args = cli.parse(["route", "implement a parser"])
    before = delegation._route(args)
    delegation.cmd_route(args)
    after = json.loads(capsys.readouterr().out)
    assert after.pop("ability")["error"]
    assert after == before


def test_api_ability_requires_token_and_does_not_change_files(p):
    add(p, "r", brief="Fix a bug")
    server = ui.UI(p, idle_s=60)
    worker = threading.Thread(target=server.serve, daemon=True)
    worker.start()
    conn = http.client.HTTPConnection("127.0.0.1", server.httpd.server_address[1], timeout=10)
    try:
        conn.request("GET", "/api/ability")
        response = conn.getresponse()
        assert response.status == 403
        response.read()
        conn.request("GET", "/api/ability?vendor=codex&task=fix", headers={"X-CCX-Token": server.token})
        response = conn.getresponse()
        assert response.status == 200
        data = json.loads(response.read())
        assert data["rows"][0]["task"] == "fix" and data["rows"][0]["n"] == 1
        assert not (p.state / "ability.json").exists()
    finally:
        conn.close()
        server.stop()
        worker.join(timeout=10)
