"""#470: the logged-in homes every unit shares keep earlier units' session records (a Codex home's sessions/,
archived_sessions/, history.jsonl, state and log databases; a Claude home's projects/<other unit>/, file-history/,
todos/ ...). Their prompts and tool results hold an on or mem arm's answer, and the audit masked the whole home as
the unit's own. Now every unit is audited (and a Claude unit denied) on the parts that are not its own. Fake CLIs only.
"""
import fnmatch
import json
import os
from pathlib import Path
import sys

import pytest

from test_strength_fresh_tasks import EVAL, calls, fake_env, memory_file

sys.path.insert(0, str(EVAL))
import strength_retest as retest  # noqa: E402
import strength_runner as runner  # noqa: E402

PF = runner.PF
CODEX = {"agent": "codex", "model": retest.AGENT_MODELS["codex"][0], "effort": "low", "rep": 1}
CLAUDE = {"agent": "claude", "model": "haiku", "effort": "low", "rep": 1}


def homes(tmp_path):
    codex = tmp_path / "eval-codex-home"
    claude = tmp_path / "claude-eval"
    for h in (codex, claude):
        h.mkdir(exist_ok=True)
    (codex / "auth.json").write_text("", encoding="utf-8")
    return codex, claude


def unit(tmp_path, index=1):
    dest = tmp_path / "out" / f"unit-{index:04d}"
    (dest / "repo").mkdir(parents=True, exist_ok=True)
    return dest, runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())


@pytest.mark.parametrize("rel", ["sessions/2026/11/19/rollout-2026-11-19T10-00-00-0000aaaa.jsonl",
                                 "archived_sessions/rollout-x-0000aaaa.jsonl", "history.jsonl", "state_5.sqlite",
                                 "logs_2.sqlite", "memories/notes.md"])
def test_codex_home_records_of_other_units_are_hits(tmp_path, rel):
    codex, _ = homes(tmp_path)
    _dest, u = unit(tmp_path)
    target = codex / rel
    for call in (f"cat {target.as_posix()}", {"file_path": str(target)}, f"Get-Content {target}"):
        assert runner.audit_hits([json.dumps(call)], u, (codex,)), (rel, call)


@pytest.mark.parametrize("rel", ["projects/D--eval-out-unit-0000-repo/1234.jsonl",
                                 "projects/D--eval-out-unit-0000-repo/1234/tool-results/t1.txt",
                                 "projects/D--other-run-unit-0007-repo/9.jsonl", "file-history/9/calc.py@v1",
                                 "todos/9-agent.json", "history.jsonl", "shell-snapshots/s.sh", "session-env/9/x"])
def test_claude_home_records_of_other_units_are_hits(tmp_path, rel):
    _, claude = homes(tmp_path)
    _dest, u = unit(tmp_path)
    target = claude / rel
    assert runner.audit_hits([json.dumps({"file_path": str(target)})], u, (claude,)), rel
    assert runner.audit_hits([json.dumps(f"cat {target.as_posix()}")], u, (claude,)), rel


def test_reaching_the_shared_home_by_cd_or_search_is_a_hit(tmp_path):
    codex, claude = homes(tmp_path)
    _dest, u = unit(tmp_path)
    for call in (f"cd {codex.as_posix()} && cat sessions/2026/11/19/r.jsonl", f"rg -n Agreed {codex.as_posix()}",
                 {"pattern": "Agreed", "path": str(claude / "projects")}):
        assert runner.audit_hits([json.dumps(call)], u, (codex, claude)), call


def test_own_session_records_are_not_hits(tmp_path):
    """The unit's own Claude project folders (its repo and its ccx worktrees) and its own Codex rollout."""
    codex, claude = homes(tmp_path)
    dest, u = unit(tmp_path)
    proj = claude / "projects"
    mine = [proj / PF.slug(u.repo) / "abc.jsonl", proj / PF.slug(u.repo) / "abc" / "tool-results" / "t1.txt",
            proj / (PF.slug(u.worktrees) + "-run1") / "abc" / "tool-results" / "t2.txt"]
    rollout = codex / "sessions" / "2026" / "11" / "19" / "rollout-2026-11-19T10-00-00-0000bbbb.jsonl"
    calls_ = [json.dumps({"file_path": str(p)}) for p in mine] + [json.dumps(f"cat {rollout.as_posix()}")]
    assert runner.audit_hits(calls_, u, (codex, claude), own=(rollout,)) == []
    # Not records: the login and config files Codex itself reads; the unit's own repo
    fine = [json.dumps({"file_path": str(dest / "repo" / "calc.py")}), json.dumps("python -m pytest -q")]
    assert runner.audit_hits(fine, u, (codex, claude)) == []


