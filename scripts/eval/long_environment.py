"""Opt-in long-session checkout and baseline contract; no model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

import ext_repo as E
import long_check as LC

POLICY = "native-git-checkout-v2"
CHECK = "-m pytest -q -o addopts="


def checkout(repo: Path) -> dict:
    """Re-checkout tracked bytes as Git would on this platform, respecting attributes."""
    if os.name == "nt":
        E._git(repo, "config", "core.autocrlf", "true")
        # --force alone skips stat-clean files left by the LF archive snapshot.
        # An empty export prefix guarantees smudge conversion, honoring attributes.
        with tempfile.TemporaryDirectory(prefix="p5-checkout-") as tmp:
            prefix = Path(tmp).as_posix()+"/"
            E._git(repo, "-c", "core.autocrlf=true", "checkout-index", "--all", "--force", "--prefix="+prefix)
            shutil.copytree(tmp, repo, dirs_exist_ok=True)
    return checkout_evidence(repo)


def checkout_evidence(repo: Path) -> dict:
    """Git reports index/worktree EOL counts; do not infer bytes from config alone."""
    counts = {}
    for line in E._git(repo, "ls-files", "--eol").splitlines():
        fields = line.split()
        if len(fields) >= 2:
            key = fields[0]+" "+fields[1]
            counts[key] = counts.get(key, 0)+1
    return {"policy": POLICY, "autocrlf": "true" if os.name == "nt" else "not-overridden",
            "attributes": "respected", "eol_counts": counts}


def build(tree: bytes, repo: Path):
    E.repo_from_tar(tree, {"stubs": []}, repo)
    return checkout(repo)


def command(python: str) -> str:
    path = str(Path(python).resolve())
    quoted = subprocess.list2cmdline([path]) if os.name == "nt" else __import__('shlex').quote(path)
    return quoted + " " + CHECK


def environment(repo: Path, python: str, tmp: Path):
    tmp.mkdir(parents=True, exist_ok=True)
    return {**os.environ, "PATH": str(Path(python).resolve().parent) + os.pathsep + os.environ.get("PATH", ""),
            "PYTHONPATH": str(repo), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_NO_INDEX": "1", **{k: str(tmp) for k in ("TMP", "TEMP", "TMPDIR")}}


def baseline(repo: Path, python: str, tmp: Path, raw: Path | None = None):
    """Exactly the unit acceptance command, original parent tests, no hidden test injection."""
    env = environment(repo, python, tmp)
    cmd = command(python)
    try:
        r = subprocess.run(cmd, shell=True, cwd=repo, env=env, capture_output=True, timeout=180)
        output = LC.normalize_output((r.stdout + r.stderr).decode("utf-8", "replace"), repo)
        result = {"rc": r.returncode, "summary": output.strip().splitlines()[-1] if output.strip() else "empty",
                  "errors": [s for s in output.splitlines() if s.startswith(("E   ", "FAILED ", "ERROR "))][:12]}
    except subprocess.TimeoutExpired:
        output = "baseline timeout"
        result = {"rc": None, "summary": output}
    result.update(command="PYTHON " + CHECK, checkout=POLICY, python=LC.runtime(python),
                  cwd="<unit.repo>", tmp="<unit.repo>/.ccx-eval-tmp-acceptance",
                  checkout_evidence=checkout_evidence(repo))
    if raw:
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(output, encoding="utf-8", newline="")
        result["raw"] = {"file": raw.name, "sha256": hashlib.sha256(output.encode()).hexdigest()}
    return result


def validate_task(cache: Path, python: str, task: dict, raw_dir: Path | None = None):
    m = LC.material(cache, task)
    with tempfile.TemporaryDirectory(prefix="p5-native-") as tmp:
        root = Path(tmp)
        repo = root / "repo"
        policy = build(m["tar"], repo)
        stem = task["commit"]
        base = baseline(repo, python, repo / ".ccx-eval-tmp-acceptance",
                        raw_dir / (stem + "-baseline.txt") if raw_dir else None)
        # Remove all generated baseline state; hidden validation uses fresh identical checkouts.
        checks = {}
        if base["rc"] == 0:
            for name, tree in (("parent", m["tar"]), ("reference", m["reference"])):
                target = root/name
                build(tree, target)
                # Hidden tests are evaluator-only and receive the same native checkout policy.
                for rel, body in m["tests"].items():
                    path = target/rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                E._git(target, "add", "-A")
                if E._git(target, "diff", "--cached", "--name-only").strip():
                    E._git(target, "commit", "-q", "--no-verify", "-m", "hidden snapshot")
                checkout(target)
                checks[name] = hidden(target, task["tests"], python,
                                      raw_dir/(stem+f"-{name}.txt") if raw_dir else None)
        else:
            checks = {k: {"rc": None, "summary": "not run: original parent baseline failed"}
                      for k in ("parent", "reference")}
    valid = base["rc"] == 0 and checks["parent"]["rc"] in (1, 2) and checks["reference"]["rc"] == 0
    return {"baseline": base, **checks, "valid": valid, "checkout": policy}


def hidden(repo, tests, python, raw=None):
    try:
        r = subprocess.run([python, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:cacheprovider", *tests],
                           cwd=repo, env=environment(repo, python, repo/".ccx-eval-tmp-hidden"),
                           capture_output=True, timeout=180)
        output = LC.normalize_output((r.stdout+r.stderr).decode("utf-8", "replace"), repo)
        result = {"rc": r.returncode, "summary": output.strip().splitlines()[-1] if output.strip() else "empty",
                  "errors": [s for s in output.splitlines() if s.startswith(("E   ", "FAILED ", "ERROR "))][:12]}
    except subprocess.TimeoutExpired:
        output = "hidden timeout"
        result = {"rc": None, "summary": output}
    if raw:
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(output, encoding="utf-8", newline="")
        result["raw"] = {"file": raw.name, "sha256": hashlib.sha256(output.encode()).hexdigest()}
    return result


def audit(tasks, cache, python, raw_dir=None):
    rows = []
    for task in tasks:
        result = validate_task(cache, python, task, raw_dir)
        rows.append({**task, **result})
        print(f"{task['id']} baseline={result['baseline']['rc']} valid={result['valid']}", flush=True)
    return {"checkout_policy": POLICY, "rule": "original parent full acceptance check must exit 0, then parent hidden fails/reference hidden passes; no model outcomes",
            "checked": rows, "eligible": [r["commit"] for r in rows if r["valid"]],
            "excluded": [r["commit"] for r in rows if not r["valid"]]}


def selection_from_audit(previous, result):
    """Exclude without filling from a new pool; keep the fixed four-task episode rule."""
    checked = result["checked"]
    qualified = [t for t in checked if t.get("valid") is True and t.get("baseline", {}).get("rc") == 0]
    accepted = []
    for repo in previous.get("repository_order", []):
        group = [t for t in qualified if t["repo"] == repo]
        accepted.extend(group[:len(group)//4*4])
    return {"about": "P5 revalidated before any model run; exclude failed baselines/reference checks without replacing from another pool",
            "selection": previous["selection"], "repository_order": previous["repository_order"],
            "ordering": previous["ordering"], "checkout_policy": POLICY,
            "baseline_rule": result["rule"], "target_count": 8, "accepted": accepted,
            "qualified": qualified, "checked": checked, "audited_tasks": checked,
            "excluded_commits": previous.get("excluded_commits", []),
            "baseline_exclusions": [t["commit"] for t in checked if t["baseline"]["rc"] != 0],
            "grading_exclusions": [t["commit"] for t in checked if t["baseline"]["rc"] == 0 and not t["valid"]],
            "incomplete_episode_commits": [t["commit"] for t in qualified if t not in accepted],
            "complete": len(accepted) == 8, "shortfall": 8-len(accepted),
            "status": "Pass" if len(accepted) == 8 else "Unknown", "models_called": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--ext-cache", type=Path, required=True)
    p.add_argument("--ext-python", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path)
    a = p.parse_args(argv)
    if a.output.resolve() == a.manifest.resolve():
        p.error("audit output must not overwrite the selection manifest")
    source = json.loads(a.manifest.read_text(encoding="utf-8"))
    frozen = source["accepted"] or source.get("audited_tasks", [])
    if not frozen:
        p.error("no frozen or previously audited tasks; empty validation is not Pass")
    tasks = [{**t, "id": t.get("id", "p5-long-"+t["commit"][:12])} for t in frozen]
    result = audit(tasks, a.ext_cache, a.ext_python, a.raw_dir)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8", newline="")
    return 0 if not result["excluded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
