"""ccx q — the project's durable work queue (ccx/queue.py): add pieces, see them, run every ready one."""
from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from .. import lanes, ledger, queue as wq
from ..config import load_config, paths
from ..delegate import Request, compact, run, verify
from ..gitstate import SHARED_WHY, clean as _clean, in_git as _in_git
from ..modes import resolve_mode
from .common import _caller, _out, resolve


def _root(a) -> Path:
    from .. import project
    root = project.find_root(Path(a.cwd) if getattr(a, "cwd", None) else None)
    if root:
        return root
    return Path(getattr(a, "cwd", None) or os.getcwd())


def cmd_q(a) -> int:
    root = _root(a)
    if a.q_cmd == "add":
        if a.plan:
            _out(wq.add_plan(root, json.loads(Path(a.plan).read_text(encoding="utf-8"))))
            return 0
        it = wq.add(root, a.title, a.brief or a.title, deps=a.dep or [], parent=a.parent, check=a.check,
                    minutes=a.minutes, mode=a.mode, kind=a.kind, to=a.to, budget_usd=a.budget)
        _out(it)
    elif a.q_cmd in ("ls", "tree"):
        from ..recover import sweep
        sweep(paths())                  # as `ccx stats` does: a run whose ccx was killed shows as interrupted
        q = wq.view(wq.load(root))      # a stuck dependency shows on what waits for it (shown, not written)
        if a.q_cmd == "tree":
            print("\n".join(wq.tree(q)) or "(queue empty)")
        elif not getattr(a, "long", False):
            print(compact_ls(root, q, bool(getattr(a, "gate", False))))
        else:
            gate = bool(getattr(a, "gate", False))
            out = {"items": [q["items"][i] for i in q["order"]], "ready": [x["id"] for x in wq.ready(q, gate)],
                   "spent_usd": wq.spent(q), "budget_usd": q["budget_usd"]}
            held = runner(root)
            if held:
                out["runner"] = held                 # a `q run` (--bg or not) is working on it now
            try:
                out["last_run"] = json.loads((wq.qdir(root) / LAST).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            _out(out)
    elif a.q_cmd == "budget":
        wq.set_budget(root, a.usd)
        _out({"budget_usd": a.usd})
    elif a.q_cmd == "done":
        q = wq.load(root)
        ids = list(dict.fromkeys(wq.norm_id(x, q["items"]) for x in a.id))
        notes = done_notes(paths(), q, ids, bool(a.ok), a.note or [])
        for i in ids:
            it = q["items"][i]
            if it.get("run"):
                verify(paths(), it["run"], bool(a.ok), notes[i])
            wq.update(root, i, status="done" if a.ok else "failed", verdict=bool(a.ok))
        out = {"id": ids[0]} if len(ids) == 1 else {"ids": ids}
        if a.ok:
            from ..accept import branch_landed
            loose = [i for i in ids if q["items"][i].get("worktree") and not q["items"][i].get("merged")
                     and not branch_landed(root, q["items"][i])]
            if loose:   # recorded as asked; but their work is still only on their branches
                out["not_merged"] = {"ids": loose, "next": "their branches are not in the checked-out branch: "
                                     "land them with `ccx q accept " + " ".join(loose) + "`"}
        out["closed_parents"] = wq.close_parents(root)
        moved = wq.propagate(root)
        out.update({k: v for k, v in moved.items() if v})
        from ..ability import after_verdict
        after_verdict(paths())
        _out(out)
    elif a.q_cmd == "accept":
        if not a.ids and not a.all_ready:
            raise ValueError("name the pieces to accept (`ccx q accept q1 q2`) or give --all-ready")
        if a.ids and a.all_ready:
            raise ValueError("give piece ids or --all-ready, not both")
        from ..accept import accept
        p = paths()
        out, code = accept(p, load_config(p), root, a.ids or [], all_ready=a.all_ready, check=a.check,
                           dry_run=a.dry_run, into_protected=a.into_protected)
        from ..ability import after_verdict
        after_verdict(p)
        _out(out)
        return code
    elif a.q_cmd in ("run", "resume"):
        return _run(a, root)
    return 0


def _note_for(note: str, i: str, items: dict) -> bool:
    """Does `q1: tests pass` (or `1: ...`) speak of piece i?"""
    head, sep, _ = note.partition(":")
    return bool(sep) and wq.norm_id(head, items) == i


def done_notes(p, q: dict, ids: list[str], ok: bool, notes: list[str]) -> dict[str, str]:
    """{id: the note kept with its verdict}. One id: every --note, joined (as before). Several ids accepted at
    once: each needs evidence of its own, its run's passed check or review, or a `--note "<id>: why"` naming it;
    otherwise nothing is recorded and the ones without are named."""
    from ..accept import evidence
    items = q["items"]
    unknown = [i for i in ids if i not in items]
    if unknown:
        raise ValueError(f"no piece {', '.join(unknown)} in this queue (`ccx q ls` lists them)")
    if len(ids) == 1:
        return {ids[0]: " ".join(notes)}
    out, lacking = {}, []
    for i in ids:
        own = [n.partition(":")[2].strip() for n in notes if _note_for(n, i, items)]
        rec = _run_record(p, items[i]["run"]) if items[i].get("run") else None
        ev = evidence(rec) if rec else None
        if ok and not own and not ev:
            lacking.append(i)
        out[i] = "; ".join(own) or (ev or "")
    if lacking:
        raise ValueError(f"accepting several pieces at once needs evidence for each: {', '.join(lacking)} had no "
                         "passed check or review; add --note \"<id>: what you checked\" for each (nothing was "
                         "recorded)")
    return out


def compact_ls(root: Path, q: dict, gate: bool = False) -> str:
    """`ccx q ls`: one line per piece (id, state, agent, seconds, $, then what to do or wait on, then the title)
    and one line about the queue. A finished worktree piece not landed yet shows as `unmerged`. `--long` prints
    the full JSON."""
    if not q["order"]:
        return "(queue empty)"
    from ..accept import accepted_unmerged
    p, now, lines = paths(), time.time(), []
    loose = set(accepted_unmerged(root, q))
    for i in q["order"]:
        it = q["items"][i]
        st = it["status"]
        unm = (st == "done" and it.get("worktree") and it.get("verdict") is not True) or i in loose
        if st == "doing":
            secs = now - float(it.get("updated") or it.get("added") or now)
        else:
            rec = _run_record(p, it["run"]) if it.get("run") else None
            secs = sum(float(x.get("seconds") or 0) for x in (rec or {}).get("attempts") or [])
        row = (f"{i} {'unmerged' if unm else st} {it.get('agent') or '-'} {int(secs)}s "
               f"${float(it.get('cost_usd') or 0):.3f}")
        if st == "doing" and it.get("live"):
            row += f" live {it['live']}"
        elif unm and it.get("verdict") is None and i not in loose:
            # one order, the same as ccx ui: your verdict first, then the merge
            row += f" next: ccx q done {i} --ok 1, then ccx q accept {i}"
        elif unm and it.get("verdict") is False:
            row += " rejected: not merged"
        elif unm:
            row += f" next: ccx q accept {i}"
        elif st == "dep_blocked" and it.get("blocked_by"):
            row += f" fix {','.join(it['blocked_by'])} first"
        elif st == "todo" and it.get("deps"):
            row += f" after {','.join(it['deps'])}"
        title = str(it.get("title") or "")
        lines.append(row + (f"  {title[:30]}{'...' if len(title) > 30 else ''}" if title else ""))
    tail = [f"spent ${wq.spent(q):.3f}" + (f" of ${q['budget_usd']}" if q["budget_usd"] is not None else "")]
    ready = [x["id"] for x in wq.ready(q, gate)]
    if ready:
        tail.insert(0, "ready " + ",".join(ready))
    held = runner(root)
    if held:
        tail.append(f"runner pid {held.get('pid')}")
    try:
        last = json.loads((wq.qdir(root) / LAST).read_text(encoding="utf-8"))
        tail.append(f"last_run exit {last.get('code')}" + (f" stopped: {last['stopped']}" if last.get("stopped")
                                                            else ""))
    except (OSError, ValueError, AttributeError):
        pass
    return "\n".join(lines + [" | ".join(tail)])


RESUME_NOTE = ("ccx was stopped while you were working on this piece. Go on from where you were: check what is "
               "already done before redoing anything.\n\n")


def _cost(rec: dict) -> float:
    return sum(a.get("ae_usd") or 0 for a in rec.get("attempts", [])) + ((rec.get("review") or {}).get("usd") or 0)


def item_runs(p, root: Path, it: dict) -> list[dict]:
    """The ccx runs this item started since it last went 'doing' (label q:<id>, this project), oldest first: the
    first run and a review's fix round. Found from the runs folder because the item hears of them only when
    run() returns, which a killed `q run` never reaches."""
    from .. import ledger
    import time as _t
    if not p.runs.exists():
        return []
    since = _t.strftime("%Y%m%d-%H%M%S", _t.localtime(float(it.get("updated") or it.get("added") or 0) - 5))
    out = []
    for d in sorted(p.runs.iterdir()):
        if d.name < since or not (d / "run.json").exists():
            continue
        try:
            rec = ledger.read_record(d / "run.json")
            if rec.get("label") == f"q:{it['id']}" and _here(Path(rec.get("cwd") or ""), root):
                out.append(rec)
        except (OSError, ValueError):
            continue
    return out


@functools.lru_cache(maxsize=64)
def _top(root: str) -> str | None:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _here(cwd: Path, root: Path) -> bool:
    """A run in this project: in its folder, or in a ccx worktree of it (workspace.make_worktree's layout, named
    after the repository's top folder, which is not the project folder when the queue lives in a subfolder)."""
    cwd, root = cwd.resolve(), root.resolve()
    if cwd == root:
        return True
    tops = {root}
    top = _top(str(root))
    if top:
        tops.add(Path(top).resolve())
    return any(cwd.parent == t.parent / ".ccx-worktrees" / t.name for t in tops)


def _mode(it: dict) -> dict:
    """An item's read/write mode, decided the same way when `q run` counts its writers and when it runs: from its
    own words (task-split's title for a piece without a brief), never from SPLIT_HINT, whose "JSON list" read as
    analysis and made a plain "Disk backend" piece read-only."""
    return resolve_mode(it.get("mode"), it.get("mode_from") or it.get("brief", ""))


def _tree_fields(rec: dict) -> tuple[dict, str | None]:
    """Fields for a finished run's item: where its work sits. In a ccx worktree its work is not in the project
    folder: one commit there, and whatever waits on it waits for the lead to merge that branch and accept the item
    (`ccx q done <id> --ok 1`; queue.accepted). In the project folder the fields are cleared, so a worktree or a
    verdict left from an earlier run of the item does not stick."""
    cwd = str(rec.get("cwd") or "")
    if "/.ccx-worktrees/" not in cwd.replace("\\", "/"):
        return {"worktree": None, "branch": None, "verdict": None}, None
    from ..lanes import commit_block
    from ..workspace import _git
    sha = commit_block(rec)
    _, branch = _git(Path(cwd), "rev-parse", "--abbrev-ref", "HEAD")
    return {"worktree": cwd, "branch": branch or None, "verdict": None}, sha


def restored(old_run: str, rec: dict) -> str:
    """How an interrupted piece came back (OpenRig's taxonomy): resumed | fresh | decide | failed."""
    if rec.get("kind") in ("quota", "auth", "env", "needs_write", "over_budget", "user_stopped", "interrupted",
                               "check_broken", "no_changes", "no_answer"):
        return "decide"                 # something only the user or the lead can settle
    if not rec.get("ok") or rec.get("kind") in ("check_failed", "timeout", "error"):
        return "failed"
    return "resumed" if rec.get("continued") or rec.get("resumed_from") == old_run else "fresh"


def _one(it: dict, root: Path, caller: str, p, cfg, warm: str | None = None, got: dict | None = None,
         worktree: bool = False) -> dict:
    """Route and run one queue item; write its outcome back. Never raises (a thread must report).
    warm: a lane's last run (ccx/lanes.py), whose session takes this item as a new task; got["rec"]: its record.
    worktree: a write item that runs beside other writers works in its own git worktree (as `ccx batch`)."""
    rec, live = None, None
    try:
        if it.get("budget_usd") is not None and float(it.get("cost_usd") or 0) >= float(it["budget_usd"]):
            wq.update(root, it["id"], status="blocked", summary="its budget is used up")
            return {"id": it["id"], "status": "blocked", "why": "budget"}
        m = _mode(it)                                      # before SPLIT_HINT is added (see _mode)
        spec = {"brief": it["brief"] + ("\n\n" + wq.SPLIT_HINT if it.get("depth", 0) < wq.MAX_DEPTH else ""),
                "to": it.get("to"), "minutes": it.get("minutes"), "kind": it.get("kind"), "mode": m["mode"],
                "mode_source": m["source"], "mode_why": m["why"], "cwd": str(root), "force": True}
        if not spec["minutes"]:
            spec["clarity"] = "goal"                       # switch on routing even without an estimate
        kw, route = resolve(spec, caller, p, cfg)
        if kw is None:
            wq.update(root, it["id"], status="todo", summary=route.get("advice"))
            return {"id": it["id"], "status": "todo", "skipped": route.get("advice")}
        # named up front: `ccx q ls` shows it as `live` while it runs, so a lead can `ccx show <ids> --any --wait`
        # (ledger.new_run_id makes its folder: two pieces started in the same second can no longer draw one id and
        # share a run folder and a ccx/<run> branch)
        live = ledger.new_run_id(p)
        wq.update(root, it["id"], status="doing", agent=kw["to"], live=live)
        resume = it.get("run") if it.get("resume") else None
        left = (max(0.0, float(it["budget_usd"]) - float(it.get("cost_usd") or 0))   # F11: the cap is what it has left
                if it.get("budget_usd") is not None else None)
        brief = (RESUME_NOTE + spec["brief"]) if resume else spec["brief"]
        rec = run(Request(brief=brief, mode=spec["mode"], mode_source=spec["mode_source"], run_id=live,
                          mode_why=spec["mode_why"], cwd=root, caller=caller, label=f"q:{it['id']}",
                          check=it.get("check"), resume_run=resume or warm, continued=bool(warm and not resume),
                          budget_usd=left, worktree=worktree, **kw), p)
        if got is not None:
            got["rec"] = rec
        res = compact(rec)
        status = res.get("status")
        cost = _cost(rec)
        fields = {"run": rec["run_id"], "agent": rec["to"], "summary": (res.get("summary") or "")[:300],
                  "cost_usd": round(float(it.get("cost_usd") or 0) + cost, 6), "resume": False, "live": None}
        where, sha = _tree_fields(rec)
        fields.update(where)
        pieces = wq.parse_split(rec.get("result")) if status == "blocked" else None
        if pieces and it.get("depth", 0) < wq.MAX_DEPTH:
            wq.update(root, it["id"], **fields)
            kids = wq.add_split(root, it, pieces)
            return {"id": it["id"], "split_into": kids}
        if rec.get("kind") == "needs_write":
            fields["status"] = "needs_write"
        elif rec.get("kind") in ("check_failed", "check_broken", "review_failed", "review_issues",
                                 "no_changes", "no_answer") or not rec["ok"] or status in ("failed",):
            fields["status"] = "failed"
        elif status == "blocked":
            fields["status"] = "blocked"
        else:
            fields["status"] = "done"
        wq.update(root, it["id"], **fields)
        out = {"id": it["id"], "status": fields["status"], "run": rec["run_id"]}
        if fields.get("worktree"):
            out.update(worktree=fields["worktree"], branch=fields.get("branch"))
            if sha:
                out["commit"] = sha
        if resume:
            out["restored"] = restored(resume, rec)
        return out
    except Exception as e:  # noqa: BLE001
        why = f"{type(e).__name__}: {e}"[:300]
        row = {"id": it["id"], "status": "failed", "error": why}
        ran = {}
        if not isinstance(rec, dict) and live:          # run() itself raised: its run (named up front) may exist
            rec = _run_record(p, live)
        if isinstance(rec, dict) and rec.get("run_id"):   # it failed after the run: keep the run and what it cost
            ran = {"run": rec["run_id"], "agent": rec.get("to")}
            try:
                ran["cost_usd"] = round(float(it.get("cost_usd") or 0) + _cost(rec), 6)
            except Exception:  # noqa: BLE001
                pass
            row["run"] = rec["run_id"]
        elif live:
            ran = {"run": live}                          # no record yet: still name the run it was started as
            row["run"] = live
        try:
            wq.update(root, it["id"], status="failed", summary=why, live=None, **ran)
        except Exception as e2:  # noqa: BLE001   writing the failure back failed too: still report, never raise
            row["not_recorded"] = f"{type(e2).__name__}: {e2}"[:300]
        return row


def _run_record(p, run_id: str) -> dict | None:
    """The record ccx wrote for run_id, if any (None when it was never written or cannot be read)."""
    try:
        from .. import ledger
        rec = ledger.read_record(Path(p.runs) / run_id / "run.json")
        return rec if isinstance(rec, dict) else None
    except Exception:  # noqa: BLE001
        return None


# an attempt that hit these (runners.py: rate limits are `quota`; delegate.env_failure: the sub-agent could not
# start a process on this machine, which every later item meets too): start nothing new
PRESSURE_KINDS = ("quota", "auth", "env")


def _pressure(rec: dict | None) -> str | None:
    """The quota/auth/env kind any attempt of this run hit (a fallback to another agent included), else None."""
    for x in (rec or {}).get("attempts") or []:
        if x.get("kind") in PRESSURE_KINDS:
            return x["kind"]
    return (rec or {}).get("kind") if (rec or {}).get("kind") in PRESSURE_KINDS else None


def _over_budget(root: Path) -> dict | None:
    q = wq.load(root)
    if q["budget_usd"] is not None and wq.spent(q) >= float(q["budget_usd"]):
        return {"stopped": "budget reached", "spent_usd": wq.spent(q), "budget_usd": q["budget_usd"],
                "ask": "raise it with `ccx q budget <usd>` if the rest is worth it"}
    return None


def _backpressure(kind: str, rec: dict | None) -> dict:
    rid = (rec or {}).get("run_id")
    if kind == "env":
        return {"stopped": "backpressure", "kind": kind, "run": rid,
                "ask": "a run's sub-agent could not start a process on this machine (an environment problem, see "
                       f"`ccx show {rid}`): nothing new was started; tell the person, and once they fixed it run "
                       "`ccx q run --max 1`"}
    return {"stopped": "backpressure", "kind": kind, "run": rid,
            "ask": "a run hit a quota/auth limit (its fallback may have finished the item): nothing new was "
                   "started; run `ccx q run --max 1` when it has reset"}


def _writer(it: dict) -> bool:
    return _mode(it)["mode"] == "write"


def _place(root: Path, new: list[str], alongside: dict[str, bool], st: dict) -> dict[str, bool]:
    """{writer id: True} for the writers about to start that get their own git worktree. Writers that run at the
    same time (these and `alongside`, {writer still running: in a worktree}) must not trample each other: with more
    than one, each new one gets a worktree, as in `ccx batch`. Outside git there is no worktree, and with uncommitted
    changes a worktree (made from the last commit) would miss them: then they share the folder, as before (listed
    in st["shared"]); task-split's `files` keep them apart. st["git"] caches whether the project is in git."""
    if not new or len(new) + len(alongside) < 2:
        return {}
    if st.get("git") is None:
        st["git"] = _in_git(root)
    if not st["git"]:
        return {}
    if not _clean(root):
        st["shared"] += [i for i, tree in alongside.items() if not tree] + new
        return {}
    return {i: True for i in new}


def _waves(a, root: Path, caller: str, p, cfg, width: int, n: int, done: list,
           shared: list | None = None) -> dict | None:
    """Warm lanes: ready items for the same agent and mode share at most n sessions, one after another. An item is
    tried once per `q run` (one routing skipped stays todo and would otherwise be picked again and again). Writers
    of one round get worktrees (_place). A run that hit quota/auth: the lanes start nothing new (their next items
    stay todo), then it stops (`stopped: backpressure`)."""
    gate = bool(getattr(a, "gate", False))
    st = {"git": None, "shared": shared if shared is not None else []}
    started: set[str] = set()
    hit: dict = {}
    while True:
        wq.propagate(root)             # a stuck dependency: what waits for it is dep_blocked, not left todo forever
        stop = _over_budget(root)
        if stop:
            return stop
        batch = [it for it in wq.ready(wq.load(root), gate) if it["id"] not in started]
        if not batch:
            return None
        started.update(it["id"] for it in batch)
        tree = _place(root, [it["id"] for it in batch if _writer(it)], {}, st)

        def step(it, warm):
            if hit:
                return {"id": it["id"], "skipped": "backpressure: a run hit a quota/auth limit or an environment "
                        "problem"}, None
            got: dict = {}
            kw = {"worktree": True} if tree.get(it["id"]) else {}
            res = _one(it, root, caller, p, cfg, warm=warm, got=got, **kw)
            kind = _pressure(got.get("rec"))
            if kind:
                hit.setdefault("stop", _backpressure(kind, got.get("rec")))
            return res, got.get("rec")
        done += lanes.run_lanes(lanes.split(batch, n, lambda it: (it.get("to"), it.get("mode"))), step,
                                lanes.limits(cfg), width)
        wq.close_parents(root)
        if hit:
            return hit["stop"]
        if a.once:
            return None


def _refill(a, root: Path, caller: str, p, cfg, width: int, done: list,
            shared: list | None = None) -> dict | None:
    """At most `width` runs at once; whenever one finishes, the slot goes to the next ready item (submit +
    wait-first-completed, not wave by wave). --once: only the items ready at the start. Ready as the queue says
    (dependencies accepted, --gate, dep_blocked propagated before each fill), and no file shared with a run in
    flight; a writer starting beside other writers gets its own worktree (_place). A run any of whose attempts
    hit quota/auth: nothing new starts, the runs in flight finish, then it stops (`stopped: backpressure`)."""
    gate = bool(getattr(a, "gate", False))
    st = {"git": None, "shared": shared if shared is not None else []}
    started: set[str] = set()           # an item is tried once per `q run` (one routing skipped stays todo)
    stop: dict | None = None
    first = True
    with ThreadPoolExecutor(max_workers=max(1, width)) as ex:
        live: dict = {}                 # future -> (item, got, in a worktree)
        while True:
            if stop is None and (first or not a.once):
                wq.propagate(root)
                stop = _over_budget(root)
                if stop is None:
                    running = [x[0] for x in live.values()]
                    new: list[dict] = []
                    for it in wq.ready(wq.load(root), gate):
                        if len(live) + len(new) >= width:
                            break
                        if it["id"] in started:
                            continue
                        # held_by sees a run as `doing` only once its thread wrote that: check the runs in flight
                        if any(wq.overlaps(it, o) for o in running + new):
                            continue
                        new.append(it)
                    tree = _place(root, [it["id"] for it in new if _writer(it)],
                                  {x[0]["id"]: x[2] for x in live.values() if _writer(x[0])}, st)
                    for it in new:
                        started.add(it["id"])
                        got: dict = {}
                        wt = bool(tree.get(it["id"]))
                        kw = {"worktree": True} if wt else {}
                        live[ex.submit(_one, it, root, caller, p, cfg, None, got, **kw)] = (it, got, wt)
            first = False
            if not live:
                return stop
            fin, _ = wait(list(live), return_when=FIRST_COMPLETED)
            for fu in fin:
                _, got, _ = live.pop(fu)
                done.append(fu.result())
                kind = _pressure(got.get("rec"))
                if kind and stop is None:
                    stop = _backpressure(kind, got.get("rec"))
            wq.close_parents(root)


RUNNER = "run.lock"                     # the live `q run` / `q resume` of this queue: {"pid", "started"}
LAST = "last-run.json"                  # how the last one ended (read by `ccx q ls`, for a --bg run's lead)


def runner(root: Path) -> dict | None:
    """The `q run` working on this queue now, or None (no lock, or its process is gone)."""
    from ..runners import pid_alive
    try:
        info = json.loads((wq.qdir(root) / RUNNER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) and pid_alive(info.get("pid")) else None


def _claim(root: Path) -> dict | None:
    """Take the queue's runner lock; the holder's info if another live `q run` has it (two runners would hand
    the same ready item out twice, and `q resume` would re-dispatch items the other one is running)."""
    wq.qdir(root).mkdir(parents=True, exist_ok=True)
    f = wq.qdir(root) / RUNNER
    for _ in range(2):
        try:
            fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = runner(root)
            if held:
                return held
            try:
                f.unlink()              # left by a `q run` that was killed
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "started": time.time()}, fh)
        return None
    return runner(root) or {"pid": None}


