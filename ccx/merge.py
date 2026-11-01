"""`ccx batch --merge` (B3 item 5, measured in M4): small independent write pieces for the same folder, agent, model
and mode become one run instead of one run each. Opt-in: `--merge`, or `[merge] default = true`; without it `ccx batch`
is exactly what it was.

Why: a sub-agent's input is mostly a fixed prefix re-sent on every request (Codex ~18-25k, Claude ~13-15k; about 5
requests a run), so k separate runs pay that start about k times; one run doing the k pieces in a row pays it once
(round-2 PAR10, pieces of the same small size: 5.7-7.4x fewer tokens, work cost about 1/5, wall clock about 2.5x).
Not measured on mixed difficulty: hence opt-in until M4 (plan: .ccx/plans/b3-plan-20261030.md).

Which pieces: write pieces only, each with an estimate (`minutes` <= piece_minutes; a piece without one is not
merged: it may be big), not part of a task-checkpoint step, sharing folder / agent / provider / model rung or tier /
worktree / namecheck, and with no declared path (`paths`) in common; at most max_pieces and total_minutes a group.

What stays per piece: its acceptance check (run by ccx after the merged run), its own entry in the batch's `results`
(one per piece, plan order, with `merged_run` / `merged_with`), and `ccx undo <run> --piece <id>` for the paths it
declared. Shared: the session, the review (triggered and judged on the whole diff), the merged run's ledger row.

After the merged run, per piece:
- it has a check: the check decides (passed = done), whatever the run's overall status;
- no check: its own `[id] done|partial|failed` line decides; no line = `unconfirmed` (not done, not redone: the lead
  looks), partial counts as not done.
If the run stopped for a reason a retry does not fix (quota, auth, `ccx stop`, timeout, the machine, over budget,
needs write), nothing more is started: pieces not shown done are `not_run`, with the run's kind, for `ccx resume`.
Otherwise the pieces not done (and the unconfirmed ones) get one follow-up in the same session; a piece whose check
still fails, or that it still reports failed/partial, becomes a run of its own on the usual ladder. The merged run
never escalates and starts no sub-agents of its own. Every follow-up and spun-off run carries `merge_of` (run.json
and its ledger row), and a `merge` ledger event lists each piece's outcome: what M4 needs to count a plan's cost.
"""
from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

DEFAULTS = {"default": False, "max_pieces": 5, "piece_minutes": 5.0, "total_minutes": 15.0}
# a piece line as models write it: "- [p1] done: ...", "**[p1]** — DONE", "1. `[p1]`: 完成", several on one line
STATUS_LINE = re.compile(r"\[(?P<id>[^\]\n]{1,80})\][*_`]*\s*[:：\-—–]?\s*[*_`]*\s*"
                         r"(?P<st>(?:done|partial|failed)(?![a-z])|完成|部分完成|部分|失败)", re.I)
_ST = {"完成": "done", "部分完成": "partial", "部分": "partial", "失败": "failed"}
TAIL_CHARS = 1500            # of a failed check's output, in the follow-up
NOT_DONE = ("check_failed", "check_broken", "no_changes", "review_issues", "review_failed")
# the merged run's own verdict that no piece can pass on its own check: the review (after its fix round) or ccx
# turned the whole diff down, or nothing changed
HELD = ("check_broken", "no_changes", "review_issues", "review_failed")
# the run stopped for a reason another run would meet again: start nothing more, hand it back to the lead
STOPPED = ("quota", "auth", "user_stopped", "env", "timeout", "over_budget", "max_usd", "needs_write", "interrupted",
           "split", "model")

HEAD = ("[ccx merged pieces] The {n} pieces below are independent small tasks, merged into this one run to save "
        "start-up cost. Do them one at a time, in this order, each inside its own files; finish one (its own check "
        "included, when it names one) before starting the next. If a piece cannot be done, say so for that piece and "
        "go on with the others.\n")
PIECE = "\n### Piece {k} of {n} - id: {id}{files}\n{brief}\n{check}"
FINISH = ("ccx runs each piece's check again afterwards, outside your sandbox, and that result counts: run each "
          "piece's own check once when you finish that piece, not a whole test suite. Status: done when every piece "
          "is done, partial when some are not; never failed or blocked because one piece could not be done. Summary: "
          "first one line per piece, `[id] done|partial|failed: what changed` (at most 15 words each), then anything "
          "the lead must know; put questions in open_questions. List what you ran in commands_run and its outcome in "
          "verification.")
