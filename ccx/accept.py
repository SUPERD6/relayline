"""`ccx q accept`: land the pieces a `ccx q run` left on worktree branches, one at a time, in dependency order.

For each piece: merge its branch (ccx/<run>) into the branch the project has checked out (autonomy's merge steps:
commit what the worktree still has, `git merge --no-ff`, abort on a conflict), then run the joint check on the
merged tree (the --check given here, else the piece's own check) and roll that one merge back (`git reset --keep`)
when it fails. A merged piece is accepted as `ccx q done <id> --ok 1` would (its run gets the lead's verdict, what
waited on it is released) and the merge goes into the ledger (`q_accept` rows, runs/<run>/merge.json).

Refused, each with why: a piece that is not done (running, failed, no_changes, review_failed, blocked, still
todo), whose review is still running, whose work is not on a branch, that is not verified (no passed check, no
passed review, no verdict of yours, and no --check here), or that waits on a piece not accepted. A conflict stops
that piece (and what waits on it) and leaves the others. Never pushes. Never merges into a protected branch (main
and the like) unless the person said yes (--into-protected). --dry-run only shows the plan."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import autonomy, ledger, queue as wq
from .workspace import run_check

FAILED_WHY = {
    "no_changes": "its run changed nothing: there is nothing to merge",
    "review_failed": "its review failed: fix it (`ccx resume <run>`) and run it again",
    "review_issues": "its review found issues: fix them (`ccx resume <run>`) and run it again",
    "check_failed": "its check failed",
    "check_broken": "its check tested nothing (fix the check)",
}


def _rec(p, run_id: str | None) -> dict | None:
    if not run_id:
        return None
    try:
        rec = ledger.read_record(Path(p.runs) / run_id / "run.json")
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def review_running(p, run_id: str, scan: int = 80) -> bool:
    """Is a review of run_id still going (a `review:<run>` run in state running)?"""
    try:
        dirs = sorted((d for d in Path(p.runs).iterdir() if d.is_dir()), reverse=True)[:scan]
    except OSError:
        return False
    for d in dirs:
        rec = _rec(p, d.name) or {}
        if rec.get("label") == f"review:{run_id}" and rec.get("state") == "running":
            return True
    return False


def evidence(rec: dict) -> str | None:
    """What says the piece's work is right: its check passed, its review passed, or your verdict. None = nothing."""
    v = rec.get("verdict") or {}
    if v.get("ok") is True and not v.get("soft"):
        return "your verdict: ok"
    if rec.get("max_usd"):              # P0-15: --max-usd stopped a step (its review, say): only your verdict counts
        return None
    c = rec.get("check") or {}
    if c.get("passed") and not c.get("broken"):
        from .coverage import text
        cov = text(c.get("covers"))
        return f"check passed{f' ({cov})' if cov else ''}: {c.get('cmd')}"
    if (rec.get("review") or {}).get("verdict") == "pass" and not (rec.get("review") or {}).get("downgraded"):
        return "review passed"
    return None


def why_not(p, q: dict, it: dict | None, joint: bool, root: Path) -> str | None:
    """Why this piece cannot be accepted now, or None. joint: a --check is given here (it counts as evidence)."""
    if it is None:
        return "no such piece in this queue"
    kids = wq.children(q, it["id"])
    if kids:
        return f"it was split into {', '.join(k['id'] for k in kids)}: accept those"
    st = it["status"]
    if st == "doing":
        live = it.get("live") or it.get("run")
        return f"still running ({live}): wait with `ccx show {live} --any --wait`" if live else "still running"
    if st in ("todo", "dep_blocked"):
        return "it has not run yet"
    rec = _rec(p, it.get("run"))
    if st == "failed":
        kind = (rec or {}).get("kind")
        return FAILED_WHY.get(kind, f"it failed ({kind or 'failed'})")
    if st != "done":
        return f"it is {st}, not done"
    if it.get("merged"):
        return "already accepted (merged)"
    if not it.get("worktree"):
        if it.get("verdict") is True:
            return "already accepted"
        return f"its work is already in the project folder (no branch to merge): `ccx q done {it['id']} --ok 1`"
    if it.get("verdict") is True and branch_landed(root, it):
        return "already accepted (its branch is already in the checked-out branch)"
    if rec is None:
        return f"its run record ({it.get('run')}) is missing"
    v = rec.get("verdict") or {}
    if v.get("ok") is False and not v.get("soft"):
        return (f"you rejected this run (`ccx verify {rec['run_id']} --ok 0`): send it back "
                f"(`ccx resume {rec['run_id']} \"...\"`) or verify it ok first")
    if rec.get("state") == "running":
        return "its run is still running"
    if review_running(p, rec["run_id"]):
        return "its review is still running: wait for it"
    if not Path(it["worktree"]).exists() or autonomy._git(Path(it["worktree"]), "rev-parse", "HEAD")[0] != 0:
        return f"its worktree is gone ({it['worktree']})"
    if not joint and not evidence(rec):
        return ("not verified: no check passed, no review passed and no verdict of yours; look at the diff and "
                f"`ccx verify {rec['run_id']} --ok 1 --note \"...\"`, or give --check here")
    return None


