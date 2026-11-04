"""Engineering checks only: fake CLIs, no paid requests or user tool homes."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "eval"))
import p4_long_session as P
import p4_receipt as RECEIPT


def tree(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def tasks():
    return [{"id": f"fake-{i}", "repo": "fake", "commit": str(i) * 40,
             "brief": f"Task {i}", "tests": ["tests/test_hidden.py"], "split": "dev"} for i in range(1, 5)]


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    ts = tasks()
    fake = ROOT / "tests" / "fakes" / "p4_lead.py"
    log = tmp_path / "calls.jsonl"
    report = {"ok": True, "result": "pass", "commit": "a" * 40}
    monkeypatch.setattr(P.PF, "snapshot", lambda: [])
    monkeypatch.setattr(P.PF, "run_checks", lambda _: report)
    monkeypatch.setattr(P.PF, "between_units", lambda *a, **k: [])
    monkeypatch.setattr(P.PF, "fingerprint", lambda *a, **k: {"commit": "a" * 40})
    monkeypatch.setattr(P.PF, "audit", lambda *a, **k: {"clean": True})
    monkeypatch.setattr(P.PF, "Watch", lambda *a, **k: SimpleNamespace(start=lambda: SimpleNamespace(take=lambda: [], close=lambda: None)))
    monkeypatch.setattr(P.r5.r3, "lead_argv", lambda *a, **k: [sys.executable, str(fake)])
    original_unit = P.PF.Unit
    monkeypatch.setattr(P.PF, "Unit", lambda *a, **k: original_unit(*a, **k, real={"home": tmp_path}))
    monkeypatch.setattr(P.PF, "lead_flags", lambda _: [])

    def prepare(unit):
        unit.tmp.mkdir(parents=True)
        return {**os.environ, "P4_FAKE_LOG": str(log)}

    monkeypatch.setattr(P.PF, "prepare", prepare)
    def cleanup(unit, before, job, sids, keep_repo=False):
        job.close()
        return {"snapshot": True, "unkilled": []}

    monkeypatch.setattr(P.PF, "after_unit", cleanup)
    monkeypatch.setattr(P.r5.r2, "hub_cost", lambda _: {"usd": 0, "review_usd": 0, "run_ids": []})
    material = {t["id"]: {"tar": tree({"source.py": t["id"] + "\n", "tests/test_old.py": "# old"}),
                           "tests": {"tests/test_hidden.py": b"# HIDDEN_GRADE_SENTINEL"}} for t in ts}
    monkeypatch.setattr(P.LC, "material", lambda _, t: material[t["id"]])

    def hidden(repo, names, python):
        assert (repo / "tests/test_hidden.py").read_text() == "# HIDDEN_GRADE_SENTINEL"
        return {"ok": True, "rc": 0, "summary": "HIDDEN_GRADE_SENTINEL", "output": "HIDDEN_GRADE_SENTINEL",
                "environment_error": False}

    monkeypatch.setattr(P, "run_hidden", hidden)
    args = SimpleNamespace(ext_cache=tmp_path / "cache", codex_home=str(tmp_path / "codex"),
                           workdir=tmp_path / "work", out=tmp_path / "results.jsonl", ext_python=sys.executable,
                           wait_quiet=0, budget=5, task_cap=1, timeout=30, pin_commit="", tag="fake",
                           evidence="engineering check")
    return args, ts, log


def test_fake_resume_reset_and_hidden_grade_never_return_to_lead(fake_engine):
    a, ts, log = fake_engine
    assert P.run_experiment(a, ts, P.schedule(ts)) == 0
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(entries) == 8
    assert [x["parent"].strip() for x in entries] == [f"fake-{i}" for i in range(1, 5) for _ in range(2)]
    sessions = {e["session"] for e in entries}
    assert len(sessions) == 2
    for sid in sessions:
        es = [e for e in entries if e["session"] == sid]
        assert [e["turn"] for e in es] == [1, 2, 3, 4]
        assert [e["flag"] for e in es] == ["--session-id", "--resume", "--resume", "--resume"]
    rows = P.read_jsonl(a.out)
    assert len(rows) == 8
    assert all(r["env_clean"] and r["ok"] for r in rows)
    assert all(r["cache_read_tokens"] == r["turn"] * 100 for r in rows)
    assert all(r["context_growth_tokens"] == (r["turn"] - 1) * 100 for r in rows)
    assert all(not (s / "tests/test_hidden.py").exists() for s in a.work.glob("repo-*"))


def test_budget_reservation_stops_before_next_cli(fake_engine):
    a, ts, log = fake_engine
    a.budget = 1.15
    assert P.run_experiment(a, ts, P.schedule(ts)) == 2
    assert len(log.read_text().splitlines()) == 2
    rows = P.read_jsonl(a.out)
    assert len(rows) == 2 and sum(r["usd"] for r in rows) == .2
    assert P.summary(rows, 4)["all"]["verdict"] == "Unknown"


def test_unknown_cost_stops_and_keeps_known_child_spend(fake_engine, monkeypatch):
    a, ts, log = fake_engine
    monkeypatch.setattr(P.r5.r3, "last_result", lambda _: {})
    monkeypatch.setattr(P.r5.r2, "hub_cost", lambda _: {"usd": .04, "review_usd": .01, "run_ids": ["r"]})
    assert P.run_experiment(a, ts, P.schedule(ts)) == 2
    rows = P.read_jsonl(a.out)
    assert len(rows) == 1 and rows[0]["usd"] is None
    assert rows[0]["known_usd"] == .04
    assert P.summary(rows, 4)["all"]["arms"][rows[0]["arm"]]["cost_known_usd"] == .04


def test_summary_requires_paired_complete_denominators_and_reports_both_populations():
    rows = [{"round": 1, "episode": 1, "task": f"t{i}", "arm": arm, "ok": True,
             "usd": 1 if arm == "self" else .5, "wall_s": 2 if arm == "self" else 3,
             "cost_complete": True, "env_clean": i != 0} for i in range(4) for arm in P.ARMS]
    report = P.summary(rows, 4)
    assert report["all"]["verdict"] == "Pass"
    assert report["all"]["ratios"]["cost"] == {"numerator": 2, "denominator": 4, "ratio": .5}
    assert report["env_clean"]["verdict"] == "Unknown"
    assert report["env_clean"]["arms"]["self"]["attempted"] == 3
    assert P.summary(rows[:-1], 4)["all"]["verdict"] == "Unknown"


def test_source_task_rule_and_split():
    assert len(P.TASKS.T) == 12
    assert sum(t["split"] == "dev" for t in P.TASKS.T) == 4
    assert sum(t["split"] == "final" for t in P.TASKS.T) == 8
    assert all(len(t["commit"]) == 40 and t["brief"] for t in P.TASKS.T)
    assert all(t["code_lines"] >= 60 or len(t["code"]) >= 3 for t in P.TASKS.T)
    assert len(P.schedule(P.TASKS.T)) == 24
    import tasks_holdout
    used = {t["commit"] for t in tasks_holdout.T}
    assert not used.intersection(t["commit"] for t in P.TASKS.T)
    assert all(r["parent"]["rc"] == 1 and r["reference"]["rc"] == 0 for r in P.TASKS.SELECTION["accepted"])


def test_success_receipt_never_spills_full_details_even_when_attention_is_needed():
    result = {"ok": True, "run_id": "fake", "status": "done", "summary": "small summary",
              "check": {"passed": True}, "review": {"verdict": "pass", "notes": "PRIVATE_REVIEW"},
              "diff": "PRIVATE_DIFF", "open_questions": ["PRIVATE_QUESTION"]}
    assert not RECEIPT.leadview.clean(result)  # shipped line mode would expand this
    rendered = RECEIPT.render(result)
    assert len(rendered.splitlines()) == 1
    assert all(word not in rendered for word in ("PRIVATE_REVIEW", "PRIVATE_DIFF", "PRIVATE_QUESTION"))
    assert json.loads(rendered)["ok"] is True
    result["ok"] = False
    assert "PRIVATE_DIFF" in RECEIPT.render(result)


def test_scoring_error_preserves_already_observed_cost(fake_engine, monkeypatch):
    a, ts, log = fake_engine
    def broken(*args):
        raise OSError("fake scoring failure")
    monkeypatch.setattr(P, "score", broken)
    assert P.run_experiment(a, ts, P.schedule(ts)) == 2
    row, = P.read_jsonl(a.out)
    assert row["usd"] == .1
    assert row["error"] == "OSError" and row["env_clean"] is False
    assert row["environment_error"] is True and row["ok"] is None


@pytest.mark.parametrize("action", [[], ["--dry-run"], ["--run"]])
def test_cli_wiring_outside_repo_is_free_and_run_fails_closed(tmp_path, action):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/eval/p4_long_session.py"),
                             "--out", str(tmp_path / "results.jsonl"), *action], cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == (1 if action == ["--run"] else 0), result.stderr
    assert "hard cap" in result.stderr if action == ["--run"] else '"run": false' in result.stdout
    assert not (tmp_path / "results.jsonl").exists()


def test_unknown_budget_and_nonfinite_rejected():
    b = P.Budget(1)
    b.charge(None)
    assert not b.reserve(.01)
    with pytest.raises(SystemExit):
        P.main(["--budget", "nan"])


def test_budget_counts_prior_tags(fake_engine):
    a, ts, log = fake_engine
    P.append_jsonl(a.out, {"tag": "old", "usd": 4.5})
    assert P.run_experiment(a, ts, P.schedule(ts)) == 2
    assert not log.exists()
    assert len(P.read_jsonl(a.out)) == 1


def test_child_review_repair_cost_is_delta_per_turn(fake_engine, monkeypatch):
    a, ts, log = fake_engine
    calls = {}
    def cost(hub):
        if "ccxlong" not in hub.name:
            return {"usd": 0, "review_usd": 0, "run_ids": []}
        n = calls[hub.name] = calls.get(hub.name, 0) + 1
        return {"usd": n * .05, "review_usd": n * .01,
                "run_ids": [f"run-{i}" for i in range(1, n + 1)]}
    monkeypatch.setattr(P.r5.r2, "hub_cost", cost)
    assert P.run_experiment(a, ts, P.schedule(ts)) == 0
    delegated = [r for r in P.read_jsonl(a.out) if r["arm"] == "ccxlong"]
    assert [r["ccx_run_ids"] for r in delegated] == [[f"run-{i}"] for i in range(1, 5)]
    assert all(r["ccx_review_usd"] == .01 and r["ccx_usd"] == .05 and r["usd"] == .15 for r in delegated)


def test_other_arms_workspaces_and_hubs_are_denied(fake_engine, monkeypatch):
    a, ts, log = fake_engine
    units = []
    prepare = P.PF.prepare
    def capture(unit):
        units.append(unit)
        return prepare(unit)
    monkeypatch.setattr(P.PF, "prepare", capture)
    assert P.run_experiment(a, ts, P.schedule(ts)) == 0
    first, second = units
    assert first.repo in second.hidden and second.repo in first.hidden
    assert first.hub in second.hidden and second.hub in first.hidden
    assert not list(a.work.glob("*.jsonl"))


def test_receipt_wrapper_wiring_from_an_outside_directory(tmp_path):
    # Fake ccx source and tiny leadview module; never import or run a model CLI.
    fake_root = tmp_path / "fake-root"
    (fake_root / "ccx").mkdir(parents=True)
    (fake_root / "ccx/__init__.py").write_text("", encoding="utf-8")
    (fake_root / "ccx/leadview.py").write_text(
        "def line(result):\n    return {k: result[k] for k in ('ok', 'run_id', 'summary')}\n", encoding="utf-8")
    (fake_root / "ccx.py").write_text(
        "import json\nprint(json.dumps({'ok': True, 'run_id': 'fake', 'check': {}, "
        "'summary': 'done', 'diff': 'PRIVATE_DIFF'}, indent=2))\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/eval/p4_receipt.py"), "run", "fake"],
                            cwd=tmp_path, env={**os.environ, "CCX_P4_ROOT": str(fake_root)},
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1
    assert json.loads(result.stdout)["run_id"] == "fake"
    assert "PRIVATE_DIFF" not in result.stdout


def test_real_preflight_audit_allows_private_wrapper_and_flags_other_arm(tmp_path):
    real = {key: tmp_path / "person" / key for key in
            ("home", "home_codex", "codex_home", "ccx_home", "hub", "dsh_home", "agents_home",
             "home_claude", "claude_home", "root", "claude_json")}
    real["root_worktrees"] = []
    work = tmp_path / "work"
    other_repo = work / "repo-other"
    u = P.PF.Unit("self", work, work / "repo-self", work / "hub-self", claude="config-dir",
                  real=real, hidden=(other_repo,), flags=P.r5.EXT_FLAGS)
    own_command = f'python "{(u.x / "p4_receipt.py").as_posix()}" run fake'
    assert P.PF.path_hits([own_command], u) == []
    foreign_command = f'cat "{(other_repo / "source.py").as_posix()}"'
    assert P.PF.path_hits([foreign_command], u) == [foreign_command]
    fetch = "curl https://github.com/more-itertools/more-itertools"
    assert P.PF.path_hits([fetch], u) == [fetch]
