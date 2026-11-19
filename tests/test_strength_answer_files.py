"""#467: an arm that must not get the answer has no answer-level file in its unit, and no unit may read another
unit's folder (an on arm's shared-context.md, a mem arm's notes) or the run's manifest.json / results.jsonl. The
dry run lists each arm's answer-level files. Fake CLIs only."""
import fnmatch
import json
import os
from pathlib import Path
import sys

import pytest

from test_strength_fresh_tasks import EVAL, calls, context_file, fake_env, memory_file

sys.path.insert(0, str(EVAL))
import strength_retest as retest  # noqa: E402
import strength_runner as runner  # noqa: E402

PF = runner.PF
CODEX = {"agent": "codex", "model": retest.AGENT_MODELS["codex"][0], "effort": "low", "rep": 1}
CLAUDE = {"agent": "claude", "model": "haiku", "effort": "low", "rep": 1}


def codex_home(tmp_path):
    home = tmp_path / "eval-codex-home"
    home.mkdir(exist_ok=True)
    (home / "auth.json").write_text("", encoding="utf-8")
    return home


def claude_home(tmp_path):
    home = tmp_path / "claude-eval"
    home.mkdir(exist_ok=True)
    return home


def holding(root: Path, text: str) -> list[str]:
    """Files under `root` whose text holds `text`, relative posix paths."""
    out = []
    for f in root.rglob("*"):
        if f.is_file():
            try:
                if text in f.read_text(encoding="utf-8", errors="replace"):
                    out.append(f.relative_to(root).as_posix())
            except OSError:
                pass
    return sorted(out)


def declared(found: list[str], kind: str, arm: str, agent: str) -> list[str]:
    """The found files the dry run's answer_files for this arm does not list."""
    pats = [p.split(" ")[0] for p in runner.answer_files(kind, arm, agent)]
    return [f for f in found if not any(fnmatch.fnmatch(f, p) for p in pats)]


# ------------------------------------------------------------------ (1) no answer in an off arm's unit


def test_off_arm_unit_holds_no_lead_transcript_or_answer(tmp_path, monkeypatch):
    """Round 1: every off unit kept claude-home/projects/lead/strength-synthetic-lead.jsonl (the agreed answer)."""
    fake_env(monkeypatch, tmp_path)
    path, sha = context_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "context")
    settle = tasks[0]["settle"]
    home = codex_home(tmp_path)
    off = runner.run_unit({"task": "r2-ctx-0", "arm": "off", **CODEX}, "context", tmp_path / "out" / "unit-0000",
                          .1, home, tasks=tasks, fresh=True, hidden=runner.isolation_paths(path))
    assert "error" not in off, off
    dest = tmp_path / "out" / "unit-0000"
    assert not (dest / "claude-home" / "projects" / "lead" / "strength-synthetic-lead.jsonl").exists()
    assert holding(dest, settle) == []
    assert runner.answer_files("context", "off", "codex") == []
    # The on arm still gets its transcript (ccx reads it), and every file holding the answer is listed
    on = runner.run_unit({"task": "r2-ctx-0", "arm": "on", **CODEX}, "context", tmp_path / "out" / "unit-0001",
                         .1, home, tasks=tasks, fresh=True, hidden=runner.isolation_paths(path))
    assert on["note_in_prompt"] is True, on
    found = holding(tmp_path / "out" / "unit-0001", settle)
    assert "claude-home/projects/lead/strength-synthetic-lead.jsonl" in found
    assert declared(found, "context", "on", "codex") == []


