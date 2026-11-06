"""Offline strength tools: no real agent CLI or personal hub access."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import ledger_reconcile as ledger
import model_fit_board as fit
import strength_retest as retest


def test_plans_keep_old_tasks_and_add_startup_path():
    context = retest.plan("context")
    assert context["n"] == 84 and context["cap_usd"] == 4
    assert {r["scenario"] for r in context["units"]} == {"neutral", "favourable"}
    memory = retest.plan("memory")
    assert memory["tasks"] == 6 and memory["n"] == 72 and memory["cap_usd"] == 3
    assert set(memory["arms"]) == {"nomem", "mem", "hubmem", "hubstart"}
    assert len({r["task"] for r in memory["units"]}) == 6
    assert memory["within_estimated_cap"] and memory["dry_run"]
    assert retest.plan("memory", unit_usd=1)["within_estimated_cap"] is False
    with pytest.raises(ValueError):
        retest.plan("memory", unit_usd=float("nan"))


def test_board_counts_failures_and_unknown_and_clean_scope():
    records = [{"task_type": "code", "model": "m", "ok": True, "usd": 1, "env_clean": True},
               {"task_type": "code", "model": "m", "ok": False, "usd": 2, "env_clean": False}]
    result = fit.board(records)
    assert result[0]["n"] == 2 and result[0]["pass_rate"] == .5
    assert result[0]["usd_per_success"] == 3 and result[0]["sample_note"] == "样本少"
    assert result[1]["n"] == 1 and result[1]["usd_per_success"] == 1
    unknown = fit.board([{"model": "m", "ok": None, "usd": None}])[0]
    assert unknown["pass_rate"] is None and unknown["usd_per_success"] is None
    assert unknown["task_type"] == "Unknown"
    zero = fit.board([{"ok": False, "usd": 3}])[0]
    assert zero["known_total_usd"] == 3 and zero["usd_per_success"] is None


def test_board_fallback_models_and_cost_completeness():
    row = {"rungs": ["codex:m1:low", "claude:m2:low"], "ok": True,
           "sub_ae_usd": 1, "review_ae_usd": 2, "lead": {"cost_usd": 3}}
    report = fit.board([row])[0]
    assert report["model"] == "m1+m2" and report["usd_per_success"] == 6
    row["lead"] = {"cost_usd": None}
    assert fit.board([row])[0]["usd_per_success"] is None


def sample_run():
    usage = {k: i for i, k in enumerate(ledger.BUCKETS)}
    attempts = [{"agent": "codex", "model": "m1", "usage": usage, "ae_usd": 1, "cost_usd": 5},
                {"agent": "dsh", "rung": "dsh:m2:low", "usage": usage, "ae_usd": 2, "cost_usd": 7}]
    record = {"run_id": "r", "to": "codex", "attempts": attempts}
    slim = {"run_id": "r", "usage4": {k: 2*v for k, v in usage.items()}, "ae_usd": 3, "cost_usd": 12}
    slim["ae_by_agent"] = {"codex": 1, "dsh": 2}
    reports = [{"run_id": "r", "attempt": i, "vendor": maker, "model": name,
                "usage": usage, "cost_usd": bill} for i, maker, name, bill in
               [(0, "openai", "m1", 5), (1, "deepseek", "m2", 7)]]
    return record, slim, reports


def test_ledger_multi_vendor_and_independent_price_rulers():
    record, slim, reports = sample_run()
    report = ledger.reconcile([record], [slim], reports)
    assert report["counts"]["Pass"] == 1
    assert [a["vendor"] for a in report["runs"][0]["attempts"]] == ["openai", "deepseek"]
    reports[1]["usage"] = {**reports[1]["usage"], "output_tokens": 99}
    assert ledger.reconcile([record], [slim], reports)["counts"]["Fail"] == 1


def test_ledger_missing_duplicate_and_unknown_are_not_zero():
    record, slim, reports = sample_run()
    assert ledger.reconcile([record], [slim], [])["counts"]["Unknown"] == 1
    assert ledger.reconcile([record], [slim, slim], reports)["counts"]["Fail"] == 1
    assert ledger.reconcile([record], [slim], reports + [reports[0]])["counts"]["Fail"] == 1
    record["attempts"][0]["ae_usd"] = None
    assert ledger.reconcile([record], [slim], reports)["runs"][0]["ledger_cost_checks"]["ae_usd"] == "Unknown"


def test_raw_streams_fresh_input_and_missing_scope(tmp_path):
    path = tmp_path / "events.log"
    path.write_text(json.dumps({"type": "turn.completed", "usage": {
        "input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 3}}), encoding="utf-8")
    item = {"run_id": "r", "attempt": 0, "cli": "codex", "path": path.name, "usage_scope": "attempt"}
    report = ledger.stream_reports([item], tmp_path)[0]
    assert report["usage"]["input_tokens"] == 60
    assert report["usage"]["cached_input_tokens"] == 40
    assert report["model"] is None and report["cost_usd"] is None
    del item["usage_scope"]
    assert ledger.stream_reports([item], tmp_path)[0]["usage"] == {}


def test_raw_claude_and_dsh_streams(tmp_path):
    claude = {"type": "result", "total_cost_usd": .04, "modelUsage": {
        "claude-native": {"inputTokens": 7, "cacheCreationInputTokens": 3,
                          "cacheReadInputTokens": 9, "outputTokens": 4}}}
    dsh = {"type": "status", "phase": "step_end", "usage": {
        "inputTokens": 2, "cacheWriteTokens": 3, "cacheReadTokens": 5, "outputTokens": 7}}
    for name, native in [("claude", claude), ("dsh", dsh)]:
        (tmp_path / name).write_text(json.dumps(native), encoding="utf-8")
        observed = ledger.stream_reports([{"run_id": "r", "attempt": 0, "cli": name,
                                          "path": name, "usage_scope": "attempt"}], tmp_path)[0]
        assert observed["usage"]["output_tokens"] == (4 if name == "claude" else 7)
        assert observed["cost_usd"] == (.04 if name == "claude" else None)


def test_ledger_agent_allocation_cannot_pass_only_by_matching_total():
    record, slim, reports = sample_run()
    slim["ae_by_agent"] = {"codex": 2, "dsh": 1}
    assert ledger.reconcile([record], [slim], reports)["counts"]["Fail"] == 1


def test_single_jsonl_row_and_absent_lead_cost(tmp_path):
    from result_rows import rows
    path = tmp_path / "single.jsonl"
    path.write_text('{"run_id":"single"}\n', encoding="utf-8")
    assert rows(path) == [{"run_id": "single"}]
    assert fit.board([{"ok": True, "sub_ae_usd": 1, "review_ae_usd": 0}])[0]["usd_per_success"] is None


def invoke(script, args, tmp_path):
    env = {**os.environ, "CCX_NO_LOCATE": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(EVAL / script), *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=45)


def test_entrypoints_from_outside_repository(tmp_path):
    planned = invoke("strength_retest.py", ["plan", "context", "--dry-run"], tmp_path)
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["n"] == 84
    record, slim, reports = sample_run()
    for name, data in [("run", record), ("ledger", [slim]), ("reports", reports),
                       ("scored", [{"task_type": "code", "model": "m", "ok": True, "usd": 1}])]:
        (tmp_path / (name + ".json")).write_text(json.dumps(data), encoding="utf-8")
    checked = invoke("ledger_reconcile.py", ["--run", "run.json", "--ledger", "ledger.json",
                                            "--cli-reports", "reports.json"], tmp_path)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["counts"]["Pass"] == 1
    ranked = invoke("model_fit_board.py", ["--results", "scored.json"], tmp_path)
    assert ranked.returncode == 0, ranked.stderr
    assert json.loads(ranked.stdout)["groups"][0]["n"] == 1


def test_startup_hook_command_with_synthetic_hub(tmp_path):
    hub = tmp_path / "hub"
    (hub / "ccx").mkdir(parents=True)
    config = tmp_path / "isolated.toml"
    config.write_text("", encoding="utf-8")
    env = retest.lead_env()
    env.update(CCX_HUB=str(hub), CCX_CONFIG=str(config), CCX_NO_QUOTA_PROBE="1")
    note = "Convention: probe-only memory has violet backups."
    added = subprocess.run([sys.executable, str(retest.ROOT / "ccx.py"), "mem", "add", "--by", "claude", note],
                           cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert added.returncode == 0, added.stderr
    probe = invoke("strength_retest.py", ["probe-hook", "--hub", str(hub), "--cwd", str(tmp_path)], tmp_path)
    assert probe.returncode == 0, probe.stderr
    data = json.loads(probe.stdout)
    assert note in data["payload"] and data["native_hook_execution"] == "Unknown"
