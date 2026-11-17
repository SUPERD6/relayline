"""Hold-out task set (backlog C1) and its selection in r5.py: task list and flags only (no git history, no real CLI)."""
import contextlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import holdout_check  # noqa: E402
import r5  # noqa: E402
import tasks_holdout  # noqa: E402
import tasks_r5  # noqa: E402


def test_holdout_tasks_are_complete_and_in_band():
    assert len(tasks_holdout.IDS) == len(set(tasks_holdout.IDS)) == 10
    lo, hi = holdout_check.BAND_LINES
    for t in tasks_holdout.T + tasks_holdout.DROPPED:
        assert t["brief"] and t["area"] and len(t["commit"]) >= 7
        assert len(t["tests"]) == 1 and t["tests"][0].startswith("tests/") and t["tests"][0].endswith(".py")
        assert lo <= t["size"] <= hi and holdout_check.BAND_FILES[0] <= t["files"] <= holdout_check.BAND_FILES[1]
        assert "\\" not in t["brief"] and ":/" not in t["brief"]          # generic: no local paths


def test_holdout_shares_nothing_with_r5():
    assert not set(tasks_holdout.IDS) & set(tasks_r5.IDS)
    r5_commits = [t["commit"] for t in tasks_r5.T]
    for t in tasks_holdout.T:
        assert not any(c.startswith(t["commit"]) or t["commit"].startswith(c) for c in r5_commits), t["id"]
    assert len({t["area"] for t in tasks_holdout.T}) == 10                # one task per feature area


def test_holdout_is_half_this_repo_half_other_repos():
    ext = [t for t in tasks_holdout.T if tasks_holdout.external(t)]
    assert len(ext) == 5 and {t["repo"] for t in ext} == set(tasks_holdout.REPOS)
    for t in ext:                                       # pinned by the full sha, tests and stubs named
        assert len(t["commit"]) == 40 and all(c in "0123456789abcdef" for c in t["commit"])
        spec = tasks_holdout.REPOS[t["repo"]]
        assert spec["url"].startswith("https://") and spec["needs"] and spec["pythonpath"] == "src"
        assert "relayline" not in t["brief"] and "ccx" not in t["brief"]
    sizes = sorted(t["size"] for t in tasks_holdout.T)
    assert sizes[0] < 15 and sizes[-1] > 80                # a size spread like r5's (5-91)


def test_dropped_candidates_are_recorded_and_not_scheduled():
    ids = {t["id"] for t in tasks_holdout.DROPPED}
    assert len(ids) == 6 and not ids & set(tasks_holdout.IDS)
    assert all(t["dropped"] for t in tasks_holdout.DROPPED)
    with pytest.raises(StopIteration):
        tasks_holdout.by_id("send-busy-guard")
    assert tasks_holdout.dropped_by_id("send-busy-guard")["deselect"]


def test_r5_stays_the_default():
    a = r5.parser().parse_args(["run"])
    assert a.taskset == "r5" and r5.IDS == tasks_r5.IDS
    assert r5.results_file("r5") == r5.OUT / "results.jsonl"
    assert r5.results_file("holdout") != r5.results_file("r5")
    assert r5.parser().parse_args(["summary"]).taskset == "r5"


def test_by_id_finds_tasks_of_either_set():
    assert r5.by_id(tasks_r5.IDS[0])["commit"] == tasks_r5.T[0]["commit"]
    assert r5.by_id(tasks_holdout.IDS[0])["commit"] == tasks_holdout.T[0]["commit"]
    with pytest.raises(KeyError):
        r5.by_id("no-such-task")


def _dry(tmp_path, *extra):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = r5.main(["run", "--dry-run", "--rounds", "1", "--arms", "self", "--out", str(tmp_path / "res.jsonl"),
                      "--workdir", str(tmp_path / "work"), *extra])
    return rc, buf.getvalue()


def test_taskset_flag_schedules_the_holdout_tasks(tmp_path):
    rc, out = _dry(tmp_path, "--taskset", "holdout")
    assert rc == 0
    assert {ln.split(":")[3] for ln in out.splitlines() if ln.startswith("[dry]")} == set(tasks_holdout.IDS)
    rc, out = _dry(tmp_path)
    assert {ln.split(":")[3] for ln in out.splitlines() if ln.startswith("[dry]")} == set(tasks_r5.IDS)


def test_tasks_must_belong_to_the_chosen_set(tmp_path):
    with pytest.raises(SystemExit):
        _dry(tmp_path, "--tasks", tasks_holdout.IDS[0])                  # a hold-out id under the default r5 set
    rc, out = _dry(tmp_path, "--taskset", "holdout", "--tasks", tasks_holdout.IDS[0])
    assert rc == 0 and out.count("[dry]") == 1


