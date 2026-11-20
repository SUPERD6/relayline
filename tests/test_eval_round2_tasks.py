"""Round 2 task tools (#348): fake repositories and fake runners only; no model, no network."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/eval"))
import round2_tasks as R  # noqa: E402


def _git(cwd, *args, date=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    r = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _commit(work, files, date, message):
    for rel, text in files.items():
        p = work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", message, date=date)
    return _git(work, "rev-parse", "HEAD").strip()


def _bulk(n, tag):
    return "".join(f"def {tag}_{i}():\n    return {i}\n" for i in range(n))


@pytest.fixture(scope="module")
def fake_cache(tmp_path_factory):
    """c1 valid; c2 no fail->pass; c3 breaks the suite without tests; c4 valid change on a broken parent."""
    root = tmp_path_factory.mktemp("r2repo")
    work = root / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    ok_test = "from pkg.mod import base\n\ndef test_base():\n    assert base() == 1\n"
    c0 = _commit(work, {"pkg/__init__.py": "", "pkg/mod.py": "def base():\n    return 1\n",
                        "tests/test_mod.py": ok_test}, "2026-01-01T00:00:00+00:00", "base")
    _commit(work, {"README": "old\n"}, "2026-02-01T00:00:00+00:00", "old commit before the date limit")
    c1 = _commit(work, {"pkg/new.py": _bulk(31, "n") + "def new():\n    return 7\n", "tests/__init__.py": "",
                        "tests/test_new.py": "from pkg.new import new\n\ndef test_new():\n    assert new() == 7\n"},
                 "2026-08-01T00:00:00+00:00", "add new")
    c2 = _commit(work, {"pkg/more.py": _bulk(31, "m"),
                        "tests/test_more.py": "from pkg.mod import base\n\ndef test_again():\n    assert base() == 1\n"},
                 "2026-08-02T00:00:00+00:00", "test existing behavior only")
    c3 = _commit(work, {"pkg/mod.py": "def base():\n    return 2\n"}, "2026-08-03T00:00:00+00:00", "break base")
    c4 = _commit(work, {"pkg/x.py": _bulk(31, "x") + "def x():\n    return 3\n",
                        "tests/test_x.py": "from pkg.x import x\n\ndef test_x():\n    assert x() == 3\n"},
                 "2026-08-04T00:00:00+00:00", "add x on broken parent")
    c5 = _commit(work, {"pkg/y.py": _bulk(31, "y"), "tests/conftest.py": "import pytest\n",
                        "tests/test_y.py": "from pkg.y import y_1\n\ndef test_y():\n    assert y_1() == 1\n"},
                 "2026-08-05T00:00:00+00:00", "change test support file")
    (work / "tests/test_more.py").unlink()
    c6 = _commit(work, {"pkg/z.py": _bulk(31, "z"),
                        "tests/test_z.py": "from pkg.z import z_1\n\ndef test_z():\n    assert z_1() == 1\n"},
                 "2026-08-06T00:00:00+00:00", "delete a test file")
    cache = root / "cache"
    cache.mkdir()
    _git(root, "clone", "-q", "--bare", str(work), str(cache / "fakepkg.git"))
    return {"cache": cache, "c0": c0, "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c6": c6}


def test_upstream_selection_on_fake_repository(fake_cache, tmp_path):
    repos = [{"repo": "boltons", "project": "boltons"}, {"repo": "fakepkg", "project": "fakepkg"}]
    out = R.select_upstream(fake_cache["cache"], repos, sys.executable, used={"boltons"})
    reasons = {e.get("commit") or e["repo"]: e["reason"] for e in out["exclusions"]}
    assert [t["commit"] for t in out["B"]] == [fake_cache["c1"]]
    assert "existing suite does not pass on parent" in reasons[fake_cache["c4"]]
    assert "no hidden test fails on parent" in reasons[fake_cache["c2"]]
    assert reasons[fake_cache["c3"]] == "no test file added or changed"
    assert reasons[fake_cache["c5"]] == "changes test support files: tests/conftest.py"
    assert reasons[fake_cache["c6"]] == "deletes or renames a test file: tests/test_more.py"
    assert out["B"][0]["src_layout"] is False
    assert reasons["boltons"] == "repository used in an earlier evaluation"
    before = [e for e in out["exclusions"] if e["reason"].startswith("commit before")]
    assert before == [{"repo": "fakepkg", "reason": "commit before 2026-07-01", "count": 1}]
    assert out["models_called"] is False and out["b_shortfall"] == R.B_TAKE - 1


def test_groups_caps_and_size_rules(monkeypatch):
    monkeypatch.setattr(R, "B_TAKE", 2)
    monkeypatch.setattr(R, "C_TAKE", 1)
    monkeypatch.setattr(R, "B_CAP", 1)
    monkeypatch.setattr(R, "compiled_files", lambda cache, repo: [])
    monkeypatch.setattr(R, "test_changes", lambda cache, repo, sha: None)
    monkeypatch.setattr(R, "src_layout", lambda cache, repo, sha: False)
    monkeypatch.setattr(R, "installed_overlap", lambda *a, **k: None)
    monkeypatch.setattr(R, "ext_plugins", lambda python: [])

    def row(sha, ts, lines, files=1):
        return {"commit": sha * 40, "timestamp": ts, "tests": ["tests/test_a.py"], "code_lines": lines,
                "code": [f"m{i}.py" for i in range(files)], "subject": "s"}
    hist = {"r1": [row("a", 2_000_000_000, 80), row("b", 1_999_999_999, 80)],
            "r2": [row("c", 2_000_000_000, 70), row("d", 1_999_999_998, 160), row("e", 1_999_999_997, 10)]}
    monkeypatch.setattr(R.LCand, "history", lambda cache, repo: hist[repo])
    out = R.select_upstream(Path("x"), [{"repo": "r1"}, {"repo": "r2"}], "py", set(),
                            validator=lambda *a: {"valid": True})
    assert [t["commit"][0] for t in out["B"]] == ["a", "c"]
    assert [t["commit"][0] for t in out["C"]] == ["d"]
    reasons = {e["commit"][0]: e["reason"] for e in out["exclusions"] if "commit" in e}
    assert reasons["b"].startswith("repository cap (B")
    assert out["c_shortfall"] == 0
    # the walk goes on for the development tasks (#371): e is too small even for B-dev
    assert reasons["e"].startswith("implementation change below")


def _dev_setup(monkeypatch, hist, b_dev, c_dev, b_cap, c_cap):
    for name, value in (("B_TAKE", 1), ("C_TAKE", 1), ("B_DEV_TAKE", b_dev), ("C_DEV_TAKE", c_dev),
                        ("B_CAP", b_cap), ("C_CAP", c_cap)):
        monkeypatch.setattr(R, name, value)
    monkeypatch.setattr(R, "compiled_files", lambda cache, repo: [])
    monkeypatch.setattr(R, "test_changes", lambda cache, repo, sha: None)
    monkeypatch.setattr(R, "src_layout", lambda cache, repo, sha: False)
    monkeypatch.setattr(R, "installed_overlap", lambda *a, **k: None)  # no real --ext-python in these tests
    monkeypatch.setattr(R, "ext_plugins", lambda python: [])
    monkeypatch.setattr(R.LCand, "history", lambda cache, repo: hist[repo])


def _row(sha, ts, lines):
    return {"commit": sha * 40, "timestamp": ts, "tests": ["tests/test_a.py"], "code_lines": lines,
            "code": ["m.py"], "subject": "s"}


def _select(repos):
    return R.select_upstream(Path("x"), [{"repo": r} for r in repos], "py", set(), validator=lambda *a: {"valid": True})


def test_dev_tasks_follow_in_the_same_order_with_shared_b_cap(monkeypatch):
    t = 2_000_000_000
    hist = {"r1": [_row("a", t, 80), _row("b", t - 1, 80), _row("c", t - 2, 160), _row("d", t - 3, 80),
                   _row("x", t - 4, 80)],
            "r2": [_row("e", t, 80), _row("g", t - 1, 160), _row("h", t - 2, 160)],
            "r3": [_row("i", t, 160)]}
    _dev_setup(monkeypatch, hist, b_dev=2, c_dev=1, b_cap=2, c_cap=4)
    out = _select(["r1", "r2", "r3"])
    # final tasks exactly as before #371
    assert [t["commit"][0] for t in out["B"]] == ["a"] and [t["commit"][0] for t in out["C"]] == ["c"]
    assert out["b_shortfall"] == 0 and out["c_shortfall"] == 0
    # b (B-size, before C's first task) is not a B-dev task; d follows C; x hits the B cap shared with B
    assert [t["commit"][0] for t in out["dev"]["B"]] == ["d", "e"]
    assert [t["commit"][0] for t in out["dev"]["C"]] == ["g"]
    assert all(t["dev"] is True for t in out["dev"]["B"] + out["dev"]["C"])
    assert all("dev" not in t for t in out["B"] + out["C"])
    assert {t["group"] for t in out["dev"]["B"]} == {"B"} and {t["group"] for t in out["dev"]["C"]} == {"C"}
    assert out["dev_shortfall"] == {"B": 0, "C": 0}
    reasons = {e["commit"][0]: e["reason"] for e in out["exclusions"] if "commit" in e}
    assert reasons["b"].startswith("below C size rule")
    assert reasons["x"].startswith("repository cap (B")
    assert "h" not in reasons and "i" not in reasons  # stops once the development tasks are full
    assert [e.get("dev", False) for e in out["exclusions"] if "commit" in e] == [False, True]  # b, x
    assert {c["commit"][0]: c.get("dev", False) for c in out["checked"]} == {
        "a": False, "c": False, "d": True, "e": True, "g": True}


def test_dev_phase_leaves_final_selection_unchanged(monkeypatch):
    t = 2_000_000_000
    hist = {"r1": [_row(s, t - i, n) for i, (s, n) in enumerate(zip("abcdefgh", (80, 10, 80, 160, 80, 160, 80, 160)))],
            "r2": [_row(s, t - i, n) for i, (s, n) in enumerate(zip("ijklmn", (160, 80, 160, 10, 80, 160)))]}
    _dev_setup(monkeypatch, hist, b_dev=0, c_dev=0, b_cap=2, c_cap=1)
    no_dev = _select(["r1", "r2"])
    monkeypatch.setattr(R, "B_DEV_TAKE", 2)
    monkeypatch.setattr(R, "C_DEV_TAKE", 1)
    with_dev = _select(["r1", "r2"])
    assert with_dev["B"] == no_dev["B"] and with_dev["C"] == no_dev["C"]
    assert with_dev["exclusions"][:len(no_dev["exclusions"])] == no_dev["exclusions"]
    assert with_dev["dev"]["B"] and with_dev["dev"]["C"]


def test_dev_c_shares_c_cap_and_reports_shortfall(monkeypatch):
    t = 2_000_000_000
    hist = {"r1": [_row("a", t, 80), _row("c", t - 1, 160), _row("d", t - 2, 80), _row("e", t - 3, 160),
                   _row("f", t - 4, 80)]}
    _dev_setup(monkeypatch, hist, b_dev=1, c_dev=1, b_cap=6, c_cap=1)
    out = _select(["r1"])
    assert [t["commit"][0] for t in out["dev"]["B"]] == ["d"] and out["dev"]["C"] == []
    reasons = {e["commit"][0]: e["reason"] for e in out["exclusions"] if "commit" in e}
    assert reasons["e"].startswith("repository cap (C")
    assert reasons["f"].startswith("below C size rule")
    assert out["dev_shortfall"] == {"B": 0, "C": 1}


def test_no_dev_tasks_when_final_groups_are_short(monkeypatch):
    t = 2_000_000_000
    _dev_setup(monkeypatch, {"r1": [_row("a", t, 80), _row("b", t - 1, 80)]}, b_dev=4, c_dev=2, b_cap=6, c_cap=4)
    out = _select(["r1"])
    assert out["c_shortfall"] == 1 and out["dev"] == {"B": [], "C": []}
    assert out["dev_shortfall"] == {"B": 4, "C": 2}


def test_cli_select_reports_dev_and_downstream_includes_dev(tmp_path, monkeypatch, capsys):
    t = 2_000_000_000
    _dev_setup(monkeypatch, {"r1": [_row("a", t, 80), _row("c", t - 1, 160), _row("d", t - 2, 80)]},
               b_dev=2, c_dev=1, b_cap=6, c_cap=4)
    monkeypatch.setattr(R, "_validate", lambda *a: {"valid": True})
    monkeypatch.setattr(R, "installed_overlap", lambda *a, **k: None)  # no real --ext-python here (#415)
    monkeypatch.setattr(R, "ext_plugins", lambda python: [])
    monkeypatch.setattr(R, "runner_missing", lambda python: [])
    monkeypatch.setattr(R, "corpus", lambda **k: {"repos": set()})
    (tmp_path / "cache").mkdir()
    (tmp_path / "repos.json").write_text(json.dumps({"kept": [{"repo": "r1"}]}), encoding="utf-8")
    out = tmp_path / "sel.json"
    rc = R.main(["select", "--repos-json", str(tmp_path / "repos.json"), "--ext-cache", str(tmp_path / "cache"),
                 "--ext-python", "py", "--out", str(out)])
    printed = capsys.readouterr().out
    assert rc == 0  # a development shortfall is filled by authored tasks, not a failed selection
    assert "dev B 1/2, C 0/1" in printed and "author" in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [t["commit"][0] for t in data["dev"]["B"]] == ["d"]
    assert set(data["environment"]) == {"ext_python_version", "prepare_json_sha256"}  # recorded (#415)
    # env-check covers the development tasks too
    seen = []
    monkeypatch.setattr(R, "own_package", lambda py, project, ts, meta, run: seen.append(project) or {"ok": True})
    for task in data["dev"]["B"]:
        task["project"] = "devpkg"
    quiet = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr="")  # no site-packages
    assert R.env_check(data, "py", None, quiet)["ok"] and "devpkg" in seen
    # leak reads B, C and the development tasks from a selection file
    leaked = []
    monkeypatch.setattr(R, "leak_check", lambda tasks, corp: leaked.extend(tasks) or {"clean": True})
    assert R.main(["leak", "--tasks", str(out), "--out", str(tmp_path / "leak.json")]) == 0
    assert sorted(t["commit"][0] for t in leaked) == ["a", "c", "d"]
    # the output names the files left out of the corpus: the task file, the output and any --exclude
    extra = tmp_path / "briefs.json"
    assert R.main(["leak", "--tasks", str(out), "--exclude", str(extra), "--out", str(tmp_path / "leak.json")]) == 0
    assert json.loads((tmp_path / "leak.json").read_text(encoding="utf-8"))["excluded_from_corpus"] == [
        out.as_posix(), (tmp_path / "leak.json").as_posix(), extra.as_posix()]
    # a final-task shortfall still fails the command
    monkeypatch.setattr(R, "C_TAKE", 5)
    assert R.main(["select", "--repos-json", str(tmp_path / "repos.json"), "--ext-cache", str(tmp_path / "cache"),
                   "--ext-python", "py", "--out", str(out)]) == 1


def test_compiled_repository_is_excluded(monkeypatch):
    monkeypatch.setattr(R.LCand, "history", lambda cache, repo: [])
    monkeypatch.setattr(R, "compiled_files", lambda cache, repo: ["src/speed.c"])
    out = R.select_upstream(Path("x"), [{"repo": "r"}], "py", set(), registered=[])
    assert out["exclusions"] == [{"repo": "r", "reason": "not pure Python: src/speed.c"}]


def _authored(root, reference_mul="a * b", reference_add="a + b"):
    (root / "start/tests").mkdir(parents=True)
    (root / "start/calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "start/tests/test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
                                                   encoding="utf-8")
    (root / "reference").mkdir()
    import shutil
    shutil.copytree(root / "start/tests", root / "reference/tests")
    (root / "reference/calc.py").write_text(f"def add(a, b):\n    return {reference_add}\n\ndef mul(a, b):\n    return {reference_mul}\n",
                                            encoding="utf-8")
    (root / "hidden/tests").mkdir(parents=True)
    (root / "hidden/tests/test_hidden.py").write_text(
        "from calc import mul\n\ndef test_mul():\n    assert mul(6, 7) == 42\n    assert mul(0, 5) == 0\n", encoding="utf-8")
    brief = "Add mul(a, b) that returns the product. Multiplying by zero gives zero."
    trace = [{"assertion": "tests/test_hidden.py::test_mul#1", "brief": "Add mul(a, b) that returns the product."},
             {"assertion": "tests/test_hidden.py::test_mul#2", "brief": "Multiplying by zero gives zero."}]
    (root / "task.json").write_text(json.dumps({"id": "auth-1", "brief": brief, "hidden_tests": ["tests/test_hidden.py"],
                                                "trace": trace}), encoding="utf-8")
    return root


def test_authored_task_valid_and_broken_reference_flagged(tmp_path):
    good = R.check_authored(_authored(tmp_path / "good"), sys.executable)
    assert good["valid"], good["problems"]
    bad = R.check_authored(_authored(tmp_path / "bad", "a + b"), sys.executable)
    assert not bad["valid"]
    assert any(p.startswith("reference fails hidden tests") for p in bad["problems"])


def test_authored_reference_must_keep_existing_tests(tmp_path):
    """#452: a reference that passes the hidden tests but breaks an existing test is invalid, and the failing test is named."""
    good = R.check_authored(_authored(tmp_path / "good"), sys.executable)
    assert good["valid"] and good["reference_full"]["rc"] == 0 and good["reference_failed"] == []
    bad = R.check_authored(_authored(tmp_path / "bad", reference_add="a - b"), sys.executable)
    assert bad["reference"]["rc"] == 0  # the old check (hidden tests only) would have passed it
    assert not bad["valid"]
    assert any(p.startswith("reference breaks existing or hidden tests") and "test_add" in p for p in bad["problems"])
    assert any("test_add" in n for n in bad["reference_failed"])


