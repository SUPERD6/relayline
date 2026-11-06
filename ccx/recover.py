"""What a killed or abandoned run spent, and closing runs whose ccx process is gone.

A sub-agent stopped mid-run (timeout, spending cap, `ccx stop`, Ctrl+C) prints no final usage line: Codex's comes
with turn.completed, Claude's with the result event. Its tokens were spent all the same, so they are read back from
what is there: Claude's assistant events in the stream (or its transcript), Codex's session file (rollout). A run
whose ccx process died leaves a record that says `running` forever; `sweep` closes it as interrupted, with that
usage, so `ccx stats` counts it and `ccx resume` continues it.
"""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from . import ledger
from .config import Paths, claude_home, codex_home
from .runners import pid_alive, usage_dict

STALE_SEC = 600            # no heartbeat for this long, and liveness can't be checked: the run is gone
SWEEP_DAYS = 14            # only runs this young are looked at


def _claude_usage(lines) -> dict:
    """Sum of assistant messages' usage, each message once (one message spans several events/lines)."""
    seen, tot = set(), usage_dict()
    for line in lines:
        if '"usage"' not in line or '"assistant"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = e.get("message") or {}
        u = m.get("usage")
        if e.get("type") != "assistant" or not u or (m.get("id") and m.get("id") in seen):
            continue
        seen.add(m.get("id"))
        cc = u.get("cache_creation") or {}
        for k, v in usage_dict(fresh=u.get("input_tokens", 0) or 0, write=u.get("cache_creation_input_tokens", 0) or 0,
                               write_1h=cc.get("ephemeral_1h_input_tokens", 0) or 0,
                               cached=u.get("cache_read_input_tokens", 0) or 0,
                               out=u.get("output_tokens", 0) or 0).items():
            tot[k] += v
    return tot


def _codex_attempt(sid: str, since: float, home: Path | None = None) -> tuple[dict | None, dict | None]:
    """From the session's rollout file(s): (what its requests since `since` cost, as {input, cached, output}; the
    session's running total of completed work, as its last token_count says). codex-cli 0.164 writes a
    token_usage_record per request, also for a turn that never finished; its token_count total covers only what
    got that far (a turn stopped during its first request was in no token_count at all: real run, 2026-10-25)."""
    from .usage import _ts, walk
    root = (home or codex_home()) / "sessions"
    spent, total = None, None
    for f in walk(root, f"rollout-*{sid}.jsonl") if sid else []:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"token_usage_record"' in line or '"token_count"' in line:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                pl = e.get("payload") or {}
                if e.get("type") == "token_usage_record":
                    t = _ts(e.get("timestamp"))
                    u = pl.get("usage") or {}
                    if t is not None and t >= since and u:
                        spent = spent or {"input": 0, "cached": 0, "output": 0}
                        spent["input"] += int(u.get("input_tokens", 0) or 0)
                        spent["cached"] += int(u.get("cached_input_tokens", 0) or 0)
                        spent["output"] += int(u.get("output_tokens", 0) or 0)
                elif pl.get("type") == "token_count":
                    tot = (pl.get("info") or {}).get("total_token_usage")
                    if tot:
                        total = {"input": int(tot.get("input_tokens", 0) or 0),
                                 "cached": int(tot.get("cached_input_tokens", 0) or 0),
                                 "output": int(tot.get("output_tokens", 0) or 0)}
    return spent, total


