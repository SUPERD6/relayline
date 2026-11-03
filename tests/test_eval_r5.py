"""Round-5 evaluation script: task list and scheduling only (no git history, no real CLI)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import pytest  # noqa: E402
import r5  # noqa: E402
import tasks_r5  # noqa: E402

FAKES = Path(__file__).resolve().parent / "fakes"


def test_tasks_are_complete():
    assert len(tasks_r5.IDS) == len(set(tasks_r5.IDS)) == 10
    for t in tasks_r5.T:
        assert t["brief"] and t["tests"] and len(t["commit"]) >= 7
        assert all(x.startswith("tests/") and x.endswith(".py") for x in t["tests"])


def test_schedule_covers_every_task_arm_round():
    us = r5.schedule(2, 53, tasks_r5.IDS, list(r5.ARMS))
    assert len(us) == 2 * 10 * len(r5.ARMS)
    assert us == r5.schedule(2, 53, tasks_r5.IDS, list(r5.ARMS))


def test_ccx2_is_opt_in():
    assert "ccx2" not in r5.ARMS and "ccx2" in r5.OPT_IN_ARMS
    us = r5.schedule(1, 53, tasks_r5.IDS[:2], ["ccx", "ccx2"])
    assert sorted(u["arm"] for u in us) == ["ccx", "ccx", "ccx2", "ccx2"]


def test_ccx2_lead_instruction_follows_the_skill():
    old, new = r5.lead_how("ccx", "L"), r5.lead_how("ccx2", "L")
    assert "--review on" in old and old == r5.HOW_CCX.format(ccx=r5.r3.CCX_CMD, label="L")   # old arm unchanged
    assert "--review" not in new and "--bg" in new and "show <run_id> --wait" in new
    assert "verbatim" in new and "do not ask the sub-agent to commit" in new and "tail" in new
    # A2: one call (--bg --wait 540 under a 600000 ms Bash timeout), show --wait only if it is still running
    assert "run --bg --wait 540 " in new and "timeout set to 600000" in new
    assert "If it is still running when that call returns" in new
    assert new.index("--wait 540") < new.index("show <run_id> --wait") and "then wait for it with" not in new


def test_unknown_arm_is_refused(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        r5.main(["run", "--arms", "nope", "--out", str(tmp_path / "r.jsonl"), "--workdir", str(tmp_path), "--dry-run"])


def test_summary_of_rows():
    rows = [{"task": "a", "round": 1, "arm": arm, "ok": arm != "self", "usd": usd, "lead_only_usd": usd,
             "lead_tokens": 10, "lead_requests": 3, "wall_s": 5, "env_clean": True}
            for arm, usd in (("self", 0.3), ("builtin", 0.3), ("ccx", 0.2), ("direct", 0.04), ("ccx2", 0.1))]
    s = r5.summarize(rows)
    assert s["arms"]["self"]["cps"] is None and s["arms"]["direct"]["cps"] == 0.04
    assert s["arms"]["ccx2"]["cps"] == 0.1 and s["arms"]["ccx2"]["n"] == 1


def test_builtin2_is_builtin_with_ccx2_acceptance():
    assert "builtin2" not in r5.ARMS and "builtin2" in r5.OPT_IN_ARMS
    b2, c2, b1 = r5.lead_how("builtin2", "L"), r5.lead_how("ccx2", "L"), r5.lead_how("builtin", "L")
    assert b1 == r5.r3.HOW["builtin"]                                                    # old arm unchanged
    assert "Agent tool" in b2 and "`worker`" in b2 and "ccx" not in b2
    assert "run the tests" not in b2 and "read the diff" not in b2                       # builtin's re-check is gone
    assert "accept it without re-running the tests or reading the full diff" in b2
    assert r5.LEAN_BRIEF in b2 and r5.LEAN_BRIEF in c2                                   # shared, not copied
    head, tail = r5.LEAN_ACCEPT.split("{send_back}")
    assert head in b2 and tail in b2 and head in c2 and tail in c2
    assert r5.lead_flags_arm("builtin2") == "builtin" and r5.lead_flags_arm("ccx2") == "ccx"
    us = r5.schedule(1, 53, tasks_r5.IDS[:2], ["ccx2", "builtin2"])
    assert sorted(u["arm"] for u in us) == ["builtin2", "builtin2", "ccx2", "ccx2"]
    s = r5.summarize([{"task": "a", "round": 1, "arm": "builtin2", "ok": True, "usd": 0.2, "lead_only_usd": 0.1,
                       "lead_tokens": 1, "lead_requests": 1, "wall_s": 1, "env_clean": True}])
    assert s["arms"]["builtin2"]["n"] == 1


# ------------------------------------------------------------------ confirmation-run additions (fake rows only)

def _row(task, rd, arm, ok, usd, wall, **kw):
    return {"tag": "t", "round": rd, "task": task, "arm": arm, "ok": ok, "usd": usd, "wall_s": wall,
            "lead_only_usd": usd, "lead_tokens": 1, "lead_requests": 1, "env_clean": True, **kw}


def test_summary_completion_and_failed_cost_cli(tmp_path):
    import json
    import subprocess

    rows = [_row("right", 1, "self", True, 1, 10, rc=0, subtype="success", lead_usd=0.6, ccx_usd=0.4),
            _row("wrong", 1, "self", False, 2, 10, rc=0, subtype="success"),
            _row("failed", 1, "self", False, 7, 10, rc=-9, error="quota"),
            _row("missing", 1, "self", False, None, 10, rc=0, subtype="success", lead_usd=0.5, ccx_usd=None),
            _row("legacy", 1, "self", False, 3, 10),
            _row("unclean", 1, "self", True, 20, 10, rc=0, subtype="success", env_clean=False),
            _row("env-unknown", 1, "self", True, 40, 10, rc=0, subtype="success", env_clean=None)]
    path = tmp_path / "results.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="")
    result = subprocess.run([sys.executable, str(Path(r5.__file__)), "summary", "--results", str(path),
                             "--results", str(path)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    report = summary["completion_and_cost"]
    clean = report["clean"]
    assert (clean["started"], clean["valid_completion"], clean["right"], clean["unknown"]) == (5, 3, 1, 2)
    assert clean["completion_unknown"] == clean["right_unknown"] == 1
    assert clean["valid_over_started"] == 3 / 5 and clean["right_over_started"] == 1 / 5
    assert clean["right_over_valid"] == 1 / 3
    assert clean["spend_all_started"] == clean["cost_per_success_all"] == 13.5
    assert clean["missing_cost_n"] == 1
    assert report["unclean"]["started"] == report["env_unknown"]["started"] == 1
    assert report["batch_cost"] == {"started": 7, "spend_all_started": 73.5, "missing_cost_n": 1,
                                    "spend_complete": False}
    assert report["by_arm"]["self"]["clean"] == clean
    assert r5.summarize(rows, True)["completion_and_cost"] == report
    assert summary["arms"]["self"]["n"] == 4 and summary["arms"]["self"]["cps"] == 6


def test_summary_completion_legacy_unknown_and_empty_cost():
    rows = [_row("old", 1, "direct", True, None, 1),
            _row("failed", 1, "direct", False, 0, 0, error="environment failed before billing")]
    clean = r5.summarize(rows)["completion_and_cost"]["clean"]
    assert clean["completion_unknown"] == 1 and clean["right_unknown"] == 1 and clean["unknown"] == 2
    assert clean["right"] == 1 and clean["valid_completion"] == 0 and clean["right_over_valid"] is None
    assert clean["spend_all_started"] is None and clean["cost_per_success_all"] is None
    assert clean["missing_cost_n"] == 2
    empty = r5.summarize([])["completion_and_cost"]["clean"]
    assert empty["started"] == empty["missing_cost_n"] == 0 and empty["spend_all_started"] == 0
    assert all(empty[k] is None for k in ("valid_over_started", "right_over_started", "right_over_valid"))


@pytest.mark.parametrize("cost", [None, float("nan"), float("inf"), -1, True])
def test_summary_completion_missing_cost_is_not_zero(cost):
    rows = [_row("new", 1, "direct", True, cost, 1, status="done", kind="ok"),
            _row("old", 1, "direct", True, 0, 1)]
    clean = r5.summarize(rows)["completion_and_cost"]["clean"]
    assert clean["missing_cost_n"] == 1 and clean["spend_all_started"] == 0
    assert clean["completion_unknown"] == 1 and clean["right"] == 2
    assert clean["right_over_valid"] is None  # an unobserved completion cannot enter this denominator


@pytest.mark.parametrize("fields,valid,unknown", [
    ({"status": "done", "rc": 2, "kind": "check_failed"}, 1, 0),
    ({"status": "done", "rc": 0, "kind": "ok"}, 1, 0),
    ({"status": "done", "rc": 2, "kind": "quota"}, 0, 0),
    ({"status": "done", "rc": 2, "kind": "env"}, 0, 0),
    ({"status": "done", "rc": 2, "kind": "timeout"}, 0, 0),
    ({"status": "done", "rc": 2}, 0, 1),
    ({"status": "done", "rc": 0, "kind": None}, 0, 1),
    ({"subtype": "success", "rc": 0}, 1, 0),
    ({"status": "failed", "rc": 2}, 0, 0),
])
def test_review_receipt_kind_and_legacy_evidence(fields, valid, unknown):
    report = r5.summarize([_row("receipt", 1, "direct", False, 1, 1, **fields)])["completion_and_cost"]
    assert report["clean"]["valid_completion"] == valid
    assert report["clean"]["completion_unknown"] == unknown


@pytest.mark.parametrize("source", ["receipt", "record"])
@pytest.mark.parametrize("kind", ["ok", "check_failed", "env", "quota", "timeout"])
def test_review_direct_records_receipt_kind(tmp_path, monkeypatch, source, kind):
    import json
    from types import SimpleNamespace
    from common import valid_completion

    receipt = {"run_id": "r", "status": "done", "ok": False}
    if source == "receipt":
        receipt["kind"] = kind
    monkeypatch.setattr(r5, "by_id", lambda tid: {"brief": "fixture"})
    monkeypatch.setattr(r5, "ext_python", lambda a: None)
    monkeypatch.setattr(r5, "task_env", lambda task, env, python: env)
    monkeypatch.setattr(r5.PF, "run", lambda *a, **kw: (json.dumps(receipt), "", 2, []))
    monkeypatch.setattr(r5.r2, "record", lambda *a: {"kind": kind if source == "record" else "ok"})
    monkeypatch.setattr(r5.r2, "hub_cost", lambda hub: {"usd": 1, "review_usd": 0, "run_ids": []})
    monkeypatch.setattr(r5.TL, "unit_timeline", lambda *a, **kw: {})
    row = r5.direct_unit({"task": "fixture", "arm": "direct", "label": "fixture"}, SimpleNamespace(timeout=1),
                         tmp_path / "repo", tmp_path / "hub", env={})
    assert row["kind"] == kind
    assert valid_completion(row) is (kind in ("ok", "check_failed"))


@pytest.mark.parametrize("cost,complete", [(0, True), (2, True), (None, False)])
def test_review_spend_complete_in_every_group(cost, complete):
    rows = [_row(str(i), 1, "self", True, cost, 1, subtype="success", env_clean=clean)
            for i, clean in enumerate((True, False, None))]
    report = r5.summarize(rows)["completion_and_cost"]
    for scope in (report, report["by_arm"]["self"]):
        for name in ("clean", "unclean", "env_unknown", "batch_cost"):
            assert scope[name]["spend_complete"] is complete
            assert scope[name]["missing_cost_n"] == (0 if complete else (3 if name == "batch_cost" else 1))
        assert scope["clean"]["cost_per_success_all"] == cost
    empty = r5.summarize([])["completion_and_cost"]
    assert all(empty[name]["spend_complete"] is False for name in ("clean", "unclean", "env_unknown", "batch_cost"))


def test_review_partial_spend_flag_does_not_change_cost_per_success():
    rows = [_row("success", 1, "self", True, 1, 1, subtype="success"),
            _row("failed", 1, "self", False, None, 1, error="quota", lead_usd=0.5, ccx_usd=None)]
    report = r5.summarize(rows)["completion_and_cost"]
    for scope in (report, report["by_arm"]["self"]):
        assert scope["clean"]["spend_all_started"] == scope["clean"]["cost_per_success_all"] == 1.5
        assert scope["clean"]["missing_cost_n"] == 1
        assert scope["clean"]["spend_complete"] is False and scope["batch_cost"]["spend_complete"] is False


def test_builtin2r_worker_carries_ccx_rules_word_for_word(monkeypatch):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKES / "fake_claude.py"))       # CI has no claude
    from ccx import prompts
    assert "builtin2r" in r5.OPT_IN_ARMS and "builtin2r" not in r5.ARMS
    assert "builtin2r" in r5.BUILTIN_ARMS and "builtin2r" not in r5.PF.CODEX_ARMS
    assert r5.lead_how("builtin2r", "L") == r5.lead_how("builtin2", "L")       # the lead is told the same
    assert r5.lead_flags_arm("builtin2r") == "builtin"
    w = r5.WORKER_RULES["worker"]
    assert prompts.KEEP_TESTS in w["prompt"] and prompts.WIRING.strip() in w["prompt"]
    base = r5.r3.WORKER["worker"]["prompt"]
    assert w["prompt"].startswith(base.replace(r5.WORKER_TESTS_BASE, r5.WORKER_TESTS_R))
    assert w["model"] == r5.r3.WORKER_MODEL
    # no "whole suite" instruction left to contradict WIRING's "not the whole suite"
    assert r5.WORKER_TESTS_BASE in base and "python -m pytest -q`" not in w["prompt"]
    assert "acceptance command" in w["prompt"]
    import json
    a2r = r5.r3.lead_argv("builtin", 1, agents=r5.worker_agents("builtin2r"))
    a2 = r5.r3.lead_argv("builtin", 1, agents=r5.worker_agents("builtin2"))
    assert json.loads(a2r[a2r.index("--agents") + 1]) == r5.WORKER_RULES
    assert json.loads(a2[a2.index("--agents") + 1]) == r5.r3.WORKER                 # builtin2 unchanged
    assert r5.unit_models({"arm": "builtin2r"}, {})["worker_rules"]
    assert "worker_rules" not in r5.unit_models({"arm": "builtin2"}, {})


def test_lead_model_defaults_and_keys(monkeypatch):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKES / "fake_claude.py"))       # CI has no claude
    argv = r5.r3.lead_argv("ccx", 1)
    assert argv[argv.index("--model") + 1] == "sonnet" and argv[argv.index("--effort") + 1] == "medium"
    argv = r5.r3.lead_argv("ccx", 1, "opus", "high")
    assert argv[argv.index("--model") + 1] == "opus" and argv[argv.index("--effort") + 1] == "high"
    old = {"tag": "r5", "round": 1, "task": "x", "arm": "ccx"}                        # a row from before the flag
    new = {**old, "lead_model": "sonnet", "lead_effort": "medium"}
    other = {**old, "lead_model": "opus", "lead_effort": "high"}
    assert r5.done_key(old) == r5.done_key(new) != r5.done_key(other)
    assert r5.arm_of(old) == r5.arm_of(new) == "ccx" and r5.arm_of(other) == "ccx@opus-high"
    assert r5.unit_key(old) == "1-x-ccx" and r5.unit_key(other) == "1-x-ccx@opus-high"
    assert r5.unit_models(other, {})["lead"] == "opus" and r5.unit_models(old, {})["lead_effort"] == "medium"
    s = r5.summarize([_row("a", 1, "ccx", True, 0.1, 10), _row("a", 1, "ccx", False, 0.5, 20, lead_model="opus")])
    assert s["arms"]["ccx"]["n"] == 1 and s["arms"]["ccx@opus-medium"]["n"] == 1   # never pooled
    assert "ccx vs ccx@opus-medium" in s["paired"]


def test_direct_has_no_lead_so_lead_flags_leave_it_alone(tmp_path, capsys):
    old = {"tag": "t", "round": 1, "task": "x", "arm": "direct"}
    stamped = {**old, "lead_model": "opus", "lead_effort": "high"}       # even a row that carries a lead
    assert r5.done_key(stamped) == r5.done_key(old) and r5.unit_key(stamped) == "1-x-direct"
    assert r5.arm_of(stamped) == "direct" and r5.unit_models(stamped, {}) == {"direct": " ".join(r5.DIRECT)}
    s = r5.summarize([_row("a", 1, "direct", True, 0.1, 10), _row("a", 1, "direct", True, 0.1, 10, lead_model="opus"),
                      _row("a", 1, "ccx", True, 0.2, 20, lead_model="opus")])
    assert s["arms"]["direct"]["n"] == 2 and "ccx@opus-medium vs direct" in s["paired"] or \
        "direct vs ccx@opus-medium" in s["paired"]
    # a run with another lead: direct units are already done, only the lead arms are new
    from common import append_jsonl
    f = tmp_path / "res.jsonl"
    append_jsonl(f, {"tag": "t", "round": 1, "task": r5.IDS[0], "arm": "direct"})
    a = r5.parser().parse_args(["run", "--tag", "t", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "direct,ccx",
                                "--lead-model", "opus", "--lead-effort", "high", "--out", str(f), "--dry-run",
                                "--workdir", str(tmp_path / "w")])
    assert r5.cmd_run(a) == 0
    out = capsys.readouterr().out
    assert "units: 1" in out and ":ccx@opus-high" in out and ":direct" not in out


def test_paired_comparison_mcnemar_holm_wilson_rounds():
    rows = []
    for i, t in enumerate("abcdef"):
        for rd in (1, 2):
            rows.append(_row(t, rd, "save", i < 2, 0.10, 100 + i))
            rows.append(_row(t, rd, "balanced", True, 0.12, 50 + i))
            rows.append(_row(t, rd, "self", i < 5, 0.30, 40))
    rows.append(_row("a", 3, "save", True, 0.1, 1))            # no partner: not paired
    s = r5.summarize(rows)
    p = s["paired"]["balanced vs save"]
    assert p["units"] == 12 and p["discordant"] == {"only_balanced": 8, "only_save": 0}
    assert p["mcnemar_p"] == r5.S.mcnemar_p(8, 0)
    assert set(s["paired"]) == {"self vs balanced", "self vs save", "balanced vs save"}
    adj = r5.S.holm({k: v["mcnemar_p"] for k, v in s["paired"].items()})
    assert all(v["mcnemar_p_holm"] == adj[k][1] for k, v in s["paired"].items())
    assert p["diff_is"] == "save - balanced" and p["wall_med_diff"] > 0
    assert p["wall_med_diff_ci"][0] <= p["wall_med_diff"] <= p["wall_med_diff_ci"][1]
    lo, hi = p["cps_diff_ci"]
    assert lo <= p["cps_diff"] <= hi
    assert s["arms"]["save"]["wilson"] == r5.S.wilson(5, 13)
    assert s["arms"]["save"]["ok_by_round"] == {"1": 2, "2": 2, "3": 1}
    # 12 units from 6 tasks: McNemar is flagged; the sign test counts tasks (4 where balanced was right more often)
    assert "mcnemar_note" in p and p["tasks"] == 6
    assert p["task_sign"] == {"more_balanced": 4, "more_save": 0} and p["task_sign_p"] == r5.S.mcnemar_p(4, 0)
    assert p["task_sign_p"] > p["mcnemar_p"]
    adj = r5.S.holm({k: v["task_sign_p"] for k, v in s["paired"].items()})
    assert all(v["task_sign_p_holm"] == adj[k][1] for k, v in s["paired"].items())
    assert "wilson_note" in s["arms"]["save"]
    lo, hi = s["arms"]["save"]["ok_rate_ci_tasks"]
    assert lo <= 5 / 13 <= hi and hi - lo > s["arms"]["save"]["wilson"][1] - s["arms"]["save"]["wilson"][0]
    one = r5.summarize([_row(t, 1, a, True, 0.1, 1) for t in "ab" for a in ("save", "self")])
    assert "mcnemar_note" not in one["paired"]["self vs save"] and "wilson_note" not in one["arms"]["save"]


def test_rounds_sort_numerically():
    rows = [_row("a", rd, "ccx", True, 0.1, 1) for rd in (10, 2, 1)]
    s = r5.summarize(rows)
    assert list(s["arms"]["ccx"]["ok_by_round"]) == ["1", "2", "10"]
    assert list(s["by_tag"]["t"]["ccx"]["rounds"]) == ["1", "2", "10"]


def test_cost_ci_reports_dropped_resamples():
    # arm x is right only on task a: resamples without a have no cost per success for x and are left out
    ps = [(_row(t, 1, "x", t == "a", 0.1, 1), _row(t, 1, "y", True, 0.2, 1)) for t in "abcd"]
    p = r5.compare_pair(ps, "x", "y")
    assert p["cps_diff_ci"] is not None and p["cps_diff_ci_dropped"] > 0 and "conditional" in p["cps_diff_note"]
    info: dict = {}
    r5.task_boot(ps, r5.cps_diff, n=200, info=info)
    assert info["n"] == 200 and 0 < info["dropped"] < 200
    never = [(_row(t, 1, "x", False, 0.1, 1), _row(t, 1, "y", True, 0.2, 1)) for t in "ab"]
    p = r5.compare_pair(never, "x", "y")
    assert p["cps_diff"] is None and p["cps_diff_ci"] is None and "x has no success" in p["cps_diff_note"]
    full = r5.compare_pair([(_row(t, 1, "x", True, 0.1, 1), _row(t, 1, "y", True, 0.2, 1)) for t in "ab"], "x", "y")
    assert full["cps_diff_ci_dropped"] == 0 and "cps_diff_note" not in full


def test_task_bootstrap_needs_two_tasks():
    ps = [(_row("a", 1, "x", True, 1, 1), _row("a", 1, "y", True, 2, 2))]
    assert r5.task_boot(ps, r5.cps_diff) is None and r5.cps_diff(ps) == 1.0
    assert r5.cps_diff([(_row("a", 1, "x", False, 1, 1), _row("a", 1, "y", True, 2, 2))]) is None


def test_tier_rule_pass_and_fail():
    ok = [r for t in "ab" for r in (_row(t, 1, "save", True, 0.10, 100), _row(t, 1, "balanced", True, 0.14, 60))]
    tr = r5.summarize(ok)["tier_rule"]
    assert tr["result"] == "pass" and all(c["result"] == "pass" for c in tr["conditions"].values())
    bad = [r for t in "ab" for r in (_row(t, 1, "save", True, 0.10, 100), _row(t, 1, "balanced", t == "a", 0.2, 61))]
    c = r5.tier_rule(bad)["conditions"]
    # one task's worth fewer right: the CI's lower end is below -1 task, so the right condition is Unknown
    assert c["right"]["result"] == "unknown" and c["right"]["diff_tasks"] == -1.0 and c["right"]["ci"][0] < -1
    assert c["wall"]["result"] == c["cps"]["result"] == "fail" and r5.tier_rule(bad)["result"] == "fail"
    none = [_row("a", 1, "save", False, 0.1, 100), _row("a", 1, "balanced", True, 0.1, 10)]
    # cannot tell is not failed: one task has no CI (unknown), and its cost per success is n/a
    assert r5.tier_rule(none)["conditions"]["cps"]["result"] == "n/a"
    assert r5.tier_rule(none)["conditions"]["right"]["result"] == "unknown" and r5.tier_rule(none)["result"] == "unknown"
    none_bad = [_row("a", 1, "save", False, 0.1, 100), _row("a", 1, "balanced", True, 0.1, 90)]
    assert r5.tier_rule(none_bad)["result"] == "fail"                    # a failed condition still fails it
    # the wall median is the upper middle, as the arms' wall_med
    ev = [r for t, w in zip("ab", (100, 200)) for r in (_row(t, 1, "save", True, 0.1, w), _row(t, 1, "balanced",
                                                                                                True, 0.1, w))]
    s = r5.summarize(ev)
    assert s["tier_rule"]["conditions"]["wall"]["value"] == [s["arms"]["balanced"]["wall_med"],
                                                             s["arms"]["save"]["wall_med"]] == [200, 200]
    lines = r5.tier_rule_lines(r5.tier_rule(ok))
    assert lines[0].startswith("tier rule (2 shared clean units): pass") and len(lines) == 4 and "CI" in lines[1]
    assert "tier_rule" not in r5.summarize([_row("a", 1, "save", True, 0.1, 1)])


def _rec(hub, rid, **kw):
    import json
    d = hub / "ccx" / "runs" / rid
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"run_id": rid, **kw}), encoding="utf-8")


def test_phase_wall_from_run_records(tmp_path):
    hub = tmp_path / "h"
    _rec(hub, "r1", label="L", attempts=[{"seconds": 30}, {"seconds": 20}], check={"seconds": 5},
         review={"run_id": "v1"})
    _rec(hub, "v1", label="review:r1", attempts=[{"seconds": 12}])
    _rec(hub, "f1", label="L", review_of="r1", attempts=[{"seconds": 8}], check={"seconds": 4},
         review={"run_id": "v2"})
    _rec(hub, "v2", label="review:f1", attempts=[{"seconds": 6}])
    ph = r5.phase_wall(hub, ["r1", "f1", "gone"], wall_s=100)        # v1 / v2 found through the records
    # each review ran while its run's final check ran: 5 (r1) + 4 (f1) counted once
    assert ph == {"sub_s": 50.0, "check_s": 5.0, "review_s": 18.0, "fix_s": 12.0, "overlap_s": 9.0, "n_attempts": 2,
                  "n_reviews": 2, "n_fix_rounds": 1, "missing": 1, "lead_wait_s": 76.0, "lead_active_s": 24.0}
    assert r5.phase_wall(hub, ["r1"], wall_s=10)["lead_wait_s"] == 10.0          # never more than the wall
    assert "lead_wait_s" not in r5.phase_wall(hub, ["r1"])                         # direct: no lead
    # a rung whose check failed (and climbed) keeps that check's time on its attempt; no check: no overlap
    _rec(hub, "e1", label="L", attempts=[{"seconds": 10, "kind": "check_failed", "check_seconds": 7},
                                         {"seconds": 20}], check={"seconds": 3})
    _rec(hub, "n1", label="L", attempts=[{"seconds": 10}], review={"run_id": "v3"})
    _rec(hub, "v3", label="review:n1", attempts=[{"seconds": 6}])
    e = r5.phase_wall(hub, ["e1", "n1"], wall_s=100)
    assert e["check_s"] == 10.0 and e["overlap_s"] == 0.0 and e["lead_wait_s"] == 56.0
    # a review stopped when the first rung's check failed ran alongside that check: counted once too
    _rec(hub, "s1", label="L", attempts=[{"seconds": 100, "kind": "check_failed", "check_seconds": 60},
                                         {"seconds": 100}], check={"seconds": 60}, review={"run_id": "rev2"})
    _rec(hub, "rev1", label="review:s1", attempts=[{"seconds": 50}])
    _rec(hub, "rev2", label="review:s1", attempts=[{"seconds": 50}])
    s = r5.phase_wall(hub, ["s1", "rev1", "rev2"], wall_s=1000)
    assert s["check_s"] == 120.0 and s["review_s"] == 100.0 and s["overlap_s"] == 100.0
    assert s["lead_wait_s"] == 320.0
    rows = [_row("a", 1, "ccx2", True, 0.1, 100, phases=ph),
            _row("b", 1, "ccx2", True, 0.1, 100, phases={**ph, "sub_s": 10.0}), _row("c", 1, "ccx2", True, 0.1, 1)]
    st = r5.summarize(rows)["arms"]["ccx2"]["phases"]
    assert st["sub_s"] == {"med": 50.0, "p75": 50.0, "n": 2} and st["lead_wait_s"]["med"] == 76.0


def test_budget_counts_only_its_tag(tmp_path):
    from common import append_jsonl
    f = tmp_path / "r.jsonl"
    append_jsonl(f, {"tag": "old", "usd": 50.0})
    append_jsonl(f, {"tag": "new", "usd": 1.25})
    assert r5.spent(f) == 51.25 and r5.spent(f, "new") == 1.25
    assert r5.budget_spent(f, "new", 0.5) == 1.75 and r5.budget_spent(f, "none") == 0
    assert r5.spend_line(f, "new", 0.5, 0.25) == "run=$0.250 tag=$1.750 file=$51.250"


# ------------------------------------------------------------------ tier arms (fake CLIs and fake rows only)

def _fake_env(tmp_path):
    """An environment for ccx subprocesses: fake CLIs, throwaway homes, nothing of the machine's lead identity."""
    import os
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CCX_", "CODEX_", "CLAUDE")) and k not in ("FAKE_STATUS", "DSH_SESSION_ID")}
    for var, sub in (("CODEX_HOME", "codex-home"), ("CLAUDE_CONFIG_DIR", "claude-home"), ("DSH_HOME", "dsh")):
        (tmp_path / sub).mkdir(exist_ok=True)
        env[var] = str(tmp_path / sub)
    env.update({"CCX_CODEX_BIN": str(FAKES / "fake_codex.py"), "CCX_CLAUDE_BIN": str(FAKES / "fake_claude.py"),
                "FAKE_LOG": str(tmp_path / "calls.jsonl"), "CCX_AB_RATE": "0", "CCX_NO_BENCH_REFRESH": "1",
                "CCX_NO_QUOTA_PROBE": "1", "CCX_CONFIG": str(tmp_path / "user-config.toml"),
                "PYTHONIOENCODING": "utf-8"})
    return env