def test_authored_reports_every_failed_existing_test(tmp_path):
    """#452: with several failures every test name is reported (tracebacks must not use up the kept lines)."""
    root = _authored(tmp_path / "t", reference_add="a - b")
    body = "from calc import add"+'\n'+'\n'+"".join(f"def test_extra{i}():"+'\n'+"    assert add(1, 2) == 3"+'\n'+'\n' for i in range(4))
    for part in ("start", "reference"):
        (root / part / "tests/test_extra.py").write_text(body, encoding="utf-8")
    out = R.check_authored(root, sys.executable)
    assert not out["valid"]
    names = " ".join(out["reference_failed"])
    assert all(f"test_extra{i}" in names for i in range(4)) and "test_add" in names and len(out["reference_failed"]) == 5


def test_authored_hidden_version_replaces_same_named_existing_test(tmp_path):
    """The hidden copy of a same-named existing file wins, so an old assertion the task changes does not fail the reference."""
    root = _authored(tmp_path / "t", reference_add="a + b + 1")
    (root / "hidden/tests/test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 4\n", encoding="utf-8")
    cfg = json.loads((root / "task.json").read_text(encoding="utf-8"))
    cfg["hidden_tests"] = ["tests/test_calc.py", "tests/test_hidden.py"]
    cfg["trace"] = []
    (root / "task.json").write_text(json.dumps(cfg), encoding="utf-8")
    out = R.check_authored(root, sys.executable)
    assert out["reference_full"]["rc"] == 0 and out["reference_failed"] == []


def test_brief_literal_overlap_and_trace_coverage():
    hidden = {"t.py": "def test_a():\n    assert f('hello world') == 4242\n    assert g(3) == 1\n"}
    res = R.brief_checks("f returns 4242 for 'hello world'.", hidden,
                         [{"assertion": "t.py::test_a#1", "brief": "f returns 4242 for 'hello world'."}])
    assert {o["literal"] for o in res["literal_overlap"]} == {"hello world", 4242}
    assert res["unmapped"] == ["t.py::test_a#2"] and not res["trace_complete"]
    res = R.brief_checks("Plain text.", hidden, [{"assertion": "t.py::test_a#1", "brief": "Plain text."},
                                                 {"assertion": "t.py::test_a#2", "brief": "Not in brief."},
                                                 {"assertion": "t.py::nope#1", "brief": "Plain text."}])
    assert res["sentence_not_in_brief"] == ["Not in brief."] and res["unknown_in_trace"] == ["t.py::nope#1"]


