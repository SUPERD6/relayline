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
    # Without verdicts these runs stay outside n; self-checks remain visible without becoming successes.
    assert (cell["n"], cell["ok"], cell["ok_self_checked"], cell["success_rate"]) == (0, 0, 1, None)
    # No judged successes means neither a success-cost median nor its cost basis can be reported.
    assert cell["median_usd_per_success"] is None
    assert cell["cost_basis"] is None
    # Unjudged attempts also supply no samples to the counted-run wall median.
    assert cell["median_wall_s"] is None
    assert cell["efforts"] == {"high": 1, "low": 3}
    assert cell["updated"] == 103 and cell["insufficient_data"]
    add(p, "bad", kind="check_failed", ok=False, ae_usd=8, seconds=400)
    cell = ability.table(p, vendor="codex", task="code")["rows"][0]
    # A failed check with no verdict is still unjudged, so it adds neither a failure nor a counted run.
    assert (cell["n"], cell["failed"], cell["success_rate"]) == (0, 0, None)
    # Five raw observations do not meet the five-judged-run threshold or establish a success-cost median.
    assert cell["insufficient_data"] and cell["median_usd_per_success"] is None


def test_verdicts_correct_existing_samples_and_self_check_stays_separate(p):
    add(p, "s", kind="ok_self_checked")
    add(p, "u", kind=None)
    ledger.append_event(p, {"type": "verify", "run_id": "s", "ok": True, "ts": 200})
    ledger.append_event(p, {"type": "verify", "run_id": "u", "ok": True, "soft": True, "ts": 201})
    cell = ability.refresh(p)["cells"][0]
    assert (cell["ok"], cell["ok_self_checked"], cell["unverified"]) == (0, 1, 1)
    ledger.append_event(p, {"type": "verify", "run_id": "u", "ok": True, "ts": 202})
    cell = ability.refresh(p)["cells"][0]
    # A positive verdict counts this run, but kind=None cannot satisfy the additional kind=ok success rule.
    assert (cell["n"], cell["ok"], cell["unverified"]) == (2, 0, 1)
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
    # User preferences do not turn an observation without a verdict into a measured success rate.
    assert (luna["preference"], luna["preference_source"], luna["success_rate"]) == ("avoid", "user", None)
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
    # The command exposes the unjudged observation, but no verdict means it contributes zero counted runs.
    assert len(doc["rows"]) == 1 and doc["rows"][0]["n"] == 0
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
    # The verdict is persisted, but this fixture's kind=None still prevents classification as a right run.
    assert (state["cells"][0]["n"], state["cells"][0]["ok"], state["cells"][0]["unverified"]) == (1, 0, 1)
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
    # Route shows the actual pending observation without counting it as a verdict-backed sample.
    assert any(r["model"] == "gpt-6-luna" and r["n"] == 0 and r["unverified"] == 1
               for r in out["ability"]["rows"])


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
        # API summaries use the same denominator: this fixture has no verdict and therefore n=0.
        assert data["rows"][0]["task"] == "fix" and data["rows"][0]["n"] == 0
        assert not (p.state / "ability.json").exists()
    finally:
        conn.close()
        server.stop()
        worker.join(timeout=10)


# Review follow-up: regression coverage for verdict-gated accounting and read-only paths.
def test_review_only_judged_ok_runs_are_right(p):
    for rid, kw in {
        "right": {"kind": "ok", "verdict": {"ok": True}, "seconds": 4},
        "wrong": {"kind": "check_failed", "ok": False, "verdict": {"ok": False}, "seconds": 6},
        "self": {"kind": "ok_self_checked", "verdict": {"ok": True}, "seconds": 8},
        "self-pending": {"kind": "ok_self_checked", "seconds": 1000},
        "pending": {"seconds": 1000},
        "soft": {"verdict": {"ok": True, "soft": True}, "seconds": 1000},
        "unknown-kind": {"kind": None, "verdict": {"ok": True}, "seconds": 10},
    }.items():
        add(p, rid, state="finished", status="done", **kw)
    cell = ability.refresh(p)["cells"][0]
    assert (cell["n"], cell["ok"], cell["failed"], cell["success_rate"]) == (4, 1, 1, .25)
    assert (cell["ok_self_checked"], cell["unverified"]) == (2, 3)
    assert cell["median_wall_s"] == 7 and cell["wall_n"] == 4
    assert cell["median_usd_per_success"] == .2
    assert cell["efforts"] == {"low": 7} and cell["insufficient_data"]
    add(p, "fifth", verdict={"ok": True}, status="done", state="finished")
    cell = ability.refresh(p)["cells"][0]
    assert cell["n"] == 5 and not cell["insufficient_data"]
    assert ability.refresh(p) == ability.refresh(p, rebuild=True)


@pytest.mark.parametrize("kw", [
    {"status": "partial"},
    {"status": "done", "result": {"status": "partial"}},
    {"status": "done", "state": "running"},
])
def test_review_partial_work_never_enters_denominator(p, kw):
    add(p, "partial", verdict={"ok": True}, **kw)
    assert ability.refresh(p)["cells"] == []


@pytest.mark.parametrize("ok", [True, False])
def test_review_no_verdict_is_neither_right_nor_failed(p, ok):
    add(p, "pending", ok=ok, kind="ok" if ok else "check_failed", state="finished", status="done")
    cell = ability.refresh(p)["cells"][0]
    assert (cell["n"], cell["ok"], cell["failed"], cell["success_rate"]) == (0, 0, 0, None)
    assert cell["unverified"] == 1
    assert cell["median_wall_s"] is None and cell["median_usd_per_success"] is None


