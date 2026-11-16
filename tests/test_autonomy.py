"""K4: the project manager's autonomy level (ccx/autonomy.py) — where it comes from, what `ccx run --project` does
at each level, and the conditions of the L2 merge. Fake CLIs only, git in temp folders."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_projects import catalog, run_ccx, run_env  # noqa: E402

from ccx import autonomy  # noqa: E402
from ccx.config import load_config, paths, set_setting  # noqa: E402
from ccx.workspace import make_worktree  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)


def level(project=None, flag=None):
    p = paths()
    return autonomy.level_for(project, p, load_config(p), flag=flag)


# ---- where the level comes from ----

def test_default_is_l1_and_config_set_changes_it():
    assert level()["level"] == "L1" and level()["source"] == "config"
    set_setting(paths(), "autonomy.level", "L0")
    assert level()["level"] == "L0"
    with pytest.raises(ValueError):
        set_setting(paths(), "autonomy.level", "L3")


def test_hub_project_setting_raises_and_project_file_only_lowers(tmp_path):
    catalog(tmp_path)
    p = paths()
    autonomy.set_level(p, "L2", "desk-pet", auto_merge=True)
    got = level("desk-pet")
    assert (got["level"], got["source"], got["auto_merge"]) == ("L2", "hub project", True)
    assert level("notes-site")["level"] == "L1"                     # other projects keep the default
    pet = tmp_path / "ws" / "group" / "desk-pet"
    (pet / ".ccx").mkdir(exist_ok=True)
    (pet / ".ccx" / "autonomy.toml").write_text('level = "L0"\n', encoding="utf-8")
    got = level("desk-pet")
    assert (got["level"], got["source"], got["auto_merge"]) == ("L0", "project .ccx/autonomy.toml", False)
    autonomy.set_level(p, "L0", "notes-site")
    site = tmp_path / "ws" / "group" / "notes-site"
    (site / ".ccx").mkdir(exist_ok=True)
    (site / ".ccx" / "autonomy.toml").write_text('level = "L2"\n', encoding="utf-8")
    assert level("notes-site")["level"] == "L0"                     # a project's own file can't raise it
    assert level("notes-site", flag="L1")["source"] == "--autonomy"
    with pytest.raises(ValueError):
        autonomy.set_level(p, None, auto_merge=True)                # merging is per project only


def test_gate():
    plan = {"to": "codex"}
    for lv, mode, approved, stops in (("L0", "read", False, True), ("L0", "read", True, False),
                                      ("L1", "read", False, False), ("L1", "write", False, True),
                                      ("L1", "write", True, False), ("L2", "write", False, False)):
        info = {"level": lv, "source": "config", "project": None}
        got = autonomy.gate(info, mode, approved, plan)
        assert (got is not None) == stops, (lv, mode, approved)
        if got:
            assert got["delegated"] is False and got["plan"] == plan and "--approved" in got["next"]


# ---- ccx run --project at each level ----

def calls(tmp_path):
    f = tmp_path / "calls.jsonl"
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


def test_run_project_l1_reads_by_itself_and_waits_before_edits(tmp_path):
    catalog(tmp_path)
    env = run_env(tmp_path)
    env["FAKE_TOUCH"] = "1"            # the write run changes something (else it is kind no_changes)
    base = ("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--project", "desk-pet")
    code, out = run_ccx(env, *base, "--mode", "write", "rename foo to bar in a.py")
    assert code == 0 and out["delegated"] is False and out["autonomy"]["level"] == "L1"
    assert out["plan"]["mode"] == "write" and out["plan"]["to"] == "codex" and out["plan"]["project"] == "desk-pet"
    assert not calls(tmp_path)
    code, out = run_ccx(env, *base, "--mode", "read", "explain what a.py does")
    assert code == 0 and out["autonomy"] == {"level": "L1", "source": "config"} and len(calls(tmp_path)) == 1
    code, out = run_ccx(env, *base, "--mode", "write", "--approved", "--review", "off", "rename foo to bar in a.py")
    assert code == 0 and out["autonomy"]["level"] == "L1" and len(calls(tmp_path)) == 2


def test_run_l0_only_proposes_even_reads_and_bg_stops_too(tmp_path):
    catalog(tmp_path)
    env = run_env(tmp_path)
    code, out = run_ccx(env, "run", "--from", "claude", "--to", "codex", "--tier", "T1", "--project", "desk-pet",
                        "--autonomy", "L0", "--mode", "read", "--bg", "explain a.py")
    assert code == 0 and out["delegated"] is False and "L0" in out["why"] and "run_id" not in out
    assert not calls(tmp_path)


def test_run_without_project_or_flag_is_not_gated(tmp_path):
    env = run_env(tmp_path)
    code, out = run_ccx(env, "run", "--from", "claude", "--to", "codex", "--tier", "T1", "--mode", "write",
                        "--cwd", str(tmp_path), "rename foo to bar in a.py")
    assert code == 0 and "autonomy" not in out and len(calls(tmp_path)) == 1


def test_autonomy_command_shows_and_sets(tmp_path):
    catalog(tmp_path)
    env = run_env(tmp_path)
    code, out = run_ccx(env, "autonomy")
    assert code == 0 and out["level"] == "L1" and len(out["always_ask"]) == 4
    code, out = run_ccx(env, "autonomy", "set", "L2", "--project", "桌宠", "--auto-merge", "on")
    assert code == 0 and out["set"] == {"project": "desk-pet", "level": "L2", "auto_merge": True}
    code, out = run_ccx(env, "autonomy", "--project", "desk-pet")
    assert out["level"] == "L2" and out["auto_merge"] is True and out["default"] == "L1"


# ---- the L2 merge ----

def git(d, *args):
    r = subprocess.run(["git", *args], cwd=d, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def repo_with_run(tmp_path, branch="work", lines=3, review="pass", check=True):
    """A repo on `branch`, a ccx worktree with `lines` new lines left uncommitted, and the run's record."""
    repo = tmp_path / "proj"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    if branch != "main":
        git(repo, "checkout", "-qb", branch)
    run_id = "20261025-000000-abcd"
    wt = make_worktree(repo, run_id)
    (wt / "a.py").write_text("x = 1\n" + "".join(f"y{i} = {i}\n" for i in range(lines)), encoding="utf-8")
    p = paths()
    (p.runs / run_id).mkdir(parents=True)
    rec = {"run_id": run_id, "ok": True, "kind": None, "state": "done", "cwd": str(wt), "label": "add ys",
           "check": {"cmd": "true", "passed": check, "exit": 0 if check else 1}, "review": {"verdict": review}}
    (p.runs / run_id / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    return repo, run_id


L2 = {"level": "L2", "auto_merge": True, "source": "hub project", "project": "proj"}


def test_l2_merges_a_small_checked_reviewed_branch_into_a_working_branch(tmp_path):
    repo, run_id = repo_with_run(tmp_path)
    p = paths()
    dry = autonomy.merge(p, run_id, L2)
    assert dry["can_merge"] and dry["into"] == "work" and dry["lines"] == 3 and dry["files"] == ["a.py"]
    assert not dry["merged"]
    done = autonomy.merge(p, run_id, L2, apply=True)
    assert done["merged"] and "reset --keep" in done["undo"]
    assert "y2 = 2" in (repo / "a.py").read_text(encoding="utf-8")
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "work"
    assert git(repo, "log", "-1", "--format=%s").startswith("Merge ccx/")
    assert any(json.loads(l).get("type") == "auto_merge" for l in p.ledger.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize("kw, info, why", [
    ({"branch": "main"}, L2, "protected"),
    ({"lines": 200}, L2, "too big"),
    ({"review": "issues"}, L2, "review did not pass"),
    ({"review": None}, L2, "review did not pass"),
    ({"check": False}, L2, "check failed"),
    ({}, {**L2, "auto_merge": False}, "does not allow merging"),
    ({}, {**L2, "level": "L1"}, "needs L2"),
])
def test_l2_does_not_merge_unless_every_condition_holds(tmp_path, kw, info, why):
    repo, run_id = repo_with_run(tmp_path, **kw)
    before = git(repo, "rev-parse", "HEAD")
    out = autonomy.merge(paths(), run_id, info, apply=True)
    assert not out["merged"] and not out["can_merge"] and any(why in x for x in out["why_not"]), out
    assert git(repo, "rev-parse", "HEAD") == before


def test_l2_never_merges_with_approval_rules_or_into_the_remote_default(tmp_path):
    repo, run_id = repo_with_run(tmp_path, branch="dev")
    out = autonomy.merge(paths(), run_id, L2, rules=[{"text": "Approval needed"}])
    assert any("approval rules" in x for x in out["why_not"])
    git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/dev")
    out = autonomy.merge(paths(), run_id, L2)
    assert any("dev is protected" in x for x in out["why_not"])


def test_autonomy_merge_command_is_a_dry_run_by_default(tmp_path):
    repo, run_id = repo_with_run(tmp_path)
    code, out = run_ccx({**os.environ}, "autonomy", "merge", run_id)
    assert code == 2 and out["autonomy"]["level"] == "L1" and not out["merged"]   # default level: no merge
    assert out["into"] == "work"


def repo_behind_upstream(tmp_path):
    """#349: the project's `work` trails origin/work by one commit (up1..up3.txt, 200 lines each); a
    `--base upstream` worktree run starts from origin/work and adds 3 lines to a.py, left uncommitted."""
    remote, repo, other = tmp_path / "remote.git", tmp_path / "proj", tmp_path / "other"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    git(repo, "checkout", "-qb", "work")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-qu", "origin", "work")
    git(tmp_path, "clone", "-q", "-b", "work", str(remote), str(other))
    for n in (1, 2, 3):
        (other / f"up{n}.txt").write_text("".join(f"{i}\n" for i in range(200)), encoding="utf-8")
    git(other, "add", ".")
    git(other, "commit", "-qm", "someone else's work")
    git(other, "push", "-q", "origin", "work")
    run_id = "20261116-000000-up01"
    info: dict = {}
    wt = make_worktree(repo, run_id, base="upstream", base_info=info)    # fetches origin/work first
    assert info["worktree_base"] == "upstream" and (wt / "up1.txt").is_file()
    (wt / "a.py").write_text("x = 1\n" + "".join(f"y{i} = {i}\n" for i in range(3)), encoding="utf-8")
    p = paths()
    (p.runs / run_id).mkdir(parents=True)
    rec = {"run_id": run_id, "ok": True, "kind": None, "state": "done", "cwd": str(wt), "label": "add ys",
           "check": {"cmd": "true", "passed": True, "exit": 0}, "review": {"verdict": "pass"}, **info}
    (p.runs / run_id / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    return repo, run_id


def test_upstream_based_run_counts_only_the_sub_agents_change(tmp_path):
    repo, run_id = repo_behind_upstream(tmp_path)
    out = autonomy.merge(paths(), run_id, L2)
    assert out["lines"] == 3 and out["files"] == ["a.py"], out          # not up1..up3.txt's 600 lines
    assert not any("too big" in x for x in out["why_not"]), out


def test_upstream_based_run_is_not_merged_into_a_branch_that_trails_the_upstream(tmp_path):
    repo, run_id = repo_behind_upstream(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    out = autonomy.merge(paths(), run_id, L2, apply=True)
    assert not out["merged"] and not out["can_merge"], out
    assert any("1 commit(s) behind origin/work" in x and "pull" in x for x in out["why_not"]), out
    assert git(repo, "rev-parse", "HEAD") == before and not (repo / "up1.txt").exists()   # no silent pull
    git(repo, "merge", "-q", "--ff-only", "origin/work")                # the person pulls; now it merges
    done = autonomy.merge(paths(), run_id, L2, apply=True)
    assert done["merged"] and done["lines"] == 3 and done["files"] == ["a.py"], done
    assert "y2 = 2" in (repo / "a.py").read_text(encoding="utf-8")