def test_tier_arms_are_opt_in_and_registered(monkeypatch):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKES / "fake_claude.py"))       # CI has no claude
    assert r5.TIER_ARMS == ("fast", "balanced", "save", "cheapest")
    assert all(x in r5.OPT_IN_ARMS and x not in r5.ARMS for x in r5.TIER_ARMS)
    assert r5.ARMS == ("self", "builtin", "ccx", "direct")                      # the default schedule stays
    assert r5.TIER_RULE_ARMS == ("balanced", "save")                            # #142's rule reads these names
    assert {"balanced", "save", "cheapest"} <= set(r5.PF.CODEX_ARMS) and "fast" not in r5.PF.CODEX_ARMS
    assert not set(r5.TIER_ARMS) & set(r5.BUILTIN_ARMS)
    assert not r5.has_lead("cheapest") and all(r5.has_lead(x) for x in ("fast", "balanced", "save"))
    assert r5.lead_flags_arm("fast") == "self" and r5.lead_flags_arm("balanced") == r5.lead_flags_arm("save") == "ccx"
    fast, bal = r5.r3.lead_argv(r5.lead_flags_arm("fast"), 1), r5.r3.lead_argv(r5.lead_flags_arm("balanced"), 1)
    assert "Agent" not in fast[fast.index("--tools") + 1] and "--no-session-persistence" in fast
    assert "--no-session-persistence" not in bal                               # ccx --context reads its session
    # --lead-model: the lead arms get their own key, cheapest (no lead) keeps one
    old = {"tag": "t", "round": 1, "task": "x"}
    assert r5.unit_key({**old, "arm": "save", "lead_model": "opus", "lead_effort": "high"}) == "1-x-save@opus-high"
    assert r5.unit_key({**old, "arm": "cheapest", "lead_model": "opus", "lead_effort": "high"}) == "1-x-cheapest"
    m = r5.unit_models({**old, "arm": "cheapest"}, {})
    assert m == {"direct": " ".join(r5.CHEAPEST), "tier_picked": "cheapest"}
    assert r5.unit_models({**old, "arm": "direct"}, {}) == {"direct": " ".join(r5.DIRECT)}    # direct unchanged
    # cheapest is the shipped cheapest tier's script run, not direct under a new name: save's model pick (no
    # explicit model; the explicit --tradeoff save wins over the hub's picked tier, so ccx plans nothing), nobody
    # reviews it; its --check (the repository's suite) is added per task by direct_unit
    ch = r5.no_lead_flags("cheapest")
    assert ch == r5.CHEAPEST and r5.no_lead_flags("direct") == r5.DIRECT
    assert ch[ch.index("--review") + 1] == "off" and "--model" not in ch and "--effort" not in ch
    assert ch[ch.index("--tradeoff") + 1] == "save"                             # as propose's `next` has it
    assert "--minutes" not in ch and "--check" not in ch      # nobody sizes it; the suite check is per task (below)
    assert "--no-escalate" not in ch and "--no-fallback" not in ch
    assert r5.DIRECT[r5.DIRECT.index("--review") + 1] == "on" and "gpt-6-luna" in r5.DIRECT
    m = r5.unit_models({**old, "arm": "balanced", "lead_model": "opus", "lead_effort": "high"}, {})
    assert m["lead"] == "opus" and m["tier_picked"] == "balanced"
    assert "tier_picked" not in r5.unit_models({**old, "arm": "ccx2"}, {})
    us = r5.schedule(1, 53, tasks_r5.IDS[:2], list(r5.TIER_ARMS) + ["ccx2"])
    assert sorted(u["arm"] for u in us) == sorted(list(r5.TIER_ARMS) * 2 + ["ccx2"] * 2)


