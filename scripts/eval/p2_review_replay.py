"""Offline-first pg3b test-review replay (experimental; real execution is opt-in).

Inspect material before spending: --dry-run prints every missing receipt/task/diff/
hidden score. An existing local Exercism clone supplies pinned instructions and
stubs; it is never cloned into a reviewer-visible directory. No downloads.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluation_root() -> Path:
    """Ignored evaluation data belongs to the main checkout, not each worktree."""
    if (ROOT / ".ccx/eval/r5/pg3b-results.jsonl").is_file():
        return ROOT
    try:
        common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=ROOT,
                                         text=True, encoding="utf-8", stderr=subprocess.DEVNULL).strip()
        parent = (ROOT / common).resolve().parent
        if (parent / ".ccx/eval/r5/pg3b-results.jsonl").is_file():
            return parent
    except (OSError, subprocess.SubprocessError):
        pass
    return ROOT


def exercise_source(explicit: Path | None, cache: Path | None, data_root: Path) -> Path | None:
    """Look only at named local clone locations; do not fetch or scan directories."""
    if explicit:
        return explicit
    caches = [cache] if cache else [data_root / ".ccx/eval/ext-cache", ROOT / ".ccx/eval/ext-cache",
                                  Path(tempfile.gettempdir()) / "pg3b/ext-cache"]
    for folder in caches:
        for name in ("polyglot", "polyglot.git", "polyglot-benchmark", "polyglot-benchmark.git"):
            source = folder / name
            if (source / "HEAD").is_file() or (source / ".git").exists():
                return source
    return None


def pg3b_receipts(rows: list[dict]) -> tuple[dict[int, str], str | None]:
    """Public report: 29 self-checked + one final issues review, identifiable from ccx telemetry.

    No inference on other datasets, or if the sole final failed review cannot be identified.
    This reconstructs cohort membership, not the missing receipt's literal bytes.
    """
    import tasks_polyglot as tasks
    if (len(rows) != 30 or {r.get("task") for r in rows} != set(tasks.IDS)
            or any(r.get("tag") != "pg3b" for r in rows)):
        return {}, None
    failed = []
    for index, row in enumerate(rows):
        builders = [r.get("run", "") for r in (row.get("switches_applied") or {}).get("runs", [])
                    if not r.get("review")]
        last = max(builders, default="")
        if last and any(m.get("run_id") == last and m.get("verdict") == "issues" and not m.get("fixed_by")
                        for m in row.get("must_categories") or []):
            failed.append(index)
    if len(failed) != 1:
        return {}, None
    return {i: "review_failed" if i == failed[0] else "ok_self_checked" for i in range(len(rows))}, rows[failed[0]]["task"]


def worker(row: dict) -> str | None:
    """Use the recorded implementer, never the lead or a guessed pg3b vendor."""
    receipt = row.get("receipt") or {}
    explicit = receipt.get("provider") or receipt.get("to") or row.get("implementer")
    if isinstance(explicit, str):
        return explicit
    runs = [r for r in (row.get("switches_applied") or {}).get("runs", []) if not r.get("review")]
    if runs:
        last = runs[-1]
        return last.get("provider") or next(iter(last.get("agents") or []), None)
    return None


def under(root: Path, *parts) -> Path:
    result = root.joinpath(*parts).resolve()
    if result == root.resolve() or root.resolve() not in result.parents:
        raise ValueError("artifact path escapes supplied directory")
    return result


def audit(results: Path, artifacts: Path, exercise_source: Path | None) -> tuple[list[dict], list[str]]:
    problems = []
    if not artifacts.is_dir():
        problems.append("missing artifacts directory: " + str(artifacts))
    if not results.is_file():
        return [], ["missing results file: " + str(results), *problems]
    import tasks_polyglot as tasks
    import ext_repo
    cases = []
    rows = read_rows(results)
    inferred, excluded = pg3b_receipts(rows)
    for index, row in enumerate(rows):
        receipt = row.get("receipt") or {}
        kind = receipt.get("kind") or row.get("kind") or inferred.get(index)
        # Keep unknown receipts so absent data cannot improve the denominator.
        if kind is not None and kind != "ok_self_checked":
            continue
        case = {"index": index, "task": row.get("task"), "source_row": row,
                "implementer": worker(row), "hidden_ok": row.get("ok") if type(row.get("ok")) is bool else None,
                "missing": [], "hidden_roots": [str(artifacts.resolve()), str(results.resolve())],
                "receipt_basis": "recorded" if receipt.get("kind") or row.get("kind") else
                                 "public pg3b report + final unresolved ccx review" if index in inferred else "unknown",
                "cohort_excluded": excluded}
        if exercise_source:
            case["hidden_roots"].append(str(exercise_source.resolve()))
        if kind is None:
            case["missing"].append("last receipt kind (cannot verify membership in the 29 receipts)")
        if case["implementer"] is None:
            case["missing"].append("recorded implementer vendor")
        if case["hidden_ok"] is None:
            case["missing"].append("hidden test outcome")
        try:
            meta = row.get("artifacts") or {}
            dest = under(artifacts, meta.get("run") or "", meta["dir"])
            case["diff_file"] = str(dest / "final.diff")
            for name in ("final.diff", "hidden-pytest.txt"):
                if not (dest / name).is_file():
                    case["missing"].append(name)
            if (dest / "final.diff").is_file():
                diff = (dest / "final.diff").read_text(encoding="utf-8")
                case["diff"] = diff
                if len(diff) >= 5_000_000:  # r5.ARTIFACT_MAX
                    case["missing"].append("diff may be truncated; cannot reconstruct exact tree")
        except (KeyError, ValueError, TypeError, OSError):
            case["missing"].append("artifact location")
        if exercise_source is None:
            case["missing"].append("pinned task instructions and original stubs (--exercise-source or --ext-cache required)")
        else:
            try:
                task = tasks.by_id(row["task"])
                material = ext_repo.exercise_material(exercise_source, task["commit"], task["dir"],
                                                       task["solution"], task["tests"])
                case["user_task"] = receipt.get("user_task") or row.get("user_task")
                case["task_text"] = case["user_task"] or tasks.brief(task, material["docs"])
                # ONLY the stub archive crosses into reconstruction. Hidden tests stay in this process.
                case["stubs"] = material["tar"]
                case["solution"] = task["solution"]
            except (OSError, ValueError, LookupError, StopIteration, RuntimeError, subprocess.SubprocessError):
                case["missing"].append("pinned exercise material unavailable")
        cases.append(case)
    if len(cases) != 29:
        problems.append(f"expected 29 ok_self_checked receipts; found {len(cases)} candidate rows")
    return cases, problems


def score(rows: list[dict]) -> dict:
    def group(correct):
        rs = [r for r in rows if r.get("hidden_ok") is correct]
        blocked = sum(r.get("verdict") == "issues" for r in rs)
        uncertain = sum(r.get("verdict") not in ("pass", "issues") for r in rs)
        return rs, blocked, uncertain
    wrong, caught, uw = group(False)
    right, blocked, ur = group(True)
    ratio = lambda n, d: {"numerator": n, "denominator": d, "rate": n / d if d else None}
    return {"rows": len(rows), "catch": ratio(caught, len(wrong)), "false_block": ratio(blocked, len(right)),
            "unknown": sum(r.get("verdict") not in ("pass", "issues") for r in rows),
            "hidden_unknown": sum(r.get("hidden_ok") is None for r in rows),
            "unknown_wrong": uw, "unknown_right": ur,
            "worst_catch": ratio(caught, len(wrong)), "worst_false_block": ratio(blocked + ur, len(right))}


def print_score(rows):
    s = score(rows)
    for title, key in (("抓错率", "catch"), ("误拦率", "false_block"),
                       ("按最坏算抓错率（Unknown 全算没抓到）", "worst_catch"),
                       ("按最坏算误拦率（Unknown 全算误拦）", "worst_false_block")):
        x = s[key]
        rate = "Unknown" if x["rate"] is None else f"{x['rate']:.1%}"
        print(f"{title}: {x['numerator']}/{x['denominator']} = {rate}")
    print(f"Unknown: {s['unknown']}/{s['rows']}; hidden outcome Unknown: {s['hidden_unknown']}")


def rebuild(case: dict, tree: Path) -> None:
    import ext_repo
    ext_repo.extract(case["stubs"], tree, names=case["solution"])
    for argv in (["git", "init", "-q"], ["git", "add", "--", *case["solution"]],
                 ["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid", "commit", "-qm", "stub"]):
        subprocess.run(argv, cwd=tree, check=True, capture_output=True)
    # Builder tests in final.diff are never applied. No history from the benchmark.
    patch = solution_diff(case["diff"], case["solution"])
    if patch.strip():
        applied = subprocess.run(["git", "apply", "--whitespace=nowarn", *[f"--include={n}" for n in case["solution"]]],
                                 input=patch.encode("utf-8"), cwd=tree, capture_output=True)
        if applied.returncode:
            raise ValueError("cannot apply recorded solution diff: " + applied.stderr.decode("utf-8", "replace")[:1000])


def solution_diff(diff: str, solution: list[str]) -> str:
    """Drop cache/binary/builder-test blocks before git even parses the patch."""
    keep = []
    for block in re.split(r"(?m)(?=^diff --git )", diff):
        header = block.splitlines()[0] if block else ""
        if any(header == f"diff --git a/{name} b/{name}" for name in solution):
            keep.append(block)
    return "".join(keep)


def one(job_file: Path) -> None:
    """Clean-room worker. Its job contains no hidden output, test files or source-row data."""
    from ccx.config import Paths, load_config
    from ccx.delegate import Request
    from ccx.review import reviewers
    from ccx.review_tests import run_review, unknown
    from ccx.runners import find_bin
    job = json.loads(job_file.read_text(encoding="utf-8"))
    p = Paths(Path(job["hub"]))
    cfg = load_config(p)
    candidates = reviewers(cfg, job["implementer"], find_bin, cheapest=True)
    # Claude's native per-call max-budget-usd is the available budget enforcement.
    # Never silently use an unbounded CLI when a hard budget was requested.
    candidates = [c for c in candidates if c[0] == "claude"]
    record = {"run_id": job["key"]}
    if not candidates:
        record["review"] = unknown("no independent reviewer with a native USD budget limit", usd=0.0, native_usd=0.0)
    else:
        run_review(Request(to=job["implementer"], brief=job["task_text"], user_task=job.get("user_task"), review="on"), p, cfg, record,
                   Path(job["tree"]), Path(job["evidence"]), candidates, "pg3b replay")
    print(json.dumps(record["review"]))


def replay(case: dict, base: Path, unit_cap: float, reviewer_model: str = "", reviewer_effort: str = "") -> dict:
    import preflight as PF
    key = f"p2-{case['index']}"
    work = base / key
    tree, hub = work / "tree", work / "hub"
    tree.mkdir(parents=True)
    rebuild(case, tree)
    u = PF.Unit(key=key, work=work, repo=tree, hub=hub,
                hidden=tuple(Path(d) for d in case.get("hidden_roots", [])))
    # Hidden artifacts/exercise clones are not in the clean room. PF also denies
    # outside reference locations; no hidden text enters the job or prompt.
    env = PF.prepare(u)
    config = hub / "ccx" / "tiers.toml"
    config.parent.mkdir(parents=True)
    cap = unit_cap / 2  # at most two requests: write, then validate failures
    config.write_text('[review]\nmode = "tests"\n'
                      f'tests_model = {json.dumps(reviewer_model)}\ntests_effort = {json.dumps(reviewer_effort)}\n'
                      '[permissions.claude]\n'
                      f'write = ["--permission-mode", "acceptEdits", "--max-budget-usd", "{cap}"]\n'
                      f'read = ["--permission-mode", "dontAsk", "--allowed-tools", "Read Grep Glob", "--max-budget-usd", "{cap}"]\n',
                      encoding="utf-8", newline="")
    job = {"key": key, "tree": str(tree), "hub": str(hub), "evidence": str(work / "evidence"),
           "implementer": case["implementer"], "task_text": case["task_text"], "user_task": case.get("user_task"),
           "reviewer_model": reviewer_model, "reviewer_effort": reviewer_effort, "unit_cap": unit_cap}
    f = work / "job.json"
    f.write_text(json.dumps(job), encoding="utf-8", newline="")
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__)), "--one", str(f)],
                           cwd=tree, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
        (work / "worker-output.txt").write_text(r.stdout + r.stderr, encoding="utf-8", newline="")
        if r.returncode:
            raise ValueError("review worker failed")
        return json.loads(r.stdout.splitlines()[-1])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # A lost response may have spent the whole reservation. Never reclaim it.
        return {"verdict": "unknown", "unknown_reasons": ["review worker unavailable"], "usd": None, "native_usd": None}


def unit_cap(values: list[str] | None, model: str) -> float:
    """Keep the numeric option; optionally repeat it as MODEL=USD for a pinned model."""
    default, models = 0.10, {}
    for value in values or []:
        name, sep, amount = value.partition("=")
        cap = float(amount if sep else name)
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError("unit-cap must be finite and positive")
        if sep:
            if not name.strip() or not model:
                raise ValueError("model unit-cap requires MODEL=USD and --reviewer-model")
            models[name] = cap
        else:
            default = cap
    return models.get(model, default)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    data_root = evaluation_root()
    p.add_argument("--results", type=Path, default=data_root / ".ccx/eval/r5/pg3b-results.jsonl")
    p.add_argument("--artifacts", type=Path, default=data_root / ".ccx/eval/r5/pg3b-results-artifacts")
    p.add_argument("--exercise-source", type=Path, help="existing local pinned Exercism clone (never downloaded)")
    p.add_argument("--ext-cache", type=Path, help="r5-compatible folder containing local polyglot or polyglot.git")
    p.add_argument("--out", type=Path, default=ROOT / ".ccx/eval/p2-review-replay.jsonl")
    p.add_argument("--work", type=Path, help="evidence directory outside hidden material")
    p.add_argument("--budget", type=float, default=0.0, help="hard admission cap including lost-response reservations")
    p.add_argument("--unit-cap", action="append", metavar="USD|MODEL=USD",
                   help="per-unit reservation (default 0.10); repeat MODEL=USD with --reviewer-model")
    p.add_argument("--reviewer-model", default="", help="test-review model override; empty keeps the existing candidate")
    p.add_argument("--reviewer-effort", default="", help="test-review effort override; empty keeps the existing candidate")
    p.add_argument("--pin-commit", default="")
    p.add_argument("--wait-quiet", type=float, default=0.0, metavar="MINUTES")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--run", action="store_true", help="explicitly enable paid CLI calls")
    p.add_argument("--one", type=Path, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.one:
        one(a.one)
        return 0
    try:
        a.unit_cap = unit_cap(a.unit_cap, a.reviewer_model)
    except ValueError as exc:
        p.error(str(exc))
    if not all(math.isfinite(x) and x >= 0 for x in (a.budget, a.unit_cap, a.wait_quiet)) or not a.unit_cap:
        p.error("budget/wait must be finite nonnegative; unit-cap must be positive")
    a.exercise_source = exercise_source(a.exercise_source, a.ext_cache, data_root)
    cases, problems = audit(a.results, a.artifacts, a.exercise_source)
    if a.exercise_source:
        print("exercise source: " + str(a.exercise_source))
    else:
        import tasks_polyglot as tasks
        clone = (a.ext_cache or data_root / ".ccx/eval/ext-cache") / "polyglot.git"
        print(f'local task material missing; lead may run: git clone --bare {tasks.REPOS["polyglot"]["url"]} "{clone}"')
    excluded = next((c.get("cohort_excluded") for c in cases if c.get("cohort_excluded")), None)
    if excluded:
        print(f"cohort: exclude {excluded} (final unresolved ccx review); other 29 inferred from public pg3b report")
    for problem in problems:
        print("Unknown: " + problem)
    for case in cases:
        print(f"[{case['index']}] {case['task']}: " + ("ready" if not case["missing"] else "; ".join(case["missing"])))
    print(f"units={len(cases)} ready={sum(not c['missing'] for c in cases)} estimate<=${len(cases) * a.unit_cap:.2f}; "
          f"budget=${a.budget:.2f} (API-equivalent USD, two native-limited calls/unit)")
    print(f"reviewer model={a.reviewer_model or '(existing candidate)'} effort={a.reviewer_effort or '(existing candidate)'}; "
          f"unit-cap=${a.unit_cap:.3f}")
    if a.dry_run or not a.run:
        return 0
    if not a.pin_commit:
        p.error("--run requires --pin-commit")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                   encoding="utf-8", errors="replace").strip()
    pin = subprocess.check_output(["git", "rev-parse", a.pin_commit + "^{commit}"], cwd=ROOT, text=True,
                                  encoding="utf-8", errors="replace").strip()
    if head != pin:
        p.error("HEAD does not match --pin-commit")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT).returncode:
        p.error("tracked checkout changes differ from --pin-commit")
    if a.out.exists():
        p.error("output exists; choose a fresh path to preserve every prior row and its budget")
    quiet = True
    if a.wait_quiet:
        from r5 import wait_quiet
        quiet = wait_quiet(a.wait_quiet)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    base = a.work or Path(tempfile.mkdtemp(prefix="ccx-p2-replay-"))
    for hidden in (a.artifacts, a.exercise_source):
        if hidden and (hidden.resolve() == base.resolve() or base.resolve() in hidden.resolve().parents
                       or hidden.resolve() in base.resolve().parents):
            p.error("work and hidden material must be disjoint")
    rows, reserved = [], 0.0
    with a.out.open("x", encoding="utf-8", newline="") as f:
        for case in cases:
            row = {"index": case["index"], "task": case["task"], "hidden_ok": case["hidden_ok"],
                   "implementer": case["implementer"], "source_row": case["source_row"], "pin_commit": head,
                   "receipt_basis": case.get("receipt_basis", "unknown"), "cohort_excluded": case.get("cohort_excluded"),
                   "reviewer_model": a.reviewer_model, "reviewer_effort": a.reviewer_effort, "unit_cap": a.unit_cap,
                   "verdict": "unknown", "unknown_reasons": case["missing"], "usd": 0.0, "native_usd": 0.0}
            if problems:
                row["unknown_reasons"] += problems
            if not quiet:
                row["unknown_reasons"].append("machine remained busy (--wait-quiet)")
            if not row["unknown_reasons"]:
                if reserved + a.unit_cap > a.budget + 1e-12:
                    row["unknown_reasons"] = ["hard budget reservation exhausted"]
                else:
                    reserved += a.unit_cap
                    try:
                        overrides = {"reviewer_model": a.reviewer_model, "reviewer_effort": a.reviewer_effort}
                        row.update(replay(case, base, a.unit_cap, **{k: v for k, v in overrides.items() if v}))
                    except (OSError, ValueError, subprocess.SubprocessError):
                        row.update(unknown_reasons=["reconstruction/review unavailable"], usd=None, native_usd=None)
            row["reserved_usd"] = reserved
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
    print_score(rows)
    print(f"reserved=${reserved:.3f}/{a.budget:.3f}; evidence={base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
