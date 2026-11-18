"""Round 2 B authored tasks (#375): build their git repositories deterministically, and check them.

Each library is a folder here: `<lib>/base/` is the starting tree (package + its own tests); each task is
`<lib>/tasks/<task id>/` with `task.json` ({id, dev, subject, brief, hidden_tests, trace_by_test}), `reference/`
(files the reference change adds or replaces, relative to the repository root) and `hidden/` (the hidden test files).

    build  --ext-cache DIR --tasks-out FILE   one bare repository per library, `round2-authored/<lib>`, cached as
                                              `round2-authored__<lib>.git`: commit 1 is the base tree, every task is
                                              one commit on top of it (base + reference + hidden tests), kept on the
                                              branch task/<id>; fixed author, committer and dates, text normalized to
                                              LF, so every SHA is the same on every machine. Writes the task entries
                                              p4_long_session reads ({"accepted": [...]}, plus "dev").
    check  --out FILE [--python PY]           exports every task in the layout `round2_tasks.py authored` checks
                                              (start/, reference/, hidden/, task.json with the per-assertion trace)
                                              and runs that check: hidden tests fail on start and pass on the
                                              reference, the start suite passes, the trace is complete.

No model is called. The libraries are standard-library only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import round2_tasks as R  # noqa: E402
import long_candidates as LCand  # noqa: E402
import ext_repo as E  # noqa: E402

OWNER = "round2-authored"
AUTHOR = ("round2 authored tasks", "authored@example.invalid")
BASE_DATE = "2026-11-18T00:00:00+00:00"
EPOCH = 1794960000  # BASE_DATE as a timestamp; task n is committed n minutes later


def libraries() -> list[str]:
    return sorted(p.parent.name for p in HERE.glob("*/base") if p.is_dir())


def read_tree(root: Path) -> dict[str, bytes]:
    """Files under `root` as {posix path: bytes}, text normalized to LF (a Windows checkout may hold CRLF)."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            data = p.read_bytes()
            out[p.relative_to(root).as_posix()] = data.replace(b"\r\n", b"\n") if b"\0" not in data else data
    return out


def tasks_of(lib: str) -> list[dict]:
    rows = []
    for d in sorted((HERE / lib / "tasks").glob("*/task.json")):
        task = json.loads(d.read_text(encoding="utf-8"))
        task["_dir"] = d.parent
        rows.append(task)
    # development tasks first (pre-registration: written and frozen before any final authored task), then by id
    return sorted(rows, key=lambda t: (not t.get("dev"), t["id"]))


def _write(root: Path, files: dict[str, bytes]) -> None:
    for rel, body in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def _git(cwd: Path, *args: str, when: int | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": AUTHOR[0], "GIT_AUTHOR_EMAIL": AUTHOR[1],
           "GIT_COMMITTER_NAME": AUTHOR[0], "GIT_COMMITTER_EMAIL": AUTHOR[1]}
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    r = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main",
                        *args], cwd=cwd, env=env, capture_output=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {r.stderr.decode('utf-8', 'replace')[:300]}")
    return r.stdout.decode("utf-8", "replace").strip()