def _fake_root(tmp_path):
    (tmp_path / "scripts/eval").mkdir(parents=True)
    (tmp_path / "docs/research/data").mkdir(parents=True)
    (tmp_path / "scripts/eval/tasks_old.py").write_text(
        "T = []\nfor i in range(1):\n    T.append({'id': 'old-1', 'repo': 'oldrepo', 'commit': '" + "ab" * 20 + "',\n"
        "              'brief': 'Add a retry option to the download helper so transient errors are retried three times.'})\n",
        encoding="utf-8")
    (tmp_path / "docs/research/data/run.json").write_text(json.dumps(
        {"rows": [{"task": "x", "repo": "https://github.com/someone/OtherRepo.git", "commit": "cdef012"}]}), encoding="utf-8")
    return tmp_path


def test_leak_check_against_earlier_tasks(tmp_path):
    corp = R.corpus(_fake_root(tmp_path))
    assert {"oldrepo", "otherrepo", "more-itertools", "boltons"} <= corp["repos"] and corp["errors"] == []
    tasks = [{"id": "old-1", "brief": "Something unrelated about parsing dates in logs."},
             {"id": "n2", "repo": "fresh", "commit": "cdef012" + "0" * 33, "brief": "Totally different words here."},
             {"id": "n3", "brief": "Add a retry option to the download helper so transient errors get retried 3 times."},
             {"id": "n4", "repo": "otherRepo", "brief": "Write a new formatter for durations."}]
    rows = {r["id"]: r for r in R.leak_check(tasks, corp)["tasks"]}
    assert rows["old-1"]["findings"] == ["id old-1 used before"]
    assert rows["n2"]["findings"][0].startswith("commit cdef012")
    assert rows["n3"]["findings"] and rows["n3"]["listed_above_0.4"][0]["ratio"] >= R.SIMILAR
    assert rows["n4"]["findings"] == ["repository otherRepo used before"]


def test_repo_list_is_mechanical(tmp_path):
    meta = tmp_path / "meta"
    meta.mkdir()
    def info(name, url, lic):
        (meta / f"{name}.json").write_text(json.dumps({"info": {"project_urls": {"Source": url}, "license": lic,
                                                                "classifiers": []}}), encoding="utf-8")
    info("good-pkg", "https://github.com/o/good_pkg", "MIT")
    info("gpl-pkg", "https://github.com/o/gpl", "GPL-3.0")
    info("gl-pkg", "https://gitlab.com/o/x", "MIT")
    info("boltons", "https://github.com/mahmoud/boltons", "BSD")
    snap = {"last_update": "2026-11-01", "rows": [{"project": p} for p in
                                                  ("good_pkg", "gpl-pkg", "gl-pkg", "boltons", "missing")]}
    out = R.repo_list(snap, meta, {"boltons"})
    assert [(k["rank"], k["repo"], k["license"]) for k in out["kept"]] == [(1, "o/good_pkg", "mit")]
    assert [e["reason"] for e in out["excluded"]] == [
        "license not MIT/BSD/Apache-2.0/ISC/PSF", "source is not a public GitHub repository",
        "used in an earlier evaluation", "no PyPI metadata"]


def test_repo_list_skips_sponsor_links_and_lists_a_repository_once(tmp_path):
    """#397: github.com/sponsors/<user> is a funding link, not the source; packages sharing one repository keep only
    the best-ranked row."""
    meta = tmp_path / "meta"
    meta.mkdir()
    def info(name, urls):
        (meta / f"{name}.json").write_text(json.dumps({"info": {"project_urls": urls, "license": "MIT",
                                                                "classifiers": []}}), encoding="utf-8")
    info("attrs", {"Funding": "https://github.com/sponsors/hynek", "Source": "https://github.com/python-attrs/attrs"})
    info("otel-api", {"Source": "https://github.com/o/otel-python"})
    info("otel-sdk", {"Source": "https://github.com/o/otel-python.git"})
    info("only-sponsor", {"Funding": "https://github.com/sponsors/someone"})
    info("a-utils", {"Source": "https://github.com/a/utils"})
    info("b-utils", {"Source": "https://github.com/b/utils"})
    snap = {"rows": [{"project": p} for p in ("attrs", "otel-api", "otel-sdk", "only-sponsor", "a-utils", "b-utils")]}
    out = R.repo_list(snap, meta, set())
    assert [(k["project"], k["url"]) for k in out["kept"]] == [
        ("attrs", "https://github.com/python-attrs/attrs"), ("otel-api", "https://github.com/o/otel-python"),
        ("a-utils", "https://github.com/a/utils"), ("b-utils", "https://github.com/b/utils")]
    assert [(e["project"], e["reason"]) for e in out["excluded"]] == [
        ("otel-sdk", "same repository as rank 2 (otel-api)"),
        ("only-sponsor", "source is not a public GitHub repository")]


def test_select_walks_a_repeated_repository_once(monkeypatch):
    """#397: an older repos list naming one repository twice must not accept the same commit twice."""
    _dev_setup(monkeypatch, {"r1": [_row("a", 2_000_000_000, 80), _row("b", 1_999_999_999, 80)]}, 0, 0, 6, 4)
    monkeypatch.setattr(R, "B_TAKE", 5)
    out = _select(["r1", "r1"])
    assert [t["commit"][0] for t in out["B"]] == ["a", "b"]
    assert {"repo": "r1", "project": "r1", "reason": "repository listed again (walked at its first rank)"} \
        in out["exclusions"]
    # same name, different owners: two repositories, both walked
    two = R.select_upstream(Path("x"), [{"repo": "r1", "url": "https://github.com/a/r1"},
                                        {"repo": "r1", "url": "https://github.com/B/r1"}], "py", set(),
                            validator=lambda *a: {"valid": True})
    assert not [e for e in two["exclusions"] if e["reason"].startswith("repository listed again")]
    assert R.repo_key("https://github.com/A/Utils.git") == R.repo_key({"url": "https://github.com/a/utils"}) == "a/utils"


def test_same_name_different_owner_repositories_get_their_own_cache(tmp_path):
    """#400: the cache key is owner/name (case-folded, file-name safe), not the bare repository name."""
    import ext_repo as E
    import long_candidates as LC
    assert E.cache_key("A/Utils") == E.cache_key("a/utils") == "a__utils"
    assert E.cache_key("a/utils") != E.cache_key("b/utils")
    assert E.cache_key("pallets/itsdangerous") == "pallets__itsdangerous"
    assert E.cache_key("polyglot") == "polyglot"  # a frozen task's plain name keeps its folder
    assert E.cache_key("o/na:me*?") == "o__na_me__"  # characters Windows rejects
    assert E.cache_key("o/trailing.") == "o__trailing_"
    assert E.cache_path(tmp_path, "a/utils") != E.cache_path(tmp_path, "b/utils")
    # two real clones, same name, different history
    cache, src = tmp_path / "cache", tmp_path / "src"
    for owner in ("a", "b"):
        work = tmp_path / f"work-{owner}"
        work.mkdir()
        _git(work, "init", "-q", "-b", "main")
        _commit(work, {"m.py": "x = 1\n"}, "2026-01-01T00:00:00+00:00", "base")
        _commit(work, {f"{owner}_only.py": "y = 2\n"}, "2026-08-01T00:00:00+00:00", f"change by {owner}")
        src.mkdir(exist_ok=True)
        _git(tmp_path, "clone", "-q", "--bare", str(work), str(src / f"{owner}__utils.git"))
    got = {o: E.fetch(f"{o}/utils", {"url": "unused"}, cache, source=src) for o in "ab"}
    assert got["a"] != got["b"]
    assert [r["subject"] for r in LC.history(cache, "a/utils")][0] == "change by a"
    assert [r["subject"] for r in LC.history(cache, "b/utils")][0] == "change by b"
    # an old clone under the bare name is not used for an owner/name repository
    old = tmp_path / "oldcache"
    old.mkdir()
    _git(tmp_path, "clone", "-q", "--bare", str(tmp_path / "work-a"), str(old / "utils.git"))
    with pytest.raises(FileNotFoundError):
        LC.bare_path(old, "a/utils")
    with pytest.raises(FileNotFoundError):
        E.fetch("a/utils", {"url": "unused"}, tmp_path / "newcache", source=old)


def test_repo_list_gives_same_name_repositories_owner_qualified_keys(tmp_path):
    meta = tmp_path / "meta"
    meta.mkdir()
    for name, url in (("a-utils", "https://github.com/a/utils"), ("b-utils", "https://github.com/B/Utils")):
        (meta / f"{name}.json").write_text(json.dumps({"info": {"project_urls": {"Source": url}, "license": "MIT",
                                                                "classifiers": []}}), encoding="utf-8")
    out = R.repo_list({"rows": [{"project": "a-utils"}, {"project": "b-utils"}]}, meta, set())
    assert [k["repo"] for k in out["kept"]] == ["a/utils", "b/utils"]
    # an owner/name repo still counts as used by its bare name
    sel = R.select_upstream(Path("x"), [{"repo": "a/utils", "url": "https://github.com/a/utils", "project": "a-utils"}],
                            "py", {"utils"}, registered=[])  # no real --ext-python here (#424)
    assert sel["exclusions"] == [{"repo": "a/utils", "reason": "repository used in an earlier evaluation"}]


