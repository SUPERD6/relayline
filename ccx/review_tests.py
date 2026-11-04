"""Experimental task-derived test review. Evidence lives outside the working tree.

The reviewer writes unittest files, not a claimed test result. ccx executes those
files and asks the reviewer to check scope and test correctness before blocking.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def mode(rc: dict) -> str:
    return "tests" if rc.get("mode") == "tests" else "read"


def trigger(rc: dict) -> str:
    # mode historically meant auto/on/off. Preserve all three as aliases.
    value = rc.get("mode", "read")
    return value if value in ("auto", "on", "off") else "auto"


def unknown(cause: str, **extra) -> dict:
    return {"verdict": "unknown", "issues": [], "review_mode": "tests",
            "tests_written": 0, "tests_run": 0, "tests_failed": 0,
            "unknown_reasons": [cause], **extra}


def task_text(p, req, record: dict) -> str:
    from .review import task_for_review
    # Additive raw-task fields used by callers; never substitute shared context.
    for text in (record.get("user_task"), getattr(req, "user_task", None)):
        if isinstance(text, str) and text.strip():
            return text
    rid = req.resume_run
    seen = set()
    while rid and rid not in seen:
        seen.add(rid)
        try:
            prev = json.loads((p.runs / rid / "run.json").read_text(encoding="utf-8"))
            if isinstance(prev.get("user_task"), str) and prev["user_task"].strip():
                return prev["user_task"]
            rid = prev.get("resumed_from")
        except (OSError, ValueError):
            break
    return task_for_review(p, req)


def copy_source(cwd: Path, dest: Path) -> None:
    """Tracked source + new source only: no builder tests, history or ccx data."""
    from .review import _git, is_test_file
    names = _git(cwd, "-c", "core.quotepath=off", "ls-files", "--cached", "--others", "--exclude-standard", "--full-name").splitlines()
    # git paths are relative to the repository root, even for a subdirectory cwd.
    root = Path(_git(cwd, "rev-parse", "--show-toplevel").strip() or cwd)
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        rel = Path(name)
        if (rel.is_absolute() or ".." in rel.parts or any(x.startswith(".") for x in rel.parts)
                or is_test_file(name) or rel.name in ("AGENTS.md", "CLAUDE.md", "conftest.py", "hidden-pytest.txt")):
            continue
        src = root / rel
        if src.is_file() and not src.is_symlink() and root.resolve() in src.resolve().parents:
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)


WRITE = """[ccx test review] Independently test this implementation against the task.
## Task (the person's original words when available, otherwise the brief)
{task}

This folder contains source only. Do not seek hidden tests or the implementer's tests.
Do not change source. Write independent Python unittest tests in checks/test_*.py.
Use only behaviours explicitly stated in the task. Do not invent robustness requirements.
Write manifest.json as {{"cases": [{{"file": "test_name.py", "task_quote": "exact task words"}}]}}.
Each listed file must contain unittest.TestCase tests. ccx will really execute each file.
If tests cannot be written or dependencies are unavailable, leave cases empty and put
the reason in summary. Do not claim pass. Do not put test source in your JSON answer,
only filenames and a short summary. Do not run the implementation's tests.
"""

CONFIRM = """[ccx test review] Check whether the observed assertion failures or runtime exceptions justify a fix.
## Task
{task}
## Actual test execution
{evidence}

Read checks/ and source. First check each failing test (including a test method that raised) against the quoted task words:
only explicitly requested behaviour counts. Check the test itself is correct (imports,
fixtures, expectations and assumptions). Environment errors are Unknown, not issues.
Do not edit anything. For a genuine implementation failure, put one item in
open_questions as a JSON object encoded as a string:
{{"file":"test_name.py","task_quote":"exact task words","test_correct":true}}.
Omit tests that are wrong, out of scope, or uncertain. No test code in the answer.
"""

# This controller is written AFTER the reviewer has finished. Test assertion
# failures/runtime errors and loading/environment errors are separate machine counts.
RUNNER = '''import importlib.util, json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
report = {"run": 0, "failed": 0, "errors": 0, "load_errors": 0, "skipped": 0}
class Result(unittest.TextTestResult):
    def addError(self, test, err):
        super().addError(test, err)
        loading = issubclass(err[0], (ImportError, SyntaxError)) or isinstance(test, unittest.loader._FailedTest)
        report["load_errors" if loading else "errors"] += 1
try:
    spec = importlib.util.spec_from_file_location("independent_check", sys.argv[1])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromModule(mod))
    report.update(run=result.testsRun, failed=len(result.failures), skipped=len(result.skipped))
except BaseException as exc:
    import traceback
    traceback.print_exc()
    report["load_errors"] += 1
Path(sys.argv[2]).write_text(json.dumps(report), encoding="utf-8")
'''


def test_env() -> dict[str, str]:
    """Do not give model-generated checks the parent's API keys or tokens."""
    keep = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "OS", "TEMP", "TMP", "TMPDIR",
            "LANG", "LC_ALL", "TZ"}
    return {**{k: v for k, v in os.environ.items() if k.upper() in keep}, "PYTHONDONTWRITEBYTECODE": "1"}


