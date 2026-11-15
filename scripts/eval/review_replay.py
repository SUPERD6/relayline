"""Replay recorded independent reviews with the old and the new review prompt (r5 design, PR A gate).

PR A gives ccx's reviewer (caller `ccx-review`) a read-only Finish text instead of the builder's "run the tests" one,
and adds a "## Code around the change" block to its brief. Before trusting it, re-run reviews that round 5 already
recorded, old prompt against new, through the real review path (claude haiku low, as ccx picks for a Codex builder),
and check the new prompt still finds the real bugs the old one found.

Each case is one recorded review run (<work>/<tag>/h-<unit>/ccx/runs/<id>/, caller ccx-review). The reviewed tree
is rebuilt from the build run's undo snapshot (base commit in the unit repo) plus the diff the brief carried (a
fix-round's tree is not on disk any more: the unit folder holds only the final state). All variants review the
same rebuilt tree: `old` runs the ccx of --old-ref (default origin/main); `new` this checkout's, code context
included; `finish` this checkout's without the code context (only the read-only Finish text), to tell the two
parts apart.
Each review runs in its own process with the round-5 clean room (scripts/eval/preflight.py: allow-listed
environment, no user settings, hooks, CLAUDE.md or auto-memory for the Claude reviewer).

Not reproducible from the repository alone: KNOWN below names round-5 run ids that live only in the round-5 work
folder of the machine that ran it (see temp_root); elsewhere `list` finds no cases.

This spends real money (about $0.01-0.03 a review). --budget caps the total: a review starts only while the money
spent so far plus a reserve per running review stays under it.

  python scripts/eval/review_replay.py list                       # the cases found, nothing run
  python scripts/eval/review_replay.py run --budget 2.0 --reps 2 --out <results.json>
  python scripts/eval/review_replay.py summary <results.json>
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

# The real findings round 5's reviewers made that the new prompt must keep (r5 design text, PR A gate): the case
# (tag, unit, review run) and a test on the [must] items. Controls: reviews of the same tasks, kept for cost/time.
KNOWN = {
    "check_ok": ("r5e", "h-2-brief-words-ccx2", "20261026-081537-53f0",
                 lambda t: bool(re.search(r"get\(\s*['\"]ok['\"]", t)) or ("passed" in t and re.search(r"\bok\b", t))),
    "caller_nameerror": ("r5e", "h-2-mem-report-ccx2", "20261026-081810-8a41", lambda t: "_caller" in t),
    "paths_str": ("r5g", "h-1-projects-refresh-ccx2", "20261026-105348-cc56",
                  lambda t: "Paths(" in t or ("TypeError" in t and "str" in t)),
    "bg_path": ("r5h", "h-1-brief-words-ccx2", "20261026-131138-31cb", lambda t: "--bg" in t or "_background" in t),
    "status_done": ("r5e", "h-2-brief-words-ccx2", "20261026-081415-b907",
                    lambda t: bool(re.search(r"get\(\s*['\"](status|state)['\"]|status\s*==\s*['\"]done", t))),
}
EST_MAX_USD = 0.06            # reserve per running review when checking the budget


def temp_root() -> Path:
    return Path(os.environ.get("CCX_REPLAY_RECORDS") or tempfile.gettempdir())


def load(f: Path) -> dict:
    return json.loads(f.read_text(encoding="utf-8"))


def review_dirs(base: Path, tags: list[str]) -> list[Path]:
    out = []
    for tag in tags:
        for rj in sorted(base.glob(f"{tag}/h-*/ccx/runs/*/run.json")):
            try:
                if load(rj).get("caller") == "ccx-review" and (rj.parent / "brief.md").exists():
                    out.append(rj.parent)
            except (OSError, ValueError):
                pass
    return out


def musts(result: dict | None) -> list[str]:
    return [str(x) for x in ((result or {}).get("open_questions") or []) if str(x).lstrip().lower().startswith("[must]")]


def parse_brief(text: str) -> dict:
    """task, summary, diff and check of a recorded review brief (review.BRIEF)."""
    m = re.search(r"## The task it was given\n(.*?)\n\n## What it says it did\n(.*?)\n\n## The change \(git diff "
                  r"against the tree before it started(.*?)\)\n```diff\n(.*?)\n```\n.*?## Checks\n(.*?)\n\n## Answer",
                  text, re.S)
    if not m:
        raise ValueError("not a review brief")
    task, summary, cut, diff, checks = m.groups()
    check = None
    c = re.match(r"ccx ran the acceptance command `(.*)` after the change: (passed|FAILED \(exit (.*?)\))\.", checks)
    if c:
        check = {"cmd": c.group(1), "passed": c.group(2) == "passed", "exit": 0 if c.group(2) == "passed" else c.group(3)}
    return {"task": task, "summary": summary, "diff": "" if diff == "(empty)" else diff, "cut": bool(cut.strip()),
            "check": check}


def build_run(hub_runs: Path, review: dict) -> dict | None:
    """The reviewed run's undo snapshot, walking back through resumes to the first run (as review_run does)."""
    rid = (review.get("label") or "").split("review:", 1)[-1]
    for _ in range(6):
        if not rid:
            return None
        d = hub_runs / rid
        if (d / "undo.json").exists():
            return load(d / "undo.json")
        try:
            rid = load(d / "run.json").get("resumed_from")
        except (OSError, ValueError):
            return None
    return None


