"""Git receives canonical worktree paths without Windows's extended-length prefix, on every Python version."""
import subprocess
from pathlib import Path

import pytest

from ccx import workspace


@pytest.mark.parametrize("resolved, expected", [
    (r"\\?\C:\Users\runneradmin\repo", r"C:\Users\runneradmin\repo"),
    (r"\\?\UNC\server\share\repo", r"\\server\share\repo"),
    (r"C:\Users\runneradmin\repo", r"C:\Users\runneradmin\repo"),
    (r"\\server\share\repo", r"\\server\share\repo"),
])
def test_canonical_strips_only_the_extended_length_prefix(monkeypatch, resolved, expected):
    monkeypatch.setattr(Path, "resolve", lambda self: Path(resolved))
    assert workspace.canonical("unused") == Path(expected)


@pytest.mark.parametrize("location", ["sibling", "inside"])
def test_git_worktree_arguments_have_no_extended_length_prefix(tmp_path, monkeypatch, location):
    root = workspace.canonical(tmp_path / "repo")
    root.mkdir()
    expected = workspace.worktree_path(root, "run-0", location)
    real_resolve = Path.resolve
    resolved_paths, calls = [], []

    def extended_resolve(path, *args, **kwargs):
        resolved = str(real_resolve(path, *args, **kwargs))
        resolved_paths.append(str(path))
        if resolved.startswith("\\\\?\\"):
            return Path(resolved)
        if resolved.startswith("\\\\"):
            return Path("\\\\?\\UNC\\" + resolved[2:])
        return Path("\\\\?\\" + resolved)

    def git(argv, **kwargs):
        calls.append(argv)
        assert all(not str(a).replace("\\", "/").startswith("//?/") for a in argv)
        assert not str(kwargs["cwd"]).replace("\\", "/").startswith("//?/")
        if argv[1:] == ["rev-parse", "--show-toplevel"]:
            out = str(root)
        elif argv[1:] == ["rev-parse", "--path-format=absolute", "--git-common-dir"]:
            out = str(root / ".git")
        else:
            assert argv[1:3] in (["check-ignore", "-q"], ["worktree", "add"])
            out = ""
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(Path, "resolve", extended_resolve)
    monkeypatch.setattr(workspace.subprocess, "run", git)
    monkeypatch.setattr(workspace, "load_config", lambda: {"worktree": {"location": location}})
    wt = workspace.make_worktree(root, "run-0")
    assert wt == expected
    assert str(expected) in resolved_paths
    assert workspace.worktree_repo(wt) == root
    add = next(argv for argv in calls if argv[1:3] == ["worktree", "add"])
    assert add[-1] == str(expected)
