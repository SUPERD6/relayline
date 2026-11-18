"""#454: strength_retest units are kept away from the run's own checkout, the task data and every --hide path:
Claude deny rules, a tool-call audit (the P4 path_hits rules plus content patterns, alias spellings and recursive
searches of a parent folder) and the forbidden list in the dry run. Fake CLIs only."""
import json
import os
from pathlib import Path
import sys

import pytest

from test_strength_fresh_tasks import EVAL, ROOT, calls, context_file, fake_env, fake_rows, invoke, memory_file

sys.path.insert(0, str(EVAL))
import strength_retest as retest  # noqa: E402
import strength_runner as runner  # noqa: E402

PF = runner.PF


def norm(paths):
    return [os.path.normcase(str(p)) for p in paths]


def dev_checkout(tmp_path):
    """A stand-in for another local relayline checkout with authored tasks' answers."""
    d = tmp_path / "dev-checkout-454"
    (d / "scripts" / "eval" / "round2_a").mkdir(parents=True)
    (d / "scripts" / "eval" / "round2_a" / "spec.py").write_text("x = 1\n", encoding="utf-8")
    return d


def test_plan_with_tasks_lists_checkout_data_and_task_file(tmp_path):
    path, sha = context_file(tmp_path)
    iso = retest.plan("context", 1, tasks=path, tasks_sha256=sha, agents=["claude"])["isolation"]
    got = norm(iso["forbidden_paths"])
    for p in (ROOT, ROOT / "scripts" / "eval", ROOT / "docs" / "research" / "data", path.resolve()):
        assert os.path.normcase(str(p)) in got, p
    assert iso["hide"] == [] and "codex" in iso["note"].lower()
    assert iso["content_patterns"]                      # the audit's path-independent patterns are printed too


def test_cli_hide_resolved_deduplicated_and_reported(tmp_path):
    dev = dev_checkout(tmp_path)
    path, sha = context_file(tmp_path)
    r = invoke(["execute", "context", "--dry-run", "--tasks", str(path), "--tasks-sha256", sha, "--reps", "1",
                "--agents", "claude", "--budget", "0.5", "--unit-budget", "0.15",
                "--hide", dev.name, "--hide", str(dev), "--hide", dev.name], tmp_path)     # relative to the start
    assert r.returncode == 0, r.stderr
    iso = json.loads(r.stdout)["isolation"]
    assert iso["hide"] == [str(dev.resolve())]
    assert os.path.normcase(str(dev.resolve())) in norm(iso["forbidden_paths"])
    plan = invoke(["plan", "memory", "--hide", str(dev)], tmp_path)        # built-in tasks: printed with --hide
    assert plan.returncode == 0, plan.stderr
    assert json.loads(plan.stdout)["isolation"]["hide"] == [str(dev.resolve())]


def test_cli_hide_missing_or_holding_python_refused(tmp_path):
    r = invoke(["plan", "context", "--hide", str(tmp_path / "nope")], tmp_path)
    assert r.returncode == 2 and "--hide" in r.stderr and "no such" in r.stderr
    py = invoke(["plan", "context", "--hide", str(Path(sys.executable).parent)], tmp_path)
    assert py.returncode == 2 and "--hide" in py.stderr and "Python" in py.stderr


def test_execute_refuses_out_inside_a_forbidden_folder(tmp_path, monkeypatch):
    path, sha = context_file(tmp_path, n=2)
    data = retest.plan("context", 1, tasks=path, tasks_sha256=sha, agents=["dsh"])
    fake_rows(monkeypatch, [{}] * 4)
    for out in (ROOT / "tmp-454-out", tmp_path / "out-454"):
        if out == tmp_path / "out-454":
            data = retest.plan("context", 1, tasks=path, tasks_sha256=sha, agents=["dsh"], hide=[tmp_path])
        with pytest.raises(ValueError, match="--out"):
            runner.execute(data, out, 0.5, 0.1)
        assert not out.exists()


