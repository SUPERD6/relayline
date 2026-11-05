"""P5 isolation/selection/receipts use temporary fixtures and fake CLIs only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts/eval"))
import long_environment as L
import p4_long_session as P
import p4_receipt as R
import p5_arms as A
import p5_cold_start as COLD
from ccx import workspace as W
from test_p4_long_session import fake_engine, tree
from test_p5_tools import gate_rows


def test_full_check_output_and_actual_python_cwd_are_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "_check_doubt", lambda *a: {})
    monkeypatch.delenv("CCX_CHECK_ARTIFACTS", raising=False)
    cmd = subprocess.list2cmdline([sys.executable, str(ROOT/"tests/fakes/check_emit.py")])
    result = W.run_check(cmd, tmp_path)
    assert result["exit"] == 1 and "artifacts" not in result
    monkeypatch.setenv("CCX_CHECK_ARTIFACTS", str(tmp_path/"checks"))
    result = W.run_check(cmd, tmp_path)
    assert result["exit"] == 1 and not result["passed"] and len(result["tail"]) == 800
    dest = Path(result["artifacts"]["dir"])
    output = (dest/"stdout.log").read_text(encoding="utf-8")
    assert "CHECK_BEGIN" in output and "CHECK_END" in output and len(output) > 800
    assert (dest/"stderr.log").read_text().strip() == "CHECK_STDERR"
    data = json.loads((dest/"execution.json").read_text())
    assert Path(data["interpreter_probe"]["python"]).resolve() == Path(sys.executable).resolve()
    assert Path(data["interpreter_probe"]["cwd"]).resolve() == tmp_path.resolve()
    assert data["exit"] == 1


def test_artifact_failure_cannot_change_check_exit(tmp_path, monkeypatch):
    root = tmp_path/"not-directory"
    root.write_text("occupied")
    monkeypatch.setenv("CCX_CHECK_ARTIFACTS", str(root))
    cmd = subprocess.list2cmdline([sys.executable, str(ROOT/"tests/fakes/check_emit.py")])
    result = W.run_check(cmd, tmp_path)
    assert result["exit"] == 1 and result["artifacts"]["status"] == "Unknown"


def test_native_checkout_and_baseline_gate_before_hidden_tests(tmp_path, monkeypatch):
    parent = tree({"source.py": "value = 0\n", "tests/test_original.py": "def test_original():\n    assert False\n"})
    monkeypatch.setattr(L.LC, "material", lambda *a: {"tar": parent, "reference": parent, "tests": {}})
    monkeypatch.setattr(L, "hidden", lambda *a: pytest.fail("hidden check ran despite broken baseline"))
    row = L.validate_task(tmp_path, sys.executable, {"commit": "a"*40, "tests": []})
    assert row["baseline"]["rc"] == 1 and not row["valid"]
    assert row["reference"]["rc"] is None
    assert row["checkout"]["policy"] == L.POLICY


def test_baseline_and_hidden_use_matching_checkouts(tmp_path, monkeypatch):
    files = {"source.py": "value = 0\n", "tests/test_original.py": "def test_original():\n    import source\n    assert source.value in (0, 1)\n",
             "fixture.txt": "a\nb\n"}
    parent = tree(files)
    reference = tree({**files, "source.py": "value = 1\n"})
    hidden = {"tests/test_hidden.py": b"def test_new():\n    import source\n    assert source.value == 1\n"}
    monkeypatch.setattr(L.LC, "material", lambda *a: {"tar": parent, "reference": reference, "tests": hidden})
    row = L.validate_task(tmp_path, sys.executable, {"commit": "a"*40, "tests": list(hidden)})
    assert row["baseline"]["rc"] == 0
    assert row["parent"]["rc"] == 1 and row["reference"]["rc"] == 0 and row["valid"]


def test_selection_excludes_baseline_failure_and_keeps_full_episodes():
    previous = {"selection": "code-only", "ordering": "fixed", "repository_order": ["x"]}
    checked = [{"repo": "x", "commit": str(i), "valid": i < 3, "baseline": {"rc": 0 if i < 3 else 1}}
               for i in range(4)]
    result = L.selection_from_audit(previous, {"checked": checked, "rule": "baseline must pass"})
    assert not result["accepted"] and len(result["qualified"]) == 3
    assert result["baseline_exclusions"] == ["3"] and not result["complete"]


def test_empty_audit_cli_is_not_a_pass_outside_repository(tmp_path):
    manifest = tmp_path/"empty.json"
    manifest.write_text('{"accepted": []}', encoding="utf-8")
    run = subprocess.run([sys.executable, str(ROOT/"scripts/eval/long_environment.py"), "--manifest", str(manifest),
                          "--ext-cache", str(tmp_path), "--ext-python", sys.executable,
                          "--output", str(tmp_path/"audit.json")], cwd=tmp_path, capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert run.returncode != 0 and "empty validation is not Pass" in run.stderr
    assert not (tmp_path/"audit.json").exists()


def test_cheap_prompt_changes_only_initial_model_and_effort():
    assert A.MODEL == "gpt-6-luna" and A.EFFORT == "medium"
    task = {"brief": "Implement X", "code": ["source.py"]}
    normal = P.prompt(task, "ccxlong", 1.5)
    cheap = P.prompt(task, A.CHEAP, 1.5)
    assert cheap.replace(A.initial_model_flags(A.CHEAP), "") == normal
    focused = P.prompt(task, "ccxlong", 1.5, focused=True)
    assert "source.py" in focused and len(focused) < len(normal)
    assert P.parser().parse_args([]).focused_context is False
    assert P.parser().parse_args([]).arms == "self,ccxlong"


def test_receipt_pins_check_model_effort_through_fake_cli_outside_repo(tmp_path):
    fake_root = tmp_path/"fake-root"
    fake_root.mkdir()
    shutil.copytree(ROOT/"ccx", fake_root/"ccx", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT/"tests/fakes/ccx_capture.py", fake_root/"ccx.py")
    log = tmp_path/"argv.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT), "CCX_P4_ROOT": str(fake_root),
           "CCX_HUB": str(tmp_path/"hub"), "CCX_P4_CHILD_LIMIT": "1.5", "CCX_P4_CHILD_START": "0",
           "CCX_P4_CHILD_MODEL": A.MODEL, "CCX_P4_CHILD_EFFORT": A.EFFORT,
           "CCX_P4_CHECK_COMMAND": "PINNED_CHECK", "P5_CAPTURE_ARGV": str(log)}
    run = subprocess.run([sys.executable, str(ROOT/"scripts/eval/p4_receipt.py"), "run", "--model", "wrong",
                          "--effort=high", "--check", "wrong", "--max-usd", "1", "brief"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    args = json.loads(log.read_text())
    assert args[args.index("--model")+1] == A.MODEL
    assert args[args.index("--effort")+1] == A.EFFORT
    assert args[args.index("--check")+1] == "PINNED_CHECK"
    assert "wrong" not in args and args[args.index("--max-usd")+1] == "1.0"


def test_three_arm_schedule_budget_and_independent_gates(fake_engine):
    a, tasks, log = fake_engine
    units = P.schedule(tasks, arms=A.ARMS)
    assert len(units) == 12
    assert P.task_caps(a, A.CHEAP) == P.task_caps(a, "ccxlong")
    assert P.run_experiment(a, tasks, units) == 0
    assert len(log.read_text().splitlines()) == 12
    rows = gate_rows()
    rows += [{**r, "arm": A.CHEAP, "session_id": "cheap-"+str(r["episode"])}
             for r in rows if r["arm"] == "ccxlong"]
    report = P.summary(rows, 8, gates="p5")
    assert set(report["p5_arms"]) == set(A.ARMS)
    assert all(v["verdict"] == "Pass" for v in report["p5_candidates"].values())


def test_cold_estimates_do_not_invent_system_or_first_request_tool_tokens():
    stream = "\n".join(json.dumps(e) for e in [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "cat source.py", "aggregated_output": "abcd"*10}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "python -m pytest", "aggregated_output": "pass"}},
        {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 800}}])
    result = COLD.analyze(stream)
    assert result["observed_content"]["file_reads"]["tokens_proxy"] == 10
    assert result["first_request_file_reads_tokens"] == result["first_request_command_outputs_tokens"] == 0
    assert result["first_request_system_tools_tokens"] == "Unknown"
    assert result["inherited_context_file_command_tokens"] == "Unknown"


def test_check_artifacts_survive_fake_engine_cleanup_per_turn(fake_engine, monkeypatch):
    a, tasks, log = fake_engine
    monkeypatch.setattr(P.r5.r3, "lead_argv", lambda *a, **k: [sys.executable, str(ROOT/"tests/fakes/p5_lead.py")])
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 0
    rows = P.read_jsonl(a.out)
    assert len(rows) == 8
    for row in rows:
        assert row["checks"]["status"] == "saved" and len(row["checks"]["files"]) == 3
        dest = a.artifacts/row["streams"]["dir"]/"checks"
        output = next(dest.glob("check-*/stdout.log")).read_text()
        assert "CHECK_BEGIN" in output and len(output) > 800
        metadata = json.loads(next(dest.glob("check-*/execution.json")).read_text())
        assert metadata["interpreter_probe"]["python"] == sys.executable


def test_cheap_adapter_argv_names_requested_model_and_medium(tmp_path, monkeypatch):
    from ccx.agents import codex
    monkeypatch.setattr(codex, "bin_argv", lambda *a: ["fake-codex"])
    monkeypatch.delenv("CCX_CODEX_ISOLATE", raising=False)
    invocation = codex.codex_invocation(model=A.MODEL, effort=A.EFFORT, perm=[], cwd=tmp_path,
                                        prompt="test", run_dir=tmp_path)
    assert invocation.argv[invocation.argv.index("-m")+1] == "gpt-6-luna"
    assert 'model_reasoning_effort="medium"' in invocation.argv


def test_native_fake_engine_pins_contract_and_scores_without_changing_legacy_fixture(fake_engine, monkeypatch):
    a, tasks, log = fake_engine
    a.split, a.rounds, a.gates = "p5", 1, "p5"
    called = []
    def audit(ts, *args):
        called.append([t["id"] for t in ts])
        return {"excluded": [], "checked": []}
    monkeypatch.setattr(P.LE, "audit", audit)
    assert P.run_experiment(a, tasks, P.schedule(tasks, arms=A.ARMS)) == 0
    assert called == [[t["id"] for t in tasks]]
    rows = P.read_jsonl(a.out)
    assert len(rows) == 12 and all(r["checkout_policy"] == L.POLICY for r in rows)
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert all("--check" in entry["prompt"] for entry in entries if "Delegate" in entry["prompt"])
    assert any("--model gpt-6-luna --effort medium" in entry["prompt"] for entry in entries)


def test_interrupted_lead_exports_completed_checks_before_cleanup(fake_engine, monkeypatch):
    a, tasks, log = fake_engine
    monkeypatch.setattr(P.r5.r3, "lead_argv", lambda *a, **k: [sys.executable, str(ROOT/"tests/fakes/p5_lead.py")])
    run = P.PF.run
    cleanup = P.PF.after_unit
    def interrupted(*args, **kwargs):
        run(*args, **kwargs)
        raise RuntimeError("interrupted after a completed check")
    def checked_cleanup(unit, *args, **kwargs):
        assert list(a.artifacts.glob("*/checks/check-*/stdout.log"))
        return cleanup(unit, *args, **kwargs)
    monkeypatch.setattr(P.PF, "run", interrupted)
    monkeypatch.setattr(P.PF, "after_unit", checked_cleanup)
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 2
    row, = P.read_jsonl(a.out)
    assert row["checks"]["status"] == "saved" and row["error"] == "RuntimeError"
