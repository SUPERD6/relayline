"""J0: the lead's own cost, measured the same way before and after proposal J (J1 fixed overhead, J2 cache breaks,
J3 compressed outputs, J6 a one-page STATUS).

  python scripts/eval/j0_baseline.py real [--days 7] [--until ISO] [--tag T]   # free: real lead sessions + ledgers
  python scripts/eval/j0_baseline.py compare --before T1 --after T2           # two `real` readings side by side
  python scripts/eval/j0_baseline.py tasks --ref HEAD [--repeat 2] [--model haiku]
  python scripts/eval/j0_baseline.py summary [--tag TAG]

`real` reads what already happened (no model calls): per lead request, the tokens it re-read (new input + cache
writes + cache reads), its API-equivalent cost, the cache read / write shares, how many requests broke the cache (a
cache write of 20k+ tokens and over half of the request), `ccx lead --cache`'s breaks and causes in the window, and
what ccx sub-runs cost in the same window. Only conversations a person drove count as the lead: left out are the
sessions any ccx ledger knows (this hub's and the temporary hubs eval scripts leave under the temp folder) and
every session a program started headless — Claude `-p` (entrypoint sdk-*) and `codex exec` — which is how every
ccx sub-run (CCX_ROLE=subagent; the variable itself is not in the session files) and every eval lead runs. A `-p`
run started from inside the desktop app inherited its CLAUDE_CODE_ENTRYPOINT and was labelled "claude-desktop"
until ccx and the eval scripts stopped passing it on (2026-10-25); such older sub-runs are caught by the ledgers
and the project filter (eval leads ran in temp folders), not by the label.
`--keep-headless` counts them as before (the reading in PR #6 did). By default only this project's conversations
are read (its main checkout and its worktrees; Claude folders by path, Codex sessions by their cwd), `--project
DIR` for another, `--all-projects` for every one (PR #6's scope). `--until` re-reads an earlier window with the same
rules, so a before/after pair is measured the same way.

`tasks` runs a fixed set of lead tasks in a fresh clone of this repo at `--ref`, each by a new headless Claude Code
lead with the person's DEFAULT setup (their CLAUDE.md, hooks, skills and MCP — what J1–J3 and J6 change; no slim
flags). Each answer is checked against facts read from the clone itself, so "acceptance" means the same before and
after. Per run: requests, tokens re-read per request (first request = fixed start-up overhead), cache shares, $.
Run it now, and again with the same arguments after J lands; compare with `summary`.
Results go to .ccx/eval/j0/ (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, append_jsonl, git, lead_env, read_jsonl, run_tree  # noqa: E402

from ccx import learn, ledger  # noqa: E402
from ccx.config import paths  # noqa: E402
from ccx.runners import bin_argv  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "j0"
BREAK_MIN = 20_000      # a cache write this big, and over half the request, counts as a cache break (J2)

# The three things a lead does all day here: get its bearings, look at a large output, read code to answer.
TASKS = {
    "orient": "You are starting work on this repository. Follow its own start-here instructions for coding agents. "
              "Then answer in at most 6 lines: the package version, and the next 3 steps the project lists.",
    "diff": "Summarise what the last 3 commits changed (look at `git diff HEAD~3 HEAD`), in at most 6 bullets. "
            "Name the files that changed most.",
    "code": "Where is `ccx verify --sweep` implemented, and how does it decide that a run was probably right? "
            "Answer in at most 5 lines and name the function.",
}


def expected(clone: Path) -> dict:
    """Facts each answer must contain, read from the clone (so the check moves with the code)."""
    ver = re.search(r'__version__\s*=\s*"([^"]+)"', (clone / "ccx" / "__init__.py").read_text(encoding="utf-8"))
    files = [l.split("|")[0].strip() for l in git(clone, "diff", "--stat", "HEAD~3", "HEAD").splitlines() if "|" in l]
    sweep = sorted({m.group(1) for f in (clone / "ccx").rglob("*.py")
                    for m in re.finditer(r"def (\w*(?:sweep|soft_verdict)\w*)\(", f.read_text(encoding="utf-8"))})
    return {"orient": [ver.group(1)] if ver else [], "diff": [Path(f).name for f in files],
            "code": sweep}


def accepted(task: str, answer: str, facts: dict) -> bool:
    want = facts.get(task) or []
    return bool(want) and any(w and w in answer for w in want)


def per_request(stdout: str) -> list[dict]:
    """One row per API request (deduplicated by message id) from Claude's stream-json."""
    msgs: dict[str, dict] = {}
    final = {}
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant" and (ev.get("message") or {}).get("id"):
            m = ev["message"]
            msgs[m["id"]] = m.get("usage") or {}
        elif ev.get("type") == "result":
            final = ev
    rows = [{"fresh": u.get("input_tokens", 0) or 0, "write": u.get("cache_creation_input_tokens", 0) or 0,
             "read": u.get("cache_read_input_tokens", 0) or 0, "out": u.get("output_tokens", 0) or 0}
            for u in msgs.values()]
    return rows, final


