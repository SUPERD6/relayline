"""Issue #506: in a test, the eval scripts' module-level output folders are under the test's tmp_path, not the
checkout's .ccx/ (tests/_ccx_repo_outputs.py); the scripts' own defaults are unchanged; a session that writes under
the checkout's .ccx/eval/ fails."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import _ccx_repo_outputs as RO  # noqa: E402
import batch  # noqa: E402
import r5  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_eval_outputs_point_to_tmp(tmp_path):
    for p in (r5.OUT, batch.OUT, batch.RESULTS):
        assert p.is_relative_to(tmp_path), p
        assert not p.is_relative_to(ROOT / ".ccx"), p
    assert r5.OUT == tmp_path / "repo-ccx" / "eval" / "r5"
    assert r5.results_file("r5") == tmp_path / "repo-ccx" / "eval" / "r5" / "results.jsonl"
    assert batch.OUT != r5.OUT


def test_defaults_unchanged():
    # the scripts' own source keeps the checkout's .ccx/eval as the default
    src = (ROOT / "scripts" / "eval" / "r5.py").read_text(encoding="utf-8")
    assert 'OUT = ROOT / ".ccx" / "eval" / "r5"' in src


def _session():
    return SimpleNamespace(exitstatus=0, config=SimpleNamespace(pluginmanager=SimpleNamespace(
        get_plugin=lambda name: None)))


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(RO, "EVAL_DIR", tmp_path / "eval")
    (tmp_path / "eval" / "r5").mkdir(parents=True)
    old = tmp_path / "eval" / "r5" / "results.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(RO, "_before", None)
    RO.pytest_sessionstart(_session())
    return old


def test_session_check_sees_new_and_appended_files(tmp_path, monkeypatch, capsys):
    old = _seed(tmp_path, monkeypatch)
    (tmp_path / "eval" / "r5" / "streams" / "untagged").mkdir(parents=True)
    (tmp_path / "eval" / "r5" / "streams" / "untagged" / "lead.jsonl").write_text("", encoding="utf-8")
    with open(old, "a", encoding="utf-8") as f:     # what r5 does with results.jsonl
        f.write("{}\n")
    s = _session()
    RO.pytest_sessionfinish(s, 0)
    assert s.exitstatus == 1
    err = capsys.readouterr().err
    assert "lead.jsonl" in err and "results.jsonl" in err


def test_session_check_quiet_when_nothing_written(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)
    s = _session()
    RO.pytest_sessionfinish(s, 0)
    assert s.exitstatus == 0 and capsys.readouterr().err == ""


def test_session_check_only_warns_when_allowed(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)
    (tmp_path / "eval" / "new.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(RO.ALLOW_ENV, "1")
    s = _session()
    RO.pytest_sessionfinish(s, 0)
    assert s.exitstatus == 0 and "new.json" in capsys.readouterr().err
