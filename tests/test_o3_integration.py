"""Integration regressions: fake CLIs only, never external model or client homes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest

from ccx.contract_semantic import generate_semantic
from ccx.delegate import compact

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "scripts/eval"
sys.path.insert(0, str(EVAL))
import contract_defects as defects
import review_contract_diag as diag
import strength_retest as retest
import strength_runner as runner

FAKE = ROOT / "tests/fakes/fake_contract.py"
SOURCES = {"task": "Return 2.", "user_words": "Keep integers.", "interface": "def value(): pass"}


def test_compact_retains_both_integrated_fields(tmp_path):
    record = {"run_id": "r", "to": "codex", "tier": "T1", "ok": True, "kind": "ok",
              "attempts": [], "result": {"status": "done"}, "contract_diagnostic": {"behaviors": []},
              "dispatch": {"phase": "first"}, "cwd": str(tmp_path)}
    receipt = compact(record)
    assert receipt["contract_diagnostic"] == record["contract_diagnostic"]
    assert receipt["dispatch"] == record["dispatch"] and receipt["ok"]
    assert receipt["evidence_level"] == "unverified"


def test_semantic_adapter_empty_cwd_allowlist_and_semantics(monkeypatch):
    monkeypatch.setenv("CONTRACT_SECRET", "do not inherit")
    monkeypatch.setenv("PYTHONPATH", "do not inherit")
    result = generate_semantic({**SOURCES, "implementation": "IMPLEMENTATION_SECRET", "hidden": "HIDDEN_SECRET"},
                               budget=.1, cli=[sys.executable, str(FAKE)])
    assert result["exit_code"] == 0 and result["cost_usd"] == .01
    row = result["contract"]["behaviors"][0]
    assert row["expected"] != row["quote"] and row["unknown"] is False
    assert result["contract"]["generator"] == "claude-semantic"


@pytest.mark.parametrize("flag", ["--fake-missing-cost", "--fake-error"])
def test_semantic_failure_and_unknown_cost(flag):
    result = generate_semantic(SOURCES, budget=.1, cli=[sys.executable, str(FAKE), flag])
    if flag == "--fake-missing-cost":
        assert result["cost_usd"] is None
    else:
        assert result["cost_usd"] == .01 and result["contract"]["behaviors"] == []


def test_no_call_on_invalid_budget():
    with mock.patch("ccx.contract_semantic.subprocess.run") as run:
        with pytest.raises(ValueError):
            generate_semantic(SOURCES, budget=float("nan"))
    run.assert_not_called()


HIDDEN = ("_________________ Tests.test_value _________________\n"
          ">       assert value() == 2\nE       assert 3 == 2\n"
          "FAILED test_hidden.py::Tests::test_value - assert 3 == 2\n")


def test_mapping_is_unconfirmed_and_cannot_score_until_human_fills_it(tmp_path):
    folder = tmp_path / "snapshot/pg3b-1-pg-book-store-ccx2"
    folder.mkdir(parents=True)
    path = folder / "hidden-pytest.txt"
    path.write_text(HIDDEN, encoding="utf-8")
    table = defects.defect_table(tmp_path, {1: "book-store"})
    rule = table["p2-1"][0]
    assert rule["hidden_test"] == "test_hidden.py::Tests::test_value"
    assert any("value() == 2" in s for s in rule["failure_assertions"])
    assert rule["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert rule["confirmed"] is False and rule["requirements"] == []
    from ccx.review_pipeline import validate
    contract = validate({"behaviors": [{"id": "b", "source": "task", "quote": "Return 2.",
                         "expected": "Returns integer 2", "unknown": False}]}, SOURCES)
    assert diag.score(contract, [rule], tmp_path)["coverage"] == "Unknown"
    rule.update(confirmed=True, requirements=[{"source": "task", "quote": "Return 2.",
                                               "expected_contains": ["integer", "2"]}])
    assert diag.score(contract, [rule], tmp_path)["coverage"] == "Pass"
    contract["behaviors"][0]["expected"] = "Returns string 2"
    assert diag.score(contract, [rule], tmp_path)["coverage"] == "Fail"


def invoke(script, args, cwd, env=None):
    return subprocess.run([sys.executable, "-X", "utf8", str(EVAL / script), *args], cwd=cwd,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "CCX_NO_LOCATE": "1", **(env or {})},
        capture_output=True, text=True, encoding="utf-8", timeout=90)


def test_diagnostic_actual_entrypoint_with_fake_semantic_cli(tmp_path):
    material = tmp_path / "evidence/p2-1"
    tree = material / "tree"
    tree.mkdir(parents=True)
    (tree / "book_store.py").write_text("def total(books): pass\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "book_store.py"],
                 ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "stub"]):
        subprocess.run(["git", *args], cwd=tree, check=True, capture_output=True)
    (material / "job.json").write_text(json.dumps({"task_text": "Return 2.", "user_task": "Keep integers."}), encoding="utf-8")
    hidden = tmp_path / "hidden/pg3b-1-pg-book-store-ccx2"
    hidden.mkdir(parents=True)
    (hidden / "hidden-pytest.txt").write_text(HIDDEN, encoding="utf-8")
    out = tmp_path / "out"
    result = invoke("review_contract_diag.py", ["--evidence", str(material.parent), "--run", "--generator", "claude",
        "--budget", "8", "--out", str(out), "--map-defects", "--hidden-root", str(hidden.parent)], tmp_path,
        {"CCX_CLAUDE_BIN": str(FAKE)})
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["model_calls"] == 1 and report["spent_usd"] == .01 and report["unknown"] == 15
    assert report["defect_rows"] == 1
    assert (out / "human-review.md").exists() and (out / "p2-1.json").exists()
    missing = invoke("review_contract_diag.py", ["--evidence", str(material.parent), "--run", "--generator", "claude"], tmp_path)
    assert missing.returncode == 2


@pytest.mark.parametrize("kind,cap", [("context", 4), ("memory", 3)])
def test_runner_entrypoint_dry_run_and_required_budget(tmp_path, kind, cap):
    before = set(tmp_path.iterdir())
    result = invoke("strength_retest.py", ["execute", kind, "--dry-run"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["cap_usd"] == cap
    assert set(tmp_path.iterdir()) == before
    for extra in (["--run"], ["--run", "--budget", str(cap + 1)], ["--budget", "nan"]):
        assert invoke("strength_retest.py", ["execute", kind, *extra], tmp_path).returncode == 2
    preview = invoke("strength_retest.py", ["execute", kind, "--dry-run", "--budget", ".001"], tmp_path)
    data = json.loads(preview.stdout)
    assert preview.returncode == 2 and data["budget_usd"] == .001 and data["within_budget"] is False


@pytest.mark.parametrize("cost", [None, .06, .05])
def test_serial_runner_stops_and_keeps_unknown_or_overspend(tmp_path, cost):
    manifest = {**retest.plan("memory", 1), "units": [{"task": "one"}, {"task": "two"}], "n": 2}
    row = {"ok": False, "usd": cost}
    with mock.patch.object(runner, "run_unit", return_value=row) as run:
        report = runner.execute(manifest, tmp_path / "out", .05, .05)
    assert run.call_count == 1 and report["budget_stopped"] and report["attempted"] == 1
    assert len((tmp_path / "out/results.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert report["spent_usd"] == cost
    frozen = json.loads((tmp_path / "out/manifest.json").read_text(encoding="utf-8"))
    assert frozen["runtime_budget_usd"] == .05 and frozen["unit_budget_usd"] == .05


@pytest.mark.parametrize("arm", ["nomem", "mem", "hubmem", "hubstart"])
def test_memory_arms_execute_real_ccx_with_fake_cli(tmp_path, monkeypatch, arm):
    monkeypatch.setenv("CCX_CODEX_BIN", str(ROOT / "tests/fakes/fake_codex.py"))
    monkeypatch.setenv("CCX_NO_LOCATE", "1")
    monkeypatch.setenv("FAKE_WRITE", "net.py=" + runner.CASES[0]["solution"]["net.py"])
    unit = {"task": "mem-errors", "arm": arm, "agent": "codex", "model": "gpt-6-luna", "effort": "low", "rep": 1}
    row = runner.run_unit(unit, "memory", tmp_path / arm, .1, fake_codex_home(tmp_path))
    assert "error" not in row, row
    assert row["usd"] is not None and row["ok"] is True
    assert row["note_in_prompt"] is (arm in ("hubmem", "hubstart"))
    assert row["project_context_referenced"] is (arm == "mem")
    assert row["startup_payload_delivered"] is (arm == "hubstart")


def fake_codex_home(tmp_path):
    """A stand-in for a logged-in Codex home: an empty placeholder auth.json, no credential in it."""
    home = tmp_path / "eval-codex-home"
    home.mkdir(exist_ok=True)
    (home / "auth.json").write_text("", encoding="utf-8")
    return home


def test_runner_actual_execution_entrypoint_budget_stop_with_fake(tmp_path):
    home = fake_codex_home(tmp_path)
    result = invoke("strength_retest.py", ["execute", "memory", "--run", "--budget", "0.000001",
        "--unit-budget", "0.000001", "--reps", "1", "--out", str(tmp_path / "run"), "--codex-home", str(home)],
        tmp_path, {"CCX_CODEX_BIN": str(ROOT / "tests/fakes/fake_codex.py")})
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["budget_stopped"] and report["attempted"] == 1
    assert (tmp_path / "run/results.jsonl").exists()
    frozen = json.loads((tmp_path / "run/manifest.json").read_text(encoding="utf-8"))
    assert frozen["codex_home"] == str(home.resolve())


def test_codex_home_is_resolved_and_prepared_like_p4(tmp_path, monkeypatch):
    """A relative --codex-home becomes absolute; a passing home gets p4's start config (on Windows the
    unelevated sandbox); a home inside your own Codex home is refused."""
    home = fake_codex_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert retest.checked_codex_home(home.name) == home.resolve()
    config = (home / "config.toml").read_text(encoding="utf-8")
    assert "[features]" in config
    if sys.platform == "win32":
        assert 'sandbox = "unelevated"' in config
    assert sorted(p.name for p in home.iterdir()) == ["auth.json", "config.toml"]
    assert retest.checked_codex_home(str(home)) == home.resolve()      # a second start passes unchanged
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="overlaps"):
        retest.checked_codex_home(str(home))


@pytest.mark.parametrize("kind", ["context", "memory"])
def test_runner_entrypoint_refuses_codex_units_without_logged_in_home(tmp_path, kind):
    """Issue #320: no --codex-home (or one with no login) stops before any unit, never an empty home."""
    env = {"CCX_CODEX_BIN": str(ROOT / "tests/fakes/fake_codex.py")}
    base = ["execute", kind, "--run", "--budget", "0.01", "--reps", "1"]
    missing = invoke("strength_retest.py", [*base, "--out", str(tmp_path / "a")], tmp_path, env)
    assert missing.returncode == 2 and "--codex-home" in missing.stderr, missing.stderr
    no_login = tmp_path / "no-login"
    no_login.mkdir()
    refused = invoke("strength_retest.py", [*base, "--out", str(tmp_path / "b"), "--codex-home", str(no_login)],
                     tmp_path, env)
    assert refused.returncode == 2 and "no login" in refused.stderr, refused.stderr
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()
    assert list(no_login.iterdir()) == []       # checking wrote nothing into the home


