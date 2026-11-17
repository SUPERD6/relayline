"""Verify actual unit bytes rather than trusting a checkout policy label."""
import io
import os
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts/eval"))
import long_environment as L


def test_native_checkout_rewrites_lf_archive_bytes(tmp_path):
    data = io.BytesIO()
    body = b"first\nsecond\n"
    with tarfile.open(fileobj=data, mode="w") as tar:
        info = tarfile.TarInfo("fixture.txt")
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    repo = tmp_path/"repo"
    evidence = L.build(data.getvalue(), repo)
    assert (repo/"fixture.txt").read_bytes() == (b"first\r\nsecond\r\n" if os.name == "nt" else body)
    assert evidence["eol_counts"] == {"i/lf w/crlf" if os.name == "nt" else "i/lf w/lf": 1}


def test_nonwindows_checkout_does_not_set_autocrlf(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(L, "os", SimpleNamespace(name="posix"))
    def git(repo, *args):
        calls.append(args)
        return "i/lf w/lf attr/\tfixture.txt\n"
    monkeypatch.setattr(L.E, "_git", git)
    evidence = L.checkout(tmp_path)
    assert calls == [("ls-files", "--eol")]
    assert evidence["autocrlf"] == "not-overridden"


def test_explicit_lf_attributes_override_windows_default(tmp_path):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        for name, body in ((".gitattributes", b"fixture.txt text eol=lf\n"), ("fixture.txt", b"first\nsecond\n")):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    repo = tmp_path/"repo"
    evidence = L.build(data.getvalue(), repo)
    assert (repo/"fixture.txt").read_bytes() == b"first\nsecond\n"
    assert evidence["eol_counts"].get("i/lf w/lf", 0) >= 1


def _tar(files):
    import tarfile as _t
    data = io.BytesIO()
    with _t.open(fileobj=data, mode="w") as tar:
        for name, text in files.items():
            body = text.encode()
            info = _t.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return data.getvalue()


def test_validate_task_puts_src_on_path_for_src_layout_task(monkeypatch, tmp_path):
    """#365: --validate-native (p4 pre-check for B/C) validates a src_layout task the way round2_tasks selected it."""
    old = "from srcpkg import f\n\ndef test_f():\n    assert f() == 1\n"
    material = {"tar": _tar({"src/srcpkg/__init__.py": "def f():\n    return 1\n", "tests/test_old.py": old}),
                "reference": _tar({"src/srcpkg/__init__.py": "def f():\n    return 1\n\ndef g():\n    return 2\n",
                                   "tests/test_old.py": old}),
                "tests": {"tests/test_new.py": b"from srcpkg import g\n\ndef test_g():\n    assert g() == 2\n"}}
    monkeypatch.setattr(L.LC, "material", lambda cache, task: material)
    task = {"id": "t", "commit": "c" * 40, "tests": ["tests/test_new.py"]}
    assert L.SRC_ON_PATH is False
    flat = L.validate_task(tmp_path, sys.executable, task)
    assert flat["baseline"]["rc"] != 0 and flat["valid"] is False   # root only: srcpkg does not import
    src = L.validate_task(tmp_path, sys.executable, {**task, "src_layout": True})
    assert src["baseline"]["rc"] == 0 and src["parent"]["rc"] in (1, 2) and src["reference"]["rc"] == 0
    assert src["valid"] is True
    assert L.environment(tmp_path, sys.executable, tmp_path/"t1")["PYTHONPATH"] == str(tmp_path)
