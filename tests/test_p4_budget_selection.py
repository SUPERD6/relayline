"""Follow-up regressions. Existing P4 tests and their old assertions stay intact."""
import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/eval"))
import p4_long_session as P
import p4_receipt as R
import long_candidates as C
from test_p4_long_session import fake_engine


def test_defaults_reserve_lead_plus_child_and_report_operational_bound():
    a = P.parser().parse_args(["--run", "--budget", "12"])
    assert P.task_caps(a, "self") == (1.5, 0)
    assert P.task_caps(a, "ccxlong") == (1.5, 1.5)
    limits = P.budget_envelope(a)
    assert limits["operational_upper_usd"] == 15
    assert limits["overrun_allowance_usd"] == 3
    assert limits["absolute_hard_cap"] is False
    b = P.Budget(12, spent=9.01)
    assert not b.reserve(sum(P.task_caps(a, "ccxlong")))
    report = P.summary([], 12, limits)
    assert report["budget_envelope"]["operational_upper_usd"] == 15
    assert report["all"]["verdict"] == "Unknown"


def test_explicit_run_budget_routes_to_engine_without_calling_a_model(monkeypatch, tmp_path):
    received = []
    monkeypatch.setattr(P, "run_experiment", lambda a, ts, units: received.append((a, ts, units)) or 0)
    assert P.main(["--run", "--budget", "12", "--out", str(tmp_path / "rows.jsonl")]) == 0
    a, tasks, units = received[0]
    assert a.budget == 12 and a.lead_budget == 1.5 and a.run
    assert len(units) == 2 * len(tasks)


def test_real_lead_argv_has_per_invocation_cap_without_starting_cli(monkeypatch):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(Path(__file__).parent / "fakes" / "fake_claude.py"))
    monkeypatch.setattr(P.PF, "lead_flags", lambda _: [])
    argv = P.lead_argv(SimpleNamespace(), "fake-uuid", 2, 1.5)
    assert argv[argv.index("--max-budget-usd") + 1] == "1.5"
    assert argv[-2:] == ["--resume", "fake-uuid"]


def test_repairs_share_child_allowance_and_cannot_raise_it():
    env = {"CCX_P4_CHILD_LIMIT": "1.5", "CCX_P4_CHILD_START": "2"}
    args = R.bounded_args(["resume", "run-id", "--max-usd", "99", "repair"], env, spent=2.4)
    assert float(args[args.index("--max-usd") + 1]) == pytest.approx(1.1)
    assert args[-1] == "repair"
    with pytest.raises(ValueError, match="exhausted"):
        R.bounded_args(["run", "another attempt"], env, spent=3.5)
    assert R.bounded_args(["show", "run-id"], env, spent=99) == ["show", "run-id"]


def test_code_filter_excludes_documentation_stubs_and_test_support():
    assert C.is_code("src/pkg/feature.py")
    assert C.is_code("setup.py")
    for path in ("docs/example.py", "src/pkg/feature.pyi", "tests/test_feature.py", "testing/test_hooks.py", "conftest.py"):
        assert not C.is_code(path)


def test_candidate_metric_is_code_only_and_holdout_is_excluded(monkeypatch, tmp_path):
    good, small, used = "a" * 40, "b" * 40, "c" * 40
    log = (f"{small}\t300\tsmall with many docs\n10\t2\tsrc/x.py\n200\t0\tdocs/a.rst\n1\t0\tsrc/x.pyi\n1\t0\ttests/test_x.py\n"
           f"{good}\t200\tlarge code\n40\t20\tsrc/x.py\n1\t0\ttests/test_x.py\n"
           f"{used}\t100\tused holdout\n100\t0\tsrc/x.py\n1\t0\ttests/test_x.py\n")
    monkeypatch.setattr(C, "bare_path", lambda *a: tmp_path)
    monkeypatch.setattr(C.E, "_git", lambda *a, **k: log)
    monkeypatch.setattr(C.tasks_holdout, "T", [{"repo": "fake", "commit": used}])
    monkeypatch.setattr(C.tasks_holdout, "DROPPED", [])
    result = C.candidates(tmp_path, "fake")
    assert [r["commit"] for r in result] == [good]
    assert result[0]["code_lines"] == 60


