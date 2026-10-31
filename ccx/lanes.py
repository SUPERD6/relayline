"""Warm lanes: small pieces for one agent in one project go one after another into the same sub-session
(as `ccx resume` does: its context and prompt cache stay) instead of each piece paying a fresh start-up.
Only the lanes run side by side.

Round 2 (docs/research/2026-10-25-seven-cores-r2.md section 2.4) measured about 93k input tokens per Codex
run (not a one-off start-up: the run's whole input, mostly cache reads, a fixed prefix of ~18-25k re-sent on each of ~5 requests): ten
pieces as ten runs were the fastest and the most expensive. A lane is a list of pieces; its first piece
starts a session, each later one continues it as a new task (Request.continued). Every piece is still its own ccx
run: its own check, ledger row, undo snapshot and, inside a worktree, its own commit. A piece that fails, or a
session whose last piece read more than [lanes] max_tokens, or that did max_blocks pieces, hands the next piece a fresh session.

Off by default (`[lanes] default = 0`): `ccx batch --lanes N` / `ccx q run --lanes N` switch it on per call."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .workspace import _git

# what ends a lane's session: the next piece then starts a new one
BAD_KINDS = ("quota", "auth", "timeout", "user_stopped", "interrupted", "check_failed", "check_broken",
             "review_failed",
             "review_issues", "needs_write", "over_budget", "split", "no_changes", "no_answer", "env")


def limits(cfg: dict) -> dict:
    c = cfg.get("lanes") or {}
    return {"max_tokens": int(c.get("max_tokens", 200_000)), "max_blocks": int(c.get("max_blocks", 5))}


def width(flag: int | None, cfg: dict) -> int:
    """Lanes asked for: the flag, else [lanes] default; 0 = off (every piece its own session, as before)."""
    n = flag if flag is not None else int((cfg.get("lanes") or {}).get("default", 0))
    return max(0, int(n))


def split(items: list, n: int, key: Callable) -> list[list]:
    """Group by key (project, agent, mode), then cut each group into at most n lanes of nearly equal length,
    keeping the order inside a lane."""
    groups: dict = {}
    for it in items:
        groups.setdefault(key(it), []).append(it)
    lanes = []
    for g in groups.values():
        k = max(1, min(n, len(g)))
        size, extra = divmod(len(g), k)
        i = 0
        for j in range(k):
            m = size + (1 if j < extra else 0)
            lanes.append(g[i:i + m])
            i += m
    return lanes


def used(rec: dict) -> int:
    """Tokens one piece read and wrote (fresh + cache writes + cache reads + output). A continued piece re-reads the
    whole session, so this grows with it; summed over a lane it would mostly count cheap cache reads (measured
    2026-10-25: a warm luna piece read ~2-5k fresh and ~85-115k cached tokens), hence the cap is per piece."""
    from .ledger import sum_usage
    t = sum_usage(rec.get("attempts") or [])
    return t["input"] + t["cached"] + t["output"]


def commit_block(rec: dict) -> str | None:
    """Inside a ccx worktree, one commit per piece, so a piece is undone with `git revert <sha>` there."""
    cwd = rec.get("cwd") or ""
    if rec.get("mode") != "write" or "/.ccx-worktrees/" not in cwd.replace("\\", "/"):
        return None
    wt = Path(cwd)
    _, dirty = _git(wt, "status", "--porcelain")
    if not dirty:
        return None
    _git(wt, "add", "-A")
    state = "ok" if rec.get("ok") and (rec.get("kind") or "ok") == "ok" else (rec.get("kind") or "failed")
    rc, _ = _git(wt, "-c", "user.name=ccx", "-c", "user.email=ccx@localhost", "commit", "-qm",
                 f"ccx run {rec['run_id']}: {rec.get('label') or 'piece'} ({state})")
    if rc != 0:
        return None
    _, sha = _git(wt, "rev-parse", "HEAD")
    return sha or None


def walk(lane: list, step: Callable, lim: dict, n: int = 0) -> list[dict]:
    """Run one lane in order. step(item, warm_run_id or None) -> (result dict, run record or None)."""
    out, warm, blocks, tokens = [], None, 0, 0
    for it in lane:
        res, rec = step(it, warm)
        res = {**res, "lane": n, "warm": bool(warm)}
        if warm:
            res["continued_from"] = warm
        if rec:
            sha = commit_block(rec)
            if sha:
                res["commit"] = sha
        ok = bool(rec and rec.get("ok") and (rec.get("result") or {}).get("status") == "done"
                  and (rec.get("kind") or "ok") not in BAD_KINDS and rec.get("session_id"))
        if not ok:
            warm, blocks, tokens = None, 0, 0
            res["lane_next"] = "fresh: this piece did not finish cleanly"
            out.append(res)
            continue
        blocks += 1
        tokens = used(rec)
        if blocks >= lim["max_blocks"] or tokens >= lim["max_tokens"]:
            res["lane_next"] = (f"fresh: the session reached {blocks} pieces / {tokens} tokens in its last piece "
                                f"(limits {lim['max_blocks']} / {lim['max_tokens']})")
            warm, blocks, tokens = None, 0, 0
        else:
            warm = rec["run_id"]
        out.append(res)
    return out


def run_lanes(lanes: list[list], step: Callable, lim: dict, threads: int) -> list[dict]:
    """Lanes side by side (at most `threads` at once), each one in order; results lane by lane."""
    with ThreadPoolExecutor(max_workers=max(1, min(threads, len(lanes)))) as ex:
        done = list(ex.map(lambda x: walk(x[1], step, lim, x[0]), enumerate(lanes)))
    return [r for lane in done for r in lane]