def git(cwd: Path, *args: str, input: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid",
                           "-c", "core.autocrlf=false", *args], cwd=cwd, capture_output=True, input=input)


def split_diff(diff: str) -> tuple[str, dict[str, str]]:
    """(the git part, {path: text}) of review.changes()'s diff: new untracked files come as a bare `--- /dev/null`
    / `+++ b/x` header and `+` lines, without a hunk header that git apply would need."""
    lines, out, new, i = diff.split("\n"), [], {}, 0
    while i < len(lines):
        ln = lines[i]
        if (ln == "--- /dev/null" and i + 1 < len(lines) and lines[i + 1].startswith("+++ b/")
                and (i + 2 >= len(lines) or not lines[i + 2].startswith("@@"))
                and not (out and out[-1].startswith(("new file mode", "index ")))):
            name, j, body = lines[i + 1][6:], i + 2, []
            while j < len(lines) and lines[j].startswith("+") and not lines[j].startswith("+++ "):
                body.append(lines[j][1:])
                j += 1
            new[name] = "\n".join(body) + "\n"
            i = j
            continue
        out.append(ln)
        i += 1
    return "\n".join(out).strip("\n") + "\n", new


def _untar(data: bytes, dest: Path) -> None:
    """Unpack a `git archive` tar; the "data" filter where Python has it (3.12+ warns without one)."""
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, filter="data")
        else:
            tf.extractall(dest)


def rebuild(case_dir: Path, repo: Path, base: str, diff: str, dest: Path) -> dict:
    """The tree the reviewer saw: `base` from the unit repo, then the diff, uncommitted (so git diff shows it)."""
    data = git(repo, "archive", "--format=tar", base).stdout
    if not data:
        return {"ok": False, "why": f"git archive {base} failed in {repo}"}
    dest.mkdir(parents=True, exist_ok=True)
    _untar(data, dest)
    git(dest, "init", "-q")
    git(dest, "add", "-A")
    git(dest, "commit", "-qm", "base")
    tracked, new = split_diff(diff)
    why = ""
    if tracked.strip():
        r = git(dest, "apply", "--whitespace=nowarn", "-", input=tracked.encode("utf-8"))
        if r.returncode:
            r = git(dest, "apply", "--whitespace=nowarn", "--reject", "-", input=tracked.encode("utf-8"))
            why = "partial apply: " + r.stderr.decode("utf-8", "replace")[:300]
    for name, body in new.items():
        f = dest / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8", newline="\n")
    return {"ok": not why, "why": why, "new_files": sorted(new)}