def test_modern_engine_reserves_full_child_cap_and_records_not_started(fake_engine):
    a, tasks, log = fake_engine
    a.task_cap = None
    a.lead_budget = a.child_budget = 1.5
    a.budget = 3.1
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 2
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2
    rows = P.read_jsonl(a.out)
    assert [r["reservation_usd"] for r in rows] == [1.5, 3]
    event, = P.read_jsonl(a.out.with_suffix(".events.jsonl"))
    assert event["not_started"]["arm"] == "ccxlong"
    assert event["not_started"]["reservation_usd"] == 3
    assert event["budget_envelope"]["operational_upper_usd"] == 6.1


def test_observed_overrun_is_charged_and_stops_next_task(fake_engine, monkeypatch):
    a, tasks, log = fake_engine
    a.task_cap = None
    a.lead_budget = a.child_budget = 1.5
    a.budget = 4
    original = P.r5.r3.last_result
    monkeypatch.setattr(P.r5.r3, "last_result", lambda out: {**original(out), "total_cost_usd": 5})
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 2
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    event, = P.read_jsonl(a.out.with_suffix(".events.jsonl"))
    assert event["spent_known_usd"] == 5
    assert event["budget_envelope"]["observed_overspend_usd"] == 1


def test_revised_frozen_manifest_obeys_code_rule_and_episode_grouping():
    assert len(P.TASKS.T) == 12
    assert [t["code_lines"] for t in P.TASKS.T] == [179, 68, 106, 69, 73, 66, 41, 62, 62, 128, 64, 67]
    assert sum(t["code_lines"] for t in P.TASKS.T) == 985
    assert all(t["code_lines"] >= 60 or len(t["code"]) >= 3 for t in P.TASKS.T)
    assert all(C.is_code(path) for t in P.TASKS.T for path in t["code"])
    assert P.TASKS.SELECTION["old_rule"]["status"] == "void"
    for start in (0, 4, 8):
        assert len({t["repo"] for t in P.TASKS.T[start:start + 4]}) == 1
    assert all(t["split"] == "dev" for t in P.TASKS.T[:4])
    assert all(t["split"] == "final" for t in P.TASKS.T[4:])


def test_full_validation_output_matches_its_recorded_hashes():
    path = Path(__file__).resolve().parents[1] / "docs/research/data/2026-11-04-p4-validation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["checked"]) == 12 and data["valid"]
    for row in data["checked"]:
        assert row["parent"]["rc"] == 1 and row["reference"]["rc"] == 0
        for side in ("parent", "reference"):
            body = row[side]["output"].encode("utf-8")
            assert hashlib.sha256(body).hexdigest() == row[side]["raw"]["sha256"]
            assert len(body) == row[side]["raw"]["bytes"]


def test_explicit_cli_run_reaches_preflight_from_outside_repo_without_models(tmp_path):
    root = Path(__file__).resolve().parents[1]
    marker = tmp_path / "preflight-reached.txt"
    # Child-process-only preflight/material fakes: no model CLI or user home is touched.
    (tmp_path / "sitecustomize.py").write_text(
        "import os\nfrom pathlib import Path\nimport preflight as PF\nimport long_check as LC\n"
        "LC.material = lambda *args: {}\n"
        "def check(options):\n"
        "    Path(os.environ['P4_TEST_MARKER']).write_text('preflight reached', encoding='utf-8')\n"
        "    return {'ok': False}\n"
        "PF.run_checks = check\n", encoding="utf-8", newline="")
    env = {**os.environ, "P4_TEST_MARKER": str(marker),
           "PYTHONPATH": os.pathsep.join((str(tmp_path), str(root / "scripts/eval"), str(root)))}
    result = subprocess.run([sys.executable, str(root / "scripts/eval/p4_long_session.py"),
                             "--run", "--budget", "12", "--ext-cache", str(tmp_path / "cache"),
                             "--codex-home", str(tmp_path / "codex-home"), "--workdir", str(tmp_path / "work"),
                             "--out", str(tmp_path / "results.jsonl")], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 2, result.stderr
    assert marker.read_text(encoding="utf-8") == "preflight reached"
    plan = json.loads(result.stdout)
    assert plan["run"] is True
    assert plan["budget_envelope"]["operational_upper_usd"] == 15
