"""Fix-round re-review replay: [review] fix_rereview = "focus" against "full" (B2 gate). Spends real money.

A review that says `issues` gets one fix round, whose change is reviewed again. "full" (the default) gives that
second review the whole change, as the first one got. "focus" also gives it the first review's problems and the fix
alone (the diff since the run before the fix ended), and asks it to settle those problems first. Before switching,
re-run round 5's recorded fix-round reviews both ways, paired, through the real review path (claude haiku low, as
ccx picked for every recorded one) in the round-5 clean room (scripts/eval/preflight.py), and compare:

  * the [must] items the recorded (full) review raised: does focus still raise each one (and does a full re-run)?
  * the fix rounds that made a unit right (fixround_replay.py: fail->pass): focus must not fail them where full
    passes them;
  * seconds per review, paired (both variants of a case start together).

Each case is one recorded auto fix round with a review (<work>/<tag>/h-<unit>/ccx/runs/<fix>/, review_of set). Its
trees are rebuilt from the unit repository (fixround_replay.fix_rounds_of / state_from_prompt / build_tree): the
tree before the fix (from the first review's diff) and after it (from the fix review's diff, which the reviewer
reads). The fix alone is ccx's own workspace.fix_delta between the two (an end.json written for the replay).
Rounds whose recorded diff was cut, or whose new files were cut and changed later, are skipped and counted.

Not reproducible from the repository alone: it needs a round-5 work folder (see review_replay.temp_root).

  python scripts/eval/rereview_replay.py list
  python scripts/eval/rereview_replay.py run --budget 1.9 --rows <fixreplay rows.json> --out <results.json>
  python scripts/eval/rereview_replay.py summary <results.json>
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import fixround_replay as FR  # noqa: E402
import preflight as PF  # noqa: E402
import review_replay as RR  # noqa: E402
from common import map_stopping, run_tree  # noqa: E402  (preflight already imports it)

EST_MAX_USD = 0.05            # reserve per running review when checking the budget
VARIANTS = ("full", "focus")
_PATH = re.compile(r"([\w./-]+\.(?:py|toml|md|json|txt|js|ts))(?::(\d+))?")
_IDENT = re.compile(r"`([^`]{3,60})`")


# ---------------------------------------------------------------- cases

def cases(base: Path, tags: list[str]) -> list[dict]:
    """Every auto fix round with a recorded review under base/<tag>/h-*/ (its repository next to the hub)."""
    out = []
    for tag in tags:
        wd = base / tag
        for hub in sorted(wd.glob("h-*")):
            repo = wd / hub.name[2:]
            if not (repo / ".git").exists():
                continue
            runs = FR.load_runs(hub)
            for fr in FR.fix_rounds_of(hub):
                fix = runs.get(fr.get("fix") or "")
                if not fix or fix.get("review_of") != fr["run"] or not isinstance(fix.get("review"), dict):
                    continue
                rv = fix["review"]
                rr = runs.get(rv.get("run_id") or "") or {}
                a = (rr.get("attempts") or [{}])[-1]
                out.append({"id": f"{tag}/{hub.name[2:]}/{fr['fix']}", "tag": tag, "hub": str(hub), "repo": str(repo),
                            "run": fr["run"], "fix": fr["fix"], "base": fr.get("base"), "pre": fr.get("pre"),
                            "pre_cut": fr.get("pre_cut"), "post": fr.get("post"), "post_cut": fr.get("post_cut"),
                            "prior": fr.get("issues") or [], "review_dir": rr.get("_dir"),
                            "recorded": {"verdict": rv.get("verdict"), "issues": rv.get("issues") or [],
                                         "seconds": a.get("seconds"), "usd": rv.get("usd"), "by": rv.get("by")}})
    return out


def _commit_all(d: Path) -> str | None:
    """A ref (refs/heads/pre-fix) to a commit of d's tree as ccx's full_tree sees it (same line-end handling)."""
    from ccx.workspace import full_tree
    tree = full_tree(d)
    if not tree:
        return None
    r = subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid", "commit-tree", tree,
                        "-m", "pre-fix"], cwd=d, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    sha = r.stdout.strip()
    if r.returncode or not sha or RR.git(d, "update-ref", "refs/heads/pre-fix", sha).returncode:
        return None
    return sha


def prepare_case(c: dict, work: Path) -> dict:
    """Rebuild the trees before and after the fix, and compute the fix alone with ccx's own fix_delta."""
    from ccx.config import Paths
    from ccx.workspace import fix_delta
    if not c.get("base"):
        return {**c, "skip": "no start commit"}
    if not c["prior"]:
        return {**c, "skip": "the first review listed no issues: focus falls back to the full review"}
    if c["pre"] is None or c["post"] is None:
        return {**c, "skip": "a review prompt has no diff"}
    if c["pre_cut"] or c["post_cut"]:
        return {**c, "skip": "a review diff was cut to max_diff_chars"}
    repo = Path(c["repo"])
    _fp, fnew = FR.final_state(repo, c["base"])
    p1, n1, _c1, why = FR.state_from_prompt(c["pre"], fnew)
    if not why:
        p2, n2, _c2, why = FR.state_from_prompt(c["post"], fnew)
    if why:
        return {**c, "skip": why}
    key = re.sub(r"[^A-Za-z0-9]+", "-", c["id"])
    pre, post = work / "trees" / f"{key}-pre", work / "trees" / f"{key}-post"
    for d in (pre, post):
        PF.rmtree(d)
    why = FR.build_tree(repo, c["base"], pre, p1, n1) or FR.build_tree(repo, c["base"], post, p2, n2)
    if why:
        return {**c, "skip": why}
    sha = _commit_all(pre)
    f = RR.git(post, "fetch", "-q", str(pre), "refs/heads/pre-fix") if sha else None
    if not sha or f.returncode:
        err = f.stderr.decode("utf-8", "replace")[:200] if f else "commit failed"
        return {**c, "skip": f"could not carry the pre-fix tree over: {err}"}
    tree = RR.git(post, "rev-parse", sha + "^{tree}").stdout.decode().strip()
    hub = work / "delta-hubs" / key
    (hub / "ccx" / "runs" / c["run"]).mkdir(parents=True, exist_ok=True)
    (hub / "ccx" / "runs" / c["run"] / "end.json").write_text(json.dumps({"tree": tree}), encoding="utf-8")
    delta = fix_delta(Paths(hub), c["run"], post)
    PF.rmtree(pre)
    if delta is None:
        return {**c, "skip": "fix_delta failed"}
    try:
        b = RR.parse_brief((Path(c["review_dir"]) / "brief.md").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as x:
        return {**c, "skip": f"recorded brief unreadable: {x}"}
    b["diff"] = c["post"]
    return {**c, "tree": str(post), "brief": b, "delta": delta}


# ---------------------------------------------------------------- one review (own process)

def one(job_file: Path) -> None:
    job = RR.load(job_file)
    from ccx import review
    from ccx.config import Paths
    from ccx.delegate import Request, run
    b, tree = job["brief"], Path(job["tree"])
    kw = {"focus": {"issues": job["prior"], "delta": job["delta"]}} if job["variant"] == "focus" else {}
    text = review.brief(job["run_id"], b["task"], b["summary"], b["diff"], 12000, b["check"], **kw)
    p = Paths(Path(job["hub"]))
    t0 = time.time()
    rec = run(Request(to="claude", model="haiku", effort="low", tier="auto", mode="read", cwd=tree, brief=text,
                      caller="ccx-review", escalate=False, fallback=False, review="off", allow_subagents=False,
                      ephemeral=True, label=f"rereview:{job['case']}:{job['variant']}"), p)
    wall = time.time() - t0
    a = (rec.get("attempts") or [{}])[-1]
    tools = 0
    for log in (p.runs / rec["run_id"]).glob("events*.log"):
        tools += log.read_text(encoding="utf-8", errors="replace").count('"type":"tool_use"')
    v = review.verdict(rec.get("result")) if rec.get("ok") else {"verdict": "not-run", "issues": []}
    print(json.dumps({"ok": rec.get("ok"), "error": rec.get("error"), "seconds": a.get("seconds"),
                      "wall": round(wall, 1), "output_tokens": (a.get("usage") or {}).get("output_tokens"),
                      "usd": sum(x.get("cost_usd") or 0 for x in rec.get("attempts") or []), "tool_uses": tools,
                      "brief_chars": len(text), "verdict": v["verdict"], "issues": v.get("issues") or []}))


def run_job(c: dict, variant: str, work: Path, timeout: int) -> dict:
    key = f"{re.sub(r'[^A-Za-z0-9]+', '-', c['id'])}-{variant}"
    hub = work / "hubs" / key
    PF.rmtree(hub)
    hub.mkdir(parents=True, exist_ok=True)
    env = PF.prepare(PF.Unit(key=key, work=work, repo=Path(c["tree"]), hub=hub))
    job = {"variant": variant, "brief": c["brief"], "tree": c["tree"], "hub": str(hub), "run_id": c["run"],
           "prior": c["prior"], "delta": c["delta"], "case": c["id"]}
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
    out.update({"case": c["id"], "variant": variant})
    return out


# ---------------------------------------------------------------- matching [must] items

def anchors(item: str) -> tuple[set[str], set[str]]:
    """(file names, `identifiers`) an item names: what a later item must share to count as the same problem."""
    files = {m.group(1).rsplit("/", 1)[-1].lower() for m in _PATH.finditer(item)}
    idents = {x.strip().lower() for x in _IDENT.findall(item) if not x.strip().lower().endswith(tuple(files) or ("\0",))}
    return files, idents


def same_problem(recorded: str, other: str) -> bool:
    """A loose match for counting: same file named and (when the recorded item quotes `identifiers`) one shared."""
    f1, i1 = anchors(recorded)
    f2, i2 = anchors(other)
    if f1 and not (f1 & f2):
        return False
    return not i1 or bool(i1 & i2)


def summary(*files: Path, rows: Path | None = None) -> dict:
    data = [RR.load(f) for f in files]
    res = [r for d in data for r in d["results"] if r.get("ok")]
    cs = {c["id"]: c for d in data for c in d["cases"]}
    rescues = set()
    if rows and rows.exists():
        for r in RR.load(rows).get("rows") or []:
            if r.get("outcome") == "fail->pass" and r.get("by") == "auto":
                rescues.add(f"{r['workdir']}/{r['unit']}/{r['fix']}")
    by = {}
    for r in res:
        by.setdefault(r["case"], {})[r["variant"]] = r
    pairs = {k: v for k, v in by.items() if all(x in v for x in VARIANTS)}
    out = {"spent": round(sum(d.get("spent") or 0 for d in data), 4), "finished": len(res),
           "failed": sum(len(d["results"]) for d in data) - len(res), "pairs": len(pairs)}
    for v in VARIANTS:
        rs = [p[v] for p in pairs.values()]
        if rs:
            out[v] = {"median_s": statistics.median(r["seconds"] for r in rs if r.get("seconds") is not None),
                      "median_tools": statistics.median(r.get("tool_uses") or 0 for r in rs),
                      "usd": round(sum(r.get("usd") or 0 for r in rs), 4),
                      "issues": sum(r["verdict"] == "issues" for r in rs),
                      "other": sorted(k for k, p in pairs.items() if p[v]["verdict"] not in ("pass", "issues"))}
    saves = [p["full"]["seconds"] - p["focus"]["seconds"] for p in pairs.values()
             if p["full"].get("seconds") is not None and p["focus"].get("seconds") is not None]
    out["median_saving_s"] = statistics.median(saves) if saves else None
    rec_musts, missed = 0, {"full": [], "focus": []}
    for k, p in pairs.items():
        rec = (cs.get(k) or {}).get("recorded") or {}
        for m in rec.get("issues") or []:
            if not m.lstrip().lower().startswith("[must]"):
                continue
            rec_musts += 1
            for v in VARIANTS:
                if not any(same_problem(m, x) for x in p[v].get("issues") or []):
                    missed[v].append({"case": k, "must": m[:200]})
    out["recorded_musts"] = rec_musts
    out["missed"] = {v: len(missed[v]) for v in VARIANTS}
    out["missed_items"] = missed
    out["rescues"] = [{"case": k, "recorded": (cs.get(k) or {}).get("recorded", {}).get("verdict"),
                       **{v: p[v]["verdict"] for v in VARIANTS}} for k, p in pairs.items() if k in rescues]
    out["rescues_kept"] = sum(1 for x in out["rescues"] if x["focus"] == "pass" or x["focus"] == x["full"])
    out["verdict_table"] = {f"{a}->{b}": sum(1 for p in pairs.values() if p["full"]["verdict"] == a
                                             and p["focus"]["verdict"] == b)
                            for a in ("pass", "issues") for b in ("pass", "issues")}
    # a pair where either side is neither pass nor issues ("unclear"): counted here so the table adds up to pairs
    out["verdict_table"]["other"] = len(pairs) - sum(out["verdict_table"].values())
    return out


# ---------------------------------------------------------------- driver

def cmd_run(a) -> None:
    work = Path(a.work or tempfile.mkdtemp(prefix="rereview-replay-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    cs = cases(RR.temp_root(), a.tags)
    if a.only:
        cs = [c for c in cs if c["id"] in a.only.split(",")]
    if a.issues_only:
        cs = [c for c in cs if c["recorded"]["verdict"] == "issues" or c["id"] in a.also.split(",")]
    cs = [prepare_case(c, work) for c in cs]
    for c in cs:
        print(f"{c['id']}: {c.get('skip') or 'ok'}", file=sys.stderr)
    ready = [c for c in cs if not c.get("skip")]
    jobs = [(c, v) for i, c in enumerate(ready) for v in (VARIANTS if i % 2 else VARIANTS[::-1])]
    lock, spent, running, results = threading.Lock(), [0.0], [0], []
    out_file = Path(a.out)

    def save():
        out_file.write_text(json.dumps({"work": str(work), "budget": a.budget, "spent": round(spent[0], 4),
                                        "cases": [{k: v for k, v in c.items() if k not in ("brief", "pre", "post",
                                                                                           "delta")} for c in cs],
                                        "results": results}, indent=1), encoding="utf-8")

    def go(job):
        c, v = job
        with lock:
            if spent[0] + (running[0] + 1) * EST_MAX_USD > a.budget:
                results.append({"case": c["id"], "variant": v, "skipped": "budget"})
                return
            running[0] += 1
        try:
            res = run_job(c, v, work, a.timeout)
        finally:
            with lock:
                running[0] -= 1
        with lock:
            spent[0] += res.get("usd") or 0
            results.append(res)
            save()
        print(f"{c['id']} {v}: {res.get('verdict')} {res.get('seconds')}s ${res.get('usd') or 0:.4f} "
              f"(spent ${spent[0]:.3f})", file=sys.stderr)

    save()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        map_stopping(ex, go, jobs)
    save()
    print(json.dumps(summary(out_file, rows=Path(a.rows) if a.rows else None), indent=1, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "run"):
        s = sub.add_parser(name)
        s.add_argument("--tags", default="r5c,r5d,r5e,r5f,r5g,r5h", type=lambda x: x.split(","))
    r = sub.choices["run"]
    r.add_argument("--budget", type=float, required=True, help="dollars, all reviews together")
    r.add_argument("--workers", type=int, default=4, help="even: the two variants of a case start together")
    r.add_argument("--timeout", type=int, default=600)
    r.add_argument("--only", default="", help="comma-separated case ids")
    r.add_argument("--issues-only", action="store_true", help="only rounds whose recorded review said issues ...")
    r.add_argument("--also", default="", help="... plus these case ids (e.g. the rescues)")
    r.add_argument("--rows", default="", help="fixround_replay --json rows, to name the fail->pass rounds")
    r.add_argument("--work", default="")
    r.add_argument("--out", required=True)
    o = sub.add_parser("one")
    o.add_argument("job")
    s = sub.add_parser("summary")
    s.add_argument("file", nargs="+")
    s.add_argument("--rows", default="")
    a = ap.parse_args()
    if a.cmd == "list":
        for c in cases(RR.temp_root(), a.tags):
            print(c["id"], c["recorded"]["verdict"], len(c["prior"]), "cut" if c["pre_cut"] or c["post_cut"] else "")
    elif a.cmd == "run":
        cmd_run(a)
    elif a.cmd == "one":
        one(Path(a.job))
    else:
        print(json.dumps(summary(*map(Path, a.file), rows=Path(a.rows) if a.rows else None), indent=1,
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