def test_alias_spellings_absolute_and_resolved(tmp_path):
    """(a) a junction or symbolic link: both the spelling given and the resolved target are denied and audited."""
    target = dev_checkout(tmp_path)
    link = tmp_path / "alias-454"
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, AttributeError, ImportError) as e:
        pytest.skip(f"no junction/symlink here: {e}")
    hidden = runner.isolation_paths(hide=retest.resolve_hide([str(link)]))
    assert {os.path.normcase(str(link.absolute())), os.path.normcase(str(target.resolve()))} <= set(norm(hidden))
    u = runner.isolation_unit(tmp_path / "u", tmp_path / "u" / "hub", hidden)
    deny = PF.claude_settings(u)["permissions"]["deny"]
    assert f"Read({PF._rule_path(link.absolute())}/**)" in deny
    assert f"Read({PF._rule_path(target.resolve())}/**)" in deny
    for spelled in (link, target):
        assert runner.audit_hits([f"cat {(spelled / 'notes.txt').as_posix()}"], u)


@pytest.mark.parametrize("call", [
    "cd ../../relayline && cat scripts/eval/round2_a/a1_p1.py",          # relative read after a cd
    r"type ..\..\x\scripts\eval\round2_bc\g\tasks\t1\hidden\test_h.py",   # backslashes, another folder name
    r"Get-Content ROUND2~1\spec.py",                                      # an 8.3 short name of round2_a
    "python -c \"import round2_a_tasks\"",                                # the generator by module name
    "rg -n settle ../..",                                                 # recursive search above the unit
    "grep -rn settle ../../..",
    'Get-ChildItem -Recurse ..\\.. | Select-String settle',
])
def test_content_patterns_and_parent_searches_flagged(tmp_path, call):
    """(b) relative paths, a cd first, or a recursive search of a parent folder: flagged however the path is written."""
    u = runner.isolation_unit(tmp_path / "u", tmp_path / "u" / "hub", runner.isolation_paths())
    assert runner.audit_hits([json.dumps(call)], u), call


def test_grep_tool_on_a_parent_folder_flagged(tmp_path):
    u = runner.isolation_unit(tmp_path / "u", tmp_path / "u" / "hub", runner.isolation_paths())
    assert runner.audit_hits([json.dumps({"pattern": "settle", "path": str(ROOT.parent)})], u)
    assert runner.audit_hits([json.dumps({"pattern": "**/*.py", "path": ROOT.parent.as_posix() + "/"})], u)


def test_the_units_own_work_python_and_ccx_not_flagged(tmp_path, monkeypatch):
    """The unit's repo stays readable, and running Python or ccx is never a hit (else every unit is unclean)."""
    dest = tmp_path / "u"
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    fine = ["python -m pytest -q", f'"{sys.executable}" -m pytest -q', "rg -n f .", "grep -rn f ..",
            "cat calc.py", json.dumps({"file_path": str(dest / "repo" / "calc.py")}),
            json.dumps({"pattern": "f", "path": str(dest / "repo")}), f'python "{ROOT / "ccx.py"}" mem list']
    assert runner.audit_hits([json.dumps(x) if not x.startswith("{") else x for x in fine], u) == []
    # A venv inside a hidden folder: its interpreter is masked, the folder's other files are not
    venv = ROOT / "scripts" / "eval" / ".venv-454"
    monkeypatch.setattr(runner, "python_paths", lambda: [venv, venv / "Scripts"])
    assert runner.audit_hits([f'"{(venv / "Scripts" / "python.exe").as_posix()}" -m pytest -q'], u) == []
    assert runner.audit_hits([f"cat {(ROOT / 'scripts' / 'eval' / 'common.py').as_posix()}"], u)


@pytest.mark.skipif(os.name != "nt", reason="8.3 short names are a Windows thing")
def test_short_names_denied_and_audited_when_the_volume_has_them(tmp_path):
    """(c) an 8.3 short name of a hidden folder: added when Windows reports one; a volume without 8.3 names has none
    (the documented limit: a path mixing short and long parts is caught only by the content patterns)."""
    long_dir = tmp_path / "averyverylongfoldername454"
    long_dir.mkdir()
    short = runner.short_path(long_dir)
    if short is None or os.path.normcase(str(short)) == os.path.normcase(str(long_dir.resolve())):
        pytest.skip("this volume has no 8.3 names")
    hidden = runner.isolation_paths(hide=[long_dir.resolve()])
    assert os.path.normcase(str(short)) in norm(hidden)
    u = runner.isolation_unit(tmp_path / "u", tmp_path / "u" / "hub", hidden)
    assert runner.audit_hits([f"type {short}\\x.txt"], u)