def test_claude_off_arm_writes_no_transcript_and_the_folder_is_denied(tmp_path, monkeypatch):
    """A Claude unit's transcript lives in the shared logged-in home, which the audit masked as the unit's own."""
    log = fake_env(monkeypatch, tmp_path)
    path, sha = context_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "context")
    home = claude_home(tmp_path)
    synth = home / "projects" / runner.SYNTHETIC_LEAD_FOLDER
    out = tmp_path / "out"
    off = runner.run_unit({"task": "r2-ctx-0", "arm": "off", **CLAUDE}, "context", out / "unit-0000", .1, None,
                          claude_home=home, tasks=tasks, fresh=True, hidden=runner.isolation_paths(path))
    assert "error" not in off and "lead_transcript" not in off, off
    assert not synth.exists() or not any(synth.iterdir())
    argv = calls(log, "claude")[-1]["argv"]
    deny = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
    assert f"Read({PF._rule_path(synth.resolve())}/**)" in deny
    on = runner.run_unit({"task": "r2-ctx-0", "arm": "on", **CLAUDE}, "context", out / "unit-0001", .1, None,
                         claude_home=home, tasks=tasks, fresh=True, hidden=runner.isolation_paths(path))
    mine = Path(on["lead_transcript"])
    assert on["note_in_prompt"] is True and mine.parent == synth, on
    assert on["path_audit"]["clean"] is True, on
    # A later off unit reading that transcript is a hit; the on unit reading its own is not
    monkeypatch.setenv("FAKE_TOOL_INPUT", json.dumps({"name": "Read", "input": {"file_path": str(mine)}}))
    peek = runner.run_unit({"task": "r2-ctx-0", "arm": "off", **CLAUDE}, "context", out / "unit-0002", .1, None,
                           claude_home=home, tasks=tasks, fresh=True, hidden=runner.isolation_paths(path))
    assert peek["path_audit"]["clean"] is False, peek
    hidden = (*runner.isolation_paths(path), *runner.aliases(synth))
    u = runner.isolation_unit(out / "unit-0001", out / "unit-0001" / "hub", hidden)
    read = json.dumps({"file_path": str(mine)})
    assert runner.audit_hits([read], u, (home,), own=(mine,)) == []
    assert runner.audit_hits([read], u, (home,))


# ------------------------------------------------------------------ (2) sibling units and the run's own files


def sibling_layout(tmp_path):
    out = tmp_path / "out"
    ctx = out / "unit-0000" / "hub" / "ccx" / "runs" / "r1" / "shared-context.md"
    ctx.parent.mkdir(parents=True)
    ctx.write_text("Agreed: f returns 1.\n", encoding="utf-8")
    for f in ("manifest.json", "results.jsonl"):
        (out / f).write_text("{}\n", encoding="utf-8")
    dest = out / "unit-0001"
    (dest / "repo").mkdir(parents=True)
    own = dest / "hub" / "ccx" / "runs" / "r2" / "shared-context.md"
    own.parent.mkdir(parents=True)
    own.write_text("Agreed: f returns 1.\n", encoding="utf-8")
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    return out, dest, ctx, own, u


@pytest.mark.parametrize("spell", ["abs", "abs-backslash", "json-read", "rel", "cd-out", "manifest", "results",
                                   "search-out"])
def test_reading_a_sibling_unit_or_the_runs_files_is_a_hit(tmp_path, spell):
    out, dest, ctx, _own, u = sibling_layout(tmp_path)
    call = {"abs": f"cat {ctx.as_posix()}",
            "abs-backslash": f"type {ctx}",
            "json-read": {"file_path": str(ctx)},
            "rel": "cat ../../unit-0000/hub/ccx/runs/r1/shared-context.md",
            "cd-out": f"cd {out.as_posix()} && cat unit-0000/hub/ccx/runs/r1/shared-context.md",
            "manifest": f"cat {(out / 'manifest.json').as_posix()}",
            "results": {"file_path": str(out / "results.jsonl")},
            "search-out": {"pattern": "Agreed", "path": str(out)}}[spell]
    text = json.dumps(call)
    assert runner.audit_hits([text], u, out=out), spell


def test_sibling_read_through_a_junction_is_a_hit(tmp_path):
    out, dest, ctx, _own, u = sibling_layout(tmp_path)
    link = tmp_path / "out-link-467"
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(out), str(link))
        else:
            os.symlink(out, link, target_is_directory=True)
    except (OSError, AttributeError, ImportError) as e:
        pytest.skip(f"no junction/symlink here: {e}")
    via = link / "unit-0000" / "hub" / "ccx" / "runs" / "r1" / "shared-context.md"
    assert runner.audit_hits([json.dumps(f"cat {via.as_posix()}")], u, out=link)
    assert runner.audit_hits([json.dumps(f"cat {ctx.as_posix()}")], u, out=link)     # the resolved spelling too


def test_own_repo_and_own_shared_context_are_not_hits(tmp_path):
    """The on arm reading its own shared-context.md or memory is legitimate."""
    out, dest, _ctx, own, u = sibling_layout(tmp_path)
    fine = [f"cat {own.as_posix()}", {"file_path": str(own)}, {"file_path": str(dest / "repo" / "calc.py")},
            {"pattern": "def", "path": str(dest / "repo")}, "cat calc.py", "python -m pytest -q", "rg -n f .",
            f"cat {(dest / 'repo' / '.ccx' / 'context.md').as_posix()}", f"ls {(dest / 'hub').as_posix()}"]
    assert runner.audit_hits([json.dumps(x) for x in fine], u, out=out) == []