def execute(tree: Path, evidence: Path, task: str, timeout: float = 60) -> dict:
    out = unknown("no executable task-derived tests")
    try:
        manifest = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
        cases = manifest["cases"]
        if not isinstance(cases, list):
            raise ValueError("cases must be a list")
    except (OSError, ValueError, KeyError, TypeError):
        return out
    evidence.mkdir(parents=True, exist_ok=True)
    controller = evidence / "runner.py"
    controller.write_text(RUNNER, encoding="utf-8", newline="")
    out.update(unknown_reasons=[], evidence=[], tests_written=0)
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            out["unknown_reasons"].append("invalid test manifest entry")
            continue
        name, quote = case.get("file"), case.get("task_quote")
        if (not isinstance(name, str) or Path(name).name != name or not name.startswith("test_")
                or not name.endswith(".py") or name in seen or not isinstance(quote, str)
                or not quote.strip() or quote not in task):
            out["unknown_reasons"].append("test missing a valid filename or exact task quote")
            continue
        seen.add(name)
        source = tree / "checks" / name
        if not source.is_file() or source.is_symlink():
            out["unknown_reasons"].append(f"{name}: test file missing")
            continue
        shutil.copyfile(source, evidence / name)
        counts = evidence / (name + ".json")
        output = evidence / (name + ".txt")
        try:
            env = test_env()
            proc = subprocess.run([sys.executable, "-I", str(controller), str(source), str(counts)],
                                  cwd=tree, env=env, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout)
            output.write_text(proc.stdout + proc.stderr, encoding="utf-8", newline="")
            n = json.loads(counts.read_text(encoding="utf-8"))
            if not all(type(n.get(k)) is int and n[k] >= 0 for k in ("run", "failed", "errors", "load_errors", "skipped")):
                raise ValueError("invalid execution counts")
            out["tests_written"] += n["run"]
            out["tests_run"] += max(0, n["run"] - n["skipped"])
            failed = n["failed"] + n["errors"]
            out["tests_failed"] += failed
            out["evidence"].append({"file": str(evidence / name), "output": str(output),
                                    "task_quote": quote, "failed": failed, "exit": proc.returncode})
            if proc.returncode or n["load_errors"] or n["skipped"] or not n["run"]:
                out["unknown_reasons"].append(f"{name}: test error, skip, or no tests collected")
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            output.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8", newline="")
            out["unknown_reasons"].append(f"{name}: execution unavailable ({type(exc).__name__})")
            # A timeout/lost result may have executed part of the suite. Zero
            # would assert that no tests ran; the counts are genuinely unknown.
            out.update(tests_written=None, tests_run=None, tests_failed=None)
            break
    if out["tests_run"] == 0:
        out["unknown_reasons"].append("no tests executed")
    return out


def run_review(req, p, cfg: dict, record: dict, cwd: Path, run_dir: Path,
               candidates: list, why: str, cancel=None, run_agent=None) -> None:
    from .agents import same_vendor
    from .delegate import Request, run
    from .review import fix_rounds
    run_agent = run_agent or run
    record["review_test_mode"] = "tests"
    task = task_text(p, req, record)
    out = unknown("no reviewer from another vendor installed", independent=False, usd=0.0, reason=why)
    record["review"] = out
    if not candidates:
        return
    agent, model, effort = candidates[0]
    out.update(by=f"{agent}:{model}:{effort}", independent=not same_vendor(agent, req.provider or req.to, cfg))
    if not out["independent"]:
        out["unknown_reasons"] = ["same vendor: review does not count as independent"]
        return
    if cancel is not None and cancel.is_set():
        out["unknown_reasons"] = ["review cancelled"]
        return
    evidence = run_dir / "review-tests"
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ccx-test-review-") as tmp:
        tree = Path(tmp)
        try:
            copy_source(cwd, tree)
            (tree / "checks").mkdir(exist_ok=True)
            before = {f.relative_to(tree): f.read_bytes() for f in tree.rglob("*") if f.is_file()}

            def ask(text, permission):
                rev = run_agent(Request(to=agent, model=model, effort=effort, tier="auto", mode=permission,
                                        cwd=tree, brief=text, caller="ccx-test-review", escalate=False,
                                        fallback=False, review="off", allow_subagents=False, ephemeral=True,
                                        share_context="off", label=f"review:{record['run_id']}"), p)
                out["usd"] = round(out["usd"] + sum(a.get("ae_usd") or 0 for a in rev.get("attempts", [])), 6)
                out["run_id"] = rev.get("run_id")
                return rev

            rev = ask(WRITE.format(task=task), "write")
            if not rev.get("ok"):
                out["unknown_reasons"] = ["reviewer could not write tests"]
                return
            if any(not (tree / f).is_file() or (tree / f).read_bytes() != data for f, data in before.items()):
                out["unknown_reasons"] = ["reviewer modified implementation; test result unusable"]
                return
            out.update(execute(tree, evidence, task))
            if out["tests_failed"]:
                ev = [{**e, "actual_output": Path(e["output"]).read_text(encoding="utf-8")[-12000:]}
                      for e in out["evidence"] if e["failed"]]
                rev = ask(CONFIRM.format(task=task, evidence=json.dumps(ev)), "read")
                confirmed = []
                if rev.get("ok"):
                    for item in (rev.get("result") or {}).get("open_questions") or []:
                        try:
                            item = json.loads(item)
                            quote = item.get("task_quote")
                            if item.get("test_correct") is True and isinstance(quote, str) and quote.strip() and quote in task:
                                confirmed.extend(e for e in ev if Path(e["file"]).name == item.get("file")
                                                 and e["task_quote"] == quote)
                        except (ValueError, TypeError):
                            continue
                if confirmed:
                    out.update(verdict="issues", issues=[f"[must] {e['task_quote']} — {e['file']}; actual output: {e['output']}"
                                                         for e in confirmed])
                    record["kind"] = "review_issues" if req.review_round < fix_rounds(cfg.get("review") or {}) else "review_failed"
                else:
                    out["unknown_reasons"].append("assertion failures not confirmed as correct, in-scope tests")
            elif out["tests_run"] and not out["unknown_reasons"]:
                out["verdict"] = "pass"
        except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
            out["unknown_reasons"] = [f"test review unavailable ({type(exc).__name__})"]
