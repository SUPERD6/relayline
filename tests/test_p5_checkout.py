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