def test_tier_lead_wording():
    bal = r5.lead_how("balanced", "L", ("opus", "high"))
    save = r5.lead_how("save", "L")
    fast = r5.lead_how("fast", "L")
    for t, how in (("balanced", bal), ("save", save)):
        assert f"`{t}`" in how and "policy.picked" in how and "propose --lead claude:" in how
        assert "--minutes" in how and "--files" in how and "authorized: true" in how and "next" in how
        assert "--label L" in how and "--bg" in how and "show <run_id> --wait" in how and "--no-ab" in how
        assert "`--bg --wait 540 " in how and "600000" in how and r5.WAIT_ONE_CALL.split("{ccx}")[0] in how
        assert r5.LEAN_BRIEF in how and "do the work yourself" in how
        head, tail = r5.LEAN_ACCEPT.split("{send_back}")
        assert head in how and tail in how                                       # ccx2's acceptance, shared
        assert "{" not in how                                                    # every field filled
        # the proposal is made on the text the run sends (its re-plan agrees), and a refused run is done by hand
        assert "verbatim" in how.split("propose --lead")[0] and "in one line" not in how
        assert "refuses the proposal" in how and "do not propose again" in how
    assert "claude:opus:high" in bal and "claude:sonnet:medium" in save
    # a full model id is not a ccx rung: the family alias goes to `ccx propose --lead`
    assert "claude:opus:high" in r5.lead_how("save", "L", ("claude-opus-4-7", "high"))
    assert r5.ccx_lead_model("claude-sonnet-4-6") == "sonnet" and r5.ccx_lead_model("haiku") == "haiku"
    assert r5.ccx_lead_model("mystery-1") == "mystery-1"
    assert "`fast`" in fast and "ccx" not in fast.replace("ccx settings", "") and "yourself" in fast
    assert r5.lead_how("ccx2", "L") == r5.HOW_CCX2.format(ccx=r5.r3.CCX_CMD, label="L")      # old arms unchanged
    assert r5.lead_how("self", "L") == r5.r3.HOW["self"]