def test_execute_needs_codex_home_only_for_codex_units(tmp_path):
    codex = {**retest.plan("memory", 1), "units": [{"task": "one", "agent": "codex"}], "n": 1}
    with mock.patch.object(runner, "run_unit") as run, pytest.raises(ValueError, match="codex-home"):
        runner.execute(codex, tmp_path / "codex", .05, .05)
    assert run.call_count == 0 and not (tmp_path / "codex").exists()
    with pytest.raises(ValueError, match="codex-home"):
        runner.run_unit({"task": "mem-errors", "agent": "codex"}, "memory", tmp_path / "unit", .05)
    dsh = {**retest.plan("context", 1), "units": [{"task": "one", "agent": "dsh"}], "n": 1}
    with mock.patch.object(runner, "run_unit", return_value={"ok": True, "usd": .01}) as run:
        report = runner.execute(dsh, tmp_path / "dsh", .05, .05)
    assert run.call_count == 1 and report["attempted"] == 1
    assert run.call_args.args[4] is None


def test_codex_unit_uses_the_given_home_and_dsh_unit_its_own(tmp_path, monkeypatch):
    monkeypatch.setenv("CCX_CODEX_BIN", str(ROOT / "tests/fakes/fake_codex.py"))
    monkeypatch.setenv("CCX_DSH_BIN", str(ROOT / "tests/fakes/fake_dsh.py"))
    monkeypatch.setenv("CCX_NO_LOCATE", "1")
    seen, real_run = [], runner.subprocess.run
    def spy(argv, *args, **kwargs):
        if "strength-retest" in argv:
            seen.append({k: kwargs["env"].get(k) for k in ("CODEX_HOME", "CODEX_SQLITE_HOME")})
        return real_run(argv, *args, **kwargs)
    monkeypatch.setattr(runner.subprocess, "run", spy)
    home = fake_codex_home(tmp_path)
    for agent in ("codex", "dsh"):
        model, effort = retest.MODELS[agent]
        unit = {"task": "t1-empty-mean", "arm": "off", "agent": agent, "model": model, "effort": effort, "rep": 1}
        row = runner.run_unit(unit, "context", tmp_path / agent, .1, home)
        assert "error" not in row, row
    assert seen[0] == {"CODEX_HOME": str(home), "CODEX_SQLITE_HOME": str(home)}
    own = str(tmp_path / "dsh" / "codex-home")
    assert seen[1] == {"CODEX_HOME": own, "CODEX_SQLITE_HOME": own}


