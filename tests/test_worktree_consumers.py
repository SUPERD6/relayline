"""Saved sibling and inside paths identify the same project, even without a live worktree."""
from pathlib import Path

import pytest

from ccx import ledger, ui
from ccx.workspace import worktree_repo


@pytest.mark.parametrize("cwd, repo", [
    ("/w/.ccx-worktrees/app/run-1", "/w/app"),
    ("/w/.ccx-worktrees/app/run-1/src", "/w/app"),
    ("/w/app/.ccx/worktrees/run-1", "/w/app"),
    ("/w/app/.ccx/worktrees/run-1/src", "/w/app"),
    ("C:\\My Projects\\.ccx-worktrees\\app\\run-1", "C:/My Projects/app"),
    ("C:\\My Projects\\app\\.ccx\\worktrees\\run-1", "C:/My Projects/app"),
    (None, None),
    ("/w/app", None),
    ("/w/app/.ccx/worktrees", None),
    ("/w/.ccx-worktrees/app", None),
])
def test_worktree_repo_recognizes_both_layouts(cwd, repo):
    assert worktree_repo(cwd) == (Path(repo) if repo is not None else None)


def test_check_trust_groups_both_saved_layouts_with_the_project():
    for cwd in ("/w/.ccx-worktrees/app/run-1", "/w/app/.ccx/worktrees/run-2",
                "C:\\w\\app\\.ccx\\worktrees\\run-3"):
        assert ledger.check_key("python check.py", cwd) == ledger.check_key("python check.py", "/w/app")


def test_ui_groups_both_removed_worktree_layouts_with_the_project(tmp_path):
    repo = tmp_path / "app"
    repo.mkdir()
    (repo / ".git").mkdir()
    for wt in (tmp_path / ".ccx-worktrees" / "app" / "run-1", repo / ".ccx" / "worktrees" / "run-2"):
        assert not wt.exists()
        assert ui.project_root(str(wt)) == repo


def test_inside_l2_merge_keeps_the_existing_merge_gates(tmp_path, monkeypatch):
    from test_autonomy import GIT_ENV, L2, repo_with_run
    from ccx import autonomy
    from ccx.config import paths, set_setting

    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    p = paths()
    set_setting(p, "worktree.location", "inside")
    repo, rid = repo_with_run(tmp_path)
    set_setting(p, "worktree.location", "sibling")
    dry = autonomy.merge(p, rid, L2)
    assert dry["can_merge"] and dry["into"] == "work" and dry["files"] == ["a.py"]
    assert not autonomy.merge(p, rid, {**L2, "auto_merge": False}, apply=True)["merged"]
    assert autonomy.merge(p, rid, L2, apply=True)["merged"]
    assert "y2 = 2" in (repo / "a.py").read_text(encoding="utf-8")


def test_recent_runs_includes_inside_worktrees_of_the_project(tmp_path):
    import time
    from ccx import handoff
    from ccx.config import Paths
    from ccx.workspace import worktree_path

    p = Paths(tmp_path / "hub")
    root = (tmp_path / "app").resolve()
    other = (tmp_path / "other").resolve()
    for rid, repo, location in (("inside", root, "inside"), ("sibling", root, "sibling"),
                                ("other-inside", other, "inside"), ("other-sibling", other, "sibling")):
        rec = {"run_id": rid, "to": "codex", "cwd": str(worktree_path(repo, rid, location)),
               "ts": time.time(), "attempts": [], "result": {"status": "done", "summary": rid}}
        d = p.runs / rid
        d.mkdir(parents=True)
        ledger.write_record(d, rec)
        ledger.append(p, rec)
    assert {r["run_id"] for r in handoff._recent_runs(p, root)} == {"inside", "sibling"}
