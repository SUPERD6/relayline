"""Round-2 p4 options (#346): frozen task files, the cheap-first v2 arm, invalid rows; fake CLIs only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_p4_long_session import fake_engine  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "eval"))
sys.path.insert(0, str(ROOT))
import p4_long_session as P
import dispatch_eval as D
import codex_tmp

LEGACY_DEV_KEYS = ['arms', 'available_tasks', 'budget_envelope', 'budget_semantics', 'budget_usd', 'checkout_policy',
                   'claude_isolation', 'cli_checked', 'estimate', 'focused_context', 'focused_retry', 'limitation',
                   'pinned_commit', 'run', 'selection_sha256', 'target_tasks', 'tasks_sha256', 'units']


def task_file(tmp_path, n=5, name="r2b.json"):
    rows = [{"repo": "fakerepo", "commit": hashlib.sha1(str(i).encode()).hexdigest(), "brief": f"Add feature {i}.",
             "tests": ["tests/test_new.py"], "code": ["pkg/mod.py"], "code_lines": 80} for i in range(1, n + 1)]
    f = tmp_path / name
    f.write_text(json.dumps({"accepted": rows}), encoding="utf-8", newline="")
    return f, hashlib.sha256(f.read_bytes()).hexdigest()


def dry(args, tmp_path):
    script = Path(P.__file__).resolve()
    r = subprocess.run([sys.executable, str(script), "--dry-run", "--out", str(tmp_path / "results.jsonl"), *args],
                       cwd=tmp_path, capture_output=True, encoding="utf-8",
                       env={**os.environ, "CCX_NO_QUOTA_PROBE": "1"})
    return r


def test_r2_split_reads_any_number_of_tasks_and_refuses_wrong_sha(tmp_path):
    f, sha = task_file(tmp_path, 5)
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha,
             "--arms", "self,ccxcheapfirst2", "--budget", "10"], tmp_path)
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert plan["target_tasks"] == 5 and plan["available_tasks"] == 5 and len(plan["units"]) == 10
    assert plan["tasks_file_sha256"] == sha
    assert all(u["turn"] == 1 for u in plan["units"])
    assert len({u["episode"] for u in plan["units"]}) == 5
    bad = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", "0" * 64,
               "--arms", "self,ccxcheapfirst2", "--budget", "10"], tmp_path)
    assert bad.returncode != 0 and "SHA-256" in bad.stderr
    missing = dry(["--split", "r2b", "--tasks-file", str(f), "--arms", "self,ccxcheapfirst2", "--budget", "10"], tmp_path)
    assert missing.returncode != 0


def test_task_file_refuses_incomplete_tasks(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"accepted": [{"repo": "x", "commit": "abc", "brief": "b", "tests": ["t.py"]}]}),
                 encoding="utf-8")
    with pytest.raises(SystemExit):
        P.load_task_file(f, hashlib.sha256(f.read_bytes()).hexdigest(), "r2b")


def test_max_tasks_limit(tmp_path):
    f, sha = task_file(tmp_path, 5)
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha, "--max-tasks", "4",
             "--arms", "self,ccxcheapfirst2", "--budget", "10"], tmp_path)
    assert r.returncode != 0 and "max-tasks" in r.stderr


def test_v2_arm_hub_has_cheap_first_and_escalate(tmp_path):
    (tmp_path / "ccx").mkdir()
    D.configure(tmp_path, True, D.ARM2)
    text = (tmp_path / "ccx" / "settings.toml").read_text(encoding="utf-8")
    assert "[dispatch]\ncheap_first = true\n" in text and '[check]\nsensitivity = "escalate"\n' in text
    from ccx.config import Paths, load_config
    cfg = load_config(Paths(tmp_path))
    assert cfg["dispatch"]["cheap_first"] is True and cfg["check"]["sensitivity"] == "escalate"
    legacy = tmp_path / "legacy"
    (legacy / "ccx").mkdir(parents=True)
    D.configure(legacy, True)
    assert (legacy / "ccx" / "settings.toml").read_text() == "[dispatch]\ncheap_first = true\n"


def test_v2_prompt_writes_failing_check_first_and_legacy_prompt_unchanged():
    task = {"brief": "Add frobnicate().", "code": ["pkg/mod.py"]}
    v2 = P.prompt(task, D.ARM2, 1.0, child_agent="claude")
    assert "fail" in v2.lower() and "before" in v2.lower()
    assert "run --to claude" in v2 and "--max-usd 1" in v2
    assert '--check "python -m pytest -q -o addopts="' not in v2
    assert "concrete inputs and expected outputs" in v2
    assert "git commit" in v2
    assert "-p no:cacheprovider" in v2 and "git status --porcelain" in v2
    legacy = P.prompt(task, D.ARM, 1.0)
    assert '--check "python -m pytest -q -o addopts="' in legacy and "run --to codex" in legacy
    assert P.prompt(task, "ccxlong", 1.0) == P.prompt(task, "ccxlong", 1.0, child_agent="codex")


def test_escalation_stop_is_a_parameter():
    rows = [{"arm": D.ARM2, "task": "t", "dispatch_observed": True,
             "side_ledger": [{"dispatch": {"cheap_first": True, "attempted": 1, "escalated": 1,
                                           "first_usd": .01, "escalation_usd": .1}}]}]
    assert D.stop_reason(rows, arm=D.ARM2) == "escalation_rate_above_30_percent"
    assert D.stop_reason(rows, arm=D.ARM2, max_rate=None) is None
    assert D.metrics(rows, arm=D.ARM2)["escalation_rate"] == 1


def test_dry_run_prints_default_first_rung_reviewers_and_network(tmp_path):
    from ccx.config import Paths, load_config, tier_spec
    f, sha = task_file(tmp_path, 3)
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha,
             "--arms", "self,ccxcheapfirst2", "--max-escalation-rate", "none", "--budget", "10",
             "--self-lead-budget", "1.5", "--lead-budget", ".5", "--child-budget", "1"], tmp_path)
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    hub = tmp_path / "hub"
    (hub / "ccx").mkdir(parents=True)
    D.configure(hub, True, D.ARM2)
    spec = tier_spec(load_config(Paths(hub)), "T1", "claude")
    first = plan["default_first_rung"][D.ARM2]
    assert (first["agent"], first["model"], first["effort"]) == ("claude", spec["model"], spec["effort"])
    asked = tier_spec(load_config(Paths(hub)), "T2", "claude")
    assert first["requested_rung"] == f"claude:{asked['model']}:{asked['effort']}"
    assert plan["tasks_sha256"] != sha and plan["selection_sha256"] == sha
    settings = plan["arm_settings"]
    assert settings[D.ARM2]["cheap_first"] is True and settings[D.ARM2]["check_sensitivity"] == "escalate"
    assert settings["self"]["cheap_first"] is False and settings["self"]["lead_budget_usd"] == 1.5
    assert settings[D.ARM2]["lead_budget_usd"] == .5 and settings[D.ARM2]["child_budget_usd"] == 1
    assert settings[D.ARM2]["child_agent"] == "claude"
    assert plan["reviewers"][D.ARM2][0].startswith("codex:")
    assert plan["network"]["codex_web_search"] == "disabled"
    assert "WebSearch" in plan["network"]["claude_subagent_deny"]
    assert plan["stop_rules"]["max_escalation_rate"] is None and plan["stop_rules"]["max_invalid_rows"] == 3
    codex = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha, "--child-agent", "codex",
                 "--arms", "self,ccxcheapfirst2", "--budget", "10"], tmp_path)
    plan = json.loads(codex.stdout)
    spec = tier_spec(load_config(Paths(hub)), "T1", "codex")
    assert plan["default_first_rung"][D.ARM2]["model"] == spec["model"]
    assert plan["stop_rules"]["max_escalation_rate"] == .3


def test_legacy_dry_runs_unchanged(tmp_path):
    r = dry(["--split", "dev"], tmp_path)
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert sorted(plan) == LEGACY_DEV_KEYS
    assert len(plan["units"]) == 8 and plan["budget_envelope"]["max_task_reservation_usd"] == 3
    r = dry(["--split", "dispatch", "--arms", "self,ccxcheapfirst", "--budget", "6.5", "--lead-budget", ".25",
             "--child-budget", ".5"], tmp_path)
    plan = json.loads(r.stdout)
    assert plan["dispatch"] == {"cheap_first": True, "tasks": 6,
                                "selection": "first six validated P4 tasks in frozen order; reused dev/final, not unseen",
                                "stop_escalation_rate_above": .3, "maximum_operational_envelope_usd": 8,
                                "evidence": "not run", "policy": "independent check only; check.baseline on_fail; new failures only"}
    assert plan["default_first_rung"][D.ARM]["agent"] == "codex"
    with pytest.raises(SystemExit):
        P.main(["--dry-run", "--split", "dispatch", "--arms", "self,ccxcheapfirst", "--budget", "9"])


def test_new_options_refused_with_legacy_combinations():
    with pytest.raises(SystemExit):
        P.main(["--dry-run", "--split", "dev", "--arms", "self,ccxcheapfirst2"])
    with pytest.raises(SystemExit):
        P.main(["--dry-run", "--split", "dev", "--child-agent", "claude"])


def test_episode_size_one_gives_each_task_its_own_session():
    ts = [{"id": f"t{i}", "repo": f"r{i % 2}"} for i in range(3)]
    units = P.schedule(ts, 1, ("self", "ccxlong"), episode_size=1)
    assert len(units) == 6 and all(u["turn"] == 1 for u in units)
    assert [u["episode"] for u in units] == [1, 1, 2, 2, 3, 3]
    with pytest.raises(ValueError):
        P.schedule(ts, 1, ("self", "ccxlong"))


def test_self_lead_budget_matches_ccx_lead_plus_child():
    from types import SimpleNamespace
    a = SimpleNamespace(lead_budget=.5, child_budget=1.0, self_lead_budget=1.5, budget=38)
    assert P.task_caps(a, "self") == (1.5, 0.0)
    assert P.task_caps(a, D.ARM2) == (.5, 1.0)
    assert P.budget_envelope(a)["max_task_reservation_usd"] == 1.5
    legacy = SimpleNamespace(lead_budget=.5, child_budget=1.0, budget=38)
    assert P.task_caps(legacy, "self") == (.5, 0.0)


def test_codex_launcher_disables_web_search_only_when_asked():
    args = ["exec", "--json", "-m", "m", "-C", "x", "-"]
    assert codex_tmp.web_search_args(args, {}) == args
    on = {"CCX_EVAL_CODEX_WEB_SEARCH": "disabled"}
    assert codex_tmp.web_search_args(args, on)[:3] == ["exec", "-c", 'web_search="disabled"']
    resume = ["exec", "resume", "abc", "--json", "-"]
    assert codex_tmp.web_search_args(resume, on)[:5] == ["exec", "resume", "abc", "-c", 'web_search="disabled"']
    assert codex_tmp.web_search_args(["--version"], on) == ["--version"]


def test_invalid_row_reasons():
    ledger = [{"dispatch": {"cheap_first": True, "attempted": 1, "escalated": 0, "first_usd": .01, "escalation_usd": 0}}]
    ok = {"arm": D.ARM2, "cost_complete": True, "dispatch_observed": True, "ok": False, "side_ledger": ledger}
    assert P.invalid_reason(ok) is None  # own timeout/cap with known cost: valid, ok=False
    assert P.invalid_reason({**ok, "cost_complete": False}) == "cost_unknown"
    assert P.invalid_reason({**ok, "environment_error": True}) == "environment_error"
    assert P.invalid_reason({**ok, "receipt_error": True}) == "receipt_error"
    assert P.invalid_reason({**ok, "dispatch_observed": False}) == "dispatch_evidence_unknown"
    assert P.invalid_reason({**ok, "side_ledger": [{"dispatch": {"cheap_first": True, "attempted": 1,
                                                                "first_usd": None, "escalation_usd": 0}}]}) == "dispatch_cost_unknown"
    assert P.invalid_reason({"arm": "self", "cost_complete": True}) is None


def _r2_engine(fake_engine, monkeypatch, tmp_path, ledger):
    a, _, log = fake_engine
    ts = [{"id": f"r2-{i}", "repo": "fake", "commit": str(i) * 40, "brief": f"Task {i}",
           "tests": ["tests/test_hidden.py"], "code": ["source.py"], "split": "r2b"} for i in range(1, 7)]
    from test_p4_long_session import tree
    material = {t["id"]: {"tar": tree({"source.py": t["id"] + "\n", "tests/test_old.py": "# old"}),
                          "tests": {"tests/test_hidden.py": b"# HIDDEN_GRADE_SENTINEL"}} for t in ts}
    monkeypatch.setattr(P.LC, "material", lambda _, t: material[t["id"]])
    a.task_cap = None
    a.lead_budget, a.child_budget, a.self_lead_budget = .5, 1.0, 1.5
    a.budget = 100
    a.split, a.max_escalation_rate, a.max_invalid_rows = "r2b", None, 3
    a.child_agent, a.episode_size, a.task_count, a.rounds = "claude", 1, len(ts), 1
    monkeypatch.setattr(P.r5, "hub_rows", ledger)
    # The shape ccx writes to run.json: the receipt's status lives under result (ledger.slim / delegate).
    monkeypatch.setattr(P.r5.r2, "record", lambda hub, rid: {"check_cmd": "python -m pytest -q tests/test_new.py",
                                                            "check_sensitivity": "sensitive",
                                                            "result": {"status": "done"}})
    return a, ts, log


def _ledger(escalated=0, first_usd=.01):
    def rows(hub):
        return ([{"run_id": "r1", "dispatch": {"cheap_first": True, "attempted": 1, "escalated": escalated,
                                               "first_usd": first_usd, "escalation_usd": .1 * escalated}}]
                if str(hub).endswith(D.ARM2) else [])
    return rows


def _run_ids(monkeypatch):
    monkeypatch.setattr(P.r5.r2, "hub_cost", lambda hub: {"usd": 0, "review_usd": 0,
                                                         "run_ids": ["r1", "rv"] if str(hub).endswith(D.ARM2) else []})


def test_receipt_error_reads_result_status_and_skips_review_records(fake_engine, monkeypatch, tmp_path):
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, _ledger())
    _run_ids(monkeypatch)
    records = {"r1": {"label": "x", "check_cmd": "c"},                     # no result: the receipt says error
               "rv": {"label": "review:r1", "result": None}}
    monkeypatch.setattr(P.r5.r2, "record", lambda hub, rid: records[rid])
    assert P.run_experiment(a, ts[:2], P.schedule(ts[:2], 1, ("self", D.ARM2))) == 0
    v2 = [r for r in P.read_jsonl(a.out) if r["arm"] == D.ARM2]
    assert all(r["receipt_error"] and r["invalid_reason"] == "receipt_error" for r in v2)
    records["r1"]["result"] = {"status": "done"}
    a.out = tmp_path / "second.jsonl"
    a.workdir = tmp_path / "work2"
    assert P.run_experiment(a, ts[:2], P.schedule(ts[:2], 1, ("self", D.ARM2))) == 0
    assert all(r["receipt_error"] is False for r in P.read_jsonl(a.out) if r["arm"] == D.ARM2)


def test_hidden_collection_error_is_a_valid_failed_row_in_round2(fake_engine, monkeypatch, tmp_path):
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, _ledger())
    monkeypatch.setattr(P, "run_hidden", lambda repo, names, python: {
        "ok": False, "rc": 2, "summary": "1 error", "output": "ImportError", "environment_error": True})
    assert P.run_experiment(a, ts[:2], P.schedule(ts[:2], 1, ("self", D.ARM2))) == 0
    rows = P.read_jsonl(a.out)
    assert all(r["ok"] is False and not r["environment_error"] and r["invalid_reason"] is None
               and r["score_collection_error"] for r in rows)


def test_round2_error_continues_but_keyboard_interrupt_stops(fake_engine, monkeypatch, tmp_path):
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, _ledger())
    original = P.Episode.step
    calls = {"n": 0}

    def step(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        if calls["n"] == 4:
            raise KeyboardInterrupt
        return original(self, *args, **kwargs)
    monkeypatch.setattr(P.Episode, "step", step)
    assert P.run_experiment(a, ts, P.schedule(ts, 1, ("self", D.ARM2))) == 2
    rows = P.read_jsonl(a.out)
    assert len(rows) == 4 and rows[0]["error"] == "RuntimeError" and rows[0]["invalid_reason"] == "cost_unknown"
    assert rows[3]["error"] == "KeyboardInterrupt"
    assert P.read_jsonl(a.out.with_suffix(".events.jsonl"))[-1]["reason"] == "interrupted_or_error"


def test_fourth_cost_unknown_row_stops(fake_engine, monkeypatch, tmp_path):
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, _ledger())
    monkeypatch.setattr(P.r5.r3, "last_result", lambda out: {})
    assert P.run_experiment(a, ts, P.schedule(ts, 1, ("self", D.ARM2))) == 2
    rows = P.read_jsonl(a.out)
    assert len(rows) == 4 and all(r["invalid_reason"] == "cost_unknown" for r in rows)
    assert all(r["reserved_usd"] == r["reservation_usd"] for r in rows) and all("source" in r for r in rows)
    event = P.read_jsonl(a.out.with_suffix(".events.jsonl"))[-1]
    assert event["reason"] == "cost_unknown_over_limit" and event["spent_known_usd"] >= 4 * 1.5


def test_dispatch_cost_unknown_is_charged_at_reservation(fake_engine, monkeypatch, tmp_path):
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, _ledger(first_usd=None))
    assert P.run_experiment(a, ts[:2], P.schedule(ts[:2], 1, ("self", D.ARM2))) == 0
    rows = P.read_jsonl(a.out)
    v2 = [r for r in rows if r["arm"] == D.ARM2]
    assert all(r["invalid_reason"] == "dispatch_cost_unknown" for r in v2)
    event = P.read_jsonl(a.out.with_suffix(".events.jsonl"))[-1]
    self_usd = sum(r["usd"] for r in rows if r["arm"] == "self")
    assert event["cost_unknown_rows"] == 2 and abs(event["spent_known_usd"] - (self_usd + 2 * 1.5)) < 1e-9


def test_v2_default_escalation_limit_still_stops(fake_engine, monkeypatch, tmp_path):
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, _ledger(escalated=1))
    a.max_escalation_rate = .3
    assert P.run_experiment(a, ts, P.schedule(ts, 1, ("self", D.ARM2))) == 2
    assert len(P.read_jsonl(a.out)) == 1
    assert P.read_jsonl(a.out.with_suffix(".events.jsonl"))[-1]["reason"] == "escalation_rate_above_30_percent"


@pytest.mark.parametrize("extra", [("--focused-retry",), ("--focused-context",), ("--episode-size", "1"),
                                   ("--native-checkout",)])
def test_v2_refuses_options_that_would_silently_change_it(tmp_path, extra):
    f, sha = task_file(tmp_path, 2)
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha,
             "--arms", "self,ccxcheapfirst2", "--budget", "10", *extra], tmp_path)
    assert r.returncode != 0 and not r.stdout


def test_engine_continues_past_invalid_rows_until_more_than_three(fake_engine, monkeypatch, tmp_path):
    # No dispatch evidence for the v2 arm: each such row is invalid; the fourth one stops the group.
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, lambda hub: [])
    units = P.schedule(ts, 1, ("self", D.ARM2))
    assert P.run_experiment(a, ts, units) == 2
    rows = P.read_jsonl(a.out)
    v2 = [r for r in rows if r["arm"] == D.ARM2]
    assert len(v2) == 4 and all(r["invalid_reason"] == "dispatch_evidence_unknown" for r in v2)
    events = P.read_jsonl(a.out.with_suffix(".events.jsonl"))
    assert events[-1]["reason"] == "dispatch_evidence_unknown"


def test_engine_v2_rows_record_check_sensitivity_and_first_rung(fake_engine, monkeypatch, tmp_path):
    from ccx.config import Paths, load_config, tier_spec

    def ledger(hub):
        if not str(hub).endswith(D.ARM2):
            return []
        cfg = load_config(Paths(hub))
        spec = tier_spec(cfg, "T1", "claude")
        return [{"run_id": "r1", "dispatch": {"cheap_first": True, "attempted": 1, "escalated": 1,
                                              "first_rung": f"claude:{spec['model']}:{spec['effort']}",
                                              "first_usd": .01, "escalation_usd": .1}}]
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, ledger)
    monkeypatch.setattr(P.r5.r2, "hub_cost", lambda hub: {"usd": 0, "review_usd": 0,
                                                         "run_ids": ["r1"] if str(hub).endswith(D.ARM2) else []})
    units = P.schedule(ts, 1, ("self", D.ARM2))
    assert P.run_experiment(a, ts, units) == 0  # 100% escalation does not stop with --max-escalation-rate none
    rows = P.read_jsonl(a.out)
    assert len(rows) == 12
    v2 = [r for r in rows if r["arm"] == D.ARM2]
    assert all(r["lead_check_commands"] == ["python -m pytest -q tests/test_new.py"] for r in v2)
    assert all(r["check_sensitivity"] == ["sensitive"] for r in v2)
    assert all(r["first_rung_matches_default"] is True for r in v2)
    assert all(r["invalid_reason"] is None and r["cap_hit"] is False for r in rows)
    assert all(r["lead_allowance_usd"] == (1.5 if r["arm"] == "self" else .5) for r in rows)
    prompts = [json.loads(s)["prompt"] for s in log.read_text().splitlines()]
    assert sum("run --to claude" in p for p in prompts) == 6
    s = P.summary(rows, 6)
    assert s["dispatch2"]["metrics"]["escalation_rate"] == 1


def test_engine_charges_unknown_cost_at_reservation_and_continues(fake_engine, monkeypatch, tmp_path):
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path,
                            lambda hub: [{"dispatch": {"cheap_first": True, "attempted": 1, "escalated": 0,
                                                       "first_usd": .01, "escalation_usd": 0}}]
                            if str(hub).endswith(D.ARM2) else [])
    real = P.r5.r3.last_result
    calls = {"n": 0}

    def last(out):
        calls["n"] += 1
        return {} if calls["n"] == 1 else real(out)  # first unit: no terminal receipt
    monkeypatch.setattr(P.r5.r3, "last_result", last)
    units = P.schedule(ts, 1, ("self", D.ARM2))
    assert P.run_experiment(a, ts, units) == 0
    rows = P.read_jsonl(a.out)
    assert len(rows) == 12 and rows[0]["invalid_reason"] == "cost_unknown"
    events = P.read_jsonl(a.out.with_suffix(".events.jsonl"))
    assert events[-1]["cost_unknown_rows"] == 1
    assert events[-1]["spent_known_usd"] >= rows[0]["reservation_usd"]
