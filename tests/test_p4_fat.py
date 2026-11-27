"""Fat-context diagnostic arms (#546): fake CLIs only, no paid request, no real Claude/Codex."""
import json
from pathlib import Path
import sys

import pytest

from test_p4_long_session import fake_engine  # noqa: F401
from test_p4_round2 import _r2_engine, dry, task_file

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "eval"))
sys.path.insert(0, str(ROOT))
import p4_long_session as P
import fat_arms as FA
import dispatch_eval as D

FAKE = ROOT / "tests" / "fakes" / "p4_fat_lead.py"
TOOLS = "Read,Grep,Glob,Edit,Write,Bash"
TASK = {"id": "t", "repo": "fake", "commit": "1" * 40, "brief": "Add feature one.", "tests": ["tests/test_new.py"],
        "code": ["pkg/mod.py"]}


def fat_engine(fake_engine, monkeypatch, tmp_path, tokens=2000, **extra):
    a, ts, log = _r2_engine(fake_engine, monkeypatch, tmp_path, lambda hub: [])
    monkeypatch.setattr(P.r5.r3, "lead_argv", lambda *x, **k: [
        sys.executable, str(FAKE), "--model", "sonnet", "--tools", TOOLS, "--allowed-tools", TOOLS.replace(",", " ")])
    a.fat_tier, a.fat_tokens, a.fill_chars_per_token, a.fill_tolerance = "main", tokens, 4.0, .15
    a.fill_budget, a.fat_lead_model, a.arms = 1.0, "sonnet[1m]", ",".join(FA.ARMS)
    for k, v in extra.items():
        setattr(a, k, v)
    return a, ts, log


def entries(log):
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------ pieces

def test_filler_is_deterministic_task_independent_and_the_requested_size():
    one, two = FA.filler(3000), FA.filler(3000)
    assert one == two and len(one) == 3000 * 4
    assert FA.filler(3000, 3.0) != one and len(FA.filler(3000, 3.0)) == 9000
    assert FA.fill_prompt(500).startswith(FA.FILL_MARKER) and "READY" in FA.fill_prompt(500)
    for word in ("test", "hidden", "ccx", "repository", "def ", "import"):
        assert word not in one.lower()
    with pytest.raises(ValueError):
        FA.filler(0)


def test_fill_range_is_unknown_without_a_measurement():
    assert FA.fill_in_range(None, 225_000) is None
    assert FA.fill_in_range(200_000, 225_000) is True        # 11% off, inside 15%
    assert FA.fill_in_range(150_000, 225_000) is False
    assert FA.TIERS == {"main": 225_000, "heavy": 360_000}


def test_only_fatnative_gets_the_agent_tool_and_every_fat_lead_the_big_model(monkeypatch):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKE))          # a path only: nothing is started
    base = P.r5.r3.lead_argv("ccx", 1.5, "sonnet", "medium")     # the shipped p4 lead argv, a pure function
    assert "Agent" not in base[base.index("--tools") + 1] and "--no-session-persistence" not in base
    for arm in (FA.SELF, FA.CCX):
        assert FA.lead_argv(base, arm)[FA.lead_argv(base, arm).index("--model") + 1] == FA.LEAD_MODEL
        assert "Agent" not in " ".join(FA.lead_argv(base, arm)) and "--agents" not in FA.lead_argv(base, arm)
    native = FA.lead_argv(base, FA.NATIVE, "sonnet[1m]")
    assert native[native.index("--tools") + 1].endswith(",Agent")
    assert native[native.index("--allowed-tools") + 1].endswith(" Agent")
    assert json.loads(native[native.index("--agents") + 1])["worker"]["model"] == "haiku"
    assert "--no-session-persistence" not in native         # resume needs the session file
    assert FA.lead_argv(base, FA.NATIVE).count("--agents") == 1
    assert base == P.r5.r3.lead_argv("ccx", 1.5, "sonnet", "medium")   # the input was not modified