def build_library(lib: str, cache: Path) -> list[dict]:
    """The library's bare repository in `cache`; returns one task entry per task (P4 fields)."""
    repo_name = f"{OWNER}/{lib}"
    base = read_tree(HERE / lib / "base")
    entries = []
    with tempfile.TemporaryDirectory(prefix=f"r2bc-{lib}-") as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        _git(work, "init", "-q")
        _write(work, base)
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", f"{lib}: starting tree", when=EPOCH)
        base_sha = _git(work, "rev-parse", "HEAD")
        _git(work, "branch", "-q", "base")
        for n, task in enumerate(tasks_of(lib), 1):
            _git(work, "checkout", "-q", "--detach", base_sha)  # the previous task's files were all committed
            reference = read_tree(task["_dir"] / "reference")
            hidden = read_tree(task["_dir"] / "hidden")
            if set(hidden) != set(task["hidden_tests"]):
                raise ValueError(f"{task['id']}: hidden/ holds {sorted(hidden)}, task.json names {task['hidden_tests']}")
            _write(work, {**reference, **hidden})
            _git(work, "add", "-A")
            _git(work, "commit", "-q", "-m", task["subject"], when=EPOCH + 60 * n)
            sha = _git(work, "rev-parse", "HEAD")
            _git(work, "branch", "-q", f"task/{task['id']}", sha)
            numstat = _git(work, "diff", "--numstat", base_sha, sha)
            code, lines = [], 0
            for row in numstat.splitlines():
                add, rem, name = row.split("\t", 2)
                if LCand.is_code(name):
                    code.append(name)
                    lines += int(add) + int(rem)
            entries.append({"id": task["id"], "repo": repo_name, "project": lib, "url": None, "commit": sha,
                            "timestamp": EPOCH + 60 * n, "subject": task["subject"], "brief": task["brief"],
                            "tests": list(task["hidden_tests"]), "code": sorted(code), "code_lines": lines,
                            "group": "B", "source": "authored", "src_layout": False, "stubs": [],
                            "pythonutf8": True, "pytest_plugins": [], **({"dev": True} if task.get("dev") else {})})
        dest = E.cache_path(cache, repo_name)
        if dest.exists():
            shutil.rmtree(dest, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        cache.mkdir(parents=True, exist_ok=True)
        _git(Path(tmp), "clone", "-q", "--bare", str(work), str(dest))
    return entries


def trace_rows(task: dict, hidden: dict[str, bytes]) -> list[dict]:
    """task.json's trace_by_test as one row per assertion of the hidden tests. A value is either one brief sentence
    for every check of that test, or a list with one sentence per check, in source order."""
    rows, by_test = [], task.get("trace_by_test") or {}
    for rel, body in sorted(hidden.items()):
        for check in R.assertions(rel, body.decode("utf-8")):
            qual, k = check["id"].split("::", 1)[1].rsplit("#", 1)
            value = by_test.get(qual)
            if isinstance(value, list):
                value = value[int(k) - 1] if int(k) <= len(value) else None
            if value:
                rows.append({"assertion": check["id"], "brief": value})
    return rows


def export_authored(lib: str, task: dict, dest: Path) -> Path:
    """`dest` in the layout round2_tasks.check_authored reads."""
    base = read_tree(HERE / lib / "base")
    reference = read_tree(task["_dir"] / "reference")
    hidden = read_tree(task["_dir"] / "hidden")
    _write(dest / "start", base)
    _write(dest / "reference", {**base, **reference})
    _write(dest / "hidden", hidden)
    (dest / "task.json").write_text(json.dumps({"id": task["id"], "brief": task["brief"],
                                                "hidden_tests": task["hidden_tests"],
                                                "trace": trace_rows(task, hidden)}, indent=1),
                                    encoding="utf-8", newline="")
    return dest


def check_all(python: str) -> dict:
    rows = []
    with tempfile.TemporaryDirectory(prefix="r2bc-check-") as tmp:
        for lib in libraries():
            for task in tasks_of(lib):
                d = export_authored(lib, task, Path(tmp) / task["id"])
                result = R.check_authored(d, python)
                result["lib"], result["dev"] = lib, bool(task.get("dev"))
                rows.append(result)
    return {"models_called": False, "tasks": rows, "valid": all(r["valid"] for r in rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build")
    s.add_argument("--ext-cache", type=Path, required=True)
    s.add_argument("--tasks-out", type=Path, required=True)
    s = sub.add_parser("check")
    s.add_argument("--python", default=sys.executable)
    s.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        entries = [e for lib in libraries() for e in build_library(lib, a.ext_cache)]
        data = {"about": "Round 2 B authored tasks (#375), built by scripts/eval/round2_bc/build.py",
                "accepted": [e for e in entries if not e.get("dev")], "dev": [e for e in entries if e.get("dev")]}
        R.write_json(a.tasks_out, data)
        print(f"built {len(libraries())} repositories, {len(data['accepted'])} final and {len(data['dev'])} "
              "development tasks")
        return 0
    data = check_all(a.python)
    R.write_json(a.out, data)
    for r in data["tasks"]:
        print(f"{'OK ' if r['valid'] else 'BAD'} {r['id']}: {'; '.join(r['problems']) or 'valid'}"
              + (f" | review: {len(r['review'])} literal(s)" if r["review"] else ""))
    return 0 if data["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
