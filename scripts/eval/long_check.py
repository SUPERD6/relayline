"""Validate long-session candidates offline (pytest only, no agent CLI)."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import ext_repo as E
from long_candidates import REPOS, RULE, bare_path, candidates

OLD_RULE = {"rule": "non-test lines >= 80 OR non-test files >= 3, including docs and .pyi",
            "status": "void", "reason": "Admitted small implementation changes through documentation/type-stub file counts; replaced by lead decision before any model evaluation."}


def normalize_output(text: str, work: Path | None = None) -> str:
    if work:
        for path in (str(work).replace("\\", "\\\\"), str(work), work.as_posix()):
            text = text.replace(path, "<tree>")
    text = re.sub(r"[A-Za-z]:[\\/]+Users[\\/]+[^\s'\"()]+", "<private-path>", text)
    text = re.sub(r"pytest-of-[^\\/\s'\"()]+", "pytest-of-user", text)
    return re.sub(r"0x[0-9A-Fa-f]+", "<address>", text)


def git(bare, *args, data=False):
    return E._git(None, f"--git-dir={bare}", *args, data=data)


def material(cache: Path, task: dict) -> dict:
    bare = bare_path(cache, task["repo"])
    sha = task["commit"]
    if len(sha) != 40 or git(bare, "rev-parse", sha).strip() != sha:
        raise ValueError("task must pin a full commit SHA")
    return {"tar": git(bare, "archive", f"{sha}^", data=True),
            "reference": git(bare, "archive", sha, data=True),
            "tests": {p: git(bare, "show", f"{sha}:{p}", data=True) for p in task["tests"]}}


def check_tree(tree: bytes, hidden: dict, tests: list, python: str, work: Path, raw: Path | None = None) -> dict:
    work.mkdir(parents=True)
    E.extract(tree, work)
    for rel, body in hidden.items():
        target = work / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    env = {**os.environ, "PYTHONPATH": str(work / "src" if (work / "src").is_dir() else work), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "PIP_NO_INDEX": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        r = subprocess.run([python, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:cacheprovider", *tests],
                           cwd=work, env=env, capture_output=True, timeout=120)
        out = normalize_output((r.stdout + r.stderr).decode("utf-8", "replace"), work)
        result = {"rc": r.returncode, "summary": out.strip().splitlines()[-1] if out.strip() else "empty",
                  "errors": [line for line in out.splitlines() if line.startswith(("E   ", "FAILED "))][:8]}
        if raw:
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(out, encoding="utf-8", newline="")
            result["raw"] = {"file": raw.name, "bytes": len(out.encode("utf-8")),
                             "sha256": hashlib.sha256(out.encode("utf-8")).hexdigest()}
        return result
    except subprocess.TimeoutExpired:
        return {"rc": None, "summary": "timeout"}


def runtime(python: str) -> dict:
    def version(args):
        r = subprocess.run([python, *args], capture_output=True, text=True, encoding="utf-8", timeout=30)
        return r.stdout.strip() if r.returncode == 0 else "Unknown"
    return {"python": version(["--version"]), "pytest": version(["-m", "pytest", "--version"]), "models_called": False}


def frozen_check(cache: Path, python: str, raw_dir: Path | None = None) -> dict:
    from tasks_long import T
    rows = []
    for task in T:
        m = material(cache, task)
        with tempfile.TemporaryDirectory(prefix="p4-check-") as tmp:
            parent = check_tree(m["tar"], m["tests"], task["tests"], python, Path(tmp) / "parent",
                                raw_dir / (task["commit"] + "-parent.txt") if raw_dir else None)
            reference = check_tree(m["reference"], m["tests"], task["tests"], python, Path(tmp) / "reference",
                                   raw_dir / (task["commit"] + "-reference.txt") if raw_dir else None)
        rows.append({"id": task["id"], "commit": task["commit"], "parent": parent, "reference": reference,
                     "valid": parent["rc"] in (1, 2) and reference["rc"] == 0})
        print(f"{task['id']} parent={parent['rc']} reference={reference['rc']}", flush=True)
    return {"runtime": runtime(python), "checked": rows, "valid": all(r["valid"] for r in rows)}


def validate(cache: Path, python: str, count=12, repos=REPOS, limit=0, commit="", raw_dir=None) -> dict:
    accepted, checked, qualified = [], [], []
    catalog = {repo: candidates(cache, repo) for repo in repos}
    report = {"selection": RULE, "old_rule": OLD_RULE, "repository_order": list(repos),
              "ordering": "within repository: commit timestamp descending, full SHA ascending; first passing full groups of four",
              "history_scope": "all locally available single-parent commits, no date limit, no network fetch",
              "candidate_counts": {repo: len(ts) for repo, ts in catalog.items()},
              "runtime": runtime(python), "accepted": accepted, "qualified": qualified, "checked": checked,
              "raw_directory": str(raw_dir.as_posix()) if raw_dir else None,
              "target_count": count, "complete": False}
    # Repository priority and chronological order are fixed before any model run.
    for repo in repos:
        repo_qualified = []
        for t in (catalog[repo][:limit] if limit else catalog[repo]):
            if commit and not t["commit"].startswith(commit):
                continue
            m = material(cache, t)
            with tempfile.TemporaryDirectory(prefix="p4-check-") as tmp:
                root = Path(tmp)
                parent = check_tree(m["tar"], m["tests"], t["tests"], python, root / "parent",
                                    raw_dir / (t["commit"] + "-parent.txt") if raw_dir else None)
                reference = check_tree(m["reference"], m["tests"], t["tests"], python, root / "reference",
                                       raw_dir / (t["commit"] + "-reference.txt") if raw_dir else None)
            valid = parent["rc"] in (1, 2) and reference["rc"] == 0
            row = {**t, "parent": parent, "reference": reference, "valid": valid}
            checked.append(row)
            print(f"{repo} {t['commit'][:10]} code={t['code_lines']}/{len(t['code'])} parent={parent['rc']} reference={reference['rc']} valid={valid}", flush=True)
            if valid:
                qualified.append(row)
                repo_qualified.append(row)
                if len(repo_qualified) % 4 == 0:
                    accepted.extend(repo_qualified[-4:])
            if len(accepted) >= count:
                report["complete"] = True
                report["incomplete_episode_commits"] = [r["commit"] for r in qualified if r not in accepted]
                return report
    report["shortfall"] = count - len(accepted)
    report["incomplete_episode_commits"] = [r["commit"] for r in qualified if r not in accepted]
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ext-cache", type=Path, required=True)
    p.add_argument("--ext-python", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repos", default=",".join(REPOS))
    p.add_argument("--limit", type=int, default=0, help="diagnostic only; not the selection run")
    p.add_argument("--commit", default="", help="diagnostic only")
    p.add_argument("--select", action="store_true", help="reproduce candidate selection; default validates the frozen 12 tasks")
    p.add_argument("--raw-dir", type=Path, help="keep full normalized pytest output plus hashes")
    a = p.parse_args()
    frozen_manifest = Path(__file__).with_name("long_selection.json").resolve()
    if a.output.resolve() == frozen_manifest and not a.select:
        p.error("validation output must not overwrite the frozen selection manifest")
    result = (validate(a.ext_cache, a.ext_python, repos=tuple(a.repos.split(",")), limit=a.limit, commit=a.commit, raw_dir=a.raw_dir)
              if a.select else frozen_check(a.ext_cache, a.ext_python, a.raw_dir))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="")
    raise SystemExit(0 if (len(result.get("accepted", [])) >= 12 if a.select else result["valid"]) else 1)