@pytest.mark.parametrize("kind", sorted(ui.NOT_WRONG))
@pytest.mark.parametrize("verdict", [{}, {"ok": False}, {"ok": True}])
def test_review_machine_and_person_stops_are_not_ability_failures(p, kind, verdict):
    assert ability.NOT_WRONG == ui.NOT_WRONG
    assert ability.NOT_WRONG is ui.NOT_WRONG  # One source keeps future budget stops from drifting again.
    add(p, "stopped", kind=kind, ok=False, state="finished", status="failed", verdict=verdict,
        error="sandbox setup helper: 1223" if kind == "env" else kind)
    assert ability.refresh(p)["cells"] == []


def test_review_max_usd_stop_replaces_old_cached_failure(p):
    add(p, "capped", kind="max_usd", ok=False, state="finished", status="failed", verdict={"ok": False})
    # Simulate a cache produced before max_usd was recognised as a stop, without changing the ledger.
    with mock.patch.object(ability, "NOT_WRONG", ui.NOT_WRONG - {"max_usd"}):
        assert ability.refresh(p)["cells"][0]["failed"] == 1
    assert ability.refresh(p)["cells"] == []
    assert ability.refresh(p) == ability.refresh(p, rebuild=True)


def test_review_q_accept_dry_run_does_not_call_refresh(tmp_path, p):
    from ccx.commands import workqueue
    project = tmp_path / "project"
    project.mkdir()
    args = cli.parse(["q", "accept", "--all-ready", "--dry-run", "--cwd", str(project)])
    with mock.patch("ccx.accept.accept", return_value=({"plan": []}, 0)), \
            mock.patch.object(ability, "after_verdict") as refresh:
        assert workqueue.cmd_q(args) == 0
        refresh.assert_not_called()
    assert not p.state.exists()
    assert not list(project.iterdir())


def test_review_real_dry_run_writes_no_hub_files(tmp_path, monkeypatch):
    hub = tmp_path / "absent-hub"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CCX_HUB", str(hub))
    process(tmp_path, "q", "accept", "--all-ready", "--dry-run", "--cwd", str(project))
    assert not hub.exists() and not list(project.iterdir())


def test_review_api_with_no_hub_returns_seed_without_writing(tmp_path):
    hub = tmp_path / "absent-hub"
    server = ui.UI(Paths(hub), idle_s=60)
    worker = threading.Thread(target=server.serve, daemon=True)
    worker.start()
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        conn.request("GET", "/api/ability", headers={"X-CCX-Token": server.token})
        response = conn.getresponse()
        assert response.status == 200
        data = json.loads(response.read())
        assert data["seed"] and all(r["n"] == 0 for r in data["rows"])
        assert not hub.exists()
    finally:
        conn.close()
        server.stop()
        worker.join(timeout=10)


@pytest.mark.parametrize("which", ["run.json", "brief.md", "stat"])
def test_review_permission_error_does_not_cache_unread_fingerprint(p, which):
    add(p, "r", brief="", verdict={"ok": True})
    d = p.runs / "r"
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"kind": "ok"}), encoding="utf-8")
    (d / "brief.md").write_text("Fix a parser", encoding="utf-8")
    method = "stat" if which == "stat" else "read_text"
    target = d / ("run.json" if which == "stat" else which)
    original = getattr(Path, method)
    calls = []

    def denied(path, *args, **kw):
        if path == target:
            calls.append(path)
            raise PermissionError("temporarily replaced")
        return original(path, *args, **kw)

    with mock.patch.object(Path, method, autospec=True, side_effect=denied):
        for _ in range(2):
            state = ability.refresh(p)
            assert "r" not in state["entries"] and state["cells"] == []
        assert len(calls) == 2
    recovered = ability.refresh(p)
    assert recovered["cells"][0]["task"] == "fix" and recovered["cells"][0]["n"] == 1
    assert recovered == ability.refresh(p, rebuild=True)


def test_review_permission_error_keeps_only_last_good_fingerprint(p):
    add(p, "r", verdict={"ok": True})
    d = p.runs / "r"
    d.mkdir(parents=True)
    metadata = d / "run.json"
    metadata.write_text(json.dumps({"brief": "Fix it"}), encoding="utf-8")
    before = ability.refresh(p)
    metadata.write_text(json.dumps({"brief": "Docs: expand the command reference"}), encoding="utf-8")
    original = Path.read_text

    def denied(path, *args, **kw):
        if path == metadata:
            raise PermissionError("temporarily replaced")
        return original(path, *args, **kw)

    with mock.patch.object(Path, "read_text", autospec=True, side_effect=denied):
        assert ability.refresh(p) == before
    recovered = ability.refresh(p)
    assert recovered["entries"]["r"]["stamp"] != before["entries"]["r"]["stamp"]
    assert recovered["cells"][0]["task"] == "docs"


def test_review_ledger_permission_error_does_not_replace_cache(p):
    add(p, "r", verdict={"ok": True})
    ability.refresh(p)
    cache = p.state / "ability.json"
    before = cache.read_bytes()
    add(p, "new", verdict={"ok": True})
    original = Path.read_text

    def denied(path, *args, **kw):
        if path == p.ledger:
            raise PermissionError("ledger temporarily unavailable")
        return original(path, *args, **kw)

    with mock.patch.object(Path, "read_text", autospec=True, side_effect=denied):
        with pytest.raises(PermissionError):
            ability.refresh(p)
        assert cache.read_bytes() == before
    assert ability.refresh(p)["cells"][0]["n"] == 2
