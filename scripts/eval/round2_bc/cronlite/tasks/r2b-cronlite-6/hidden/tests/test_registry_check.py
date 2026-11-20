import io
import json
from datetime import datetime

import pytest

from cronlite import CronError, Registry, dumps, lint_all, lint_registry
from cronlite.cli import run

MON = datetime(2026, 3, 2, 8, 0)   # a Monday


def test_lint_all_ignore():
    jobs = {"x": "0 * * * *", "y": "0 * * * *", "z": "0 0 13 * 5"}
    assert lint_all(jobs, ignore=["duplicate"]) == {"z": ["day-and-weekday"]}
    assert lint_all(jobs, ignore=("duplicate", "day-and-weekday")) == {}
    with pytest.raises(CronError):
        lint_all(jobs, ignore=["dupe"])


def test_retry_overlap_boundary():
    r = Registry()
    r.add("tight", "0,30 * * * *", retries=3, retry_delay=10)
    r.add("roomy", "15,45 * * * *", retries=2, retry_delay=10)
    r.add("never-retries", "* * * * *")
    assert lint_registry(r, MON) == {"never-retries": ["every-minute"], "tight": ["retry-overlap"]}


def test_retry_overlap_uses_firings_after_start():
    r = Registry()
    r.add("weekly", "0 9 * * 1", retries=3, retry_delay=3360)
    r.add("monthly", "0 9 1 * *", retries=100, retry_delay=1000)
    r.add("impossible", "0 0 31 2 *", retries=5)
    assert lint_registry(r, MON) == {"impossible": ["never"], "weekly": ["retry-overlap"]}


def test_retry_overlap_comes_last_and_can_be_ignored():
    r = Registry()
    r.add("a", "0 * * * *")
    r.add("b", "0 * * * *", retries=2, retry_delay=30)
    assert lint_registry(r, MON) == {"a": ["duplicate"], "b": ["duplicate", "retry-overlap"]}
    assert lint_registry(r, MON, ignore=["retry-overlap"]) == {"a": ["duplicate"], "b": ["duplicate"]}
    with pytest.raises(CronError):
        lint_registry(r, MON, ignore=["colliding"])


def _saved(tmp_path):
    r = Registry()
    r.add("a", "0 * * * *")
    r.add("b", "0 * * * *", retries=2, retry_delay=30)
    r.add("c", "15 3 * * *", retries=1)
    path = tmp_path / "jobs.json"
    path.write_text(dumps(r), encoding="utf-8")
    return str(path)


def test_cli_check_text(tmp_path):
    path, out = _saved(tmp_path), io.StringIO()
    assert run(["check", path, "--from", "2026-03-02T08:00"], out) == 1
    assert out.getvalue() == "a: duplicate\nb: duplicate, retry-overlap\n"
    out = io.StringIO()
    assert run(["check", path, "--from", "2026-03-02T08:00", "--ignore", "duplicate"], out) == 1
    assert out.getvalue() == "b: retry-overlap\n"
    out = io.StringIO()
    code = run(["check", path, "--from", "2026-03-02T08:00", "--ignore", "duplicate", "--ignore", "retry-overlap"],
               out)
    assert code == 0 and out.getvalue() == ""


def test_cli_check_json(tmp_path):
    path, out = _saved(tmp_path), io.StringIO()
    assert run(["check", path, "--from", "2026-03-02T08:00", "--json"], out) == 1
    assert json.loads(out.getvalue()) == {"a": ["duplicate"], "b": ["duplicate", "retry-overlap"]}
    assert out.getvalue().endswith("\n") and out.getvalue().count("\n") == 1
    out = io.StringIO()
    clean = run(["check", path, "--from", "2026-03-02T08:00", "--json", "--ignore", "duplicate", "--ignore",
                 "retry-overlap"], out)
    assert clean == 0 and json.loads(out.getvalue()) == {}


def test_cli_check_errors(tmp_path):
    assert run(["check", str(tmp_path / "none.json")], io.StringIO()) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert run(["check", str(broken)], io.StringIO()) == 2
    assert run(["check", _saved(tmp_path), "--ignore", "nope"], io.StringIO()) == 2


def test_cli_lint_ignore():
    out = io.StringIO()
    assert run(["lint", "0 0 13 * 5", "--ignore", "day-and-weekday"], out) == 0 and out.getvalue() == ""
    assert run(["lint", "0 0 13 * 5", "--ignore", "bogus"], io.StringIO()) == 2