def test_prompts_fat_self_and_ccx_reuse_the_legacy_text_and_native_uses_the_agent_tool():
    receipt = Path("/x/p4_receipt.py")
    assert P.prompt(TASK, FA.SELF, 1.0, receipt) == P.prompt(TASK, "self", 1.0, receipt)
    assert P.prompt(TASK, FA.CCX, 1.0, receipt) == P.prompt(TASK, "ccxlong", 1.0, receipt)
    native = P.prompt(TASK, FA.NATIVE, 1.0, receipt)
    assert "Agent tool" in native and "subagent_type `worker`" in native and TASK["brief"] in native
    assert "p4_receipt" not in native and "Do not use ccx" in native
    assert "Do not use Agent" in P.prompt(TASK, "self", 1.0, receipt)    # the legacy wording is untouched
    src = P.prompt({**TASK, "src_layout": True}, FA.NATIVE, 1.0, receipt)
    assert "PYTHONPATH='src" in src and "PYTHONPATH=." not in src


def test_caps_and_envelope_fat_arms_only_add_and_legacy_numbers_are_unchanged(fake_engine):
    a = fake_engine[0]
    a.task_cap, a.lead_budget, a.child_budget, a.self_lead_budget = None, .5, 1.0, 1.5
    legacy = (P.task_caps(a, "self"), P.task_caps(a, "ccxlong"), P.budget_envelope(a))
    assert P.task_caps(a, FA.SELF) == (1.5, 0.0) and P.task_caps(a, FA.CCX) == (.5, 1.0)
    assert P.task_caps(a, FA.NATIVE) == (1.5, 0.0)                # the sub-agent spends inside the lead's cap
    assert "fill_allowance_usd" not in legacy[2]
    a.arms, a.fill_budget = "fatself,fatccx", 2.0
    env = P.budget_envelope(a)
    assert env["fill_allowance_usd"] == 2.0 and env["max_task_reservation_usd"] == 1.5 + 2.0
    del a.arms, a.fill_budget
    assert (P.task_caps(a, "self"), P.task_caps(a, "ccxlong"), P.budget_envelope(a)) == legacy
    assert P.ARMS == ("self", "ccxlong")


def test_dry_run_prints_the_three_arms_settings(tmp_path):
    f, sha = task_file(tmp_path, 3)
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha, "--arms", ",".join(FA.ARMS),
             "--budget", "30", "--episode-size", "1", "--fat-tier", "heavy"], tmp_path)
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    fat = plan["fat"]
    assert set(fat["arms"]) == set(FA.ARMS)
    assert "Agent" in fat["arms"][FA.NATIVE]["tools"] and fat["arms"][FA.NATIVE]["agents"]["worker"]["model"] == "haiku"
    assert "Agent" not in fat["arms"][FA.SELF]["tools"] and fat["arms"][FA.CCX]["delegates_to"].startswith("codex")
    assert fat["fill"]["tier"] == "heavy" and fat["fill"]["target_tokens"] == 360_000
    assert fat["fill"]["tiers"] == {"main": 225_000, "heavy": 360_000}
    assert all(v["lead_model"] == "sonnet[1m]" for v in fat["arms"].values())
    assert len(plan["units"]) == 9 and {u["arm"] for u in plan["units"]} == set(FA.ARMS)
    assert plan["budget_envelope"]["fill_allowance_usd"] == FA.HEAVY_FILL_BUDGET
    assert set(plan["arm_settings"]) == set(FA.ARMS)
    assert plan["arm_settings"][FA.CCX]["child_agent"] == "codex" and plan["arm_settings"][FA.NATIVE]["child_agent"] is None
    assert "Unknown" in plan["estimate"]["tasks"][0]["basis"]
    explicit = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha, "--arms", FA.SELF,
                    "--budget", "30", "--episode-size", "1", "--fat-tokens", "1234"], tmp_path)
    assert explicit.returncode == 0, explicit.stderr
    assert json.loads(explicit.stdout)["fat"]["fill"]["target_tokens"] == 1234


