"""scripts/eval/b3_arms.py (B3 "fewer runs" arms) without real CLIs: the schedule, the hub's one switch, the m4 plan,
the m5 transcripts, the registered rule, and one unit of each experiment end to end on tests/fakes/fake_codex.py."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "eval"))

import b3_arms as B  # noqa: E402

FAKES = Path(__file__).resolve().parent / "fakes"


def test_schedule_runs_both_arms_of_a_pair_back_to_back_and_balances_who_goes_first():
    us = B.schedule(["m4", "m3", "m5"], B.REPS, B.TASKS)
    assert sum(u["exp"] == "m4" for u in us) == 4 * 2 * 2 and sum(u["exp"] == "m3" for u in us) == 6 * 1 * 2
    assert sum(u["exp"] == "m5" for u in us) == 8 * 2 * 2
    for i in range(0, len(us), 2):
        a, b = us[i], us[i + 1]
        assert (a["exp"], a["task"], a["rep"]) == (b["exp"], b["task"], b["rep"])
        assert {a["arm"], b["arm"]} == set(B.EXPS[a["exp"]])
    firsts = [u["arm"] for u in us[::2] if u["exp"] == "m5"]
    assert firsts.count("keep") == firsts.count("dedupe")
    assert len({B.unit_key(u) for u in us}) == len(us)


@pytest.mark.parametrize("exp,arm,want", [("m4", "batch", False), ("m4", "merge", False), ("m3", "all", "all"),
                                          ("m3", "none", "none"), ("m5", "keep", False), ("m5", "dedupe", True)])
def test_the_hub_writes_the_switch_for_both_arms_and_ccx_reads_it_back(tmp_path, exp, arm, want):
    info = B.make_hub(tmp_path / "hub", exp, arm)
    assert info["switch"] == want and info["archive"] == "off"
    other = [x for x in B.EXPS[exp] if x != arm][0]
    # both arms' hub files differ only in the switch's value line
    diff = set(B.hub_toml(exp, arm).splitlines()) ^ set(B.hub_toml(exp, other).splitlines())
    assert len(diff) == (0 if exp == "m4" else 2)


def test_a_switch_ccx_does_not_resolve_stops_the_unit(tmp_path, monkeypatch):
    monkeypatch.setitem(B.SWITCH, "m3", ("subagents", "fork_turns", {"all": "all", "none": "None please"}))
    with pytest.raises(RuntimeError, match="resolves"):
        B.make_hub(tmp_path / "hub", "m3", "none")


def test_m4_plan_pieces_fit_one_merge_group_and_both_arms_run_the_same_plan(tmp_path):
    from ccx import merge
    for pid in B.M4_PLANS:
        mat, pieces = B.m4_material(pid)
        assert [p["kind"] for p in pieces] == ["piece"] * 4 + ["trap"]
        paths = [x for p in pieces for x in p["paths"]]
        assert len(paths) == len(set(paths))                                   # declared paths never overlap
        assert all(p["minutes"] <= merge.DEFAULTS["piece_minutes"] for p in pieces)
        assert sum(p["minutes"] for p in pieces) <= merge.DEFAULTS["total_minutes"]
        assert len(pieces) <= merge.DEFAULTS["max_pieces"]
        assert all(x in mat["files"] or x == "test_task.py" or x.startswith("tests/test_") for x in paths)
        plan = B.m4_plan(pieces, tmp_path, B.MODEL["m4"])
        assert all(t["id"].startswith("eval-") and t["to"] == "codex" and t["mode"] == "write" for t in plan["tasks"])
        assert all("paths" in t and "minutes" in t and t["check"] for t in plan["tasks"])
        assert "worktree" not in json.dumps(plan)                             # ccx decides, the same for both arms


def test_m5_dedupe_drops_the_persons_repeat_and_keeps_the_leads_restatement(tmp_path):
    from ccx import context_share as cs
    for tid, task in B.M5_TASKS.items():
        f = tmp_path / f"{tid}.jsonl"
        f.write_text("".join(json.dumps(e) + "\n" for e in B.m5_transcript(task, time.time())), encoding="utf-8")
        evs = cs.drop_lead_only(cs.read_events("claude", f) or [], [])
        st: dict = {}
        on = cs.summary(evs, "claude", "s", tmp_path, "x", dedupe=True, stats=st)
        off = cs.summary(evs, "claude", "s", tmp_path, "x")
        assert len(on) <= len(off)
        if tid == "t8-reopened":
            assert st["deduped"] == 1 and "we keep MAX_RETRIES at 3" in on
            settled = on.split("Settled in that conversation")[1]
            assert "person] Settled: MAX_RETRIES is 3." not in settled
    ts = [e["timestamp"] for e in B.m5_transcript(B.T8, time.time())]
    assert ts == sorted(ts)                                                      # the reopened turns in order


def test_rollout_inputs_reads_token_usage_records_live_or_archived(tmp_path):
    d = tmp_path / "archived_sessions"
    d.mkdir()
    # a forked child's file starts with a copy of its parent's older history: only its own records count
    recs = [{"type": "token_usage_record", "timestamp": "2026-10-31T00:00:00Z", "payload": {"usage": {"input_tokens": 5}}},
            {"type": "session_meta", "timestamp": "2026-10-31T00:00:01Z", "payload": {"id": "abc"}}]
    recs += [{"type": "token_usage_record", "timestamp": f"2026-10-31T00:00:0{i}Z",
              "payload": {"usage": {"input_tokens": n}}} for i, n in ((3, 900), (2, 700))]
    (d / "rollout-2026-abc.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\nnot json\n", encoding="utf-8")
    assert B.rollout_inputs(tmp_path, "abc") == [700, 900]
    assert B.rollout_inputs(tmp_path, "zzz") == [] and B.rollout_inputs(None, "abc") == []


def test_spawn_calls_counts_the_parents_spawns_and_those_without_history(tmp_path):
    d = tmp_path / "sessions" / "2026"
    d.mkdir(parents=True)
    evs = [{"payload": {"type": "function_call", "name": "spawn_agent", "arguments": '{"fork_turns": "none"}'}},
           {"payload": {"type": "function_call", "name": "spawn_agent", "arguments": '{"message": "x"}'}},
           {"payload": {"type": "custom_tool_call", "name": "exec",
                        "input": 'tools.spawn_agent(message="a", fork_turns="none")'}},
           {"payload": {"type": "function_call", "name": "shell", "arguments": "spawn_agent docs"}}]
    (d / "rollout-p1.jsonl").write_text("\n".join(json.dumps(e) for e in evs), encoding="utf-8")
    assert B.spawn_calls(tmp_path, "p1") == {"spawn_calls": 3, "fork_none_calls": 2}
    assert B.spawn_calls(tmp_path, None) == {"spawn_calls": 0, "fork_none_calls": 0}


def _row(exp, task, rep, arm, **kw):
    base = {"tag": "t", "exp": exp, "task": task, "rep": rep, "arm": arm, "switch_ok": True, "right": 1, "runs": 5,
            "first_input": 1000, "prompt_tokens": 5000, "usd": 0.1, "reviews": 0, "requests": 5, "wall_s": 10}
    return {**base, **kw}


def test_rule_pass_fail_and_unknown():
    rows = [_row("m4", "mp1", 1, "batch", right=5, right_trap=1, n_pieces=5),
            _row("m4", "mp1", 1, "merge", right=5, right_trap=1, n_pieces=5, runs=2, prompt_tokens=3000)]
    r = B.rule(rows, "m4")
    assert r["verdict"] == "Pass" and r["pairs"] == 1 and all(r["checks"].values())
    worse = [rows[0], {**rows[1], "right_trap": 0, "right": 5}]
    assert B.rule(worse, "m4")["checks"]["trap_right_not_lower"] is False and B.rule(worse, "m4")["verdict"] == "Fail"
    dearer = [rows[0], {**rows[1], "prompt_tokens": 9000}]
    assert B.rule(dearer, "m4")["verdict"] == "Fail"
    # the switch did not take in one unit: Unknown, whatever the numbers say
    assert B.rule([rows[0], {**rows[1], "switch_ok": False}], "m4")["verdict"] == "Unknown"
    # too few of the planned pairs: given, or recorded in the rows by the run that planned them (a budget stop)
    assert B.rule(rows, "m4", planned=4)["verdict"] == "Unknown"
    stopped = [{**r, "planned_pairs": 8} for r in rows]
    assert B.rule(stopped, "m4")["planned_pairs"] == 8 and B.rule(stopped, "m4")["verdict"] == "Unknown"
    # a unit that failed is missing, not a switch that did not take
    failed = B.rule([rows[0], {**rows[1], "error": "RuntimeError: x", "switch_ok": False}], "m4")
    assert failed["left_out"][0]["why"].startswith("RuntimeError") and failed["pairs"] == 0
    # m3: the arm wrong where the baseline was right, with children spawned: a context loss, Fail
    m3 = [_row("m3", "bank", 1, "all", children={"n": 2, "first_inputs": [30000, 31000]}),
          _row("m3", "bank", 1, "none", right=0, first_input=500, prompt_tokens=100,
               children={"n": 2, "first_inputs": [9000, 9100]})]
    r3 = B.rule(m3, "m3")
    assert r3["checks"]["no_child_context_loss"] is False and r3["child_context_losses"] == [["bank", 1]]
    assert r3["all"]["child_first_input_median"] == 31000 and r3["none"]["child_first_input_median"] == 9100
    # m5: est_tokens and deduped chars are reported per side
    m5 = [_row("m5", "t1", 1, "keep", runs=1, shared_context={"est_tokens": 300}),
          _row("m5", "t1", 1, "dedupe", runs=1, first_input=990, prompt_tokens=4990,
               shared_context={"est_tokens": 290, "deduped": 1, "deduped_chars": 27})]
    r5 = B.rule(m5, "m5")
    assert r5["verdict"] == "Pass" and r5["dedupe"]["deduped_chars"] == 27 and r5["keep"]["est_tokens"] == 300
    # m5's prompt totals are reported, not judged: one more turn is not a loss by itself
    more = B.rule([m5[0], {**m5[1], "requests": 7, "prompt_tokens": 9000}], "m5")
    assert more["verdict"] == "Pass" and "prompt_not_higher" not in more["checks"]
    assert more["dedupe"]["prompt_per_request"] == round(9000 / 7, 1)
    # m3 where neither arm spawned a child: the switch had nothing to act on
    idle = [{**r, "children": {"n": 0}} for r in m3]
    assert B.rule(idle, "m3")["verdict"] == "Unknown" and B.rule(idle, "m3")["pairs_without_children"] == 1


def test_dry_run_prints_the_schedule_and_cost_and_runs_nothing(tmp_path, capsys):
    assert B.main(["run", "--exp", "m5", "--tasks", "t1-empty-mean", "--reps", "1", "--dry-run",
                   "--out", str(tmp_path / "r.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "2 unit(s)" in out and "m5-1-t1-empty-mean-keep" in out and not (tmp_path / "r.jsonl").exists()
    with pytest.raises(SystemExit):
        B.main(["run", "--exp", "m9", "--dry-run"])


# ------------------------------------------------------------------ one unit each, on the fake Codex

def _fake(monkeypatch, tmp_path, extra=None):
    def env_of(iso):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CCX_", "CODEX_", "CLAUDE")) and k not in ("FAKE_STATUS", "DSH_SESSION_ID")}
        (iso.x / "codex-home").mkdir(parents=True, exist_ok=True)
        iso.claude_dir.mkdir(parents=True, exist_ok=True) if iso.claude == "config-dir" else None
        env.update({"CCX_CODEX_BIN": str(FAKES / "fake_codex.py"), "CCX_CLAUDE_BIN": str(FAKES / "fake_claude.py"),
                    "FAKE_LOG": str(tmp_path / "calls.jsonl"), "CCX_AB_RATE": "0", "CCX_NO_BENCH_REFRESH": "1",
                    "CCX_NO_QUOTA_PROBE": "1", "CCX_CONFIG": str(tmp_path / "user-config.toml"),
                    "PYTHONIOENCODING": "utf-8", "CCX_HUB": str(iso.hub), "CODEX_HOME": str(iso.x / "codex-home"),
                    "DSH_HOME": str(tmp_path / "dsh"), **(extra or {})})
        if iso.claude == "config-dir":
            env["CLAUDE_CONFIG_DIR"] = str(iso.claude_dir)
        return env
    monkeypatch.setattr(B, "unit_env", env_of)
    monkeypatch.setattr(B.PF, "snapshot", lambda: None)
    monkeypatch.setattr(B.PF, "after_unit", lambda *a, **k: {})


class _A:
    timeout = 300
    codex_home = ""


def _unit(exp, task, arm):
    return {"exp": exp, "task": task, "rep": 1, "arm": arm, "tag": "t", "label": f"eval-b3arms:t:{exp}-{task}-{arm}"}


@pytest.mark.parametrize("arm", ["keep", "dedupe"])
def test_m5_unit_records_the_shared_context_and_whether_dedupe_ran(tmp_path, monkeypatch, arm):
    _fake(monkeypatch, tmp_path)
    row = B.run_unit(_unit("m5", "t8-reopened", arm), _A, tmp_path)
    assert not row.get("error"), row.get("error")
    assert row["context_attached"] and row["switch_ok"] and row["hub"]["switch"] is (arm == "dedupe")
    assert ("deduped" in row["shared_context"]) == (arm == "dedupe") and row["shared_context"]["est_tokens"] > 0
    if arm == "dedupe":
        assert row["shared_context"]["deduped"] == 1
    assert row["runs"] == 1 and row["first_input_missing"] in (0, 1) and row["prompt_tokens"] > 0
    assert not (tmp_path / B.unit_key(_unit("m5", "t8-reopened", arm))).exists()      # the unit left nothing


@pytest.mark.parametrize("arm", ["all", "none"])
def test_m3_unit_records_fork_turns_and_the_line_in_the_prompt(tmp_path, monkeypatch, arm):
    _fake(monkeypatch, tmp_path, {"FAKE_CHILD": "1"})
    row = B.run_unit(_unit("m3", "pg-a", arm), _A, tmp_path)
    assert not row.get("error"), row.get("error")
    assert row["switch_seen"] == arm and row["fork_none_in_prompt"] is (arm == "none") and row["switch_ok"]
    assert row["children"]["n"] == 1 and row["right"] == 0
    calls = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    prompt = next(c["prompt"] for c in calls if c["agent"] == "codex" and "exec" in c["argv"])
    assert ("fork_turns=\"none\"" in prompt) == (arm == "none")


@pytest.mark.parametrize("arm", ["merge", "batch"])
def test_m4_unit_scores_each_piece_where_its_run_left_it(tmp_path, monkeypatch, arm):
    mat, pieces = B.m4_material("mp1")
    trap = B._TRAP["dupparse"]
    writes = [f"{B._PIECE[p['id']]['file']}={B._PIECE[p['id']]['solution']}" for p in pieces if p["kind"] == "piece"]
    writes += [f"tests/test_{p['id']}.py={B._PIECE[p['id']]['hidden']}" for p in pieces if p["kind"] == "piece"]
    writes += [f"{f}={c}" for f, c in trap["solution"].items()]
    summary = "\n".join(f"[eval-{p['id']}] done: implemented" for p in pieces)
    _fake(monkeypatch, tmp_path, {"FAKE_WRITE": ";".join(writes), "FAKE_SUMMARY": summary})
    row = B.run_unit(_unit("m4", "mp1", arm), _A, tmp_path)
    assert not row.get("error"), row.get("error")
    assert row["switch_ok"] and row["n_pieces"] == 5 and row["right"] == 5 and row["right_trap"] == 1
    if arm == "merge":
        assert row["switch_seen"] and len(row["merged"]) == 1 and all(x["merged_run"] for x in row["pieces"])
        assert row["follow_ups"] == 0 and row["spun_off"] == 0
    else:                       # five runs, each piece found by its run's label and scored in its own worktree
        assert not row["switch_seen"] and not any(x["merged_run"] for x in row["pieces"])
        assert len({x["run_id"] for x in row["pieces"]}) == 5 and all(x["worktree"] for x in row["pieces"])
        assert row["runs"] >= 5