def cases(base: Path, tags: list[str], controls: int) -> list[dict]:
    """The known-finding cases, then up to `controls` reviews that passed (most recent tag first), one per unit."""
    out, seen = [], set()
    for key, (tag, unit, rid, _f) in KNOWN.items():
        d = base / tag / unit / "ccx" / "runs" / rid
        if d.exists():
            out.append({"id": key, "dir": str(d), "known": key})
            seen.add(unit)
    for d in reversed(review_dirs(base, tags)):
        if len([c for c in out if not c.get("known")]) >= controls:
            break
        unit = d.parents[2].name
        rec = load(d / "run.json")
        if unit in seen or not (rec.get("result") or {}).get("summary", "").startswith("REVIEW: pass"):
            continue
        seen.add(unit)
        out.append({"id": f"pass:{d.parents[3].name}/{unit}", "dir": str(d), "known": None})
    return out


def old_ccx(ref: str, work: Path) -> Path:
    """`ref`'s ccx/ and config/ unpacked under work (the checkout itself is left alone)."""
    dest = work / f"old-ccx-{re.sub(r'[^A-Za-z0-9]+', '-', ref)}"
    if not (dest / "ccx" / "review.py").exists():
        data = git(ROOT, "archive", "--format=tar", ref, "ccx", "config", "ccx.py").stdout
        if not data:
            raise SystemExit(f"git archive {ref} failed")
        dest.mkdir(parents=True, exist_ok=True)
        _untar(data, dest)
    return dest


# ---- one review, in its own process: python review_replay.py one <job.json> ----

def insert_rules(text: str, inserts) -> tuple[str, list[str]]:
    """Each extra rule put in front of its anchor text (first occurrence); the anchors not found are returned, so
    the caller can fail the job instead of running the brief without the rule."""
    missing = []
    for anchor, add in inserts:
        if anchor not in text:
            missing.append(anchor)
            continue
        text = text.replace(anchor, add + anchor, 1)
    return text, missing


def one(job_file: Path) -> None:
    job = load(job_file)
    sys.path.insert(0, job["root"])
    from ccx import review                                              # noqa: E402 — the variant's ccx
    from ccx.config import Paths                                        # noqa: E402
    from ccx.delegate import Request, run                               # noqa: E402
    b, tree = job["brief"], Path(job["tree"])
    kw = {"cwd": tree} if job["variant"] == "new" else {}
    if job.get("text"):                 # a brief given whole (offline experiments C4/C6 build their own)
        text = job["text"]
    else:
        text = review.brief(job["run_id"], b["task"], b["summary"], b["diff"], job["max_chars"], b["check"], **kw)
        text, missing = insert_rules(text, job.get("insert") or [])
        if missing:            # the brief's wording moved: running it would silently be the arm without the rule
            print(json.dumps({"ok": False, "error": f"insert anchor not in the brief: {missing[0][:80]!r}",
                              "inserted": False, "usd": 0, "musts": [], "items": []}))
            return
    p = Paths(Path(job["hub"]))
    t0 = time.time()
    rec = run(Request(to="claude", model=job.get("model") or "haiku", effort=job.get("effort") or "low",
                      tier="auto", mode="read", cwd=tree, brief=text,
                      caller="ccx-review", escalate=False, fallback=False, review="off", allow_subagents=False,
                      ephemeral=True, label=f"replay:{job['case']}:{job['variant']}"), p)
    wall = time.time() - t0
    a = (rec.get("attempts") or [{}])[-1]
    tools = 0
    for log in (p.runs / rec["run_id"]).glob("events*.log"):
        tools += log.read_text(encoding="utf-8", errors="replace").count('"type":"tool_use"')
    print(json.dumps({"ok": rec.get("ok"), "error": rec.get("error"), "seconds": a.get("seconds"), "wall": round(wall, 1),
                      "output_tokens": (a.get("usage") or {}).get("output_tokens"), "usage": a.get("usage"),
                      "usd": sum(x.get("cost_usd") or 0 for x in rec.get("attempts") or []), "tool_uses": tools,
                      "brief_chars": len(text), "inserted": bool(job.get("insert")), "summary": ((rec.get("result") or {}).get("summary") or "")[:300],
                      "musts": musts(rec.get("result")), "same_as_recorded": text == job.get("recorded"),
                      "items": [str(x) for x in ((rec.get("result") or {}).get("open_questions") or [])]}))


# ---- the driver ----