def branch_landed(root: Path, it: dict) -> bool:
    """Is the piece's branch already part of what the project has checked out (merged by hand, say)?"""
    branch = it.get("branch") or f"ccx/{it.get('run')}"
    return autonomy._git(root, "merge-base", "--is-ancestor", branch, "HEAD")[0] == 0


def accepted_unmerged(root: Path, q: dict) -> list[str]:
    """Worktree pieces given `ccx q done <id> --ok 1` whose branch never reached the checked-out branch (and was
    not landed by `ccx q accept`): their work is still only on the branch."""
    items = q["items"]
    return [i for i in q["order"] if items[i]["status"] == "done" and items[i].get("worktree")
            and items[i].get("verdict") is True and not items[i].get("merged")
            and Path(items[i]["worktree"]).exists() and not branch_landed(root, items[i])]


def _order(q: dict, ids: list[str]) -> list[str]:
    """ids in dependency order (a piece after every piece it waits on, directly or through others), queue order
    otherwise."""
    items, want, out, seen = q["items"], set(ids), [], set()

    def under(i: str, stack: tuple) -> set[str]:
        got: set[str] = set()
        for d in items.get(i, {}).get("deps", []):
            if d in stack:
                continue
            got |= {d} | under(d, stack + (d,))
        return got
    before = {i: under(i, (i,)) & want for i in ids}
    rank = {i: n for n, i in enumerate(q["order"])}
    left = sorted(want, key=lambda i: rank.get(i, len(rank)))
    while left:
        nxt = next((i for i in left if before[i] <= seen), left[0])
        out.append(nxt)
        seen.add(nxt)
        left.remove(nxt)
    return out


def _upstream(q: dict, i: str) -> set[str]:
    """Every piece i waits on, directly or through others."""
    items, out, todo = q["items"], set(), list(q["items"].get(i, {}).get("deps", []))
    while todo:
        d = todo.pop()
        if d not in out:
            out.add(d)
            todo += items.get(d, {}).get("deps", [])
    return out


def _writer_here(p, q: dict, root: Path) -> str | None:
    """A piece writing in the project folder right now (not in a worktree): merging under it would mix its edits
    with the merge."""
    for i in q["order"]:
        it = q["items"][i]
        if it["status"] != "doing":
            continue
        rec = _rec(p, it.get("live") or it.get("run")) or {}
        cwd = str(rec.get("cwd") or "")
        if rec.get("mode") == "write" and cwd and "/.ccx-worktrees/" not in cwd.replace("\\", "/"):
            try:
                if Path(cwd).resolve() == root.resolve():
                    return i
            except OSError:
                continue
    return None