def test_own_package_check():
    def fake(version, rc=0):
        return lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout=version + "\n", stderr="")
    meta = {"releases": {"2.0": [{"upload_time_iso_8601": "2026-09-01T00:00:00.000Z"}],
                         "1.0": [{"upload_time_iso_8601": "2026-01-01T00:00:00Z"}]}}
    commit = R._since_ts("2026-08-01")
    assert R.own_package("py", "p", commit, meta, fake(""))["ok"] is True
    assert R.own_package("py", "p", commit, meta, fake("1.0"))["ok"] is True
    later = R.own_package("py", "p", commit, meta, fake("2.0"))
    assert later["ok"] is False and later["reason"] == "released at or after the commit"
    assert R.own_package("py", "p", commit, None, fake("1.0"))["reason"] == "release date unknown"
    assert R.own_package("py", "p", commit, meta, fake("", 1))["ok"] is False


def test_prepare_installs_dependencies_but_not_the_package(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(R.E, "fetch", lambda name, spec, cache: cache / name)
    def run(cmd, **kw):
        calls.append(cmd)
        if "download" in cmd:
            d = Path(cmd[cmd.index("-d") + 1])
            d.mkdir(parents=True, exist_ok=True)
            for name in ("my_pkg-2.0-py3-none-any.whl", "attrs-25.1.0-py3-none-any.whl"):
                (d / name).write_bytes(b"")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    two = [{"repo": "my-pkg", "project": "my-pkg", "url": "u"}, {"repo": "attrs", "project": "attrs", "url": "u"}]
    with pytest.raises(ValueError, match="--pypi-meta"):  # kept dependencies but no release dates to pin them
        R.prepare(two, tmp_path / "c", tmp_path / "w", "py", run)
    calls.clear()
    (tmp_path / "meta").mkdir()
    data = R.prepare(two, tmp_path / "c", tmp_path / "w", "py", run, meta_dir=tmp_path / "meta")
    rows = data["repos"]
    installs = [c for c in calls if "install" in c]
    assert installs == []  # attrs is itself a kept repository: no latest release of either; no metadata, so no pin
    assert rows[0]["skipped_kept_packages"] == ["attrs", "my-pkg"] and rows[0]["cloned"]
    assert {k: v["version"] for k, v in data["pins"].items()} == {"attrs": None, "my-pkg": None}  # each needs the other
    calls.clear()
    rows = R.prepare([{"repo": "my-pkg", "project": "my-pkg", "url": "u"}], tmp_path / "c", tmp_path / "w2", "py",
                     run)["repos"]
    install = next(c for c in calls if "install" in c)
    assert "--no-index" in install and any(a.endswith("attrs-25.1.0-py3-none-any.whl") for a in install)
    assert not any("my_pkg" in a for a in install)
    assert rows[0]["installed"]


def _rel(version, when, **extra):
    return {version: [{"upload_time_iso_8601": when, **extra}]}


def test_pinned_version_is_the_highest_final_release_before_the_date_limit():
    """#415: kept dependencies are installed at a release older than every candidate commit."""
    meta = {"releases": {**_rel("1.9", "2026-03-01T00:00:00Z"), **_rel("1.10", "2026-05-01T00:00:00Z"),
                         **_rel("1.10.post1", "2026-05-02T00:00:00Z"), **_rel("2.0rc1", "2026-06-01T00:00:00Z"),
                         **_rel("1.11", "2026-06-20T00:00:00Z", yanked=True),
                         **_rel("2.0", "2026-07-02T00:00:00Z"), "0.1": []}}
    assert R.pinned_version(meta, R._since_ts("2026-07-01")) == "1.10.post1"
    assert R.pinned_version(meta, R._since_ts("2026-01-01")) is None
    assert R.pinned_version(None, R._since_ts("2026-07-01")) is None


def test_prepare_pins_kept_dependencies_and_the_runner_before_the_date_limit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(R.E, "fetch", lambda name, spec, cache: cache / name)
    dl = {"my-pkg": ["my_pkg-2.0-py3-none-any.whl", "attrs-25.1.0-py3-none-any.whl", "other-1.0-py3-none-any.whl"],
          "attrs==24.1.0": ["attrs-24.1.0-py3-none-any.whl", "six-1.0-py3-none-any.whl", "dep-3.0-py3-none-any.whl"],
          "six==1.0": ["six-1.0-py3-none-any.whl"], "pytest==8.0": ["pytest-8.0-py3-none-any.whl"]}
    def run(cmd, **kw):
        calls.append(cmd)
        if "download" in cmd:
            d = Path(cmd[cmd.index("-d") + 1])
            d.mkdir(parents=True, exist_ok=True)
            for name in dl.get(cmd[-1].split("[")[0], []):
                (d / name).write_bytes(b"")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    meta = tmp_path / "meta"
    meta.mkdir()
    for name, rel in (("attrs", {**_rel("24.1.0", "2026-06-01T00:00:00Z"), **_rel("25.1.0", "2026-08-01T00:00:00Z")}),
                      ("six", _rel("1.0", "2020-01-01T00:00:00Z")), ("pytest", _rel("8.0", "2026-01-01T00:00:00Z")),
                      ("my-pkg", _rel("1.0", "2026-01-01T00:00:00Z"))):
        (meta / f"{name}.json").write_text(json.dumps({"releases": rel}), encoding="utf-8")
    repos = [{"repo": n, "project": n, "url": "u"} for n in ("my-pkg", "attrs", "six", "pytest")]
    data = R.prepare(repos, tmp_path / "c", tmp_path / "w", "py", run, meta_dir=meta)
    assert {k: v["version"] for k, v in data["pins"].items()} == {"attrs": "24.1.0", "pytest": "8.0", "six": "1.0"}
    installed = [Path(a).name for c in calls if "install" in c for a in c if a.endswith(".whl")]
    assert "attrs-24.1.0-py3-none-any.whl" in installed and "dep-3.0-py3-none-any.whl" in installed
    assert "attrs-25.1.0-py3-none-any.whl" not in installed      # never the latest release of a kept package
    assert not [n for n in installed if n.startswith("my_pkg")]  # nobody needs my-pkg: not installed at all
    assert installed.count("six-1.0-py3-none-any.whl") == 1      # the pin's kept dependency, pinned once


def test_failed_pin_download_is_not_reported_installed_and_pip_is_never_pinned(tmp_path, monkeypatch):
    """#442: a pin whose download produced no file of the package was reported installed (pytest missing went
    unnoticed until every baseline failed); pip itself is never reinstalled; a missing runner fails the command."""
    calls = []
    monkeypatch.setattr(R.E, "fetch", lambda name, spec, cache: cache / name)
    dl = {"my-pkg": ["my_pkg-2.0-py3-none-any.whl", "pip-26.3-py3-none-any.whl", "attrs-25.1.0-py3-none-any.whl"],
          "attrs==24.1.0": ["attrs-24.1.0-py3-none-any.whl"], "pytest==8.0": []}   # pytest's download fails

    def run(cmd, **kw):
        calls.append(cmd)
        if "download" in cmd:
            d = Path(cmd[cmd.index("-d") + 1])
            d.mkdir(parents=True, exist_ok=True)
            for name in dl.get(cmd[-1].split("[")[0], []):
                (d / name).write_bytes(b"")
            return subprocess.CompletedProcess(cmd, 0 if dl.get(cmd[-1].split("[")[0]) else 1, "", "")
        if "list" in cmd:  # pytest is even listed: only the import decides (#444 review)
            return subprocess.CompletedProcess(cmd, 0, json.dumps([{"name": "attrs", "version": "24.1.0"},
                                                                   {"name": "pytest", "version": "8.0"}]), "")
        if cmd[1:] == ["-c", "import pytest"]:
            return subprocess.CompletedProcess(cmd, 1, "", "ModuleNotFoundError: No module named 'pluggy'")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    meta = tmp_path / "meta"
    meta.mkdir()
    for name, rel in (("attrs", _rel("24.1.0", "2026-06-01T00:00:00Z")), ("pytest", _rel("8.0", "2026-01-01T00:00:00Z")),
                      ("pip", _rel("25.0", "2026-01-01T00:00:00Z"))):
        (meta / f"{name}.json").write_text(json.dumps({"releases": rel}), encoding="utf-8")
    repos = [{"repo": n, "project": n, "url": "u"} for n in ("my-pkg", "attrs", "pytest", "pip")]
    data = R.prepare(repos, tmp_path / "c", tmp_path / "w", "py", run, meta_dir=meta)
    assert data["pins"]["pytest"]["installed"] is False and "no file of pytest" in data["pins"]["pytest"]["reason"]
    assert data["pins"]["attrs"]["installed"] is True
    assert "pip" not in data["pins"]
    assert not any(Path(a).name.startswith("pip-") for c in calls if "install" in c for a in c)
    assert data["runner_missing"] == ["pytest"]
    # only other packages' files in the pin's folder (own empty, files not): still not installed
    dl["attrs==24.1.0"] = ["six-1.0-py3-none-any.whl"]
    data = R.prepare(repos, tmp_path / "c", tmp_path / "w2", "py", run, meta_dir=meta)
    assert data["pins"]["attrs"]["installed"] is False
    # a failed download over files an earlier run left: installed, with a warning
    dl["attrs==24.1.0"] = []
    (tmp_path / "w3/_pins/attrs-24.1.0").mkdir(parents=True)
    (tmp_path / "w3/_pins/attrs-24.1.0/attrs-24.1.0-py3-none-any.whl").write_bytes(b"")
    data = R.prepare(repos, tmp_path / "c", tmp_path / "w3", "py", run, meta_dir=meta)
    assert data["pins"]["attrs"]["installed"] is True and "download failed" in data["pins"]["attrs"]["warning"]
    # only pip needed and no --pypi-meta: nothing to pin, no error
    only_pip = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "[]", "")
    def pip_only(cmd, **kw):
        if "download" in cmd:
            d = Path(cmd[cmd.index("-d") + 1])
            d.mkdir(parents=True, exist_ok=True)
            (d / "pip-26.3-py3-none-any.whl").write_bytes(b"")
        return only_pip(cmd)
    assert R.prepare([{"repo": "x", "project": "x", "url": "u"}, {"repo": "pip", "project": "pip", "url": "u"}],
                     tmp_path / "c", tmp_path / "w4", "py", pip_only)["pins"] == {}
    assert R.runner_missing("no-such-python-here") == ["pytest"]
    # the import is checked as a baseline sees it: no PYTHONPATH, no user site, from an empty folder
    seen = {}
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    def spy(cmd, **kw):
        seen.update(kw, files=os.listdir(kw["cwd"]))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    assert R.runner_missing("py", spy) == []
    assert "PYTHONPATH" not in seen["env"] and seen["env"]["PYTHONNOUSERSITE"] == "1" and seen["files"] == []
    # a project whose download failed over files an earlier run left gets the same warning as a pin
    dl["my-pkg"] = []
    (tmp_path / "w5/my-pkg").mkdir(parents=True)
    (tmp_path / "w5/my-pkg/other-1.0-py3-none-any.whl").write_bytes(b"")
    rows = R.prepare(repos[:1], tmp_path / "c", tmp_path / "w5", "py", run, meta_dir=meta)["repos"]
    assert rows[0]["downloaded"] is False and "download failed" in rows[0]["warning"]
    (tmp_path / "repos.json").write_text(json.dumps({"kept": []}), encoding="utf-8")
    monkeypatch.setattr(R, "prepare", lambda *a, **k: {"repos": [], "pins": {}, "pip_list": [], "runner_missing": ["pytest"]})
    assert R.main(["prepare", "--repos-json", str(tmp_path / "repos.json"), "--ext-cache", str(tmp_path / "c"),
                   "--wheels", str(tmp_path / "w"), "--ext-python", "py", "--out", str(tmp_path / "p.json")]) == 1
    # select refuses to start when pytest does not import in --ext-python
    (tmp_path / "cache").mkdir()
    called = []
    monkeypatch.setattr(R, "select_upstream", lambda *a, **k: called.append(1))
    assert R.main(["select", "--repos-json", str(tmp_path / "repos.json"), "--ext-cache", str(tmp_path / "cache"),
                   "--ext-python", "no-such-python-here", "--out", str(tmp_path / "s.json")]) == 1
    assert called == []