def prepare_case(c: dict, work: Path) -> dict:
    d = Path(c["dir"])
    rec, brief_text = load(d / "run.json"), (d / "brief.md").read_text(encoding="utf-8")
    b = parse_brief(brief_text)
    snap = build_run(d.parent, rec)
    if not snap:
        return {**c, "skip": "no undo snapshot for the reviewed run"}
    if b["cut"]:
        return {**c, "skip": "the recorded diff was cut; the tree cannot be rebuilt"}
    tree = work / "trees" / re.sub(r"[^A-Za-z0-9]+", "-", c["id"])
    if not tree.exists():
        rb = rebuild(d, Path(snap.get("repo") or rec["cwd"]), snap["base"], b["diff"], tree)
        (tree.parent / (tree.name + ".rebuild.json")).write_text(json.dumps(rb), encoding="utf-8")
    rb = load(tree.parent / (tree.name + ".rebuild.json"))
    a = (rec.get("attempts") or [{}])[-1]
    return {**c, "brief": b, "tree": str(tree), "rebuild": rb, "recorded_text": brief_text,
            "run_id": (rec.get("label") or "").split("review:", 1)[-1] or rec["run_id"],      # the reviewed run
            "recorded": {"seconds": a.get("seconds"), "output_tokens": (a.get("usage") or {}).get("output_tokens"),
                         "usd": a.get("cost_usd"), "musts": musts(rec.get("result"))}}


def run_job(c: dict, variant: str, rep: int, roots: dict, work: Path, timeout: int, extra: dict | None = None) -> dict:
    """One review in its own clean-room process. `extra` goes into the job as is (text, insert, model, effort)."""
    sys.path.insert(0, str(HERE))
    import preflight as PF
    from common import run_tree
    key = f"{re.sub(r'[^A-Za-z0-9]+', '-', c['id'])}-{variant}-{rep}"
    hub = work / "hubs" / key
    hub.mkdir(parents=True, exist_ok=True)
    u = PF.Unit(key=key, work=work, repo=Path(c["tree"]), hub=hub)
    env = PF.prepare(u)
    job = {"root": str(roots[variant]), "variant": variant, "brief": c["brief"], "tree": c["tree"], "hub": str(hub),
           "run_id": c["run_id"], "max_chars": 12000, "case": c["id"], "recorded": c["recorded_text"], **(extra or {})}
    jf = work / "jobs" / f"{key}.json"
    jf.parent.mkdir(parents=True, exist_ok=True)
    jf.write_text(json.dumps(job), encoding="utf-8")
    try:
        r = run_tree([sys.executable, str(Path(__file__).resolve()), "one", str(jf)], cwd=c["tree"], env=env,
                     timeout=timeout)
        out = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
        if not out:
            out = {"ok": False, "error": r.stderr[-500:]}
    except (subprocess.TimeoutExpired, ValueError) as x:
        out = {"ok": False, "error": f"{type(x).__name__}: {x}"[:500]}
    out.update({"case": c["id"], "known": c.get("known"), "variant": variant, "rep": rep})
    if c.get("known") in KNOWN:
        test = KNOWN[c["known"]][3]
        out["found"] = any(test(m) for m in out.get("musts") or [])
    return out


def cmd_list(a) -> None:
    for c in cases(temp_root(), a.tags, a.controls):
        print(c["id"], c["dir"])


