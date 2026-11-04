"""Offline deterministic history scan; never calls a model."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import ext_repo as E
import tasks_holdout

REPOS = ("more-itertools", "boltons", "pluggy", "humanize", "itsdangerous")
RULE = "implementation .py only, outside tests/test/testing/docs/doc; exclude .pyi and holdout commits; code_lines >= 60 OR code_files >= 3"


def is_test(name: str) -> bool:
    p = Path(name)
    return bool(set(p.parts[:-1]) & {"tests", "test", "testing"}) or p.name == "conftest.py" or p.name.startswith("test_")


def is_code(name: str) -> bool:
    return name.endswith(".py") and not is_test(name) and not set(Path(name).parts[:-1]) & {"docs", "doc"}


def bare_path(cache: Path, repo: str) -> Path:
    for path in (cache / (repo + ".git"), cache / repo):
        if (path / "HEAD").is_file():
            return path
        if (path / ".git").is_dir():
            return path / ".git"
    raise FileNotFoundError(f"cache has no repository {repo}")


def candidates(cache: Path, repo: str) -> list[dict]:
    bare = bare_path(cache, repo)
    log = E._git(None, f"--git-dir={bare}", "log", "--no-merges", "--min-parents=1",
                 "--format=%H%x09%ct%x09%s", "--numstat")
    rows, current = [], None
    for line in log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        if len(parts[0]) == 40:
            current = {"repo": repo, "commit": parts[0], "timestamp": int(parts[1]),
                       "subject": parts[2], "size": 0, "code_lines": 0, "code": [], "non_test_files": [], "tests": []}
            rows.append(current)
        elif current and parts[0].isdigit():
            name = parts[2]
            test_file = is_test(name)
            if test_file and name.endswith(".py") and Path(name).name.startswith("test"):
                current["tests"].append(name)
            elif not test_file:
                current["size"] += int(parts[0]) + int(parts[1])
                current["non_test_files"].append(name)
                if is_code(name):
                    current["code"].append(name)
                    current["code_lines"] += int(parts[0]) + int(parts[1])
    used = [t["commit"] for t in tasks_holdout.T + tasks_holdout.DROPPED if t.get("repo") == repo]
    return sorted([r for r in rows if r["tests"] and r["code"] and
                   (r["code_lines"] >= 60 or len(r["code"]) >= 3) and
                   not any(r["commit"].startswith(sha) for sha in used)],
                  key=lambda r: (-r["timestamp"], r["commit"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ext-cache", type=Path, required=True)
    p.add_argument("--repo", default="more-itertools")
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args()
    print(json.dumps(candidates(a.ext_cache, a.repo)[:a.limit], indent=2))