def _release(root: Path) -> None:
    f = wq.qdir(root) / RUNNER
    try:
        if json.loads(f.read_text(encoding="utf-8")).get("pid") == os.getpid():
            f.unlink()
    except (OSError, ValueError):
        pass


def _background(a, root: Path) -> int:
    """`ccx q run --bg`: the same command detached (hidden console on Windows), its output in the queue folder.
    detach() drops --bg from the child's arguments, so the child runs in the foreground of its hidden console."""
    from .common import detach
    held = runner(root)
    if held:
        _out(_busy(held))
        return 2
    log = wq.qdir(root) / f"run-bg-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log"
    detach(sys.argv[1:], log, {})
    _out({"state": "started", "log": str(log),
          "next": "ccx q ls: an item being run shows its run id as `live`; `ccx show <live ids> --any --wait` hands "
                  "back each one as it finishes; `runner` is set while the batch runs, `last_run` says how it ended"})
    return 0


def _busy(held: dict) -> dict:
    return {"stopped": "already running", "pid": held.get("pid"),
            "ask": "another `ccx q run` is working on this queue: follow it with `ccx q ls`, or stop that process "
                   "first"}


def _finish(root: Path, done: list, stop: dict | None, gate: bool = False,
            shared: list | None = None) -> tuple[dict, int]:
    """The summary `q run` prints and its exit code. A stop adds its fields (exit 2) unless it is backpressure and
    nothing is left open: then every item is closed and the summary only notes the limit (exit 0). New keys
    (dep_blocked, waiting, unmerged, shared_folder, restored, backpressure) only when there is something to say."""
    wq.propagate(root)
    q = wq.load(root)
    out = {"results": done, "open": [i for i in q["order"] if q["items"][i]["status"] not in ("done", "failed")],
           "spent_usd": wq.spent(q), "tree": wq.tree(q)}
    stuck = [i for i in q["order"] if q["items"][i]["status"] == "dep_blocked"]
    if stuck:
        # {piece: the pieces that did not finish behind it}: settle those (fix, then `ccx q done <id> --ok 1`)
        out["dep_blocked"] = {i: q["items"][i].get("blocked_by") or [] for i in stuck}
        out["settle"] = ("each piece under dep_blocked waits on the pieces listed with it, which failed, got "
                         "blocked or need write access: fix or redo those, then `ccx q done <id> --ok 1` and "
                         "`ccx q run` again (or drop the waiting pieces)")
    waits = wq.waiting(q, gate)
    if waits:
        out["waiting"] = waits
        out["next"] = ("they wait for your verdict on what they depend on: a piece on a worktree branch lands with "
                       "`ccx q accept <id>` (merge + joint check), one in the project folder with "
                       "`ccx q done <id> --ok 1`; then `ccx q run` again")
    waited_on = {x for w in waits for x in w["on"]}
    loose = [u for u in wq.unmerged(q) if u["id"] not in waited_on]
    if loose:
        out["unmerged"] = loose          # nothing waits on them, but their work is only on these branches
        out.setdefault("next", "land the branches with `ccx q accept " + " ".join(u["id"] for u in loose) + "`")
    if shared:
        out["shared_folder"] = {"ids": list(dict.fromkeys(shared)), "why": SHARED_WHY}
    back = {r["id"]: r["restored"] for r in done if r.get("restored")}
    if back:
        # resumed = same session; fresh = started again; decide = needs you; finished = it had finished already
        out["restored"] = back
    if stop and stop.get("stopped") == "backpressure" and not out["open"]:
        out["backpressure"] = {"kind": stop["kind"], "run": stop.get("run")}
        stop = None
    if stop:
        return {**stop, **out}, 2       # out's spent_usd: counted after the runs in flight finished
    return out, 0