def test_claude_unit_denied_and_audited_end_to_end(tmp_path, monkeypatch):
    log = fake_env(monkeypatch, tmp_path)
    path, sha = context_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "context")
    home = tmp_path / "claude-eval"
    home.mkdir()
    dev = dev_checkout(tmp_path)
    hidden = runner.isolation_paths(path, [dev.resolve()])
    unit = {"task": "r2-ctx-0", "arm": "on", "agent": "claude", "model": "haiku", "effort": "low", "rep": 1}
    row = runner.run_unit(unit, "context", tmp_path / "u1", .1, None, claude_home=home, tasks=tasks, fresh=True,
                          hidden=hidden)
    assert "error" not in row and row["ok"] is True, row
    assert row["path_audit"]["clean"] is True and row["path_audit"]["logs"] >= 1
    argv = calls(log, "claude")[-1]["argv"]
    deny = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
    assert {"WebFetch", "WebSearch"} <= set(deny)
    for p in (ROOT, ROOT / "scripts" / "eval", dev.resolve()):
        assert f"Read({PF._rule_path(p)}/**)" in deny and f"Edit({PF._rule_path(p)}/**)" in deny
    assert f"Read({PF._rule_path(path.resolve())})" in deny               # the task file itself
    monkeypatch.setenv("FAKE_TOOL_INPUT", json.dumps({"name": "Read", "input": {
        "file_path": str(ROOT / "scripts" / "eval" / "round2_a" / "spec.py")}}))
    bad = runner.run_unit(unit, "context", tmp_path / "u2", .1, None, claude_home=home, tasks=tasks, fresh=True,
                          hidden=hidden)
    assert bad["path_audit"]["clean"] is False and bad["path_audit"]["n_path_hits"] >= 1


def test_default_units_are_isolated_without_hide(tmp_path, monkeypatch):
    """No --hide and the built-in tasks: the checkout is still denied (the default changed with #454)."""
    log = fake_env(monkeypatch, tmp_path)
    home = tmp_path / "claude-eval"
    home.mkdir()
    unit = {"task": "mem-errors", "arm": "nomem", "agent": "claude", "model": "haiku", "effort": "low", "rep": 1}
    runner.run_unit(unit, "memory", tmp_path / "u", .1, None, claude_home=home)
    argv = calls(log, "claude")[-1]["argv"]
    deny = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
    assert f"Read({PF._rule_path(ROOT)}/**)" in deny


def test_codex_unit_audited_end_to_end(tmp_path, monkeypatch):
    fake_env(monkeypatch, tmp_path)
    path, sha = memory_file(tmp_path, n=1)
    tasks = retest.load_tasks(path, sha, "memory")
    home = tmp_path / "eval-codex-home"
    home.mkdir()
    (home / "auth.json").write_text("", encoding="utf-8")
    unit = {"task": "r2-mem-0", "arm": "hubmem", "agent": "codex", "model": "gpt-6-luna", "effort": "low", "rep": 1}
    monkeypatch.setenv("FAKE_COMMANDS", "python -m pytest -q\ncat calc.py")
    ok = runner.run_unit(unit, "memory", tmp_path / "u1", .1, home, tasks=tasks, fresh=True,
                         hidden=runner.isolation_paths(path))
    assert ok["path_audit"]["clean"] is True, ok
    monkeypatch.setenv("FAKE_COMMANDS", f"cat {(ROOT / 'scripts' / 'eval' / 'round2_a' / 'spec.py').as_posix()}")
    bad = runner.run_unit(unit, "memory", tmp_path / "u2", .1, home, tasks=tasks, fresh=True,
                          hidden=runner.isolation_paths(path))
    assert bad["path_audit"]["clean"] is False


