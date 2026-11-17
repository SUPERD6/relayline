"""Round 2 task tools (#348): new tasks only, frozen before any run; never calls a model.

The rules come from docs/research/prereg/2026-11-16-round2.md, section 2, and are fixed here before running.

    meta      fetch PyPI JSON for the top-pypi snapshot rows                  (network: pypi.org only)
    repos     mechanical repository list from the snapshot + that metadata    (offline)
    prepare   clone kept repositories into --ext-cache, download wheels, install dependencies (not the package
              itself) into --ext-python                                       (network: GitHub, PyPI)
    select    upstream commits for B (first 60) and C (next 24), then in the same order the development tasks
              (B: next 4, C: next 2; #371), every exclusion with its reason (offline)
    authored  validate authored tasks: hidden fails on start, passes on reference, existing suite passes
    brief     brief checks only: literal overlap with hidden asserts, trace table coverage
    leak      task ids, repository + commit and normalized briefs against every earlier task
    env-check --ext-python has no task's own package released at or after the task's commit; lists vendored
              copies of each task's package (#417)
    manifest  SHA-256 of every file (text normalized to LF), for the pre-registration change log

Reused: long_candidates.history (commit scan, code/test split), long_environment.validate_task (native checkout,
parent full suite, hidden tests on parent and commit), long_environment.hidden (pytest run), ext_repo.fetch.
"""
from __future__ import annotations

import argparse
import ast
import calendar
import difflib
import functools
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import ext_repo as E
import long_candidates as LCand
import long_environment as LE

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parents[1]
SINCE = "2026-07-01"
B_SIZE, C_SIZE = (60, 3), (150, 5)  # implementation lines OR code files
B_TAKE, C_TAKE, B_CAP, C_CAP = 60, 24, 6, 4
B_DEV_TAKE, C_DEV_TAKE = 4, 2  # development tasks, after C's final tasks in the same order (#371)
SUITE_TIMEOUT = 600
ALWAYS_USED = ("more-itertools", "boltons")
LICENSES = (("mit",), ("bsd",), ("apache",), ("isc",), ("psf", "python software foundation"))
COMPILED = (".c", ".cc", ".cpp", ".cxx", ".pyx", ".pxd", ".rs", ".f", ".f90", ".go", ".zig")
SIMILAR, LISTED = 0.6, 0.4
TEST_EXTRAS = ("test", "tests", "testing")
# task text: `brief` always; the other keys only when long enough to be a task statement, not an id
BRIEF_KEYS = ("brief", "prompt", "task", "instruction", "instructions")


def norm_name(name: str) -> str:
    """PEP 503 style, also for repository names and URLs (last path part, no .git)."""
    name = str(name).strip().rstrip("/").split("/")[-1]
    name = name[:-4] if name.lower().endswith(".git") else name
    return re.sub(r"[-_.]+", "-", name).lower()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- earlier tasks (corpus)

def corpus_files(root: Path = ROOT, exclude=()) -> list[Path]:
    skip = {Path(p).resolve() for p in exclude}
    files = sorted((root / "scripts/eval").glob("*.py")) + sorted((root / "scripts/eval").glob("*.json"))
    data = root / "docs/research/data"
    files += sorted(p for p in data.rglob("*") if p.is_file()) if data.is_dir() else []
    return [p for p in files if p.resolve() not in skip]