def cmd_run(a) -> None:
    work = Path(a.work or tempfile.mkdtemp(prefix="review-replay-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    roots = {"old": old_ccx(a.old_ref, work), "new": ROOT, "finish": ROOT}
    variants = a.variants.split(",")
    cs = [prepare_case(c, work) for c in cases(temp_root(), a.tags, a.controls)]
    if a.known_only:
        cs = [c for c in cs if c.get("known")]
    if a.only:
        cs = [c for c in cs if c["id"] in a.only.split(",")]
    for c in cs:
        print(f"{c['id']}: {c.get('skip') or c['rebuild']}", file=sys.stderr)
    cs = [c for c in cs if not c.get("skip")]
    jobs = [(c, v, r) for r in range(a.rep_from, a.rep_from + a.reps) for c in cs
            for v in (variants if (r + len(c["id"])) % 2 else variants[::-1])]
    lock, spent, running, results = threading.Lock(), [0.0], [0], []
    out_file = Path(a.out)

    def go(job):
        c, v, r = job
        with lock:
            if spent[0] + (running[0] + 1) * EST_MAX_USD > a.budget:
                return {"case": c["id"], "variant": v, "rep": r, "skipped": "budget"}
            running[0] += 1
        try:
            res = run_job(c, v, r, roots, work, a.timeout)
        finally:
            with lock:
                running[0] -= 1
        with lock:
            spent[0] += res.get("usd") or 0
            results.append(res)
            out_file.write_text(json.dumps({"work": str(work), "budget": a.budget, "spent": round(spent[0], 4),
                                            "cases": [{k: v for k, v in c.items() if k not in ("brief", "recorded_text")}
                                                      for c in cs], "results": results}, indent=1), encoding="utf-8")
        print(f"{c['id']} {v} {r}: ok={res.get('ok')} {res.get('seconds')}s out={res.get('output_tokens')} "
              f"${res.get('usd') or 0:.4f} musts={len(res.get('musts') or [])} found={res.get('found')} "
              f"(spent ${spent[0]:.3f})", file=sys.stderr)
        return res

    from common import map_stopping       # late, as in run_job
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        map_stopping(ex, go, jobs)
    summary(out_file)


def summary(*out_files: Path) -> None:
    datas = [load(f) for f in out_files]
    allres = [r for d in datas for r in d["results"]]
    res = [r for r in allres if r.get("ok")]
    print(f"spent ${sum(d['spent'] for d in datas):.3f}; {len(res)} reviews finished, "
          f"{len(allres) - len(res)} failed")
    names = [v for v in ("old", "new", "finish") if any(r["variant"] == v for r in res)]
    for v in names:
        rs = [r for r in res if r["variant"] == v]
        if not rs:
            continue
        med = lambda k: statistics.median([r[k] for r in rs if r.get(k) is not None])  # noqa: E731
        print(f"{v}: n={len(rs)} median seconds {med('seconds')}, output tokens {med('output_tokens')}, "
              f"tool uses {med('tool_uses')}, usd {med('usd'):.4f}, brief chars {med('brief_chars')}")
    for known in KNOWN:
        line = []
        for v in names:
            rs = [r for r in res if r.get("known") == known and r["variant"] == v]
            hit = sum(any(KNOWN[known][3](m) for m in r.get("musts") or []) for r in rs)   # today's matcher
            line.append(f"{v} {hit}/{len(rs)}")
        print(f"  {known}: " + ", ".join(line))
    ctrl = [r for r in res if not r.get("known")]
    for v in names:
        rs = [r for r in ctrl if r["variant"] == v]
        print(f"  controls {v}: {sum(bool(r.get('musts')) for r in rs)}/{len(rs)} with a [must]")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "run"):
        s = sub.add_parser(name)
        s.add_argument("--tags", default="r5e,r5f,r5g,r5h", type=lambda x: x.split(","))
        s.add_argument("--controls", type=int, default=5, help="passed reviews to replay as controls")
    r = sub.choices["run"]
    r.add_argument("--budget", type=float, required=True, help="dollars, all reviews together")
    r.add_argument("--reps", type=int, default=1)
    r.add_argument("--rep-from", type=int, default=0, help="first rep number (to add reps to an earlier run)")
    r.add_argument("--variants", default="old,new", help="old, new, finish (comma-separated)")
    r.add_argument("--known-only", action="store_true", help="only the known-finding cases")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--timeout", type=int, default=600)
    r.add_argument("--old-ref", default="origin/main")
    r.add_argument("--only", default="", help="comma-separated case ids")
    r.add_argument("--work", default="")
    r.add_argument("--out", required=True)
    o = sub.add_parser("one")
    o.add_argument("job")
    s = sub.add_parser("summary")
    s.add_argument("file", nargs="+")
    a = ap.parse_args()
    if a.cmd == "list":
        cmd_list(a)
    elif a.cmd == "run":
        cmd_run(a)
    elif a.cmd == "one":
        one(Path(a.job))
    else:
        summary(*map(Path, a.file))


if __name__ == "__main__":
    main()
