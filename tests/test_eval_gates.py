"""PR-E evaluation gates (scripts/eval/r5.py, r5_timeline.py): only clean rows count, the lead / ccx split, one commit
per tag, the paired right-rate rule, Opus priced at Opus prices, the ccx2-skill arm and the per-unit timeline.
No real CLI: run records and streams are written by hand."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import preflight as PF  # noqa: E402
import r5  # noqa: E402
import r5_timeline as TL  # noqa: E402
import tasks_r5  # noqa: E402

FAKES = Path(__file__).resolve().parent / "fakes"


def _row(task, rd, arm, ok, usd=0.1, wall=10, **kw):
    return {"tag": "t", "round": rd, "task": task, "arm": arm, "ok": ok, "usd": usd, "wall_s": wall,
            "lead_only_usd": usd, "lead_tokens": 1, "lead_requests": 1, "env_clean": True, **kw}


# ------------------------------------------------------------------ only env_clean rows count

def test_summary_counts_clean_rows_only_and_says_how_many_it_left_out(tmp_path, capsys, monkeypatch):
    rows = [_row("a", 1, "ccx2", True), _row("b", 1, "ccx2", False, env_clean=False),
            {k: v for k, v in _row("c", 1, "ccx2", True).items() if k != "env_clean"}]
    s = r5.summarize(rows)
    assert s["arms"]["ccx2"]["n"] == 1 and s["excluded_rows"] == {"unclean": 1, "env_unknown": 1}
    assert s["counted"] == "env_clean rows only"
    assert s["unclean_rows"] == 1 and s["env_unknown_rows"] == 1            # what the file has, as before
    every = r5.summarize(rows, include_unclean=True)
    assert every["arms"]["ccx2"]["n"] == 3 and every["excluded_rows"] == {"unclean": 0, "env_unknown": 0}
    f = tmp_path / "res.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(r5, "results_file", lambda taskset: f)
    assert r5.main(["summary"]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["arms"]["ccx2"]["n"] == 1
    assert "left out 2 rows that are not env_clean (1 unclean, 1 from before the clean room)" in cap.err
    assert r5.main(["summary", "--include-unclean"]) == 0
    assert "left out" not in capsys.readouterr().err


def test_tier_rule_never_counts_unclean_rows():
    clean = [r for t in "ab" for r in (_row(t, 1, "save", True, 0.1, 100), _row(t, 1, "balanced", True, 0.1, 50))]
    dirty = [_row(t, 1, arm, arm == "save", 0.1, 100, env_clean=False) for t in "cdef" for arm in ("save", "balanced")]
    tr = r5.tier_rule(clean + dirty)
    assert tr["units"] == 2 and tr["excluded_rows"]["unclean"] == 8 and tr["result"] == "pass"
    s = r5.summarize(clean + dirty, include_unclean=True)      # the arms count them, the rule still does not
    assert s["arms"]["save"]["n"] == 6 and s["tier_rule"]["units"] == 2
    assert r5.tier_rule(dirty) is None


# ------------------------------------------------------------------ $ split into the lead's and ccx's

def test_each_arm_splits_its_spend_into_lead_and_ccx():
    rows = [_row("a", 1, "ccx2", True, 0.3, lead_usd=0.2, ccx_usd=0.1),
            _row("b", 1, "ccx2", False, 0.2, lead_usd=0.15, ccx_usd=0.05),
            _row("a", 1, "direct", True, 0.05, ccx_usd=0.05)]
    a = r5.summarize(rows)["arms"]
    assert (a["ccx2"]["lead_usd"], a["ccx2"]["ccx_usd"]) == (0.35, 0.15)
    assert (a["ccx2"]["lead_cps"], a["ccx2"]["ccx_cps"], a["ccx2"]["cps"]) == (0.35, 0.15, 0.5)
    assert (a["direct"]["lead_usd"], a["direct"]["ccx_cps"]) == (0, 0.05)
    assert r5.summarize([_row("a", 1, "self", False, lead_usd=1)])["arms"]["self"]["lead_cps"] is None


# ------------------------------------------------------------------ one commit per tag

def test_a_tag_runs_on_one_commit():
    head = "a" * 40
    old = [{"tag": "t", "fingerprint": {"commit": "b" * 12}}, {"tag": "u", "fingerprint": {"commit": "a" * 12}}]
    assert r5.pin_check([], "t", head) == ("a" * 12, [])                   # a new tag pins this checkout
    assert r5.pin_check(old, "u", head) == ("a" * 12, [])                  # its rows are from here
    pinned, probs = r5.pin_check(old, "t", head)
    assert pinned == "b" * 12 and probs == [f"tag t was run at {'b' * 12}; this checkout is at {'a' * 12}"]
    two = old + [{"tag": "t", "fingerprint": {"commit": "a" * 12}}]
    assert any("2 commits" in p for p in r5.pin_check(two, "t", head)[1])
    assert r5.pin_check([], "t", head, "aaaaaaa") == ("aaaaaaa", [])        # --pin-commit, short sha
    assert r5.pin_check([], "t", head, "c" * 40)[1] == [f"this checkout is at {'a' * 12}, not the pinned commit "
                                                        f"{'c' * 40}"]
    fp = PF.fingerprint({**_REP, "pinned_commit": "b" * 12}, None, None)
    assert fp["pinned_commit"] == "b" * 12


_REP = {"commit": "a" * 40, "dirty": False, "tasks_sha256": "t" * 16, "tiers_sha256": "s" * 16,
        "cli": {"claude": "2.1.309"}, "jobs": 1, "result": "pass", "force_unclean": False, "codex": {}}


def test_run_refuses_a_tag_started_at_another_commit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(PF, "commit_state", lambda: {"commit": "a" * 40, "dirty": []})
    ran = []
    monkeypatch.setattr(r5, "prepare_external", lambda *a, **k: ran.append(1) or [])
    out = tmp_path / "r.jsonl"
    out.write_text(json.dumps({"tag": "t", "round": 1, "task": "x", "arm": "self",
                               "fingerprint": {"commit": "b" * 12}}) + "\n", encoding="utf-8")
    base = ["run", "--tag", "t", "--rounds", "1", "--tasks", r5.IDS[0], "--arms", "self", "--out", str(out),
            "--workdir", str(tmp_path / "w"), "--no-canary"]
    assert r5.main(base) == 3 and ran == []                             # nothing prepared, nothing paid
    assert "one tag runs on one commit" in capsys.readouterr().out
    assert r5.main(base + ["--dry-run"]) == 0
    assert "[dry] commit: tag t was run at" in capsys.readouterr().out


# ------------------------------------------------------------------ the paired right-rate condition

def test_right_condition_is_a_paired_ci_lower_bound():
    def rows(bad_tasks, n=10, rounds=3):
        return [r for i in range(n) for rd in range(1, rounds + 1)
                for r in (_row(f"t{i}", rd, "save", True, 0.1, 100),
                          _row(f"t{i}", rd, "balanced", i not in bad_tasks, 0.1, 50))]
    same = r5.tier_rule(rows(set()))["conditions"]["right"]
    assert same["result"] == "pass" and same["ci"] == (0.0, 0.0) and same["diff_tasks"] == 0
    one = r5.tier_rule(rows({0}))["conditions"]["right"]      # one task always wrong: -1 task, CI reaches below -1
    assert one["diff_tasks"] == -1.0 and one["ci"][0] < -1 and one["result"] == "unknown"
    assert r5.tier_rule(rows({0}))["result"] == "unknown"     # wall and cost pass: the rule cannot say yes
    assert r5.right_diff_tasks([]) is None
    # a resample keeps the sample's task count: two copies of one wrong task are -2 tasks of 2, not -1 of 1
    ps = [(_row("b", 1, "s", True), _row("b", 1, "b", False))] * 2
    assert r5.right_diff_tasks(ps, n_tasks=2) == -2.0 and r5.right_diff_tasks(ps) == -1.0


# ------------------------------------------------------------------ an Opus lead priced at Opus prices

def test_opus_lead_is_priced_at_its_list_prices_on_the_measured_mix(tmp_path, capsys):
    assert r5.model_family("claude-opus-4-7") == "opus" and r5.model_family("mystery") is None
    # all cache reads: Opus 5.5 costs the same per cache read, so x1; all output: x2
    assert r5.lead_price_ratio("opus", {"input": 0, "output": 0, "cache_read": 1, "cache_write": 0}) == 1.0
    assert r5.lead_price_ratio("opus", {"input": 0, "output": 1, "cache_read": 0, "cache_write": 0}) == 2.0
    assert r5.lead_price_ratio("haiku") is None and r5.lead_price_ratio("sonnet") == 1.0
    usage = {"input_tokens": 0, "output_tokens": 1000, "cache_read_input_tokens": 50000,
             "cache_creation_input_tokens": 0}
    rows = [{"arm": "ccx2", "lead_usage": usage}, {"arm": "ccx2", "lead_usage": usage, "lead_model": "opus"},
            {"arm": "direct", "lead_usage": usage}]
    mix, note = r5.lead_mix(rows)
    assert note == "measured from 1 sonnet-lead rows" and mix["output"] == 0.5 and mix["cache_read"] == 0.5
    assert r5.lead_price_ratio("opus", mix) == 1.5
    assert r5.lead_mix([])[1].startswith("assumed")
    sp = r5.unit_split({"arm": "ccx2", "task": tasks_r5.IDS[0], "lead_model": "opus"}, 1.5)
    assert (sp["lead"], sp["ccx"], sp["mode"]) == (round(0.12 * 0.64 * 1.5, 4), round(0.12 * 0.36, 4), "ccx2")
    assert sp["usd"] == pytest.approx(sp["lead"] + sp["ccx"], abs=1e-4)
    assert r5.unit_split({"arm": "ccx2", "task": tasks_r5.IDS[0], "lead_model": "haiku"}, None)["mode"] == "ccx2 $?"
    out = tmp_path / "r.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    a = r5.parser().parse_args(["run", "--tag", "x", "--rounds", "1", "--tasks", tasks_r5.IDS[0], "--arms", "ccx2",
                                "--lead-model", "opus", "--out", str(out), "--workdir", str(tmp_path / "w"),
                                "--dry-run"])
    assert r5.cmd_run(a) == 0
    text = capsys.readouterr().out
    assert "lead prices: opus x1.5 of sonnet; token mix measured from 1 sonnet-lead rows" in text
    assert "(lead ~$0.12, ccx ~$0.04)" in text


# ------------------------------------------------------------------ ccx2-skill (R7)

def test_ccx2_skill_arm_loads_the_skill_and_gets_no_inline_how(monkeypatch, tmp_path):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKES / "fake_claude.py"))       # CI has no claude
    assert "ccx2-skill" in r5.OPT_IN_ARMS and "ccx2-skill" not in r5.ARMS
    assert "ccx2-skill" in r5.CCX_ARMS and "ccx2-skill" in PF.CODEX_ARMS and r5.lead_flags_arm("ccx2-skill") == "ccx"
    how = r5.lead_how("ccx2-skill", "L")
    assert "agent-delegate" in how and "Skill tool" in how
    for inline in ("--bg", "--wait", "--tradeoff", "--check", "show <run_id>", r5.LEAN_BRIEF, "ccx.py"):
        assert inline not in how                                               # what to run comes from the skill
    argv = r5.skill_argv(r5.r3.lead_argv("ccx", 1))
    assert "--disable-slash-commands" not in argv
    assert argv[argv.index("--tools") + 1].endswith(",Skill") and "Skill" in argv[argv.index("--allowed-tools") + 1]
    assert r5.skill_argv(argv) == argv                                         # once
    assert "--disable-slash-commands" in r5.r3.lead_argv("ccx", 1)             # every other lead still has it
    with pytest.raises(SystemExit, match="ccx-home"):
        r5.main(["run", "--arms", "ccx2-skill", "--rounds", "1", "--tasks", r5.IDS[0], "--out",
                 str(tmp_path / "r.jsonl"), "--workdir", str(tmp_path / "w")])

    class A:
        claude_isolation, codex_home, dsh_home = "ccx-home", "", "unit"
    u = {"round": 1, "task": r5.IDS[0], "label": "L"}
    assert r5.unit_of({**u, "arm": "ccx2-skill"}, A, tmp_path).ccx_home
    assert r5.unit_of({**u, "arm": "save"}, A, tmp_path).ccx_home              # leads that use ccx
    assert not r5.unit_of({**u, "arm": "self"}, A, tmp_path).ccx_home          # a fresh, empty home
    A.claude_isolation = "config-dir"
    assert not r5.unit_of({**u, "arm": "ccx2-skill"}, A, tmp_path).ccx_home


# ------------------------------------------------------------------ R8: the timeline

def _rec(hub, rid, **kw):
    d = hub / "ccx" / "runs" / rid
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"run_id": rid, **kw}), encoding="utf-8")


def _stream():
    def msg(mid, out, parent=None):
        return {"type": "assistant", "parent_tool_use_id": parent,
                "message": {"id": mid, "usage": {"input_tokens": 1, "cache_read_input_tokens": 100,
                                                 "cache_creation_input_tokens": 10, "output_tokens": out},
                            "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "agent-delegate"}}]
                            if mid == "m1" else []}}
    evs = [msg("m1", 5), msg("m1", 5), msg("m2", 7), msg("w1", 99, parent="tu1"),
           {"type": "result", "duration_ms": 100000, "duration_api_ms": 30000, "total_cost_usd": 0.05}]
    return "\n".join(json.dumps(e) for e in evs)


def test_timeline_splits_a_unit_by_role_and_reason(tmp_path):
    hub = tmp_path / "h"
    att = lambda s, k, rung, **kw: {"seconds": s, "kind": k, "rung": rung, "ae_usd": 0.01,  # noqa: E731
                                    "usage": {"input": 10, "output": 5}, **kw}
    _rec(hub, "r1", attempts=[att(40, "check_failed", 1, check_seconds=8), att(30, None, 2)],
         check={"seconds": 9, "passed": True}, review={"run_id": "v1"})
    _rec(hub, "v1", label="review:r1", attempts=[att(12, None, 1)])
    _rec(hub, "r2", review_of="r1", attempts=[att(20, None, 2)], check={"seconds": 5})
    _rec(hub, "r3", resumed_from="r1", attempts=[att(6, None, 2), att(4, "blocked", 2)])
    ls = TL.lead_stream(_stream())
    assert ls["requests"] == 2 and ls["usage"]["output_tokens"] == 12 and ls["skills"] == ["agent-delegate"]
    assert ls["tokens"] == 2 * (1 + 100 + 10) + 12 and ls["api_s"] == 30.0 and ls["usd"] == 0.05
    tl = TL.unit_timeline(hub, ["r1", "r2", "r3", "gone"], _stream(), 100.0, {"lead_wait_s": 60.0})
    p = tl["parts"]
    assert p["sub"]["first attempt"]["s"] == 40 and p["sub"]["climb after check_failed"]["s"] == 30
    assert p["sub"]["sent back by the lead (resume)"]["s"] == 6 and p["sub"]["retry after failed"]["s"] == 4
    assert p["check"]["failed rung's check"]["s"] == 8 and p["check"]["final check"]["s"] == 9
    assert p["review"]["review"]["s"] == 12 and p["review"]["review"]["usd"] == 0.01
    assert p["fix"]["fix round after a review"]["s"] == 20 and p["fix"]["check of a fix round"]["s"] == 5
    assert p["lead"]["model"] == {"s": 30.0, "usd": 0.05, "tokens": ls["tokens"], "n": 1}
    assert p["lead"]["waiting on ccx"]["s"] == 60 and p["lead"]["tools and other"]["s"] == 10
    assert tl["missing_records"] == 1 and tl["residual_s"] == 0 and tl["ccx_s"] == 134
    assert p["sub"]["first attempt"]["tokens"] == 15
    direct = TL.unit_timeline(hub, ["r1"], "", 120.0)
    assert "lead" not in direct["parts"] and direct["residual_s"] == round(120 - direct["ccx_s"], 1)
    s = TL.summarize([{"arm": "ccx2", "timeline": tl}, {"arm": "ccx2", "timeline": direct}, {"arm": "self"}])
    assert s["ccx2"]["units"] == 2 and s["ccx2"]["parts"]["sub"]["first attempt"]["units"] == 2
    assert s["ccx2"]["parts"]["lead"]["model"]["s_med"] == 30.0 and any("ccx2" in x for x in TL.lines(s))


def test_timeline_counts_a_392_final_check_once(tmp_path):
    """#392: the last attempt also carries the final check (record["check"]): one "final check", no early copy."""
    hub = tmp_path / "h"
    t = "2026-11-17T10:00:00+00:00"
    _rec(hub, "r1", attempts=[{"seconds": 40, "kind": "check_unverified", "rung": 1, "check_started_at": t,
                               "check_seconds": 6.0},
                              {"seconds": 30, "kind": None, "rung": 2, "check_started_at": t, "check_seconds": 10.0}],
         check={"seconds": 10.0, "passed": True})
    parts, _ = TL.run_parts(hub, ["r1"])
    assert parts["check"]["final check"]["s"] == 10.0
    assert parts["check"]["earlier rung's check"]["s"] == 6.0
    assert "failed rung's check" not in parts["check"]
    assert sum(v["s"] for v in parts["check"].values()) == 16.0