@pytest.mark.parametrize("extra,message", [
    (["--arms", "fatself,self", "--split", "r2b"], "run only together"),
    (["--arms", "fatself,ccxcheapfirst2", "--split", "r2b"], "run only together"),
    (["--arms", "fatself,fatccx", "--split", "dev"], "--split r2b"),
    (["--arms", "fatself,fatccx", "--split", "r2b", "--focused-retry"], "focused"),
    (["--arms", "fatself,fatccx", "--split", "r2b", "--child-agent", "claude"], "child-agent"),
    (["--arms", "fatself,fatccx", "--split", "r2b", "--fill-tolerance", "1.5"], "fill-tolerance"),
    (["--arms", "fatself,fatccx", "--split", "r2b", "--fill-budget", "0"], "fill-budget"),
])
def test_fat_arms_refuse_what_would_silently_mean_something_else(tmp_path, extra, message):
    f, sha = task_file(tmp_path, 2)
    r = dry(["--tasks-file", str(f), "--tasks-sha256", sha, "--budget", "10", *extra], tmp_path)
    assert r.returncode != 0 and message in r.stderr


def test_legacy_dry_plans_have_no_fat_section(tmp_path):
    f, sha = task_file(tmp_path, 2)
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha, "--arms", "self,ccxcheapfirst2",
             "--budget", "10"], tmp_path)
    plan = json.loads(r.stdout)
    assert "fat" not in plan and "fill_allowance_usd" not in plan["budget_envelope"]


# ------------------------------------------------------------------ the engine with a fake lead

