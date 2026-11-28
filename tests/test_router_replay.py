"""Router replay and oracle bound (#544): synthetic rows only, no CLI, no evaluation execution."""
import json
from pathlib import Path
import subprocess
import sys

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import router_replay as R

D = "ccxcheapfirst2"


def row(task, arm, ok, usd, wall=10.0, ctx=1000, **kw):
    return {"task": task, "arm": arm, "ok": ok, "usd": usd, "wall_s": wall, "context_first": ctx, **kw}


def pair(task, s_ok, s_usd, d_ok, d_usd, ctx=1000):
    return [row(task, "self", s_ok, s_usd, ctx=ctx), row(task, D, d_ok, d_usd, wall=30.0, ctx=ctx)]


def many(n=12):
    out = []
    for i in range(n):
        # even tasks: delegate is cheaper and as right; odd: delegate wrong
        out += pair(f"t{i}", True, 1.0, i % 2 == 0, 0.5 if i % 2 == 0 else 0.4, ctx=100 * i)
    return out


def test_oracle_picks_better_per_task_and_bounds_every_rule():
    rep = R.replay(many(), D)
    r = rep["rules"]
    assert r["always_self"]["correct"] == 12 and r["always_self"]["usd"] == 12.0
    assert r["always_delegate"]["correct"] == 6
    assert r["oracle"]["correct"] == 12 and r["oracle"]["usd"] == 6 * 0.5 + 6 * 1.0
    assert rep["oracle_picks_delegate"] == 6
    for name, s in r.items():
        assert (-s["correct"], s["usd"]) >= (-r["oracle"]["correct"], r["oracle"]["usd"]), name
    assert "headroom" in rep["verdict"]


def test_low_ceiling_says_not_worth_routing():
    rows = []
    for i in range(12):
        rows += pair(f"t{i}", True, 1.0, True, 1.2)  # delegate never better
    rep = R.replay(rows, D)
    assert rep["rules"]["oracle"] == rep["rules"]["always_self"]
    assert "not worth routing" in rep["verdict"]


def test_threshold_is_tuned_on_the_other_half_only():
    rows = many(20)
    tasks, _ = R.pair_tasks(rows, D, "context_first")
    rule = R.threshold_rule(tasks, "ge")
    assert rule["n"] == 20
    assert len(rule["thresholds_tuned_on_other_half"]) == 2
    # a scored half never saw its own tasks: tuning on a half ignores the other half's rows entirely
    h0 = [t for t in tasks if R.half_of(t["task"]) == 0]
    h1 = [t for t in tasks if R.half_of(t["task"]) == 1]
    flipped = [dict(t, delegate=dict(t["delegate"], ok=0.0)) for t in h0]
    assert R.tune_threshold(h1, "ge")[0] == R.tune_threshold(h1, "ge")[0]
    assert R.score(flipped, lambda r: "delegate")["correct"] == 0.0
    assert R.threshold_rule(h1 + h0, "ge")["thresholds_tuned_on_other_half"][0] == \
        R.threshold_rule(h1 + flipped, "ge")["thresholds_tuned_on_other_half"][0]


def test_invalid_rows_dropped_unless_included_and_missing_feature_means_self():
    rows = pair("a", True, 1.0, False, 0.5)
    rows[1]["receipt_error"] = True
    rows += [row("b", "self", True, 1.0, ctx=None), row("b", D, True, 0.5, ctx=None)]
    rows += [row("c", "self", None, 1.0), row("c", D, True, 0.5)]  # unknown ok -> dropped
    tasks, info = R.pair_tasks(rows, D, "context_first")
    assert [t["task"] for t in tasks] == ["b"] and info["tasks_dropped"] == 2
    tasks2, _ = R.pair_tasks(rows, D, "context_first", include_invalid=True)
    assert [t["task"] for t in tasks2] == ["a", "b"]
    assert tasks[0]["feature"] is None
    assert R.threshold_rule(tasks, "ge")["delegated"] == 0


def test_repeats_are_averaged_and_empty_is_unknown():
    rows = [row("a", "self", True, 1.0), row("a", "self", False, 3.0), row("a", D, True, 1.0)]
    tasks, _ = R.pair_tasks(rows, D, "context_first")
    assert tasks[0]["self"]["ok"] == 0.5 and tasks[0]["self"]["usd"] == 2.0
    assert R.replay([], D)["verdict"].startswith("Unknown")


def test_small_n_is_flagged_and_output_is_reproducible(tmp_path):
    f = tmp_path / "rows.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in many(4)), encoding="utf-8")
    outs = [subprocess.run([sys.executable, str(EVAL / "router_replay.py"), str(f), "--json", "--label", "x"],
                           capture_output=True, text=True, check=True).stdout for _ in range(2)]
    assert outs[0] == outs[1]
    rep = json.loads(outs[0])
    assert rep["label"] == "x" and "too few" in rep["verdict"]
    text = subprocess.run([sys.executable, str(EVAL / "router_replay.py"), str(f)], capture_output=True,
                          text=True, check=True).stdout
    assert "oracle" in text and "always_self" in text
