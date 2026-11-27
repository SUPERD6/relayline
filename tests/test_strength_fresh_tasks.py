"""strength_retest with frozen new task files (issue #345): offline only, no real agent CLI, no personal home."""
import hashlib
import json
from _settings_arg import settings_arg
import os
from pathlib import Path
import subprocess
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import strength_retest as retest
import strength_runner as runner
import unified_summary as U

# Fingerprints of the default plans as they were before #345 (code_pin/dirty removed): no new flag -> same output.
DEFAULT_PLANS = {
    ("context", 3): "11051984831eeecc03b3b8e66e2a0c7743faa133fa35546d6a3908ee7fcfa9bd",
    ("context", 1): "50c948e10fa06dede57d5d9392ce18a8891770443637322df07e340df903b574",
    ("memory", 3): "36996f32f4b2665ed989d98fd5f437bbac39e40dea02e9b4e1fc6e13de4b0263",
    ("memory", 1): "dfdc517f867f245ccf99df2a69ab421e6b95682af9a391a4dd17274647f6f9c7",
}

HIDDEN = "from calc import f\n\ndef test_f():\n    assert f() == 1\n"


def context_file(tmp_path, n=3, neutral=(2,)):
    tasks = [{"id": f"r2-ctx-{i}", "files": {"calc.py": "def f():\n    return 0\n"},
              "brief": f"Task {i}: make f follow what we agreed.", "settle": f"Agreed: f returns 1 (task {i}).",
              "reversed": None if i % 2 else "Earlier idea: f returns 2.", "hidden": HIDDEN,
              "neutral": i in neutral, "source": "authored"} for i in range(n)]
    path = tmp_path / "a1.json"
    path.write_text(json.dumps({"kind": "context", "tasks": tasks}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def memory_file(tmp_path, n=2):
    tasks = [{"id": f"r2-mem-{i}", "files": {"calc.py": "def f():\n    return 0\n"},
              "brief": f"Task {i}: implement f.", "memory": f"Convention {i}: f returns 1.", "hidden": HIDDEN,
              "kind": "convention", "source": "authored"} for i in range(n)]
    path = tmp_path / "a2.json"
    path.write_text(json.dumps({"kind": "memory", "tasks": tasks,
                                "distractors": [["style", "Use tabs nowhere."]]}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(data):
    data = {k: v for k, v in data.items() if k not in ("code_pin", "dirty")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("kind,reps", sorted(DEFAULT_PLANS))
def test_default_plans_unchanged(kind, reps):
    assert fingerprint(retest.plan(kind, reps)) == DEFAULT_PLANS[(kind, reps)]


def test_context_tasks_file_lists_new_tasks_and_units(tmp_path):
    path, sha = context_file(tmp_path)
    data = retest.plan("context", 1, tasks=path, tasks_sha256=sha, agents=["codex"])
    assert data["task_ids"] == ["r2-ctx-0", "r2-ctx-1", "r2-ctx-2"] and data["tasks"] == 3
    assert data["tasks_sha256"] == sha and data["tasks_file"] == str(path.resolve())
    assert data["n"] == 3 * 2                       # tasks x arms, one agent, one rep
    assert {u["agent"] for u in data["units"]} == {"codex"} and {u["rep"] for u in data["units"]} == {1}
    assert data["neutral_tasks"] == ["r2-ctx-2"]
    assert set(data["subagent_tools"]) == {"codex"} and "web_search" in data["subagent_tools"]["codex"]
    assert [u["neutral"] for u in data["units"] if u["task"] == "r2-ctx-2"] == [True, True]
    assert {u["scenario"] for u in data["units"]} == {"neutral", "favourable"}
    assert data["cap_usd"] <= retest.FRESH_HARD_CAP_USD
    both = retest.plan("context", 2, tasks=path, tasks_sha256=sha, agents=["codex", "dsh"])
    assert both["n"] == 3 * 2 * 2 * 2


def test_claude_agent_and_memory_tasks_file(tmp_path):
    path, sha = memory_file(tmp_path)
    data = retest.plan("memory", 1, tasks=path, tasks_sha256=sha, agents=["claude"])
    assert data["n"] == 2 * 4 and data["task_ids"] == ["r2-mem-0", "r2-mem-1"]
    assert {(u["agent"], u["model"], u["effort"]) for u in data["units"]} == {("claude", "haiku", "low")}
    assert all(u["previously_used"] is False and u["source"] == "authored" for u in data["units"])
    assert "--as claude" in data["arms"]["hubstart"]
    ctx = retest.plan("context", 1, agents=["claude"])        # old tasks with a Claude sub-agent
    assert ctx["n"] == 7 * 2 and {u["model"] for u in ctx["units"]} == {"haiku"}


def test_sha_mismatch_and_bad_files_refused(tmp_path):
    path, sha = context_file(tmp_path)
    with pytest.raises(ValueError, match="SHA-256"):
        retest.plan("context", 1, tasks=path, tasks_sha256="0" * 64)
    with pytest.raises(ValueError, match="tasks-sha256"):
        retest.plan("context", 1, tasks=path)
    with pytest.raises(ValueError, match="kind"):
        retest.plan("memory", 1, tasks=path, tasks_sha256=sha)
    bad = json.loads(path.read_text(encoding="utf-8"))
    bad["tasks"][1]["id"] = bad["tasks"][0]["id"]
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        retest.plan("context", 1, tasks=path, tasks_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    del bad["tasks"][1]["neutral"]
    bad["tasks"][1]["id"] = "other"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="neutral"):
        retest.plan("context", 1, tasks=path, tasks_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="agent"):
        retest.plan("context", 1, agents=["gemini"])


def invoke(args, cwd):
    env = {**os.environ, "CCX_NO_LOCATE": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(EVAL / "strength_retest.py"), *args], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_cli_dry_run_and_limits(tmp_path):
    path, sha = context_file(tmp_path)
    ok = invoke(["execute", "context", "--dry-run", "--tasks", str(path), "--tasks-sha256", sha,
                 "--reps", "1", "--agents", "codex", "--unit-budget", "0.15", "--budget", "0.5"], tmp_path)
    assert ok.returncode == 0, ok.stderr
    data = json.loads(ok.stdout)
    assert data["n"] == 6 and data["unit_budget_usd"] == 0.15 and data["on_invalid"] == "continue"
    wrong = invoke(["plan", "context", "--tasks", str(path), "--tasks-sha256", "f" * 64], tmp_path)
    assert wrong.returncode == 2 and "SHA-256" in wrong.stderr
    over = invoke(["execute", "context", "--tasks", str(path), "--tasks-sha256", sha,
                   "--unit-budget", "0.2"], tmp_path)
    assert over.returncode == 2 and "unit budget" in over.stderr
    big = invoke(["execute", "context", "--tasks", str(path), "--tasks-sha256", sha,
                  "--budget", str(retest.FRESH_HARD_CAP_USD + 1)], tmp_path)
    assert big.returncode == 2 and "budget" in big.stderr
    old = invoke(["execute", "context", "--dry-run"], tmp_path)
    assert old.returncode == 0 and "on_invalid" not in json.loads(old.stdout)   # old output unchanged
    nohome = invoke(["execute", "context", "--run", "--budget", "0.5", "--out", str(tmp_path / "o"),
                     "--tasks", str(path), "--tasks-sha256", sha, "--agents", "claude"], tmp_path)
    assert nohome.returncode == 2 and "--claude-home" in nohome.stderr and not (tmp_path / "o").exists()


def test_claude_home_check_by_existence_only(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="--claude-home"):
        retest.checked_claude_home("")
    home = tmp_path / "claude-eval"
    with pytest.raises(ValueError, match="not a folder"):
        retest.checked_claude_home(str(home))
    home.mkdir()
    with pytest.raises(ValueError, match="login"):
        retest.checked_claude_home(str(home))
    (home / ".credentials.json").write_text("not read", encoding="utf-8")
    real = runner.PF.real_paths()
    monkeypatch.setattr(runner.PF, "real_paths", lambda: {**real, "claude_home": home})
    with pytest.raises(ValueError, match="your own"):
        retest.checked_claude_home(str(home))
    monkeypatch.setattr(runner.PF, "real_paths", lambda: {**real, "claude_home": tmp_path})   # home inside it
    with pytest.raises(ValueError, match="overlaps"):
        retest.checked_claude_home(str(home))
    monkeypatch.setattr(runner.PF, "real_paths", lambda: real)
    assert retest.checked_claude_home(str(home)) == home.resolve()
    (home / "CLAUDE.md").write_text("reaches every run", encoding="utf-8")
    with pytest.raises(ValueError, match="CLAUDE.md"):
        retest.checked_claude_home(str(home))
    with pytest.raises(ValueError, match="absolute"):
        retest.checked_claude_home("relative/home")


def test_unit_env_homes_and_no_web(tmp_path):
    codex_home, claude_home = tmp_path / "cx", tmp_path / "cl"
    claude = runner.unit_env({"agent": "claude"}, tmp_path / "u1", codex_home, claude_home, fresh=True)
    assert claude["CLAUDE_CONFIG_DIR"] == str(claude_home)
    deny = json.loads(claude["CCX_CLAUDE_SETTINGS"])["permissions"]["deny"]
    assert {"WebFetch", "WebSearch"} <= set(deny)
    codex = runner.unit_env({"agent": "codex"}, tmp_path / "u2", codex_home, claude_home, fresh=True)
    assert codex["CODEX_HOME"] == str(codex_home) and codex["CLAUDE_CONFIG_DIR"] == str(tmp_path / "u2" / "claude-home")
    tiers = runner.Paths(Path(codex["CCX_HUB"])).user_tiers
    assert "codex_lean_tools = true" in tiers.read_text(encoding="utf-8")
    old = runner.unit_env({"agent": "codex"}, tmp_path / "u3", codex_home, None, fresh=False)
    assert (tmp_path / "u3" / "config.toml").read_text(encoding="utf-8") == ""
    assert not runner.Paths(Path(old["CCX_HUB"])).user_tiers.exists()
    assert "CCX_CLAUDE_SETTINGS" not in old
    with pytest.raises(ValueError, match="Claude home"):
        runner.unit_env({"agent": "claude"}, tmp_path / "u4", None, None, fresh=True)


def fake_rows(monkeypatch, outcomes):
    """run_unit replaced: each unit's row comes from `outcomes` in order (no CLI is started)."""
    seen = []

    def fake(unit, kind, dest, budget, codex_home=None, claude_home=None, tasks=None, fresh=False, **_):
        row = {**unit, "ok": False, "usd": 0.01, **outcomes[len(seen)]}
        seen.append(unit)
        return row
    monkeypatch.setattr(runner, "run_unit", fake)
    return seen


def manifest(tmp_path, on_invalid):
    path, sha = context_file(tmp_path, n=4)
    data = retest.plan("context", 1, tasks=path, tasks_sha256=sha, agents=["dsh"])
    data["on_invalid"] = on_invalid
    return data


def test_invalid_rows_recorded_and_group_continues(tmp_path, monkeypatch):
    data = manifest(tmp_path, "continue")
    seen = fake_rows(monkeypatch, [{"error": "OSError", "usd": 0.0}, {"status": "error", "kind": "crash"},
                                   # the receipt of a sub-agent's own timeout (ccx: no result -> status error)
                                   {"status": "error", "kind": "timeout", "ok": True, "usd": 0.02}]
                     + [{"ok": True}] * 5)
    report = runner.execute(data, tmp_path / "out", 1.0, 0.1)
    assert len(seen) == data["n"] == 8 and not report["budget_stopped"]
    assert [r["invalid"] for r in report["rows"][:3]] == [True, True, False]
    assert report["invalid"] == 2 and report["successes"] == 5
    timed = report["rows"][2]
    assert timed["ok"] is False and timed["hidden_ok"] is True and timed["arm_limit"] == "timeout"
    assert U.valid(timed) and not U.valid(report["rows"][1])     # the summary agrees with the runner
    lines = (tmp_path / "out" / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 8


def test_auth_receipt_is_an_environment_stop(tmp_path, monkeypatch):
    data = manifest(tmp_path, "continue")
    seen = fake_rows(monkeypatch, [{"ok": True}, {"status": "error", "kind": "auth", "ok": None}] + [{}] * 6)
    report = runner.execute(data, tmp_path / "out", 1.0, 0.1)
    assert len(seen) == 2 and report["budget_stopped"] and "auth" in report["stop_reason"]


def test_fourth_unknown_cost_stops(tmp_path, monkeypatch):
    data = manifest(tmp_path, "continue")
    seen = fake_rows(monkeypatch, [{"usd": None}, {"ok": True}, {"usd": None}, {"usd": None}, {"usd": None},
                                   {"ok": True}, {"ok": True}, {"ok": True}])
    report = runner.execute(data, tmp_path / "out", 1.0, 0.1)
    assert len(seen) == 5 and report["budget_stopped"] and "Unknown cost" in report["stop_reason"]
    assert report["charged_usd"] == pytest.approx(0.01 + 4 * 0.1)


def test_default_mode_still_stops_on_first_error(tmp_path, monkeypatch):
    data = manifest(tmp_path, "stop")
    seen = fake_rows(monkeypatch, [{"ok": True}, {"error": "OSError"}] + [{"ok": True}] * 6)
    report = runner.execute(data, tmp_path / "out", 1.0, 0.1)
    assert len(seen) == 2 and report["budget_stopped"] and "invalid" not in report["rows"][0]


def test_execute_rechecks_task_file(tmp_path, monkeypatch):
    data = manifest(tmp_path, "continue")
    Path(data["tasks_file"]).write_text("{}", encoding="utf-8")
    fake_rows(monkeypatch, [{}] * 8)
    with pytest.raises(ValueError, match="SHA-256"):
        runner.execute(data, tmp_path / "out", 1.0, 0.1)
    assert not (tmp_path / "out").exists()


def test_synthetic_transcript_for_claude_unit_has_its_own_session(tmp_path):
    home = tmp_path / "claude"
    a = runner.write_lead_transcript({"files": {"x.py": ""}, "settle": "s", "reversed": None}, home, "u-0001")
    b = runner.write_lead_transcript({"files": {"x.py": ""}, "settle": "s", "reversed": None}, home, "u-0002")
    assert a[0] != b[0] and a[1].parent == b[1].parent and a[1].is_file() and b[1].is_file()
    assert a[1].is_relative_to(home / "projects")


def test_summary_subset_uses_row_neutral_flag():
    rows = [{"task": t, "arm": arm, "agent": "claude", "rep": 1, "ok": ok, "usd": 0.01, "neutral": t == "n1"}
            for t in ("s1", "s2", "n1") for arm, ok in (("on", True), ("off", t == "s2"))]
    settled = U.strength(rows, ("on", "off"), "settled")
    assert settled["pair"]["n_pairs"] == 2 and settled["pair"]["b"] == 1
    neutral = U.strength(rows, ("on", "off"), "neutral")
    assert neutral["subset"] == "neutral" and neutral["pair"]["n_pairs"] == 1
    old = [{"task": "t7-neutral", "arm": "on", "ok": True, "usd": 0.0, "rep": 1}]
    assert U.strength(old, subset="neutral")["arms"]["on"]["attempted"] == 1
    assert U.strength(old, subset="settled")["arms"] == {}


ROOT = EVAL.parents[1]
GOOD = "calc.py=def f():\n    return 1\n"


def fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(ROOT / "tests/fakes/fake_claude.py"))
    monkeypatch.setenv("CCX_CODEX_BIN", str(ROOT / "tests/fakes/fake_codex.py"))
    monkeypatch.setenv("CCX_NO_LOCATE", "1")
    monkeypatch.setenv("FAKE_WRITE", GOOD)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    return log


def calls(log, agent):
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if json.loads(x)["agent"] == agent]


def test_claude_context_unit_end_to_end_with_fake(tmp_path, monkeypatch):
    """A Claude unit on a frozen task: the logged-in home is its CLAUDE_CONFIG_DIR, the lead transcript there is read
    into the prompt (context on), web tools are denied, the hidden test scores the result."""
    log = fake_env(monkeypatch, tmp_path)
    path, sha = context_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "context")
    home = tmp_path / "claude-eval"
    home.mkdir()
    unit = {"task": "r2-ctx-0", "arm": "on", "agent": "claude", "model": "haiku", "effort": "low", "rep": 1}
    row = runner.run_unit(unit, "context", tmp_path / "u", .1, None, claude_home=home, tasks=tasks, fresh=True)
    assert "error" not in row and row["ok"] is True, row
    assert row["note_in_prompt"] is True and Path(row["lead_transcript"]).is_relative_to(home)
    argv = calls(log, "claude")[-1]["argv"]
    settings = settings_arg(argv)
    assert {"WebFetch", "WebSearch"} <= set(settings["permissions"]["deny"])
    assert argv[argv.index("--model") + 1] == "haiku"


def test_fresh_codex_unit_has_web_search_disabled(tmp_path, monkeypatch):
    log = fake_env(monkeypatch, tmp_path)
    path, sha = memory_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "memory")
    home = tmp_path / "eval-codex-home"
    home.mkdir()
    (home / "auth.json").write_text("", encoding="utf-8")
    unit = {"task": "r2-mem-0", "arm": "hubmem", "agent": "codex", "model": "gpt-6-luna", "effort": "low", "rep": 1}
    row = runner.run_unit(unit, "memory", tmp_path / "u", .1, home, tasks=tasks, fresh=True)
    assert "error" not in row and row["ok"] is True, row
    argv = calls(log, "codex")[-1]["argv"]
    assert 'web_search="disabled"' in argv
    old = runner.run_unit(unit | {"task": "mem-errors"}, "memory", tmp_path / "old", .1, home)
    assert 'web_search="disabled"' not in calls(log, "codex")[-1]["argv"], old


def test_task_file_paths_stay_in_repo(tmp_path):
    path, _ = context_file(tmp_path, n=1)
    for bad in ("../escape.py", "test_task.py", "sub/test_zz_hidden_eval.py"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tasks"][0]["files"] = {bad: "x = 1\n"}
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError, match="inside the repo"):
            retest.load_tasks(path, hashlib.sha256(path.read_bytes()).hexdigest(), "context")


def test_claude_settings_merged_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("CCX_CLAUDE_SETTINGS", json.dumps({"permissions": {"deny": ["Read(//secret/**)"]},
                                                          "hooks": {}}))
    env = runner.unit_env({"agent": "claude"}, tmp_path / "u", None, tmp_path / "cl", fresh=True)
    merged = json.loads(env["CCX_CLAUDE_SETTINGS"])
    assert set(merged["permissions"]["deny"]) == {"Read(//secret/**)", "WebFetch", "WebSearch"}
    assert merged["hooks"] == {}