def partial_usage(cli: str, sid: str | None, stdout: str = "", cwd: Path | None = None, since: float = 0.0,
                  before: dict | None = None) -> tuple[dict, dict | None]:
    """What an attempt that ended without its final usage line spent: (usage, Codex's running total to remember
    for the session, or None). Claude: its assistant events (stream, else transcript). Codex: its per-request
    records since the attempt began (`since`); older Codex without them: the growth of its running total over
    `before`, the total already counted for the session."""
    if cli == "claude":
        u = _claude_usage(stdout.splitlines())
        if not any(u.values()) and sid and cwd:
            from .transcript import claude_project_dirs
            f = next((d / f"{sid}.jsonl" for d in claude_project_dirs(Path(cwd), claude_home())
                      if (d / f"{sid}.jsonl").exists()), Path(cwd) / f"{sid}.jsonl")
            try:
                u = _claude_usage(f.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                pass
        return (u if any(u.values()) else {}), None
    if cli == "codex" and sid:
        from .agents.codex import _codex_growth
        spent, total = _codex_attempt(sid, since)
        if total and before and total["input"] < before.get("input", 0):
            total = None                   # an older reading than what is counted already: keep the baseline
        if spent:
            return usage_dict(fresh=max(0, spent["input"] - spent["cached"]), cached=spent["cached"],
                              out=spent["output"]), total or before
        if total:
            return _codex_growth(total, before or {}), total
    return {}, None


def close_dead(p: Paths, run_id: str, kind: str, state: str, why: str, by: str,
               attempt_kind: str | None = None) -> dict | None:
    """Close a run whose own ccx process is gone: the attempt it was in the middle of becomes one attempt with the
    usage read back (kind `attempt_kind`, else `kind`), then the final state and its one ledger row. None if
    someone else closed it."""
    from . import learn
    from .agents.codex import _codex_seen
    run_dir = p.runs / run_id
    if not ledger.claim_final(run_dir, by):
        return None
    rec = ledger.load_run(p, run_id)
    cur = rec.get("current") or {}
    if cur and len(rec.get("attempts") or []) <= int(cur.get("n", 0)):
        cli, sid = cur.get("cli") or cur.get("agent"), rec.get("session_id")
        u, total = partial_usage(cli, sid, cwd=Path(rec["cwd"]) if rec.get("cwd") else None,
                                 since=float(cur.get("t0") or 0), before=cur.get("before") or _codex_seen(rec).get(sid))
        ae = learn.price_usd(p, cur["agent"], cur["model"], u, ts=cur.get("t0")) if u else None
        rec.setdefault("attempts", []).append({
            "agent": cur["agent"], "tier": cur.get("tier"), "rung": cur.get("rung"), "model": cur.get("model"),
            "effort": cur.get("effort"), "ok": False, "kind": attempt_kind or kind,
            "seconds": round(max(0.0, time.time() - float(cur.get("t0") or time.time())), 1), "usage": u,
            "cost_usd": None, "ae_usd": round(ae, 6) if ae is not None else None, "error": why,
            "auth_problem": False, "retry_after": None, "session_id": sid, "recovered": True,
            **({"credential_guard": cur["credential_guard"]} if "credential_guard" in cur else {}),
            **({"codex_total": total} if total else {})})
    last = (rec.get("attempts") or [{}])[-1]
    rec.update({key: last[key] for key in ("agent", "model", "effort") if key in last})
    rec.update(state=state, kind=kind, ok=False, error=why)
    ledger.write_record(run_dir, rec)
    ledger.append(p, rec)
    return rec


def _gone(rec: dict, run_dir: Path, now: float) -> bool:
    if rec.get("ccx_pid") and rec.get("host") == socket.gethostname():
        return not pid_alive(rec["ccx_pid"])
    beats = [f.stat().st_mtime for f in (run_dir / "beat", run_dir / "run.json") if f.exists()]
    return bool(beats) and now - max(beats) > STALE_SEC


def sweep(p: Paths, now: float | None = None) -> list[str]:
    """Close every `running` record whose ccx process is gone (dead pid on this machine, or no heartbeat for
    STALE_SEC) as interrupted. Cheap: only run folders with no ledger row are opened. Returns their ids."""
    now = now or time.time()
    if not p.runs.exists():
        return []
    done = {r.get("run_id") for r in ledger.rows(p) if not r.get("type")}
    cutoff = time.strftime("%Y%m%d", time.localtime(now - SWEEP_DAYS * 86400))
    out = []
    for d in p.runs.iterdir():
        if d.name in done or d.name[:8] < cutoff or not (d / "run.json").exists():
            continue
        try:
            rec = ledger.read_record(d / "run.json")
        except (OSError, ValueError):
            continue
        if rec.get("state") != "running" or not _gone(rec, d, now):
            continue
        try:
            if close_dead(p, d.name, "interrupted", "interrupted",
                          "its ccx process ended before the run finished (closed window, crash or kill); "
                          f"continue with `ccx resume {d.name}`", "sweep", attempt_kind="killed"):
                out.append(d.name)
        except (OSError, ValueError, KeyError):
            continue
    return out
