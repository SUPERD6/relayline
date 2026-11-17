"""scripts/eval/long_environment (issue #359): a baseline or hidden check that times out ends the whole process tree,
not only the shell. The repo is a scratch one whose only test starts a grandchild and hangs; no real CLI is started."""
import subprocess
import sys

import pytest

import _hang_tree as H
import long_environment as L  # noqa: E402  (scripts/eval is on sys.path via _hang_tree)


@pytest.mark.parametrize("which", ["baseline", "hidden"])
def test_timeout_ends_pytest_and_its_children(tmp_path, which):
    repo = tmp_path / "repo"
    repo.mkdir()
    pids_file = tmp_path / "pids"
    (repo / "test_hang.py").write_text(H.hang_source(pids_file), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    def call():
        if which == "baseline":
            return L.baseline(repo, sys.executable, repo / ".ccx-eval-tmp-acceptance", timeout=10)
        return L.hidden(repo, ["test_hang.py"], sys.executable, timeout=10)

    out = H.run_and_check_tree_ended(pids_file, call)
    assert out["rc"] is None and out["summary"] == f"{which} timeout"
