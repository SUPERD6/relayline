"""Issue #506: in a test, the eval scripts' module-level output folders are under the test's tmp_path, not the
checkout's .ccx/ (tests/repo_outputs.py); the scripts' own defaults are unchanged."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import batch  # noqa: E402
import r5  # noqa: E402
import repo_outputs  # noqa: E402

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


def test_session_check_sees_new_eval_files(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_outputs, "EVAL_DIR", tmp_path / "eval")
    (tmp_path / "eval" / "r5").mkdir(parents=True)
    (tmp_path / "eval" / "r5" / "old.json").write_text("{}", encoding="utf-8")
    before = repo_outputs._eval_files()
    (tmp_path / "eval" / "r5" / "streams" / "untagged").mkdir(parents=True)
    (tmp_path / "eval" / "r5" / "streams" / "untagged" / "new.jsonl").write_text("", encoding="utf-8")
    new = repo_outputs._eval_files() - before
    assert [Path(p).name for p in new] == ["new.jsonl"]
