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
    env-check --ext-python has no task's own package released at or after the task's commit
    manifest  SHA-256 of every file (text normalized to LF), for the pre-registration change log

Reused: long_candidates.history (commit scan, code/test split), long_environment.validate_task (native checkout,
parent full suite, hidden tests on parent and commit), long_environment.hidden (pytest run), ext_repo.fetch.
"""
from __future__ import annotations

import argparse
import ast
import calendar
import difflib
import hashlib
import importlib.util
import json
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
    with tempfile.TemporaryDirectory(prefix="r2-authored-") as tmp:
        root = Path(tmp)
        existing = run(_tree_with(task_dir / "start", root / "existing", {}), [], python)
        parent = run(_tree_with(task_dir / "start", root / "start", hidden), task["hidden_tests"], python)
        reference = run(_tree_with(task_dir / "reference", root / "reference", hidden), task["hidden_tests"], python)
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
    return {"id": task["id"], "existing": existing, "start": parent, "reference": reference, **briefs,
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
                entry.update(repo=norm_name(url), url=url, license=lic)
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
    previous, LE.SRC_ON_PATH = LE.SRC_ON_PATH, True  # src-layout packages import from src/, as long_check does
    try:
        return LE.validate_task(cache, python, task, raw_dir, SUITE_TIMEOUT)
    finally:
        LE.SRC_ON_PATH = previous


def src_layout(cache: Path, repo: str, sha: str) -> bool:
    """The parent tree has a top-level src/ folder; the evaluation run must then put src/ on PYTHONPATH too."""
    bare = LCand.bare_path(cache, repo)
    return bool(E._git(None, f"--git-dir={bare}", "ls-tree", "-d", "--name-only", f"{sha}^", "src").strip())


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
                    raw_dir: Path | None = None, validator=None) -> dict:
    validator = validator or _validate
    since_ts = _since_ts(since)
    b, c, b_dev, c_dev, exclusions, checked = [], [], [], [], [], []
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
            if not reason:
                try:
                    reason = test_changes(cache, repo, row["commit"])
                except RuntimeError as exc:
                    reason = f"cannot read the commit's changed files ({exc})"[:300]
            if reason:
                exclusions.append({"repo": repo, "commit": row["commit"], "reason": reason,
                                   **({"dev": True} if dev else {})})
                continue
            task = {**row, "id": f"r2-{repo}-{row['commit'][:12]}", "project": spec.get("project", repo),
                    "url": spec.get("url"), "group": group, **({"dev": True} if dev else {})}
            try:
                result = validator(cache, python, task, raw_dir)
            except Exception as exc:
                result = {"valid": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
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
                               "commits changing test support files or deleting/renaming tests are excluded"],
                     "hidden": "commit's added/changed test files: parent fails (rc 1/2), commit passes, "
                               "parent's existing suite passes"},
            "models_called": False, "B": b, "C": c, "b_shortfall": B_TAKE - len(b), "c_shortfall": C_TAKE - len(c),
            "dev": {"B": b_dev, "C": c_dev},
            "dev_shortfall": {"B": B_DEV_TAKE - len(b_dev), "C": C_DEV_TAKE - len(c_dev)},
            "exclusions": exclusions, "checked": checked}


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


def env_check(selection: dict, python: str, meta_dir: Path | None, run=subprocess.run) -> dict:
    rows = []
    for task in selection_tasks(selection):
        path = Path(meta_dir) / f"{norm_name(task['project'])}.json" if meta_dir else None
        meta = read_json(path) if path and path.is_file() else None
        rows.append({"id": task["id"], **own_package(python, task["project"], task["timestamp"], meta, run)})
    return {"rule": "the task's own distribution is absent from --ext-python, or its installed release predates "
                    "the commit", "tasks": rows, "ok": all(r["ok"] for r in rows)}


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


def prepare(repos: list[dict], cache: Path, wheels: Path, python: str, run=subprocess.run) -> list[dict]:
    """Clone each kept repository; download the latest release with test extras and install every wheel except
    the kept packages themselves (its own and every other kept one), so no task's code sits in --ext-python.
    A repository whose suite then lacks a dependency fails its parent baseline and is excluded with that reason.
    Filled from the list, not by hand."""
    rows = []
    kept = {norm_name(r["project"]) for r in repos}
    for spec in repos:
        row = {"repo": spec["repo"], "project": spec["project"]}
        try:
            E.fetch(spec["repo"], {"url": spec["url"]}, cache)
            row["cloned"] = True
        except Exception as exc:
            row.update(cloned=False, error=str(exc)[:300])
        target = wheels / norm_name(spec["project"])
        extras = ",".join(TEST_EXTRAS)
        d = run([python, "-m", "pip", "download", "--quiet", "-d", str(target), f"{spec['project']}[{extras}]"],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
        row["downloaded"] = d.returncode == 0
        files = sorted(p for p in target.glob("*") if p.is_file()) if target.is_dir() else []
        deps = [str(p) for p in files if norm_name(re.split(r"-\d", p.name, maxsplit=1)[0]) not in kept]
        row["skipped_kept_packages"] = sorted({norm_name(re.split(r"-\d", p.name, maxsplit=1)[0]) for p in files} & kept)
        if deps:
            i = run([python, "-m", "pip", "install", "--quiet", "--no-index", "--no-deps", *deps],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            row["installed"] = i.returncode == 0
        rows.append(row)
    return rows


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
    s = sub.add_parser("select"); s.add_argument("--repos-json", type=Path, required=True)
    s.add_argument("--ext-cache", type=Path, required=True); s.add_argument("--ext-python", required=True)
    s.add_argument("--out", type=Path, required=True); s.add_argument("--raw-dir", type=Path)
    s = sub.add_parser("authored"); s.add_argument("task_dirs", type=Path, nargs="+")
    s.add_argument("--python", default=sys.executable); s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("brief"); s.add_argument("--task-json", type=Path, required=True)
    s.add_argument("--hidden-dir", type=Path, required=True)
    s = sub.add_parser("leak"); s.add_argument("--tasks", type=Path, required=True)
    s.add_argument("--exclude", type=Path, nargs="*", default=[]); s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("env-check"); s.add_argument("--selection", type=Path, required=True)
    s.add_argument("--ext-python", required=True); s.add_argument("--pypi-meta", type=Path)
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
        rows = prepare(read_json(a.repos_json)["kept"], a.ext_cache, a.wheels, a.ext_python)
        write_json(a.out, rows)
        return 0
    if a.cmd == "select":
        if not a.ext_cache.is_dir():
            ap.error("--ext-cache must exist (run prepare first)")
        data = select_upstream(a.ext_cache, read_json(a.repos_json)["kept"], a.ext_python,
                               corpus(exclude=[a.out, a.repos_json])["repos"],
                               raw_dir=a.raw_dir)
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
        data = env_check(read_json(a.selection), a.ext_python, a.pypi_meta)
        write_json(a.out, data)
        return 0 if data["ok"] else 1
    data = manifest(a.paths, a.root)
    write_json(a.out, data)
    print(data["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
