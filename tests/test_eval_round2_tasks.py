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
    c1 = _commit(work, {"pkg/new.py": _bulk(31, "n") + "def new():\n    return 7\n",
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
    cache = root / "cache"
    cache.mkdir()
    _git(root, "clone", "-q", "--bare", str(work), str(cache / "fakepkg.git"))
    return {"cache": cache, "c0": c0, "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5}


def test_upstream_selection_on_fake_repository(fake_cache, tmp_path):
    repos = [{"repo": "boltons", "project": "boltons"}, {"repo": "fakepkg", "project": "fakepkg"}]
    out = R.select_upstream(fake_cache["cache"], repos, sys.executable, used={"boltons"})
    reasons = {e.get("commit") or e["repo"]: e["reason"] for e in out["exclusions"]}
    assert [t["commit"] for t in out["B"]] == [fake_cache["c1"]]
    assert "existing suite does not pass on parent" in reasons[fake_cache["c4"]]
    assert "no hidden test fails on parent" in reasons[fake_cache["c2"]]
    assert reasons[fake_cache["c3"]] == "no test file added or changed"
    assert reasons[fake_cache["c5"]] == "changes test support files: tests/conftest.py"
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
    assert out["c_shortfall"] == 0 and "e" not in reasons  # stops once both groups are full


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
    rows = R.prepare([{"repo": "my-pkg", "project": "my-pkg", "url": "u"}, {"repo": "attrs", "project": "attrs", "url": "u"}],
                     tmp_path / "c", tmp_path / "w", "py", run)
    installs = [c for c in calls if "install" in c]
    assert installs == []  # attrs is itself a kept repository: neither package is installed for any task
    assert rows[0]["skipped_kept_packages"] == ["attrs", "my-pkg"] and rows[0]["cloned"]
    calls.clear()
    rows = R.prepare([{"repo": "my-pkg", "project": "my-pkg", "url": "u"}], tmp_path / "c", tmp_path / "w2", "py", run)
    install = next(c for c in calls if "install" in c)
    assert "--no-index" in install and any(a.endswith("attrs-25.1.0-py3-none-any.whl") for a in install)
    assert not any("my_pkg" in a for a in install)
    assert rows[0]["installed"]


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