def test_dependency_groups_resolve_includes_and_prepare_downloads_them(tmp_path, monkeypatch):
    config = {"dependency-groups": {"test": ["pytest>=8", {"include-group": "extra"}, "trustme"],
                                    "extra": ["hypothesis"], "docs": ["sphinx"]}}
    assert R.dependency_groups(config) == ["pytest>=8", "hypothesis", "trustme"]  # in order, includes in place
    calls = []
    monkeypatch.setattr(R.E, "fetch", lambda name, spec, cache: cache / name)
    monkeypatch.setattr(R.LCand, "bare_path", lambda cache, repo: cache / repo)
    monkeypatch.setattr(R.E, "_git", lambda *a, **k: '[dependency-groups]\ntest = ["trustme"]\n')
    run = lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    rows = R.prepare([{"repo": "anyio", "project": "anyio", "url": "u"}], tmp_path / "c", tmp_path / "w", "py", run)
    assert rows["repos"][0]["dependency_groups"] == ["trustme"] and rows["repos"][0]["groups_failed"] == []
    assert any(c[-1] == "trustme" and "download" in c for c in calls)


def test_version_stubs_from_pyproject(tmp_path):
    """#415: setuptools-scm / hatch-vcs version files missing from the parent tree become stubs."""
    assert R._version_files({"tool": {"setuptools_scm": {"write_to": "src/_pytest/_version.py"}}}) == [
        "src/_pytest/_version.py"]
    assert R._version_files({"tool": {"hatch": {"build": {"hooks": {"vcs": {"version-file": "./src/f/version.py"}},
                                                          "targets": {"wheel": {"hooks": {"vcs": {
                                                              "version-file": "src/g/_v.py"}}}}}}}}) == [
        "src/f/version.py", "src/g/_v.py"]
    work = tmp_path / "w"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _commit(work, {"pyproject.toml": '[tool.setuptools_scm]\nversion_file = "pkg/_version.py"\n'
                                     '[tool.hatch.build.hooks.vcs]\nversion-file = "pkg/tracked.py"\n',
                   "pkg/tracked.py": "x = 1\n"}, "2026-08-01T00:00:00+00:00", "p")
    sha = _commit(work, {"pkg/a.py": "a = 1\n"}, "2026-08-02T00:00:00+00:00", "c")
    cache = tmp_path / "cache"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(cache / "pkg.git"))
    assert R.version_stubs(cache, "pkg", sha) == ["pkg/_version.py"]
    assert R.version_stubs(cache, "missing", sha) == []
    repo = tmp_path / "built"
    R.LE.build(R.E.archive(cache / "pkg.git", sha + "^"), repo, ["pkg/_version.py"])
    assert (repo / "pkg/_version.py").read_text(encoding="utf-8") == R.E.VERSION_STUB
    assert "pkg/_version.py" in R.E._git(repo, "ls-files")


def test_installed_overlap_finds_a_change_already_in_the_installed_package(tmp_path):
    """#415 review: dates are not proof; a commit whose new lines the installed release already has is a leak."""
    work = tmp_path / "w"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _commit(work, {"pkg/__init__.py": "", "pkg/mod.py": "def old():\n    return 'an existing line that is long enough'\n"},
            "2026-08-01T00:00:00+00:00", "p")
    added = "    return compute_the_new_behaviour(value, strict=True)\n"
    sha = _commit(work, {"pkg/mod.py": "def old():\n    return 'an existing line that is long enough'\n"
                                       "def new(value):\n" + added + "    x = 1\n"},
                  "2026-08-02T00:00:00+00:00", "c")
    cache = tmp_path / "cache"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(cache / "pkg.git"))
    site = tmp_path / "site.py"

    def fake(body, rc=0):
        site.write_text(body, encoding="utf-8")
        return lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout=f"1.0\n{site}\n", stderr="")
    hit = R.installed_overlap("py", "pkg", cache, "pkg", sha, fake("def new(value):\n" + added))
    # short and old lines ignored; the only new line is a hit, so every new line is: a leak
    assert (hit["hits"], hit["new_lines"], hit["installed"], hit["leak"]) == (1, 1, "1.0", True)
    clean = R.installed_overlap("py", "pkg", cache, "pkg", sha, fake("return 'an existing line that is long enough'\n"))
    assert clean["hits"] == 0 and clean["leak"] is False
    absent = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr="")
    assert R.installed_overlap("py", "pkg", cache, "pkg", sha, absent) is None
    no_files = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="1.0\n", stderr="")
    assert R.installed_overlap("py", "pkg", cache, "pkg", sha, no_files)["status"] == "unknown"
    broken = lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="boom")
    assert R.installed_overlap("py", "pkg", cache, "pkg", sha, broken)["status"] == "unknown"


def test_installed_overlap_ignores_common_lines_of_a_new_file(tmp_path):
    """#415 re-review: a new file's boilerplate (found elsewhere in the parent tree) is not a new line."""
    work = tmp_path / "w"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    common = "from __future__ import annotations\nfrom typing import TYPE_CHECKING, Any, Iterable\n"
    _commit(work, {"pkg/__init__.py": "", "pkg/a.py": common + "def a():\n    return 1\n"},
            "2026-08-01T00:00:00+00:00", "p")
    one = "    return frobnicate_everything(items, depth=3)\n"
    two = "    raise ValueError(f'cannot frobnicate {items!r} at all')\n"
    sha = _commit(work, {"pkg/b.py": common + "def b(items):\n" + one + "def c(items):\n" + two},
                  "2026-08-02T00:00:00+00:00", "c")
    cache = tmp_path / "cache"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(cache / "pkg.git"))
    site = tmp_path / "site.py"

    def fake(body):
        site.write_text(body, encoding="utf-8")
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=f"1.0\n{site}\n", stderr="")
    boiler = R.installed_overlap("py", "pkg", cache, "pkg", sha, fake(common))
    assert boiler["new_lines"] == 2 and boiler["hits"] == 0 and boiler["leak"] is False
    partly = R.installed_overlap("py", "pkg", cache, "pkg", sha, fake(one))
    assert partly["hits"] == 1 and partly["leak"] is False   # one of two new lines: below LEAK_HITS, not all
    both = R.installed_overlap("py", "pkg", cache, "pkg", sha, fake(one + two))
    assert both["hits"] == 2 and both["leak"] is True and len(both["examples"]) == 2


def _vendored_case(tmp_path):
    """Repository `pkg` (distribution python-pkg, import package `pkg`) and a commit adding one long line."""
    work = tmp_path / "w"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _commit(work, {"pkg/__init__.py": "", "pkg/mod.py": "def old():\n    return 'an existing line that is long enough'\n",
                   "tests/__init__.py": "", "setup.py": "import setuptools\n"}, "2026-08-01T00:00:00+00:00", "p")
    added = "    return compute_the_new_behaviour(value, strict=True)\n"
    sha = _commit(work, {"pkg/mod.py": "def old():\n    return 'an existing line that is long enough'\n"
                                       "def new(value):\n" + added}, "2026-08-02T00:00:00+00:00", "c")
    cache = tmp_path / "cache"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(cache / "pkg.git"))
    return cache, sha, added


def _files(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
    return root


def _sites(*dirs):
    """A fake --ext-python whose own distribution is absent and whose site-packages are `dirs`."""
    out = "".join(f"S\t{d}\n" for d in dirs)
    return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr="")


