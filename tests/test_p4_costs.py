"""Cumulative Claude receipts: fake streams only, no provider calls."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/eval"))
import p4_long_session as P
from test_p4_long_session import fake_engine

COSTS = [.1229, .1755, .2583]
READS = [105337, 79423, 215807]


def receipt(turn, sid="session"):
    usage = dict.fromkeys(P.USAGE_COUNTERS, 0)
    usage["cache_read_input_tokens"] = READS[turn - 1]
    model = {v: 0 for v in P.USAGE_COUNTERS.values()}
    model["cacheReadInputTokens"] = sum(READS[:turn])
    return {"type": "result", "session_id": sid, "total_cost_usd": COSTS[turn - 1],
            "usage": usage, "modelUsage": {"fake": model}, "subtype": "success"}


def cumulative_engine(monkeypatch):
    original = P.r5.r3.last_result

    def result(out):
        fin = original(out)
        messages = list(P.PF._events(out))
        turn = messages[0]["message"]["usage"]["cache_read_input_tokens"] // 100
        return receipt(turn, fin["session_id"])

    monkeypatch.setattr(P.r5.r3, "last_result", result)


def self_units(tasks):
    return [u for u in P.schedule(tasks) if u["arm"] == "self"][:3]


def test_shared_fake_cli_emits_native_cumulative_protocol(fake_engine):
    a, tasks, _ = fake_engine
    assert P.run_experiment(a, tasks, P.schedule(tasks)) == 0
    rows = P.read_jsonl(a.out)
    for arm in P.ARMS:
        arm_rows = [r for r in rows if r["arm"] == arm]
        assert [r["lead_cumulative_usd"] for r in arm_rows] == [.1, .2, .3, .4]
        assert [r["lead_usd"] for r in arm_rows] == pytest.approx([.1] * 4)
        assert [r["lead_result_usage"]["cache_read_input_tokens"] for r in arm_rows] == [100, 200, 300, 400]
        assert [r["lead_model_usage"]["cache_read_input_tokens"] for r in arm_rows] == [100, 300, 600, 1000]
        assert all(r["cost_complete"] and r["cost_cumulative_check"] for r in arm_rows)
        assert sum(r["usd"] for r in arm_rows) == pytest.approx(.4)


def test_three_resumed_receipts_charge_only_deltas(fake_engine, monkeypatch):
    a, tasks, _ = fake_engine
    cumulative_engine(monkeypatch)
    assert P.run_experiment(a, tasks, self_units(tasks)) == 0
    rows = P.read_jsonl(a.out)
    assert [r["lead_cumulative_usd"] for r in rows] == COSTS
    assert [r["lead_usd"] for r in rows] == pytest.approx([.1229, .0526, .0828])
    assert sum(r["usd"] for r in rows) == pytest.approx(.2583)
    assert rows[-1]["episode_usd"] == .2583
    assert all(r["cost_cumulative_check"] and r["cost_complete"] for r in rows)
    assert P.read_jsonl(a.out.with_suffix(".events.jsonl"))[0]["spent_known_usd"] == pytest.approx(.2583)
    assert P.summary(rows, 4)["all"]["arms"]["self"]["cost_known_usd"] == .2583


@pytest.mark.parametrize("bad", ["backwards", "missing", "mismatch", "missing result"])
def test_bad_resume_is_unknown_retains_previous_and_stops(fake_engine, monkeypatch, bad):
    a, tasks, log = fake_engine
    cumulative_engine(monkeypatch)
    original = P.r5.r3.last_result

    def result(out):
        fin = original(out)
        if fin["total_cost_usd"] == COSTS[1]:
            if bad == "backwards":
                fin["total_cost_usd"] = .1
            elif bad == "missing":
                fin.pop("total_cost_usd")
            elif bad == "mismatch":
                fin["modelUsage"]["fake"]["cacheReadInputTokens"] += 1
            else:
                return {}
        return fin

    monkeypatch.setattr(P.r5.r3, "last_result", result)
    assert P.run_experiment(a, tasks, self_units(tasks)) == 2
    rows = P.read_jsonl(a.out)
    assert len(rows) == len(log.read_text(encoding="utf-8").splitlines()) == 2
    assert rows[-1]["lead_previous_cumulative_usd"] == .1229
    assert rows[-1]["lead_usd"] is None and rows[-1]["usd"] is None
    assert not rows[-1]["cost_complete"]
    if bad in ("mismatch", "missing result"):
        assert rows[-1]["cost_cumulative_check"] is False
    event, = P.read_jsonl(a.out.with_suffix(".events.jsonl"))
    assert event["cost_unknown"] and event["reason"] == "budget_unknown"
    assert event["spent_known_usd"] == pytest.approx(.1229)


@pytest.mark.parametrize("counter", list(P.USAGE_COUNTERS.values()))
def test_all_four_usage_counters_are_cross_checked(counter):
    state = P.LeadCost()
    fin = receipt(1)
    fin["modelUsage"]["fake"][counter] += 1
    row = state.observe(fin)
    assert row["cost_cumulative_check"] is False and row["lead_usd"] is None
    assert state.cumulative == 0 and state.failed


@pytest.mark.parametrize("field", ["usage", "modelUsage", "total_cost_usd"])
def test_missing_first_receipt_fields_are_unknown_and_poison_session(field):
    state = P.LeadCost()
    fin = receipt(1)
    fin.pop(field)
    assert state.observe(fin)["lead_usd"] is None
    assert state.observe(receipt(2))["lead_usd"] is None
    assert state.cumulative == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "0.1"])
def test_invalid_cumulative_values_are_unknown(value):
    fin = receipt(1)
    fin["total_cost_usd"] = value
    assert P.LeadCost().observe(fin)["lead_usd"] is None


@pytest.mark.parametrize("turn", [1, 2])
def test_interrupt_retains_last_valid_cumulative_and_stops(fake_engine, monkeypatch, turn):
    a, tasks, _ = fake_engine
    cumulative_engine(monkeypatch)
    run = P.PF.run
    calls = []

    def interrupt(*args, **kwargs):
        calls.append(1)
        if len(calls) == turn:
            raise KeyboardInterrupt
        return run(*args, **kwargs)

    monkeypatch.setattr(P.PF, "run", interrupt)
    assert P.run_experiment(a, tasks, self_units(tasks)) == 2
    rows = P.read_jsonl(a.out)
    assert len(rows) == turn
    assert rows[-1]["usd"] is None and not rows[-1]["cost_complete"]
    assert rows[-1]["lead_previous_cumulative_usd"] == (0 if turn == 1 else .1229)


def test_readonly_recompute_cli_outside_repo(tmp_path):
    source = tmp_path / "results.jsonl"
    artifacts = tmp_path / "artifacts"
    for arm in P.ARMS:
        for turn in range(1, 4):
            unit = f"{arm}-{turn}"
            stream = artifacts / unit / "streams" / "lead.jsonl"
            stream.parent.mkdir(parents=True)
            stream.write_text(json.dumps(receipt(turn, arm)) + "\n", encoding="utf-8")
            P.append_jsonl(source, {"tag": "replay", "round": 1, "episode": 1, "turn": turn,
                                  "task": f"task-{turn}", "arm": arm, "session_id": arm,
                                  "streams": {"dir": unit}, "cost_complete": True, "ok": True,
                                  "env_clean": True, "wall_s": 1, "lead_usd": COSTS[turn - 1],
                                  "usd": COSTS[turn - 1], "ccx_usd": 0})
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    run = subprocess.run([sys.executable, str(Path(P.__file__).resolve()), "--recompute", str(source),
                          "--artifacts-root", str(artifacts), "--tag", "replay"], cwd=tmp_path,
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["summary"]["all"]["ratios"]["cost"] == {
        "numerator": .2583, "denominator": .2583, "ratio": 1}
    assert result["summary"]["all"]["verdict"] == "Unknown"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert P.recompute_rows(result["rows"])[-1]["episode_usd"] == .2583
