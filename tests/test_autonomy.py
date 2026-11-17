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
    assert any("work is missing 1 commit(s) that this run started from (origin/work at " in x
               and "pull first (`git pull`)" in x for x in out["why_not"]), out
    assert git(repo, "rev-parse", "HEAD") == before and not (repo / "up1.txt").exists()   # no silent pull
    git(repo, "merge", "-q", "--ff-only", "origin/work")                # the person pulls; now it merges
    done = autonomy.merge(paths(), run_id, L2, apply=True)
    assert done["merged"] and done["lines"] == 3 and done["files"] == ["a.py"], done
    assert "y2 = 2" in (repo / "a.py").read_text(encoding="utf-8")


def test_a_diverged_branch_is_told_to_bring_the_upstream_in_not_just_pull(tmp_path):
    repo, run_id = repo_behind_upstream(tmp_path)
    (repo / "local.txt").write_text("mine\n", encoding="utf-8")
    git(repo, "add", "local.txt")
    git(repo, "commit", "-qm", "local only")
    out = autonomy.merge(paths(), run_id, L2)
    why = [x for x in out["why_not"] if "missing 1 commit(s)" in x]
    assert why and "diverged" in why[0] and "1 local commit(s)" in why[0] and "git pull --rebase" in why[0], out


# ---- #349: where a resumed run started (upstream_start follows resumed_from) ----

def write_rec(run_id, **fields):
    p = paths()
    (p.runs / run_id).mkdir(parents=True, exist_ok=True)
    (p.runs / run_id / "run.json").write_text(json.dumps({"run_id": run_id, **fields}), encoding="utf-8")
    return {"run_id": run_id, **fields}


def test_upstream_start_follows_resumed_from_to_the_base():
    write_rec("r1", worktree_base="upstream", base_ref="origin/x", base_sha="a" * 40)
    write_rec("r2", resumed_from="r1")
    rec = write_rec("r3", resumed_from="r2")
    assert autonomy.upstream_start(paths(), rec) == {"sha": "a" * 40, "ref": "origin/x"}


def test_upstream_start_head_runs_and_old_records_are_head_based():
    assert autonomy.upstream_start(paths(), write_rec("h1")) is None                    # default / pre-#341 record
    assert autonomy.upstream_start(paths(), write_rec("h2", worktree_base="head")) is None
    write_rec("u1", worktree_base="upstream", base_ref="origin/x", base_sha="a" * 40)
    rec = write_rec("h3", worktree_base="head", resumed_from="u1")      # the resume's own base wins: it is head
    assert autonomy.upstream_start(paths(), rec) is None
    write_rec("h4", worktree_base="head", worktree_base_fallback="no upstream")
    assert autonomy.upstream_start(paths(), write_rec("h5", resumed_from="h4")) is None


@pytest.mark.parametrize("setup, why", [
    ("missing", "run r0, which it resumed, is missing"),
    ("corrupt", "run r0, which it resumed, cannot be read"),
    ("no_sha", "records no base_sha"),
    ("cycle", "loop"),
    ("long", "too long"),
])
def test_upstream_start_a_broken_chain_is_unknown_not_head(setup, why):
    p = paths()
    if setup == "corrupt":
        (p.runs / "r0").mkdir(parents=True)
        (p.runs / "r0" / "run.json").write_text("{not json", encoding="utf-8")
    elif setup == "no_sha":
        write_rec("r0", worktree_base="upstream", base_ref="origin/x")
    elif setup == "cycle":
        write_rec("r0", resumed_from="r1")
    elif setup == "long":
        for i in range(25):
            write_rec(f"c{i}", resumed_from=f"c{i + 1}")
        write_rec("r0", resumed_from="c0")
    rec = write_rec("r1", resumed_from="r0")
    start = autonomy.upstream_start(p, rec)
    assert start and "sha" not in start and why in start["unknown"], start


def test_a_run_whose_start_cannot_be_told_is_not_merged(tmp_path):
    repo, run_id = repo_with_run(tmp_path)          # a plain run, resumed from a run whose record is gone
    p = paths()
    rec = json.loads((p.runs / run_id / "run.json").read_text(encoding="utf-8"))
    (p.runs / run_id / "run.json").write_text(json.dumps({**rec, "resumed_from": "20261025-gone"}), encoding="utf-8")
    before = git(repo, "rev-parse", "HEAD")
    out = autonomy.merge(p, run_id, L2, apply=True)
    assert not out["merged"] and any("cannot tell where this run started" in x for x in out["why_not"]), out
    assert not any("nothing changed" in x for x in out["why_not"]), out
    assert git(repo, "rev-parse", "HEAD") == before