def test_installed_overlap_reads_vendored_copies_of_the_task_package(tmp_path):
    """#417: pip/setuptools (and wheels embedded by virtualenv) vendor copies of kept packages under `_vendor`; the
    task's own distribution is absent, yet a vendored copy holding the commit's new line is a leak."""
    import zipfile
    cache, sha, added = _vendored_case(tmp_path)
    R.vendored_inventory.cache_clear()
    body = "def new(value):\n" + added
    # pip style: vendor.txt names the version; the folder is the import package (matched via the parent's tree)
    pip_site = _files(tmp_path / "site-417-pip", {"pip/_vendor/vendor.txt": "pkg==9.9\nother==1.0\n",
                                                  "pip/_vendor/pkg/__init__.py": "",
                                                  "pip/_vendor/pkg/mod.py": body})
    hit = R.installed_overlap("py", "python-pkg", cache, "pkg", sha, _sites(pip_site))
    assert (hit or {}).get("status") == "compared" and hit.get("leak") is True and hit["hits"] == 1
    assert hit["vendored"] == [{"where": "pip/_vendor/pkg", "version": "9.9"}]
    reason = R.overlap_reason("python-pkg", hit)
    assert "vendored" in reason and "pip/_vendor/pkg 9.9" in reason and "1 of the 1 new line" in reason
    # setuptools style: a dist-info whose top_level.txt maps the distribution to a differently named folder
    st_site = _files(tmp_path / "site-417-st", {
        "setuptools/_vendor/python_pkg-7.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: python-pkg\nVersion: 7.0\n",
        "setuptools/_vendor/python_pkg-7.0.dist-info/top_level.txt": "pkg_alias\n",
        "setuptools/_vendor/pkg_alias/__init__.py": body})
    st = R.installed_overlap("py", "python-pkg", cache, "pkg", sha, _sites(st_site))
    assert st["leak"] is True and st["vendored"] == [{"where": "setuptools/_vendor/pkg_alias", "version": "7.0"}]
    # virtualenv style: a wheel inside site-packages whose pip vendors the package; version from __version__
    whl_site = tmp_path / "site-417-whl"
    embed = whl_site / "virtualenv/seed/wheels/embed"
    embed.mkdir(parents=True)
    with zipfile.ZipFile(embed / "pip-24.0-py3-none-any.whl", "w") as z:
        z.writestr("pip/_vendor/pkg/__init__.py", "__version__ = '8.0'\n" + body)
    whl = R.installed_overlap("py", "python-pkg", cache, "pkg", sha, _sites(whl_site))
    assert whl["leak"] is True
    assert whl["vendored"] == [{"where": "virtualenv/seed/wheels/embed/pip-24.0-py3-none-any.whl!pip/_vendor/pkg",
                                "version": "8.0"}]
    # another vendored package holding the same line is not this task's copy; nothing to compare
    other = _files(tmp_path / "site-417-other", {"pip/_vendor/other/__init__.py": body})
    assert R.installed_overlap("py", "python-pkg", cache, "pkg", sha, _sites(other)) is None
    # a vendored copy without the line: compared, no leak
    clean = _files(tmp_path / "site-417-clean", {"pip/_vendor/pkg/__init__.py": "x = 1\n"})
    found = R.installed_overlap("py", "python-pkg", cache, "pkg", sha, _sites(clean))
    assert found["status"] == "compared" and found["leak"] is False and R.overlap_reason("python-pkg", found) is None
    assert found["vendored"] == [{"where": "pip/_vendor/pkg", "version": None}]


def test_env_check_lists_vendored_copies(tmp_path):
    """#417: env-check reports each vendored copy of a task's package and whether that release postdates the commit."""
    cache, sha, added = _vendored_case(tmp_path)
    R.vendored_inventory.cache_clear()
    site = _files(tmp_path / "site-417-env", {"pip/_vendor/vendor.txt": "pkg==9.9\n",
                                              "pip/_vendor/pkg/__init__.py": ""})

    def run(cmd, **kw):
        out = f"S\t{site}\n" if cmd[2] == R.SITE_DIRS else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    meta_dir = tmp_path / "meta"
    meta_dir.mkdir()
    (meta_dir / "python-pkg.json").write_text(json.dumps(
        {"releases": {"9.9": [{"upload_time_iso_8601": "2026-09-01T00:00:00Z"}]}}), encoding="utf-8")
    selection = {"B": [{"id": "r2-pkg-x", "project": "python-pkg", "repo": "pkg", "commit": sha,
                        "timestamp": 1785628800}]}  # 2026-08-02
    out = R.env_check(selection, "py", meta_dir, run, cache=cache)
    row = out["tasks"][0]
    assert row["vendored"] == [{"where": "pip/_vendor/pkg", "version": "9.9", "released": 1788220800,
                                "after_commit": True}]
    assert out["ok"] is True and "vendored" in out["rule"] and out["vendored_scan"] == "ok"
    broken = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1 if cmd[2] == R.SITE_DIRS else 0, stdout="", stderr="")
    failed = R.env_check(selection, "py", meta_dir, broken, cache=cache)
    assert failed["ok"] is False and failed["vendored_scan"].startswith("unknown")
    # one folder, two distributions (top_level.txt): the date of one is missing, so the release is unknown
    two = _files(tmp_path / "site-417-two", {
        "setuptools/_vendor/a-9.9.dist-info/METADATA": "Name: a\nVersion: 9.9\n",
        "setuptools/_vendor/a-9.9.dist-info/top_level.txt": "pkg\n",
        "setuptools/_vendor/b-2.0.dist-info/METADATA": "Name: b\nVersion: 2.0\n",
        "setuptools/_vendor/b-2.0.dist-info/top_level.txt": "pkg\n",
        "setuptools/_vendor/pkg/__init__.py": ""})
    run_two = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=f"S\t{two}\n" if cmd[2] == R.SITE_DIRS
                                                            else "", stderr="")
    row = R.env_check(selection, "py", meta_dir, run_two, cache=cache)["tasks"][0]
    assert row["vendored"] == [{"where": "setuptools/_vendor/pkg", "version": "2.0, 9.9", "released": None,
                                "after_commit": None, "release_unknown": ["2.0"]}]


def _broken_wheel(path):
    """A wheel whose deflated member is garbage: reading it raises zlib.error (or another non-OSError)."""
    import zipfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bad/__init__.py", "x = 1\n" * 2000)
    with zipfile.ZipFile(path) as z:
        info = z.infolist()[0]
    raw = bytearray(path.read_bytes())
    start = info.header_offset + 30 + len(info.filename.encode())
    raw[start:start + info.compress_size] = b"\xff" * info.compress_size
    path.write_bytes(bytes(raw))
    return path


def test_vendored_scan_survives_a_broken_wheel_and_reads_ensurepip(tmp_path, monkeypatch):
    """#422 review: a broken wheel is a scan error (cached, scanned once), never an exception that empties the
    selection or crashes env-check; ensurepip's bundled pip wheel (stdlib) is scanned too."""
    import zipfile
    cache, sha, added = _vendored_case(tmp_path)
    R.vendored_inventory.cache_clear()
    site = tmp_path / "venv-417" / "site-packages"
    _broken_wheel(site / "virtualenv/seed/wheels/embed/bad-1.0-py3-none-any.whl")
    (site / "empty-1.0-py3-none-any.whl").write_bytes(b"")  # an empty leftover file: no code, no error
    bundled = tmp_path / "py-417" / "ensurepip" / "_bundled"
    bundled.mkdir(parents=True)
    with zipfile.ZipFile(bundled / "pip-25.0-py3-none-any.whl", "w") as z:
        z.writestr("pip/_vendor/vendor.txt", "pkg==9.9\n")
        z.writestr("pip/_vendor/pkg/__init__.py", "def new(value):\n" + added)
    scanned = []
    real = R._wheel_copies
    monkeypatch.setattr(R, "_wheel_copies", lambda path, shown: scanned.append(shown) or real(path, shown))
    run = _sites(site, bundled)
    first = R.installed_overlap("py", "python-pkg", cache, "pkg", sha, run)
    assert first["leak"] is True
    assert first["vendored"] == [{"where": "ensurepip/_bundled/pip-25.0-py3-none-any.whl!pip/_vendor/pkg",
                                  "version": "9.9"}]
    assert len(first["scan_errors"]) == 1 and "bad-1.0-py3-none-any.whl" in first["scan_errors"][0]
    second = R.installed_overlap("py", "python-pkg", cache, "pkg", sha, run)
    assert second == first and len(scanned) == 3  # three wheels, each read once: errors are cached too
    # only the broken wheel: nothing to compare, the error is carried, the commit is kept
    alone = R.installed_overlap("py", "python-pkg", cache, "pkg", sha, _sites(site))
    assert alone["status"] == "absent" and alone["scan_errors"] and R.overlap_reason("python-pkg", alone) is None
    # env-check does not crash; the scan error makes it fail
    env = R.env_check({"B": [{"id": "t", "project": "python-pkg", "repo": "pkg", "commit": sha,
                              "timestamp": 1785628800}]}, "py", None,
                      lambda cmd, **kw: subprocess.CompletedProcess(
                          cmd, 0, stdout=f"S\t{site}\n" if cmd[2] == R.SITE_DIRS else "", stderr=""), cache=cache)
    assert env["ok"] is False and env["vendored_scan"].startswith("errors") and len(env["vendored_scan_errors"]) == 1


def test_vendored_copy_with_an_unreadable_file_is_unknown(tmp_path, monkeypatch):
    cache, sha, added = _vendored_case(tmp_path)
    R.vendored_inventory.cache_clear()
    site = _files(tmp_path / "site-417-unread", {"pip/_vendor/pkg/__init__.py": "", "pip/_vendor/pkg/mod.py": "x\n"})
    real = R._read_text
    monkeypatch.setattr(R, "_read_text", lambda p: None if p.name == "mod.py" else real(p))
    found = R.installed_overlap("py", "python-pkg", cache, "pkg", sha, _sites(site))
    assert found["status"] == "unknown" and "pip/_vendor/pkg" in found["error"]
    assert R.overlap_reason("python-pkg", found).startswith("cannot compare vendored copies of python-pkg")
    assert any("cannot read pkg/mod.py" in e for e in found["scan_errors"])


def test_select_records_vendored_scan_errors_without_excluding(monkeypatch):
    _dev_setup(monkeypatch, {"r1": [_row("a", 2_000_000_000, 80), _row("b", 1_999_999_999, 80)]}, 0, 0, 6, 4)
    monkeypatch.setattr(R, "B_TAKE", 2)
    out = R.select_upstream(Path("x"), [{"repo": "r1", "project": "r1"}], "py", set(),
                            validator=lambda *a: {"valid": True},
                            overlap=lambda *a: {"status": "absent", "scan_errors": ["w.whl: error: bad"]})
    assert [t["commit"][0] for t in out["B"]] == ["a", "b"] and out["vendored_scan_errors"] == ["w.whl: error: bad"]