def test_unclean_unit_is_invalid_and_stops_the_default_group(tmp_path, monkeypatch):
    from test_strength_fresh_tasks import manifest
    dirty = {"ok": True, "path_audit": {"clean": False, "n_path_hits": 1, "path_hits": ["cat x"]}}
    data = manifest(tmp_path, "continue")
    fake_rows(monkeypatch, [dirty] + [{"ok": True}] * 7)
    report = runner.execute(data, tmp_path / "out", 1.0, 0.1)
    assert report["rows"][0]["invalid"] is True and "forbidden path" in report["rows"][0]["invalid_reason"]
    assert report["invalid"] == 1 and not report["budget_stopped"]
    data = manifest(tmp_path / "s", "stop") if (tmp_path / "s").mkdir() is None else None
    seen = fake_rows(monkeypatch, [{"ok": True}, dirty] + [{"ok": True}] * 6)
    report = runner.execute(data, tmp_path / "out2", 1.0, 0.1)
    assert len(seen) == 2 and report["budget_stopped"] and "forbidden path" in report["stop_reason"]
    assert report["rows"][1]["invalid"] is True and "invalid" not in report["rows"][0]


# ------------------------------------------------------------------ review of #455


def test_unit_folder_named_like_a_pattern_is_masked(tmp_path):
    """(blocker a) an --out whose name holds round2_a: the unit's own files are never a hit."""
    dest = tmp_path / "r2-round2_a-l5_memory" / "unit-0000"
    home = tmp_path / "claude-round2_a-home"
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    own = [json.dumps({"file_path": str(dest / "repo" / "calc.py")}),
           json.dumps({"pattern": "def", "path": str(dest / "repo")}),
           json.dumps(f"cat {(dest / 'repo' / 'calc.py').as_posix()}"),
           json.dumps({"file_path": str(home / "projects" / "x.jsonl")})]
    assert runner.audit_hits(own, u, homes=(home,)) == []
    assert runner.audit_hits([json.dumps("cat ../../relayline/scripts/eval/round2_a/spec.py")], u, homes=(home,))


def test_out_or_home_named_like_a_pattern_refused(tmp_path):
    """(blocker b) such an --out or logged-in home is refused before anything runs."""
    with pytest.raises(ValueError, match="content pattern"):
        runner.check_out(tmp_path / "eval-round2_a", runner.isolation_paths())
    with pytest.raises(ValueError, match="content pattern"):
        runner.check_out(tmp_path / "out", runner.isolation_paths(), homes=(tmp_path / "shared_context_ab-home",))
    home = tmp_path / "claude-l5_memory"
    home.mkdir()
    (home / ".credentials.json").write_text("not read", encoding="utf-8")
    with pytest.raises(ValueError, match="content pattern"):
        retest.checked_claude_home(str(home))
    with pytest.raises(ValueError, match="content pattern"):
        retest.checked_codex_home(str(tmp_path / "codex-round2_bc"))


def test_out_inside_the_persons_hub_refused(tmp_path, monkeypatch):
    real = PF.real_paths()
    monkeypatch.setattr(PF, "real_paths", lambda env=None: {**real, "hub": tmp_path / "hub"})
    with pytest.raises(ValueError, match="--out"):
        runner.check_out(tmp_path / "hub" / "eval", runner.isolation_paths())
    runner.check_out(tmp_path / "eval", runner.isolation_paths())          # outside: fine