def test_a_resumed_upstream_run_counts_only_the_sub_agents_change(tmp_path):
    repo, run_id = repo_behind_upstream(tmp_path)
    p = paths()
    first = json.loads((p.runs / run_id / "run.json").read_text(encoding="utf-8"))
    resumed = write_rec("20261116-000100-up02", ok=True, kind=None, state="done", cwd=first["cwd"], label="add ys",
                        check=first["check"], review=first["review"], resumed_from=run_id)
    out = autonomy.merge(p, resumed["run_id"], L2)
    assert out["lines"] == 3 and out["files"] == ["a.py"], out
    assert any("missing 1 commit(s)" in x for x in out["why_not"]), out


# ---- #374: a resumed run works in the first run's worktree, so its branch is ccx/<first run_id> ----

def resume_of(run_id, new_id, **extra):
    """A record of `new_id` resuming `run_id` in the same worktree, as `ccx resume` writes it (no base of its own)."""
    first = json.loads((paths().runs / run_id / "run.json").read_text(encoding="utf-8"))
    return write_rec(new_id, ok=True, kind=None, state="done", cwd=first["cwd"], label=first["label"],
                     check=first["check"], review=first["review"], resumed_from=run_id, **extra)


def test_a_resumed_run_merges_its_first_runs_branch(tmp_path):
    repo, run_id = repo_with_run(tmp_path)
    resume_of(run_id, "20261025-000100-r1")
    last = resume_of("20261025-000100-r1", "20261025-000200-r2")["run_id"]     # resumed twice
    p = paths()
    dry = autonomy.merge(p, last, L2)
    assert dry["can_merge"] and dry["branch"] == f"ccx/{run_id}" and dry["lines"] == 3, dry
    done = autonomy.merge(p, last, L2, apply=True)
    assert done["merged"], done
    assert "y2 = 2" in (repo / "a.py").read_text(encoding="utf-8")
    assert git(repo, "log", "-1", "--format=%s") == f"Merge ccx/{run_id} (ccx autonomy L2)"


def test_a_resumed_upstream_run_merges_once_the_branch_has_its_start(tmp_path):
    repo, run_id = repo_behind_upstream(tmp_path)
    last = resume_of(run_id, "20261116-000100-up02")["run_id"]
    git(repo, "merge", "-q", "--ff-only", "origin/work")
    done = autonomy.merge(paths(), last, L2, apply=True)
    assert done["merged"] and done["branch"] == f"ccx/{run_id}" and done["files"] == ["a.py"], done
    assert "y2 = 2" in (repo / "a.py").read_text(encoding="utf-8")


def test_a_worktree_moved_off_its_run_branch_is_not_merged(tmp_path):
    repo, run_id = repo_with_run(tmp_path)
    wt = Path(json.loads((paths().runs / run_id / "run.json").read_text(encoding="utf-8"))["cwd"])
    git(wt, "checkout", "-qb", "elsewhere")             # e.g. the sub-agent switched branches in its worktree
    before = git(repo, "rev-parse", "HEAD")
    for rid in (run_id, resume_of(run_id, "20261025-000100-r1")["run_id"]):
        out = autonomy.merge(paths(), rid, L2, apply=True)
        assert not out["merged"] and any("is on elsewhere, not a branch of this run" in x for x in out["why_not"]), out
        assert not any("nothing changed" in x for x in out["why_not"]), out
    assert git(repo, "rev-parse", "HEAD") == before


def test_a_detached_worktree_is_not_merged(tmp_path):
    repo, run_id = repo_with_run(tmp_path)
    wt = Path(json.loads((paths().runs / run_id / "run.json").read_text(encoding="utf-8"))["cwd"])
    git(wt, "checkout", "-q", "--detach")
    before = git(repo, "rev-parse", "HEAD")
    out = autonomy.merge(paths(), run_id, L2, apply=True)
    assert not out["merged"] and any("not on a branch (detached HEAD)" in x for x in out["why_not"]), out
    assert git(repo, "rev-parse", "HEAD") == before


def test_a_resume_chain_broken_before_the_branch_is_not_merged(tmp_path):
    repo, run_id = repo_with_run(tmp_path)
    resume_of(run_id, "20261025-000100-r1")
    last = resume_of("20261025-000100-r1", "20261025-000200-r2")["run_id"]
    (paths().runs / "20261025-000100-r1" / "run.json").unlink()        # the middle record is gone
    before = git(repo, "rev-parse", "HEAD")
    out = autonomy.merge(paths(), last, L2, apply=True)
    assert not out["merged"], out
    assert any("cannot tell which branch this run worked on" in x and "is missing" in x for x in out["why_not"]), out
    assert not any("nothing changed" in x for x in out["why_not"]), out
    assert git(repo, "rev-parse", "HEAD") == before