FIX = ("[ccx merged pieces] ccx checked each piece after your run. These are not done:\n{failed}\n"
       "Fix only these pieces; keep the other pieces and the rest of your change as they are. Do not start sub-agents. "
       "Finish with the JSON result again, summary beginning with one `[id] done|partial|failed: ...` line per piece "
       "you worked on.")
REVIEW_LINE = " Begin the summary with one `[id] done|partial|failed: ...` line for each piece the fix touched."


def settings(cfg: dict) -> dict:
    c = cfg.get("merge") or {}
    out = dict(DEFAULTS)
    out["default"] = c.get("default") is True
    for k in ("max_pieces", "piece_minutes", "total_minutes"):
        try:
            out[k] = max(1, int(c[k])) if k == "max_pieces" else max(0.0, float(c[k]))
        except (KeyError, TypeError, ValueError):
            pass
    return out


def choose(merge_flag, lanes_flag, cfg: dict) -> tuple[bool, str | None]:
    """(merge?, error). An explicit flag wins over the other's config default; both explicit: an error; both from
    config: lanes (the older default), merge stays off."""
    lanes_cfg = int((cfg.get("lanes") or {}).get("default", 0) or 0)
    want = settings(cfg)["default"] if merge_flag is None else bool(merge_flag)
    if not want:
        return False, None
    if lanes_flag:                      # lanes asked for on the command line
        if merge_flag is not None:
            return False, ("--merge and --lanes do not mix: --merge puts small pieces in one run, --lanes keeps a "
                           "run per piece in a few sessions; pick one")
        return False, None
    if lanes_flag is None and lanes_cfg and merge_flag is None:
        return False, None              # both from config: lanes, as before [merge] existed
    return True, None


def _norm(f: str) -> str:
    f = str(f).replace("\\", "/").strip()
    while f.startswith("./"):
        f = f[2:]
    return os.path.normcase(f).replace("\\", "/")


def _files(t: dict) -> set[str]:
    """The paths a piece declared: `paths` (a list; in a batch plan `files` is the routing rubric's count)."""
    got = t.get("paths")
    if not isinstance(got, list):
        return set()
    return {_norm(f) for f in got if str(f).strip()}


def key(req, t: dict) -> tuple:
    """What pieces must share to run as one: folder, agent, provider, mode, model rung or tier, worktree, namecheck."""
    return (str(Path(req.cwd).resolve()), req.to, req.provider, req.mode, req.model, req.effort,
            req.tier if not req.model else None, bool(req.worktree), req.namecheck)


def _minutes(t: dict) -> float | None:
    try:
        return float(t["minutes"]) if t.get("minutes") is not None else None
    except (TypeError, ValueError):
        return None


def groups(items: list[tuple], cfg: dict) -> list[list[int]]:
    """items: [(Request, task dict)] in plan order -> groups of indexes, order kept; a piece that may not merge is a
    group of one."""
    s = settings(cfg)
    out: list[list[int]] = []
    open_groups: list[dict] = []
    for i, (req, t) in enumerate(items):
        minutes = _minutes(t)
        if (minutes is None or minutes > s["piece_minutes"] or req.mode != "write" or getattr(req, "resume_run", None)
                or req.task or req.step):
            out.append([i])
            continue
        files = _files(t)
        k = key(req, t)
        for g in open_groups:
            if g["key"] == k and len(g["idx"]) < s["max_pieces"] and g["minutes"] + minutes <= s["total_minutes"] \
                    and not (files and g["files"] & files):
                g["idx"].append(i)
                g["minutes"] += minutes
                g["files"] |= files
                break
        else:
            g = {"key": k, "idx": [i], "minutes": minutes, "files": set(files)}
            open_groups.append(g)
            out.append(g["idx"])
    return out


def piece_ids(reqs: list) -> list[str]:
    """One id per piece, the same in the brief, the record and the results; unique."""
    out: list[str] = []
    for k, r in enumerate(reqs, 1):
        pid = (r.label or "").strip() or f"#{k}"
        while pid in out:
            pid += f"#{k}"
        out.append(pid)
    return out


def _review_of(reqs: list) -> str:
    vals = {str(r.review or "auto") for r in reqs}
    return "on" if "on" in vals else "auto" if "auto" in vals else "off"


_RISK = {None: 0, "low": 0, "visible": 1, "critical": 2}


def _risk_of(reqs: list) -> str | None:
    return max((r.risk for r in reqs), key=lambda x: _RISK.get(x, 0))