@pytest.mark.parametrize("call,hit", [
    ("cd ../..", False),                          # <unit>/.ccx-worktrees: still the unit's
    ("cd ../../.. && rg -n settle .", False),     # the unit's folder itself
    ("rg -n settle ../../..", False),
    ("cd ../../../..", True),                     # out of the unit
    ("cd ../../.. && cd ..", True),
    ("rg -n settle ../../../..", True),
    ("Get-ChildItem -Recurse ..\\..\\..\\..", True),
    ("cd $(dirname $PWD)/../../..", True),        # cannot be resolved and climbs: counted as leaving
    # third review: any command's relative path, ./.., bare cd, cd ~, Push-Location, cmd's cd /d
    ("cat ../../../../../dev/scripts/eval/x.py", True),
    ("cat ./../../../../x.txt", True),
    ("type ..\\..\\..\\..\\x.txt", True),
    ("cat ../../x.txt", False),
    ("python ./../../../x.py", False),           # lands in the unit's folder
    ("cd", True),
    ("cd ; cat x", True),
    ("cd ~", True),
    ("Push-Location ..\\..\\..\\..", True),
    ("cd /d ..\\..\\..\\..", True),
    ("cd /d ..\\..", False),
])
def test_climbs_judged_by_where_they_land(tmp_path, call, hit):
    """(should-fix 2) the sub-agent works in <unit>/.ccx-worktrees/repo/<run id>; only leaving the unit is a hit."""
    dest = tmp_path / "u"
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    cwd = dest / ".ccx-worktrees" / "repo" / "run1"
    assert bool(runner.audit_hits([json.dumps(call)], u, cwd=cwd)) is hit, call


def test_cd_to_a_parent_of_a_forbidden_folder_is_a_hit(tmp_path):
    """(third review 2) a cd outside the unit into a folder holding a forbidden one, then a relative read."""
    dest = tmp_path / "u"
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    up = ROOT.parent.as_posix()
    for call in (f"cd {up} && cat README.md", f"Push-Location {up}; Get-Content x.txt", f"cd /d {up}",
                 f"pushd \"{up}\""):
        assert runner.audit_hits([json.dumps(call)], u), call
    elsewhere = tmp_path / "elsewhere-454"
    assert runner.audit_hits([json.dumps(f"cd {elsewhere.as_posix()} && ls")], u) == []


def test_home_holding_a_forbidden_folder_is_not_masked(tmp_path):
    dest = tmp_path / "u"
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    read = json.dumps(f"cat {(ROOT / 'scripts' / 'eval' / 'common.py').as_posix()}")
    assert runner.audit_hits([read], u, homes=(ROOT.parent,))


def test_written_code_is_not_a_search(tmp_path):
    """(should-fix 3) a Write/Edit body is not navigation: code that says tree, find or ../.. reads nothing."""
    dest = tmp_path / "u"
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    body = "def walk(tree):\n    # find files, rg style\n    return os.path.join(root, '../..')\n"
    edits = [json.dumps({"file_path": str(dest / "repo" / "walk.py"), "content": body}),
             json.dumps({"file_path": str(dest / "repo" / "walk.py"), "old_string": "x", "new_string": body})]
    assert runner.audit_hits(edits, u) == []


def test_written_script_naming_the_task_folder_is_a_hit(tmp_path):
    """(third review) a body is still scanned for the content patterns: a script written to read round2_a, then run."""
    dest = tmp_path / "u"
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    body = "print(open('../../../../relayline/scripts/eval/round2_a/spec.py').read())\n"
    assert runner.audit_hits([json.dumps({"file_path": str(dest / "repo" / "peek.py"), "content": body})], u)


def test_absolute_path_with_dots_is_resolved(tmp_path):
    dest = tmp_path / "u"
    u = runner.isolation_unit(dest, dest / "hub", runner.isolation_paths())
    sneaky = f"{ROOT.parent.as_posix()}/zzz/../{ROOT.name}/ccx/cli.py"
    assert runner.audit_hits([json.dumps(f"cat {sneaky}")], u)


def test_hide_brings_the_checkouts_other_worktrees(tmp_path):
    import subprocess
    main = tmp_path / "main-454"
    main.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], cwd=main, check=True)
    (main / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run([*git, "add", "a.txt"], cwd=main, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "a"], cwd=main, check=True)
    wt = tmp_path / "wt-454"
    subprocess.run([*git, "worktree", "add", "-q", str(wt)], cwd=main, check=True)
    got = norm(retest.resolve_hide([str(main)]))
    assert os.path.normcase(str(wt.resolve())) in got and os.path.normcase(str(main.resolve())) in got
