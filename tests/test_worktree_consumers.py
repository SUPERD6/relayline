"""Saved sibling and inside paths identify the same project, even without a live worktree."""
import os
from pathlib import Path

import pytest

from ccx import ledger, ui
from ccx.workspace import worktree_repo


def _main_check_key(cmd, cwd):
    """Reference copied from main: only a sibling worktree's root is folded into its repository."""
    import hashlib
    import re
    norm = " ".join((cmd or "").split())
    parts = [x for x in re.split(r"[\\/]+", (cwd or "").lower()) if x]
    if len(parts) >= 3 and parts[-3] == ".ccx-worktrees":
        parts = parts[:-1]
    place = re.sub(r"\d+", "#", parts[-1]) if parts else ""
    return hashlib.sha1(f"{norm}\0{place}".encode("utf-8")).hexdigest()[:12], norm, place


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
    assert worktree_repo(cwd) == (Path(repo).resolve() if repo is not None else None)


def test_check_trust_groups_both_saved_layouts_with_the_project():
    for cwd in ("/w/.ccx-worktrees/app/run-1", "/w/app/.ccx/worktrees/run-2",
                "C:\\w\\app\\.ccx\\worktrees\\run-3"):
        assert ledger.check_key("python check.py", cwd) == ledger.check_key("python check.py", "/w/app")


def test_ui_groups_both_removed_worktree_layouts_with_the_project(tmp_path):
    tmp_path = tmp_path.resolve()
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


@pytest.mark.parametrize("cwd", [
    "/w/.ccx-worktrees/app/run-1",
    "/w/.ccx-worktrees/app/run-1/src",
    "/w/.ccx-worktrees/app/run-2/src/tests",
    "C:\\w\\.ccx-worktrees\\app\\run-3\\src",
])
def test_sibling_subdirectory_check_keys_match_main(cwd):
    assert ledger.check_key("pytest  -q", cwd) == _main_check_key("pytest  -q", cwd)


def test_subdirectory_weak_checks_keep_their_main_key_in_soft_verdicts(tmp_path):
    import time
    from ccx.config import Paths
    from ccx.verdicts import soft_verdicts

    p = Paths(tmp_path / "hub")
    now = time.time()
    wt, cmd = "/w/.ccx-worktrees/app/run-1", "pytest -q"
    old_key = _main_check_key(cmd, wt + "/src")[0]
    for i in range(3):
        rid = f"old-{i}"
        ledger.append_event(p, {"run_id": rid, "cwd": wt + "/src", "ok": True, "status": "done",
                                "ts": now - 13 * 3600, "check": {"key": old_key, "cmd": cmd, "passed": True}})
        ledger.append_event(p, {"type": "verify", "run_id": rid, "ok": False})
    root_key = _main_check_key(cmd, wt)[0]
    ledger.append_event(p, {"run_id": "old-root", "cwd": wt, "ok": True, "status": "done",
                            "ts": now - 13 * 3600, "check": {"key": root_key, "cmd": cmd, "passed": True}})
    ledger.append_event(p, {"type": "verify", "run_id": "old-root", "ok": True})
    for rid, cwd in (("sub-candidate", wt + "/src"), ("root-candidate", wt)):
        rec = {"run_id": rid, "cwd": cwd, "to": "codex", "ok": True, "state": "finished", "attempts": [],
               "ts": now - 13 * 3600, "check": {"cmd": cmd, "passed": True}, "result": {"status": "done"}}
        d = p.runs / rid
        d.mkdir(parents=True)
        ledger.write_record(d, rec)
        ledger.append(p, rec)
    assert {r["run_id"] for r in soft_verdicts(p, now=now)} == {"root-candidate"}
    assert not ledger.load_run(p, "sub-candidate").get("verdict")
    trust = ledger.check_trust(ledger.rows(p), p)
    assert trust[old_key]["weak"]
    assert not trust[ledger.check_key(cmd, wt)[0]]["weak"]
    assert (trust[root_key]["judged"], trust[root_key]["wrong"]) == (1, 0)


@pytest.mark.skipif(os.name != "nt", reason="Windows paths are case insensitive")
@pytest.mark.parametrize("layout", [".CCX/WORKTREES", ".cCx/WoRkTrEeS", ".CCX-WORKTREES"])
def test_windows_worktree_consumers_recognize_uppercase_layouts(tmp_path, layout):
    import time
    from ccx import handoff
    from ccx.commands.workqueue import _here
    from ccx.config import Paths

    tmp_path = tmp_path.resolve()
    root = tmp_path / "app"
    root.mkdir()
    (root / ".git").mkdir()
    wt = (tmp_path / layout / root.name / "run-1" if layout == ".CCX-WORKTREES"
          else root / layout / "run-1")
    assert worktree_repo(wt) == root
    assert _here(wt, root)
    assert ui.project_root(str(wt)) == root
    assert ledger.check_key("check", str(wt)) == ledger.check_key("check", str(root))
    p = Paths(tmp_path / "hub")
    rec = {"run_id": "upper", "cwd": str(wt), "ts": time.time(), "attempts": [],
           "to": "codex", "result": {"status": "done"}}
    d = p.runs / "upper"
    d.mkdir(parents=True)
    ledger.write_record(d, rec)
    ledger.append(p, rec)
    assert [r["run_id"] for r in handoff._recent_runs(p, root)] == ["upper"]


