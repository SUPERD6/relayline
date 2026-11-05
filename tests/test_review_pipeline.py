"""Offline contract process and controller regressions, no real models."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest

from test_ccx import Env, ROOT
from ccx import review_pipeline as pipeline
from ccx.config import Paths, load_config

sys.path.insert(0, str(ROOT / "scripts/eval"))
import review_contract_diag as diagnostic


def example(expected="Returns integer 2", **overrides):
    return {"id": "value", "source": "task", "quote": "Return 2.",
            "expected": expected, "unknown": False, **overrides}


def test_worker_is_separate_source_free_and_does_not_execute_input(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("CONTRACT_SECRET", "must not inherit")
    original = subprocess.run
    seen = []

    def run(argv, **kw):
        seen.append((argv, kw))
        assert list(Path(kw["cwd"]).iterdir()) == []
        assert "PYTHONPATH" not in kw["env"] and "CONTRACT_SECRET" not in kw["env"]
        return original(argv, **kw)

    source = {"task": "Return 2. 中文行为。", "interface": "def value(): pass", "user_words": "Keep integers.",
              "implementation": "IMPLEMENTATION_SECRET", "hidden_tests": "HIDDEN_SECRET"}
    with mock.patch.object(pipeline.subprocess, "run", side_effect=run):
        contract = pipeline.generate(source)
    argv, kw = seen[0]
    assert "-I" in argv and "-S" in argv
    assert "IMPLEMENTATION_SECRET" not in kw["input"] and "HIDDEN_SECRET" not in kw["input"]
    assert "中文行为" in json.dumps(contract, ensure_ascii=False)
    assert all(row["unknown"] is True for row in contract["behaviors"])


@pytest.mark.parametrize("row", [example(source="implementation"), example(quote="Return 3."),
    example(unknown="false"), example(expected=""), example(id=""), example(source=[]),
    example(source="interface", quote="def value(): pass")])
def test_bad_citations_and_interface_assumptions_stay_unknown(row):
    result = pipeline.validate({"behaviors": [row]}, {"task": "Return 2.", "interface": "def value(): pass"})
    assert result["behaviors"][0]["unknown"] is True


def test_duplicate_ids_missing_original_limit_and_freeze(tmp_path):
    sources = {"task": "Return 2.", "user_words": "", "interface": ""}
    checked = pipeline.validate({"behaviors": [example(), example()]}, sources)
    assert checked["behaviors"][1]["unknown"] is True
    assert checked["behaviors"][0]["unknown"] is True
    assert "Missing user_words" in checked["unknown_reasons"]
    frozen = pipeline.freeze(checked, tmp_path / "contract.json")
    assert pipeline.verify(frozen)
    frozen["behaviors"][0]["expected"] = "changed"
    assert not pipeline.verify(frozen)
    with pytest.raises(FileExistsError):
        pipeline.freeze(checked, tmp_path / "contract.json")
    with mock.patch.object(pipeline.subprocess, "run") as run:
        over = pipeline.generate({"task": "z" * (pipeline.LIMIT + 1)})
    run.assert_not_called()
    assert "exceeds limit" in over["unknown_reasons"][0]


def test_conflicting_expectations_cannot_depend_on_arrival_order():
    rows = [example(id="one"), example(id="two", expected="Returns a string")]
    for order in (rows, list(reversed(rows))):
        checked = pipeline.validate({"behaviors": order}, {"task": "Return 2."})
        assert all(row["unknown"] is True for row in checked["behaviors"])


def test_attach_preserves_truncation_notice_and_tampering_is_unknown(tmp_path):
    from ccx.delegate import Request
    sources = ("original truncated", "Return 2.")
    with mock.patch("ccx.review_task.inputs", return_value=("[User's original words truncated at 18 characters.]", sources)), \
         mock.patch("ccx.review_contract.before_change", return_value="def value(): pass"):
        record = {}
        pipeline.attach(Paths(tmp_path), Request(to="codex", brief="task"), record, tmp_path, tmp_path)
        assert "Saved original words were truncated" in record["contract_diagnostic"]["unknown_reasons"]
        path = tmp_path / "review-contract.json"
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["sources"]["task"] = "modified frozen data"
        path.write_text(json.dumps(saved), encoding="utf-8")
        pipeline.attach(Paths(tmp_path), Request(to="codex", brief="task"), record, tmp_path, tmp_path)
        assert "Contract unavailable" in record["contract_diagnostic"]["unknown_reasons"][0]
        assert "modified frozen data" in path.read_text(encoding="utf-8")


def test_independent_evidence_is_scoped_and_read_review_cannot_upgrade_self_check():
    record = {"check": {"passed": True, "covers": {"files": ["test_own.py"], "self_authored": True}},
              "review": {"verdict": "pass", "self_checked": True}}
    assert pipeline.evidence(record)["evidence_level"] == "self_checked"
    record["check"]["covers"] = {"files": ["test_existing.py"]}
    assert pipeline.evidence(record)["evidence_level"] == "independent_verified"
    record["check"]["unchanged_tree"] = True
    assert pipeline.evidence(record)["evidence_level"] == "unverified"
    record["check"]["unchanged_tree"] = False
    record["check"]["covers"]["partial"] = True
    assert pipeline.evidence(record)["evidence_level"] == "unverified"
    assert pipeline.evidence(record)["covered_ids"] == []


def test_hidden_table_checks_expectation_not_just_keyword_and_unknown_denominator(tmp_path):
    hidden = tmp_path / "hidden.txt"
    hidden.write_text("test_integer: expected integer 2, got wrong value", encoding="utf-8")
    rule = {"hidden_test": "test_integer", "hidden_artifact": "hidden.txt", "confirmed": True,
            "sha256": hashlib.sha256(hidden.read_bytes()).hexdigest(),
            "requirements": [{"source": "task", "quote": "Return 2.", "expected_contains": ["integer", "2"]}]}
    sources = {"task": "Return 2.", "user_words": "Original task", "interface": "def value(): pass"}
    contract = pipeline.validate({"behaviors": [example()]}, sources)
    assert diagnostic.score(contract, [rule], tmp_path)["coverage"] == "Pass"
    contract["behaviors"][0]["expected"] = "Returns string 2"
    assert diagnostic.score(contract, [rule], tmp_path)["coverage"] == "Fail"
    contract["behaviors"][0]["unknown"] = True
    assert diagnostic.score(contract, [rule], tmp_path)["coverage"] == "Unknown"
    rule["sha256"] = "incorrect"
    assert diagnostic.score(contract, [rule], tmp_path)["coverage"] == "Unknown"
    assert diagnostic.score(contract, [], tmp_path)["coverage"] == "Unknown"
    assert diagnostic.score(contract, ["invalid rule"], tmp_path)["coverage"] == "Unknown"


def test_script_from_outside_repo_retains_all_missing_units_and_blocks_budget(tmp_path):
    script = ROOT / "scripts/eval/review_contract_diag.py"
    args = [sys.executable, "-X", "utf8", str(script), "--evidence", str(tmp_path / "missing")]
    dry = subprocess.run(args + ["--dry-run"], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert dry.returncode == 0, dry.stderr
    report = json.loads(dry.stdout)
    assert (report["denominator"], report["unknown"], report["model_calls"], report["spent_usd"]) == (15, 15, 0, 0)
    assert report["reservation_usd"] == 7.5 and report["expected_model_cost"] == "Unknown"
    out = tmp_path / "result"
    generated = subprocess.run(args + ["--generate", "--out", str(out)], cwd=tmp_path, capture_output=True,
                               text=True, encoding="utf-8")
    assert generated.returncode == 0, generated.stderr
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["unknown"] == 15
    for option in (["--budget", "9"], ["--budget", "nan"], ["--unit-reservation", "1"]):
        bad = subprocess.run(args + option, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
        assert bad.returncode == 2


class TestContractWiring(Env):
    def test_default_off_and_explicit_diagnostic_preserves_test_review_verdict(self):
        assert load_config(Paths(self.hub))["review"]["contract_diag"] is False
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=self.work, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "initial"],
                       cwd=self.work, check=True, capture_output=True)
        tiers = Paths(self.hub).user_tiers
        tiers.parent.mkdir(parents=True, exist_ok=True)
        tiers.write_text('[review]\nmode = "tests"\ncontract_diag = true\nfix_rounds = 0\n', encoding="utf-8")
        raw = self.hub / "task.txt"
        raw.write_text("change x to 2 in a.py", encoding="utf-8")
        result = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                          "--review", "on", "--no-fallback", "--no-escalate", "--user-task-file", str(raw),
                          "worker instruction", env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 4\n"})
        assert result.returncode == 2, result.stdout + result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["review"]["verdict"] == "issues"
        assert receipt["evidence_level"] == "independent_verified"
        frozen = json.loads((Paths(self.hub).runs / receipt["run_id"] / "review-contract.json").read_text(encoding="utf-8"))
        assert pipeline.verify(frozen)
        assert frozen["sources"]["task"] == "change x to 2 in a.py"
        assert "x = 1" in frozen["sources"]["interface"]
        assert "x = 4" not in json.dumps(frozen)