def test_three_arms_run_fill_then_task_in_one_session_with_full_accounting(fake_engine, monkeypatch, tmp_path):
    a, ts, log = fat_engine(fake_engine, monkeypatch, tmp_path)
    units = P.schedule(ts[:2], 1, FA.ARMS, 1)
    assert len(units) == 6 and {u["arm"] for u in units} == set(FA.ARMS)
    assert P.run_experiment(a, ts[:2], units) == 0
    es = entries(log)
    assert len(es) == 12
    for sid in {e["session"] for e in es}:
        pair = [e for e in es if e["session"] == sid]
        assert [e["fill"] for e in pair] == [True, False]
        assert [e["flag"] for e in pair] == ["--session-id", "--resume"]     # even the first task resumes
        assert pair[0]["prompt_len"] > 2000 * 4 and pair[0]["prompt_head"].startswith("BACKGROUND-FILL")
        assert pair[1]["prompt_head"].startswith("The repository has been reset")
        assert all(e["argv"][e["argv"].index("--model") + 1] == "sonnet[1m]" for e in pair)
    native_argv = next(e for e in es if e["arm"] == FA.NATIVE)["argv"]
    assert native_argv[native_argv.index("--tools") + 1].endswith(",Agent") and "--agents" in native_argv
    assert all("--agents" not in e["argv"] for e in es if e["arm"] != FA.NATIVE)
    rows = P.read_jsonl(a.out)
    assert len(rows) == 6
    for r in rows:
        assert r["ok"] is True and r["env_clean"] and r["cost_complete"] and r["invalid_reason"] is None
        assert r["lead_model"] == "sonnet[1m]" and r["fat_lead_model"] == "sonnet[1m]"
        assert r["fill_usd"] == .5 and r["usd"] == .1                 # the fill is apart from the task's spend
        assert r["lead_usd"] == pytest.approx(.1) and r["fill_cumulative_usd"] == .5 and r["lead_cumulative_usd"] == .6
        assert r["lead_previous_cumulative_usd"] == .5 and r["cost_cumulative_check"] is True
        assert r["fill_target_tokens"] == 2000 and r["fill_measured_tokens"] == 2000 and r["fill_ok"] is True
        assert r["fill_tier"] == "main" and r["fill_chars_per_token"] == 4.0 and r["fill_rc"] == 0
        assert r["fill_audit"] == {"clean": True} and r["audit"] == {"clean": True}
        assert r["fill_session_match"] is True and r["session_match"] is True
        assert r["context_first"] == 2050 and r["fill_reserved_usd"] == 1.0
        assert r["between_units"] == []
        assert r["claude_side_usd"] == .1                              # the lead-vendor spend of the task
    by = {r["arm"]: r for r in rows if r["task"] == ts[0]["id"]}
    assert (by[FA.SELF]["agent_calls"], by[FA.SELF]["ccx_calls"]) == (0, 0)
    assert (by[FA.NATIVE]["agent_calls"], by[FA.NATIVE]["ccx_calls"], by[FA.NATIVE]["worker_requests"]) == (1, 0, 1)
    assert (by[FA.CCX]["agent_calls"], by[FA.CCX]["ccx_calls"]) == (0, 1)
    assert all(r["arm_conformance"] is True for r in rows)
    events = [json.loads(x) for x in a.out.with_suffix(".events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "complete" and events[-1]["spent_known_usd"] == pytest.approx(6 * (.5 + .1))
    shown = P.summary(rows, 2)["fat"]
    assert set(shown["arms"]) == set(FA.ARMS) and shown["verdict"] == "Unknown"
    assert shown["arms"][FA.SELF]["fill"] == {"episodes": 2, "usd_known": 1.0, "usd_unknown": 0, "out_of_range": 0,
                                              "measured_tokens": [2000, 2000]}
    assert shown["arms"][FA.CCX]["arm_followed"] == 2 and shown["ratios_to_fatself"][FA.CCX]["claude_side"] == 1.0
    assert any(Path(a.out).parent.rglob("fill-streams")), "the fill stream is kept with the evidence"


def test_one_fill_per_episode_when_an_episode_has_several_tasks(fake_engine, monkeypatch, tmp_path):
    a, ts, log = fat_engine(fake_engine, monkeypatch, tmp_path)
    a.episode_size = 2
    units = P.schedule(ts[:2], 1, (FA.SELF,), 2)
    assert P.run_experiment(a, ts[:2], units) == 0
    es = entries(log)
    assert [(e["fill"], e["flag"]) for e in es] == [(True, "--session-id"), (False, "--resume"), (False, "--resume")]
    first, second = P.read_jsonl(a.out)
    assert "fill_usd" in first and "fill_usd" not in second
    assert first["usd"] == .1 and second["usd"] == .1 and second["lead_previous_cumulative_usd"] == .6
    assert second["context_first"] == 2100                   # the second task starts after the first one's turn
    events = [json.loads(x) for x in a.out.with_suffix(".events.jsonl").read_text().splitlines()]
    assert events[-1]["spent_known_usd"] == pytest.approx(.5 + .1 + .1)


def test_fill_is_reserved_before_the_first_task_and_the_budget_stops_before_a_cli(fake_engine, monkeypatch, tmp_path):
    a, ts, log = fat_engine(fake_engine, monkeypatch, tmp_path)
    a.budget = 2.49          # task 0.5 + 1.0 child + 1.0 fill = 2.5 reserved: one unit does not fit
    assert P.run_experiment(a, ts[:1], P.schedule(ts[:1], 1, (FA.CCX,), 1)) == 2
    assert not log.exists() and P.read_jsonl(a.out) == []
    stop = json.loads(a.out.with_suffix(".events.jsonl").read_text().splitlines()[-1])
    assert stop["reason"] == "budget" and stop["not_started"]["fill_allowance_usd"] == 1.0
    assert stop["not_started"]["reservation_usd"] == 1.5


def test_a_fill_outside_the_tolerance_marks_the_row_and_stops_the_run(fake_engine, monkeypatch, tmp_path):
    a, ts, log = fat_engine(fake_engine, monkeypatch, tmp_path, fill_chars_per_token=2.0)   # the fake assumes 4.0
    assert P.run_experiment(a, ts[:2], P.schedule(ts[:2], 1, FA.ARMS, 1)) == 2
    row, = P.read_jsonl(a.out)
    assert row["fill_ok"] is False and row["fill_measured_tokens"] == 1000 and row["fill_target_tokens"] == 2000
    assert row["invalid_reason"] == "fill_out_of_range"
    assert len(entries(log)) == 2          # the fill and the task of the first unit only
    event = json.loads(a.out.with_suffix(".events.jsonl").read_text().splitlines()[-1])
    assert event["reason"] == "fill_out_of_range"


def test_an_arm_the_lead_did_not_follow_is_an_invalid_row_that_is_kept(fake_engine, monkeypatch, tmp_path):
    monkeypatch.setenv("P4_FAKE_BEHAVE", FA.NATIVE)         # every lead calls the Agent tool, whatever its arm says
    a, ts, log = fat_engine(fake_engine, monkeypatch, tmp_path)
    assert P.run_experiment(a, ts[:1], P.schedule(ts[:1], 1, FA.ARMS, 1)) == 0
    rows = {r["arm"]: r for r in P.read_jsonl(a.out)}
    assert rows[FA.NATIVE]["invalid_reason"] is None and rows[FA.NATIVE]["arm_conformance"] is True
    assert rows[FA.SELF]["arm_conformance"] is False and rows[FA.SELF]["invalid_reason"] == "arm_not_followed"
    assert rows[FA.CCX]["arm_conformance"] is False and rows[FA.CCX]["invalid_reason"] == "arm_not_followed"
    assert P.summary(list(rows.values()), 1)["invalid_rows"]["by_reason"] == {"arm_not_followed": 2}
    assert P.summary(list(rows.values()), 1)["fat"]["arms"][FA.SELF]["arm_not_followed"] == 1


def test_a_failed_fill_is_an_environment_error_not_a_free_row(fake_engine, monkeypatch, tmp_path):
    monkeypatch.setenv("P4_FAKE_FILL_FAIL", "1")
    a, ts, log = fat_engine(fake_engine, monkeypatch, tmp_path)
    a.max_invalid_rows = None                               # round-1 rule: the first error stops
    assert P.run_experiment(a, ts[:2], P.schedule(ts[:2], 1, (FA.SELF,), 1)) == 2
    row, = P.read_jsonl(a.out)
    assert row["error"] == "RuntimeError" and row["environment_error"] is True and row["env_clean"] is False
    assert row["fill_rc"] == 3 and row["fill_session_match"] is False and row["ok"] is None
    assert not log.exists()      # the failed fill logged nothing and no task turn followed


def test_recompute_replays_the_fill_turn_and_keeps_the_task_cost(fake_engine, monkeypatch, tmp_path):
    a, ts, log = fat_engine(fake_engine, monkeypatch, tmp_path)
    assert P.run_experiment(a, ts[:2], P.schedule(ts[:2], 1, (FA.SELF,), 1)) == 0
    rows = P.read_jsonl(a.out)
    again = P.recompute_rows(rows)
    assert [r["lead_usd"] for r in again] == [r["lead_usd"] for r in rows]
    assert all(r["lead_usd"] == pytest.approx(.1) for r in again)
    assert [r["usd"] for r in again] == [.1, .1] and all(r["cost_cumulative_check"] for r in again)
    broken = [{**rows[0], "fill_model_usage": None}]
    assert P.recompute_rows(broken)[0]["lead_usd"] is None      # a fill that cannot be replayed fails closed


def test_old_arms_rows_carry_no_fat_fields_and_summary_has_no_fat_section(fake_engine):
    a, ts, log = fake_engine
    assert P.run_experiment(a, ts, P.schedule(ts)) == 0
    rows = P.read_jsonl(a.out)
    assert rows and not any(k.startswith(("fill_", "fat_")) or k in ("agent_calls", "arm_conformance") for r in rows for k in r)
    assert "fat" not in P.summary(rows, 4)
    assert P.invalid_reason({"arm": "self", "cost_complete": True}) is None


def test_the_cheap_first_arms_are_untouched(fake_engine):
    assert P.child_agent(type("A", (), {"child_agent": None})(), D.ARM2) == "claude"
    assert P.child_agent(None, "ccxlong") == "codex" and P.child_agent(None, "self") is None
    assert P.child_agent(None, FA.CCX) == "codex" and P.child_agent(None, FA.NATIVE) is None


def test_fill_prompt_is_not_read_by_ccx_context_as_a_decision_and_a_fill_with_tools_is_found():
    from ccx import context_share
    sentences = [s for s in context_share._SENT.split(FA.fill_prompt(2000)) if s.strip()]
    assert sentences and not any(context_share._DECIDED.search(s) for s in sentences)
    use = json.dumps({"type": "assistant", "message": {"id": "m", "content": [
        {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "ls"}}]}})
    sub = json.dumps({"type": "assistant", "parent_tool_use_id": "t", "message": {"id": "w", "content": [
        {"type": "tool_use", "id": "u", "name": "Read", "input": {}}]}})
    assert FA.tool_calls(use + "\n" + sub) == 1 and FA.tool_calls("") == 0


def test_native_arm_must_use_the_worker_agent():
    base = {"agent_calls": 1, "ccx_calls": 0, "worker_requests": 1}
    assert FA.conformance(FA.NATIVE, {**base, "agent_types": ["worker"]}) is True
    assert FA.conformance(FA.NATIVE, {**base, "agent_types": ["general-purpose"]}) is False