def test_select_excludes_a_commit_the_installed_package_already_holds(monkeypatch):
    _dev_setup(monkeypatch, {"r1": [_row("a", 2_000_000_000, 80), _row("b", 1_999_999_999, 80),
                                    _row("c", 1_999_999_998, 80), _row("d", 1_999_999_997, 80)]}, 0, 0, 6, 4)
    monkeypatch.setattr(R, "B_TAKE", 5)

    def seen(py, project, cache, repo, sha):
        if sha.startswith("a"):
            return {"status": "compared", "installed": "1.0", "new_lines": 4, "hits": 2, "examples": ["x = 1"],
                    "leak": True}
        if sha.startswith("b"):
            return {"status": "unknown", "installed": "1.0", "error": "the distribution lists no .py files"}
        if sha.startswith("c"):
            raise subprocess.TimeoutExpired("py", 120)
        return {"status": "compared", "installed": "1.0", "new_lines": 4, "hits": 1, "examples": [], "leak": False}
    out = R.select_upstream(Path("x"), [{"repo": "r1", "project": "r1"}], "py", set(),
                            validator=lambda *a: {"valid": True}, overlap=seen)
    assert [t["commit"][0] for t in out["B"]] == ["d"]
    ex = {e["commit"][0]: e for e in out["exclusions"] if "commit" in e}
    assert ex["a"]["reason"] == "installed r1 1.0 already has 2 of the 4 new line(s) the commit adds"
    assert ex["a"]["examples"] == ["x = 1"] and ex["a"]["installed"] == "1.0"
    assert ex["b"]["reason"] == "cannot compare installed r1 1.0: the distribution lists no .py files"
    assert ex["c"]["reason"].startswith("cannot compare installed r1: TimeoutExpired")
    assert out["rule"]["installed_overlap"] == R.OVERLAP_RULE and str(R.LEAK_LINE) in R.OVERLAP_RULE


def test_install_retries_each_file_and_prepare_freezes_pip_list(tmp_path, monkeypatch):
    def run(cmd, **kw):
        if "list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps([{"name": "B", "version": "2"},
                                                                   {"name": "a", "version": "1"}]), "")
        bad = any(str(x).endswith("bad.tar.gz") for x in cmd)
        return subprocess.CompletedProcess(cmd, 1 if bad else 0, "", "")
    failed = []
    assert R._install(run, "py", ["ok-1.whl", "bad.tar.gz", "ok2-1.whl"], failed) is False
    assert failed == ["bad.tar.gz"]
    monkeypatch.setattr(R.E, "fetch", lambda name, spec, cache: cache / name)
    data = R.prepare([], tmp_path / "c", tmp_path / "w", "py", run)
    assert data["pip_list"] == [{"name": "a", "version": "1"}, {"name": "B", "version": "2"}]
    (tmp_path / "repos.json").write_text(json.dumps({"kept": []}), encoding="utf-8")
    monkeypatch.setattr(R, "prepare", lambda *a, **k: {"repos": [], "pins": {}, "pip_list": None})
    assert R.main(["prepare", "--repos-json", str(tmp_path / "repos.json"), "--ext-cache", str(tmp_path / "c"),
                   "--wheels", str(tmp_path / "w"), "--ext-python", "py", "--out", str(tmp_path / "p.json")]) == 1


def test_version_files_stay_inside_the_tree():
    scm = lambda p: {"tool": {"setuptools_scm": {"version_file": p}}}
    assert R._version_files(scm("/abs/v.py")) == [] and R._version_files(scm("../out/v.py")) == []
    assert R._version_files(scm("C:/v.py")) == [] and R._version_files(scm("a/../../v.py")) == []


def test_authored_check_runs_with_utf8(tmp_path):
    root = tmp_path / "t"
    for part in ("start", "reference"):
        (root / part).mkdir(parents=True)
    (root / "hidden").mkdir()
    (root / "hidden/test_h.py").write_text("def test_h():\n    assert 1\n", encoding="utf-8")
    (root / "task.json").write_text(json.dumps({"id": "x", "brief": "b", "hidden_tests": ["test_h.py"]}), encoding="utf-8")
    seen = []
    run = lambda tree, tests, python: seen.append(R.LE.environment(tree, sys.executable, tree / "t").get("PYTHONUTF8")) \
        or {"rc": 0}
    out = R.check_authored(root, "py", run)
    assert seen == ["1", "1", "1", "1"] and out["pythonutf8"] is True and R.LE.UTF8_MODE is False


def test_select_records_stubs_and_utf8(monkeypatch):
    _dev_setup(monkeypatch, {"r1": [_row("a", 2_000_000_000, 80)]}, 0, 0, 6, 4)
    monkeypatch.setattr(R, "version_stubs", lambda cache, repo, sha: ["src/r1/_version.py"])
    seen = []
    out = R.select_upstream(Path("x"), [{"repo": "r1"}], "py", set(),
                            validator=lambda c, p, task, r: seen.append(dict(task)) or {"valid": True})
    assert seen[0]["stubs"] == ["src/r1/_version.py"] and seen[0]["pythonutf8"] is True
    assert out["B"][0]["stubs"] == ["src/r1/_version.py"] and out["B"][0]["pythonutf8"] is True


def test_suite_time_limit_is_a_repository_condition(monkeypatch):
    """#424: after the first candidate whose parent's suite times out, the repository's other candidates are excluded
    without running pytest again; a task taken before stays; other repositories are unaffected."""
    t = 2_000_000_000
    hist = {"r1": [_row("a", t, 80), _row("b", t - 1, 80), _row("c", t - 2, 80), _row("d", t - 3, 80)],
            "r2": [_row("e", t, 80)]}
    # set up by hand (not _dev_setup), so on code without #424 this fails on behaviour, not on a missing name
    for name, value in (("B_TAKE", 10), ("C_TAKE", 0), ("B_DEV_TAKE", 0), ("C_DEV_TAKE", 0)):
        monkeypatch.setattr(R, name, value)
    monkeypatch.setattr(R, "compiled_files", lambda cache, repo: [])
    monkeypatch.setattr(R, "test_changes", lambda cache, repo, sha: None)
    monkeypatch.setattr(R, "src_layout", lambda cache, repo, sha: False)
    monkeypatch.setattr(R, "installed_overlap", lambda *a, **k: None)
    monkeypatch.setattr(R, "ext_plugins", lambda python: [], raising=False)
    monkeypatch.setattr(R.LCand, "history", lambda cache, repo: hist[repo])
    ran = []

    def validator(cache, python, task, raw):
        ran.append(task["commit"][0])
        if task["commit"][0] == "b":
            return {"valid": False, "baseline": {"rc": None, "summary": "baseline timeout"},
                    "parent": {"rc": None}, "reference": {"rc": None}}
        return {"valid": True, "baseline": {"rc": 0}}
    out = R.select_upstream(Path("x"), [{"repo": "r1"}, {"repo": "r2"}], "py", set(), validator=validator)
    assert ran == ["a", "b", "e"]
    assert [t["commit"][0] for t in out["B"]] == ["a", "e"]
    reasons = {e["commit"][0]: e["reason"] for e in out["exclusions"] if "commit" in e}
    assert reasons["c"].startswith("repository's pytest suite does not run offline within 10 minutes")
    assert "bbbbbbbbbbbb" in reasons["d"]
    assert out["repositories_over_time_limit"] == {"r1": "b" * 40}


def test_declared_requirements_and_plugins(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _commit(work, {
        "pyproject.toml": '[project]\nname = "pkg"\ndependencies = ["anyio>=4", "idna"]\n'
                          '[project.optional-dependencies]\ntest = ["pytest-timeout>=2", "pkg[cov]"]\n'
                          'docs = ["sphinx"]\ncov = ["pytest-cov", "pkg[extra2]"]\nextra2 = ["pytest-randomly"]\n'
                          'viaeditable = ["pytest-env"]\n'
                          '[dependency-groups]\ndev = ["pytest_mock", {include-group = "lint"}]\nlint = ["ruff"]\n'
                          '[project.entry-points.pytest11]\npkg = "pkg.plugin:Plugin"\n',
        "setup.cfg": "[options]\ninstall_requires =\n    attrs\n[options.extras_require]\ntesting =\n    trustme\n"
                     "[options.entry_points]\npytest11 =\n    other = pkg.other_plugin\n",
        "requirements/tests.txt": "# comment\n-r base.txt\nhypothesis==6\n",
        "dev-requirements.txt": "pytest-xdist\n-e .[viaeditable]\n", "pkg/__init__.py": ""},
            "2026-08-01T00:00:00+00:00", "p")
    sha = _commit(work, {"pkg/a.py": "a = 1\n"}, "2026-08-02T00:00:00+00:00", "c")
    cache = tmp_path / "cache"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(cache / "pkg.git"))
    d = R.declared(cache, "pkg", sha)
    # docs extra not read; cov and extra2 (asked by pkg[cov] -> pkg[extra2]) and viaeditable (-e .[viaeditable]) are
    assert d["requirements"] == ["anyio", "attrs", "hypothesis", "idna", "pkg", "pytest-cov", "pytest-env",
                                 "pytest-mock", "pytest-randomly", "pytest-timeout", "pytest-xdist", "ruff", "trustme"]
    assert d["own_plugins"] == ["pkg.other_plugin", "pkg.plugin"]
    registered = [("anyio", "anyio.pytest_plugin"), ("pytest-timeout", "pytest_timeout"), ("pytest-randomly",
                  "pytest_randomly"), ("pkg", "pkg.plugin"), ("pytest-sugar", "pytest_sugar"),
                  ("pytest-cov", "pytest_cov.plugin"), ("pytest-env", "pytest_env.plugin")]
    # pytest-randomly is declared but on the deny list; pytest-sugar is installed but not declared
    assert R.pytest_plugins(d, registered, "pkg") == ["anyio.pytest_plugin", "pkg.other_plugin", "pkg.plugin",
                                                      "pytest_cov.plugin", "pytest_env.plugin", "pytest_timeout"]
    assert R.declared(cache, "missing", sha) == {"requirements": [], "own_plugins": []}


