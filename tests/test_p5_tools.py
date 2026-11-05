"""Stage 5 engineering checks; no real CLI, credentials, clock or model outcomes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/eval"))
import p4_long_session as P
import p5_costs as C
import p5_long_select as SELECT
from test_p4_long_session import fake_engine


@pytest.mark.parametrize("vendor,model,expected", [
    ("anthropic", "", "claude"), ("", "claude-sonnet-5-5", "claude"),
    ("openai", "", "codex"), ("", "gpt-6-luna", "codex"),
    ("", "unrecognized", "unknown"), ("anthropic", "gpt-6-luna", "unknown"),
    ("", "", "unknown"),
    ("", "o1-other", "codex"), ("", "o1unknown", "unknown"),
])
def test_vendor_model_only(vendor, model, expected):
    assert C.side(vendor, model) == expected


def test_native_lead_children_and_review_costs_are_counted_once():
    ledger = [
        {"ae_usd": .3, "rungs": ["codex:gpt-6-luna:low"]},
        {"ae_usd": .2, "label": "review:builder", "vendor": "anthropic", "model": "claude-haiku-4"},
        {"ae_usd": .1, "vendor": "anthropic", "model": "claude-sonnet-5"},
    ]
    row = {"lead_usd": .4, "ccx_usd": .6, "side_ledger": ledger}
    assert C.costs(row) == {"claude_side_usd": .7, "codex_side_usd": .3,
                            "unknown_side_usd": 0, "side_cost_status": "Pass"}
    assert C.aggregate([row, row])["claude_side_usd"] == 1.4


@pytest.mark.parametrize("ledger", [None, [], [{"ae_usd": .3, "to": "codex"}],
    [{"ae_usd": .3, "rungs": ["codex:gpt-6-luna:low", "claude:claude-haiku-4:low"]}],
    [{"ae_usd": .3, "model": "gpt-6-luna", "rungs": ["claude:claude-haiku-4:low"]}],
    [{"ae_usd": .3, "rungs": ["codex:gpt-6-luna:low", None]}],
    [{"ae_usd": .1, "vendor": "openai"}], [{"ae_usd": None, "vendor": "openai"}]])
def test_missing_or_ambiguous_child_evidence_remains_unknown(ledger):
    row = {"lead_usd": .2, "ccx_usd": .3, "side_ledger": ledger}
    result = C.costs(row)
    assert result["side_cost_status"] == "Unknown"
    assert result["claude_side_usd"] == .2
    assert result["unknown_side_usd"] == .3
    assert C.aggregate([row])["side_cost_status"] == "Unknown"


def gate_rows():
    return [{"tag": "p5", "round": 1, "episode": i // 4 + 1, "turn": i % 4 + 1,
             "task": f"t{i}", "arm": arm, "lead_usd": 1 if arm == "self" else .5,
             "ccx_usd": 0 if arm == "self" else .3,
             "side_ledger": [] if arm == "self" else [{"ae_usd": .3, "model": "gpt-6-luna"}],
             "usd": 1 if arm == "self" else .8, "cost_complete": True, "ok": True,
             "env_clean": i >= 2, "rc": 0, "subtype": "success", "session_match": True,
             "session_id": f"{arm}-{i // 4}",
             "wall_s": 2 if arm == "self" else 6}
            for i in range(8) for arm in P.ARMS]


def test_p5_boundary_and_no_wall_time_gate_and_p4_unchanged():
    rows = gate_rows()
    result = P.summary(rows, 8, gates="p5")
    assert result["p5"]["verdict"] == "Pass"
    assert result["p5"]["claude_cost_ratio"] == .5
    assert result["p5"]["total_cost_ratio"] == pytest.approx(.8)
    assert result["p5"]["wall_median_ratio"] == 3
    assert result["p5"]["env_clean"] == {"self": 6, "ccxlong": 6}
    assert result["all"]["verdict"] == "Fail"  # P4 still includes its wall gate
    assert "p5" not in P.summary(rows, 8)


@pytest.mark.parametrize("failure", ["cost", "right"])
def test_p5_fails_only_registered_outcome_thresholds(failure):
    rows = gate_rows()
    if failure == "cost":
        rows[1]["lead_usd"] += .01
    else:
        rows[1]["ok"] = False
    assert C.gates(rows)["verdict"] == "Fail"


@pytest.mark.parametrize("failure", ["missing", "pair", "duplicate", "clean", "per_arm", "interrupted",
                                     "receipt", "cost", "unknown_vendor", "session", "turn", "conversation"])
def test_p5_missing_evidence_cannot_pass(failure):
    rows = gate_rows()
    if failure == "missing":
        rows.pop()
    elif failure == "pair":
        rows[-1]["task"] = "other"
    elif failure == "duplicate":
        rows[-1] = dict(rows[1])
    elif failure == "clean":
        rows[4]["env_clean"] = False
    elif failure == "per_arm":
        rows[0]["env_clean"] = rows[2]["env_clean"] = True
        rows[5]["env_clean"] = False  # total 13 but ccxlong only 5
    elif failure == "interrupted":
        rows[-1]["rc"] = 1
    elif failure == "receipt":
        rows[-1]["subtype"] = "error_max_budget_usd"
    elif failure == "cost":
        rows[-1]["cost_complete"] = False
    elif failure == "unknown_vendor":
        rows[-1]["side_ledger"] = []
    elif failure == "session":
        rows[-1]["session_match"] = False
    elif failure == "turn":
        rows[-1]["turn"] = 1
    elif failure == "conversation":
        rows[-1]["session_id"] = "new-session-instead-of-resume"
    assert C.gates(rows)["verdict"] == "Unknown"


def test_fake_resume_engine_persists_ledger_attribution(fake_engine, monkeypatch):
    a, tasks, log = fake_engine
    ledger = [{"run_id": "r", "ae_usd": .04, "rungs": ["claude:claude-haiku-4:low"],
               "label": "review:builder"}]
    monkeypatch.setattr(P.r5, "hub_rows", lambda _: ledger)
    monkeypatch.setattr(P.r5.r2, "hub_cost", lambda _: {"usd": .04, "review_usd": .04, "run_ids": ["r"]})
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 0
    assert len(log.read_text().splitlines()) == 8
    rows = P.read_jsonl(a.out)
    assert all(r["claude_side_usd"] == (.14 if r["turn"] == 1 else .1) for r in rows)
    assert all(r["codex_side_usd"] == r["unknown_side_usd"] == 0 for r in rows)
    assert all(r["side_cost_status"] == "Pass" for r in rows)
    assert all(bool(r["side_ledger"]) == (r["turn"] == 1) for r in rows)


def test_recompute_cli_is_readonly_outside_checkout(tmp_path):
    source = tmp_path / "rows.jsonl"
    usage = dict.fromkeys(P.USAGE_COUNTERS, 0)
    row = {**gate_rows()[0], "session_id": "test", "lead_cumulative_usd": 1,
           "lead_result_usage": usage, "lead_model_usage": usage}
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    run = subprocess.run([sys.executable, str(Path(P.__file__).resolve()), "--recompute", str(source),
                          "--tag", "p5", "--gates", "p5"], cwd=tmp_path,
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["rows"][0]["claude_side_usd"] == 1
    assert result["summary"]["p5"]["verdict"] == "Unknown"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_no_cache_cli_reports_shortfall_without_download(tmp_path):
    cache = tmp_path / "empty-cache"
    cache.mkdir()
    output = tmp_path / "selection.json"
    run = subprocess.run([sys.executable, str(Path(SELECT.__file__).resolve()), "--ext-cache", str(cache),
                          "--output", str(output)], cwd=tmp_path, capture_output=True, text=True,
                         encoding="utf-8", timeout=30)
    assert run.returncode == 1, run.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["accepted"] == [] and result["shortfall"] == 8
    assert set(result["excluded_commits"]) == {t["commit"] for t in P.TASKS.T}
    assert len(result["missing_cached_repositories"]) == 5
    assert list(cache.iterdir()) == []


def test_p5_split_does_not_change_legacy_all_or_allow_incomplete_run(tmp_path):
    assert len(P.selected_tasks("all")) == 12
    assert P.expected_count(P.parser().parse_args(["--split", "p5"])) == 8
    # The explicit p5 split is never silently replaced with dev/final tasks.
    assert not {t["commit"] for t in P.selected_tasks("p5")} & {t["commit"] for t in P.TASKS.T}


def test_frozen_p5_manifest_preserves_eligibility_validation_and_episode_rules():
    selection = P.TASKS.P5_SELECTION
    selected = P.TASKS.P5_T
    assert len(selected) == len(selection.get("accepted", []))
    assert selection.get("complete") is (len(selected) == 8)
    assert len({t["commit"] for t in selected}) == len(selected)
    assert all(len(t["commit"]) == 40 and (t["code_lines"] >= 60 or len(t["code"]) >= 3)
               and t["parent"]["rc"] in (1, 2) and t["reference"]["rc"] == 0 for t in selected)
    assert len(P.schedule(selected)) == 2 * len(selected)
    assert all(Path(path).name.endswith(".py") and not Path(path).name.endswith(".pyi")
               for t in selected for path in t["code"])


def test_interruption_also_has_side_fields_and_keeps_known_cost(fake_engine, monkeypatch):
    a, tasks, _ = fake_engine
    monkeypatch.setattr(P.PF, "run", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(P.r5.r2, "hub_cost", lambda _: {"usd": .04, "review_usd": 0, "run_ids": []})
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 2
    row, = P.read_jsonl(a.out)
    assert row["side_cost_status"] == "Unknown"
    assert row["unknown_side_usd"] == .04


def test_selector_excludes_old_tasks_keeps_order_and_requires_groups_of_four(tmp_path, monkeypatch):
    old = P.TASKS.T[0]["commit"]
    catalog = [{"repo": "fake", "commit": old},
               *[{"repo": "fake", "commit": f"{i:040x}", "tests": ["test_x.py"],
                  "code": ["x.py"], "code_lines": 60, "timestamp": 100 - i,
                  "subject": "Add a public library operation"}
                 for i in range(1, 11)]]
    seen = []
    monkeypatch.setattr(SELECT, "REPOS", ("fake",))
    monkeypatch.setattr(SELECT.LC, "candidates", lambda *a: catalog)
    monkeypatch.setattr(SELECT.LC, "runtime", lambda _: {"models_called": False})
    monkeypatch.setattr(SELECT.LC, "material", lambda c, t: {"tar": b"parent", "reference": b"ref", "tests": {}})
    def check(tree, *args):
        seen.append(tree)
        return {"rc": 1 if tree == b"parent" else 0}
    monkeypatch.setattr(SELECT.LC, "check_tree", check)
    report = SELECT.select(tmp_path, sys.executable)
    assert len(report["accepted"]) == 8 and report["complete"]
    assert [r["commit"] for r in report["accepted"]] == [f"{i:040x}" for i in range(1, 9)]
    assert all(r["parent"]["rc"] == 1 and r["reference"]["rc"] == 0 for r in report["accepted"])
    assert seen == [b"parent", b"ref"] * 8
    assert old in report["excluded_commits"]
    catalog[:] = catalog[:4]  # old + three valid tasks: no complete episode
    report = SELECT.select(tmp_path, sys.executable)
    assert report["accepted"] == [] and report["shortfall"] == 8
    assert len(report["qualified"]) == 3


def test_dry_run_and_incomplete_run_cli_outside_repo(tmp_path):
    cmd = [sys.executable, str(Path(P.__file__).resolve()), "--split", "p5", "--gates", "p5",
           "--out", str(tmp_path / "results.jsonl"), "--budget", "9"]
    dry = subprocess.run([*cmd, "--dry-run"], cwd=tmp_path, capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert dry.returncode == 0, dry.stderr
    plan = json.loads(dry.stdout)
    assert plan["target_tasks"] == 8 and plan["run"] is False
    if not P.TASKS.P5_T:
        refused = subprocess.run([*cmd, "--run"], cwd=tmp_path, capture_output=True,
                                 text=True, encoding="utf-8", timeout=30)
        assert refused.returncode != 0
        assert "P5 selection incomplete" in refused.stderr
        assert not (tmp_path / "results.jsonl").exists()