def test_codex_unit_reading_a_sibling_is_unclean_end_to_end(tmp_path, monkeypatch):
    """run_unit passes the run's --out (the unit folder's parent) to the audit."""
    fake_env(monkeypatch, tmp_path)
    path, sha = memory_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "memory")
    home = codex_home(tmp_path)
    out = tmp_path / "out"
    unit = {"task": "r2-mem-0", "arm": "nomem", **CODEX}
    first = runner.run_unit({**unit, "arm": "hubmem"}, "memory", out / "unit-0000", .1, home, tasks=tasks,
                            fresh=True, hidden=runner.isolation_paths(path))
    assert first["path_audit"]["clean"] is True, first
    (out / "results.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_COMMANDS", f"cat {(out / 'unit-0000' / 'hub').as_posix()}/memory/*")
    bad = runner.run_unit(unit, "memory", out / "unit-0001", .1, home, tasks=tasks, fresh=True,
                          hidden=runner.isolation_paths(path))
    assert bad["path_audit"]["clean"] is False, bad
    monkeypatch.setenv("FAKE_COMMANDS", f"cat {(out / 'results.jsonl').as_posix()}")
    bad = runner.run_unit(unit, "memory", out / "unit-0002", .1, home, tasks=tasks, fresh=True,
                          hidden=runner.isolation_paths(path))
    assert bad["path_audit"]["clean"] is False, bad


@pytest.mark.parametrize("index", [0, 1, 9, 10, 42, 100, 191, 1000, 1234])
def test_sibling_globs_match_exactly_the_earlier_units(index):
    """Claude deny rules: a few folder globs cover unit-0000 .. unit-<index-1>, never the unit itself or a later one
    (one rule per sibling would overflow the command line ccx passes --settings on)."""
    globs = runner.sibling_globs(index)
    assert len(globs) <= 40
    for i in range(0, max(index + 30, 60)):
        name = f"unit-{i:04d}"
        assert any(fnmatch.fnmatchcase(name, g) for g in globs) is (i < index), (index, name, globs)


def test_claude_unit_denied_the_runs_files_and_earlier_units(tmp_path, monkeypatch):
    log = fake_env(monkeypatch, tmp_path)
    home = claude_home(tmp_path)
    out = tmp_path / "out"
    unit = {"task": "mem-errors", "arm": "nomem", **CLAUDE}
    runner.run_unit(unit, "memory", out / "unit-0012", .1, None, claude_home=home)
    argv = calls(log, "claude")[-1]["argv"]
    deny = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
    r = PF._rule_path(out.resolve())
    for f in ("manifest.json", "results.jsonl"):
        assert f"Read({r}/{f})" in deny and f"Edit({r}/{f})" in deny
    sib = [d[len(f"Read({r}/"):-len("/**)")] for d in deny if d.startswith(f"Read({r}/unit-")]
    assert any(fnmatch.fnmatchcase("unit-0011", g) for g in sib)
    assert not any(fnmatch.fnmatchcase("unit-0012", g) for g in sib)


# ------------------------------------------------------------------ (3) the dry run lists answer-level files


def test_dry_run_lists_answer_files_per_arm(tmp_path):
    path, sha = context_file(tmp_path)
    iso = retest.plan("context", 1, tasks=path, tasks_sha256=sha, agents=["claude"])["isolation"]
    files = iso["answer_files"]
    assert files["off"] == [] and files["on"]
    assert any(runner.SYNTHETIC_LEAD_FOLDER in f for f in files["on"])
    assert {"manifest.json", "results.jsonl"} <= set(iso["siblings"]["run_files"])
    path, sha = memory_file(tmp_path)
    files = retest.plan("memory", 1, tasks=path, tasks_sha256=sha, agents=["codex"])["isolation"]["answer_files"]
    assert files["nomem"] == [] and all(files[a] for a in ("mem", "hubmem", "hubstart"))


@pytest.mark.parametrize("arm", ["nomem", "mem", "hubmem", "hubstart"])
def test_memory_arms_hold_only_the_listed_answer_files(tmp_path, monkeypatch, arm):
    fake_env(monkeypatch, tmp_path)
    path, sha = memory_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "memory")
    dest = tmp_path / "out" / "unit-0000"
    row = runner.run_unit({"task": "r2-mem-0", "arm": arm, **CODEX}, "memory", dest, .1, codex_home(tmp_path),
                          tasks=tasks, fresh=True, hidden=runner.isolation_paths(path))
    assert "error" not in row, row
    found = holding(dest, tasks[0]["memory"])
    assert (found == []) is (arm == "nomem"), found
    assert declared(found, "memory", arm, "codex") == []