def test_timeline_reaches_rows_and_its_summary_reads_them(tmp_path, monkeypatch, capsys):
    hub = tmp_path / "h"
    _rec(hub, "r1", attempts=[{"seconds": 5, "ae_usd": 0.02}])
    rows = [_row("a", 1, "ccx2", True, timeline=TL.unit_timeline(hub, ["r1"], "", 9.0)),
            _row("b", 1, "ccx2", True, env_clean=False, timeline=TL.unit_timeline(hub, ["r1"], "", 9.0))]
    f = tmp_path / "res.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(r5, "results_file", lambda taskset: f)
    assert TL.main(["summary"]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["ccx2"]["units"] == 1 and "excluded 1 rows" in cap.err
    assert TL.main(["summary", "--include-unclean"]) == 0
    assert json.loads(capsys.readouterr().out)["ccx2"]["units"] == 2


# ------------------------------------------------------------------ review fixes: the gates' blind spots

def test_unclean_rows_are_counted_per_arm_and_a_one_sided_loss_is_flagged():
    clean = [r for t in "ab" for r in (_row(t, 1, "save", True, 0.1, 100), _row(t, 1, "balanced", True, 0.1, 50))]
    # c-f: save's rows are clean, balanced's are not: the pairs are lost on balanced's side only
    lopsided = [r for t in "cdef" for r in (_row(t, 1, "save", True, 0.1, 100),
                                            _row(t, 1, "balanced", False, 0.1, 50, env_clean=False))]
    s = r5.summarize(clean + lopsided)
    assert s["arms"]["balanced"]["excluded"] == {"unclean": 4, "env_unknown": 0, "of": 6}
    assert "excluded" not in s["arms"]["save"] and s["excluded_by_arm"] == {"balanced": s["arms"]["balanced"]
                                                                              ["excluded"]}
    assert s["excluded_by_tag"] == {"t": s["excluded_by_arm"]}
    lp = s["paired"]["balanced vs save"]["lost_pairs"]
    assert lp["lost"] == 4 and lp["of"] == 6 and lp["unclean_side"] == {"balanced": 4, "save": 0}
    assert "one-sided" in s["paired"]["balanced vs save"]["lost_pairs_note"]
    tr = s["tier_rule"]
    assert tr["units"] == 2 and all(c["result"] == "pass" for c in tr["conditions"].values())
    assert tr["result"] == "unknown" and "one-sided" in tr["exclusion_note"]          # a pass it cannot trust
    assert tr["excluded_by_arm"]["balanced"]["unclean"] == 4 and tr["excluded_rows"]["unclean"] == 4
    assert any("note" in x for x in r5.tier_rule_lines(tr))
    assert "per arm: balanced 4/6" in r5.excluded_line(s)
    # the same loss on both sides: no note, the rule may pass
    even = [_row(t, 1, arm, True, 0.1, 100 if arm == "save" else 50, env_clean=False)
            for t in "cd" for arm in ("save", "balanced")]
    assert r5.tier_rule(clean + even)["result"] == "pass"


def test_right_condition_fails_when_the_whole_ci_is_below_the_floor():
    rows = [r for i in range(10) for r in (_row(f"t{i}", 1, "save", True, 0.1, 100),
                                           _row(f"t{i}", 1, "balanced", i >= 5, 0.1, 50))]
    tr = r5.tier_rule(rows)
    assert tr["conditions"]["right"]["ci"][1] < r5.RIGHT_CI_FLOOR
    assert tr["conditions"]["right"]["result"] == "fail" and tr["result"] == "fail"


def test_a_lead_in_a_ccx_home_is_its_own_arm(tmp_path, capsys):
    flags = _row("a", 1, "ccx2", True)
    home = _row("a", 1, "ccx2", True, ccx_home=True)
    old = _row("a", 1, "ccx2", True, fingerprint={"isolation": {"claude": "ccx-home", "claude_home": "ccx"}})
    assert r5.arm_of(flags) == "ccx2" and r5.arm_of(home) == r5.arm_of(old) == "ccx2@ccx-home"
    assert r5.arm_of({**home, "lead_model": "opus", "lead_effort": "high"}) == "ccx2@opus-high@ccx-home"
    assert r5.done_key(flags) != r5.done_key(home) == r5.done_key(old)
    assert r5.unit_key(home) == "1-a-ccx2@ccx-home" and r5.unit_key(flags) == "1-a-ccx2"
    s = r5.summarize([flags, home, old])
    assert s["arms"]["ccx2"]["n"] == 1 and s["arms"]["ccx2@ccx-home"]["n"] == 2     # never pooled
    # the tier rule pairs a ccx home's balanced with a ccx home's save
    rows = [r for t in "ab" for r in (_row(t, 1, "save", True, 0.1, 100, ccx_home=True),
                                      _row(t, 1, "balanced", True, 0.1, 50, ccx_home=True))]
    assert list(r5.summarize(rows)["tier_rules"]) == ["balanced@ccx-home vs save@ccx-home"]
    out = tmp_path / "r.jsonl"
    a = ["run", "--tag", "x", "--rounds", "1", "--tasks", tasks_r5.IDS[0], "--arms", "ccx2,builtin2", "--out", str(out),
         "--workdir", str(tmp_path / "w"), "--dry-run", "--claude-isolation", "ccx-home"]
    assert r5.main(a) == 0
    text = capsys.readouterr().out
    assert f":{tasks_r5.IDS[0]}:ccx2@ccx-home " in text and f":{tasks_r5.IDS[0]}:builtin2 " in text


def test_every_arm_splits_lead_only_and_delegated_spend_and_the_skill_arm_says_if_the_skill_was_used():
    rows = [_row("a", 1, "builtin2", True, 0.3, lead_usd=0.3, lead_only_usd=0.2, sub_usd=0.1),
            _row("a", 1, "ccx2", True, 0.3, lead_usd=0.1, ccx_usd=0.2, lead_only_usd=0.1, sub_usd=0.2),
            _row("a", 1, "ccx2-skill", True, ccx_home=True, skill_used=True),
            _row("b", 1, "ccx2-skill", True, ccx_home=True, skill_used=False)]
    a = r5.summarize(rows)["arms"]
    assert (a["builtin2"]["lead_only_usd"], a["builtin2"]["sub_usd"], a["builtin2"]["sub_cps"]) == (0.2, 0.1, 0.1)
    assert (a["ccx2"]["lead_only_cps"], a["ccx2"]["sub_cps"]) == (0.1, 0.2)
    sk = a["ccx2-skill@ccx-home"]
    assert sk["skill_used"] == "1/2" and "did not load agent-delegate" in sk["skill_used_note"]
    assert "skill_used" not in a["ccx2"]


def test_timeline_shows_the_builtin_worker_as_a_sub_agent():
    tl = TL.unit_timeline(None, [], _stream(), 100.0, None, worker_usd=0.02)
    p = tl["parts"]
    assert p["sub"]["built-in worker"]["usd"] == 0.02 and p["sub"]["built-in worker"]["tokens"] == 1 + 100 + 10 + 99
    assert p["lead"]["model"]["usd"] == 0.03 and tl["usd"] == 0.05                  # the total is unchanged
    assert TL.lead_stream(_stream())["worker_requests"] == 1