def test_ext_plugins_and_stub_version(tmp_path):
    fake = lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps([["Pytest_Timeout", "pytest_timeout"],
                                                                        ["anyio", "anyio.pytest_plugin:Plugin"]]), "")
    assert R.ext_plugins("py", fake) == [("pytest-timeout", "pytest_timeout"), ("anyio", "anyio.pytest_plugin")]
    with pytest.raises(RuntimeError):
        R.ext_plugins("py", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom"))
    work = tmp_path / "w"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    first = _commit(work, {"a.py": "a = 1\n"}, "2026-08-01T00:00:00+00:00", "p")
    second = _commit(work, {"b.py": "b = 1\n"}, "2026-08-02T00:00:00+00:00", "q")
    _git(work, "tag", "v8.4.1", first)
    third = _commit(work, {"c.py": "c = 1\n"}, "2026-08-03T00:00:00+00:00", "r")
    cache = tmp_path / "cache"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(cache / "pkg.git"))
    assert R.stub_version(cache, "pkg", third) == "8.4.1" and R.stub_version(cache, "pkg", second) == "8.4.1"
    assert R.stub_version(cache, "missing", third) == "0.0"           # no clone
    bare = tmp_path / "w2"
    bare.mkdir()
    _git(bare, "init", "-q", "-b", "main")
    _commit(bare, {"a.py": "a = 1\n"}, "2026-08-01T00:00:00+00:00", "p")
    later = _commit(bare, {"b.py": "b = 1\n"}, "2026-08-02T00:00:00+00:00", "q")
    _git(tmp_path, "clone", "-q", "--bare", str(bare), str(cache / "untagged.git"))
    assert R.stub_version(cache, "untagged", later) == "0.0"           # no tag
    _git(bare, "tag", "stable", later + "^")
    _git(bare, "tag", "py3.8-compat", later + "^")
    _git(bare, "tag", "otherpkg-1.2.3", later + "^")
    _git(tmp_path, "clone", "-q", "--bare", str(bare), str(cache / "oddtag.git"))
    assert R.stub_version(cache, "oddtag", later) == "0.0"             # no tag starting with a version
    assert R.E.version_stub("8.4.1") == '__version__ = version = "8.4.1"\n__version_tuple__ = version_tuple = (8, 4, 1,)\n'
    assert R.E.version_stub(None) == R.E.VERSION_STUB


def test_select_records_plugins_and_stub_version(monkeypatch, tmp_path):
    _dev_setup(monkeypatch, {"r1": [_row("a", 2_000_000_000, 80)]}, 0, 0, 6, 4)
    monkeypatch.setattr(R, "version_stubs", lambda cache, repo, sha: ["src/r1/_version.py"])
    monkeypatch.setattr(R, "stub_version", lambda cache, repo, sha: "3.2.1")
    monkeypatch.setattr(R, "declared", lambda cache, repo, sha: {"requirements": ["anyio"], "own_plugins": []})
    seen = []
    out = R.select_upstream(Path("x"), [{"repo": "r1"}], "py", set(), registered=[("anyio", "anyio.pytest_plugin")],
                            validator=lambda c, p, task, r: seen.append(dict(task)) or {"valid": True})
    assert seen[0]["pytest_plugins"] == ["anyio.pytest_plugin"] and seen[0]["stub_version"] == "3.2.1"
    assert out["B"][0]["pytest_plugins"] == ["anyio.pytest_plugin"]
    assert out["pytest_plugins_loaded"] == {"by_task": {out["B"][0]["id"]: ["anyio.pytest_plugin"]},
                                            "counts": {"anyio.pytest_plugin": 1}}
    env = R.LE.environment(tmp_path, sys.executable, tmp_path / "t", plugins=["a.b", "c"])
    assert env["PYTEST_PLUGINS"] == "a.b,c" and env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    monkeypatch.setenv("PYTEST_PLUGINS", "inherited")
    assert "PYTEST_PLUGINS" not in R.LE.environment(tmp_path, sys.executable, tmp_path / "t")


def test_validate_task_passes_plugins_and_stub_version(monkeypatch, tmp_path):
    """#424 review: validation builds every tree with the task's stub version and runs every pytest with its plugins."""
    calls = {"build": [], "baseline": [], "hidden": []}
    monkeypatch.setattr(R.LE.LC, "material", lambda cache, task: {"tar": b"", "reference": b"", "tests": {}})
    def build(tree, repo, stubs=(), stub_version=None):
        Path(repo).mkdir(parents=True, exist_ok=True)
        calls["build"].append((tuple(stubs), stub_version))
    monkeypatch.setattr(R.LE, "build", build)
    monkeypatch.setattr(R.LE, "checkout", lambda repo: {})
    monkeypatch.setattr(R.LE.E, "_git", lambda *a, **k: "")
    monkeypatch.setattr(R.LE, "baseline", lambda *a, **k: calls["baseline"].append(a[-1]) or {"rc": 0})
    monkeypatch.setattr(R.LE, "hidden", lambda *a, **k: calls["hidden"].append(k.get("plugins")) or {"rc": 1})
    task = {"commit": "c" * 40, "tests": [], "stubs": ["v.py"], "stub_version": "2.1", "pytest_plugins": ["p1"]}
    R.LE.validate_task(Path("x"), "py", task)
    assert calls["build"] == [(("v.py",), "2.1")] * 3
    assert calls["baseline"] == [["p1"]] and calls["hidden"] == [["p1"], ["p1"]]


def test_utf8_mode_for_round2_validation_and_tasks(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    assert "PYTHONUTF8" not in R.LE.environment(tmp_path, sys.executable, tmp_path / "t")
    assert R.LE.environment(tmp_path, sys.executable, tmp_path / "t", utf8=True)["PYTHONUTF8"] == "1"
    seen = {}
    monkeypatch.setattr(R.LE, "validate_task", lambda *a: seen.setdefault(
        "env", R.LE.environment(tmp_path, sys.executable, tmp_path / "t")))
    R._validate(Path("c"), "py", {"commit": "x"}, None)
    assert seen["env"]["PYTHONUTF8"] == "1" and R.LE.UTF8_MODE is False


def test_src_layout_only_for_round2_validation(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    assert R.LE.environment(tmp_path, sys.executable, tmp_path / "t")["PYTHONPATH"] == str(tmp_path)
    seen = {}
    monkeypatch.setattr(R.LE, "validate_task", lambda *a: seen.setdefault(
        "path", R.LE.environment(tmp_path, sys.executable, tmp_path / "t")["PYTHONPATH"]))
    R._validate(tmp_path, sys.executable, {}, None)
    assert seen["path"].split(os.pathsep) == [str(tmp_path / "src"), str(tmp_path)]
    assert R.LE.SRC_ON_PATH is False


def test_manifest_hash_is_stable(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/x.py").write_bytes(b"one\r\ntwo\r\n")
    (tmp_path / "b.json").write_bytes(b"{}\n")
    first = R.manifest([tmp_path / "b.json", tmp_path / "a"], tmp_path)
    (tmp_path / "a/x.py").write_bytes(b"one\ntwo\n")
    second = R.manifest([tmp_path / "a", tmp_path / "b.json"], tmp_path)
    assert first == second and [f["path"] for f in first["files"]] == ["a/x.py", "b.json"]
    (tmp_path / "b.json").write_bytes(b"{ }\n")
    assert R.manifest([tmp_path / "a", tmp_path / "b.json"], tmp_path)["sha256"] != first["sha256"]


def test_cli_manifest_and_leak(tmp_path, capsys):
    (tmp_path / "t.json").write_text(json.dumps({"tasks": [{"id": "r2-new-task", "brief": "Brand new words only."}]}),
                                     encoding="utf-8")
    assert R.main(["manifest", str(tmp_path / "t.json"), "--root", str(tmp_path), "--out", str(tmp_path / "m.json")]) == 0
    assert json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["files"][0]["path"] == "t.json"
    assert R.main(["leak", "--tasks", str(tmp_path / "t.json"), "--out", str(tmp_path / "leak.json")]) == 0
    assert json.loads((tmp_path / "leak.json").read_text(encoding="utf-8"))["clean"] is True


def test_real_corpus_reads_every_file_without_errors():
    corp = R.corpus()
    assert corp["errors"] == []
    assert {"more-itertools", "boltons", "pluggy", "humanize", "itsdangerous"} <= corp["repos"]
    assert len(corp["briefs"]) > 50


def test_cache_key_rejects_malformed_repositories_and_keeps_distinct_keys(tmp_path):
    """#400 review: a bad `owner/name` never becomes an absolute or nested path, and the keys `repo_list` writes for
    different repositories differ (they would only collide for an owner containing `__`, which GitHub forbids)."""
    import ext_repo as E
    for bad in ("/utils", "a/", "host/o/n", "a//b", "/"):
        with pytest.raises(ValueError):
            E.cache_key(bad)
    assert E.repo_name("mahmoud/Boltons.git") == E.repo_name("boltons") == "boltons"
    meta = tmp_path / "meta"
    meta.mkdir()
    urls = {"p1": "https://github.com/a/b__c", "p2": "https://github.com/a-b/c", "p3": "https://github.com/a/b",
            "p4": "https://github.com/B/Utils", "p5": "https://github.com/b/utils-x", "p6": "https://github.com/a/utils"}
    for name, url in urls.items():
        (meta / f"{name}.json").write_text(json.dumps({"info": {"project_urls": {"Source": url}, "license": "MIT",
                                                                "classifiers": []}}), encoding="utf-8")
    out = R.repo_list({"rows": [{"project": p} for p in urls]}, meta, set())
    keys = [E.cache_key(k["repo"]) for k in out["kept"]]
    assert len(keys) == len(urls) and len(set(keys)) == len(keys)
    with pytest.raises(FileNotFoundError, match="prepared again"):
        E.fetch("a/utils", {"url": "unused"}, tmp_path / "c", source=tmp_path / "empty")