def test_own_codex_rollouts_found_by_the_runs_session_ids(tmp_path):
    codex, _ = homes(tmp_path)
    dest, u = unit(tmp_path)
    run = dest / "hub" / "ccx" / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"session_id": "0000bbbb", "attempts": [{"session_id": "0000cccc"}]}),
                                  encoding="utf-8")
    day = codex / "sessions" / "2026" / "11" / "19"
    day.mkdir(parents=True)
    for sid in ("0000bbbb", "0000cccc", "0000aaaa"):
        (day / f"rollout-2026-11-19T10-00-00-{sid}.jsonl").write_text("{}\n", encoding="utf-8")
    got = sorted(p.name for p in runner.own_sessions(dest / "hub", codex))
    assert got == ["rollout-2026-11-19T10-00-00-0000bbbb.jsonl", "rollout-2026-11-19T10-00-00-0000cccc.jsonl"]


def test_codex_unit_reading_another_units_rollout_is_unclean_end_to_end(tmp_path, monkeypatch):
    fake_env(monkeypatch, tmp_path)
    path, sha = memory_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "memory")
    codex, _ = homes(tmp_path)
    other = codex / "sessions" / "2026" / "11" / "19" / "rollout-2026-11-19T10-00-00-0000aaaa.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text('{"payload": "Convention 0: f returns 1."}\n', encoding="utf-8")
    u = {"task": "r2-mem-0", "arm": "nomem", **CODEX}
    monkeypatch.setenv("FAKE_COMMANDS", "python -m pytest -q\ncat calc.py")
    ok = runner.run_unit(u, "memory", tmp_path / "out" / "unit-0001", .1, codex, tasks=tasks, fresh=True,
                         hidden=runner.isolation_paths(path))
    assert ok["path_audit"]["clean"] is True, ok
    monkeypatch.setenv("FAKE_COMMANDS", f"cat {other.as_posix()}")
    bad = runner.run_unit(u, "memory", tmp_path / "out" / "unit-0002", .1, codex, tasks=tasks, fresh=True,
                          hidden=runner.isolation_paths(path))
    assert bad["path_audit"]["clean"] is False, bad


def test_claude_unit_denied_other_units_records(tmp_path, monkeypatch):
    log = fake_env(monkeypatch, tmp_path)
    _, claude = homes(tmp_path)
    out = tmp_path / "out"
    runner.run_unit({"task": "mem-errors", "arm": "nomem", **CLAUDE}, "memory", out / "unit-0012", .1, None,
                    claude_home=claude)
    argv = calls(log, "claude")[-1]["argv"]
    deny = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
    h = PF._rule_path(claude.resolve())
    for rule in (f"Read({h}/projects/*/*.jsonl)", f"Read({h}/file-history/**)", f"Read({h}/history.jsonl)",
                 f"Read({h}/todos/**)", f"Read({h}/projects/*/*/subagents/**)"):
        assert rule in deny, rule
    # The run's earlier units' project folders (their tool results), never this unit's own
    proj = [d[len(f"Read({h}/projects/"):-len("/**)")] for d in deny if d.startswith(f"Read({h}/projects/")
            and d.endswith("/**)") and "unit-" in d]
    own = PF.slug((out / "unit-0012" / "repo").resolve())
    earlier = PF.slug((out / "unit-0011" / "repo").resolve())
    assert any(fnmatch.fnmatchcase(earlier, g) for g in proj), proj
    assert not any(fnmatch.fnmatchcase(own, g) for g in proj), proj
    assert not any(fnmatch.fnmatchcase(own.replace("-repo", "--ccx-worktrees-repo-r1"), g) for g in proj)


def test_claude_settings_stay_under_the_limit_for_the_last_a2_unit(tmp_path, monkeypatch):
    fake_env(monkeypatch, tmp_path)
    _, claude = homes(tmp_path)
    out = tmp_path / "eval-dir-with-a-longish-name-470" / "r2-a2"
    row = runner.run_unit({"task": "mem-errors", "arm": "nomem", **CLAUDE}, "memory", out / "unit-0191", .1, None,
                          claude_home=claude)
    assert "error" not in row, row
