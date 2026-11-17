"""#367: p4 hidden-test scoring puts src/ on PYTHONPATH for src-layout tasks, as round-2 validation does (#364)."""
import io
import json
import sys
import tarfile

import pytest

from test_p4_round2 import dry, task_file

import p4_long_session as P


def _tar(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


HIDDEN = {"tests/test_hidden.py": b"from pkg import answer\n\ndef test_answer():\n    assert answer() == 42\n"}


def _repo(tmp_path, package_dir: str):
    """A fake repo whose reference implementation lives at <package_dir>/pkg (src/pkg or pkg)."""
    repo = tmp_path / "repo"
    (repo / package_dir / "pkg").mkdir(parents=True)
    (repo / package_dir / "pkg" / "__init__.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_old.py").write_text("def test_old():\n    pass\n", encoding="utf-8")
    material = {"tar": _tar({"tests/test_old.py": "def test_old():\n    pass\n"}), "tests": HIDDEN}
    return repo, material


def _task(src_layout=None):
    task = {"id": "t", "repo": "fake", "commit": "1" * 40, "brief": "b", "tests": ["tests/test_hidden.py"], "code": ["x"]}
    if src_layout is not None:
        task["src_layout"] = src_layout
    return task


def test_src_layout_reference_passes_p4_scoring(tmp_path):
    repo, material = _repo(tmp_path, "src")
    res = P.score(repo, _task(src_layout=True), material, sys.executable)
    assert res["ok"] is True, res["output"]


def test_src_layout_task_without_flag_still_scores_root_only(tmp_path):
    # The flag, not the folder, decides: a task that does not say src_layout keeps the old root-only PYTHONPATH.
    repo, material = _repo(tmp_path, "src")
    res = P.score(repo, _task(), material, sys.executable)
    assert res["ok"] is False and "ModuleNotFoundError" in res["output"]


@pytest.mark.parametrize("flag", [None, False])
def test_flat_layout_unchanged(tmp_path, flag):
    repo, material = _repo(tmp_path, ".")
    res = P.score(repo, _task(src_layout=flag), material, sys.executable)
    assert res["ok"] is True, res["output"]


def test_round2_dry_run_counts_src_layout_tasks(tmp_path):
    f, _ = task_file(tmp_path, n=3)
    data = json.loads(f.read_text(encoding="utf-8"))
    data["accepted"][0]["src_layout"] = True
    data["accepted"][1]["src_layout"] = False
    f.write_text(json.dumps(data), encoding="utf-8", newline="")
    import hashlib
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    r = dry(["--split", "r2b", "--tasks-file", str(f), "--tasks-sha256", sha,
             "--arms", "self,ccxcheapfirst2", "--budget", "10"], tmp_path)
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert plan["src_layout_tasks"] == 1