def accept(p, cfg: dict, root: Path, ids: list[str], all_ready: bool = False, check: str | None = None,
           dry_run: bool = False, into_protected: bool = False) -> tuple[dict, int]:
    """-> (what `ccx q accept` prints, exit code: 0 when everything asked for landed (or nothing was there),
    2 when something was refused, conflicted, rolled back or stopped). A rollback that does not go through, or a
    joint check that leaves edits in tracked files, stops the batch: nothing more is merged on top."""
    q = wq.load(root)
    items = q["items"]
    if all_ready:
        asked = [u["id"] for u in wq.unmerged(q)] + accepted_unmerged(root, q)
        asked = [i for i in q["order"] if i in asked]
    else:
        asked = list(dict.fromkeys(wq.norm_id(x, items) for x in ids))
    out: dict = {"accepted": [], "refused": []}
    running = [i for i in q["order"] if items[i]["status"] == "doing"]
    if all_ready and running:
        out["running"] = running                     # not refused: they are simply not finished yet
    ok_ids: list[str] = []
    for i in asked:
        why = why_not(p, q, items.get(i), bool(check), root)
        if why:
            out["refused"].append({"id": i, "why": why})
        else:
            ok_ids.append(i)
    # a piece waiting on another that is not accepted, and not landing here before it, cannot land first
    order = _order(q, ok_ids)
    for i in list(order):
        missing = [d for d in _upstream(q, i) if d in items and not wq.accepted(items[d], q=q) and d not in order]
        if missing:
            order.remove(i)
            out["refused"].append({"id": i, "why": f"it waits on {', '.join(sorted(missing))}, not accepted yet: "
                                                  f"accept {'it' if len(missing) == 1 else 'them'} first "
                                                  f"(`ccx q accept {' '.join(sorted(missing))} {i}`)"})
    rc, target = autonomy._git(root, "symbolic-ref", "--short", "HEAD")
    target = target if rc == 0 else ""
    out["into"] = target
    stop = None
    if order:
        if not target:
            stop = "the project is not on a branch: check out a working branch first"
        elif not into_protected and autonomy.protected(root, target,
                                                       autonomy.settings(cfg)["protected"]):
            stop = (f"{target} is protected: merging into it goes to the person; check out a working branch, "
                    "or add --into-protected once the person said yes")
        elif autonomy._git(root, "status", "--porcelain", "--untracked-files=no")[1]:
            stop = "the project has uncommitted changes: commit or stash them first"
        else:
            w = _writer_here(p, q, root)
            if w:
                stop = f"{w} is writing in the project folder right now: accept after it has finished"
    if stop:
        out["refused"] += [{"id": i, "why": stop} for i in order]
        order = []
    plan = [{"id": i, "run": items[i].get("run"), "branch": items[i].get("branch") or f"ccx/{items[i].get('run')}",
             "check": check or items[i].get("check")} for i in order]
    if dry_run:
        out.pop("accepted")
        out["plan"] = plan
        if order:
            out["next"] = "ccx q accept " + " ".join(order)
        return _tidy(out), (2 if out["refused"] else 0)
    timeout = int(cfg["defaults"].get("check_timeout_sec", 900))
    not_landed: set[str] = set()
    halt = None
    for step in plan:
        i, it = step["id"], items[step["id"]]
        if halt:                                     # the project is not in a known state: touch nothing more
            out["refused"].append({"id": i, "why": halt})
            continue
        held = sorted(_upstream(q, i) & not_landed)
        if held:
            out.setdefault("skipped", []).append({"id": i, "why": f"it waits on {', '.join(held)}, which did not "
                                                                    "land"})
            not_landed.add(i)
            continue
        row = _land(p, root, it, step, target, timeout)
        if row.get("merged"):
            out["accepted"].append({k: row[k] for k in ("id", "run", "head", "check") if row.get(k) is not None})
        else:
            not_landed.add(i)
            key = row.pop("key")
            out.setdefault(key, []).append({k: v for k, v in row.items()
                                            if k in ("id", "run", "conflicts", "why", "check", "head", "prev")})
            if key == "rollback_failed":
                halt = (f"stopped: the rollback of {i} did not go through, so the project is at its merge "
                        f"({str(row.get('head'))[:12]}) with local edits; sort that out first "
                        f"(`git reset --keep {row.get('prev')}` once the edits are kept or dropped)")
        dirty = [x for x in autonomy._git(root, "diff", "HEAD", "--name-only")[1].splitlines() if x.strip()]
        if dirty and not halt:
            halt = (f"stopped: the joint check left changes in tracked files ({', '.join(dirty[:5])}); commit or "
                    "discard them, then accept the rest")
            out.setdefault("dirty_after", []).append({"id": i, "files": dirty})
    if out["accepted"]:
        wq.close_parents(root)
        moved = wq.propagate(root)
        if moved.get("unblocked"):
            out["unblocked"] = moved["unblocked"]
        if wq.ready(wq.load(root)):
            out["next"] = "ccx q run: pieces that waited on these can start now"
    if out.get("conflict"):
        out["conflict_next"] = ("the other pieces were not touched; for each conflict, merge the project's branch "
                                "into the piece's worktree and resolve it there (or redo the piece on top of what "
                                "landed), then `ccx q accept` it again")
    bad = (out["refused"] or out.get("conflict") or out.get("rolled_back") or out.get("rollback_failed")
           or out.get("failed") or out.get("skipped") or out.get("dirty_after"))
    return _tidy(out), (2 if bad else 0)