@pytest.fixture(params=["symlink", "short"])
def path_alias(tmp_path, request):
    """Real filesystem aliases: macOS's temp symlink and Windows's 8.3 names need the same treatment."""
    def alias(path):
        if request.param == "symlink":
            link = tmp_path / ("alias-" + path.name)
            try:
                link.symlink_to(path, target_is_directory=True)
            except OSError as e:
                pytest.skip(f"directory symlinks are unavailable: {e}")
            return link
        if os.name != "nt":
            pytest.skip("8.3 short names are Windows-only")
        import ctypes
        from ctypes import wintypes
        short_name = ctypes.windll.kernel32.GetShortPathNameW
        short_name.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        short_name.restype = wintypes.DWORD
        size = short_name(str(path), None, 0)
        if not size:
            pytest.skip("GetShortPathNameW is unavailable for this directory")
        buf = ctypes.create_unicode_buffer(size)
        if not short_name(str(path), buf, size) or Path(buf.value) == path:
            pytest.skip("the filesystem did not provide an 8.3 alias")
        return Path(buf.value)
    return alias


@pytest.mark.parametrize("location", ["sibling", "inside"])
def test_worktree_aliases_share_paths_and_project_keys(tmp_path, path_alias, location, monkeypatch):
    import time
    from ccx import handoff, lanes, workspace
    from ccx.commands import workqueue
    from ccx.config import Paths

    root = tmp_path.resolve() / "project-with-a-long-name"
    root.mkdir()
    (root / ".git").mkdir()
    wt = workspace.worktree_path(root, "run-with-a-long-name", location)
    (wt / "src").mkdir(parents=True)
    alias_root, alias_wt = path_alias(root), path_alias(wt)
    assert workspace.worktree_path(alias_root, wt.name, location) == wt
    assert worktree_repo(alias_wt) == root
    assert worktree_repo(alias_wt / "src") == root
    assert ui.project_root(str(alias_wt)) == root
    monkeypatch.setattr(workqueue, "_top", lambda root: None)
    assert workqueue._here(alias_wt, root)
    assert workqueue._here(wt, alias_root)
    assert ledger.check_key("check", str(alias_root)) == ledger.check_key("check", str(root))
    assert ledger.check_key("check", str(alias_wt)) == ledger.check_key("check", str(root))
    assert ledger.check_key("check", str(alias_wt / "src")) == ledger.check_key("check", str(wt / "src"))
    monkeypatch.setattr(lanes, "commit_block", lambda rec: None)
    monkeypatch.setattr(workspace, "_git", lambda cwd, *args: (0, "ccx/run-with-a-long-name"))
    fields, _ = workqueue._tree_fields({"cwd": str(alias_wt), "mode": "write"})
    assert fields["worktree"] == str(wt)
    p = Paths(tmp_path / "hub")
    for rid, cwd in (("project", alias_root), ("subdir", alias_root / "src"), ("worktree", alias_wt)):
        rec = {"run_id": rid, "cwd": str(cwd), "to": "codex", "ts": time.time(), "attempts": [],
               "result": {"status": "done"}}
        d = p.runs / rid
        d.mkdir(parents=True)
        ledger.write_record(d, rec)
        ledger.append(p, rec)
    assert {r["run_id"] for r in handoff._recent_runs(p, root)} == {"project", "subdir", "worktree"}


def test_demo_reads_config_only_after_isolating_its_hub(tmp_path, monkeypatch):
    import os
    from ccx import demo, queue as wq
    from ccx.config import Paths

    tmp_path = tmp_path.resolve()
    base = tmp_path / "demo"
    own_hub = Path(os.environ["CCX_HUB"])
    real_load = demo.load_config
    seen = []

    def isolated_config(p=None):
        assert p is not None and p.hub == base / "hub"
        assert Path(os.environ["CCX_HUB"]) == p.hub
        seen.append(p.hub)
        cfg = real_load(p)
        cfg["worktree"]["location"] = "inside"
        return cfg

    monkeypatch.setattr(demo, "load_config", isolated_config)
    p = demo.build(base)
    assert seen == [p.hub]
    assert Path(os.environ["CCX_HUB"]) == own_hub
    root = base / "projects" / demo.DOCS
    assert wq.load(root)["items"]["q2"]["worktree"] == str(root / ".ccx" / "worktrees" / "demo-q2")
    assert not (Paths(own_hub).hub / demo.DEMO_MARK).exists()
