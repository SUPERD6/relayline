"""Round 2 A1/A2 task set (#375): build the frozen task files, check every task offline, look for leaks.

Never calls a model. The tasks are written in scripts/eval/round2_a/*.py (authoring helpers in round2_a/spec.py) and
frozen as the JSON files strength_retest.py reads with --tasks / --tasks-sha256:

    docs/research/data/round2-tasks/a1.json       A1: 48 settled + 8 neutral (kind "context")
    docs/research/data/round2-tasks/a1-dev.json   A1 development tasks (smoke / cost only, never analysed)
    docs/research/data/round2-tasks/a2.json       A2: 48 memory tasks (kind "memory")
    docs/research/data/round2-tasks/a2-dev.json   A2 development tasks

    build     write the four task files from the authoring modules (byte-stable, LF)
    check     per task: hidden tests fail on the start files, pass on the reference; the naive implementation
              (repository default or the dropped option) fails a test traced to every convention; a visible test
              (memory tasks only) passes on the reference; trace table complete (round2_tasks.brief_checks over brief +
              convention text); A1: the whole settle text reaches what ccx's --context on attaches from the
              synthetic lead transcript (context_share, as strength_runner writes it) and no clause is dropped;
              the file loads with strength_retest.load_tasks
    leak      round2_tasks.leak_check (ids, briefs vs every earlier task and within the set) plus the same
              SequenceMatcher rule on brief + convention text within the set and against round 1's
              context/memory tasks
    manifest  round2_tasks.manifest over the task files and the authoring modules

Why not `round2_tasks.py authored` directly: it expects a start/, reference/, hidden/ tree per task, requires an
existing suite that passes on start (A1 tasks have no visible test: pytest exits 5), and maps the trace only to the
brief, while an A task's conventions are by design only in the lead conversation or the memory note.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))
import round2_tasks as R  # noqa: E402

ROOT = EVAL.parents[1]
OUT = ROOT / "docs/research/data/round2-tasks"
HIDDEN = "test_zz_hidden_eval.py"      # common.HIDDEN: the name score() gives the hidden test
VISIBLE = "test_task.py"               # common.make_repo writes a memory task's visible test here
GROUPS = {   # file stem -> (kind, dev, authoring modules in order)
    "a1-dev": ("context", True, ["a1_dev"]),
    "a2-dev": ("memory", True, ["a2_dev"]),
    "a1": ("context", False, ["a1_p1", "a1_p2", "a1_p3", "a1_p4", "a1_p5", "a1_neutral"]),
    "a2": ("memory", False, ["a2_p1", "a2_p2", "a2_p3", "a2_p4", "a2_p5"]),
}
# Same notes in every arm of every A2 task (with each task's own adjacent-topic notes after them)
SHARED_DISTRACTORS = [
    ["tooling", "Release builds are made from a clean checkout with `python -m build`; never upload a dirty tree."],
    ["people", "Reviews on this project are asynchronous: leave a summary comment, do not wait for a call."],
    ["pitfall", "The CI image has no locale data: tests must not depend on locale-specific formatting."],
]
AUTHOR = "Claude Opus 5.5 (claude-opus-5-5), task-writing session that takes part in no evaluation"


def load_specs(stem: str) -> list[dict]:
    kind, dev, modules = GROUPS[stem]
    specs = []
    for name in modules:
        module = importlib.import_module(f"round2_a.{name}")
        for spec in module.TASKS:
            if spec["kind"] != kind:
                raise ValueError(f"{spec['id']}: kind {spec['kind']} in {stem}")
            specs.append(spec)
    return specs


def convention_text(spec: dict) -> str:
    return spec["settle"] if spec["kind"] == "context" else spec["memory"]


def trace_rows(spec: dict) -> list[dict]:
    """The trace table per assertion: every check of a traced test maps to that test's fragments."""
    checks = R.assertions(HIDDEN, spec["hidden"])
    rows = []
    for check in checks:
        test = check["id"].split("::", 1)[1].rsplit("#", 1)[0]
        for text in spec["trace"].get(test, []):
            rows.append({"assertion": check["id"], "brief": text})   # round2_tasks.brief_checks' key
    return rows


def frozen_task(spec: dict, dev: bool) -> dict:
    common = {"id": spec["id"], "dev": dev, "source": "authored", "files": spec["files"], "brief": spec["brief"]}
    if spec["kind"] == "context":
        task = {**common, "neutral": spec["neutral"], "settle": spec["settle"], "reversed": spec["reversed"],
                "modified": spec["reversed"] is not None}
    else:
        task = {**common, "neutral": False, "kind": "convention", "memory": spec["memory"],
                "distractors": SHARED_DISTRACTORS + spec["distractors"]}
        if spec["visible"]:
            task["visible"] = spec["visible"]
    task.update(hidden=spec["hidden"], reference=spec["reference"], naive=spec["naive"],
                conventions=spec["conventions"], trace=trace_rows(spec))
    return task