def _tidy(out: dict) -> dict:
    return {k: v for k, v in out.items() if v not in ([], None, "") or k in ("accepted", "into")}


def _land(p, root: Path, it: dict, step: dict, target: str, timeout: int) -> dict:
    """Merge one piece, run the joint check, roll back on failure; record the outcome. Never raises on git."""
    run_id, branch, wt = it.get("run"), step["branch"], Path(it["worktree"])
    row: dict = {"id": it["id"], "run": run_id}
    err = autonomy.commit_worktree(wt, f"ccx run {run_id}: q:{it['id']}", ident=True)
    if err:
        ledger.append_event(p, {"type": "q_accept", "id": it["id"], "run_id": run_id, "repo": str(root),
                                "into": target, "branch": branch, "result": "commit_failed", "error": err,
                                "ts": time.time()})
        return {**row, "key": "failed", "why": f"could not commit its worktree, nothing merged: {err}"}
    m = autonomy.merge_branch(root, branch, f"Merge {branch} (ccx q accept {it['id']})", ident=True)
    event = {"type": "q_accept", "id": it["id"], "run_id": run_id, "repo": str(root), "into": target,
             "branch": branch, "from": m["prev"], "ts": time.time()}
    if not m["merged"]:
        files = m["conflicts"]
        why = (f"conflict in {', '.join(files)} with what is already on {target}; merge aborted, nothing changed"
               if files else f"the merge failed, aborted: {m['error']}")
        ledger.append_event(p, {**event, "result": "conflict", "conflicts": files, "error": m["error"]})
        return {**row, "key": "conflict", "conflicts": files, "why": why}
    cmd = step.get("check")
    chk = None
    if cmd:
        chk = run_check(cmd, root, timeout)
        if not chk["passed"]:
            back = autonomy.rollback(root, m["prev"])
            brief = {"cmd": cmd, "exit": chk["exit"], "tail": chk["tail"][-400:]}
            ledger.append_event(p, {**event, "result": "rolled_back" if not back else "rollback_failed",
                                    "head": m["head"], "check": brief, "rollback_error": back})
            if not back:
                return {**row, "key": "rolled_back", "check": brief,
                        "why": "the joint check failed on the merged tree: this merge was rolled back"}
            return {**row, "key": "rollback_failed", "check": brief, "head": m["head"], "prev": m["prev"],
                    "why": f"the joint check failed and the rollback did not go through ({back}): the merge is "
                           "still in the checked-out branch, not accepted"}
    note = f"ccx q accept: merged {branch} into {target or 'HEAD'} at {m['head'][:12]}"
    if chk:
        note += f"; joint check passed: {cmd}"
    if run_id:
        from .verdicts import verify
        try:
            verify(p, run_id, True, note)
        except Exception:  # noqa: BLE001   the merge stands; a verdict that could not be written is not a reason
            pass
    wq.update(Path(root), it["id"], verdict=True, merged=m["head"])
    brief = {"cmd": cmd, "passed": True, "seconds": chk["seconds"]} if chk else None
    rowl = {**event, "result": "merged", "head": m["head"], "check": brief}
    ledger.append_event(p, rowl)
    if run_id:
        try:
            (Path(p.runs) / run_id / "merge.json").write_text(json.dumps(rowl), encoding="utf-8")
        except OSError:
            pass
    return {**row, "merged": True, "head": m["head"], "check": brief}