def brief(reqs: list, tasks: list[dict]) -> str:
    n = len(reqs)
    parts = [HEAD.format(n=n)]
    for k, (r, t, pid) in enumerate(zip(reqs, tasks, piece_ids(reqs)), 1):
        files = sorted(_files(t))
        parts.append(PIECE.format(k=k, n=n, id=pid, brief=r.brief.strip(),
                                  files=(" (files: " + ", ".join(files) + ")") if files else "",
                                  check=f"Check for this piece: `{r.check}`\n" if r.check else ""))
    return "".join(parts)


def _label(reqs: list) -> str:
    ids = piece_ids(reqs)
    # an evaluation's pieces (label eval-...) keep the prefix, so ledger.is_eval still leaves the merged run out
    pre = "eval-merge:" if all((r.label or "").startswith("eval-") for r in reqs) else "merge:"
    return pre + "+".join(ids)


def _route(reqs: list) -> dict | None:
    """The comparison flags of the pieces (no_ab, trial, bucket), kept so the ledger still tells; no difficulty: the
    merged run teaches routing nothing about any one piece."""
    keep = {k: v for k in ("no_ab", "trial", "bucket") for v in [(reqs[0].route or {}).get(k)] if v}
    return keep or None


def merged_request(reqs: list, tasks: list[dict]):
    """One Request for the group: the first piece's agent / model / folder, the strictest review, the highest risk,
    no check of its own (the pieces' checks run afterwards), no escalation, no sub-agents, the merged Finish text."""
    return dataclasses.replace(reqs[0], brief=brief(reqs, tasks), label=_label(reqs), check=None, escalate=False,
                               allow_subagents=False, parallel=None, review=_review_of(reqs), risk=_risk_of(reqs),
                               route=_route(reqs), task=None, step=None, finish_note=FINISH,
                               budget_usd=None)       # a spending cap is for its own sub-agents: it has none


def self_reported(summary: str | None) -> dict[str, str]:
    """{piece id: done|partial|failed} from the summary's piece lines. The first line for an id wins: the per-piece
    lines come first (FINISH asks so), later notes may mention another piece in passing."""
    out: dict[str, str] = {}
    for m in STATUS_LINE.finditer(summary or ""):
        st = m.group("st")
        out.setdefault(m.group("id").strip().strip("`*_"), _ST.get(st, st.lower()))
    return out


def _piece_files(t: dict, changed: list[str]) -> list[str] | None:
    declared = _files(t)
    if not declared:
        return None
    return [f for f in changed if _under(_norm(f), declared)]


def _under(f: str, declared: set[str]) -> bool:
    return f in declared or any(f.startswith(d.rstrip("/") + "/") for d in declared)


def _summary_lines(p, rec: dict) -> dict[str, str]:
    """Piece lines of a run's summary; for a review fix round's record, the run it fixed first (its lines are the
    fuller ones: the fix round lists only what it touched)."""
    from . import ledger
    said: dict[str, str] = {}
    if rec.get("review_of"):
        try:
            said = self_reported((ledger.load_run(p, rec["review_of"]).get("result") or {}).get("summary"))
        except Exception:  # noqa: BLE001 — the record's own lines still count
            pass
    return {**said, **self_reported((rec.get("result") or {}).get("summary"))}


def _judge(x: dict, said: dict[str, str]) -> None:
    """A piece's state from its check (when it has one) or its own line."""
    if x.get("check"):
        x["ok"] = bool(x["check"]["passed"])
        x["state"] = "done" if x["ok"] else "check_failed"
        return
    st = said.get(x["id"])
    x["said"] = st or x.get("said")
    x["ok"] = st == "done"
    x["state"] = {"done": "done", "partial": "partial", "failed": "failed"}.get(st or "", "unconfirmed")