def test_deselected_tests_are_left_out_of_scoring():
    t = tasks_holdout.dropped_by_id("send-busy-guard")
    assert t["deselect"] and all(n.startswith(t["tests"][0] + "::") for n in t["deselect"])
    assert r5.pytest_args(t) == [*t["tests"], "--deselect", t["deselect"][0]]
    assert r5.pytest_args(tasks_r5.T[0]) == tasks_r5.T[0]["tests"]          # r5 tasks run as before


def test_other_worktrees_of_the_checkout_are_forbidden(tmp_path):
    import preflight as PF
    other = tmp_path / "sibling-worktree"
    real = {**PF.real_paths(), "root_worktrees": [other]}
    u = PF.Unit(key="k", work=tmp_path / "work", repo=tmp_path / "work" / "k", hub=tmp_path / "work" / "h-k",
                real=real)
    assert other in PF.forbidden(u)
    assert any("sibling-worktree" in d for d in PF.claude_settings(u)["permissions"]["deny"])


def _changed_tests(old: str, new: str) -> list[str]:
    """Test functions (Class::name) whose body differs between two versions of a test file, as NEW_TESTS lists."""
    import ast

    def funcs(src):
        out = {}

        def walk(nodes, prefix):
            for n in nodes:
                if isinstance(n, ast.ClassDef):
                    walk(n.body, prefix + n.name + "::")
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                    out[prefix + n.name] = ast.dump(n)
        walk(ast.parse(src).body, "")
        return out
    o, n = funcs(old), funcs(new)
    return [k for k, v in n.items() if o.get(k) != v]


def test_every_hidden_check_derives_from_its_brief():
    """derives_from: every test the commit added or changed is mapped, each quote is the brief's own words, and the
    map says whether it has been independently reviewed (completeness only: whether a quote really determines
    the check is the reviewer's call, not a test's)."""
    norm = lambda x: " ".join(x.split())  # noqa: E731
    assert set(tasks_holdout.DERIVES_FROM) == set(tasks_holdout.IDS) == set(tasks_holdout.NEW_TESTS)
    for t in tasks_holdout.T:
        m = tasks_holdout.derives_from(t["id"])
        assert m and {e["test"] for e in m} == set(tasks_holdout.NEW_TESTS[t["id"]]), t["id"]
        for e in m:
            assert e["test"].split("::")[0] in t["tests"] and e["checks"], (t["id"], e)
            assert e["brief"] or e.get("regression"), (t["id"], e)           # a quote, or why there is none
            for q in e["brief"]:
                assert norm(q) in norm(t["brief"]), (t["id"], q)
    assert tasks_holdout.REVIEW["status"] in ("draft", "reviewed")
    assert tasks_holdout.REVIEW["status"] == "draft" or tasks_holdout.REVIEW["independent_review"]


def test_new_tests_match_the_commits_where_history_is_here():
    """For this repository's tasks NEW_TESTS is recomputed from git (skipped in a shallow clone)."""
    import subprocess
    root = Path(__file__).resolve().parents[1]
    checked = 0
    for t in tasks_holdout.T:
        if tasks_holdout.external(t):
            continue
        f = t["tests"][0]
        show = lambda rev: subprocess.run(["git", "show", f"{rev}:{f}"], cwd=root, capture_output=True,  # noqa: E731
                                          text=True, encoding="utf-8")
        new, old = show(t["commit"]), show(t["commit"] + "^")
        if new.returncode:
            continue
        got = [f"{f}::{x}" for x in _changed_tests(old.stdout if old.returncode == 0 else "", new.stdout)]
        assert sorted(got) == sorted(tasks_holdout.NEW_TESTS[t["id"]]), t["id"]
        checked += 1
    if not checked:
        pytest.skip("no history of the hold-out commits here (shallow clone)")


def test_same_repository_is_recognised_across_old_and_owner_name_formats(monkeypatch):
    """#400: an older task's `boltons` and a round 2 task's `mahmoud/boltons` are one repository."""
    monkeypatch.setattr(holdout_check, "static", lambda *a, **k: [])
    monkeypatch.setattr(holdout_check, "change_of", lambda t, ctx: {"size": 10, "files": t["files"]})
    old = {"id": "old", "repo": "boltons", "commit": "a" * 40, "files": ["boltons/x.py"], "tests": []}
    new = {"id": "new", "repo": "mahmoud/boltons", "commit": "b" * 40, "files": ["boltons/x.py"], "tests": []}
    other = {"id": "other", "repo": "o/pluggy", "commit": "c" * 40, "files": ["boltons/x.py"], "tests": []}
    row = holdout_check.check(new, [old, other], Path("unused"), run_tests=False, ctx=object())
    assert row["files_shared_with_other_set"] == ["boltons/x.py"]
    lone = holdout_check.check(new, [other], Path("unused"), run_tests=False, ctx=object())
    assert "files_shared_with_other_set" not in lone
