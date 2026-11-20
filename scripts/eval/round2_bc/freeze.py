"""Freeze the round 2 B task set (#375): merge the upstream selection outputs and write the final task file.

One-off data script, kept so the frozen files can be regenerated and checked. No model is called.

    python scripts/eval/round2_bc/freeze.py --selection SEL_V4 --resume SEL_RESUME2 --authored AUTHORED_JSON \
        --briefs docs/research/data/round2-bc/b-upstream-briefs.json --scripts DIR --trace-report REPORT \
        --trace-rows ROWS --out-dir docs/research/data/round2-bc

Writes into --out-dir:
  selection-b.json  the full select of 2026-11-18 and the resume over the 51 repositories it could not walk, merged:
                    B in selection order, resumed tasks marked `resumed_from`; tasks excluded after selection marked
                    `excluded` with the reason; exclusions and checked candidates of both runs (checked candidates
                    reduced to exit codes, summaries and raw-output hashes; the full outputs' SHA-256 is recorded);
                    the resume wrapper scripts' text. Machine-specific path prefixes in error lines (the temp and
                    home folders) are replaced by <TEMP> and <HOME>, and the login name (pytest's
                    `pytest-of-<user>` folder and any other occurrence, any case) by <USER>, in all three files.
  b.json            {"accepted": [60 tasks], "dev": [4 tasks]}: the 42 upstream tasks (source "upstream", brief
                    from the briefs file) followed by the 18 authored ones (source "authored"), as p4_long_session reads.
  b-trace.json      per upstream task: the per-assertion trace rows and the brief check (round2_tasks.brief_checks).
"""
from __future__ import annotations

import argparse
import hashlib
import getpass
import json
import re
import tempfile
from pathlib import Path

RESUME_REASON = ("git log failed transiently on these 51 repositories during the full select of 2026-11-18 "
                 "(recorded there as 'not in --ext-cache'); only they were selected again (#375)")
FULL_RUN = "selection-v4 (full select, 2026-11-18)"
RESUME_RUN = "selection-v4-resume2 (resume over the 51 repositories, 2026-11-19)"
UPSTREAM_KEYS = ("id", "repo", "url", "project", "commit", "timestamp", "subject", "group", "code_lines", "size",
                 "code", "non_test_files", "tests", "src_layout", "stubs", "pythonutf8", "pytest_plugins")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slim_phase(phase):
    if not isinstance(phase, dict):
        return phase
    out = {k: phase[k] for k in ("rc", "summary", "replayed") if k in phase}
    raw = phase.get("raw")
    if isinstance(raw, dict):
        out["raw"] = {k: raw[k] for k in ("file", "sha256") if k in raw}
    return out


def slim_checked(entry: dict, run: str) -> dict:
    out = {k: entry.get(k) for k in ("id", "repo", "commit", "group", "valid", "error")}
    for phase in ("baseline", "parent", "reference"):
        out[phase] = slim_phase(entry.get(phase))
    out["run"] = run
    return out


def _local_prefixes(temp: str | None = None, home: str | None = None) -> list[tuple[str, str]]:
    """Machine-specific path prefixes (temp folder, then home folder) and their placeholders, in every spelling
    that appears in the outputs: plain, with doubled backslashes (repr), with forward slashes."""
    out = []
    for text, name in ((temp or str(Path(tempfile.gettempdir())), "<TEMP>"), (home or str(Path.home()), "<HOME>")):
        for spelling in (text.replace("\\", "\\\\"), text, text.replace("\\", "/")):
            out.append((spelling, name))
    return out


def scrub(obj, prefixes, user: str | None = None):
    """Replace machine-specific path prefixes in every string (pytest error lines quote local paths), then the
    login name: pytest's `pytest-of-<user>` folder and any other occurrence, in any letter case, become <USER>."""
    if isinstance(obj, str):
        for old, new in prefixes:
            obj = obj.replace(old, new)
        if user:
            obj = re.sub("pytest-of-" + re.escape(user), "pytest-of-<USER>", obj, flags=re.IGNORECASE)
            obj = re.sub(re.escape(user), "<USER>", obj, flags=re.IGNORECASE)
        return obj
    if isinstance(obj, list):
        return [scrub(v, prefixes, user) for v in obj]
    if isinstance(obj, dict):
        return {scrub(k, prefixes, user): scrub(v, prefixes, user) for k, v in obj.items()}
    return obj