def finish(rec: dict, reqs: list, tasks: list[dict], p, cfg: dict) -> dict:
    """After the merged run: each piece's check, one follow-up for the pieces not done, a run of its own for each
    still failing; writes `pieces` / `merged` into run.json (the merged run's and, after a review fix round, the
    first one's too), a `merge` ledger event, and returns {"results": [per piece, plan order], "merged": {...}}."""
    import time
    from . import ledger
    from .delegate import Request, compact, run  # noqa: F401
    from .workspace import run_check
    cwd = Path(rec["cwd"])
    timeout = int(cfg["defaults"].get("check_timeout_sec", 900))
    first = rec.get("review_of") or rec["run_id"]       # run() hands back a review fix round's record
    base = compact(rec)
    kind = rec.get("kind")
    ids = piece_ids(reqs)
    said = _summary_lines(p, rec)
    pieces: list[dict] = []
    for r, t, pid in zip(reqs, tasks, ids):
        x = {"id": pid, "paths": sorted(_files(t)) or None, "check_cmd": r.check}
        if r.check:
            x["check"] = run_check(r.check, cwd, timeout)
        _judge(x, said)
        pieces.append(x)
    # how the group ends when no piece can be judged done on its own: the run's own verdict holds for every piece
    held = kind if kind in HELD else None                # the review or ccx said no to the whole diff
    stop_kind = kind if kind in STOPPED else None        # stopped: another run would meet the same wall
    stop_run = rec["run_id"]
    if rec.get("result") is None and not stop_kind and not held:
        stop_kind = kind or "error"                      # it ended without a result: nothing was reported done
    fix_id, fix_runs = None, []
    todo = [x for x in pieces if not x["ok"]]
    if todo and not (stop_kind or held) and rec.get("session_id"):
        lines = []
        for x in todo:
            if x.get("check"):
                tail = str(x["check"].get("tail") or "")[-TAIL_CHARS:]
                lines.append(f"- [{x['id']}] `{x['check_cmd']}` failed (exit {x['check'].get('exit')}):\n```\n{tail}\n```")
            elif x["state"] == "unconfirmed":
                lines.append(f"- [{x['id']}] your summary had no line for it: do it if it is not done, then report it")
            else:
                lines.append(f"- [{x['id']}] you reported it as {x['state']}")
        fix = run(Request(to=rec["to"], brief=FIX.format(failed="\n".join(lines)), resume_run=rec["run_id"],
                          caller=reqs[0].caller, cwd=cwd, check=None, escalate=False, allow_subagents=False,
                          review=_review_of(reqs), risk=_risk_of(reqs), fallback=False, label=rec.get("label") or "",
                          progress=reqs[0].progress, merge_of=first, finish_note=FINISH), p)
        fix_id = fix["run_id"]
        fix_runs = list(dict.fromkeys([fix.get("review_of") or fix_id, fix_id]))
        fkind = fix.get("kind")
        if fkind in STOPPED or fix.get("result") is None:
            stop_kind, stop_run = fkind or "error", fix_id
        elif fkind in HELD:
            held = fkind
        fsaid = _summary_lines(p, fix)
        for x in todo:
            x["fixed_in"] = fix_id
            if x.get("check_cmd"):
                x["check"] = run_check(x["check_cmd"], cwd, timeout)
                _judge(x, {})
            else:
                # its line in the follow-up, else what it said before (a failed / partial stays that)
                _judge(x, {x["id"]: fsaid.get(x["id"]) or said.get(x["id"])} if (fsaid.get(x["id"]) or said.get(
                    x["id"])) else {})
    spun: dict[int, dict] = {}
    for n, (x, r) in enumerate(zip(pieces, reqs)):
        if x["ok"] or stop_kind or held or x["state"] == "unconfirmed":
            continue                       # unconfirmed: no sign it failed; redoing it could undo good work
        # a run of its own, in the folder the merged run worked in (a worktree stays that worktree), with the
        # piece's own settings and ladder; the follow-up above was its one shared chance
        own = run(dataclasses.replace(r, cwd=cwd, worktree=False, resume_run=None, merge_of=first), p)
        x["spun_off"] = own["run_id"]
        spun[n] = own
    if fix_id or spun:
        # later runs changed the same folder: a check that passed before is run again, the last result counts
        for n, x in enumerate(pieces):
            if n not in spun and x.get("check_cmd") and x["ok"]:
                x["check"] = run_check(x["check_cmd"], cwd, timeout)
                _judge(x, {})
    for x in pieces:
        if held:
            x["ok"], x["state"] = False, held
        elif stop_kind and not x["ok"]:
            x["state"] = "not_run"
    changed = list(base.get("files_changed") or [])
    declared = set().union(*[_files(t) for t in tasks]) if tasks else set()
    unattributed = [f for f in changed if declared and not _under(_norm(f), declared)]
    rows = []
    for x in pieces:                       # run.json keeps the verdicts, not the checks' output
        row = {k: v for k, v in x.items() if k != "check"}
        if x.get("check"):
            row["check"] = {k: x["check"].get(k) for k in ("cmd", "passed", "exit")}
        rows.append(row)
    merged = {"pieces": ids, "first_run": first, "fix_run": fix_id, "fix_runs": fix_runs,
              "spun_off": {pieces[n]["id"]: v["run_id"] for n, v in spun.items()},
              **({"unattributed": unattributed} if unattributed else {}),
              **({"stopped": stop_kind, "stopped_run": stop_run} if stop_kind else {}),
              **({"held": held} if held else {})}
    for rid in dict.fromkeys([rec["run_id"], first]):
        try:
            d = ledger.load_run(p, rid)
            d.update(pieces=rows, merged=merged)
            ledger.write_record(p.runs / rid, d)
        except Exception:  # noqa: BLE001 — bookkeeping; the results below still say everything
            pass
    try:
        ledger.append_event(p, {"type": "merge", "run_id": first, "last_run": rec["run_id"], "fix_run": fix_id,
                                "ts": time.time(), **({"stopped": stop_kind} if stop_kind else {}),
                                **({"held": held} if held else {}),
                                "pieces": [{"id": x["id"], "ok": x["ok"], "state": x["state"],
                                            "check_passed": (x.get("check") or {}).get("passed"),
                                            "fixed_in": x.get("fixed_in"), "spun_off": x.get("spun_off")}
                                           for x in pieces]})
    except Exception:  # noqa: BLE001
        pass
    results = []
    for n, (x, t) in enumerate(zip(pieces, tasks)):
        if n in spun:
            out = compact(spun[n])
            # `ccx run` keeps exit 0 for a failed check (its old exit code); a piece whose check failed is not done
            out.update(label=x["id"], merged_run=rec["run_id"], merged_with=ids, spun_off=True,
                       ok=bool(out.get("ok")) and out.get("kind") not in NOT_DONE and
                       out.get("status") in ("done", None))
            if x.get("fixed_in"):
                out["piece_fix"] = x["fixed_in"]
            results.append(out)
            continue
        out = dict(base)
        files = _piece_files(t, changed)
        out.update(label=x["id"], ok=x["ok"], piece_state=x["state"], merged_run=rec["run_id"], merged_with=ids,
                   files_changed=files if files is not None else changed, status=x["state"])
        if files is None:
            out["files_note"] = "this piece declared no paths: these are the whole merged run's files"
        out.pop("check", None)
        out.pop("kind", None)
        out.pop("hint", None)
        if x.get("check"):
            c = x["check"]
            out["check"] = {"cmd": c["cmd"], "passed": c["passed"], "exit": c["exit"]}
        if not x["ok"]:
            if x["state"] == "not_run":
                out["kind"] = stop_kind
                out["hint"] = f"the merged run stopped ({stop_kind}); continue with `ccx resume {stop_run}`"
            elif held:
                out["kind"] = held
                out["hint"] = (f"ccx or its review turned down the merged run as a whole ({held}): its pieces are not "
                               f"taken as done; see `ccx show {rec['run_id']} --full`")
            elif x["state"] == "unconfirmed":
                out["kind"] = "unconfirmed"
                out["hint"] = ("no check and no line of its own in the summary: nothing shows it was done; look at "
                               f"the diff (`ccx show {rec['run_id']} --full`)")
            else:
                out["kind"] = x["state"]
                out["hint"] = f"not done after the merged run and its follow-up; see `ccx show {rec['run_id']} --full`"
        if x.get("fixed_in"):
            out["piece_fix"] = x["fixed_in"]
        results.append(out)
    return {"results": results, "merged": {"run_id": rec["run_id"], **merged}}


def piece_files(rec: dict, piece: str) -> list[str]:
    """`ccx undo <run> --piece <id>`: the paths that piece declared; a ValueError says why there are none."""
    rows = rec.get("pieces") or []
    if not rows:
        raise ValueError(f"run {rec.get('run_id')} is not a merged run (no pieces): undo the whole run")
    row = next((x for x in rows if x.get("id") == piece), None)
    if row is None:
        raise ValueError(f"no piece {piece!r} in run {rec.get('run_id')}: pieces are "
                         + ", ".join(str(x.get("id")) for x in rows))
    if not row.get("paths"):
        raise ValueError(f"piece {piece!r} declared no paths, so its changes cannot be told apart: undo the whole run")
    return list(row["paths"])


def restrict(paths: list[str], declared: list[str]) -> list[str]:
    """The git paths (C-quoted ones decoded) that fall under the declared ones (same file or inside a folder)."""
    from .workspace import _unquote
    d = {_norm(x) for x in declared}
    return [f for f in paths if _under(_norm(_unquote(f)), d)]