def shares(rows: list[dict]) -> dict:
    tok = [r["fresh"] + r["write"] + r["read"] for r in rows]
    total = sum(tok) or 1
    return {"requests": len(rows), "first_request_tokens": tok[0] if tok else 0,
            "median_request_tokens": statistics.median(tok) if tok else 0, "max_request_tokens": max(tok, default=0),
            "tokens_read": sum(tok), "cache_read_share": round(sum(r["read"] for r in rows) / total, 3),
            "cache_write_share": round(sum(r["write"] for r in rows) / total, 3),
            "cache_breaks": sum(r["write"] >= BREAK_MIN and r["write"] > t / 2 for r, t in zip(rows, tok)),
            "output_tokens": sum(r["out"] for r in rows)}


def cmd_tasks(a) -> int:
    work = Path(a.workdir or tempfile.mkdtemp(prefix="ccx-j0-"))
    clone = work / "repo"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(clone)], check=True)
    git(clone, "checkout", "-q", a.ref)
    commit = git(clone, "rev-parse", "--short", "HEAD").strip()
    facts = expected(clone)
    tag = a.tag or f"{time.strftime('%Y%m%d')}-{commit}"
    for rep in range(1, a.repeat + 1):
        for task, prompt in TASKS.items():
            argv = [*bin_argv("claude"), "-p", "--output-format", "stream-json", "--verbose", "--model", a.model,
                    "--effort", a.effort, "--permission-mode", "dontAsk", "--allowed-tools",
                    "Read Grep Glob Bash(git:*) Bash(ls:*) Bash(cat:*) Bash(python:*)",
                    "--no-session-persistence", "--max-budget-usd", str(a.lead_budget)]
            t0 = time.time()
            r = run_tree(argv, input=prompt, cwd=clone, env=lead_env(), timeout=900)
            rows, final = per_request(r.stdout)
            answer = str(final.get("result", ""))
            row = {"tag": tag, "ref": a.ref, "commit": commit, "task": task, "rep": rep, "model": a.model,
                   "ok": accepted(task, answer, facts), "cost_usd": final.get("total_cost_usd"),
                   "wall_s": round(time.time() - t0, 1), **shares(rows), "per_request": rows,
                   "answer": answer[-600:], "expected": facts.get(task), "ts": time.time()}
            append_jsonl(OUT / "tasks.jsonl", row)
            print(json.dumps({k: row[k] for k in ("task", "rep", "ok", "cost_usd", "requests", "first_request_tokens",
                                                  "median_request_tokens", "tokens_read", "cache_read_share",
                                                  "cache_breaks", "wall_s")}), flush=True)
    return 0


def other_ledgers(tmp: Path | None = None) -> list[Path]:
    """Ledgers of the temporary hubs eval scripts leave behind (<temp>/ccx-*/.../ledger.jsonl)."""
    tmp = tmp or Path(tempfile.gettempdir())
    out = []
    for d in tmp.glob("ccx-*"):
        if d.is_dir():
            out += [f for f in d.rglob("ledger.jsonl") if len(f.relative_to(d).parts) <= 6]
    return out


