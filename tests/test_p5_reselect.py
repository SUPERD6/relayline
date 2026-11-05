"""Cache-only reselection contract, independent of real repositories and models."""
import json
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts/eval"))
import p5_reselect as R


def test_fixed_pool_excludes_previous_eight_and_preserves_request_only_briefs(monkeypatch):
    old = [{"commit": f"{i:040x}"} for i in range(8)]
    def validate(cache, python, **kw):
        assert kw["repos"] == ("more-itertools", "boltons", "pluggy")
        assert {t["commit"] for t in old} <= kw["exclude"]
        assert kw["validator"] is R.validate
        return {"accepted": [{"subject": "Add public operation"}], "complete": False}
    monkeypatch.setattr(R.LC, "validate", validate)
    result = R.select(Path("unused"), "python", {"audited_tasks": old})
    assert result["accepted"][0]["brief"].endswith("Add public operation")
    assert result["models_called"] is False


def test_reference_full_failure_excludes_otherwise_valid_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(R.LE, "validate_task", lambda *a: {"valid": True})
    monkeypatch.setattr(R.LC, "material", lambda *a: {"reference": b"tree"})
    monkeypatch.setattr(R.LE, "build", lambda *a: None)
    monkeypatch.setattr(R.LE, "baseline", lambda *a: {"rc": 1})
    result = R.validate(tmp_path, "python", {"commit": "a"*40})
    assert result["reference_full"]["rc"] == 1
    assert result["valid"] is False


def test_failed_baseline_never_runs_reference_full(tmp_path, monkeypatch):
    monkeypatch.setattr(R.LE, "validate_task", lambda *a: {"valid": False})
    monkeypatch.setattr(R.LC, "material", lambda *a: (_ for _ in ()).throw(AssertionError()))
    result = R.validate(tmp_path, "python", {"commit": "a"*40})
    assert result["reference_full"]["rc"] is None


def test_reselection_cli_outside_repo_keeps_missing_cache_unknown(tmp_path):
    cache = tmp_path/"cache"
    cache.mkdir()
    previous = tmp_path/"previous.json"
    previous.write_text(json.dumps({"audited_tasks": [{"commit": "a"*40}]}), encoding="utf-8")
    output = tmp_path/"output.json"
    run = subprocess.run([sys.executable, str(Path(R.__file__).resolve()),
                          "--ext-cache", str(cache), "--ext-python", sys.executable,
                          "--previous", str(previous), "--output", str(output),
                          "--raw-dir", str(tmp_path/"raw")], cwd=tmp_path,
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 1, run.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["accepted"] == [] and result["shortfall"] == 8
    assert result["repository_order"] == list(R.REPOS)
    assert "a"*40 in result["excluded_commits"]
    assert list(cache.iterdir()) == []


def test_empty_three_arm_estimate_lists_all_requested_groups():
    import p4_long_session as P
    estimate = P.estimate([], ("self", "ccxlong", "ccxlongcheap"))
    assert estimate["by_arm"] == {"self": 0, "ccxlong": 0, "ccxlongcheap": 0}