def _records(obj, out: list) -> None:
    if isinstance(obj, dict):
        if any(k in obj for k in ("id", "commit", "repo", "url", *BRIEF_KEYS)):
            out.append(obj)
        for v in obj.values():
            _records(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _records(v, out)


def _ast_dicts(tree) -> list[dict]:
    rows = []
    for n in ast.walk(tree):
        pairs = []
        if isinstance(n, ast.Dict):
            pairs = zip(n.keys, n.values)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "dict":
            pairs = ((ast.Constant(k.arg), k.value) for k in n.keywords if k.arg)
        row = {k.value: v.value for k, v in pairs if isinstance(k, ast.Constant) and isinstance(k.value, str)
               and isinstance(v, ast.Constant) and isinstance(v.value, (str, int))}
        if row:
            rows.append(row)
    return rows


def _import_records(path: Path) -> list:
    """Task modules build their lists in code; import them (data modules) to see every brief."""
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(f"_r2_corpus_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    out = []
    for name, value in vars(module).items():
        if not name.startswith("_") and isinstance(value, (list, tuple, dict)):
            _records(value, out)
    return out


def corpus(root: Path = ROOT, exclude=()) -> dict:
    records, errors, texts = [], [], []
    files = corpus_files(root, exclude)
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        texts.append(text)
        found = []
        try:
            if path.suffix == ".json":
                _records(json.loads(text), found)
            elif path.suffix == ".py":
                found += _ast_dicts(ast.parse(text))
                if path.stem.startswith("tasks"):
                    found += _import_records(path)
        except Exception as exc:  # a file we cannot read is reported, never silently skipped
            errors.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"[:300]})
        records += [(rel, r) for r in found]
    ids, repos, briefs = set(), set(ALWAYS_USED), []
    for rel, r in records:
        if isinstance(r.get("id"), str):
            ids.add(r["id"])
        repo = r.get("repo")
        if isinstance(repo, str) and repo.strip():
            repos.add(norm_name(repo))
        url = r.get("url")
        if isinstance(url, str) and "github.com/" in url:
            repos.add(norm_name(url))
        for key in BRIEF_KEYS:
            text = r.get(key)
            if isinstance(text, str) and (key == "brief" and text.strip() or len(text.strip()) >= 40):
                briefs.append({"source": rel, "id": r.get("id"), "brief": text})
    # repository names that only appear as dict keys (tasks_holdout.REPOS)
    for rel, r in records:
        for key, value in r.items():
            if isinstance(value, dict) and isinstance(value.get("url"), str) and "github.com/" in value["url"]:
                repos.add(norm_name(key))
    shas = {m for t in texts for m in re.findall(r"\b[0-9a-f]{7,40}\b", t) if not m.isdigit()}
    seen, unique = set(), []
    for b in briefs:
        key = (b["source"], b["brief"])
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return {"files": len(files), "ids": ids, "repos": repos, "shas": shas, "briefs": unique, "errors": errors}


# ---------------------------------------------------------------- leakage

def normalize_brief(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())


def ratio(a: str, b: str) -> float:
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if m.real_quick_ratio() <= LISTED or m.quick_ratio() <= LISTED:  # both are upper bounds
        return 0.0
    return m.ratio()


def leak_check(tasks: list[dict], corp: dict) -> dict:
    old = [(b, normalize_brief(b["brief"])) for b in corp["briefs"]]
    rows = []
    for i, task in enumerate(tasks):
        findings, near = [], []
        if task.get("id") in corp["ids"]:
            findings.append(f"id {task['id']} used before")
        sha = str(task.get("commit") or "")
        if sha and any(sha.startswith(s) for s in corp["shas"]):
            findings.append(f"commit {sha} appears in an earlier evaluation")
        if task.get("repo") and norm_name(task["repo"]) in corp["repos"]:
            findings.append(f"repository {task['repo']} used before")
        brief = normalize_brief(task.get("brief") or "")
        others = old + [({"source": "new", "id": t.get("id")}, normalize_brief(t.get("brief") or ""))
                        for t in tasks[i + 1:]]
        for source, text in others:
            score = ratio(brief, text) if brief and text else 0.0
            if score > LISTED:
                near.append({"source": source["source"], "id": source.get("id"), "ratio": round(score, 4)})
        near.sort(key=lambda r: (-r["ratio"], str(r["source"]), str(r["id"])))
        findings += [f"brief similar to {r['source']}:{r['id']} (ratio {r['ratio']})" for r in near if r["ratio"] >= SIMILAR]
        rows.append({"id": task.get("id"), "findings": findings, "listed_above_0.4": near, "clean": not findings})
    return {"rule": f"same id, same repository, same commit (or earlier short SHA prefix), or normalized brief "
                    f"SequenceMatcher ratio >= {SIMILAR}; candidates above {LISTED} listed",
            "corpus": {"files": corp["files"], "briefs": len(corp["briefs"]), "ids": len(corp["ids"]),
                       "repos": sorted(corp["repos"]), "errors": corp["errors"]},
            "tasks": rows, "clean": all(r["clean"] for r in rows) and not corp["errors"]}


# ---------------------------------------------------------------- briefs: literals and trace table

def _qualname(tree):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test"):
                    yield f"{node.name}::{sub.name}", sub


def _is_check(node) -> bool:
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Call):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        return name.startswith("assert") or name in ("raises", "warns")
    return False


def assertions(rel: str, source: str) -> list[dict]:
    """Every check of a hidden test file: `file::test#n`, in source order, with its literals."""
    out = []
    for qual, fn in _qualname(ast.parse(source)):
        checks = sorted((n for n in ast.walk(fn) if _is_check(n)), key=lambda n: (n.lineno, n.col_offset))
        for k, node in enumerate(checks, 1):
            lits = [c.value for c in ast.walk(node) if isinstance(c, ast.Constant)
                    and not isinstance(c.value, bool) and c.value is not None]
            out.append({"id": f"{rel}::{qual}#{k}", "literals": lits})
    return out


def _suspicious(lit, brief: str) -> bool:
    if isinstance(lit, bytes):
        lit = lit.decode("utf-8", "replace")
    if isinstance(lit, str):
        return len(lit.strip()) >= 4 and lit.casefold() in brief.casefold()
    if isinstance(lit, (int, float)) and (abs(lit) >= 10 or lit != int(lit)):
        return re.search(rf"(?<![\w.]){re.escape(str(lit))}(?![\w])", brief) is not None
    return False


def brief_checks(brief: str, hidden: dict[str, str], trace: list[dict]) -> dict:
    checks = [a for rel, src in sorted(hidden.items()) for a in assertions(rel, src)]
    overlap = [{"assertion": a["id"], "literal": lit if not isinstance(lit, bytes) else lit.decode("utf-8", "replace")}
               for a in checks for lit in a["literals"] if _suspicious(lit, brief)]
    seen = {(o["assertion"].split("::")[0], repr(o["literal"])) for o in overlap}
    for rel, src in sorted(hidden.items()):
        for c in ast.walk(ast.parse(src)):
            if (isinstance(c, ast.Constant) and not isinstance(c.value, bool) and c.value is not None
                    and (rel, repr(c.value)) not in seen and _suspicious(c.value, brief)):
                lit = c.value.decode("utf-8", "replace") if isinstance(c.value, bytes) else c.value
                overlap.append({"assertion": f"{rel}:{c.lineno} (outside an assert)", "literal": lit})
                seen.add((rel, repr(c.value)))
    known = {a["id"] for a in checks}
    mapped = {}
    for row in trace or []:
        mapped.setdefault(row.get("assertion"), []).append(row.get("brief") or "")
    flat = normalize_brief(brief)
    return {"assertions": len(checks),
            "literal_overlap": overlap,
            "unmapped": sorted(known - set(mapped)),
            "unknown_in_trace": sorted(str(k) for k in set(mapped) - known),
            "sentence_not_in_brief": sorted({s for ss in mapped.values() for s in ss
                                             if not s.strip() or normalize_brief(s) not in flat}),
            "trace_complete": bool(known) and known <= set(mapped) and set(mapped) <= known
                              and all(s.strip() and normalize_brief(s) in flat for ss in mapped.values() for s in ss)}


# ---------------------------------------------------------------- authored tasks

def _tree_with(src: Path, dest: Path, extra: dict[str, bytes]) -> Path:
    shutil.copytree(src, dest)
    for rel, body in extra.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    return dest


def check_authored(task_dir: Path, python: str, run=None) -> dict:
    """Layout: task.json {id, brief, hidden_tests, trace}, start/, reference/, hidden/<hidden_tests paths>."""
    run = run or LE.hidden
    task = read_json(task_dir / "task.json")
    hidden = {rel: (task_dir / "hidden" / rel).read_bytes() for rel in task["hidden_tests"]}
    previous, LE.UTF8_MODE = LE.UTF8_MODE, True  # PYTHONUTF8=1 like upstream tasks; frozen as pythonutf8 (#415)
    try:
        with tempfile.TemporaryDirectory(prefix="r2-authored-") as tmp:
            root = Path(tmp)
            existing = run(_tree_with(task_dir / "start", root / "existing", {}), [], python)
            parent = run(_tree_with(task_dir / "start", root / "start", hidden), task["hidden_tests"], python)
            reference = run(_tree_with(task_dir / "reference", root / "reference", hidden), task["hidden_tests"],
                            python)
    finally:
        LE.UTF8_MODE = previous
    briefs = brief_checks(task["brief"], {k: v.decode("utf-8") for k, v in hidden.items()}, task.get("trace", []))
    problems = []
    if existing["rc"] != 0:
        problems.append(f"existing suite fails on start (rc={existing['rc']})")
    if parent["rc"] not in (1, 2):
        problems.append(f"hidden tests do not fail on start (rc={parent['rc']})")
    if reference["rc"] != 0:
        problems.append(f"reference fails hidden tests (rc={reference['rc']})")
    if not briefs["trace_complete"]:
        problems.append("trace table incomplete")
    return {"id": task["id"], "pythonutf8": True, "existing": existing, "start": parent, "reference": reference, **briefs,
            "problems": problems, "valid": not problems,
            "review": [f"literal {o['literal']!r} of {o['assertion']} appears in the brief" for o in briefs["literal_overlap"]]}


# ---------------------------------------------------------------- repository list

def license_ok(info: dict) -> str | None:
    texts = [info.get("license_expression") or "", (info.get("license") or "")[:200]]
    texts += [c for c in info.get("classifiers") or [] if c.startswith("License ::")]
    blob = " ".join(texts).casefold()
    for names in LICENSES:
        if any(re.search(rf"\b{re.escape(n)}\b", blob) for n in names):
            return names[0]
    return None


# known first path parts on github.com that are not an owner (a funding link github.com/sponsors/<user> is not a
# repository, #397); add others as they are found
NOT_OWNER = ("sponsors", "orgs", "users", "apps", "marketplace", "features", "topics", "collections", "settings")


def repo_key(spec_or_url) -> str:
    """Identity of a repository for de-duplication (#397): `owner/name` case-folded from its GitHub URL, so
    github.com/a/utils and github.com/b/utils stay two repositories; without a URL, the normalized name."""
    url = spec_or_url.get("url") if isinstance(spec_or_url, dict) else spec_or_url
    m = re.match(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", str(url or "").strip())
    if m:
        return f"{m.group(1)}/{m.group(2)}".casefold()
    return norm_name(spec_or_url.get("repo", "") if isinstance(spec_or_url, dict) else spec_or_url)


def github_url(info: dict) -> str | None:
    urls = list((info.get("project_urls") or {}).values()) + [info.get("home_page") or ""]
    for u in urls:
        m = re.match(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?(?:[#?].*)?$", str(u or "").strip())
        if m and m.group(1).casefold() not in NOT_OWNER:
            return f"https://github.com/{m.group(1)}/{m.group(2)}"
    return None


def repo_list(snapshot: dict, meta_dir: Path, used: set[str]) -> dict:
    kept, excluded, first = [], [], {}  # first: repository -> the kept row that listed it (#397)
    for rank, row in enumerate(snapshot["rows"], 1):
        project = row["project"]
        path = Path(meta_dir) / f"{norm_name(project)}.json"
        reason, entry = None, {"rank": rank, "project": project}
        if not path.is_file():
            reason = "no PyPI metadata"
        else:
            info = read_json(path).get("info", {})
            url, lic = github_url(info), license_ok(info)
            if not url:
                reason = "source is not a public GitHub repository"
            elif not lic:
                reason = "license not MIT/BSD/Apache-2.0/ISC/PSF"
            elif norm_name(project) in used or norm_name(url) in used:
                reason = "used in an earlier evaluation"
            elif repo_key(url) in first:
                prior = first[repo_key(url)]
                reason = f"same repository as rank {prior['rank']} ({prior['project']})"
            else:
                entry.update(repo=repo_key(url), url=url, license=lic)  # owner/name: also the cache key (#400)
                first[repo_key(url)] = entry
        (excluded if reason else kept).append({**entry, **({"reason": reason} if reason else {})})
    return {"snapshot_last_update": snapshot.get("last_update"), "rule": "rank order; GitHub source; MIT/BSD/"
            "Apache-2.0/ISC/PSF; not used before; each repository once, at its best rank; pure Python and offline "
            "suite are checked by select",
            "kept": kept, "excluded": excluded}


# ---------------------------------------------------------------- upstream selection

def _since_ts(date: str) -> int:
    return calendar.timegm(time.strptime(date, "%Y-%m-%d"))


def compiled_files(cache: Path, repo: str) -> list[str]:
    bare = LCand.bare_path(cache, repo)
    names = E._git(None, f"--git-dir={bare}", "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    return [n for n in names if n.lower().endswith(COMPILED)]


def _size_ok(row, size) -> bool:
    return row["code_lines"] >= size[0] or len(row["code"]) >= size[1]


def test_changes(cache: Path, repo: str, sha: str) -> str | None:
    """A reason to exclude, or None. Only `test*.py` files become hidden tests, so a commit that also changes
    conftest.py, helpers or data under a tests folder would leave the agent without them; a deleted or renamed
    test file cannot be read at the commit."""
    bare = LCand.bare_path(cache, repo)
    out = E._git(None, "-c", "core.quotepath=false", f"--git-dir={bare}", "diff-tree", "--no-commit-id", "-r",
                 "--name-status", "-M", sha)
    support, gone = [], []
    for line in out.splitlines():
        parts = line.split("\t")
        status, names = parts[0], parts[1:]
        for name in names:
            if not LCand.is_test(name):
                continue
            if status[0] in "DR":
                gone.append(name)
            elif not (name.endswith(".py") and Path(name).name.startswith("test")) and Path(name).name != "__init__.py":
                support.append(name)
    if gone:
        return "deletes or renames a test file: " + ", ".join(sorted(set(gone))[:3])
    if support:
        return "changes test support files: " + ", ".join(sorted(set(support))[:3])
    return None


def _validate(cache, python, task, raw_dir):
    previous = LE.SRC_ON_PATH, LE.UTF8_MODE
    LE.SRC_ON_PATH = True  # src-layout packages import from src/, as long_check does
    LE.UTF8_MODE = True    # PYTHONUTF8=1, recorded as the task's pythonutf8 (#415)
    try:
        return LE.validate_task(cache, python, task, raw_dir, SUITE_TIMEOUT)
    finally:
        LE.SRC_ON_PATH, LE.UTF8_MODE = previous


def _version_files(config: dict) -> list[str]:
    """Version files a build backend writes at install time, as the pyproject declares them (#415):
    setuptools-scm `version_file` / `write_to`, hatch's vcs build hook `version-file` (also per build target)."""
    tool = config.get("tool") or {}
    scm = tool.get("setuptools_scm") or {}
    hatch = (tool.get("hatch") or {}).get("build") or {}
    hooks = [(hatch.get("hooks") or {}).get("vcs") or {}]
    hooks += [((t or {}).get("hooks") or {}).get("vcs") or {} for t in (hatch.get("targets") or {}).values()]
    found = [scm.get("version_file"), scm.get("write_to")] + [h.get("version-file") for h in hooks]
    paths = {f.strip().replace("\\", "/") for f in found if isinstance(f, str) and f.strip()}
    paths = {p[2:] if p.startswith("./") else p for p in paths}
    # only relative paths inside the tree: no absolute path, drive or '..' part
    return sorted(p for p in paths if not p.startswith("/") and ":" not in p and ".." not in p.split("/"))


def version_stubs(cache: Path, repo: str, sha: str) -> list[str]:
    """Install-time version files the parent's pyproject.toml declares and its tree does not contain (#415). They are
    written with ext_repo's VERSION_STUB in validation and in the P4 run (the task's `stubs`), as for the hold-out set."""
    import tomllib
    try:
        bare = LCand.bare_path(cache, repo)
        text = E._git(None, f"--git-dir={bare}", "show", f"{sha}^:pyproject.toml")
    except (FileNotFoundError, RuntimeError):  # no clone (then validation reports it) or no pyproject.toml
        return []
    try:
        files = _version_files(tomllib.loads(text))
    except tomllib.TOMLDecodeError:
        return []
    present = set(E._git(None, f"--git-dir={bare}", "ls-tree", "-r", "--name-only", f"{sha}^", "--", *files)
                  .splitlines()) if files else set()
    return [f for f in files if f not in present]


TAG_VERSION = re.compile(r"\d+(?:\.\d+)+")


def stub_version(cache: Path, repo: str, sha: str) -> str:
    """The version a task's install-time version stub reports (#424): the first `digits.digits...` in the nearest tag
    reachable from the parent (`git describe --tags --abbrev=0`), e.g. v8.4.1 -> 8.4.1; "0.0" when there is no tag or
    it holds no such version. (A stub reporting 0.0 broke pytest's own minversion check.)"""
    try:
        tag = E._git(None, f"--git-dir={LCand.bare_path(cache, repo)}", "describe", "--tags", "--abbrev=0",
                     f"{sha}^").strip()
    except (FileNotFoundError, RuntimeError):
        return "0.0"
    m = TAG_VERSION.search(tag)
    return m.group(0) if m else "0.0"


REQUIREMENT_FILE = re.compile(r"(^|/)((test|dev)[-_]?requirements[^/]*|requirements[^/]*)\.(txt|in)$|"
                              r"(^|/)requirements/[^/]+\.(txt|in)$", re.I)
PLUGIN_GROUPS = (*TEST_EXTRAS, "dev")


def _req_name(text: str) -> str | None:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", text or "")
    return norm_name(m.group(1)) if m and not text.lstrip().startswith(("-", "#")) else None


def declared(cache: Path, repo: str, sha: str) -> dict:
    """What the parent declares, read mechanically (#424): requirement names from pyproject.toml (project.dependencies,
    optional-dependencies and [dependency-groups] test/tests/testing/dev), setup.cfg (install_requires,
    extras_require of the same groups) and requirements files (requirements*.txt/.in, test-/dev-requirements*,
    requirements/*.txt), plus the pytest11 entry points the project itself declares (pyproject or setup.cfg)."""
    import configparser
    import tomllib
    try:
        bare = LCand.bare_path(cache, repo)
    except FileNotFoundError:  # no clone: validation reports it
        return {"requirements": [], "own_plugins": []}
    names, own = set(), []

    def show(path):
        try:
            return E._git(None, f"--git-dir={bare}", "show", f"{sha}^:{path}")
        except RuntimeError:
            return None
    text = show("pyproject.toml")
    if text:
        try:
            config = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            config = {}
        project = config.get("project") or {}
        reqs = list(project.get("dependencies") or [])
        for group, items in (project.get("optional-dependencies") or {}).items():
            if norm_name(group) in PLUGIN_GROUPS:
                reqs += list(items or [])
        reqs += dependency_groups(config, PLUGIN_GROUPS)
        names |= {n for n in map(_req_name, (r for r in reqs if isinstance(r, str))) if n}
        own += [str(v) for v in ((project.get("entry-points") or {}).get("pytest11") or {}).values()]
    text = show("setup.cfg")
    if text:
        cfg = configparser.ConfigParser(interpolation=None)
        try:
            cfg.read_string(text)
        except configparser.Error:
            cfg = configparser.ConfigParser()
        lines = cfg.get("options", "install_requires", fallback="").splitlines()
        if cfg.has_section("options.extras_require"):
            for group, value in cfg.items("options.extras_require"):
                if norm_name(group) in PLUGIN_GROUPS:
                    lines += value.splitlines()
        names |= {n for n in map(_req_name, lines) if n}
        if cfg.has_section("options.entry_points"):
            for line in cfg.get("options.entry_points", "pytest11", fallback="").splitlines():
                if "=" in line:
                    own.append(line.split("=", 1)[1].strip())
    try:
        files = E._git(None, "-c", "core.quotepath=false", f"--git-dir={bare}", "ls-tree", "-r", "--name-only",
                       f"{sha}^").splitlines()
    except RuntimeError:
        files = []
    for path in (p for p in files if REQUIREMENT_FILE.search(p)):
        names |= {n for n in map(_req_name, (show(path) or "").splitlines()) if n}
    return {"requirements": sorted(names), "own_plugins": sorted({v.split(":")[0].strip() for v in own if v.strip()})}


PLUGIN_QUERY = ("import importlib.metadata as m, json\n"
                "print(json.dumps(sorted({(ep.dist.name if ep.dist else '', ep.value) "
                "for ep in m.entry_points(group='pytest11')})))\n")


def ext_plugins(python: str, run=subprocess.run) -> list[tuple[str, str]]:
    """(distribution, module) of every pytest11 entry point registered in --ext-python."""
    r = run([python, "-c", PLUGIN_QUERY], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode:
        raise RuntimeError(f"cannot list pytest plugins in --ext-python (rc={r.returncode})")
    return [(norm_name(d), v.split(":")[0].strip()) for d, v in json.loads(r.stdout)]


def pytest_plugins(decl: dict, registered: list[tuple[str, str]], project: str) -> list[str]:
    """Plugin modules a task loads through PYTEST_PLUGINS (#424): those of --ext-python distributions the parent
    declares as a requirement (not the task's own distribution: its installed copy is an older release), plus the
    project's own pytest11 entry points (imported from the repository, which comes first on PYTHONPATH)."""
    wanted = set(decl.get("requirements") or ()) - {norm_name(project)}
    mods = {mod for dist, mod in registered if dist in wanted} | set(decl.get("own_plugins") or ())
    return sorted(mods)


def src_layout(cache: Path, repo: str, sha: str) -> bool:
    """The parent tree has a top-level src/ folder; the evaluation run must then put src/ on PYTHONPATH too."""
    bare = LCand.bare_path(cache, repo)
    return bool(E._git(None, f"--git-dir={bare}", "ls-tree", "-d", "--name-only", f"{sha}^", "src").strip())


# ---------------------------------------------------------------- vendored copies in --ext-python (#417)

# The folders --ext-python can read code from, one "S\t<path>" line each: purelib, platlib, the site-packages folders
# of site.getsitepackages() and of sys.path, the user site when it is enabled (as importlib.metadata sees it), and
# ensurepip's bundled wheels in the standard library (pip with its own vendored packages)
SITE_DIRS = ("import os, site, sys, sysconfig\n"
             "paths = {sysconfig.get_paths()[k] for k in ('purelib', 'platlib')}\n"
             "paths |= {p for p in [*getattr(site, 'getsitepackages', list)(), *sys.path]\n"
             "          if os.path.basename(p) in ('site-packages', 'dist-packages') and os.path.isdir(p)}\n"
             "user = site.getusersitepackages() if site.ENABLE_USER_SITE else None\n"
             "paths |= {user} if user and os.path.isdir(user) else set()\n"
             "bundled = os.path.join(sysconfig.get_paths()['stdlib'], 'ensurepip', '_bundled')\n"
             "paths |= {bundled} if os.path.isdir(bundled) else set()\n"
             "for p in sorted(paths):\n    print('S\\t' + p)\n")
VENDOR_DIRS = ("_vendor", "vendor", "_vendored", "vendored")
VENDOR_RULE = ("vendored copies: every folder named " + "/".join(VENDOR_DIRS) + " under --ext-python's site-packages, "
               "user site (when enabled) and ensurepip's bundled wheels, and in every .whl there (e.g. virtualenv's "
               "embedded pip/setuptools wheels), is read without changing it; each top-level package or module in such "
               "a folder is one copy, and so is each top-level package of a .whl; a copy is named by its folder or "
               "module and by the distributions *.dist-info top_level.txt maps to it; its version comes from "
               "vendor.txt (matched by name), *.dist-info METADATA, else __version__; a copy belongs to a task when "
               "one of its names equals the task's project or a top-level package of the parent's tree (root or src/ "
               "only, tests/docs/setup excluded); a file or wheel that cannot be read is a scan error")
_VERSION = re.compile(r"""^__version__\s*(?::\s*str\s*)?=\s*['"]([^'"]+)['"]""", re.M)
_PKG_SKIP = re.compile(r"^(tests?|testing|docs?|examples?|benchmarks?|scripts?|setup|conftest|noxfile|tasks)$|^test_")


def package_names(cache: Path, repo: str, sha: str) -> set[str]:
    """Normalized top-level import names in the parent's tree (root or src/), to recognize a vendored copy whose folder
    is the import name rather than the distribution name (python-dateutil -> dateutil)."""
    bare = LCand.bare_path(cache, repo)
    names = set()
    for n in E._git(None, "-c", "core.quotepath=false", f"--git-dir={bare}", "ls-tree", "-r", "--name-only",
                    f"{sha}^").splitlines():
        if not n.endswith(".py"):
            continue
        m = re.match(r"^(?:src/)?([^/]+)/__init__\.py$", n) or re.match(r"^src/([^/]+)/", n) \
            or re.match(r"^(?:src/)?([^/]+)\.py$", n)
        if m and not _PKG_SKIP.match(m.group(1).lower()):
            names.add(norm_name(m.group(1)))
    return names


def _vendor_copies(rels: list[str], read, where: str) -> list[dict]:
    """The copies in one vendor folder. rels: posix paths of its files relative to it; read(rel) -> text, or None when
    it cannot be read; where: the folder as shown in reports. Each copy carries the stripped lines of its .py files
    and the files it could not read."""
    versions, tops, present = {}, {}, set(rels)
    if "vendor.txt" in present:
        for line in (read("vendor.txt") or "").splitlines():
            m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;#]+)", line)
            if m:
                versions[norm_name(m.group(1))] = m.group(2)
    for rel in rels:
        parts = rel.split("/")
        if len(parts) == 2 and parts[0].endswith(".dist-info") and parts[1] == "METADATA":
            text = read(rel) or ""
            name, ver = re.search(r"^Name:\s*(\S+)", text, re.M), re.search(r"^Version:\s*(\S+)", text, re.M)
            if not name:
                continue
            key = norm_name(name.group(1))
            if ver:
                versions[key] = ver.group(1)
            top_level = f"{parts[0]}/top_level.txt"
            for top in ((read(top_level) or "").split() if top_level in present else ()):
                tops.setdefault(norm_name(top), set()).add(key)
    entries: dict[str, list[str]] = {}
    for rel in rels:
        parts = rel.split("/")
        if not rel.endswith(".py") or "__pycache__" in parts:
            continue
        if len(parts) == 1:
            if rel != "__init__.py":
                entries.setdefault(rel[:-3], []).append(rel)
        elif not parts[0].endswith((".dist-info", ".data")):
            entries.setdefault(parts[0], []).append(rel)
    copies = []
    for entry, files in sorted(entries.items()):
        names = {norm_name(entry)} | tops.get(norm_name(entry), set())
        version = ", ".join(sorted({versions[n] for n in names if n in versions})) or None
        for rel in (f"{entry}/__init__.py", f"{entry}.py", f"{entry}/__about__.py", f"{entry}/_version.py",
                    f"{entry}/version.py"):
            if version is None and rel in present:
                m = _VERSION.search(read(rel) or "")
                version = m.group(1) if m else None
        lines, unread = set(), []
        for rel in sorted(files):
            text = read(rel)
            if text is None:
                unread.append(rel)
            else:
                lines |= {s.strip() for s in text.splitlines()}
        copies.append({"where": f"{where}/{entry}", "names": sorted(names), "version": version,
                       "lines": frozenset(lines), "unread": unread})
    return copies


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _wheel_copies(path: Path, shown: str) -> tuple[list[dict], list[str]]:
    """Copies in a wheel: its own top-level packages and those in its vendor folders, and the scan errors. Any failure
    to read the wheel (bad zip, zlib.error, unsupported compression, truncated file, ...) is a scan error."""
    import zipfile
    try:
        if path.stat().st_size == 0:  # an empty leftover file holds no code
            return [], []
        with zipfile.ZipFile(path) as z:
            members = [n for n in z.namelist() if not n.endswith("/")]
            data = {n: z.read(n).decode("utf-8", "replace") for n in members
                    if n.endswith((".py", "/vendor.txt", "/METADATA", "/top_level.txt")) or n == "vendor.txt"}
    except Exception as exc:  # noqa: BLE001 - a broken wheel never stops the scan; it is reported
        return [], [f"{shown}: {type(exc).__name__}: {exc}"[:300]]
    prefixes = {""}
    for n in members:
        parts = n.split("/")
        prefixes |= {"/".join(parts[:i + 1]) for i, p in enumerate(parts[:-1]) if p in VENDOR_DIRS}
    copies = []
    for prefix in sorted(prefixes):
        lead = prefix + "/" if prefix else ""
        rels = [n[len(lead):] for n in members if n.startswith(lead)]
        copies += _vendor_copies(rels, lambda r, lead=lead: data.get(lead + r, ""), f"{shown}!{prefix}")
    for c in copies:  # the wheel's own top level reads "x.whl!/pkg"; show it as "x.whl!pkg"
        c["where"] = c["where"].replace("!/", "!", 1)
    return copies, []


def _shown(root: Path, path: Path) -> str:
    """A path as reported: relative to its scanned folder; ensurepip's bundled wheels keep "ensurepip/_bundled/"."""
    rel = path.relative_to(root).as_posix()
    if (root.parent.name, root.name) == ("ensurepip", "_bundled"):
        return f"ensurepip/_bundled/{rel}"
    return rel


@functools.lru_cache(maxsize=8)
def vendored_inventory(sites: tuple[str, ...]) -> tuple[tuple, tuple]:
    """Every vendored copy (VENDOR_RULE) under these folders and the scan errors (folders that cannot be listed,
    wheels that cannot be read, copies with unreadable files), read once per run: the result, errors included, is
    cached, so a broken wheel is not rescanned for every candidate."""
    copies, errors = [], []
    for site in sites:
        root = Path(site)
        if not root.is_dir():
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: errors.append(
                    f"{getattr(e, 'filename', '?')}: {type(e).__name__}: {e}"[:300])):
                dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
                base = Path(dirpath)
                if base != root and base.name in VENDOR_DIRS:
                    rels = sorted(p.relative_to(base).as_posix() for p in base.rglob("*")
                                  if p.is_file() and "__pycache__" not in p.parts)
                    copies += _vendor_copies(rels, lambda r, b=base: _read_text(b / r), _shown(root, base))
                for f in sorted(filenames):
                    if f.endswith(".whl"):
                        found, failed = _wheel_copies(base / f, _shown(root, base / f))
                        copies += found
                        errors += failed
        except Exception as exc:  # noqa: BLE001 - recorded; the other folders are still scanned
            errors.append(f"{site}: {type(exc).__name__}: {exc}"[:300])
    errors += [f"{c['where']}: cannot read " + ", ".join(c["unread"][:3]) for c in copies if c["unread"]]
    return tuple(copies), tuple(errors)


def _site_key(sites) -> tuple[str, ...]:
    return tuple(sorted({os.path.normcase(os.path.abspath(s)) for s in sites}))


def vendored_copies(sites, names: set[str]) -> list[dict]:
    """The vendored copies one of whose names is in `names` (normalized)."""
    return [c for c in vendored_inventory(_site_key(sites))[0] if names & set(c["names"])]


def vendored_errors(sites) -> list[str]:
    """The scan errors of vendored_inventory for these folders (cached with it)."""
    return list(vendored_inventory(_site_key(sites))[1])


def _site_lines(stdout: str) -> tuple[list[str], list[str]]:
    """Split an interpreter's output into site-packages folders ("S\t" lines) and the other lines."""
    lines = (stdout or "").splitlines()
    return [s[2:] for s in lines if s.startswith("S\t")], [s for s in lines if not s.startswith("S\t")]


OWN_FILES = SITE_DIRS + ("import importlib.metadata as m, sys\n"
                         "try:\n    d = m.distribution(sys.argv[1])\nexcept m.PackageNotFoundError:\n    sys.exit(0)\n"
                         "print(d.version)\n"
                         "for f in d.files or ():\n    print(d.locate_file(f)) if str(f).endswith('.py') else None\n")
LEAK_LINE = 30  # a new line this long (stripped, not a comment) found in the installed package is a hit
LEAK_HITS = 2   # a commit is excluded at this many hits, or when every one of its new lines is a hit
OVERLAP_RULE = (f"the task's own distribution in --ext-python and every vendored copy of it (#417; {VENDOR_RULE}); "
                f"new lines = lines the commit adds to code files, "
                f"stripped, at least {LEAK_LINE} characters, not comments, found nowhere in the parent's code files; "
                f"excluded when at least {LEAK_HITS} new lines, or all of them (at least one), appear in the installed "
                f"package's .py files together with its vendored copies' .py files; an installed package whose files "
                f"cannot be read, or a vendored copy of it with an unreadable file, is excluded as unknown; scan "
                f"errors that belong to no copy (a folder that cannot be listed, a wheel that cannot be read) do not "
                f"exclude commits, are listed once in vendored_scan_errors and make env-check fail")


def _tree_lines(bare: Path, rev: str) -> set[str]:
    """Every stripped line of every code file (LCand.is_code) in `rev`'s tree, read in one `git cat-file --batch`."""
    names = [n for n in E._git(None, "-c", "core.quotepath=false", f"--git-dir={bare}", "ls-tree", "-r", "--name-only",
                               rev).splitlines() if LCand.is_code(n)]
    if not names:
        return set()
    r = subprocess.run(["git", f"--git-dir={bare}", "cat-file", "--batch"], capture_output=True,
                       input="".join(f"{rev}:{n}\n" for n in names).encode("utf-8"))
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[:300])
    out, data, pos = set(), r.stdout, 0
    while pos < len(data):
        end = data.index(b"\n", pos)
        header = data[pos:end].split()
        pos = end + 1
        if len(header) == 3 and header[1] == b"blob":
            size = int(header[2])
            out |= {s.strip() for s in data[pos:pos + size].decode("utf-8", "replace").splitlines()}
            pos += size + 1
    return out


def installed_overlap(python: str, project: str, cache: Path, repo: str, sha: str, run=subprocess.run) -> dict | None:
    """#415 review: the task's own distribution may sit in --ext-python (a kept package pinned as another repository's
    dependency, released before the commit by date). Dates do not prove it lacks the change, so the commit's new lines
    are compared with the installed files (OVERLAP_RULE). None: not installed. {"status": "unknown"}: the interpreter
    call failed or the distribution lists no files. Vendored copies of the package (#417, VENDOR_RULE) are compared
    together with the installed files, also when the distribution itself is absent; a copy with unreadable files makes
    the result unknown. {"status": "absent", "scan_errors": [...]}: nothing to compare, but the vendored scan had
    errors (select records them; env-check fails on them). Not covered: code copied into another package outside a
    vendor folder."""
    r = run([python, "-c", OWN_FILES, project], capture_output=True, text=True, encoding="utf-8", timeout=120)
    sites, lines = _site_lines(r.stdout)
    if r.returncode != 0:
        return {"status": "unknown", "error": f"--ext-python query failed (rc={r.returncode})"}
    copies, errors = [], []
    if sites:
        errors = vendored_errors(sites)
        if vendored_inventory(_site_key(sites))[0]:  # the parent's tree is read only when there is a copy to match
            copies = vendored_copies(sites, {norm_name(project)} | package_names(cache, repo, sha))
    vendored = {"vendored": [{"where": c["where"], "version": c["version"]} for c in copies]} if copies else {}
    scan = {"scan_errors": errors} if errors else {}
    if not lines and not copies:
        return {"status": "absent", **scan} if errors else None
    if len(lines) == 1:
        return {"status": "unknown", "installed": lines[0].strip(), "error": "the distribution lists no .py files",
                **vendored, **scan}
    unread = [c["where"] for c in copies if c["unread"]]
    if unread:
        return {"status": "unknown", "installed": lines[0].strip() if lines else None,
                "error": "vendored copy with unreadable files: " + ", ".join(unread[:3]), **vendored, **scan}
    installed = set()
    for name in lines[1:]:
        try:
            installed |= {s.strip() for s in Path(name).read_text(encoding="utf-8", errors="replace").splitlines()}
        except OSError:
            continue
    for c in copies:
        installed |= c["lines"]
    bare = LCand.bare_path(cache, repo)
    code = [n for n in E._git(None, "-c", "core.quotepath=false", f"--git-dir={bare}", "diff", "--name-only",
                              f"{sha}^", sha).splitlines() if LCand.is_code(n)]
    before = _tree_lines(bare, f"{sha}^")
    diff = E._git(None, f"--git-dir={bare}", "diff", "-U0", f"{sha}^", sha, "--", *code) if code else ""
    added = {s[1:].strip() for s in diff.splitlines() if s.startswith("+") and not s.startswith("+++")}
    new = sorted(s for s in added if len(s) >= LEAK_LINE and not s.startswith("#") and s not in before)
    hits = [s for s in new if s in installed]
    leak = len(hits) >= LEAK_HITS or (bool(hits) and len(hits) == len(new))
    return {"status": "compared", "installed": lines[0].strip() if lines else None, "new_lines": len(new),
            "hits": len(hits), "examples": hits[:3], "leak": leak, **vendored, **scan}


def overlap_reason(project: str, found: dict | None) -> str | None:
    """The exclusion reason for an installed_overlap result, or None to keep the commit."""
    if not found or found.get("status") == "absent":
        return None
    own = f"installed {project} {found.get('installed') or ''}".rstrip()
    copies = "; ".join(f"{v['where']} {v['version'] or '(version unknown)'}" for v in found.get("vendored") or [])
    if copies:
        own = f"{own} and vendored copies {copies}" if found.get("installed") else f"vendored copies of {project}: {copies}"
    if found.get("status") == "unknown":
        return f"cannot compare {own}: {found['error']}"
    if found.get("leak"):
        return f"{own} already has {found['hits']} of the {found['new_lines']} new line(s) the commit adds"
    return None


def _why_invalid(result: dict) -> str:
    if (result.get("baseline") or {}).get("rc") != 0:
        return f"existing suite does not pass on parent (rc={(result.get('baseline') or {}).get('rc')})"
    if result["parent"]["rc"] not in (1, 2):
        return f"no hidden test fails on parent (rc={result['parent']['rc']})"
    return f"hidden tests do not all pass on the commit (rc={result['reference']['rc']})"


def _phase(b, c, b_dev, c_dev):
    """The group the next qualifying commit goes to, in the pre-registered order B, C, B-dev, C-dev, as
    (group, dev); (None, None) when all four are full."""
    if len(b) < B_TAKE:
        return "B", False
    if len(c) < C_TAKE:
        return "C", False
    if len(b_dev) < B_DEV_TAKE:
        return "B", True
    if len(c_dev) < C_DEV_TAKE:
        return "C", True
    return None, None


def select_upstream(cache: Path, repos: list[dict], python: str, used: set[str], since: str = SINCE,
                    raw_dir: Path | None = None, validator=None, overlap=None, registered=None) -> dict:
    overlap = overlap or installed_overlap  # `overlap` and `registered` are for tests (a fake --ext-python)
    validator = validator or _validate
    plugins_in_env = registered  # pytest11 entry points of --ext-python, listed once when first needed (#424)
    slow = {}  # repository -> the commit whose full suite first ran past SUITE_TIMEOUT (a repository condition, #424)
    since_ts = _since_ts(since)
    b, c, b_dev, c_dev, exclusions, checked = [], [], [], [], [], []
    scan_errors = set()  # vendored scan errors (#417), recorded once in the output; env-check fails on them
    per_b, per_c = Counter(), Counter()  # final and development tasks together, per repository
    visited = set()
    for spec in repos:
        repo = spec["repo"]
        if _phase(b, c, b_dev, c_dev)[0] is None:
            break
        if repo_key(spec) in visited:  # a repository is walked once, at its first rank (#397)
            exclusions.append({"repo": repo, "project": spec.get("project", repo),
                               "reason": "repository listed again (walked at its first rank)"})
            continue
        visited.add(repo_key(spec))
        if norm_name(repo) in used or norm_name(spec.get("project", repo)) in used:
            exclusions.append({"repo": repo, "reason": "repository used in an earlier evaluation"})
            continue
        try:
            history = sorted(LCand.history(cache, repo), key=lambda r: (-r["timestamp"], r["commit"]))
            compiled = compiled_files(cache, repo)
        except (FileNotFoundError, RuntimeError) as exc:
            exclusions.append({"repo": repo, "reason": f"not in --ext-cache ({exc})"[:300]})
            continue
        if compiled:
            exclusions.append({"repo": repo, "reason": "not pure Python: " + ", ".join(compiled[:5])})
            continue
        old = [r for r in history if r["timestamp"] < since_ts]
        if old:
            exclusions.append({"repo": repo, "reason": f"commit before {since}", "count": len(old)})
        for row in (r for r in history if r["timestamp"] >= since_ts):
            group, dev = _phase(b, c, b_dev, c_dev)
            if group is None:
                break
            reason = None
            if not row["tests"]:
                reason = "no test file added or changed"
            elif not row["code"] or not _size_ok(row, B_SIZE):
                reason = f"implementation change below {B_SIZE[0]} lines and {B_SIZE[1]} code files"
            elif group == "C" and not _size_ok(row, C_SIZE):
                reason = (f"below C size rule ({C_SIZE[0]} lines or {C_SIZE[1]} files) "
                          + ("for a C development task" if dev else "after B was filled"))
            elif group == "B" and per_b[repo] >= B_CAP:
                reason = f"repository cap (B: {B_CAP})"
            elif group == "C" and per_c[repo] >= C_CAP:
                reason = f"repository cap (C: {C_CAP})"
            elif repo in slow:
                reason = (f"repository's pytest suite does not run offline within {SUITE_TIMEOUT // 60} minutes "
                          f"(timed out on the parent of {slow[repo][:12]}; a repository condition, #424)")
            if not reason:
                try:
                    reason = test_changes(cache, repo, row["commit"])
                except RuntimeError as exc:
                    reason = f"cannot read the commit's changed files ({exc})"[:300]
            found = None
            if not reason:
                try:
                    found = overlap(python, spec.get("project", repo), cache, repo, row["commit"])
                except Exception as exc:  # a failed check excludes the commit, it never stops the selection
                    found = {"status": "unknown", "error": f"{type(exc).__name__}: {exc}"[:300]}
                scan_errors.update((found or {}).get("scan_errors") or ())
                reason = overlap_reason(spec.get("project", repo), found)
            if reason:
                extra = {k: found[k] for k in ("installed", "examples", "vendored") if found and k in found}
                exclusions.append({"repo": repo, "commit": row["commit"], "reason": reason, **extra,
                                   **({"dev": True} if dev else {})})
                continue
            task = {**row, "id": f"r2-{E.cache_key(repo)}-{row['commit'][:12]}", "project": spec.get("project", repo),
                    "url": spec.get("url"), "group": group, **({"dev": True} if dev else {})}
            if plugins_in_env is None:
                plugins_in_env = ext_plugins(python)  # fails loudly: without it no task would load its plugins
            try:
                # validated, and later run and scored, with these (#415, #424)
                stubs = version_stubs(cache, repo, row["commit"])
                task.update(stubs=stubs, pythonutf8=True,
                            pytest_plugins=pytest_plugins(declared(cache, repo, row["commit"]), plugins_in_env,
                                                          spec.get("project", repo)))
                if stubs:
                    task["stub_version"] = stub_version(cache, repo, row["commit"])
                result = validator(cache, python, task, raw_dir)
            except Exception as exc:
                result = {"valid": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            if (result.get("baseline") or {}).get("rc") is None and \
                    str((result.get("baseline") or {}).get("summary", "")).endswith("timeout"):
                slow.setdefault(repo, row["commit"])
            checked.append({"id": task["id"], "repo": repo, "commit": row["commit"], "group": group,
                            **({"dev": True} if dev else {}),
                            **{k: result.get(k) for k in ("baseline", "parent", "reference", "valid", "error")}})
            if not result.get("valid"):
                why = result.get("error") or _why_invalid(result)
                exclusions.append({"repo": repo, "commit": row["commit"], "reason": why,
                                   **({"dev": True} if dev else {})})
                continue
            task["src_layout"] = src_layout(cache, repo, row["commit"])
            {("B", False): b, ("C", False): c, ("B", True): b_dev, ("C", True): c_dev}[(group, dev)].append(task)
            (per_b if group == "B" else per_c)[repo] += 1
    return {"about": "Round 2 upstream selection (#348); rules fixed in the pre-registration before running",
            "rule": {"since": since, "b_size": B_SIZE, "c_size": C_SIZE, "b_take": B_TAKE, "c_take": C_TAKE,
                     "b_dev_take": B_DEV_TAKE, "c_dev_take": C_DEV_TAKE,
                     "b_cap_per_repo": B_CAP, "c_cap_per_repo": C_CAP, "suite_timeout_s": SUITE_TIMEOUT,
                     "order": "repositories in rank order; commits by time descending, full SHA ascending",
                     "caps": "B and C caps counted separately (pre-registration: at most 6 per repository, C: 4)",
                     "dev": "after C's final tasks, in the same order: the next B-size commits for B, then the next "
                            "C-size commits for C; a group's development tasks count toward that group's repository "
                            "cap; a shortfall is filled by authored development tasks (#371)",
                     "notes": ["commits before the date limit are recorded as one count per repository",
                               "pure Python is checked on the repository HEAD (no .c/.pyx/.rs/... file anywhere)",
                               "pytest plugins are not autoloaded; PYTHONPATH is src/ (if present) then the root; "
                               "a task's src_layout tells the evaluation run to do the same",
                               "commits changing test support files or deleting/renaming tests are excluded",
                               "install-time version files the parent's pyproject.toml declares are written as stubs "
                               "(task `stubs`); validation, run and scoring use PYTHONUTF8=1 (task `pythonutf8`) (#415)",
                               "the 10-minute suite limit is a repository condition (pre-registration section 2): "
                               "after the first candidate whose parent's full suite times out, the repository's "
                               "other candidates are excluded; tasks already taken from it stay (#424)",
                               "pytest plugins: the --ext-python pytest11 entry points of distributions the parent "
                               "declares (pyproject dependencies, test/tests/testing/dev extras and dependency "
                               "groups, setup.cfg, requirements files; not the task's own distribution) plus the "
                               "project's own pytest11 entry points, loaded with PYTEST_PLUGINS (task "
                               "`pytest_plugins`); autoload stays off (#424)",
                               "version stubs report the first digits.digits... of `git describe --tags --abbrev=0` "
                               "on the parent, else 0.0 (task `stub_version`) (#424)"],
                     "installed_overlap": OVERLAP_RULE,
                     "hidden": "commit's added/changed test files: parent fails (rc 1/2), commit passes, "
                               "parent's existing suite passes"},
            "models_called": False, "B": b, "C": c, "b_shortfall": B_TAKE - len(b), "c_shortfall": C_TAKE - len(c),
            "dev": {"B": b_dev, "C": c_dev},
            "dev_shortfall": {"B": B_DEV_TAKE - len(b_dev), "C": C_DEV_TAKE - len(c_dev)},
            "exclusions": exclusions, "checked": checked,
            **({"vendored_scan_errors": sorted(scan_errors)} if scan_errors else {})}


def selection_tasks(selection: dict) -> list[dict]:
    """Final tasks, then development tasks, of a selection file."""
    dev = selection.get("dev") or {}
    return selection.get("B", []) + selection.get("C", []) + dev.get("B", []) + dev.get("C", [])


# ---------------------------------------------------------------- ext-python: own package check

OWN_VERSION = ("import importlib.metadata as m, sys\n"
               "try:\n    print(m.version(sys.argv[1]))\nexcept m.PackageNotFoundError:\n    print('')\n")


def _upload_ts(meta: dict | None, version: str) -> int | None:
    files = ((meta or {}).get("releases") or {}).get(version) or []
    stamps = [f.get("upload_time_iso_8601") or f.get("upload_time") for f in files]
    stamps = [calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) for s in stamps if s]
    return min(stamps) if stamps else None


def own_package(python: str, project: str, commit_ts: int, meta: dict | None = None, run=subprocess.run) -> dict:
    r = run([python, "-c", OWN_VERSION, project], capture_output=True, text=True, encoding="utf-8", timeout=60)
    version = (r.stdout or "").strip()
    if r.returncode != 0:
        return {"project": project, "installed": None, "ok": False, "reason": "could not query --ext-python"}
    if not version:
        return {"project": project, "installed": None, "ok": True}
    released = _upload_ts(meta, version)
    ok = released is not None and released < commit_ts
    return {"project": project, "installed": version, "released": released, "ok": ok,
            **({} if ok else {"reason": "release date unknown" if released is None else "released at or after the commit"})}


def env_check(selection: dict, python: str, meta_dir: Path | None, run=subprocess.run,
              cache: Path | None = None) -> dict:
    """Each task's own distribution by release date; vendored copies of its package (#417) are listed with theirs.
    `cache` (--ext-cache) adds the parent tree's import names to the names a vendored copy is matched by."""
    try:
        r = run([python, "-c", SITE_DIRS], capture_output=True, text=True, encoding="utf-8", timeout=60)
        sites = _site_lines(r.stdout)[0]
        scan = "ok" if r.returncode == 0 else f"unknown: --ext-python query failed (rc={r.returncode})"
    except (OSError, subprocess.SubprocessError) as exc:
        sites, scan = [], f"unknown: {type(exc).__name__}: {exc}"[:300]
    errors = vendored_errors(sites) if sites else []
    if errors and scan == "ok":
        scan = f"errors: {len(errors)} folder(s), wheel(s) or file(s) could not be read (vendored_scan_errors)"
    rows = []
    for task in selection_tasks(selection):
        path = Path(meta_dir) / f"{norm_name(task['project'])}.json" if meta_dir else None
        meta = read_json(path) if path and path.is_file() else None
        names = {norm_name(task["project"])}
        if cache and sites and vendored_inventory(_site_key(sites))[0] and task.get("repo") and task.get("commit"):
            try:
                names |= package_names(Path(cache), task["repo"], task["commit"])
            except (OSError, RuntimeError):
                pass  # the project name alone still matches
        vendored = []
        for c in vendored_copies(sites, names) if sites else []:
            # several versions (one folder, several distributions): the latest date, or unknown when any is missing
            stamps = {v: _upload_ts(meta, v) for v in (c["version"] or "").split(", ") if v}
            missing = sorted(v for v, ts in stamps.items() if ts is None)
            released = max(stamps.values()) if stamps and not missing else None
            vendored.append({"where": c["where"], "version": c["version"], "released": released,
                             "after_commit": None if released is None else released >= task["timestamp"],
                             **({"release_unknown": missing} if missing else {})})
        rows.append({"id": task["id"], **own_package(python, task["project"], task["timestamp"], meta, run),
                     "vendored": vendored})
    return {"rule": "the task's own distribution is absent from --ext-python, or its installed release predates "
                    "the commit; the scan for vendored copies ran and read everything (vendored_scan ok). Vendored "
                    f"copies of the task's package (#417; {VENDOR_RULE}) are listed with their release date "
                    "(after_commit null and release_unknown when a version has no date) and do not change ok: select "
                    "compares their files with each commit (rule.installed_overlap)",
            "vendored_scan": scan, **({"vendored_scan_errors": errors} if errors else {}), "tasks": rows,
            "ok": scan == "ok" and all(r["ok"] for r in rows)}


# ---------------------------------------------------------------- network steps (meta, prepare)

def fetch_meta(snapshot: dict, out: Path, limit: int, get=None) -> list[str]:
    import urllib.request
    get = get or (lambda url: urllib.request.urlopen(url, timeout=30).read())
    out.mkdir(parents=True, exist_ok=True)
    missing = []
    for row in snapshot["rows"][:limit]:
        name = norm_name(row["project"])
        target = out / f"{name}.json"
        if target.is_file():
            continue
        try:
            target.write_bytes(get(f"https://pypi.org/pypi/{name}/json"))
        except Exception:
            missing.append(row["project"])
    return missing


DEP_GROUPS = ("test", "tests", "testing", "dev")  # PEP 735 groups whose requirements prepare also downloads (#415)
RUNNER = ("pytest",)  # always needed to run any suite; pinned like any other kept dependency when it is kept


def _dist(filename: str) -> str:
    return norm_name(re.split(r"-\d", filename, maxsplit=1)[0])


def dependency_groups(config: dict, names=DEP_GROUPS) -> list[str]:
    """Requirement strings of the named [dependency-groups] (PEP 735), with {include-group = ...} resolved."""
    groups = config.get("dependency-groups") or {}
    out, seen = [], set()

    def walk(name):
        if name in seen or name not in groups:
            return
        seen.add(name)
        for item in groups[name] or ():
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("include-group"), str):
                walk(item["include-group"])
    for name in names:
        walk(name)
    return list(dict.fromkeys(out))


def _version_key(version: str):
    m = re.fullmatch(r"(\d+(?:\.\d+)*)(?:\.post(\d+))?", version)
    return (tuple(int(x) for x in m.group(1).split(".")), int(m.group(2) or 0)) if m else None


def pinned_version(meta: dict | None, before_ts: int) -> str | None:
    """The highest final release (no pre-release or dev, not wholly yanked) first uploaded before `before_ts` (#415).
    With before_ts = the selection date limit, it was released before every candidate commit, which is env-check's
    rule. Dates alone do not prove it lacks a task's change (a fix can be released from a maintenance branch before
    its commit lands on main), so select also compares the installed files with each commit (installed_overlap)."""
    best = None
    for version, files in ((meta or {}).get("releases") or {}).items():
        key = _version_key(version)
        live = [f for f in files or () if not f.get("yanked")]
        released = _upload_ts({"releases": {version: live}}, version) if live else None
        if key is not None and released is not None and released < before_ts and (best is None or key > best[0]):
            best = (key, version)
    return best[1] if best else None


def _install(run, python, files, failed: list | None = None) -> bool:
    """All files in one pip call; if that fails, each file on its own, so one unusable file (an sdist that does not
    build, a wheel for another platform) does not leave the rest out. Files that still fail go into `failed`."""
    if not files:
        return True
    def once(batch):
        i = run([python, "-m", "pip", "install", "--quiet", "--no-index", "--no-deps", *map(str, batch)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
        return i.returncode == 0
    if once(files):
        return True
    bad = [Path(f).name for f in files if not once([f])]
    if failed is not None:
        failed += bad
    return not bad


def _download(run, python, target: Path, *reqs) -> bool:
    d = run([python, "-m", "pip", "download", "--quiet", "-d", str(target), *reqs],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return d.returncode == 0


def prepare(repos: list[dict], cache: Path, wheels: Path, python: str, run=subprocess.run,
            meta_dir: Path | None = None, since: str = SINCE) -> dict:
    """Clone each kept repository; download the latest release with test extras, plus the requirements of its
    [dependency-groups] test/tests/testing/dev at the clone's HEAD (#415), and install every wheel except the kept
    packages, so no task's code sits in --ext-python at a version that could hold it. A kept package that another
    repository needs (or the test runner, pytest) is installed at its highest final release uploaded before `since`
    (the selection date limit), with its own dependencies under the same rule (#415): released before every
    candidate commit, env-check's rule; select additionally excludes a commit whose added lines already appear in the
    installed package (installed_overlap). A repository whose suite still lacks a dependency fails its parent
    baseline and is excluded with that reason. The final `pip list` is part of the output. Filled from the list, not
    by hand."""
    import tomllib
    rows = []
    kept = {norm_name(r["project"]) for r in repos}
    needed = {norm_name(r) for r in RUNNER} & kept
    for spec in repos:
        row = {"repo": spec["repo"], "project": spec["project"]}
        try:
            E.fetch(spec["repo"], {"url": spec["url"]}, cache)
            row["cloned"] = True
        except Exception as exc:
            row.update(cloned=False, error=str(exc)[:300])
        target = wheels / norm_name(spec["project"])
        extras = ",".join(TEST_EXTRAS)
        row["downloaded"] = _download(run, python, target, f"{spec['project']}[{extras}]")
        groups = []
        try:
            bare = LCand.bare_path(cache, spec["repo"])
            groups = dependency_groups(tomllib.loads(E._git(None, f"--git-dir={bare}", "show", "HEAD:pyproject.toml")))
        except (FileNotFoundError, RuntimeError, tomllib.TOMLDecodeError):
            pass
        if groups:
            row["dependency_groups"] = groups
            row["groups_failed"] = [r for r in groups if not _download(run, python, target, r)]
        files = sorted(p for p in target.glob("*") if p.is_file()) if target.is_dir() else []
        deps = [p for p in files if _dist(p.name) not in kept]
        row["skipped_kept_packages"] = sorted({_dist(p.name) for p in files} & kept)
        needed |= set(row["skipped_kept_packages"]) - {norm_name(spec["project"])}
        if deps:
            failed = []
            row["installed"] = _install(run, python, deps, failed)
            if failed:
                row["install_failed"] = failed
        rows.append(row)
    if needed and meta_dir is None:
        raise ValueError("kept packages are needed as dependencies (" + ", ".join(sorted(needed)) + "); pass "
                         "--pypi-meta (the meta step's folder) to pin them")
    pins, todo, before = {}, sorted(needed), _since_ts(since)
    while todo:  # kept dependencies of the pinned packages are pinned the same way
        name = todo.pop(0)
        path = Path(meta_dir) / f"{name}.json"
        version = pinned_version(read_json(path) if path.is_file() else None, before)
        pin = pins[name] = {"version": version}
        if version is None:
            pin["reason"] = f"no final release before {since} in the PyPI metadata"
            continue
        target = wheels / "_pins" / f"{name}-{version}"
        pin["downloaded"] = _download(run, python, target, f"{name}=={version}")
        files = sorted(p for p in target.glob("*") if p.is_file()) if target.is_dir() else []
        own = [p for p in files if _dist(p.name) == name]
        other_kept = sorted({_dist(p.name) for p in files} & kept - {name})
        todo += [k for k in other_kept if k not in pins and k not in todo]
        failed = []
        pin["installed"] = _install(run, python, own + [p for p in files if _dist(p.name) not in kept], failed)
        if failed:
            pin["install_failed"] = failed
    # what --ext-python holds at the end, frozen with the selection (#415 review)
    f = run([python, "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        frozen = sorted(({"name": d["name"], "version": d["version"]} for d in json.loads(f.stdout or "")),
                        key=lambda d: norm_name(d["name"]))
    except (ValueError, TypeError, KeyError):
        frozen = None
    return {"rule": f"kept packages never installed at their latest release; a kept dependency (and "
                    f"{', '.join(RUNNER)}) at its highest final release uploaded before {since}, kept dependencies of "
                    f"a pin pinned the same way; test extras of each project's latest release plus the "
                    f"[dependency-groups] {'/'.join(DEP_GROUPS)} of the clone's HEAD pyproject.toml",
            "repos": rows, "pins": pins, "pip_list": frozen}


# ---------------------------------------------------------------- manifest

def file_digest(path: Path) -> str:
    data = path.read_bytes()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def manifest(paths: list[Path], root: Path) -> dict:
    files = []
    for p in paths:
        p = Path(p)
        found = (sorted(x for x in p.rglob("*") if x.is_file() and not {".git", "__pycache__"} & set(x.parts))
                 if p.is_dir() else [p])
        for f in found:
            files.append({"path": f.resolve().relative_to(root.resolve()).as_posix(), "sha256": file_digest(f)})
    files.sort(key=lambda r: r["path"])
    canon = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"normalization": "text files hashed with CRLF -> LF; binary (NUL byte) as is",
            "files": files, "sha256": hashlib.sha256(canon).hexdigest()}


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("meta"); s.add_argument("--snapshot", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True); s.add_argument("--limit", type=int, default=300)
    s = sub.add_parser("repos"); s.add_argument("--snapshot", type=Path, required=True)
    s.add_argument("--pypi-meta", type=Path, required=True); s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("prepare"); s.add_argument("--repos-json", type=Path, required=True)
    s.add_argument("--ext-cache", type=Path, required=True); s.add_argument("--wheels", type=Path, required=True)
    s.add_argument("--ext-python", required=True); s.add_argument("--out", type=Path, required=True)
    s.add_argument("--pypi-meta", type=Path, help="the meta step's folder: release dates for pinning kept dependencies")
    s = sub.add_parser("select"); s.add_argument("--repos-json", type=Path, required=True)
    s.add_argument("--ext-cache", type=Path, required=True); s.add_argument("--ext-python", required=True)
    s.add_argument("--out", type=Path, required=True); s.add_argument("--raw-dir", type=Path)
    s.add_argument("--prepare-json", type=Path, help="prepare's output; its SHA-256 is recorded in the selection")
    s = sub.add_parser("authored"); s.add_argument("task_dirs", type=Path, nargs="+")
    s.add_argument("--python", default=sys.executable); s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("brief"); s.add_argument("--task-json", type=Path, required=True)
    s.add_argument("--hidden-dir", type=Path, required=True)
    s = sub.add_parser("leak"); s.add_argument("--tasks", type=Path, required=True)
    s.add_argument("--exclude", type=Path, nargs="*", default=[]); s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("env-check"); s.add_argument("--selection", type=Path, required=True)
    s.add_argument("--ext-python", required=True); s.add_argument("--pypi-meta", type=Path)
    s.add_argument("--ext-cache", type=Path, help="clones from prepare: also match vendored copies by import name")
    s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("manifest"); s.add_argument("paths", type=Path, nargs="+")
    s.add_argument("--root", type=Path, default=ROOT); s.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    if a.cmd == "meta":
        missing = fetch_meta(read_json(a.snapshot), a.out, a.limit)
        print(f"metadata missing for {len(missing)} project(s)")
        return 0
    if a.cmd == "repos":
        data = repo_list(read_json(a.snapshot), a.pypi_meta, corpus(exclude=[a.out])["repos"])
        write_json(a.out, data)
        print(f"kept {len(data['kept'])}, excluded {len(data['excluded'])}")
        return 0
    if a.cmd == "prepare":
        try:
            data = prepare(read_json(a.repos_json)["kept"], a.ext_cache, a.wheels, a.ext_python, meta_dir=a.pypi_meta)
        except ValueError as exc:
            ap.error(str(exc))
        write_json(a.out, data)
        unpinned = sorted(k for k, v in data["pins"].items() if not v.get("installed"))
        print(f"prepared {len(data['repos'])} repositories; pinned {len(data['pins'])} kept dependencies"
              + (f"; not installed: {', '.join(unpinned)}" if unpinned else ""))
        if data["pip_list"] is None:
            print("error: `pip list` of --ext-python could not be read; the environment is not frozen")
            return 1
        return 0
    if a.cmd == "select":
        if not a.ext_cache.is_dir():
            ap.error("--ext-cache must exist (run prepare first)")
        data = select_upstream(a.ext_cache, read_json(a.repos_json)["kept"], a.ext_python,
                               corpus(exclude=[a.out, a.repos_json])["repos"],
                               raw_dir=a.raw_dir)
        try:
            version = subprocess.run([a.ext_python, "-c", "import sys; print(sys.version)"], capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            version = ""
        data["environment"] = {"ext_python_version": (version or "").strip() or None,
                               "prepare_json_sha256": hashlib.sha256(a.prepare_json.read_bytes()).hexdigest()
                               if a.prepare_json else None}
        write_json(a.out, data)
        dev, short = data["dev"], data["dev_shortfall"]
        print(f"B {len(data['B'])}/{B_TAKE}, C {len(data['C'])}/{C_TAKE}; "
              f"dev B {len(dev['B'])}/{B_DEV_TAKE}, C {len(dev['C'])}/{C_DEV_TAKE}")
        if short["B"] or short["C"]:
            print(f"development shortfall: author {short['B']} B and {short['C']} C development task(s) before "
                  "any final authored task (pre-registration, section 2)")
        return 0 if not data["b_shortfall"] and not data["c_shortfall"] else 1
    if a.cmd == "authored":
        rows = [check_authored(d, a.python) for d in a.task_dirs]
        write_json(a.out, {"models_called": False, "tasks": rows, "valid": all(r["valid"] for r in rows)})
        return 0 if all(r["valid"] for r in rows) else 1
    if a.cmd == "brief":
        task = read_json(a.task_json)
        hidden = {rel: (a.hidden_dir / rel).read_text(encoding="utf-8") for rel in task["hidden_tests"]}
        result = brief_checks(task["brief"], hidden, task.get("trace", []))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["trace_complete"] and not result["literal_overlap"] else 1
    if a.cmd == "leak":
        source = read_json(a.tasks)
        tasks = (source.get("tasks") or selection_tasks(source)) if isinstance(source, dict) else source
        data = leak_check(tasks, corpus(exclude=[a.tasks, a.out, *a.exclude]))
        write_json(a.out, data)
        return 0 if data["clean"] else 1
    if a.cmd == "env-check":
        data = env_check(read_json(a.selection), a.ext_python, a.pypi_meta, cache=a.ext_cache)
        write_json(a.out, data)
        return 0 if data["ok"] else 1
    data = manifest(a.paths, a.root)
    write_json(a.out, data)
    print(data["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