def ledger_sessions(files: list[Path]) -> set[str]:
    out = set()
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and not r.get("type"):
                out.update(r.get("sessions") or [])
                if r.get("session_id"):
                    out.add(r["session_id"])
    return out


def headless_sessions(since: float, claude_root: Path | None = None, codex_root: Path | None = None) -> set[str]:
    """Sessions a program started, not a person: Claude Code `-p` (entrypoint sdk-cli / sdk-*) and `codex exec`
    (originator codex_exec)."""
    from ccx.config import claude_home, codex_home
    out = set()
    root = (claude_root or claude_home()) / "projects"
    for f in root.glob("*/*.jsonl") if root.exists() else ():
        try:
            if f.stat().st_mtime < since:
                continue
            with f.open(encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if '"entrypoint"' in line:
                        ep = str((json.loads(line) or {}).get("entrypoint") or "")
                        if ep.startswith("sdk"):
                            out.add(f.stem)
                        break
                    if i > 200:
                        break
        except (OSError, ValueError):
            continue
    xroot = (codex_root or codex_home()) / "sessions"
    for f in xroot.rglob("rollout-*.jsonl") if xroot.exists() else ():
        try:
            if f.stat().st_mtime < since:
                continue
            with f.open(encoding="utf-8", errors="replace") as fh:
                meta = (json.loads(fh.readline()) or {}).get("payload") or {}
        except (OSError, ValueError):
            continue
        if meta.get("originator") == "codex_exec":
            out.add(meta.get("id") or f.stem)
    return out


def main_checkout(root: Path = ROOT) -> Path:
    """The repository's main checkout, also when this runs from one of its worktrees."""
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common).parent if common else root


def _forms(p) -> set[str]:
    """A path as written and resolved, lower case (/var vs /private/var on macOS, short names on Windows)."""
    try:
        both = {str(p), str(Path(p).resolve())}
    except OSError:
        both = {str(p)}
    return {x.lower().rstrip("\\/") for x in both}


def project_sessions(project: Path, claude_root: Path | None = None, codex_root: Path | None = None) -> set[str]:
    """Conversations started in `project` or below it (its worktrees live under .claude/worktrees/)."""
    from ccx.config import claude_home, codex_home
    here = _forms(project)
    slugs = {re.sub(r"[^a-z0-9]", "-", h) for h in here}
    out = set()
    root = (claude_root or claude_home()) / "projects"
    for d in root.iterdir() if root.exists() else ():
        if d.is_dir() and any(d.name.lower().startswith(sl) for sl in slugs):
            out.update(x.stem for x in d.glob("*.jsonl"))
    xroot = (codex_root or codex_home()) / "sessions"
    for x in xroot.rglob("rollout-*.jsonl") if xroot.exists() else ():
        try:
            with x.open(encoding="utf-8", errors="replace") as fh:
                meta = (json.loads(fh.readline()) or {}).get("payload") or {}
        except (OSError, ValueError):
            continue
        if meta.get("cwd") and any(c.startswith(h) for c in _forms(meta["cwd"]) for h in here):
            out.add(meta.get("id") or x.stem)
    return out


def _session_file(agent: str, sid: str) -> Path | None:
    from ccx.config import claude_home, codex_home
    if agent == "claude":
        return next(iter((claude_home() / "projects").glob(f"*/{sid}.jsonl")), None)
    root = codex_home() / "sessions"
    return next(iter(root.rglob(f"rollout-*{sid}*.jsonl")), None) if root.exists() else None