def test_semantic_batch_stops_on_unknown_cost_before_second_call(tmp_path, capsys):
    from ccx.review_pipeline import validate
    result = {"contract": validate({"behaviors": []}, SOURCES), "model_calls": 1,
              "cost_usd": None, "budget_exceeded": False}
    with mock.patch.object(diag, "sources_for", return_value=SOURCES), \
         mock.patch("ccx.contract_semantic.generate_semantic", return_value=result) as run:
        rc = diag.main(["--evidence", str(tmp_path), "--run", "--generator", "claude", "--budget", "8",
                        "--out", str(tmp_path / "contracts")])
    report = json.loads(capsys.readouterr().out)
    assert rc == 2 and run.call_count == 1 and report["model_calls"] == 1
    assert report["spent_usd"] is None and report["charged_usd"] == .5
    assert report["known_spent_usd"] == 0 and len(report["rows"]) == 15


def test_retest_setup_error_preserves_attempt_and_reservation(tmp_path):
    manifest = {**retest.plan("memory", 1), "units": [{"task": "one"}, {"task": "two"}], "n": 2}
    with mock.patch.object(runner, "run_unit", side_effect=OSError("fixture setup failed")) as run:
        report = runner.execute(manifest, tmp_path / "out", .1, .05)
    assert run.call_count == 1 and report["budget_stopped"] and report["spent_usd"] is None
    assert report["rows"][0]["error"] == "OSError" and report["charged_usd"] == .05


@pytest.mark.parametrize("arm", ["off", "on"])
@pytest.mark.parametrize("agent", ["codex", "dsh"])
def test_context_manifest_units_use_isolated_transcript(tmp_path, monkeypatch, arm, agent):
    monkeypatch.setenv("CCX_CODEX_BIN", str(ROOT / "tests/fakes/fake_codex.py"))
    monkeypatch.setenv("CCX_DSH_BIN", str(ROOT / "tests/fakes/fake_dsh.py"))
    monkeypatch.setenv("CCX_NO_LOCATE", "1")
    monkeypatch.setenv("FAKE_WRITE", "calc.py=def average(xs):\n    return sum(xs) / len(xs) if xs else None\n")
    model, effort = retest.MODELS[agent]
    unit = {"task": "t1-empty-mean", "arm": arm, "agent": agent, "model": model, "effort": effort, "rep": 1}
    row = runner.run_unit(unit, "context", tmp_path / f"{agent}-{arm}", .1, fake_codex_home(tmp_path))
    assert "error" not in row, row
    # The existing dsh fixture emits usage/receipts but deliberately does not edit files.
    assert row["usd"] is not None and row["ok"] is (agent == "codex"), row
    assert row["note_in_prompt"] is (arm == "on")
