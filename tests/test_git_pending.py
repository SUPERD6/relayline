"""Issue #280: real temporary Git conflicts, fake agent CLIs only."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from ccx.config import git_auto_stage
from ccx.git_pending import finish, inspect
from ccx.leadview import clean, line, receipt_notes
from test_ccx import Env


def git(root, *args, ok=True):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
                            "GIT_CONFIG_GLOBAL": str(root / "absent-global-config")})
    if ok:
        assert r.returncode == 0, r.stderr
    return r


def conflict(root, operation="merge", names=("resolved.txt", "markers.txt")):
    git(root, "init")
    git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.hooksPath", str(root / "no-hooks"))
    for name in names:
        (root / name).write_text("base\n", encoding="utf-8", newline="")
    git(root, "--literal-pathspecs", "add", "--", *names)
    git(root, "commit", "-m", "base")
    git(root, "checkout", "-b", "other")
    for name in names:
        (root / name).write_text("other\n", encoding="utf-8", newline="")
    git(root, "commit", "-am", "other")
    git(root, "checkout", "main")
    for name in names:
        (root / name).write_text("main\n", encoding="utf-8", newline="")
    git(root, "commit", "-am", "main")
    args = {"merge": ("merge", "other"), "rebase": ("rebase", "other"),
            "cherry-pick": ("cherry-pick", "other")}[operation]
    assert git(root, *args, ok=False).returncode != 0


@pytest.mark.parametrize("operation", ["merge", "rebase", "cherry-pick"])
def test_detect_operations_and_unmerged(tmp_path, operation):
    conflict(tmp_path, operation)
    before = inspect(tmp_path)
    assert before["status"] == "known"
    assert before["operations"] == [operation]
    assert before["unmerged"] == ["markers.txt", "resolved.txt"]
    assert before["conflict_markers"] == before["unmerged"]
    assert before["resolved_unstaged"] == []
    (tmp_path / "resolved.txt").write_text("resolved\n", encoding="utf-8")
    pending = inspect(tmp_path, before)
    assert pending["resolved_unstaged"] == ["resolved.txt"]
    assert "git add resolved paths" in pending["steps"]


def test_default_off_and_opt_in_only_stages_resolved(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    (tmp_path / "resolved.txt").write_text("resolved\n", encoding="utf-8")
    original_head = git(tmp_path, "rev-parse", "HEAD").stdout
    off = finish(tmp_path, {}, before, write=True)
    assert off["auto_stage"]["enabled"] is False
    assert off["auto_stage"]["staged"] == []
    assert off["unmerged"] == ["markers.txt", "resolved.txt"]
    on = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert on["auto_stage"]["staged"] == ["resolved.txt"]
    assert on["auto_stage"]["not_staged"] == ["markers.txt"]
    assert on["unmerged"] == ["markers.txt"]
    assert on["operations"] == ["merge"]
    assert git(tmp_path, "rev-parse", "HEAD").stdout == original_head
    assert git(tmp_path, "show", ":resolved.txt").stdout == "resolved\n"


@pytest.mark.parametrize("link_location", ["ancestor", "inside"])
def test_symlink_checks_stay_inside_repository(tmp_path, monkeypatch, link_location):
    root = tmp_path / "parent" / "repo"
    root.mkdir(parents=True)
    (root / "nested").mkdir()
    name = "nested/resolved.txt"
    conflict(root, names=(name, "markers.txt"))
    before = inspect(root)
    (root / name).write_text("resolved\n", encoding="utf-8")
    # Model link metadata without requiring Windows symlink privileges. tmp_path itself is resolved.
    linked = root.parent.parent if link_location == "ancestor" else root / "nested"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == linked or original(path))
    out = finish(root, {"git": {"auto_stage_resolved": True}}, before, write=True)
    if link_location == "ancestor":
        assert out["auto_stage"]["staged"] == [name]
        assert name not in out["unsafe_paths"]
    else:
        assert out["auto_stage"]["staged"] == []
        assert name in out["unsafe_paths"]


def test_read_mode_never_stages(tmp_path):
    conflict(tmp_path)
    (tmp_path / "resolved.txt").write_text("resolved\n", encoding="utf-8")
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}})
    assert out["auto_stage"]["enabled"] is False
    assert out["auto_stage"]["staged"] == []
    assert "resolved.txt" in out["unmerged"]


def test_previously_conflicted_then_staged_then_edited(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    path = tmp_path / "resolved.txt"
    path.write_text("resolved\n", encoding="utf-8")
    git(tmp_path, "add", "--", path.name)
    path.write_text("resolved again\n", encoding="utf-8")
    assert inspect(tmp_path, before)["resolved_unstaged"] == [path.name]
    assert inspect(tmp_path)["resolved_unstaged"] == []


def test_marker_crlf_and_binary_are_not_staged(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    (tmp_path / "markers.txt").write_bytes(b"<<<<<<< main\r\nx\r\n=======\r\ny\r\n>>>>>>> other\r\n")
    (tmp_path / "resolved.txt").write_bytes(b"binary\0content")
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["fingerprints"]["markers.txt"] != before["fingerprints"]["markers.txt"]
    assert out["auto_stage"]["staged"] == []
    assert out["conflict_markers"] == ["markers.txt"]
    assert out["unsafe_paths"] == ["resolved.txt"]


def test_stage_failure_is_reported(tmp_path, monkeypatch):
    conflict(tmp_path)
    before = inspect(tmp_path)
    (tmp_path / "resolved.txt").write_text("resolved\n", encoding="utf-8")
    from ccx import git_pending
    original = git_pending._git

    def locked(cwd, *args, **kwargs):
        if args[0] == "add":
            raise OSError("index locked")
        return original(cwd, *args, **kwargs)

    monkeypatch.setattr(git_pending, "_git", locked)
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["auto_stage"]["failed"] == ["resolved.txt"]
    assert "resolved.txt" in out["auto_stage"]["not_staged"]
    assert "git add resolved paths" in out["steps"]


def test_git_missing_or_non_repository_is_unknown(tmp_path):
    assert inspect(tmp_path)["status"] == "Unknown"
    assert git_auto_stage({}) is False
    with pytest.raises(ValueError):
        git_auto_stage({"git": {"auto_stage_resolved": "false"}})


def test_linked_worktree_and_subdirectory_use_own_index(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    conflict(main)
    git(main, "merge", "--abort")
    linked = tmp_path / "linked"
    git(main, "worktree", "add", "-b", "linked", str(linked), "main")
    assert git(linked, "merge", "other", ok=False).returncode != 0
    sub = linked / "sub"
    sub.mkdir()
    assert (linked / ".git").is_file()
    before = inspect(sub)
    (linked / "resolved.txt").write_text("resolved\n", encoding="utf-8")
    pending = finish(sub, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert pending["operations"] == ["merge"]
    assert pending["auto_stage"]["staged"] == ["resolved.txt"]
    assert pending["unmerged"] == ["markers.txt"]
    assert inspect(main)["operations"] == []
    assert git(main, "show", ":resolved.txt").stdout == "main\n"


def test_deletion_resolution_and_unrelated_edits(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    # The agent chooses deletion for an existing UU content conflict; this is not a DU/UD conflict.
    assert before["conflict_types"]["resolved.txt"] == "UU"
    (tmp_path / "resolved.txt").unlink()
    (tmp_path / "unrelated.txt").write_text("leave alone\n", encoding="utf-8")
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["auto_stage"]["staged"] == ["resolved.txt"]
    assert "unrelated.txt" not in git(tmp_path, "diff", "--cached", "--name-only").stdout


def test_marker_in_staged_file_is_still_reported(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    git(tmp_path, "add", "--", "markers.txt")
    out = inspect(tmp_path, before)
    assert "markers.txt" not in out["unmerged"]
    assert "markers.txt" in out["conflict_markers"]
    assert "resolve conflict markers" in out["steps"]
    assert "markers.txt" not in inspect(tmp_path)["conflict_markers"]


def test_custom_conflict_marker_size_is_not_staged(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    (tmp_path / ".gitattributes").write_text("*.txt conflict-marker-size=3\n", encoding="utf-8")
    (tmp_path / "resolved.txt").write_text("<<< main\nmain\n===\nother\n>>> other\n", encoding="utf-8")
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["fingerprints"]["resolved.txt"] != before["fingerprints"]["resolved.txt"]
    assert out["auto_stage"]["staged"] == []
    assert out["conflict_markers"] == ["markers.txt", "resolved.txt"]


def test_changed_uu_with_conflict_markers_is_never_staged(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    assert before["conflict_types"]["resolved.txt"] == "UU"
    (tmp_path / "resolved.txt").write_text(
        "<<<<<<< main\npartly edited main\n=======\npartly edited other\n>>>>>>> other\n",
        encoding="utf-8", newline="")
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["fingerprints"]["resolved.txt"] != before["fingerprints"]["resolved.txt"]
    assert out["auto_stage"]["staged"] == []
    assert "resolved.txt" in out["conflict_markers"]
    assert "resolved.txt" in out["unmerged"]


def test_literal_unicode_filename_does_not_stage_glob_matches(tmp_path):
    names = ("file [one] 中文.txt", "file o 中文.txt")
    conflict(tmp_path, names=names)
    before = inspect(tmp_path)
    (tmp_path / names[0]).write_text("resolved\n", encoding="utf-8")
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["auto_stage"]["staged"] == [names[0]]
    assert out["unmerged"] == [names[1]]


def test_leadview_preserves_pending_and_existing_verdicts():
    pending = {"status": "known", "steps": ["git add resolved paths"]}
    res = {"run_id": "test", "status": "done", "ok": True, "check": {"passed": True},
           "git_pending": pending}
    assert not clean(res)
    assert line(res)["git_pending"] == pending
    assert receipt_notes(res) == ["Git pending: git add resolved paths"]
    assert res["ok"] is True and res["status"] == "done"


def test_unknown_git_state_keeps_existing_compact_output():
    res = {"run_id": "test", "status": "done", "ok": True, "check": {"passed": True},
           "git_pending": {"status": "Unknown", "steps": []}}
    assert clean(res)
    assert line(res)["git_pending"]["status"] == "Unknown"


class TestReceiptCLI(Env):
    def test_run_and_show_from_outside_repo(self):
        conflict(self.work)
        self.ccx("config", "set", "git.auto_stage_resolved", "true")
        result = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1",
                          "--mode", "write", "--review", "off", "--no-escalate", "resolve conflicts",
                          env={"FAKE_WRITE": "resolved.txt=resolved"})
        assert result.returncode == 0, result.stdout + result.stderr
        out = json.loads(result.stdout)
        assert out["git_pending"]["auto_stage"]["staged"] == ["resolved.txt"]
        assert out["git_pending"]["unmerged"] == ["markers.txt"]
        assert "Git pending" in out["recap"]
        shown = self.ccx("show", out["run_id"])
        assert shown.returncode == 0, shown.stdout + shown.stderr
        assert json.loads(shown.stdout)["git_pending"] == out["git_pending"]
        stored = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        assert stored["git_pending"] == out["git_pending"]


@pytest.mark.parametrize("text", ["Heading\n=========\n", "Heading\n======= xxx\n",
                                  "<<<<<<<word\n>>>>>>>word\n|||||||word\n"])
def test_review_marker_boundaries_do_not_flag_headings(tmp_path, text):
    conflict(tmp_path)
    before = inspect(tmp_path)
    (tmp_path / "resolved.txt").write_text(text, encoding="utf-8")
    out = inspect(tmp_path, before)
    assert "resolved.txt" not in out["conflict_markers"]
    assert out["resolved_unstaged"] == ["resolved.txt"]


def test_review_ordinary_binary_and_symlink_metadata_keep_compact_view(tmp_path, monkeypatch):
    conflict(tmp_path)
    git(tmp_path, "merge", "--abort")
    (tmp_path / "image.png").write_bytes(b"image\0data")
    git(tmp_path, "add", "--", "image.png")
    git(tmp_path, "commit", "-m", "image")
    (tmp_path / "image.png").write_bytes(b"changed\0image")
    from ccx import git_pending

    def forbidden(*args):
        raise AssertionError("ordinary changed files must not be read")

    monkeypatch.setattr(git_pending, "_file", forbidden)
    out = inspect(tmp_path)
    res = {"status": "done", "ok": True, "check": {"passed": True}, "git_pending": out}
    assert clean(res)
    out["unsafe_paths"] = ["image.png", "ordinary-link"]
    assert clean(res)
    out["known_conflicts"] = ["ordinary-link"]
    assert not clean(res)


def test_review_untouched_and_missing_snapshot_are_never_staged(tmp_path):
    conflict(tmp_path)
    path = tmp_path / "resolved.txt"
    path.write_text("already resolved before dispatch\n", encoding="utf-8")
    before = inspect(tmp_path)
    cfg = {"git": {"auto_stage_resolved": True}}
    for snapshot in (None, before):
        out = finish(tmp_path, cfg, snapshot, write=True)
        assert out["auto_stage"]["staged"] == []
        assert "resolved.txt" in out["manual_paths"]
    path.write_text("changed by this run\n", encoding="utf-8")
    out = finish(tmp_path, cfg, before, write=True)
    assert out["auto_stage"]["staged"] == ["resolved.txt"]


@pytest.mark.parametrize("code,stages", [("DU", [1, 3]), ("UD", [1, 2]), ("AU", [2]),
                                        ("UA", [3]), ("DD", [1])])
def test_review_non_content_conflicts_require_manual_choice(tmp_path, code, stages):
    conflict(tmp_path)
    from ccx.git_pending import _git
    blob = git(tmp_path, "rev-parse", "HEAD:resolved.txt").stdout.strip()
    git(tmp_path, "update-index", "--force-remove", "--", "resolved.txt")
    spec = "".join(f"100644 {blob} {stage}\tresolved.txt\n" for stage in stages)
    _git(tmp_path, "update-index", "--index-info", input_data=spec.encode("ascii"))
    before = inspect(tmp_path)
    assert before["conflict_types"]["resolved.txt"] == code
    (tmp_path / "resolved.txt").write_text("changed by agent\n", encoding="utf-8")
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["auto_stage"]["staged"] == []
    assert "resolved.txt" in out["manual_paths"]
    assert "review conflict choices and stage manually" in out["steps"]


def test_review_large_conflict_is_unknown_and_not_staged(tmp_path, monkeypatch):
    conflict(tmp_path)
    before = inspect(tmp_path)
    from ccx import git_pending
    monkeypatch.setattr(git_pending, "MAX_FILE_BYTES", 16)
    (tmp_path / "resolved.txt").write_bytes(b"x" * 100)
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["status"] == "Unknown"
    assert "resolved.txt" in out["unknown_paths"]
    assert out["auto_stage"]["staged"] == []


def test_review_candidate_rechecks_only_its_own_content(tmp_path, monkeypatch):
    conflict(tmp_path)
    before = inspect(tmp_path)
    for name in ("resolved.txt", "markers.txt"):
        (tmp_path / name).write_text("resolved\n", encoding="utf-8")
    from ccx import git_pending
    original = git_pending._file
    calls = []

    def counted(root, name, size):
        calls.append(name)
        return original(root, name, size)

    monkeypatch.setattr(git_pending, "_file", counted)
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["auto_stage"]["staged"] == ["markers.txt", "resolved.txt"]
    assert calls.count("resolved.txt") == 3
    assert calls.count("markers.txt") == 3


def test_review_invalid_config_disables_staging_with_receipt_reason(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    (tmp_path / "resolved.txt").write_text("resolved\n", encoding="utf-8")
    out = finish(tmp_path, {"git": {"auto_stage_resolved": "false"}}, before, write=True)
    assert out["auto_stage"]["enabled"] is False
    assert out["auto_stage"]["staged"] == []
    assert out["auto_stage"]["reason"] == "git.auto_stage_resolved must be true or false"


@pytest.mark.parametrize("link_location", ["ancestor", "inside"])
def test_review_symlink_scope_with_dispatch_hash(tmp_path, monkeypatch, link_location):
    root = tmp_path / "parent" / "repo"
    root.mkdir(parents=True)
    (root / "nested").mkdir()
    name = "nested/resolved.txt"
    conflict(root, names=(name, "markers.txt"))
    before = inspect(root)
    (root / name).write_text("resolved\n", encoding="utf-8")
    linked = root.parent.parent if link_location == "ancestor" else root / "nested"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == linked or original(path))
    out = finish(root, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["auto_stage"]["staged"] == ([name] if link_location == "ancestor" else [])
    assert (name in out["unsafe_paths"]) == (link_location == "inside")


def test_review_staged_markers_are_checked_for_known_conflict(tmp_path):
    conflict(tmp_path)
    before = inspect(tmp_path)
    git(tmp_path, "add", "--", "markers.txt")
    out = inspect(tmp_path, before)
    assert "markers.txt" in out["conflict_markers"]
    assert "markers.txt" not in out["unmerged"]


class TestReviewReceiptCLI(Env):
    def test_review_invalid_config_still_writes_run_and_show_receipts(self):
        conflict(self.work)
        config = self.hub / "ccx" / "tiers.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('[git]\nauto_stage_resolved = "false"\n', encoding="utf-8")
        result = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1",
                          "--mode", "write", "--review", "off", "--no-escalate", "resolve conflicts",
                          env={"FAKE_WRITE": "resolved.txt=resolved"})
        assert result.returncode == 0, result.stdout + result.stderr
        out = json.loads(result.stdout)
        auto = out["git_pending"]["auto_stage"]
        assert auto["enabled"] is False
        assert auto["reason"] == "git.auto_stage_resolved must be true or false"
        shown = self.ccx("show", out["run_id"])
        assert shown.returncode == 0, shown.stdout + shown.stderr
        assert json.loads(shown.stdout)["git_pending"]["auto_stage"] == auto


def test_review_failed_add_with_dispatch_hash_keeps_pending(tmp_path, monkeypatch):
    conflict(tmp_path)
    before = inspect(tmp_path)
    (tmp_path / "resolved.txt").write_text("changed\n", encoding="utf-8")
    from ccx import git_pending
    original = git_pending._git

    def locked(cwd, *args, **kwargs):
        if args[0] == "add":
            raise OSError("index locked")
        return original(cwd, *args, **kwargs)

    monkeypatch.setattr(git_pending, "_git", locked)
    out = finish(tmp_path, {"git": {"auto_stage_resolved": True}}, before, write=True)
    assert out["auto_stage"]["failed"] == ["resolved.txt"]
    assert "resolved.txt" in out["auto_stage"]["not_staged"]
