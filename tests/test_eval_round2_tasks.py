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
    # env-check covers the development tasks too
    seen = []
    monkeypatch.setattr(R, "own_package", lambda py, project, ts, meta, run: seen.append(project) or {"ok": True})
    for task in data["dev"]["B"]:
        task["project"] = "devpkg"
    assert R.env_check(data, "py", None)["ok"] and "devpkg" in seen
    # leak reads B, C and the development tasks from a selection file
    leaked = []
    monkeypatch.setattr(R, "leak_check", lambda tasks, corp: leaked.extend(tasks) or {"clean": True})
    assert R.main(["leak", "--tasks", str(out), "--out", str(tmp_path / "leak.json")]) == 0
    assert sorted(t["commit"][0] for t in leaked) == ["a", "c", "d"]
    # a final-task shortfall still fails the command
    monkeypatch.setattr(R, "C_TAKE", 5)
    assert R.main(["select", "--repos-json", str(tmp_path / "repos.json"), "--ext-cache", str(tmp_path / "cache"),
                   "--ext-python", "py", "--out", str(out)]) == 1


def test_compiled_repository_is_excluded(monkeypatch):
    monkeypatch.setattr(R.LCand, "history", lambda cache, repo: [])
    monkeypatch.setattr(R, "compiled_files", lambda cache, repo: ["src/speed.c"])
    out = R.select_upstream(Path("x"), [{"repo": "r"}], "py", set())
    assert out["exclusions"] == [{"repo": "r", "reason": "not pure Python: src/speed.c"}]


def _authored(root, reference_mul="a * b"):
    (root / "start/tests").mkdir(parents=True)
    (root / "start/calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "start/tests/test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
                                                   encoding="utf-8")
    (root / "reference").mkdir()
    import shutil
    shutil.copytree(root / "start/tests", root / "reference/tests")
    (root / "reference/calc.py").write_text(f"def add(a, b):\n    return a + b\n\ndef mul(a, b):\n    return {reference_mul}\n",
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
    assert [(k["rank"], k["repo"], k["license"]) for k in out["kept"]] == [(1, "good-pkg", "mit")]
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
    data = R.prepare([{"repo": "my-pkg", "project": "my-pkg", "url": "u"}, {"repo": "attrs", "project": "attrs", "url": "u"}],
                     tmp_path / "c", tmp_path / "w", "py", run)
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


def test_select_records_stubs_and_utf8(monkeypatch):
    _dev_setup(monkeypatch, {"r1": [_row("a", 2_000_000_000, 80)]}, 0, 0, 6, 4)
    monkeypatch.setattr(R, "version_stubs", lambda cache, repo, sha: ["src/r1/_version.py"])
    seen = []
    out = R.select_upstream(Path("x"), [{"repo": "r1"}], "py", set(),
                            validator=lambda c, p, task, r: seen.append(dict(task)) or {"valid": True})
    assert seen[0]["stubs"] == ["src/r1/_version.py"] and seen[0]["pythonutf8"] is True
    assert out["B"][0]["stubs"] == ["src/r1/_version.py"] and out["B"][0]["pythonutf8"] is True


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