def lead_cache_breaks(p, agent: str, sessions: set[str], since: float, until: float) -> dict:
    """`ccx lead --cache` over every lead conversation in the window, breaks inside the window only."""
    from ccx import leadcost
    from ccx.usage import _ts
    n, usd, causes = 0, 0.0, {}
    for sid in sorted(sessions):
        f = _session_file(agent, sid)
        if not f:
            continue
        for br in leadcost.cache_breaks(p, agent, f)["breaks"]:
            t = _ts(br.get("ts"))
            if t is None or not since <= t <= until:
                continue
            n += 1
            usd += br.get("extra_usd") or 0
            for w in br["why"]:
                key = leadcost.cause_key(w)        # the same cause names as `ccx lead --cache`
                causes[key] = causes.get(key, 0) + 1
    return {"breaks": n, "extra_usd": round(usd, 2), "causes": causes}


def _when(s: str | None) -> float:
    if not s:
        return time.time()
    return datetime.fromisoformat(s).timestamp()


def cmd_real(a) -> int:
    from ccx import usage
    p = paths()
    until = _when(a.until)
    since = until - a.days * 86400
    rows = ledger.rows(p)
    runs = [r for r in rows if not r.get("type")]
    mine = {s for r in runs for s in r.get("sessions", [])}
    others = [f for f in other_ledgers() if f.resolve() != p.ledger.resolve()] + [Path(x) for x in a.ledger or []]
    from_ledgers = ledger_sessions(others) - mine
    headless = set() if a.keep_headless else headless_sessions(since)
    evs, _ = usage.lead_events(since, mine | from_ledgers | headless)
    project = None if a.all_projects else Path(a.project) if a.project else main_checkout()
    keep = project_sessions(project) if project else None
    evs = [e for e in evs if e["ts"] <= until and (keep is None or e["session"] in keep or e.get("parent") in keep)]
    out = {"tag": a.tag or time.strftime("%Y%m%d"), "days": a.days, "taken": time.strftime("%Y-%m-%d %H:%M"),
           "window": [time.strftime("%Y-%m-%d %H:%M", time.localtime(since)),
                      time.strftime("%Y-%m-%d %H:%M", time.localtime(until))],
           "left_out": {"this_hub_sessions": len(mine), "other_ledgers": len(others),
                        "other_ledger_sessions": len(from_ledgers), "headless_sessions": len(headless),
                        "keep_headless": a.keep_headless},
           "project": str(project) if project else "all", "lead": {}}
    for agent in ("claude", "codex"):
        es = [e for e in evs if e["agent"] == agent and e.get("role") == "lead"]
        if not es:
            continue
        tok = [e["usage"].get("input_tokens", 0) + e["usage"].get("cache_write_tokens", 0)
               + e["usage"].get("cached_input_tokens", 0) for e in es]
        usd = [learn.price_usd(p, agent, e.get("model") or "", e["usage"]) or 0 for e in es]
        tot = sum(tok) or 1
        writes = [e["usage"].get("cache_write_tokens", 0) for e in es]
        q = statistics.quantiles(tok, n=10) if len(tok) >= 10 else [None] * 9
        out["lead"][agent] = {
            "requests": len(es), "sessions": len({e["session"] for e in es}),
            "median_request_tokens": statistics.median(tok), "p90_request_tokens": q[8],
            "median_request_usd": round(statistics.median(usd), 4), "mean_request_usd": round(statistics.fmean(usd), 4),
            "total_usd": round(sum(usd), 2),
            "cache_read_share": round(sum(e["usage"].get("cached_input_tokens", 0) for e in es) / tot, 3),
            "cache_write_share": round(sum(writes) / tot, 3),
            "cache_breaks": sum(w >= BREAK_MIN and w > t / 2 for w, t in zip(writes, tok)),
            "cache_break_usd": round(sum(u for u, w, t in zip(usd, writes, tok) if w >= BREAK_MIN and w > t / 2), 2),
            "lead_cache": lead_cache_breaks(p, agent, {e["session"] for e in es}, since, until),
            "models": sorted({e.get("model") or "?" for e in es})}
    sub = [r for r in runs if since <= (r.get("ts") or 0) <= until]
    out["sub_runs"] = {"runs": len(sub), "ae_usd": round(sum(r.get("ae_usd") or 0 for r in sub), 4),
                       "eval_runs": sum(ledger.is_eval(r) for r in sub)}
    append_jsonl(OUT / "real.jsonl", out)
    print(json.dumps(out, indent=1))
    return 0