def _run(a, root: Path) -> int:
    if getattr(a, "bg", False):
        return _background(a, root)
    held = _claim(root)
    if held:
        _out(_busy(held))
        return 2
    try:
        out, code = _locked_run(a, root)
    finally:
        _release(root)
    try:
        (wq.qdir(root) / LAST).write_text(json.dumps(
            {"ended": time.time(), "code": code, "stopped": out.get("stopped"), "kind": out.get("kind"),
             "open": out.get("open"), "ask": out.get("ask")}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    _out(out)
    return code


def _locked_run(a, root: Path) -> tuple[dict, int]:
    p = paths()
    cfg = load_config(p)
    caller = _caller(a.caller)
    from ..recover import sweep
    sweep(p)                # runs whose ccx was killed (with the whole `q run`): interrupted, their spend in the ledger
    done: list[dict] = []
    if a.q_cmd == "resume":
        # in progress when the machine stopped: continue the same session where there is one, else start again
        q = wq.load(root)
        for it in q["items"].values():
            if it["status"] == "doing":
                runs = item_runs(p, root, it)
                spent = sum(_cost(r) for r in runs)                      # never reached the item: run() didn't return
                cost = round(float(it.get("cost_usd") or 0) + spent, 6)
                last = runs[-1] if runs else {}
                if (last.get("ok") and last.get("kind") in (None, "ok", "ok_self_checked") and last.get("state") == "finished"
                        and (last.get("result") or {}).get("status") == "done"):
                    # it finished; only writing it back to the queue was cut off. In a worktree: commit it there
                    # and keep its branch, so what waits on it still waits for the lead's merge (as in _one)
                    where, sha = _tree_fields(last)
                    wq.update(root, it["id"], status="done", run=last["run_id"], agent=last.get("to"), cost_usd=cost,
                              summary=str((last.get("result") or {}).get("summary") or "")[:300], resume=False,
                              live=None, **where)
                    row = {"id": it["id"], "status": "done", "run": last["run_id"], "restored": "finished"}
                    if where["worktree"]:
                        row.update(worktree=where["worktree"], branch=where["branch"], **({"commit": sha} if sha else {}))
                    done.append(row)
                    continue
                # the run it was in the middle of (a review's fix round included): its session goes on
                run_id = last["run_id"] if last.get("session_id") else it.get("run")
                wq.update(root, it["id"], status="todo", resume=bool(run_id), run=run_id, cost_usd=cost, live=None)
    width = int(a.max or cfg["defaults"].get("max_parallel", 3))
    gate = bool(getattr(a, "gate", False))
    shared: list[str] = []            # writers that shared the folder (uncommitted changes): see _place
    n = lanes.width(getattr(a, "lanes", None), cfg)
    if n:
        stop = _waves(a, root, caller, p, cfg, width, n, done, shared)
    else:
        stop = _refill(a, root, caller, p, cfg, width, done, shared)
    return _finish(root, done, stop, gate, shared)


def register(sub) -> None:
    qp = sub.add_parser("q", help="the project's durable work queue: add pieces, see them, run every ready one")
    qs = qp.add_subparsers(dest="q_cmd", required=True)
    ad = qs.add_parser("add", help="add a piece (or --plan plan.json with ids and deps)")
    ad.add_argument("title", nargs="?", default="")
    ad.add_argument("--brief")
    ad.add_argument("--dep", action="append", help="id it waits for (repeat)")
    ad.add_argument("--parent")
    ad.add_argument("--check", metavar="CMD")
    ad.add_argument("--minutes", type=float)
    ad.add_argument("--mode", choices=["read", "write"])
    ad.add_argument("--kind", choices=["code", "read", "research", "write"])
    ad.add_argument("--to")
    ad.add_argument("--budget", type=float, help="this item's budget (API-equivalent USD); split parts share it")
    ad.add_argument("--plan", help="plan JSON: {\"tasks\": [{id, title?, brief, deps?, check?, minutes?, mode?, kind?, "
                    "to?, files?}]} or task-split's {\"pieces\": [{id, title, depends_on?, files?}]}; a dependency may "
                    "name a later piece; an unknown id is an error")
    for name, hlp in (("ls", "one line per piece (--long: items as JSON)"), ("tree", "items as a tree")):
        ls = qs.add_parser(name, help=hlp)
        if name == "ls":
            ls.add_argument("--gate", action="store_true", help="list as ready what `q run --gate` would start")
            ls.add_argument("--long", action="store_true", help="every field of every item as JSON (the default is "
                            "one line per piece: id, state, agent, seconds, $)")
    bu = qs.add_parser("budget", help="stop `q run` when the queue has spent this much (API-equivalent USD)")
    bu.add_argument("usd", type=float)
    dn = qs.add_parser("done", help="the lead's verdict on an item (also `ccx verify` on its run)")
    dn.add_argument("id", nargs="+", help="piece id(s), q1 or 1; several with --ok 1 need evidence for each")
    dn.add_argument("--ok", type=int, choices=[0, 1], required=True, help="1 = right, 0 = wrong")
    dn.add_argument("--note", action="append", help='why (repeat; with several ids, one each: "q1: what you checked")')
    ac = qs.add_parser("accept", help="land finished worktree pieces: merge each branch in dependency order, run "
                       "the joint check after each merge, roll that merge back if it fails (never pushes)")
    ac.add_argument("ids", nargs="*", help="piece ids (q1 or 1)")
    ac.add_argument("--all-ready", action="store_true", help="every finished piece still on a worktree branch")
    ac.add_argument("--check", metavar="CMD", help="the joint check run on the merged tree after each merge "
                    "(default: each piece's own check)")
    ac.add_argument("--dry-run", action="store_true", help="show the order and what would be refused; change nothing")
    ac.add_argument("--into-protected", action="store_true", help="the project is on a protected branch (main and "
                    "the like) and the person said yes to merging into it")
    for name, hlp in (("run", "route and run every ready item, in parallel, until nothing is ready"),
                      ("resume", "after a crash or a closed window: items left 'doing' continue, then run")):
        r = qs.add_parser(name, help=hlp)
        r.add_argument("--max", type=int, help="parallel runs (default: defaults.max_parallel)")
        r.add_argument("--once", action="store_true", help="one round only")
        r.add_argument("--lanes", type=int, metavar="N", help="warm lanes: ready items for the same agent share at "
                       "most N sub-sessions, one item after another (default: [lanes] default, 0 = off)")
        r.add_argument("--gate", action="store_true", help="an item's dependents start only after your verdict "
                       "on it (`ccx q done <id> --ok 1`), not as soon as its run reports done (default: off)")
        r.add_argument("--from", dest="caller")
        r.add_argument("--bg", action="store_true", help="run detached; its output goes to a log in the queue "
                       "folder; `ccx q ls` shows each running item's run id (`live`), the runner and how the last "
                       "run ended")
    # --cwd before or after the subcommand (`ccx q --cwd D ls` and `ccx q ls --cwd D`): SUPPRESS keeps a subcommand
    # that was not given it from overwriting the one given before it with None
    for x in qs.choices.values():
        x.add_argument("--cwd", default=argparse.SUPPRESS, help="the project folder (default: the current folder)")
    qp.add_argument("--cwd", help="the project folder (default: the current folder)")
    qp.set_defaults(fn=cmd_q)