def build(only=None) -> dict:
    out = {}
    for stem, (kind, dev, _) in GROUPS.items():
        if only and stem not in only:
            continue
        tasks = [frozen_task(s, dev) for s in load_specs(stem)]
        data = {"kind": kind, "group": stem.upper(), "dev": dev, "author": AUTHOR,
                "preregistration": "docs/research/prereg/2026-11-16-round2.md, section 2 (A1, A2)",
                "issue": 375, "tasks": tasks}
        if kind == "memory":
            data["distractors"] = SHARED_DISTRACTORS
        raw = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        path = OUT / f"{stem}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        out[stem] = {"file": path.relative_to(ROOT).as_posix(), "tasks": len(tasks),
                     "sha256": hashlib.sha256(raw).hexdigest()}
    return out


# ---------------------------------------------------------------- offline check

def run_tests(files: dict[str, str], hidden: str, visible: str | None) -> dict:
    """pytest on a throwaway tree: the files, the hidden test (and a visible one). Per-test outcomes from JUnit XML."""
    with tempfile.TemporaryDirectory(prefix="r2a-") as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8", newline="")
        (root / HIDDEN).write_text(hidden, encoding="utf-8", newline="")
        if visible:
            (root / VISIBLE).write_text(visible, encoding="utf-8", newline="")
        xml = Path(tmp) / "junit.xml"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        env.pop("PYTHONPATH", None)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
                            f"--junitxml={xml}"], cwd=root, env=env, capture_output=True, timeout=120)
        tests = {}
        if xml.exists():
            for case in ET.parse(xml).iter("testcase"):
                bad = case.find("failure") is not None or case.find("error") is not None
                tests[f"{Path(case.get('classname', '')).name}::{case.get('name')}"] = not bad
    return {"rc": r.returncode, "tests": tests}