def compare_real(before: dict, after: dict) -> dict:
    """Two `real` readings side by side: per agent, after / before for what a lead request costs."""
    res = {"before": before.get("window"), "after": after.get("window"), "lead": {}}
    for agent in sorted(set(before.get("lead", {})) | set(after.get("lead", {}))):
        b, x = before.get("lead", {}).get(agent) or {}, after.get("lead", {}).get(agent) or {}
        row = {}
        for k in ("requests", "median_request_tokens", "median_request_usd", "mean_request_usd", "total_usd",
                  "cache_read_share", "cache_breaks"):
            row[k] = {"before": b.get(k), "after": x.get(k),
                      "ratio": round(x[k] / b[k], 3) if b.get(k) and x.get(k) is not None else None}
        row["lead_cache_breaks"] = {"before": (b.get("lead_cache") or {}).get("breaks"),
                                    "after": (x.get("lead_cache") or {}).get("breaks")}
        res["lead"][agent] = row
    return res


def cmd_compare(a) -> int:
    rows = read_jsonl(OUT / "real.jsonl")
    pick = lambda tag: next((r for r in reversed(rows) if r.get("tag") == tag), None)  # noqa: E731
    before, after = pick(a.before), pick(a.after)
    if not before or not after:
        raise SystemExit(f"no `real` reading tagged {a.before if not before else a.after} in {OUT / 'real.jsonl'}")
    print(json.dumps(compare_real(before, after), indent=1))
    return 0


def cmd_summary(a) -> int:
    rows = [r for r in read_jsonl(OUT / "tasks.jsonl") if not a.tag or r["tag"] == a.tag]
    out: dict = {}
    for r in rows:
        out.setdefault(r["tag"], {}).setdefault(r["task"], []).append(r)
    res = {}
    for tag, by in out.items():
        res[tag] = {}
        for task, rs in by.items():
            med = lambda k: statistics.median([x[k] for x in rs])  # noqa: E731
            res[tag][task] = {"n": len(rs), "ok": sum(x["ok"] for x in rs), "usd": med("cost_usd"),
                              "requests": med("requests"), "first_request_tokens": med("first_request_tokens"),
                              "median_request_tokens": med("median_request_tokens"), "tokens_read": med("tokens_read"),
                              "cache_read_share": med("cache_read_share"), "cache_breaks": med("cache_breaks"),
                              "wall_s": med("wall_s")}
    print(json.dumps(res, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("real")
    r.add_argument("--days", type=float, default=7)
    r.add_argument("--until", help="end of the window (ISO, local time); default now")
    r.add_argument("--tag", default="", help="name this reading for `compare` (default: today's date)")
    r.add_argument("--ledger", action="append", help="another ccx ledger whose sessions are sub-runs")
    r.add_argument("--keep-headless", action="store_true", help="count headless sessions as lead (PR #6's reading)")
    r.add_argument("--project", help="read only conversations started in this folder or below (default: this repo)")
    r.add_argument("--all-projects", action="store_true", help="every project's conversations (PR #6's scope)")
    r.set_defaults(fn=cmd_real)
    c = sub.add_parser("compare")
    c.add_argument("--before", required=True)
    c.add_argument("--after", required=True)
    c.set_defaults(fn=cmd_compare)
    t = sub.add_parser("tasks")
    t.add_argument("--ref", default="HEAD")
    t.add_argument("--repeat", type=int, default=2)
    t.add_argument("--model", default="haiku")
    t.add_argument("--effort", default="low")
    t.add_argument("--lead-budget", type=float, default=0.25)
    t.add_argument("--tag", default="")
    t.add_argument("--workdir", default="")
    t.set_defaults(fn=cmd_tasks)
    s = sub.add_parser("summary")
    s.add_argument("--tag", default="")
    s.set_defaults(fn=cmd_summary)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