def test_set_picked_writes_the_hub_setting(tmp_path):
    env = _fake_env(tmp_path)
    hub = tmp_path / "hub"
    (hub / "ccx").mkdir(parents=True)
    assert r5.set_picked(hub, "balanced", env) == "balanced"
    assert "picked" in (hub / "ccx" / "settings.toml").read_text(encoding="utf-8")
    assert r5.set_picked(hub, "cheapest", env) == "cheapest"


def test_tier_fields_from_a_real_propose_in_a_fake_hub(tmp_path):
    """The lead's step through ccx itself (fake CLIs): the person picked balanced, a 4-file estimate is large ->
    ccx2, authorized; the row's plan, reference band and misbanding come from the hub's ledger."""
    import json
    import subprocess
    import sys as _sys
    env = _fake_env(tmp_path)
    hub = tmp_path / "hub"
    (hub / "ccx").mkdir(parents=True)
    env["CCX_HUB"] = str(hub)
    r5.set_picked(hub, "balanced", env)
    r = subprocess.run([_sys.executable, str(r5.ROOT / "ccx.py"), "propose", "--lead", "claude:opus:high",
                        "--minutes", "60", "--files", "4", "rework the parser"], cwd=tmp_path, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["authorized"] is True and out["tier"]["band"] == "large" and out["tier"]["mode"] == "ccx2"
    small = {"id": "tiny-x", "size": 8, "files": 1}
    f = r5.tier_fields("balanced", hub, small)
    assert f["tier"] == "balanced" and f["tier_plan"]["source"] == "propose"
    assert f["tier_plan"]["band"] == "large" and f["tier_plan"]["mode"] == "ccx2" and f["tier_plan"]["authorized"]
    assert f["tier_plan"]["estimate_minutes"] == 60 and f["tier_plan"]["n_proposals"] == 1
    assert f["ref_size"] == {"lines": 8, "files": 1, "band": "small"} and f["tier_plan"]["estimate_files"] == 4
    assert f["misband"] == "over" and f["misband_overall"] == "over"            # 4 files vs 1: over either way
    assert f["actual_mode"] == "self" and f["followed_plan"] is False            # nothing went out
    # a run the lead started from it: the ledger's actual_mode
    led = hub / "ccx" / "ledger.jsonl"
    with open(led, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"run_id": "r1", "label": "L", "actual_mode": "ccx2"}) + "\n")
        fh.write(json.dumps({"run_id": "v1", "label": "review:r1"}) + "\n")
    f = r5.tier_fields("balanced", hub, small)
    assert f["actual_mode"] == "ccx2" and f["followed_plan"] is True
    # fast: never proposed; cheapest: the tier's rule (direct for every band), unsized, no misbanding
    empty = tmp_path / "h2"
    (empty / "ccx").mkdir(parents=True)
    f = r5.tier_fields("fast", empty, small)
    assert f["tier_plan"]["mode"] == "self" and f["actual_mode"] == "self" and f["misband"] is None
    (empty / "ccx" / "ledger.jsonl").write_text(json.dumps(
        {"run_id": "d1", "label": "L", "actual_mode": "direct"}) + "\n", encoding="utf-8")
    f = r5.tier_fields("cheapest", empty, small)
    # the eval script's plan, not ccx's (ccx plans nothing for an unsized run with an explicit --tradeoff)
    assert f["tier_plan"]["source"] == "eval-script" and f["tier_plan"]["mode"] == "direct"
    assert f["tier_plan"]["ccx_planned"] is False
    assert f["actual_mode"] == "direct" and f["may_be_wrong"] is True
    assert f["tier_plan"]["sized"] is False and f["tier_plan"]["run_policy_tier"] is None
    assert f["misband"] is None and f["followed_plan"] is None                  # no lead: nothing to follow