def context_reaches(task: dict) -> dict:
    """What the --context on arm would attach (ccx.context_share on the synthetic lead transcript strength_runner
    writes): is the whole settle text there (newest ask, kept nearly whole), and was any clause dropped?"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import time
    from ccx import context_share as CS
    from shared_context_ab import lead_transcript
    with tempfile.TemporaryDirectory(prefix="r2a-ctx-") as tmp:
        f = Path(tmp) / "lead.jsonl"
        f.write_text("".join(json.dumps(e) + "\n" for e in lead_transcript(task, time.time())), encoding="utf-8",
                     newline="")
        dropped: list[str] = []
        evs = CS.drop_lead_only(CS.read_events("claude", f) or [], dropped)
        text = CS.summary(evs, "claude", "strength-synthetic-lead", Path(tmp), "check")
    flat = R.normalize_brief(text)
    return {"settle_whole_in_context": R.normalize_brief(task["settle"]) in flat,
            "context_chars": len(text), "clauses_dropped": len(dropped)}


def _outcome(result: dict, file: str, test: str):
    return result["tests"].get(f"{file[:-3]}::{test}")


def check_task(spec: dict, task: dict) -> dict:
    files, hidden, visible = task["files"], task["hidden"], task.get("visible")
    problems = []
    shadow = sorted(n for n in files if Path(n).stem in sys.stdlib_module_names)
    if shadow:
        problems.append(f"file names shadow standard library modules: {shadow}")
    start = run_tests(files, hidden, visible)
    reference = run_tests({**files, **task["reference"]}, hidden, visible)
    if start["rc"] not in (1, 2):
        problems.append(f"hidden tests do not fail on start (rc={start['rc']})")
    if reference["rc"] != 0:
        problems.append(f"reference fails (rc={reference['rc']})")
    tests = [q.split("::", 1)[1] for q in dict.fromkeys(a["id"].rsplit("#", 1)[0]
                                                         for a in R.assertions(HIDDEN, hidden))]
    untraced = sorted(set(tests) - set(spec["trace"]))
    unknown = sorted(set(spec["trace"]) - set(tests))
    if untraced or unknown:
        problems.append(f"trace keys do not match the hidden tests (untraced {untraced}, unknown {unknown})")
    text = task["brief"] + "\n" + convention_text(spec)
    briefs = R.brief_checks(text, {HIDDEN: hidden}, task["trace"])
    if not briefs["trace_complete"]:
        problems.append(f"trace incomplete: unmapped {briefs['unmapped']}, "
                        f"not in brief/conventions {briefs['sentence_not_in_brief']}")
    naive = None
    conv = convention_text(spec)
    flat = R.normalize_brief(conv)
    if spec["kind"] == "memory" or not spec["neutral"]:
        if not 2 <= len(spec["conventions"]) <= 3:
            problems.append(f"{len(spec['conventions'])} conventions (2-3 required)")
        if not spec["naive"]:
            problems.append("no naive implementation")
        else:
            naive = run_tests({**files, **spec["naive"]}, hidden, visible)
            for c in spec["conventions"]:
                if R.normalize_brief(c) not in flat:
                    problems.append(f"convention not in the convention text: {c!r}")
                traced = [t for t, frags in spec["trace"].items() if c in frags]
                if not traced:
                    problems.append(f"no hidden test traced to convention {c!r}")
                elif all(_outcome(naive, HIDDEN, t) is not False for t in traced):
                    problems.append(f"naive implementation passes every test of convention {c!r}")
            if naive["rc"] != 1:
                problems.append(f"naive implementation does not fail the hidden tests (rc={naive['rc']})")
    elif spec["conventions"] or spec["naive"]:
        problems.append("a neutral task has no conventions and no naive implementation")
    if spec["kind"] == "memory" and len(spec["distractors"]) < 1:
        problems.append("no adjacent-topic distractor")
    reach = None
    if spec["kind"] == "context":
        reach = context_reaches(task)
        if not reach["settle_whole_in_context"]:
            problems.append("the settle text does not reach the --context on attachment whole")
        if reach["clauses_dropped"]:
            problems.append(f"ccx drops {reach['clauses_dropped']} clause(s) of the conversation as hand-off text")
    brief_only = sorted(t for t, frags in spec["trace"].items() if not set(frags) & set(spec["conventions"]))
    row = {"id": task["id"], "start_rc": start["rc"], "reference_rc": reference["rc"],
           "start_failed": sorted(k.split("::")[1] for k, ok in start["tests"].items() if not ok),
           "reference_passed": f"{sum(reference['tests'].values())}/{len(reference['tests'])}",
           "assertions": briefs["assertions"], "trace_complete": briefs["trace_complete"],
           "literal_in_brief_or_conventions": len(briefs["literal_overlap"]),
           "problems": problems, "valid": not problems}
    if reach is not None:
        row.update(reach)
    if naive is not None:
        row.update(naive_rc=naive["rc"],
                   naive_failed=sorted(k.split("::")[1] for k, ok in naive["tests"].items() if not ok),
                   naive_brief_only_tests_passed=f"{sum(_outcome(naive, HIDDEN, t) is True for t in brief_only)}"
                                                 f"/{len(brief_only)}")
    return row


def check(jobs: int = 8, only=None) -> dict:
    import strength_retest as SR
    report = {"models_called": False, "python": sys.version.split()[0], "files": {}}
    for stem, (kind, dev, _) in GROUPS.items():
        if only and stem not in only:
            continue
        path = OUT / f"{stem}.json"
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        loaded = SR.load_tasks(path, sha, kind)          # what strength_retest will read
        specs = {s["id"]: s for s in load_specs(stem)}
        data = json.loads(raw.decode("utf-8"))
        if [t["id"] for t in data["tasks"]] != list(specs):
            raise ValueError(f"{stem}.json is not the build of its modules: run build")
        for t in data["tasks"]:
            if frozen_task(specs[t["id"]], dev) != t:
                raise ValueError(f"{stem}.json task {t['id']} differs from its module: run build")
        with ThreadPoolExecutor(jobs) as ex:
            rows = list(ex.map(lambda t: check_task(specs[t["id"]], t), data["tasks"]))
        settled = [t for t in data["tasks"] if not t["neutral"]]
        summary = {"tasks": len(rows), "loaded_by_strength_retest": len(loaded), "sha256": sha,
                   "neutral": sum(t["neutral"] for t in data["tasks"]), "settled_or_memory": len(settled),
                   "start_fails": f"{sum(r['start_rc'] in (1, 2) for r in rows)}/{len(rows)}",
                   "reference_passes": f"{sum(r['reference_rc'] == 0 for r in rows)}/{len(rows)}",
                   "naive_fails": f"{sum(r.get('naive_rc') == 1 for r in rows)}/{len(settled)}",
                   "trace_complete": f"{sum(r['trace_complete'] for r in rows)}/{len(rows)}",
                   "valid": f"{sum(r['valid'] for r in rows)}/{len(rows)}"}
        if kind == "context":
            summary["modified_mid_conversation"] = f"{sum(t['modified'] for t in settled)}/{len(settled)}"
        summary["conventions_per_task"] = {str(n): sum(len(t["conventions"]) == n for t in settled) for n in (2, 3)}
        report["files"][stem] = {"summary": summary, "tasks": rows}
    report["valid"] = all(r["valid"] for f in report["files"].values() for r in f["tasks"])
    return report


# ---------------------------------------------------------------- leakage / similarity

def _round1_texts() -> list[dict]:
    """Round 1's A-group tasks (shared context, memory) with their convention text, as the new tasks are compared."""
    from shared_context_ab import TASKS
    from l5_memory import CASES
    rows = [{"source": "shared_context_ab.TASKS", "id": t["id"], "text": t["brief"] + "\n" + t["settle"]}
            for t in TASKS]
    rows += [{"source": "l5_memory.CASES", "id": t["id"], "text": t["brief"] + "\n" + t["memory"]} for t in CASES]
    return rows


