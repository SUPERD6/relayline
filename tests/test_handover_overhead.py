"""Synthetic rows and lead streams only: no CLI, no model, no network (#378)."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import handover_overhead as H


def usage(inp=0, cw=0, cr=0, out=0):
    return {"input_tokens": inp, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr,
            "output_tokens": out}


def asst(mid, t, u, command=None, tid=None):
    content = [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}] if command else \
        [{"type": "text", "text": "x"}]
    return {"type": "assistant", "timestamp": t, "message": {"id": mid, "usage": u, "content": content}}


def result(t, tid):
    return {"type": "user", "timestamp": t, "message": {"content": [{"type": "tool_result", "tool_use_id": tid}]}}


def write_stream(root, name, events, run="r1"):
    d = root / run / name / "streams"
    d.mkdir(parents=True)
    raw = "".join(json.dumps(e) + "\n" for e in events).encode()
    (d / "lead.jsonl").write_bytes(raw)
    return {"dir": name, "path": "streams", "files": [{"file": "lead.jsonl", "sha256": hashlib.sha256(raw).hexdigest()}]}


def row(streams=None, **kw):
    base = {"task": "t1", "arm": "ccxlong", "round": 1, "episode": 1, "lead_usd": 1.0, "ccx_usd": 0.5,
            "ccx_review_usd": 0.1, "side_cost_status": "Pass", "unknown_side_usd": 0.0, "episode_wall_s": 300.0,
            "side_ledger": [{"run_id": "a", "label": "", "rungs": ["codex:m:medium"], "ae_usd": 0.5},
                            {"run_id": "b", "label": "review:a", "rungs": ["claude:haiku:low"], "ae_usd": 0.1}]}
    if streams:
        base["streams"] = streams
    return {**base, **kw}


def full_events():
    # m1 delegates (call 100 s), m2 reads the result and delegates again (call 50 s), m3 final answer
    return [
        {"type": "system", "subtype": "init"},
        asst("m1", "2026-11-11T10:00:10Z", usage(out=100), "ccx run --to codex", "t1"),
        result("2026-11-11T10:01:50Z", "t1"),
        asst("m2", "2026-11-11T10:01:55Z", usage(out=100), 'python "x/p4_receipt.py" resume abc', "t2"),
        result("2026-11-11T10:02:45Z", "t2"),
        asst("m3", "2026-11-11T10:02:50Z", usage(out=200)),
    ]


def test_complete_unit_splits_cost_and_wall(tmp_path):
    s = write_stream(tmp_path, "u1", full_events())
    led = [{"run_id": "a", "seconds": 120.0}, {"run_id": "b", "seconds": 20.0}]
    res = H.analyze([row(s)], tmp_path, led)
    u = res["per_unit"][0]
    assert u["delegations"] == 2 and u["attempts"] == 1 and u["reviews"] == 1
    # lead cost allocated over weight 500 + 500 + 1000: brief = 0.5, post = 0.5
    assert u["cost"]["brief"]["value"] == pytest.approx(0.5)
    assert u["cost"]["agent"]["value"] == pytest.approx(0.5)
    assert u["cost"]["check_review"]["value"] == pytest.approx(0.1 + 0.5)
    assert u["cost"]["startup"]["value"] is None and "launch-to-first-event" in u["cost"]["startup"]["unknown"]
    assert u["wall"]["call"]["value"] == pytest.approx(150.0)
    assert u["wall"]["agent"]["value"] == 120.0
    assert u["wall"]["startup_check_review_combined"]["value"] == pytest.approx(30.0)
    # first message has no earlier timestamp: only m2's 5 s gap (m1 -> its result) is known
    assert u["wall"]["brief"]["value"] is None and u["wall"]["brief"]["gaps_s"] == [5.0]
    assert u["wall"]["brief"]["delegations"] == {"known": 1, "unknown": 1}
    s = res["all"]["cost"]["_shares"]
    assert s["left_out_unknown"] == ["startup"]
    assert sum(s["share"].values()) == pytest.approx(1.0)
    assert res["all"]["wall"]["brief_per_delegation_known"]["median"] == 5.0


def test_missing_fields_are_unknown_with_a_reason(tmp_path):
    r = row(side_ledger=[], ccx_run_ids=["a"], side_cost_status="Unknown")
    res = H.analyze([r], None)
    u = res["per_unit"][0]
    assert u["cost"]["agent"]["value"] is None and "known cost" in u["cost"]["agent"]["unknown"]
    assert u["cost"]["brief"]["unknown"] == "no --artifacts directory given"
    assert u["wall"]["call"]["value"] is None and u["wall"]["agent"]["unknown"].startswith("no ledger")
    assert res["all"]["cost"]["agent"]["unknown_units"] == 1
    # no lead_usd either
    r2 = row(lead_usd=None)
    assert H.analyze([r2], None)["per_unit"][0]["cost"]["brief"]["unknown"] == "row has no lead_usd"


def test_missing_stream_file_and_hash_mismatch(tmp_path):
    s = {"dir": "nope", "path": "streams", "files": []}
    assert H.analyze([row(s)], tmp_path)["per_unit"][0]["cost"]["brief"]["unknown"] == "lead stream file missing"
    good = write_stream(tmp_path, "u1", full_events())
    good["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        H.analyze([row(good)], tmp_path)


def test_self_arm_without_delegation_is_skipped(tmp_path):
    r = {"task": "t", "arm": "self", "lead_usd": 0.4, "wall_s": 10.0}
    res = H.analyze([r, row()], None)
    assert res["units"] == 1 and res["skipped_no_delegation"] == 1 and list(res["by_arm"]) == ["ccxlong"]


def test_escalation_and_several_attempts(tmp_path):
    # two non-review runs (first rung failed, second rung ran), one review: agent cost sums both, reviews separate
    ev = [asst("m1", "2026-11-11T10:00:10Z", usage(out=10), "ccx run --to codex", "t1"),
          result("2026-11-11T10:05:10Z", "t1"),
          asst("m2", "2026-11-11T10:05:20Z", usage(out=10))]
    s = write_stream(tmp_path, "u1", ev)
    r = row(s, side_ledger=[
        {"run_id": "a", "label": "", "rungs": ["codex:a:low", "codex:a:high"], "ae_usd": 0.3},
        {"run_id": "c", "label": "", "rungs": ["codex:b:high"], "ae_usd": 0.2},
        {"run_id": "b", "label": "review:c", "rungs": ["claude:haiku:low"], "ae_usd": 0.05}])
    led = [{"run_id": "a", "seconds": 100.0}, {"run_id": "c", "seconds": 150.0}, {"run_id": "b", "seconds": 9.0}]
    u = H.analyze([r], tmp_path, led)["per_unit"][0]
    assert u["attempts"] == 2 and u["reviews"] == 1
    assert u["cost"]["agent"]["value"] == pytest.approx(0.5)
    assert u["wall"]["agent"]["value"] == 250.0
    assert u["wall"]["call"]["value"] == pytest.approx(300.0)
    assert u["wall"]["startup_check_review_combined"]["value"] == pytest.approx(50.0)
    # a run missing from the ledger makes the agent wall Unknown, not a partial sum
    u = H.analyze([r], tmp_path, led[:1])["per_unit"][0]
    assert u["wall"]["agent"]["value"] is None and "missing from the ledger" in u["wall"]["agent"]["unknown"]


def test_medians_per_arm_over_units(tmp_path):
    rows = [row(ccx_usd=x, side_ledger=[{"run_id": "a", "label": "", "rungs": [], "ae_usd": x}], arm="A")
            for x in (0.1, 0.3, 0.9)]
    res = H.analyze(rows, None)
    assert res["by_arm"]["A"]["cost"]["agent"]["median"] == pytest.approx(0.3)
    assert res["by_arm"]["A"]["cost"]["agent"]["n"] == 3


def test_one_known_item_gives_no_share():
    # no stream: only agent is known for every unit -> would be 100%; no share is printed
    res = H.analyze([row()], None)
    sh = res["all"]["cost"]["_shares"]
    assert sh["over"] == ["agent"] and sh["share"]["agent"] is None and "fewer than two" in sh["note"]


def test_review_and_lead_parts_kept_apart(tmp_path):
    s = write_stream(tmp_path, "u1", full_events())
    u = H.analyze([row(s)], tmp_path)["per_unit"][0]
    assert u["cost"]["check_review_review"]["value"] == pytest.approx(0.1)
    assert u["cost"]["check_review_lead_allocated"]["value"] == pytest.approx(0.5)


def test_weights_change_allocation_and_are_recorded(tmp_path):
    ev = [asst("m1", "2026-11-11T10:00:10Z", usage(out=100), "ccx run x", "t1"),
          result("2026-11-11T10:01:00Z", "t1"),
          asst("m2", "2026-11-11T10:01:05Z", usage(cr=1000))]
    s = write_stream(tmp_path, "u1", ev)
    default = H.analyze([row(s)], tmp_path)
    assert default["allocation_weights"]["output"] == 5.0
    w = H.parse_weights("input=1,cache_write=1,cache_read=1,output=1")
    res = H.analyze([row(s)], tmp_path, weights=w)
    assert res["allocation_weights"] == {"input": 1.0, "cache_write": 1.0, "cache_read": 1.0, "output": 1.0}
    assert default["per_unit"][0]["cost"]["brief"]["value"] == pytest.approx(500 / 600)      # 500 vs 100
    assert res["per_unit"][0]["cost"]["brief"]["value"] == pytest.approx(100 / 1100)         # 100 vs 1000
    with pytest.raises(ValueError):
        H.parse_weights("input=1")


def test_parallel_calls_count_once_and_powershell_is_seen(tmp_path):
    ev = [{"type": "assistant", "timestamp": "2026-11-11T10:00:10Z", "message": {"id": "m1", "usage": usage(out=10),
           "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ccx run a"}},
                       {"type": "tool_use", "id": "t2", "name": "PowerShell", "input": {"command": "ccx run b"}}]}},
          result("2026-11-11T10:01:10Z", "t1"), result("2026-11-11T10:01:40Z", "t2")]
    s = write_stream(tmp_path, "u1", ev)
    u = H.analyze([row(s)], tmp_path)["per_unit"][0]
    assert u["delegations"] == 2
    assert u["wall"]["call"]["value"] == pytest.approx(90.0)     # union, not 60 + 90


def test_labels_say_allocated(tmp_path):
    s = write_stream(tmp_path, "u1", full_events())
    text = H.report(H.analyze([row(s)], tmp_path))
    assert "assumed token-kind ratios" in text and "brief (allocated)" in text
    assert "check_review (part allocated)" in text and "output=5" in text


def test_cli_prints_unknown_and_writes_json(tmp_path):
    s = write_stream(tmp_path, "u1", full_events())
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps(row(s)) + "\n", encoding="utf-8", newline="")
    out = tmp_path / "o.json"
    p = subprocess.run([sys.executable, str(EVAL / "handover_overhead.py"), "--results", str(rows),
                        "--artifacts", str(tmp_path), "--out", str(out)], cwd=tmp_path, capture_output=True,
                       text=True, encoding="utf-8", env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=30)
    assert p.returncode == 0, p.stderr
    assert "Unknown" in p.stdout and "brief" in p.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["units"] == 1