def write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for name in ("selection", "resume", "authored", "briefs", "scripts", "trace-report", "trace-rows", "out-dir"):
        ap.add_argument("--" + name, type=Path, required=True)
    a = ap.parse_args(argv)
    full = json.loads(a.selection.read_text(encoding="utf-8"))
    resume = json.loads(a.resume.read_text(encoding="utf-8"))
    briefs = json.loads(a.briefs.read_text(encoding="utf-8"))
    authored = json.loads(a.authored.read_text(encoding="utf-8"))
    report = json.loads(a.trace_report.read_text(encoding="utf-8"))
    rows = json.loads(a.trace_rows.read_text(encoding="utf-8"))

    b = [dict(t) for t in full["B"]] + [dict(t, resumed_from=FULL_RUN, resume_reason=RESUME_REASON)
                                         for t in resume["B"]]
    excluded = {tid: e["excluded"] for tid, e in briefs.items() if e.get("excluded")}
    for t in b:
        if t["id"] in excluded:
            t["excluded"] = excluded[t["id"]]
    missing = [t["id"] for t in b if t["id"] not in briefs]
    if missing:
        raise SystemExit(f"no brief for {missing}")
    kept = [t for t in b if "excluded" not in t]

    scripts = {p.name: p.read_text(encoding="utf-8") for p in sorted(a.scripts.glob("*.py"))}
    selection = {
        "about": "Round 2 B upstream selection (#375): the full select and its resume, merged for the frozen task set",
        "rule": full["rule"],
        "models_called": False,
        "sources": {
            FULL_RUN: {"file": a.selection.name, "sha256": sha256(a.selection)},
            RESUME_RUN: {"file": a.resume.name, "sha256": sha256(a.resume)},
            "note": "full outputs (with every pytest error line) and the raw pytest outputs stay local "
                    "(.ccx/eval/round2-select/); checked candidates here keep exit codes, summaries and raw-output "
                    "hashes",
        },
        "resume": {
            "reason": RESUME_REASON,
            "how": "the same round2_tasks.py select with the B target set to 24 (60 - 36) and C/development targets "
                   "0, over the 51 repositories in their original rank order (repos-resume51 from "
                   "resume-repos-375-bc.py); the interrupted first resume was continued by resume2-select-375-bc.py, "
                   "which decides a candidate from the pytest outputs the interrupted run already wrote and "
                   "validates every other candidate as usual (`replayed`)",
            "scripts": scripts,
            "replayed": resume.get("replayed", []),
        },
        "B": b,
        "B_final_upstream": [t["id"] for t in kept],
        "excluded_after_selection": [{"id": tid, "reason": why} for tid, why in excluded.items()],
        # against the 60 B tasks: selected upstream tasks, then those kept after the exclusions above (the
        # authored tasks make up the rest)
        "b_shortfall": 60 - len(b),
        "b_shortfall_after_exclusion": 60 - len(kept),
        "exclusions": ([dict(e, run=FULL_RUN) for e in full["exclusions"]]
                       + [dict(e, run=RESUME_RUN) for e in resume["exclusions"]]),
        "checked": ([slim_checked(e, FULL_RUN) for e in full["checked"]]
                    + [slim_checked(e, RESUME_RUN) for e in resume["checked"]]),
        "pytest_plugins_loaded": {FULL_RUN: full.get("pytest_plugins_loaded"),
                                  RESUME_RUN: resume.get("pytest_plugins_loaded")},
        "repositories_over_time_limit": {FULL_RUN: full.get("repositories_over_time_limit"),
                                         RESUME_RUN: resume.get("repositories_over_time_limit")},
        "environment": {FULL_RUN: full.get("environment"), RESUME_RUN: resume.get("environment")},
    }

    upstream = []
    for t in kept:
        entry = {k: t[k] for k in UPSTREAM_KEYS if k in t}
        entry.update(brief=briefs[t["id"]]["brief"], source="upstream", dev=False)
        if "resumed_from" in t:
            entry["resumed_from"] = t["resumed_from"]
        upstream.append(entry)
    final_authored = [dict(t, source="authored", dev=False) for t in authored["accepted"]]
    dev = [dict(t, source="authored", dev=True) for t in authored.get("dev", [])]
    tasks = {
        "about": "Round 2 B task set (#375), frozen: 42 upstream tasks (pre-registration section 2, B) and 18 "
                 "authored tasks (scripts/eval/round2_bc, built by build.py); dev tasks are not analysed",
        "accepted": upstream + final_authored,
        "dev": dev,
    }
    trace = {t["id"]: {"rows": rows[t["id"]], "check": report[t["id"]],
                       **({"note": briefs[t["id"]]["note"]} if briefs[t["id"]].get("note") else {})}
             for t in kept}
    a.out_dir.mkdir(parents=True, exist_ok=True)
    prefixes, user = _local_prefixes(), getpass.getuser()
    write(a.out_dir / "selection-b.json", scrub(selection, prefixes, user))
    write(a.out_dir / "b.json", scrub(tasks, prefixes, user))
    write(a.out_dir / "b-trace.json", scrub(trace, prefixes, user))
    print(f"B selected {len(b)}, kept upstream {len(upstream)}, authored {len(final_authored)}, dev {len(dev)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