def leak() -> dict:
    tasks, specs = [], {}
    for stem in GROUPS:
        data = json.loads((OUT / f"{stem}.json").read_text(encoding="utf-8"))
        tasks += data["tasks"]
        specs.update({s["id"]: s for s in load_specs(stem)})
    mine = [p for p in OUT.rglob("*") if p.is_file()]
    base = R.leak_check(tasks, R.corpus(exclude=mine))
    # brief + convention text: within the set and against round 1's A-group tasks
    texts = [(t["id"], R.normalize_brief(t["brief"] + "\n" + convention_text(specs[t["id"]]))) for t in tasks]
    old = [(r, R.normalize_brief(r["text"])) for r in _round1_texts()]
    extra, worst = [], 0.0
    for i, (tid, text) in enumerate(texts):
        near = []
        for r, o in old:
            s = R.ratio(text, o)
            if s > R.LISTED:
                near.append({"source": r["source"], "id": r["id"], "ratio": round(s, 4)})
        for oid, o in texts[i + 1:]:
            s = R.ratio(text, o)
            if s > R.LISTED:
                near.append({"source": "new", "id": oid, "ratio": round(s, 4)})
        worst = max([worst, *(n["ratio"] for n in near)])
        extra.append({"id": tid, "listed_above_0.4": sorted(near, key=lambda n: -n["ratio"]),
                      "clean": all(n["ratio"] < R.SIMILAR for n in near)})
    brief_max = max([0.0, *(n["ratio"] for r in base["tasks"] for n in r["listed_above_0.4"])])
    return {"models_called": False, "brief_rule": base["rule"], "corpus": base["corpus"],
            "brief_max_ratio": round(brief_max, 4), "brief_clean": base["clean"], "brief_tasks": base["tasks"],
            "convention_rule": f"normalized brief + convention text, SequenceMatcher ratio >= {R.SIMILAR} within the "
                               f"set and against round 1's shared-context and memory tasks; above {R.LISTED} listed",
            "convention_max_ratio": round(worst, 4), "convention_clean": all(e["clean"] for e in extra),
            "convention_tasks": extra,
            "clean": base["clean"] and all(e["clean"] for e in extra)}


def manifest_paths() -> list[Path]:
    return [OUT / f"{stem}.json" for stem in GROUPS] + [EVAL / "round2_a", EVAL / "round2_a_tasks.py"]


def write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    c = sub.add_parser("check")
    for x in (b, c):
        x.add_argument("--only", nargs="*", help="file stems (default: all four)")
    c.add_argument("--jobs", type=int, default=8)
    c.add_argument("--out", type=Path, default=OUT / "check.json")
    s = sub.add_parser("leak")
    s.add_argument("--out", type=Path, default=OUT / "leak.json")
    m = sub.add_parser("manifest")
    m.add_argument("--out", type=Path, default=OUT / "manifest.json")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        print(json.dumps(build(a.only), indent=2))
        return 0
    if a.cmd == "check":
        data = check(a.jobs, a.only)
        write(a.out, data)
        print(json.dumps({k: v["summary"] for k, v in data["files"].items()}, indent=2))
        for f in data["files"].values():
            for r in f["tasks"]:
                if r["problems"]:
                    print(r["id"], r["problems"])
        return 0 if data["valid"] else 1
    if a.cmd == "leak":
        data = leak()
        write(a.out, data)
        print(json.dumps({k: data[k] for k in ("brief_max_ratio", "brief_clean", "convention_max_ratio",
                                                "convention_clean", "clean")}, indent=2))
        for r in data["brief_tasks"]:
            if r["findings"]:
                print(r["id"], r["findings"])
        for r in data["convention_tasks"]:
            if not r["clean"]:
                print(r["id"], r["listed_above_0.4"][:3])
        return 0 if data["clean"] else 1
    data = R.manifest(manifest_paths(), ROOT)
    write(a.out, data)
    print(data["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