def test_misband_compares_files_with_files(tmp_path):
    """A one-file task with an exact --files 1 and a sensible 30-minute estimate is not misbanded: the minutes make
    the planned band medium, but the reference change has only files, so only files are compared (`misband`);
    `misband_overall` keeps the planned band's comparison, which is over by construction."""
    import subprocess
    import sys as _sys
    env = _fake_env(tmp_path)
    hub = tmp_path / "hub"
    (hub / "ccx").mkdir(parents=True)
    env["CCX_HUB"] = str(hub)
    r5.set_picked(hub, "save", env)
    r = subprocess.run([_sys.executable, str(r5.ROOT / "ccx.py"), "propose", "--lead", "claude:sonnet:medium",
                        "--minutes", "30", "--files", "1", "rework the parser"], cwd=tmp_path, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    f = r5.tier_fields("save", hub, {"id": "tiny-y", "size": 8, "files": 1})
    assert f["tier_plan"]["band"] == "medium" and f["ref_size"]["band"] == "small"
    assert f["misband"] == "same" and f["misband_overall"] == "over"
    assert r5.files_band(1) == "small" and r5.files_band(2) == "medium" and r5.files_band(3) == "large"
    assert r5.files_band(None) is None and r5.files_band(0) is None


def test_a_paraphrased_proposal_is_refused_by_its_run(tmp_path):
    """Why the tier lead proposes on the verbatim request: under balanced a brief with a state-machine word is
    planned self. Proposed verbatim, ccx says so up front (not authorized); proposed as a one-line paraphrase without
    the word, it is authorized and then `ccx run --proposal` with the real brief refuses. Fake CLIs; the refused
    run starts nothing."""
    import json
    import subprocess
    import sys as _sys
    env = _fake_env(tmp_path)
    hub = tmp_path / "hub"
    (hub / "ccx").mkdir(parents=True)
    env["CCX_HUB"] = str(hub)
    r5.set_picked(hub, "balanced", env)
    brief = tasks_r5.by_id("brief-words")["brief"]
    assert "resume" in r5.task_routing().size_band(brief, None, 3, r5.shipped_policy())["hard"]

    def ccx(*args):
        r = subprocess.run([_sys.executable, str(r5.ROOT / "ccx.py"), *args], cwd=tmp_path, env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        return json.loads(r.stdout)
    est = ["--minutes", "60", "--files", "3"]
    verbatim = ccx("propose", "--lead", "claude:sonnet:medium", *est, brief)
    assert verbatim["authorized"] is False and verbatim["tier"]["mode"] == "self"
    assert r5.planned_mode("balanced", tasks_r5.by_id("brief-words")) == "self"      # the dry run agrees
    para = ccx("propose", "--lead", "claude:sonnet:medium", *est, "fix how memory notes are picked for briefs")
    assert para["authorized"] is True
    refused = ccx("run", "--tradeoff", "save", "--proposal", para["proposal"], *est, "--mode", "write", "--new",
                  "--no-ab", "--label", "L", brief)
    assert refused["ok"] is False and "plans this run's own task as self" in refused["error"]
    assert not (tmp_path / "calls.jsonl").exists()                               # no sub-agent was started


def test_reference_size_and_misband():
    import tasks_holdout
    t = tasks_holdout.by_id("ledger-repair")
    ref = r5.ref_size(t)
    assert ref["lines"] == t["size"] and ref["files"] == t["files"] and ref["band"] == "medium"   # 2 files
    assert r5.ref_size(tasks_holdout.by_id("undo-not-verdict"))["band"] == "large"                # 4 files
    assert r5.misband("small", "large") == "under" and r5.misband("large", "small") == "over"
    assert r5.misband("medium", "medium") == "same" and r5.misband(None, "small") is None
    r = r5.ref_size(tasks_r5.by_id("waiting-evals"))      # from this checkout's history; None in a shallow clone
    assert r is None or (r["files"] >= 1 and r["band"] in r5.BANDS)


def test_check_passed_reads_the_last_builder_run(tmp_path):
    hub = tmp_path / "h"
    _rec(hub, "a", label="L", check={"passed": False})
    _rec(hub, "b", label="L", check={"passed": True})
    _rec(hub, "v", label="review:b", check={"passed": False})
    _rec(hub, "n", label="L")
    assert r5.ccx_check_passed(hub, ["a", "b", "v"]) is True
    assert r5.ccx_check_passed(hub, ["b", "a"]) is False
    assert r5.ccx_check_passed(hub, ["n"]) is None and r5.ccx_check_passed(hub, []) is None


def test_tier_summary_and_tier_rule_per_lead():
    def tr(task, arm, ok, usd, wall, band, ref, actual, check=None, **kw):
        return _row(task, 1, arm, ok, usd, wall, tier=arm, tier_plan={"band": band, "mode": "self"},
                    ref_size={"band": ref}, misband=r5.misband(band, ref), actual_mode=actual,
                    followed_plan=actual == "self", **({"ccx_check_passed": check} if check is not None else {}), **kw)
    opus = {"lead_model": "opus", "lead_effort": "high"}
    rows = []
    for t in "ab":
        rows += [tr(t, "balanced", True, 0.14, 60, "small", "small", "self", **opus),
                 tr(t, "save", t == "a", 0.10, 100, "large", "small", "ccx2", check=True, **opus)]
    s = r5.summarize(rows)
    assert set(s["tier_rules"]) == {"balanced@opus-high vs save@opus-high"}
    assert s["tier_rule"] == s["tier_rules"]["balanced@opus-high vs save@opus-high"]
    assert s["tier_rule"]["units"] == 2 and s["tier_rule"]["conditions"]["right"]["result"] == "pass"
    assert s["tier_rule"]["pair"] == "balanced@opus-high vs save@opus-high"     # says which lead's arms it is
    sv, bl = s["tiers"]["save@opus-high"], s["tiers"]["balanced@opus-high"]
    assert {k: v for k, v in sv["misband"].items() if k != "basis"} == {"n": 2, "wrong": 2, "rate": 1.0,
                                                                         "under": 0, "over": 2}
    assert sv["misband"]["basis"].startswith("files") and "by construction" in sv["misband_overall"]["basis"]
    assert sv["misband_overall"]["n"] == 0 and sv["route_sources"] is None
    assert bl["misband"]["rate"] == 0.0 and bl["right"] == "2/2" and bl["cps"] == 0.14
    assert sv["check_passed_on_fail"] == "1/1" and sv["actual_modes"] == {"ccx2": 2}
    assert sv["followed_plan"] == "0/2" and {"wall_med", "wall_mean", "wall_p75"} <= set(sv)
    assert "balanced@opus-high vs save@opus-high" in s["paired"]
    # one lead's balanced is never ruled against another lead's save
    mixed = [tr("a", "balanced", True, 0.1, 10, "small", "small", "self"),
             tr("a", "save", True, 0.1, 10, "small", "small", "ccx2", **opus)]
    assert "tier_rule" not in r5.summarize(mixed) and r5.tier_rules(mixed) == {}
    assert "tiers" not in r5.summarize([_row("a", 1, "ccx2", True, 0.1, 1)])


def test_dry_run_prints_the_schedule_and_the_estimate(tmp_path, capsys):
    import re
    a = r5.parser().parse_args(["run", "--tag", "t", "--rounds", "1", "--tasks", ",".join(tasks_r5.IDS[:2]),
                                "--arms", "fast,balanced,save,ccx2,cheapest", "--lead-model", "opus",
                                "--lead-effort", "high", "--budget", "1", "--out", str(tmp_path / "r.jsonl"),
                                "--workdir", str(tmp_path / "w"), "--dry-run"])
    assert r5.cmd_run(a) == 0
    out = capsys.readouterr().out
    assert "units: 10" in out and len(re.findall(r"^\[dry\] eval-r5:t:", out, re.M)) == 10
    # Opus priced at its list prices on the assumed Sonnet mix (empty results file): x1.81 of the lead's part
    assert r5.lead_price_ratio("opus") == 1.81 and r5.lead_price_ratio("sonnet") == 1.0
    assert ":fast@opus-high  ~$0.362 (self; lead ~$0.362, ccx ~$0.000)" in out
    assert ":cheapest  ~$0.050 (direct; lead ~$0.000, ccx ~$0.050)" in out
    assert ":ccx2@opus-high  ~$0.182 (ccx2;" in out
    assert re.search(r"\[estimate\] save@opus-high\s+2 units\s+~\$0\.200/unit\s+~\$0\.40 \(lead ~\$0\.31, ccx "
                     r"~\$0\.09\)", out)
    assert "[estimate] lead prices: opus x1.81 of sonnet; token mix assumed" in out
    assert "[estimate] total ~$" in out and "short by" in out                  # $1 does not cover 10 units
    assert not (tmp_path / "w").exists()                                       # nothing prepared, nothing run
    # the estimate per unit: measured means, an Opus lead's share x1.7, one propose for balanced / save
    assert r5.unit_estimate({"arm": "ccx2", "task": tasks_r5.IDS[0]}) == (0.12, "ccx2")
    assert r5.unit_estimate({"arm": "self", "task": tasks_r5.IDS[0], "lead_model": "opus"})[0] == 0.34
    assert r5.unit_estimate({"arm": "save", "task": tasks_r5.IDS[0]}) == (0.13, "ccx2")
    assert r5.unit_estimate({"arm": "cheapest", "task": tasks_r5.IDS[0], "lead_model": "opus"}) == (0.05, "direct")
    assert r5.unit_estimate({"arm": "ccx", "task": tasks_r5.IDS[0]}) == (0.21, "ccx")
    assert r5.planned_mode("balanced", tasks_r5.by_id("q-resume-session")) == "self"            # resume: hard


def _tiny_repo(path):
    import subprocess
    path.mkdir()
    (path / "a.py").write_text("x = 1\n", encoding="utf-8")
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
        subprocess.run(["git", *cmd], cwd=path, check=True, capture_output=True)
    return path


def test_cheapest_check_is_the_repository_suite():
    """The cheapest arm's --check is the whole existing suite, the same command for every task of a repository: it
    names no task's test file (that would point at the hidden test), only the flaky nodes every task leaves out."""
    import tasks_holdout
    own = [t for t in tasks_r5.T]
    checks = {r5.suite_check(t) for t in own}
    assert len(checks) == 1
    chk = checks.pop()
    assert chk.startswith("python -m pytest -q tests") and "--deselect" in chk     # BG_RUN, flaky under load
    rest = chk.replace(r5.SUITE, "")
    hidden_files = {f for t in own for f in t["tests"]}
    # only --deselect nodes follow the suite; a hidden file is named only as part of a node every task leaves out
    assert all(x == "--deselect" or "::" in x for x in rest.split())
    assert not any(f"{f} " in chk + " " for f in hidden_files)                     # no hidden file on its own
    for t in tasks_holdout.T:
        c = r5.suite_check(t)
        if not t.get("repo"):
            assert c == chk                                                        # this repository: one command
        else:
            assert c.startswith("python -m pytest -q tests") and not any(f in c for f in t["tests"])
    hum = next(t for t in tasks_holdout.T if t.get("repo") == "humanize")
    assert "--ignore=tests/test_benchmarks.py" in r5.suite_check(hum)


@pytest.mark.parametrize("passes", [True, False])
def test_cheapest_unit_runs_the_shipped_cheapest_tier(tmp_path, monkeypatch, passes):
    """The cheapest unit through ccx itself (fake CLIs): in a hub that picked cheapest, save's model pick (no explicit
    model, no fixed --minutes: the script sizes nothing, so the run has no tier plan and its route falls back to the
    brief's keywords, as ccx2's run does), Codex, no review, the repository's suite as its --check, taken as it is
    (a failed ccx re-check climbs a rung, as save does); the row says direct, may be wrong, and ccx planned nothing.
    The direct arm's command keeps its explicit model, --minutes 60 and review."""
    import json
    from types import SimpleNamespace
    chk = f'python -c "raise SystemExit({0 if passes else 1})"'
    monkeypatch.setattr(r5, "suite_check", lambda task: chk)
    env = _fake_env(tmp_path)
    env["FAKE_TOUCH"] = "1"            # the builder changes something (a run that changes nothing is no_changes)
    hub = tmp_path / "hub"
    (hub / "ccx").mkdir(parents=True)
    env["CCX_HUB"] = str(hub)
    r5.set_picked(hub, "cheapest", env)
    repo = _tiny_repo(tmp_path / "repo")
    u = {"tag": "t", "round": 1, "task": tasks_r5.IDS[0], "arm": "cheapest", "label": "eval-r5:t:1:x:cheapest"}
    row = r5.direct_unit(u, SimpleNamespace(timeout=300), repo, hub, env)
    assert row["rc"] == 0, row
    led = [json.loads(x) for x in (hub / "ccx" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    runs = [x for x in led if not x.get("type")]
    assert len(runs) == 1 and not any(str(x.get("label") or "").startswith("review:") for x in led)
    assert "policy_tier" not in runs[0] and runs[0]["b"] is None                # unsized: no tier plan, no b
    assert runs[0]["actual_mode"] == "direct" and runs[0]["rungs"][0].startswith("codex:")
    assert not row["verdicts"]                                                  # nobody reviewed it
    r5.bookkeeping(row, "cheapest", hub, tasks_r5.by_id(u["task"]))
    assert "bookkeeping_error" not in row and row["ccx_check_passed"] is passes   # ccx's re-check, as it is
    rec = r5.r2.record(hub, runs[0]["run_id"])
    assert rec["check"]["cmd"] == chk
    if not passes:                                    # save's climb on a failed ccx re-check fires
        assert rec["attempts"][0]["kind"] == "check_failed" and len(rec["attempts"]) >= 2
    assert row["ccx_routes"][0]["source"] != "explicit" and row["ccx_routes"][0]["b"] is None
    assert row["tier_plan"]["mode"] == "direct" and row["tier_plan"]["source"] == "eval-script"
    assert row["tier_plan"]["ccx_planned"] is False
    assert row["may_be_wrong"] and row["followed_plan"] is None and row["misband"] is None


def test_ccx_routes_and_bookkeeping_errors_keep_the_unit(tmp_path, monkeypatch):
    hub = tmp_path / "h"
    _rec(hub, "r1", label="L", route={"source": "task-routing", "b": 5.5, "rung": "codex:gpt-6-luna:low"},
         attempts=[{"model": "gpt-6-luna", "effort": "low"}])
    _rec(hub, "v1", label="review:r1", route={"source": "explicit"})
    _rec(hub, "r2", label="L", route={"source": "keywords"}, attempts=[{"model": "m", "effort": "e", "rung": "x"}])
    got = r5.ccx_routes(hub, ["r1", "v1", "r2", "missing"])
    assert got == [{"source": "task-routing", "b": 5.5, "rung": "codex:gpt-6-luna:low", "model": "gpt-6-luna",
                    "effort": "low"},
                   {"source": "keywords", "b": None, "rung": "x", "model": "m", "effort": "e"}]
    rows = [_row("a", 1, "save", True, 0.1, 10, tier="save", ccx_routes=got[:1]),
            _row("b", 1, "save", True, 0.1, 10, tier="save", ccx_routes=got[1:])]
    assert r5.tier_summary(rows)["save"]["route_sources"] == {"keywords": 1, "task-routing": 1}

    def boom(*a, **k):
        raise OSError("ledger unreadable")
    monkeypatch.setattr(r5, "tier_fields", boom)
    row = {"ccx_run_ids": ["r1"]}
    r5.bookkeeping(row, "save", hub, {"id": "x"})                               # does not raise
    assert row["bookkeeping_error"] == "OSError: ledger unreadable" and "ccx_routes" not in row
