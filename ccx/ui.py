"""`ccx ui`: a live view on this machine (proposal G1) and the manager's board (K6). Showing it never writes and
never calls a model. Two kinds of clicks change something, both same-origin only: yes or no on a suggested note
(H5, POST /api/suggestion), and a button that runs one of a fixed set of ccx commands (stop, verify, resume, undo,
q done / budget / accept / resume, run --mode write for a needs_write run; RUNS). Such a button is two requests: /api/act/prepare
names the button (never a command), the server answers the exact command and a one-time nonce, the page shows it
and asks again, and /api/act/run with the nonce runs it once (execute: argv, no shell, no window).

Across projects: the runs of every project (as before), plus the queue of every project in the `ccx projects`
catalog, its approval lines, and the catalog's other projects as one quiet list. This month: what sub-agents spent
first, then report.summarize's saving below it (measured, or a model estimate labelled as one, measured totals so
far about even), read in the background every 5 minutes.

What it shows, all read from files ccx and the two tools already write — no model is ever called and the quota
probe is never started (an open page must not cost anything):
  run records      <hub>/ccx/runs/<id>/run.json (+ prompt.md for the task text); live ones are 'running'
  verdicts         <hub>/ccx/ledger.jsonl rows with type=verify (read incrementally)
  work queues      <project>/.ccx/queue/queue.jsonl of every project a recent run worked in (and --project)
  live tokens      the sub-agent's own session file while it runs (Codex rollout-*.jsonl, Claude <session>.jsonl);
                   its last write time is the heartbeat
  quota            quota.pace() over the readings already kept (Codex session logs, <hub>/ccx/quota.jsonl)
  suggested notes  <hub>/ccx/mem-suggestions.json, the pending ones (H5), each with a yes and a no button
  leads            main Claude / Codex conversations written to in the last 15 minutes: model, own sub-agents

Tests and evaluations are marked `test` and the page hides them unless asked ('show evaluations and tests'): runs
`ledger.is_eval` leaves out (eval-*, --no-ab, ccx's probes, dismissed), runs in the system's temporary folder or in
a project's .ccx folder (unless the hub itself is in one: then it is all scratch), and projects, leads and
discussions there.

The home page (P2-10, project_map, /api/data `maps`): one project on one map — the agents and what went between them
(runs sent, board messages, discussions), shared memory linked to the runs whose brief carried a note (read from the
run's prompt.md, never guessed) and how they ended, one receipt per run (tier, rung, cost, the check's cover and
whether the run edited its own tests, review, verdict), this week's spend summed from the records by rung (other ways
only from the published table, never estimated). The overview that was the home page is at #/all.

Grouping: a project = the folder a run worked in (worktrees fold back into their repo). A task = one project's work
queue (pieces = its items, split items drill down a level, at most 3), or the runs one lead conversation sent out
(pieces = runs; a fix round or a follow-up stays on its piece). Strings shown to people are keys into
ui_static/strings.json; data (titles, summaries) is sent as plain text and the page escapes it.

Server: standard-library HTTP on 127.0.0.1, a random port. The token rides after '#' in the URL (never sent to the
server, never in a request line) and comes back in an X-CCX-Token header on every data request; Host must be
127.0.0.1 or localhost with this port (DNS rebinding), there are no CORS headers, and the page loads only its own
files (CSP). The page polls every 3 s and says 'still open' every 10 s (and when it is shown again or focused); 60 s
without that and the server exits, 5 minutes when the page's last word was that its tab is hidden.

The decision card (U1) asks /api/judge/<run> for the change from ccx's own snapshots (undo.json -> end.json or
undo.json's `after`), never from the live folder; read-only `git diff` of two object ids, capped in size.

The agents' conversation (U2, docs/board.md): each project's board (<project>/.ccx/board.jsonl, what `ccx say` /
`ccx reply` write) is read incrementally, read only; /api/data carries what waits for the person (a thread stopped
by the machine-message cap, a message that asks the person), /api/conv/<project> the threads, newest first, capped
in size. Board text is written by agents: the page escapes it. The one write (I1): the person's reply, through the
same two steps as a button (/api/say/prepare answers what will be written and a one-time nonce, /api/say/run
writes it once), at most SAY_MAX characters (longer is refused, never cut), written by board.post as the person
(from user, via ui) like `ccx reply`, never run: no command, no shell.

Measured & where tokens go (B1, ccx/tokenflow.py): /api/tokens (period, project, tests) answers the published
numbers, the person's own, and one ledger across Claude and Codex grouped by task with each run's own child sessions;
/api/leadcost (agent, session) parses one lead conversation the ledger names, only when asked, with the functions
behind `ccx lead --breakdown` / `--cache`. Both read only, capped in size.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import importlib
import json
import os
import posixpath
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qs, urlsplit

from . import agents, board
from . import queue as wq
from .config import Paths, claude_home, codex_home, load_config
from .ledger import is_eval
from .usage import _ts
from .workspace import _unquote

STATIC = Path(__file__).resolve().parent / "ui_static"
INTERNAL = ("review:", "quota-probe", "selftest", "handoff-from-transcript")
STALE_MIN = 10                # a running run with no write for this long may be stuck
LEAD_MIN = 15                 # a lead conversation counts as current when written to this recently
POLL_S, BEAT_S, IDLE_S, FIRST_BEAT_S = 3, 10, 60, 120
HIDDEN_IDLE_S = 300           # a page that said it is hidden (browsers beat ~1/min there): idle this long, then exit
QUOTA_EVERY_S, LEADS_EVERY_S, MONTH_EVERY_S = 60, 15, 300
ACT_TTL_S = 120               # a prepared action must be confirmed within this long, once
TITLE_MAX = 90
VERDICTS_TO_KNOW = 30         # verdicts before "how much was saved" is worth a number


# ------------------------------------------------------------------ reading files (cached by mtime)
class Reader:
    """Keeps what it read between polls: a file is parsed again only when its mtime or size changed, and the
    ledger and live session files are read from where the last read stopped."""

    def __init__(self, p: Paths):
        self.p = p
        self._json: dict[Path, tuple] = {}
        self._tail: dict[tuple, dict] = {}
        self._busy: set[str] = set()
        self._found: dict[str, Path | None] = {}
        self._timed: dict[str, tuple[float, object]] = {}
        self._notes: dict[Path, tuple] = {}         # prompt.md -> the shared notes its brief carried (P2-10)

    def json_file(self, f: Path):
        try:
            st = f.stat()
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size)
        hit = self._json.get(f)
        if hit and hit[0] == key:
            return hit[1]
        try:
            val = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return hit[1] if hit else None          # half-written: keep the last good copy
        self._json[f] = (key, val)
        return val

    def lines(self, f: Path, fold, start):
        """Fold each new complete line into a running state (fold(state, line) -> state); returns the state."""
        try:
            size = f.stat().st_size
        except OSError:
            return start
        key = (f, fold.__name__)                     # one file can be read for different things
        t = self._tail.get(key)
        if t is None or size < t["pos"]:            # new, or rewritten (e.g. ccx repair): start over
            t = self._tail[key] = {"pos": 0, "state": start, "rest": b""}
        if size > t["pos"]:
            try:
                with open(f, "rb") as fh:
                    fh.seek(t["pos"])
                    chunk = fh.read(size - t["pos"])
            except OSError:
                return t["state"]
            t["pos"] = size
            data = t["rest"] + chunk
            *full, t["rest"] = data.split(b"\n")
            for raw in full:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    t["state"] = fold(t["state"], line)
        return t["state"]

    def cfg(self) -> dict:
        return self.every("cfg", 30, lambda: load_config(self.p))

    def every(self, key: str, seconds: float, make):
        hit = self._timed.get(key)
        if hit and time.time() - hit[0] < seconds:
            return hit[1]
        val = make()
        self._timed[key] = (time.time(), val)
        return val

    def find(self, key: str, search):
        if key not in self._found or self._found[key] is None:
            self._found[key] = search()
        return self._found[key]


def _verdict_rows(state: dict, line: str) -> dict:
    if '"verify"' in line:
        try:
            r = json.loads(line)
        except ValueError:
            return state
        if r.get("type") == "verify" and r.get("run_id"):
            state[r["run_id"]] = r                  # the last one wins
    return state


def project_root(cwd: str | None) -> Path | None:
    """The project a run worked in: worktrees fold back into their repo, then the nearest folder with a .ccx
    folder or a .git; else the folder itself. No subprocess, no writes."""
    if not cwd:
        return None
    try:
        c = Path(cwd).resolve()                     # one spelling per folder (Windows short names, symlinks)
    except OSError:
        c = Path(cwd)
    parts = c.parts
    if ".ccx-worktrees" in parts:                   # <parent>/.ccx-worktrees/<repo>/<run_id> (delegate.make_worktree)
        i = parts.index(".ccx-worktrees")
        if i + 1 < len(parts):
            c = Path(*parts[:i]) / parts[i + 1]
    home = Path.home()
    for d in (c, *c.parents):
        if d == home and c != home:                 # ~/.ccx is ccx's own settings, not a project
            break
        if (d / ".ccx" / "context.md").exists() or (d / ".ccx" / "queue").is_dir() or (d / ".git").exists():
            return d
    return c


def scratch_roots(p: Paths) -> list[Path]:
    """Where tests and evaluations work: the system's temporary folder. None when the hub itself is in it (a
    throwaway hub, e.g. an A/B round's: there everything is scratch, so nothing is set apart)."""
    import tempfile
    try:
        tmp = Path(tempfile.gettempdir()).resolve()
        hub = p.hub.resolve()
    except OSError:
        return []
    return [] if hub == tmp or tmp in hub.parents else [tmp]


def is_scratch(path: str | Path | None, roots: list[Path]) -> bool:
    """A folder in the temporary folder or inside a project's .ccx folder (ccx's own trials): not real work."""
    if not path:
        return False
    c = _resolved(str(path))
    return ".ccx" in c.parts or any(c == r or r in c.parents for r in roots)


@functools.lru_cache(maxsize=4096)
def _resolved(path: str) -> Path:                   # the page asks every 3 s about the same few hundred folders
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def is_test(rec: dict, roots: list[Path]) -> bool:
    """A run that was a test, an evaluation, a probe or a dismissed leftover: nobody waits on it."""
    return bool(is_eval({**rec, "no_ab": (rec.get("route") or {}).get("no_ab")}) or is_scratch(rec.get("cwd"), roots))


def _pid(root: Path) -> str:
    return "p" + hashlib.sha1(str(root).lower().encode("utf-8")).hexdigest()[:10]


def _sid(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text)[:64]


def _brief_of(run_dir: Path) -> str:
    try:
        text = (run_dir / "prompt.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.search(r"## Task\n(.*?)(?:\n## Finish|\Z)", text, re.S)
    if m:
        return m.group(1).strip()
    return "\n".join(text.splitlines()[1:]).strip()       # a follow-up: the brief follows its first line


def _short(text: str) -> str:
    line = next((x.strip() for x in (text or "").splitlines() if x.strip()), "")
    return line if len(line) <= TITLE_MAX else line[:TITLE_MAX - 1] + "…"


# ------------------------------------------------------------------ live usage from the sub-agent's session file
def _fold_codex(state: dict, line: str) -> dict:
    if '"token_count"' in line:
        try:
            info = ((json.loads(line).get("payload") or {}).get("info") or {})
        except ValueError:
            return state
        tot = info.get("total_token_usage")
        if tot:
            state = {**state, "tokens": int(tot.get("input_tokens", 0) or 0) + int(tot.get("output_tokens", 0) or 0)}
    return state


def _fold_claude(state: dict, line: str) -> dict:
    if '"assistant"' in line and '"usage"' in line:
        try:
            e = json.loads(line)
        except ValueError:
            return state
        m = e.get("message") or {}
        u = m.get("usage") or {}
        if e.get("type") == "assistant" and u and m.get("id") not in state["ids"]:
            state["ids"].add(m.get("id"))
            state["tokens"] += sum(int(u.get(k, 0) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                                    "cache_read_input_tokens", "output_tokens"))
            state["model"] = m.get("model") or state.get("model")
    return state


def _session_file(rd: Reader, agent: str, sid: str) -> Path | None:
    """The session file of `sid` under the agent's own folder (its adapter's home). Only Codex and Claude Code
    sessions are read; the layout is each tool's own (see their adapters' session_files)."""
    def search():
        home = agents.get(agent).home() if agent in agents.NAMES and agents.get(agent).home else None
        if home is None:
            return None
        if agent == "codex":
            root = home / "sessions"
            from .usage import walk
            hits = sorted(walk(root, f"rollout-*{sid}.jsonl"),   # newest last, a \\?\ prefix aside
                          key=lambda f: Path(str(f).removeprefix("\\\\?\\")))
        elif agent == "claude":
            root = home / "projects"
            hits = sorted(root.glob(f"*/{sid}.jsonl")) if root.exists() else []
        else:
            hits = []
        return hits[-1] if hits else None
    return rd.find(f"{agent}:{sid}", search)


def cli_of(name: str | None, cfg: dict) -> str | None:
    """The CLI an agent name runs on: itself, or for a provider (e.g. deepseek) the CLI it is configured on."""
    pv = (cfg.get("providers") or {}).get(name or "")
    return str(pv.get("agent", "claude")) if pv is not None else name


def live(rd: Reader, rec: dict) -> dict:
    """Tokens so far and the last sign of life of a running run."""
    beat = 0.0
    run_dir = rd.p.runs / rec["run_id"]
    for f in (run_dir, run_dir / "run.json"):
        try:
            beat = max(beat, f.stat().st_mtime)
        except OSError:
            pass
    out = {"beat": beat, "tokens": None}
    sid = rec.get("session_id")
    cli = cli_of(rec.get("to"), rd.cfg())
    if sid and cli in ("codex", "claude"):
        f = _session_file(rd, cli, sid)
        if f:
            try:
                out["beat"] = max(beat, f.stat().st_mtime)
            except OSError:
                pass
            st = rd.lines(f, _fold_codex, {"tokens": 0}) if cli == "codex" else \
                rd.lines(f, _fold_claude, {"tokens": 0, "ids": set(), "model": None})
            out["tokens"] = st["tokens"]
    return out


# ------------------------------------------------------------------ one run -> one piece on the chart
def _usd(rec: dict) -> float:
    return round(sum(a.get("ae_usd") or 0 for a in rec.get("attempts") or [])
                 + float((rec.get("review") or {}).get("usd") or 0), 6)


def _tokens(rec: dict) -> int:
    return sum(int(v or 0) for a in rec.get("attempts") or [] for v in (a.get("usage") or {}).values())


def _q(s: str) -> str:
    """Quote one argument for the copied command line (double quotes work in PowerShell, cmd and sh)."""
    s = str(s).replace('"', "'")
    return f'"{s}"' if re.search(r"\s|[&|<>^;]", s) or not s else s


# K6: the ccx commands a button may run from the page (`run: true`); anything else is shown to copy. Each spends
# (starts a sub-agent: runs in the background) or only records something (runs at once, waits for its answer).
# `undo` puts back the files of one write run (from ccx's own snapshot; new files are moved aside, never deleted)
# and starts nothing; `q accept` merges finished worktree pieces and runs their checks, so it runs in the
# background like a spending one, but it starts no agent (a demo hub may run it: it only touches demo data).
RUNS = {("verify",): "record", ("stop",): "record", ("q", "done"): "record", ("q", "budget"): "record",
        ("handoff",): "record",       # U7: the switch-lead panel; writes a note in the project, starts nothing
        ("undo",): "record", ("q", "accept"): "long",
        ("resume",): "spend", ("run",): "spend", ("q", "resume"): "spend"}
FILLS = ("{reason}", "{note}", "{usd}")          # filled in by the page's form, checked by the server (fill())
REASONS = ("unfinished", "wrong", "overreach", "other")


def _op(argv: list[str]) -> str | None:
    """'record' | 'long' | 'spend' for a ccx command a button may run, else None (shown to copy only)."""
    if not argv or argv[0] != "ccx":
        return None
    words = [x for x in argv[1:] if not x.startswith("-")]
    if argv[1:3] == ["q", "--cwd"]:                  # ccx q --cwd ROOT resume
        words = ["q", *argv[4:5]]
    return RUNS.get(tuple(words[:2])) or RUNS.get(tuple(words[:1]))


def _btn(label: str, cmd, style: str = "", prose: bool = False) -> dict:
    """A button. cmd is an argv list (a ccx command: maybe runnable from the page) or a string (copy only). prose:
    the string is a message for the person to give the lead, not a command (the page labels it so)."""
    if isinstance(cmd, str):
        out = {"label": label, "cmd": cmd, "style": style, "run": False}
        if prose:
            out["prose"] = True
        return out
    op = _op(cmd)
    out = {"label": label, "cmd": " ".join(x if x in FILLS else _q(x) for x in cmd), "argv": cmd, "style": style,
           "run": op is not None, "spends": op == "spend"}
    if op == "long":
        out["bg"] = True                             # runs in the background, spends nothing (q accept)
    return out


LEAD_FIXES = ("Run {rid} still fails its independent review after one fix round: check each [must] item in "
              "`ccx show {rid}` (review.issues) against the diff, fix the real ones yourself and drop the wrong ones, "
              "then `ccx verify {rid} --ok 1|0`.")


_START: dict | None = None


def start_hint() -> dict:
    """The empty overview's two lines: the same first delegation README and `ccx setup` suggest, and `ccx demo`
    (only once that command exists in this ccx)."""
    global _START
    if _START is None:
        from .setup import first_command
        try:
            from .cli import build_parser
            import argparse
            sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
            demo = "ccx demo" if "demo" in sub.choices else None
        except Exception:  # noqa: BLE001 — the hint is a nicety
            demo = None
        _START = {"first": first_command("codex"), "demo": demo}
    return _START


def _act(rec: dict, verdict: dict | None, now: float, beat: float | None) -> dict | None:
    """What the person is asked to do about this run, or None. kind: decide (red) | review (amber)."""
    rid = rec["run_id"]
    res = rec.get("result") or {}
    kind = rec.get("kind")
    show = _btn("b_see", f"ccx show {rid} --full")
    if rec.get("state") == "running":
        if beat and now - beat > STALE_MIN * 60:
            return {"kind": "decide", "what": "a_stale", "why": ["w_stale", {"m": int((now - beat) // 60)}],
                    "buttons": [show, _btn("b_stop", ["ccx", "stop", rid], "bad")]}
        return None
    if verdict is not None or (rec.get("verdict") or {}).get("ok") is not None or rec.get("dismissed"):
        return None                                  # judged (by the person, the lead or ccx's soft verdict), dismissed
    if kind == "needs_write":
        return {"kind": "decide", "what": "a_needs_write", "why": ["w_needs_write", {}],
                "buttons": [show, _btn("b_allow_write",
                                       ["ccx", "run", "--mode", "write", "--cwd", rec.get("cwd") or ".",
                                        f"Make the changes run {rid} listed as needed (see ccx show {rid} --full)"],
                                       "primary"),
                            _btn("b_not_needed", ["ccx", "verify", rid, "--ok", "0", "--reason", "other", "--note",
                                                  "not needed"])]}
    if kind == "review_failed":
        issues = "; ".join((rec.get("review") or {}).get("issues") or [])[:300]
        return {"kind": "decide", "what": "a_review_failed", "why": ["w_review_failed", {"by": _who_rung(
            (rec.get("review") or {}).get("by"))}],
                "issues": (rec.get("review") or {}).get("issues") or [],
                # the same rule as the run's hint and the agent-delegate skill: the lead checks each [must] against
                # the diff and fixes the real ones itself (a message to paste to the lead, copy only); another round
                # is the secondary choice, as it costs a run. The person may also overrule the review: an ok verdict
                # with a note saying so (ccx verify), which starts nothing
                "buttons": [show, _btn("b_lead_fixes", LEAD_FIXES.format(rid=rid), "primary", prose=True),
                            _btn("b_one_more", ["ccx", "resume", rid, "The review still finds: " + issues]),
                            _btn("b_accept_anyway", ["ccx", "verify", rid, "--ok", "1", "--note",
                                                     "review overruled: the person accepted it"], "good"),
                            _btn("b_myself", ["ccx", "verify", rid, "--ok", "0", "--reason", "wrong", "--note",
                                              "handled by hand"])]}
    if kind == "check_broken":                       # the command tested nothing: fix the check, not the code
        c = rec.get("check") or {}
        return {"kind": "decide", "what": "a_check_broken", "why": ["w_check_broken", {"cmd": c.get("cmd") or "",
                                                                                         "why": c.get("broken") or ""}],
                "buttons": [show, _btn("b_new_check", f'ccx resume {rid} "what to test" --check "..."', "primary")]}
    if kind == "no_changes":                         # said done/partial, changed nothing: met already, or not done
        return {"kind": "decide", "what": "a_no_changes", "why": ["w_no_changes", {}],
                "buttons": [show, _btn("b_make_change", ["ccx", "resume", rid, "nothing was changed: make the change"],
                                       "primary"),
                            _btn("b_already_met", ["ccx", "verify", rid, "--ok", "1", "--note",
                                                   "the task was already met"])]}
    if kind == "check_failed":
        c = rec.get("check") or {}
        return {"kind": "decide", "what": "a_check_failed", "why": ["w_check_failed", {"cmd": c.get("cmd") or "",
                                                                                         "exit": c.get("exit")}],
                "buttons": [show, _btn("b_fix_check", ["ccx", "resume", rid, "the check fails: fix it"], "primary")]}
    if kind in ("quota", "timeout"):
        ra = ((rec.get("attempts") or [{}])[-1]).get("retry_after")
        return {"kind": "decide", "what": "a_quota" if kind == "quota" else "a_timeout",
                "why": ["w_quota" if kind == "quota" else "w_timeout", {"at": ra}],
                "buttons": [_btn("b_resume", ["ccx", "resume", rid], "primary"), show]}
    if kind == "over_budget":
        return {"kind": "decide", "what": "a_over_budget", "why": ["w_over_budget", {}],
                "buttons": [show, _btn("b_more_budget", ["ccx", "resume", rid, "--budget", "{usd}"], "primary")]}
    if rec.get("auth_problem"):
        return {"kind": "decide", "what": "a_auth", "why": ["w_auth", {"agent": rec.get("to")}],
                "buttons": [_btn("b_login", f"{rec.get('to')} login", "primary")]}
    if kind == "env":
        # the machine, not the task (delegate.env_failure): trying again meets the same wall, so no "Try again";
        # the fix (delegate.env_hint's, in the page's language) says what to do, doctor checks the setup (copy only,
        # not run from the page), and ccx resume continues once it is fixed
        agent = rec.get("to") or ""
        err = rec.get("env_error") or ""
        if not err:                                  # no reason kept: the exit code, else no empty brackets
            ex = ((rec.get("attempts") or [{}])[-1]).get("exit")
            err = f"exit {ex}" if ex not in (None, "") else ""
        why = (("w_env_codex" if agent == "codex" else "w_env") if err else
               ("w_env_codex_noerr" if agent == "codex" else "w_env_noerr"))
        from .delegate import env_cause
        if env_cause(err, agent):                   # Codex's sandbox UAC prompt cancelled: named as the hint names it
            why = "w_env_codex_uac"
        return {"kind": "decide", "what": "a_env",
                "why": [why, {"agent": agent, "err": err, "rid": rid}],
                "buttons": [show, _btn("b_doctor", "ccx doctor", "primary")]}
    if not rec.get("ok") or res.get("status") in ("failed", "blocked"):
        return {"kind": "decide", "what": "a_failed", "why": ["w_failed", {}],
                "buttons": [show, _btn("b_retry", ["ccx", "resume", rid, "Try again: " + (
                    res.get("summary") or rec.get("error") or "")[:200]], "primary")]}
    if res.get("status") in ("done", "partial"):
        return {"kind": "review", "what": "a_review", "why": None, "reasons": True,
                "buttons": [_btn("b_ok", ["ccx", "verify", rid, "--ok", "1"], "good"),
                            _btn("b_bad", ["ccx", "verify", rid, "--ok", "0", "--reason", "{reason}", "--note",
                                           "{note}"], "bad"),
                            _btn("b_see_change", _diff_cmd(rec))]}
    return None


def fill(argv: list[str], given: dict | None) -> list[str]:
    """The button's argv with the page's form values put in, each checked: a reason from REASONS, a note of at most
    200 printable characters, an amount 0 < USD <= 10000. Every value is one argument (no shell ever sees it)."""
    given = given or {}
    reason = given.get("reason") if given.get("reason") in REASONS else "other"
    note = re.sub(r"[\x00-\x1f\x7f]", " ", str(given.get("note") or "")).strip()[:200] or reason
    if "{reason}" not in argv:
        note = f"{reason}: {note}" if note != reason else reason
    out = []
    for x in argv:
        if x == "{reason}":
            x = reason
        elif x == "{note}":
            x = note
        elif x == "{usd}":
            try:
                usd = float(given.get("usd"))
            except (TypeError, ValueError):
                raise ValueError("an amount in USD") from None
            if not 0 < usd <= 10000:
                raise ValueError("an amount between 0 and 10000 USD")
            x = f"{usd:.2f}"
        out.append(x)
    return out


def _diff_cmd(rec: dict) -> str:
    files = (rec.get("result") or {}).get("files_changed") or []
    cwd = rec.get("cwd") or "."
    return f"git -C {_q(cwd)} diff -- " + " ".join(_q(f) for f in files[:8]) if files else \
        f"ccx show {rec['run_id']} --full"


def _who_rung(rung: str | None) -> str:
    if not rung:
        return ""
    bits = str(rung).split(":")
    return " · ".join(b for b in bits[:2] if b)


STEP = {"sent": 0, "working": 1, "self": 2, "check": 3, "review": 4, "verdict": 5, "done": 6}


def _undo_state(rd: Reader, rec: dict) -> tuple[bool, float | None]:
    """(can be undone, when it was undone): a finished write run with ccx's undo snapshot (undo.json) can be put
    back from the page (`ccx undo <id> --apply`) until it has been (undone.json). Two file checks, no git."""
    if rec.get("state") == "running" or rec.get("mode") != "write":
        return False, None
    run_dir = rd.p.runs / str(rec["run_id"])
    done = rd.json_file(run_dir / "undone.json")
    if isinstance(done, dict):
        return False, float(done.get("ts") or 0) or None
    return (run_dir / "undo.json").is_file(), None


UNDO_LIST_MAX = 30                 # files named in the page's undo confirm box


def _chain_running(p: Paths, run_id: str) -> str | None:
    """A running run that goes on from this one (a resume or review fix round: resumed_from, followed back a few
    links, or its undo snapshot's chain_from), or None. Undoing then would change files under a working agent."""
    if not p.runs.exists():
        return None
    for d in p.runs.iterdir():
        rec = _read_json(d / "run.json")
        if not isinstance(rec, dict) or rec.get("state") != "running" or d.name == run_id:
            continue
        snap = _read_json(d / "undo.json")
        if isinstance(snap, dict) and snap.get("chain_from") == run_id:
            return d.name
        cur, seen = rec, 0
        while isinstance(cur, dict) and cur.get("resumed_from") and seen < 6:
            if cur["resumed_from"] == run_id:
                return d.name
            cur, seen = _read_json(p.runs / str(cur["resumed_from"]) / "run.json"), seen + 1
    return None


def undo_preview(p: Paths, run_id: str) -> dict:
    """What the page's "Undo this run" would do now, from `ccx undo <id>`'s own dry run, for the confirm box.
    LookupError (said on the page) when the page must not offer it: the run or a link going on from it is running,
    it was undone already, git cannot list the files, or the undo would also put back files this run did not leave
    changed (a later commit, the person's own edits elsewhere, other runs' work: `ccx undo` restores everything
    that differs from the run's base). Those go to the terminal, where the dry run lists them first. Checked when
    the button is prepared and again just before it runs."""
    from .workspace import undo
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id or ""):
        raise LookupError("bad run id")
    run_dir = p.runs / run_id
    rec = _read_json(run_dir / "run.json")
    if not isinstance(rec, dict):
        raise LookupError(f"no ccx run {run_id}")
    if rec.get("state") == "running":
        raise LookupError("this run is running again: undo it after it has finished")
    if (run_dir / "undone.json").exists():
        raise LookupError("this run was undone already: reload")
    busy = _chain_running(p, run_id)
    if busy:
        raise LookupError(f"run {busy} goes on from this one and is running: undo after it has finished")
    try:
        dry = undo(p, run_id, apply=False)
    except (OSError, ValueError, KeyError) as e:
        raise LookupError(f"ccx undo could not read this run's snapshot: {e}") from e
    if dry.get("git_error"):
        raise LookupError(dry["git_error"])
    if dry.get("nothing_to_undo"):
        raise LookupError(dry["nothing_to_undo"])
    own = judge(p, run_id).get("changed")
    if own is None:
        raise LookupError(f"ccx has no record of the tree this run left, so the page cannot check what undo would "
                          f"touch: `ccx undo {run_id}` in a terminal lists it first")
    fold = (lambda s: s.casefold()) if os.name == "nt" else (lambda s: s)
    mine = {fold(c["path"]) for c in own}
    touched = [_unquote(x) for x in [*dry["restore"], *dry["move_aside"]]]
    extra = [x for x in touched if fold(x) not in mine]
    if extra:
        more = f" and {len(extra) - 5} more" if len(extra) > 5 else ""
        raise LookupError(f"undo would also put back files this run did not leave changed ({', '.join(extra[:5])}"
                          f"{more}): a later commit, your own edits or another run's work. `ccx undo {run_id}` in a "
                          "terminal lists everything first; undo there if that is what you want")
    return {"restore": [_unquote(x) for x in dry["restore"]][:UNDO_LIST_MAX],
            "move_aside": [_unquote(x) for x in dry["move_aside"]][:UNDO_LIST_MAX],
            "chain_from": dry.get("chain_from")}


def merge_preview(p: Paths, argv: list[str]) -> None:
    """The page's Merge button (`ccx q accept <id> --cwd <root>`, run in the background): `q accept --dry-run`
    first, so a refusal (a protected branch checked out, uncommitted changes, another writer, ...) comes back to
    the page at once instead of only into the background job's log. LookupError with its reasons."""
    from .accept import accept
    try:
        root = Path(argv[argv.index("--cwd") + 1])
    except (ValueError, IndexError):
        raise LookupError("the Merge button names no project folder: reload") from None
    out, _ = accept(p, load_config(p), root, [argv[3]], dry_run=True)
    if out.get("refused"):
        raise LookupError("ccx q accept would refuse: " + "; ".join(f"{r.get('id')}: {r.get('why')}"
                                                                   for r in out["refused"]))
    if not out.get("plan"):
        raise LookupError("there is nothing to merge for this piece: reload")


def piece_of_run(rd: Reader, rec: dict, verdict: dict | None, now: float, title: str) -> dict:
    atts = rec.get("attempts") or []
    last = atts[-1] if atts else {}
    first = rec.get("first_rung") or ""
    model = last.get("model") or (first.split(":")[1] if first.count(":") >= 1 else "")
    res = rec.get("result") or {}
    running = rec.get("state") == "running"
    lv = live(rd, rec) if running else {"beat": None, "tokens": None}
    act = _act(rec, verdict, now, lv["beat"])
    v = verdict if verdict is not None else rec.get("verdict")
    skip = []
    if not rec.get("check"):
        skip.append(STEP["check"])
    if not rec.get("review") or (rec.get("review") or {}).get("verdict") == "not-run":
        skip.append(STEP["review"])
    if running:
        status, step = "run", STEP["working"]
    elif act and act["kind"] == "decide":
        status = "decide"
        step = {"check_failed": STEP["check"], "check_broken": STEP["check"], "review_failed": STEP["review"]}.get(rec.get("kind"), STEP["working"])
    elif act and act["kind"] == "review":
        status, step = "review", STEP["verdict"]
    elif v is not None and v.get("ok") is False:
        status, step = "fail", STEP["verdict"]
    else:
        status, step = "done", STEP["done"]
    secs = round(sum(a.get("seconds") or 0 for a in atts), 1)
    if running:
        secs = round(now - float(rec.get("ts") or now), 1)
    rv = rec.get("review") or {}
    piece = {
        "id": _sid(rec["run_id"]), "run_id": rec["run_id"], "title": title, "worker": rec.get("to"),
        "model": model, "effort": last.get("effort"), "mode": rec.get("mode"), "status": status, "step": step,
        "skip": skip, "secs": secs, "usd": _usd(rec), "tokens": lv["tokens"] if running and lv["tokens"] else _tokens(rec),
        "live": running, "beat": lv["beat"], "ts": rec.get("ts"),
        "reviewer": _who_rung(rv.get("by")) if rv.get("verdict") not in (None, "not-run") else None,
        "summary": res.get("summary") or rec.get("error") or "", "files": res.get("files_changed") or [],
        "verification": _clip(res.get("verification"), JUDGE_TEXT_MAX),     # U1: what the agent says it checked
        "check": check_view(rec.get("check")),                              # ... and what ccx ran (cmd, exit, tail)
        "review": ({"verdict": rv.get("verdict"), "issues": rv.get("issues") or []} if rv else None),
        "verdict": ({"ok": v.get("ok"), "soft": bool(v.get("soft")), "reason": v.get("reason")} if v else None),
        "attempts": len(atts), "rungs": [a.get("rung") for a in atts],
        "native": [{"id": k[-8:], "tokens": int(sum(x.values())) if isinstance(x, dict) else 0}
                   for k, x in (rec.get("codex_children") or {}).items()],
        "act": act,
        "ctl": [_btn("b_stop", ["ccx", "stop", rec["run_id"]], "bad")] if running and not act else [],
    }
    can_undo, undone = _undo_state(rd, rec)
    if can_undo:                                     # shown beside the change on the card (U1), two steps as always
        piece["ctl"].append({**_btn("b_undo", ["ccx", "undo", rec["run_id"], "--apply"], "bad"),
                             "note": "act_undo_note"})
    if undone:
        piece["undone"] = undone
    return piece


def hist_of_run(rec: dict, title: str) -> list[dict]:
    """The 'history' timeline of one run: sent, escalations, review, outcome, verdict."""
    out = [{"ts": rec.get("ts"), "k": "h_sent", "p": {"t": title, "w": rec.get("to") or "",
                                                       "m": ((rec.get("attempts") or [{}])[0]).get("model") or ""}}]
    t = float(rec.get("ts") or 0)
    prev = None
    for a in rec.get("attempts") or []:
        t += float(a.get("seconds") or 0)
        if prev and a.get("rung") != prev.get("rung"):
            out.append({"ts": t, "k": "h_moved", "p": {"from": prev.get("rung") or "", "to": a.get("rung") or ""}})
        prev = a
    rv = rec.get("review") or {}
    if rv.get("verdict") in ("pass", "issues", "unclear"):
        out.append({"ts": t, "k": "h_review_" + rv["verdict"], "p": {"by": _who_rung(rv.get("by")), "t": title},
                    "tone": "bad" if rv["verdict"] == "issues" else "ok" if rv["verdict"] == "pass" else ""})
    if rec.get("state") == "finished":
        k = rec.get("kind")
        st = (rec.get("result") or {}).get("status")
        key = ("h_" + k) if k in ("needs_write", "check_failed", "check_broken", "review_failed", "quota", "timeout",
                                  "over_budget", "no_changes", "env") \
            else "h_done" if rec.get("ok") and st in ("done", "partial") else "h_failed"
        out.append({"ts": t, "k": key, "p": {"t": title}, "tone": "ok" if key == "h_done" else "bad"})
    v = rec.get("verdict") or {}
    if v.get("ok") is not None:
        out.append({"ts": v.get("ts") or t, "k": "h_verdict_ok" if v["ok"] else "h_verdict_bad",
                    "p": {"t": title, "soft": bool(v.get("soft"))}, "tone": "ok" if v["ok"] else "bad"})
    return out


# ------------------------------------------------------------------ lead conversations
def _first_user_text(f: Path, agent: str) -> str:
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh):
                if n > 400:
                    break
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                text = ""
                if agent == "claude" and e.get("type") == "user" and not e.get("isSidechain"):
                    c = (e.get("message") or {}).get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
                    text = c if isinstance(c, str) else ""
                elif agent == "codex" and (e.get("payload") or {}).get("type") == "user_message":
                    text = (e.get("payload") or {}).get("message") or ""
                lines = [x for x in text.splitlines() if x.strip() and not x.lstrip().startswith("<")]
                if lines:                                # "1" or "ok" names nothing: the run's own title is better
                    return _short("\n".join(lines)) if len(lines[0].strip()) >= 6 else ""
    except OSError:
        pass
    return ""


def _tail_lines(f: Path, nbytes: int = 200_000) -> list[str]:
    try:
        with open(f, "rb") as fh:
            fh.seek(max(0, f.stat().st_size - nbytes))
            return fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _claude_leads(since: float, mine: set[str]) -> list[dict]:
    root = claude_home() / "projects"
    out = []
    for f in (root.glob("*/*.jsonl") if root.exists() else []):
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        if mt < since or f.stem in mine:
            continue
        model, cwd = "", ""
        for line in reversed(_tail_lines(f)):
            if '"assistant"' in line and '"model"' in line:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("isSidechain"):
                    continue
                model, cwd = (e.get("message") or {}).get("model") or "", e.get("cwd") or ""
                break
        if not model or model.startswith("<"):
            continue
        helpers = []
        sub = f.parent / f.stem / "subagents"
        for h in (sub.glob("agent-*.jsonl") if sub.is_dir() else []):
            try:
                if h.stat().st_mtime >= since:
                    helpers.append({"id": h.stem[-8:], "model": _last_model(h)})
            except OSError:
                pass
        out.append({"agent": "claude", "model": model, "session": f.stem, "cwd": cwd, "last": mt,
                    "helpers": helpers})
    return out


def _last_model(f: Path) -> str:
    for line in reversed(_tail_lines(f, 60_000)):
        if '"model"' in line:
            try:
                return ((json.loads(line).get("message") or {}).get("model")) or ""
            except ValueError:
                continue
    return ""


def _codex_leads(since: float, mine: set[str]) -> list[dict]:
    root = codex_home() / "sessions"
    days = {time.strftime("%Y/%m/%d", time.localtime(t)) for t in (since, time.time())}
    out = []
    for d in days:
        for f in ((root / d).glob("rollout-*.jsonl") if (root / d).is_dir() else []):
            try:
                mt = f.stat().st_mtime
                with open(f, encoding="utf-8", errors="replace") as fh:
                    meta = (json.loads(fh.readline() or "{}").get("payload") or {})
            except (OSError, ValueError):
                continue
            sid = meta.get("id") or f.stem
            if mt < since or sid in mine or meta.get("originator") == "codex_exec":
                continue
            src = meta.get("source")
            if isinstance(src, dict) and src.get("subagent"):
                continue
            model = ""
            for line in reversed(_tail_lines(f)):
                if '"turn_context"' in line:
                    try:
                        model = ((json.loads(line).get("payload") or {}).get("model")) or ""
                    except ValueError:
                        continue
                    break
            from .usage import codex_children
            kids = codex_children(sid, since)
            out.append({"agent": "codex", "model": model, "session": sid, "cwd": meta.get("cwd") or "",
                        "last": mt, "helpers": [{"id": k[-8:], "model": ""} for k in kids]})
    return out


def leads(rd: Reader, mine: set[str]) -> list[dict]:
    def make():
        since = time.time() - LEAD_MIN * 60
        found = []
        for fn in (_claude_leads, _codex_leads):
            try:
                found += fn(since, mine)
            except Exception:  # noqa: BLE001 — a tool's odd file never breaks the page
                pass
        return sorted(found, key=lambda x: -x["last"])[:6]
    return rd.every("leads", LEADS_EVERY_S, make)


def _lead_of_session(rd: Reader, sid: str, caller: str | None) -> dict:
    """agent/model/title of the conversation that sent runs out (read once per session)."""
    def look():
        for agent in ([caller] if caller in ("claude", "codex") else []) + ["claude", "codex"]:
            f = _session_file(rd, agent, sid)
            if f:
                model = _last_model(f) if agent == "claude" else ""
                if agent == "codex":
                    for line in reversed(_tail_lines(f)):
                        if '"turn_context"' in line:
                            try:
                                model = ((json.loads(line).get("payload") or {}).get("model")) or ""
                            except ValueError:
                                continue
                            break
                return {"agent": agent, "model": model, "title": _first_user_text(f, agent)}
        return {"agent": caller if caller in ("claude", "codex") else None, "model": "", "title": ""}
    return rd.every(f"lead:{sid}", 30, look)


# ------------------------------------------------------------------ quota (readings only, never the probe)
def _fold_rate(state: list, line: str) -> list:
    """Codex quota samples, as usage.codex_events reads them (token_count lines carry rate_limits)."""
    if '"rate_limits"' not in line:
        return state
    try:
        e = json.loads(line)
    except ValueError:
        return state
    pl = e.get("payload") or {}
    t = _ts(e.get("timestamp"))
    if pl.get("type") != "token_count" or t is None:
        return state
    for win in ("primary", "secondary"):
        w = (pl.get("rate_limits") or {}).get(win) or {}
        if w.get("used_percent") is not None:
            state.append({"ts": t, "agent": "codex", "window": win, "used": w["used_percent"] / 100,
                          "resets_at": w.get("resets_at"), "window_minutes": w.get("window_minutes")})
    return state


def _codex_rates(rd: Reader, days: float = 8) -> list[dict]:
    """quota.codex_readings(), but only the new part of each session file is read on later calls."""
    root = codex_home() / "sessions"
    since = time.time() - days * 86400
    out = []
    for k in range(int(days) + 2):
        d = root / time.strftime("%Y/%m/%d", time.localtime(time.time() - k * 86400))
        for f in (d.glob("rollout-*.jsonl") if d.is_dir() else []):
            try:
                if f.stat().st_mtime < since:
                    continue
            except OSError:
                continue
            out += [r for r in rd.lines(f, _fold_rate, []) if r["ts"] >= since]
    return out


def quota_view(rd: Reader, wait: bool = True) -> list[dict]:
    """Pace of every quota window from the readings already on disk. wait=False (the server): the first read of
    a week of Codex logs takes seconds, so it runs in the background and the page shows quota a moment later."""
    def make():
        from . import quota
        out = []
        for agent, readings in (("codex", _codex_rates(rd)), ("claude", quota.claude_readings(rd.p))):
            for win, w in (quota.pace(readings) if readings else {}).items():
                out.append({"agent": agent, "window": win, **{k: w.get(k) for k in (
                    "used", "projected", "resets_at", "hours_left", "reading_age_min", "note")},
                    "minutes": next((r.get("window_minutes") for r in readings if r["window"] == win), None)})
        return out

    return _later(rd, "quota", QUOTA_EVERY_S, make, wait, [])


def _later(rd: Reader, key: str, seconds: float, make, wait: bool, empty):
    """rd.every(key, seconds, make), except that with wait=False a slow first read runs in the background and the
    page gets `empty` (then the last value) until it is done. A failure gives `empty`: the page shows the rest."""
    def safe():
        try:
            return make()
        except Exception:  # noqa: BLE001 — odd files never break the page
            return empty
    hit = rd._timed.get(key)
    if wait or (hit and time.time() - hit[0] < seconds):
        return rd.every(key, seconds, safe)
    if key not in rd._busy:
        rd._busy.add(key)

        def bg():
            try:
                rd._timed[key] = (time.time(), safe())
            finally:
                rd._busy.discard(key)
        threading.Thread(target=bg, daemon=True).start()
    return hit[1] if hit else empty


# ------------------------------------------------------------------ K6: across projects, this month
def _catalog(rd: Reader) -> dict[Path, dict]:
    """The `ccx projects` catalog by resolved folder (read again only when the file changes)."""
    from . import projects
    cat = rd.json_file(projects.store(rd.p)) or {}
    return {_resolved(str(e["path"])): e for e in cat.get("projects") or [] if isinstance(e, dict) and e.get("path")}


def _rules(rd: Reader, e: dict) -> list[dict]:
    """Lines of the project's rule files that speak of approval or a freeze, quoted (projects.approval_rules)."""
    from . import projects
    return rd.every(f"rules:{e['path']}", MONTH_EVERY_S,
                    lambda: [{"file": Path(r["file"]).name, "line": r["line"], "text": r["text"]}
                             for r in projects.approval_rules(e, 6)])


def _level(rd: Reader, e: dict | None) -> str | None:
    """A catalog project's autonomy level (L0/L1/L2) when ccx has that module (K4: level_for(entry, p=) ->
    {level, ...}); else, or for a folder outside the catalog, nothing is shown."""
    if not e:
        return None

    def look():
        try:
            autonomy = importlib.import_module(__package__ + ".autonomy")     # by sys.modules: tests can hide it
            v = autonomy.level_for(e, p=rd.p)
        except Exception:  # noqa: BLE001 — not there (yet) or odd: no badge
            return None
        v = v.get("level") if isinstance(v, dict) else v
        return str(v) if re.fullmatch(r"L\d", str(v or "")) else None
    return rd.every(f"level:{e['path']}", 30, look)


def _inbox(rd: Reader) -> int | None:
    """How many issues wait to be taken in when ccx has that module (K5); else None and nothing is shown."""
    def look():
        try:
            intake = importlib.import_module(__package__ + ".intake")
            v = intake.pending(rd.p)
        except Exception:  # noqa: BLE001
            return None
        return v if isinstance(v, int) else len(v) if hasattr(v, "__len__") else None
    return rd.every("inbox", 30, look)


def month_start(now: float) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def month_view(rd: Reader, wait: bool = True) -> dict | None:
    """This calendar month's sub-agent spend and the saving `ccx report` computes (the same rule: measured by
    `ccx trial` when it has enough tasks, else a model estimate against the lead's own price). Read from the
    ledger in the background every few minutes; None until the first read is done."""
    def make():
        from . import report
        now = time.time()
        start = month_start(now)
        s = report.summarize(rd.p, report.collect(rd.p, max(1 / 24, (now - start) / 86400), include_lead=False))
        t = s["totals"]
        return {"since": start, "sub_usd": t["sub_ae"], "runs": t["runs"], "saving": t["saving"],
                "kind": t["saving_kind"], "ci95": t["saving_ci95"], "n": t["saving_n"]}
    return _later(rd, "month", MONTH_EVERY_S, make, wait, None)


# ------------------------------------------------------------------ U7: who leads a project, and switching
LEAD_NAMES = ("claude", "codex", "dsh")          # `ccx handoff --to` choices that can sit in the lead's chair
LEAD_LABEL = {"claude": "b_cont_claude", "codex": "b_cont_codex", "dsh": "b_cont_dsh"}
HANDOFFS_MAX = 50


def handoff_history(rd: Reader, root: Path) -> list[dict]:
    """The project's handoffs between leads, oldest first, from the header ccx writes on each file in
    .ccx/handoffs/ (project.handoff): {ts, from, to, file}. Read only; each file's first line only."""
    from .project import _HEAD, _order

    def look():
        d = root / ".ccx" / "handoffs"
        try:
            files = sorted(d.glob("*.md"), key=_order)[-HANDOFFS_MAX:] if d.is_dir() else []
        except OSError:
            return []
        out = []
        for f in files:
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    m = _HEAD.match(fh.readline())
            except OSError:
                continue
            if not m:
                continue
            try:
                ts = time.mktime(time.strptime(m.group(3)[:19], "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, OverflowError):
                continue
            out.append({"ts": ts, "from": _field(m.group(1)), "to": _field(m.group(2)),
                        "file": f.relative_to(root).as_posix()})
        return sorted(out, key=lambda h: h["ts"])
    d = root / ".ccx" / "handoffs"
    try:                                          # read again only when a handoff was added or removed
        key = ("handoffs", d.stat().st_mtime_ns)
    except OSError:
        return []
    hit = rd._json.get(d)
    if hit and hit[0] == key:
        return hit[1]
    val = look()
    rd._json[d] = (key, val)
    return val


def lead_switch(rd: Reader, root: Path, tasks: list[dict]) -> dict:
    """U7, a project's switch-lead panel: the current lead (the newest of: the last handoff's receiver, the lead of
    the most recent task), when each lead worked (from the handoff records), and one button per other lead that runs
    `ccx handoff --to <it> --by <current> --cwd <project>` through the usual prepare / confirm (the server adds
    --from-transcript when the current lead's session file for this folder exists). No lead known: no buttons."""
    hist = handoff_history(rd, root)
    cands = [(h["ts"], h["to"]) for h in hist if h["to"] in LEAD_NAMES]
    cands += [(float(t.get("last") or t.get("asked") or 0), (t.get("lead") or {}).get("agent")) for t in tasks
              if (t.get("lead") or {}).get("agent") in LEAD_NAMES]
    newest = max(cands, key=lambda c: c[0]) if cands else None
    current = newest[1] if newest else None
    # the periods come from the handoff records; a task led by someone else after the last handoff starts one more
    periods, agent, since = [], (hist[0]["from"] if hist else current), None
    for h in hist:
        periods.append({"agent": agent, "since": since, "until": h["ts"]})
        agent, since = h["to"], h["ts"]
    if hist and current and current != agent and newest[0] > since:
        periods.append({"agent": agent, "since": since, "until": newest[0]})
        agent, since = current, newest[0]
    if agent:
        periods.append({"agent": agent, "since": since, "until": None})
    targets = [a for a in ("claude", "codex") if a != current]
    if current != "dsh" and rd.every("dsh-bin", 60, _dsh_ready):
        targets.append("dsh")
    ctl = []
    if current:
        for i, a in enumerate(targets):
            b = _btn(LEAD_LABEL[a], ["ccx", "handoff", "--to", a, "--by", current, "--cwd", str(root)],
                     "primary" if i == 0 else "")
            b["handoff"] = {"to": a, "by": current}
            ctl.append(b)
    return {"current": current, "ctl": ctl, "periods": periods[-12:], "switches": hist[-12:]}


def _dsh_ready() -> bool:
    """DeepSeek's own agent (dsh) is offered as a lead only where it is installed."""
    try:
        from .runners import find_bin
        return bool(find_bin("dsh"))
    except Exception:  # noqa: BLE001
        return False


def lead_hist(sw: dict, task: dict) -> list[dict]:
    """The task timeline's lead lines: who led when it was asked, and every switch since (read only)."""
    asked = float(task.get("asked") or 0)
    out = []
    at = next((p["agent"] for p in sw.get("periods") or []
               if (p["since"] is None or p["since"] <= asked) and (p["until"] is None or asked < p["until"])), None)
    if at:
        out.append({"ts": asked, "k": "h_lead_at", "p": {"w": at}})
    for h in sw.get("switches") or []:
        if h["ts"] >= asked:
            out.append({"ts": h["ts"], "k": "h_lead_switch", "p": {"w": h["from"], "w2": h["to"], "f": h["file"]},
                        "tone": "lead"})
    return out


# ------------------------------------------------------------------ the whole page's data
def _unmerged(it: dict) -> bool:
    """A finished worktree piece whose branch was not merged by `ccx q accept` and whose worktree is still there
    (no git here: a branch merged by hand whose worktree is gone shows no Merge button)."""
    wt = it.get("worktree")
    return bool(wt) and not it.get("merged") and Path(wt).exists()


def _queue_pieces(rd: Reader, root: Path, q: dict, recs: dict, verdicts: dict, now: float) -> list[dict]:
    items = q["items"]

    def one(it: dict) -> dict:
        rec = recs.get(it.get("run")) if it.get("run") else None
        title = it.get("title") or _short(it.get("brief") or "")
        if rec:
            pc = piece_of_run(rd, rec, verdicts.get(rec["run_id"]), now, title)
        else:
            pc = {"id": _sid(it["id"]), "run_id": it.get("run"), "title": title, "worker": it.get("agent") or it.get("to"),
                  "model": "", "status": "queued", "step": STEP["sent"], "skip": [], "secs": 0,
                  "usd": float(it.get("cost_usd") or 0), "tokens": 0, "live": False, "summary": it.get("summary") or "",
                  "files": [], "check": None, "review": None, "verdict": None, "attempts": 0, "rungs": [], "native": [],
                  "act": None, "ctl": [], "ts": it.get("added")}
        pc["id"], pc["qid"] = _sid(it["id"]), it["id"]
        pc["usd"] = round(float(it.get("cost_usd") or pc["usd"] or 0), 6)
        st = it.get("status")
        if st == "todo":
            pc.update(status="queued", act=None)
        elif st == "doing" and pc["status"] not in ("run", "decide"):
            pc["status"] = "run"
        elif st == "done" and it.get("verdict") is not None:
            pc.update(status="done" if it["verdict"] else "fail", step=STEP["done"], act=None)
            if it["verdict"] is True and _unmerged(it):
                # one order in the CLI (`ccx q ls`) and here: the verdict first, then the merge (`ccx q accept`)
                pc["ctl"] = [{**_btn("b_q_merge", ["ccx", "q", "accept", it["id"], "--cwd", str(root)], "primary"),
                              "note": "act_merge_note"}, *pc.get("ctl", [])]
        elif st == "done" and pc.get("act") and pc["act"]["kind"] == "review":
            b = pc["act"]["buttons"]
            b[0] = _btn(b[0]["label"], ["ccx", "q", "done", it["id"], "--ok", "1", "--cwd", str(root)], b[0]["style"])
            b[1] = _btn(b[1]["label"], ["ccx", "q", "done", it["id"], "--ok", "0", "--note", "{note}", "--cwd",
                                        str(root)], b[1]["style"])
            if it.get("worktree") and not it.get("merged"):     # after the verdict comes the merge: said now, too
                pc["act"]["then"] = f"ccx q accept {it['id']}"
        elif st == "dep_blocked":
            # waits on a piece that did not finish: the lead settles that one (`ccx q done <id> --ok 1`)
            pc.update(status="decide", act={"kind": "decide", "what": "a_q_dep_blocked",
                                            "why": ["w_q_dep_blocked", {"s": ", ".join(it.get("blocked_by") or [])}],
                                            "buttons": [_btn("b_tree", "ccx q tree")]})
        elif st in ("needs_write", "blocked", "failed") and not pc.get("act"):
            show = _btn("b_see", f"ccx show {it['run']} --full") if it.get("run") else _btn("b_tree", "ccx q tree")
            pc.update(status="decide", act={"kind": "decide", "what": "a_q_" + st, "why": ["w_q_" + st,
                                                                                             {"s": it.get("summary") or ""}],
                                            "buttons": [show, _btn("b_q_resume", ["ccx", "q", "--cwd", str(root),
                                                                                  "resume"], "primary")]})
        act = pc.get("act")
        if act and act.get("what") == "a_review_failed" and it.get("verdict") is None:
            # overruling the review, or handling it by hand, is a verdict on the queue piece (`ccx q done`, which
            # records the run's verdict too): a run verdict alone leaves the piece failed, unmergeable, still listed
            for i, b in enumerate(act["buttons"]):
                if b["label"] == "b_accept_anyway":
                    act["buttons"][i] = _btn(b["label"], ["ccx", "q", "done", it["id"], "--ok", "1", "--note",
                                                          "review overruled: the person accepted it", "--cwd",
                                                          str(root)], b["style"])
                elif b["label"] == "b_myself":
                    act["buttons"][i] = _btn(b["label"], ["ccx", "q", "done", it["id"], "--ok", "0", "--note",
                                                          "handled by hand", "--cwd", str(root)], b["style"])
            if it.get("worktree") and not it.get("merged"):
                act["then"] = f"ccx q accept {it['id']}"
        kids = wq.children(q, it["id"])
        if kids:
            pc["children"] = [one(k) for k in kids]
            if st == "split":                         # waits on its parts: they carry the status, a level down
                pc.update(status="split", act=None, step=STEP["working"])
        return pc
    return [one(items[i]) for i in q["order"] if not items[i].get("parent")]


# ------------------------------------------------------------------ P2-10: one project, one map (the home page)
MAP_RECEIPTS_MAX = 20         # receipts on the map, newest first (the task pages keep every run)
MAP_THREADS_MAX = 12          # board threads plus discussions in the middle
MAP_NOTES_MAX = 8             # notes the memory column names
NOTES_HEAD = "Shared notes that may bear on this task"      # delegate._brief_notes' first line in prompt.md
_NOTE_LINE = re.compile(r"^- #(\d+) \(")


def brief_notes(rd: Reader, run_dir: Path) -> list[int]:
    """The shared notes a run's brief carried, read from the brief itself (prompt.md: NOTES_HEAD, then one
    '- #N (topic): text' line per note): which run used which note is never guessed from times or names."""
    f = run_dir / "prompt.md"
    try:
        st = f.stat()
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size)
    hit = rd._notes.get(f)
    if hit and hit[0] == key:
        return hit[1]
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    seqs: list[int] = []
    i = text.find(NOTES_HEAD)
    if i >= 0:
        for line in text[i:].splitlines()[1:]:
            if not line.strip() or line.startswith("#"):        # the block ends at a blank line or the next heading
                break
            m = _NOTE_LINE.match(line)
            if m:
                seqs.append(int(m.group(1)))
    rd._notes[f] = (key, seqs)
    return seqs


def _outcome(rec: dict, verdict: dict | None) -> str:
    """right / wrong / open: the person's verdict first, then a run that ended failed; a done run nobody judged is open."""
    v = verdict if verdict is not None else rec.get("verdict")
    if v and v.get("ok") is not None:
        return "right" if v["ok"] else "wrong"
    if rec.get("state") == "finished" and rec.get("ok") is False and rec.get("kind") not in ("env", "quota"):
        return "wrong"                            # a run its machine or quota stopped says nothing about the notes
    return "open"


def receipt_row(rd: Reader, p: Paths, rec: dict, verdict: dict | None, piece_run: dict[str, str]) -> dict:
    """One run as the map's receipt line: who sent it to whom, the tier and rung it ran on, its spend, what the check
    covered (P1-10: files, and whether the run edited its own yardstick), the review's answer and the verdict."""
    atts = rec.get("attempts") or []
    c = rec.get("check") or {}
    cov = c.get("covers") or {}
    rv = rec.get("review") or {}
    check = None
    if c:
        check = {"passed": bool(c.get("passed")), "cmd": _clip(c.get("cmd"), CONV_FIELD)}
        if cov.get("unknown"):
            check["unknown"] = True
        elif cov:
            check.update(files=[_field(x) for x in (cov.get("files") or [])[:3]], n=cov.get("n_files"),
                         partial=bool(cov.get("partial")), filtered=bool(cov.get("filtered")),
                         own_only=bool(cov.get("own_tests_only")))
            if cov.get("basis_changed"):
                check["basis_changed"] = [_field(x) for x in (cov.get("edited") or [])[:3]]
    v = verdict if verdict is not None else rec.get("verdict")
    return {"run_id": rec["run_id"], "piece": piece_run.get(rec["run_id"], rec["run_id"]), "ts": rec.get("ts"),
            "from": rec.get("caller"), "to": rec.get("to"), "tier": rec.get("tier"),
            "rung": (atts[-1].get("rung") if atts else None) or rec.get("first_rung"), "rounds": len(atts),
            "usd": _usd(rec), "running": rec.get("state") == "running", "ok": rec.get("ok"), "kind": rec.get("kind"),
            "check": check,
            "review": rv.get("verdict") if rv.get("verdict") not in (None, "not-run") else None,
            "reviewer": _who_rung(rv.get("by")) if rv.get("verdict") not in (None, "not-run") else None,
            "verdict": v.get("ok") if v else None, "outcome": _outcome(rec, verdict),
            "notes": brief_notes(rd, p.runs / rec["run_id"])}


def _map_threads(rd: Reader, root: Path, todos: list[dict]) -> tuple[list[dict], dict]:
    """The board's threads (newest first) with who took part and whether one waits for the person, and the
    messages between agents counted per pair (from -> to; to `all` counts once)."""
    es = board_entries(rd, root)
    wait = {}
    for x in todos:
        wait.setdefault(x["key"], x["kind"])
    by: dict[str, list[dict]] = {}
    pairs: dict[tuple, int] = {}
    for e in es:
        if not isinstance(e.get("from"), str):
            continue
        by.setdefault(str(e.get("thread") or ""), []).append(e)
        a, b = board.vendor_of(e["from"]), board.vendor_of(str(e.get("to") or "all"))
        pairs[(a, b)] = pairs.get((a, b), 0) + 1
    out = []
    for th, msgs in by.items():
        last = msgs[-1]
        out.append({"key": th, "name": _field(th), "n": len(msgs), "last": _board_ts(last.get("ts")),
                    "who": sorted({board.vendor_of(m["from"]) for m in msgs}),
                    "text": _short(str(last.get("text") or "")), "wait": wait.get(th)})
    out.sort(key=lambda x: -(x["last"] or 0))
    return out, pairs


def project_map(rd: Reader, p: Paths, pr: dict, runs: list[dict], verdicts: dict, piece_run: dict[str, str],
                conv: dict | None, talks: list[dict], week_from: float) -> dict:
    """P2-10: one project on one page. Middle: the agents and what they said to each other (board threads, `ccx
    discuss` talks, who sent work to whom); left: shared memory and the runs whose brief carried a note, with how
    they ended; right: the receipts; top: this week's actual spend by the rung it ran on. Read only, never a model."""
    root = Path(pr["path"])
    runs = sorted(runs, key=lambda r: -float(r.get("ts") or 0))
    rows = [receipt_row(rd, p, r, verdicts.get(r["run_id"]), piece_run) for r in runs]
    threads, pairs = _map_threads(rd, root, (conv or {}).get("todos") or [])
    sent: dict[tuple, int] = {}
    for r in runs:
        if r.get("caller") and r.get("to"):
            k = (str(r["caller"]), str(r["to"]))
            sent[k] = sent.get(k, 0) + 1
    names = {a for k in [*sent, *pairs] for a in k if a not in ("all", "user")}
    names |= {t["lead"]["agent"] for t in pr["tasks"] if t["lead"].get("agent")}
    edges = [{"from": a, "to": b, "sent": n, "said": 0} for (a, b), n in sent.items()]
    for (a, b), n in pairs.items():
        hit = next((e for e in edges if e["from"] == a and e["to"] == b), None)
        if hit:
            hit["said"] = n
        else:
            edges.append({"from": a, "to": b, "sent": 0, "said": n})
    edges.sort(key=lambda e: -(e["sent"] + e["said"]))
    # memory: the notes the hub has, those about this project, and each run here whose brief carried notes
    from . import memory
    try:
        live = rd.every("mem-live", 30, lambda: memory.live_entries(p))
    except Exception:  # noqa: BLE001 — an odd journal never breaks the page
        live = []
    by_seq = {e.get("seq"): e for e in live}
    used: dict[int, dict] = {}
    for r, row in zip(runs, rows):
        for s in row["notes"]:
            u = used.setdefault(s, {"seq": s, "runs": 0, "right": 0, "wrong": 0, "open": 0, "last": None,
                                    "last_run": None})
            u["runs"] += 1
            u[row["outcome"]] += 1
            if u["last"] is None:                 # runs are newest first
                u["last"], u["last_run"] = r.get("ts"), row["run_id"]
    notes = []
    for u in sorted(used.values(), key=lambda u: -(u["last"] or 0))[:MAP_NOTES_MAX]:
        e = by_seq.get(u["seq"]) or {}
        notes.append({**u, "text": _short(str(e.get("text") or "")), "by": _field(e.get("by")),
                      "topic": _field(e.get("topic")), "gone": not e})
    week = [r for r in runs if float(r.get("ts") or 0) >= week_from]
    rungs: dict[str, dict] = {}
    for r in week:
        for a in r.get("attempts") or []:
            k = a.get("rung") or "?"
            x = rungs.setdefault(k, {"rung": k, "tier": r.get("tier"), "usd": 0.0, "runs": 0})
            x["usd"] = round(x["usd"] + float(a.get("ae_usd") or 0), 6)
        rv = r.get("review") or {}
        if rv.get("usd"):                         # the review's own spend, under the rung that reviewed
            k = rv.get("by") or "review"
            x = rungs.setdefault(k, {"rung": k, "tier": None, "usd": 0.0, "runs": 0, "review": True})
            x["usd"] = round(x["usd"] + float(rv["usd"]), 6)
        for k in {a.get("rung") or "?" for a in r.get("attempts") or []}:
            rungs[k]["runs"] += 1
    return {
        "id": pr["id"], "name": pr["name"],
        "agents": sorted(names), "edges": edges[:12],
        "threads": threads[:MAP_THREADS_MAX], "threads_total": len(threads),
        "todos": (conv or {}).get("todos") or [],
        "talks": [{k: x.get(k) for k in ("id", "question", "state", "usd", "ts")} | {"turns": len(x.get("turns") or [])}
                  for x in talks if project_root(x.get("cwd")) == root][:MAP_THREADS_MAX],
        "memory": {"total": len(live), "here": sum(memory.relevant(e, root.name) for e in live),
                   "carried": sum(1 for row in rows if row["notes"]), "notes": notes},
        "receipts": rows[:MAP_RECEIPTS_MAX], "receipts_total": len(rows),
        "spend": {"usd": round(sum(_usd(r) for r in week), 4), "runs": len(week),
                  "rungs": sorted(rungs.values(), key=lambda x: -x["usd"])},
    }


def measured_ref(rd: Reader) -> dict | None:
    """The first published table (docs/measured.md, as shipped in ccx/data/measured.json): the map names the other
    arms' measured cost beside this week's spend, never an estimate. None when the package has no table."""
    from . import tokenflow
    m = rd.every("measured", 300, tokenflow.measured)
    tb = next(iter((m or {}).get("tables") or []), None)
    if not tb or not tb.get("rows"):
        return None
    return {"id": tb.get("id"), "date": tb.get("date"), "title": tb.get("title"),
            "rows": [{k: r.get(k) for k in ("arm", "right", "usd_per_success")} for r in tb["rows"]]}


def collect(p: Paths, project: Path | None = None, days: float = 7, rd: Reader | None = None,
            now: float | None = None, quota_wait: bool = True) -> dict:
    rd = rd or Reader(p)
    now = now or time.time()
    since = now - days * 86400
    cfg = load_config(p)
    verdicts = rd.lines(p.ledger, _verdict_rows, {}) if p.ledger.exists() else {}
    recs: dict[str, dict] = {}
    if p.runs.exists():
        for d in p.runs.iterdir():
            f = d / "run.json"
            try:
                if f.stat().st_mtime < since:
                    continue
            except OSError:
                continue
            rec = rd.json_file(f)
            if isinstance(rec, dict) and rec.get("run_id"):
                recs[rec["run_id"]] = rec
    proj = project.resolve() if project else None
    scratch = scratch_roots(p)
    shown = {rid: r for rid, r in recs.items()
             if not r.get("ephemeral") and not str(r.get("label") or "").startswith(INTERNAL)}
    mine = {s for r in recs.values() for s in [r.get("session_id"), *[a.get("session_id") for a in r.get("attempts") or []]] if s}

    # projects and their queues
    roots: dict[Path, dict] = {}

    def root_of(r: dict) -> Path:
        return project_root(r.get("cwd")) or Path(".")

    for r in shown.values():
        roots.setdefault(root_of(r), {})
    catalog = _catalog(rd)                           # K6: every project `ccx projects` knows, by its folder
    for root in catalog:                             # ... a queue there shows even without a recent run here
        if root not in roots and (wq.qdir(root) / "queue.jsonl").exists():
            roots[root] = {}
    if proj:
        roots = {k: v for k, v in roots.items() if k == proj}
        roots.setdefault(proj, {})
    tasks_by_root: dict[Path, list[dict]] = {k: [] for k in roots}
    in_queue: set[str] = set()
    for root in roots:
        qf = wq.qdir(root) / "queue.jsonl"
        if not qf.exists():
            continue
        try:
            st = qf.stat()
            key = ("queue", st.st_mtime_ns, st.st_size)
        except OSError:
            continue
        hit = rd._json.get(qf)
        q = hit[1] if hit and hit[0] == key else wq.load(root)
        rd._json[qf] = (key, q)
        if not q["items"]:
            continue
        last = max(float(it.get("updated") or it.get("added") or 0) for it in q["items"].values())
        open_ = any(it["status"] not in wq.TERMINAL for it in q["items"].values())
        if not open_ and last < since:
            continue
        in_queue |= {it["run"] for it in q["items"].values() if it.get("run")}
        in_queue |= {rid for rid, r in shown.items() if str(r.get("label") or "").startswith("q:") and root_of(r) == root}
        pieces = _queue_pieces(rd, root, q, recs, verdicts, now)
        q_runs = [recs[it["run"]] for it in q["items"].values() if it.get("run") in recs]
        lead_sid = next((r.get("lead_session") for r in q_runs if r.get("lead_session")), None)
        lead = _lead_of_session(rd, lead_sid, q_runs[0].get("caller")) if lead_sid else \
            {"agent": (q_runs[0].get("caller") if q_runs else None), "model": "", "title": ""}
        roots_items = [q["items"][i] for i in q["order"] if not q["items"][i].get("parent")]
        hist = []
        for r in sorted(q_runs, key=lambda r: r.get("ts") or 0):
            it = next((x for x in q["items"].values() if x.get("run") == r["run_id"]), {})
            hist += hist_of_run(r, it.get("title") or "")
        tasks_by_root[root].append({
            "id": "queue", "kind": "queue", "title": lead.get("title") or (roots_items[0]["title"] if len(roots_items) == 1 else ""),
            "asked": min(float(it.get("added") or now) for it in q["items"].values()), "last": last,
            "lead": {"agent": lead.get("agent"), "model": lead.get("model")}, "helpers": [],
            "spent": wq.spent(q), "budget": q.get("budget_usd"), "pieces": pieces,
            "ctl": [_btn("b_budget", ["ccx", "q", "budget", "{usd}", "--cwd", str(root)])],
            "hist": sorted(hist, key=lambda h: h.get("ts") or 0)[-40:]})

    # the rest: one task per lead conversation (or per run when no lead is known)
    chains: dict[str, str] = {}
    piece_run: dict[str, str] = {}
    for rid, r in sorted(shown.items(), key=lambda x: x[1].get("ts") or 0):
        if rid in in_queue:
            continue
        base = r.get("review_of") or (r.get("resumed_from") if not r.get("continued") else None)
        chains[rid] = chains.get(base, base) if base and base in shown else rid
    groups: dict[str, list[str]] = {}
    for rid, head in chains.items():
        r = shown[head]
        key = r.get("lead_session") or f"run-{head}"
        if proj and root_of(r) != proj:
            continue
        groups.setdefault(key, [])
        if head not in groups[key]:
            groups[key].append(head)
    for key, heads in groups.items():
        first = shown[heads[0]]
        root = root_of(first)
        lead = _lead_of_session(rd, first["lead_session"], first.get("caller")) if first.get("lead_session") else \
            {"agent": first.get("caller") if first.get("caller") in ("claude", "codex") else None, "model": "", "title": ""}
        pieces, hist, last = [], [], 0.0
        for head in heads:
            runs = sorted([rid for rid, h in chains.items() if h == head], key=lambda x: shown[x].get("ts") or 0)
            latest = shown[runs[-1]]
            piece_run.update({x: latest["run_id"] for x in runs})     # P2-10: a receipt opens its piece
            title = (shown[head].get("label") if shown[head].get("label") and not str(shown[head]["label"]).startswith("q:")
                     else "") or _short(_brief_of(p.runs / head)) or head
            pc = piece_of_run(rd, latest, verdicts.get(latest["run_id"]), now, title)
            pc["id"] = _sid(head)
            pc["test"] = any(is_test(shown[x], scratch) for x in runs)
            pc["usd"] = round(sum(_usd(shown[x]) for x in runs), 6)
            pc["rounds"] = len(runs)
            pieces.append(pc)
            for x in runs:
                hist += hist_of_run(shown[x], title)
                last = max(last, float(shown[x].get("ts") or 0) + sum(a.get("seconds") or 0 for a in shown[x].get("attempts") or []))
        tasks_by_root.setdefault(root, []).append({
            "id": _sid(key), "kind": "lead" if first.get("lead_session") else "run",
            "title": lead.get("title") or pieces[0]["title"],     # no lead title: its first piece's (never blank)
            "asked": min(float(shown[h].get("ts") or now) for h in heads), "last": last,
            "lead": {"agent": lead.get("agent"), "model": lead.get("model")}, "helpers": [],
            "spent": round(sum(x["usd"] for x in pieces), 6), "budget": None, "pieces": pieces, "ctl": [],
            "hist": sorted(hist, key=lambda h: h.get("ts") or 0)[-40:]})

    current = [{**x, "test": is_scratch(x.get("cwd"), scratch)} for x in leads(rd, mine)]
    by_session = {x["session"]: x for x in current}
    projects = []
    for root, tasks in tasks_by_root.items():
        if not tasks:
            continue
        for t in tasks:
            for pc in _walk(t["pieces"]):                # queue pieces: by their run (the lead pieces are set above)
                if "test" not in pc:
                    pc["test"] = bool(pc.get("run_id") in recs and is_test(recs[pc["run_id"]], scratch))
            t["test"] = all(pc["test"] for pc in t["pieces"])
            if t["kind"] == "lead":
                cur = by_session.get(t["id"])
                if cur:
                    t["helpers"] = cur["helpers"]
                    t["lead"]["model"] = t["lead"]["model"] or cur["model"]
        tasks.sort(key=lambda t: -(t["last"] or t["asked"] or 0))
        e = catalog.get(root)
        try:
            sw = lead_switch(rd, root, tasks)
        except Exception:  # noqa: BLE001 — an odd handoff file never breaks the page
            sw = {"current": None, "ctl": [], "periods": [], "switches": []}
        for t in tasks:
            extra = lead_hist(sw, t)
            if extra:
                t["hist"] = sorted(t["hist"] + extra, key=lambda h: h.get("ts") or 0)[-40:]
        projects.append({"id": _pid(root), "name": (e or {}).get("name") or root.name or str(root), "path": str(root),
                         "tasks": tasks[:30], "test": is_scratch(root, scratch) or all(t["test"] for t in tasks),
                         "rules": _rules(rd, e) if e else [], "level": _level(rd, e), "lead_switch": sw})
    projects.sort(key=lambda pr: -max(t["last"] or t["asked"] or 0 for t in pr["tasks"]))
    shown_roots = {Path(pr["path"]) for pr in projects}
    running = running_now(projects)
    quiet = sorted((e for root, e in catalog.items() if root not in shown_roots and not proj),
                   key=lambda e: -float(e.get("last_active") or 0))
    others = [{"name": e.get("name"), "path": e.get("path"), "last": e.get("last_active"),
               "summary": _short(e.get("summary") or ""), "test": is_scratch(e.get("path"), scratch)}
              for e in quiet[:12]]

    providers = set((cfg.get("providers") or {}).keys())
    week = [r for r in recs.values() if float(r.get("ts") or 0) >= now - 7 * 86400]
    hard = [v for v in verdicts.values() if not v.get("soft")]
    agents = sorted({pc["worker"] for pr in projects for t in pr["tasks"] for pc in _walk(t["pieces"])
                     if pc.get("worker")} | {x["agent"] for x in current})
    from . import discuss, ways
    try:
        track = rd.every("track", 60, lambda: ways.track(p))      # H9: who is good at what (judged pieces)
    except Exception:  # noqa: BLE001 — the page still shows the rest
        track = {}
    talks = [{**discuss.view(d), "test": is_scratch(d.get("cwd"), scratch)} for d in discuss.recent(p, since)
             if not proj or project_root(d.get("cwd")) == proj][:10]
    convs = []                                                # U2: the agents' boards, what waits for the person
    for pid, root in board_roots(rd, list(tasks_by_root), proj).items():
        try:
            c = conv_summary(rd, root, since, cfg, catalog.get(root), scratch)
        except Exception:  # noqa: BLE001 — an odd board never breaks the page
            c = None
        if c:
            convs.append(c)
    convs.sort(key=lambda c: -(c["last"] or 0))
    maps = []                                                 # P2-10: the home page, one map per project
    conv_of = {c["id"]: c for c in convs}
    for pr in projects:
        root = Path(pr["path"])
        try:
            maps.append(project_map(rd, p, pr, [r for r in shown.values() if root_of(r) == root], verdicts,
                                    piece_run, conv_of.get(pr["id"]), talks, now - 7 * 86400))
        except Exception:  # noqa: BLE001 — the page still shows the rest
            continue
    from . import memsuggest
    try:                                                      # H5: notes that wait for the person's yes or no
        ranked = memsuggest.ranked(p)              # the first few only: the rules sift, the person judges
        sugs = [{k: s.get(k) for k in ("id", "kind", "text", "by", "source", "ts")} for s in ranked[:memsuggest.SHOW]]
        n_sugs = len(ranked)
    except Exception:  # noqa: BLE001 — the page still shows the rest
        sugs, n_sugs = [], 0
    from .demo import is_demo
    return {
        "v": 1, "generated": now, "lang": ui_lang(cfg), "poll_s": POLL_S, "beat_s": BEAT_S, "demo": is_demo(p),
        "start": start_hint(),                   # what an empty overview tells a new user to do first
        "projects": projects, "running": running, "quota": quota_view(rd, quota_wait), "leads": current,
        "agents": agents,
        "maps": maps, "measured_ref": measured_ref(rd),
        "discussions": talks, "conversations": convs[:CONV_PROJECTS_MAX], "track": track, "track_min": ways.MIN_JUDGED, "suggestions": sugs,
        "suggestions_total": n_sugs, "others": others, "others_total": len(quiet),
        "month": month_view(rd, quota_wait), "inbox": _inbox(rd),
        "week": {"usd": round(sum(_usd(r) for r in week), 4),
                 "cash_usd": round(sum(_usd(r) for r in week if r.get("to") in providers or r.get("provider")), 4),
                 "runs": len(week), "verdicts": len(hard), "verdicts_needed": VERDICTS_TO_KNOW},
    }


def running_now(projects: list[dict]) -> list[dict]:
    """U4, the home page's "running now" strip: every piece whose run record says running (a queue item marked
    doing without a live run is not one), with its agent, time so far, tokens when the session file told us, and the
    stop button the piece already offers (its control, or for a stale run its act), addressed like any other button
    so the same prepare / confirm path runs it. Oldest first."""
    out = []
    for pr in projects:
        for t in pr["tasks"]:
            for pc in _walk(t["pieces"]):
                if not pc.get("live"):
                    continue
                btn, cmd = None, None
                for group, tag in (((pc.get("ctl") or []), "c"), (((pc.get("act") or {}).get("buttons") or []), "a")):
                    i = next((i for i, b in enumerate(group) if b.get("label") == "b_stop"), None)
                    if i is not None:
                        btn, cmd = f"{tag}{i}", group[i]["cmd"]
                        break
                out.append({"project": pr["id"], "task": t["id"], "piece": pc["id"], "run_id": pc.get("run_id"),
                            "title": pc.get("title") or t.get("title") or pc.get("run_id") or "",
                            "worker": pc.get("worker"), "model": pc.get("model") or "", "secs": pc.get("secs") or 0,
                            "tokens": pc.get("tokens") or None, "ts": pc.get("ts"),
                            "stale": ((pc.get("act") or {}).get("what") == "a_stale"), "btn": btn, "cmd": cmd,
                            "test": bool(pc.get("test"))})
    return sorted(out, key=lambda r: float(r.get("ts") or 0))


def _walk(pieces: list[dict]):
    for pc in pieces:
        yield pc
        yield from _walk(pc.get("children") or [])


def ui_lang(cfg: dict) -> str | None:
    v = (cfg.get("ui") or {}).get("lang")
    return v if v in ("zh", "en") else None


def run_detail(p: Paths, run_id: str) -> dict:
    """One run for the side panel's 'details': compact facts, no logs."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id or ""):
        raise ValueError("bad run id")
    from .delegate import compact
    from .ledger import load_run
    rec = load_run(p, run_id)
    out = compact(rec)
    out["cwd"], out["mode"], out["ts"] = rec.get("cwd"), rec.get("mode"), rec.get("ts")
    out["logs"] = str(p.runs / run_id)
    return out


# ------------------------------------------------------------------ U1: is the sub-agent's work right? (the card)
JUDGE_DIFF_MAX = 60_000       # bytes of diff the card gets; beyond, it says "truncated"
JUDGE_FILES_MAX = 300         # file names on either side
JUDGE_TEXT_MAX = 2000         # the agent's own verification text
TAIL_MAX = 800                # the check's last output (run_check keeps the same)
JUDGE_EXCLUDE_MAX = 200       # pre-existing untracked files left out of the diff by name
GIT_TIMEOUT_S = 20
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _clip(s, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[:n] + "…"


def check_view(c: dict | None) -> dict | None:
    """What ccx ran after the sub-agent said it was done: the command, its exit, the last output, and ccx's notes on
    it (broken, weak, ran on an unchanged tree). Plain data; the page escapes it."""
    if not c:
        return None
    return {"cmd": c.get("cmd"), "passed": c.get("passed"), "exit": c.get("exit"),
            "tail": str(c.get("tail") or "")[-TAIL_MAX:], "broken": c.get("broken") or None,
            "weak": c.get("weak") or None, "unchanged_tree": bool(c.get("unchanged_tree")),
            "reason": c.get("reason") or None}


def _read_json(f: Path):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _git_read(repo: str, args: list[str], cap: int) -> tuple[bytes, bool, bool]:
    """(output, truncated, ok) of one read-only git command in `repo`: at most `cap` bytes are kept, then git is
    stopped. No pager, no prompt, no optional locks (git diff takes no lock on the index then), no window."""
    import subprocess
    from .winproc import CREATE_NO_WINDOW
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "PAGER": "cat"}
    flags = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        proc = subprocess.Popen(["git", "-C", repo, "-c", "core.quotepath=off", "--no-pager", *args],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=env, **flags)
    except OSError:
        return b"", False, False
    timer = threading.Timer(GIT_TIMEOUT_S, proc.kill)
    timer.start()
    try:
        data = proc.stdout.read(cap + 1)
        truncated = len(data) > cap
        if truncated:
            proc.kill()
        proc.stdout.close()
        rc = proc.wait(GIT_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — a hung or odd git gives the card a note, not a 500
        proc.kill()
        return b"", False, False
    finally:
        timer.cancel()
    return data[:cap], truncated, truncated or rc == 0


def _said_path(f: str, cwd: str | None, repo: str) -> list[str]:
    """The spellings a file name the sub-agent reported may have in git's terms (relative to the repo top, forward
    slashes): as given, and with the run's subfolder in front when it ran in one. A string operation only: the name
    is never opened or resolved (an absolute name like //host/share/x would make Windows reach that host), only the
    repo and cwd, which ccx itself wrote, are resolved. A name outside the repo comes back as given."""
    s = str(f).strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if s.startswith("//"):                            # UNC or network name: never ours, never touched
        return [s]
    top = _resolved(repo).as_posix().rstrip("/")
    fold = (lambda x: x.casefold()) if os.name == "nt" else (lambda x: x)
    if PureWindowsPath(s).drive or s.startswith("/"):
        norm = posixpath.normpath(s)
        if fold(norm).startswith(fold(top) + "/"):
            return [norm[len(top) + 1:]]
        return [s]
    out = [posixpath.normpath(s)]
    if cwd:
        sub = _resolved(cwd).as_posix().rstrip("/")
        if fold(sub).startswith(fold(top) + "/"):
            out.insert(0, posixpath.normpath(f"{sub[len(top) + 1:]}/{s}"))
    return out


def judge(p: Paths, run_id: str) -> dict:
    """The decision card's evidence for one run, read only from that run's own records under <hub>/ccx/runs/<id>:
    what the agent says (summary, verification, the files it names), what ccx ran (the check, its exit and last
    output), and the change itself, from ccx's own snapshots: undo.json's base (the tree before the run, a chain's
    first one for a fix round) to end.json's full tree (new files included) or else undo.json's `after` tree (tracked
    files; new untracked files by name only). Never a diff against the live working tree; only `git diff` of two
    object ids, which changes nothing. Old runs without snapshots get a note and the page keeps today's view."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id or ""):
        raise ValueError("bad run id")
    runs = p.runs.resolve()
    run_dir = (p.runs / run_id).resolve()
    if run_dir.parent != runs:
        raise ValueError("bad run id")
    rec = _read_json(run_dir / "run.json")
    if not isinstance(rec, dict):
        raise FileNotFoundError(f"no ccx run {run_id!r}")
    res = rec.get("result") or {}
    said = [str(x) for x in (res.get("files_changed") or []) if str(x).strip()][:JUDGE_FILES_MAX]
    out = {"run_id": run_id,
           "says": {"summary": _clip(res.get("summary") or rec.get("error"), JUDGE_TEXT_MAX),
                    "verification": _clip(res.get("verification"), JUDGE_TEXT_MAX), "files": said},
           "ran": check_view(rec.get("check")),
           "changed": None, "diff": None, "truncated": False, "mismatch": None, "untracked_before": [],
           "note": None, "chain_from": None, "source": None}
    if rec.get("state") == "running":
        out["note"] = "j_running"
        return out
    snap = _read_json(run_dir / "undo.json")
    if not isinstance(snap, dict) or not snap.get("base"):
        out["note"] = "j_read_only" if rec.get("mode") == "read" else "j_no_snapshot"
        return out
    end = _read_json(run_dir / "end.json")
    after = snap.get("after") if isinstance(snap.get("after"), dict) else {}
    base = str(snap.get("base") or "")
    if isinstance(end, dict) and _OID.fullmatch(str(end.get("tree") or "")):
        end_tree, out["source"] = str(end["tree"]), "end"
    elif _OID.fullmatch(str(after.get("tree") or "")):
        end_tree, out["source"] = str(after["tree"]), "after"
    else:
        out["note"] = "j_no_end"
        return out
    repo = str(snap.get("repo") or "")
    if not _OID.fullmatch(base) or not repo or not Path(repo).is_dir():
        out["note"] = "j_repo_gone"
        return out
    out["chain_from"] = snap.get("chain_from")
    before_untracked = {_unquote(str(x)) for x in snap.get("untracked") or []}   # git C-quotes non-ASCII names
    raw, _, ok = _git_read(repo, ["diff", "--name-status", "-z", "--no-renames", base, end_tree], 1_000_000)
    if not ok:
        out["note"] = "j_repo_gone"
        return out
    bits = raw.decode("utf-8", errors="replace").split("\0")
    changed, was_untracked = [], []
    for st, path in zip(bits[0::2], bits[1::2]):
        if not st:
            continue
        if out["source"] == "end" and st == "A" and path in before_untracked:
            was_untracked.append(path)                # there before the run, untracked: can't tell if it changed
            continue
        changed.append({"path": path, "status": st[:1]})
    if out["source"] == "after":                       # new untracked files: names only (contents not snapshotted)
        now_untracked = {_unquote(str(x)) for x in after.get("untracked") or []}
        changed += [{"path": x, "status": "?"} for x in sorted(now_untracked - before_untracked)]
        was_untracked += sorted(now_untracked & before_untracked)  # untracked before and after: can't tell
        if now_untracked - before_untracked:
            out["note"] = "j_untracked_names"
    out["changed"] = changed[:JUDGE_FILES_MAX]
    out["untracked_before"] = sorted(was_untracked)[:JUDGE_FILES_MAX]
    spec = []
    if was_untracked and out["source"] == "end":     # the `after` tree holds no untracked file: nothing to exclude
        if len(was_untracked) <= JUDGE_EXCLUDE_MAX:
            spec = ["--", ".", *[f":(exclude,literal){x}" for x in was_untracked]]
        else:
            out["note"] = "j_untracked_many"
    diff, cut, ok = _git_read(repo, ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", base,
                                     end_tree, *spec], JUDGE_DIFF_MAX)
    if ok:
        out["diff"], out["truncated"] = diff.decode("utf-8", errors="replace"), cut
    fold = (lambda s: s.casefold()) if os.name == "nt" else (lambda s: s)
    real = {fold(c["path"]): c["path"] for c in changed}
    skip = {fold(x) for x in was_untracked}
    named, extra = set(), []
    for f in said:                                     # a name counts if any of its spellings is a real change
        keys = [fold(x) for x in _said_path(f, rec.get("cwd"), repo)]
        hit = [k for k in keys if k in real or k in skip]
        named.update(hit[:1])
        if not hit:
            extra.append(f)
    missing = [v for k, v in real.items() if k not in named]
    if extra or missing:
        out["mismatch"] = {"said_not_changed": extra[:JUDGE_FILES_MAX], "changed_not_said": missing[:JUDGE_FILES_MAX]}
    return out


# ------------------------------------------------------------------ U2 / I1: the agents' conversation (the board)
SAY_MAX = 4000                # characters of one reply from the page; longer is refused (never cut)
SAY_BODY_MAX = 64_000         # bytes of the JSON body that carries it (escapes included)
CONV_PROJECTS_MAX = 30        # projects with a board in /api/data
CONV_TODOS_MAX = 40           # to-dos of one project in /api/data
CONV_THREADS_MAX = 40         # threads in /api/conv, newest first
CONV_MSGS_MAX = 80            # the latest messages of one thread
CONV_MSG_CHARS = 6000         # one message's text on the page; longer is cut there and marked (the board keeps it)
CONV_TOTAL_CHARS = 400_000    # all the text of one /api/conv answer
CONV_FIELD = 120              # from / to / via / thread names as shown (a thread's exact name goes as `key`)
_PID = re.compile(r"p[0-9a-f]{10}")


def _fold_board(state: list, line: str) -> list:
    try:
        e = json.loads(line)
    except ValueError:
        return state
    if isinstance(e, dict) and isinstance(e.get("id"), int) and not isinstance(e.get("id"), bool):
        state.append(e)
    return state


def _board_file(root: Path) -> Path:
    return root / ".ccx" / "board.jsonl"


def _fold_rows(state: list, line: str) -> list:
    try:
        row = json.loads(line)
    except ValueError:
        return state
    if isinstance(row, dict):
        state.append(row)
    return state


def board_entries(rd: Reader, root: Path) -> list[dict]:
    """The project's board, read from where the last read stopped (it is append-only). Never written here."""
    f = _board_file(root)
    return rd.lines(f, _fold_board, []) if f.exists() else []


def _humans(rd: Reader, root: Path) -> dict:
    h = rd.json_file(root / ".ccx" / "board.humans.json")
    return {k: v for k, v in h.items() if isinstance(v, int)} if isinstance(h, dict) else {}


def _max_machine(cfg: dict) -> int:
    try:
        return int((cfg.get("board") or {}).get("max_machine_turns", board.MAX_MACHINE))
    except (TypeError, ValueError):
        return board.MAX_MACHINE


def _board_ts(s) -> float | None:
    """board.jsonl's `ts` (local time, %Y-%m-%dT%H:%M:%S) as seconds."""
    try:
        return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError, OverflowError):
        return None


def _field(v) -> str:
    return _clip(v if isinstance(v, str) else "" if v is None else str(v), CONV_FIELD)


def board_roots(rd: Reader, roots: list[Path], proj: Path | None) -> dict[str, Path]:
    """The projects whose board the page reads: the ones it shows and the `ccx projects` catalog (or only --project),
    each with a board file. Nothing else is ever opened."""
    out: dict[str, Path] = {}
    for r in ([proj] if proj else [*roots, *_catalog(rd)]):
        if r is not None and _board_file(r).exists():
            out.setdefault(_pid(r), r)
    return out


def _waits(rd: Reader, root: Path, es: list[dict], cfg: dict) -> list[dict]:
    try:
        return board.waiting_on_person(es, _humans(rd, root), _max_machine(cfg))
    except Exception:  # noqa: BLE001 — an odd line never breaks the page
        return []


def conv_summary(rd: Reader, root: Path, since: float, cfg: dict, entry: dict | None,
                 scratch: list[Path]) -> dict | None:
    """One project's board for /api/data: counts, and the to-dos (U2) — a thread stopped by the machine-message cap,
    a message that asks the person — each with the message's first line and the thread to open."""
    es = board_entries(rd, root)
    if not es:
        return None
    by_id = {e["id"]: e for e in es}
    todos = []
    for w in _waits(rd, root, es, cfg):
        e = by_id.get(w["id"]) or {}
        ts = _board_ts(e.get("ts"))
        if ts is not None and ts < since:              # old: the to-do list is about now (the thread still shows)
            continue
        todos.append({"kind": w["kind"], "thread": _field(w["thread"]), "key": str(w["thread"]), "id": w["id"],
                      "run": w["run"], "from": _field(e.get("from")), "ts": ts, "text": _short(str(e.get("text") or ""))})
    todos.sort(key=lambda x: -x["id"])
    return {"id": _pid(root), "name": (entry or {}).get("name") or root.name or str(root), "path": str(root),
            "threads": len({str(e.get("thread")) for e in es}), "messages": len(es),
            "last": _board_ts(es[-1].get("ts")), "todos": todos[:CONV_TODOS_MAX],
            "test": is_scratch(root, scratch)}


def _reply_address(parent: dict) -> str:
    """Whom a reply to `parent` goes to: its writer, or everyone when the person wrote it (as `ccx reply`)."""
    frm = str(parent.get("from") or "")
    return frm if board.vendor_of(frm) != "user" else "all"


def conversation(rd: Reader, root: Path, cfg: dict, pid: str, name: str) -> dict:
    """/api/conv/<project>: the board's threads, newest first, each message with who, when, to whom and its text
    (data written by agents: the page escapes it). Capped: CONV_THREADS_MAX threads, the last CONV_MSGS_MAX messages
    of each, CONV_MSG_CHARS per message and CONV_TOTAL_CHARS in all, each cut marked."""
    es = board_entries(rd, root)
    waits = _waits(rd, root, es, cfg)
    stuck = {w["thread"]: w["run"] for w in waits if w["kind"] == "stuck"}
    asks = {w["id"] for w in waits if w["kind"] == "asks"}
    by: dict[str, list[dict]] = {}
    for e in es:
        by.setdefault(str(e.get("thread")), []).append(e)
    order = sorted(by, key=lambda th: -by[th][-1]["id"])
    used, threads = 0, []
    for th in order[:CONV_THREADS_MAX]:
        msgs = by[th]
        last = msgs[-1]
        item = {"thread": _field(th), "key": th, "n": len(msgs), "last": _board_ts(last.get("ts")), "stuck": th in stuck,
                "run": stuck.get(th, 0), "asks": [e["id"] for e in msgs if e["id"] in asks],
                "reply": {"id": last["id"], "to": _field(_reply_address(last))},
                "more": max(0, len(msgs) - CONV_MSGS_MAX), "clipped": False, "messages": []}
        for e in msgs[-CONV_MSGS_MAX:]:
            if used >= CONV_TOTAL_CHARS:
                item["clipped"] = True
                break
            text = str(e.get("text") or "")
            shown = text[:min(CONV_MSG_CHARS, CONV_TOTAL_CHARS - used)]
            used += len(shown)
            rt = e.get("reply_to")
            item["messages"].append({
                "id": e["id"], "ts": _board_ts(e.get("ts")), "from": _field(e.get("from")),
                "who": _field(board.vendor_of(str(e.get("from") or ""))), "to": _field(e.get("to")),
                "via": _field(e.get("via")), "reply_to": rt if isinstance(rt, int) and not isinstance(rt, bool) else None,
                "text": shown, "cut": len(shown) < len(text), "chars": len(text), "asks": e["id"] in asks,
                "remote": bool(e.get("remote"))})
        threads.append(item)
    return {"project": {"id": pid, "name": name, "path": str(root)}, "threads": threads, "threads_total": len(by),
            "max_machine": _max_machine(cfg), "say_max": SAY_MAX, "generated": time.time()}


# ------------------------------------------------------------------ U7: the switch-lead button's command and answer
def handoff_argv(p: Paths, argv: list[str], by: str) -> tuple[list[str], str | None]:
    """The handoff button's argv, with `--from-transcript <current lead> --no-model` when that lead's session file for
    the project folder exists (the handoff is then assembled by code from it, never by a model: the page spends
    nothing); and that file, or None."""
    if by not in ("claude", "codex") or "--cwd" not in argv:
        return argv, None
    i = argv.index("--cwd")
    root = Path(argv[i + 1])
    try:
        from . import ledger, transcript
        mine = {s for r in ledger.rows(p) for s in [r.get("session_id"), *(r.get("sessions") or [])] if s}
        f = transcript.find_session(by, root, mine)
    except Exception:  # noqa: BLE001 — no session file found: a handoff without the transcript
        f = None
    if not f:
        return argv, None
    return [*argv[:i], "--from-transcript", by, "--no-model", *argv[i:]], str(f)


def handoff_result(argv: list[str], out: str) -> dict | None:
    """What the page shows after the handoff ran: the file and the one line to give the incoming lead (`paste`, from
    `ccx handoff`'s JSON; else the project's newest handoff file and the same line)."""
    to = argv[argv.index("--to") + 1] if "--to" in argv else ""
    root = Path(argv[argv.index("--cwd") + 1]) if "--cwd" in argv else None
    try:
        got = json.loads(out[out.index("{"):]) if "{" in out else None
    except ValueError:
        got = None
    from .commands.memory import SHOWN_AT_START, paste_line
    if isinstance(got, dict) and got.get("handoff"):
        # `note` is set when no text went in: a blank template the person must fill in before giving the line
        return {"file": str(got["handoff"]), "paste": str(got.get("paste") or ""), "to": to,
                "root": str(root or ""), "from_transcript": got.get("from_transcript"),
                "blank": bool(got.get("note")), "shown_at_start": to in SHOWN_AT_START}
    if root is None:
        return None
    from .project import _order
    d = root / ".ccx" / "handoffs"
    files = sorted(d.glob("*.md"), key=_order) if d.is_dir() else []
    if not files:
        return None
    return {"file": str(files[-1]), "paste": paste_line(to, files[-1].relative_to(root).as_posix()),
            "to": to, "root": str(root), "from_transcript": None, "blank": False, "shown_at_start": to in SHOWN_AT_START}


# ------------------------------------------------------------------ running a button's ccx command (K6)
def execute(p: Paths, argv: list[str], background: bool) -> dict:
    """Run one ccx command a button offers: this copy of ccx, an argument list (no shell), no console window.
    One that records something runs now and its answer comes back; one that starts a sub-agent runs in the
    background (its run record shows on the page). Each is one line in <hub>/ccx/ui-actions.jsonl."""
    import subprocess
    from .config import ccx_argv
    from .winproc import BACKGROUND, CREATE_NO_WINDOW
    if _op(argv) is None:                            # the last guard: only RUNS commands, whatever called this
        raise ValueError("not a command the page may run")
    real = [*ccx_argv(), *argv[1:]]
    log = p.state / "ui-actions.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "argv": argv[1:], "background": background}
    if background:
        out_f = p.state / "ui-actions" / f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}.log"
        out_f.parent.mkdir(parents=True, exist_ok=True)
        with open(out_f, "wb") as fh:
            proc = subprocess.Popen(real, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                    close_fds=True, cwd=str(p.state), **BACKGROUND)
        out = {"started": True, "pid": proc.pid, "log": str(out_f)}
    else:
        flags = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
        try:
            r = subprocess.run(real, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=90, cwd=str(p.state), **flags)
            out = {"exit": r.returncode, "out": (r.stdout or "")[-1500:], "err": (r.stderr or "")[-600:]}
        except subprocess.TimeoutExpired:
            out = {"exit": None, "out": "", "err": "still running after 90 s"}
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({**row, **{k: out.get(k) for k in ("exit", "started", "pid")}}) + "\n")
    out["ok"] = bool(out.get("started")) or out.get("exit") == 0
    return out


# ------------------------------------------------------------------ the server
def _static(name: str) -> bytes:
    return (STATIC / name).read_bytes()


CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
TYPES = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
         "app.css": "text/css; charset=utf-8", "strings.json": "application/json; charset=utf-8"}


class UI:
    """The running server. `serve()` blocks until the page has been gone for IDLE_S (or stop())."""

    def __init__(self, p: Paths, project: Path | None = None, days: float = 7, port: int = 0,
                 idle_s: float = IDLE_S, first_beat_s: float = FIRST_BEAT_S, hidden_idle_s: float = HIDDEN_IDLE_S):
        self.p, self.project, self.days = p, project, days
        self.token = secrets.token_urlsafe(24)
        self.idle_s, self.first_beat_s, self.hidden_idle_s = idle_s, first_beat_s, hidden_idle_s
        self.started = time.time()
        self.last_beat: float | None = None
        self.hidden = False                       # the last heartbeat came from a hidden tab
        self.judged: dict[str, tuple] = {}        # run id -> (run record's mtime/size, judge())
        self.reader = Reader(p)
        self.lock = threading.Lock()
        self.pending: dict[str, dict] = {}
        self.says: dict[str, dict] = {}            # I1: prepared replies, by nonce
        self.boards: dict[str, tuple[Path, str]] = {}   # U2: project id -> (folder, name) of the boards shown
        self.why_stopped = ""
        from .tokenflow import Flow
        self.flow = Flow(p)                       # B1: caches of the tokens page (children, parsed lead sessions)
        self.flow_lock = threading.Lock()
        from .demo import is_demo
        self.demo = is_demo(p)                    # U6: a `ccx demo` hub: commands that start an agent are not run
        ui = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ccx-ui"
            sys_version = ""

            def log_message(self, *a):            # quiet: the terminal shows only the URL and the exit
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
                self._drain()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", CSP)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _deny(self, why: str):
                self._send(403, json.dumps({"error": why}).encode())

            def _host_ok(self) -> bool:
                port = self.server.server_address[1]
                return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

            def _token_ok(self) -> bool:
                return hmac.compare_digest(self.headers.get("X-CCX-Token", ""), ui.token)

            def do_GET(self):
                if not self._host_ok():
                    return self._deny("host")
                path = urlsplit(self.path).path
                name = {"/": "index.html"}.get(path, path.lstrip("/"))
                if name in TYPES:
                    return self._send(200, _static(name), TYPES[name])
                if not path.startswith("/api/"):
                    return self._send(404, b'{"error":"not found"}')
                if not self._token_ok():
                    return self._deny("token")
                try:
                    if path == "/api/data":
                        with ui.lock:
                            data = collect(ui.p, ui.project, ui.days, ui.reader, quota_wait=False)
                            ui.remember_boards(data)
                        return self._send(200, json.dumps(data, ensure_ascii=False, default=list).encode("utf-8"))
                    if path.startswith("/api/run/"):
                        return self._send(200, json.dumps(run_detail(ui.p, path[len("/api/run/"):]),
                                                          ensure_ascii=False).encode("utf-8"))
                    if path.startswith("/api/judge/"):        # U1: read-only, one run's own records
                        return self._send(200, json.dumps(ui.judge(path[len("/api/judge/"):]),
                                                          ensure_ascii=False).encode("utf-8"))
                    if path.startswith("/api/conv/"):         # U2: read-only, one project's board
                        return self._send(200, json.dumps(ui.conversation(path[len("/api/conv/"):]),
                                                          ensure_ascii=False).encode("utf-8"))
                    if path in ("/api/tokens", "/api/leadcost"):  # B1: read-only, capped
                        q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items() if v}
                        out = (ui.token_flow(q.get("period", "7d"), q.get("project"), q.get("tests") == "1")
                               if path == "/api/tokens" else ui.lead_cost(q.get("agent", ""), q.get("session", "")))
                        return self._send(200, json.dumps(out, ensure_ascii=False, default=list).encode("utf-8"))
                except (FileNotFoundError, ValueError) as e:
                    return self._send(404, json.dumps({"error": str(e)[:200]}).encode())
                except Exception as e:  # noqa: BLE001 — an odd record answers 500, the server keeps going
                    return self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"[:200]}).encode())
                return self._send(404, b'{"error":"not found"}')

            def do_POST(self):
                if not self._host_ok():
                    return self._deny("host")
                if not self._token_ok():
                    return self._deny("token")
                if urlsplit(self.path).path == "/api/alive":
                    ui.beat(hidden=urlsplit(self.path).query == "hidden=1")
                    return self._send(200, b'{"ok":true}')
                if urlsplit(self.path).path == "/api/suggestion":
                    return self._suggestion()
                if urlsplit(self.path).path in ("/api/act/prepare", "/api/act/run"):
                    return self._act(urlsplit(self.path).path.rsplit("/", 1)[1])
                if urlsplit(self.path).path in ("/api/say/prepare", "/api/say/run"):
                    return self._act(urlsplit(self.path).path.rsplit("/", 1)[1], say=True)
                return self._send(404, b'{"error":"not found"}')

            def _drain(self):
                """Read a POST body nobody read before answering: closing with unread data makes Windows reset the
                connection, and the client sees ConnectionAbortedError instead of our 403 (a flaky CI test)."""
                if self.command != "POST" or getattr(self, "_drained", False):
                    return
                self._drained = True
                n = int(self.headers.get("Content-Length") or 0)
                if 0 < n <= 65536:
                    self.rfile.read(n)

            def _body(self, limit: int = 4000):
                n = int(self.headers.get("Content-Length") or 0)
                self._drained = 0 < n <= limit
                body = json.loads(self.rfile.read(n).decode("utf-8")) if 0 < n <= limit else None
                if not isinstance(body, dict):
                    raise ValueError("a JSON object")
                return body

            def _act(self, step: str, say: bool = False):
                """K6, a button that runs a ccx command, in two requests. prepare {project, task, piece|null, btn,
                fill}: the server finds that button in what it shows now, fills and checks the form values and
                answers the exact command with a one-time nonce. run {nonce}: the page's second click (the person
                read the command) runs it once. The page never sends a command, only which button.
                say (I1): the person's reply to a board thread, the same two steps: prepare {project, thread,
                reply_to|null, text} answers what will be written, run {nonce} writes it once (never runs it)."""
                if not self._same_origin():
                    return self._deny("origin")
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    return self._send(415, b'{"error":"json only"}')
                try:
                    body = self._body(SAY_BODY_MAX if say else 4000)
                    if say:
                        out = ui.prepare_say(body) if step == "prepare" else ui.run_say(str(body.get("nonce") or ""))
                    elif step == "prepare":
                        out = ui.prepare(body)
                    else:
                        out = ui.run_prepared(str(body.get("nonce") or ""))
                except (LookupError, FileNotFoundError) as e:
                    return self._send(409, json.dumps({"error": str(e)[:300]}).encode())
                except (ValueError, TypeError, KeyError) as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}).encode())
                return self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"))

            def _same_origin(self) -> bool:
                """Writes (a note's yes / no, a button's command) only from this page. A browser always sends Origin on a POST; it must be this
                server's own, and Sec-Fetch-Site (when sent) same-origin. Host and token are checked before."""
                port = self.server.server_address[1]
                if self.headers.get("Origin", "") not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                    return False
                return self.headers.get("Sec-Fetch-Site", "same-origin") == "same-origin"

            def _suggestion(self):
                """The person's yes or no on a suggested note (H5): {"id": N, "accept": true|false}."""
                if not self._same_origin():
                    return self._deny("origin")
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    return self._send(415, b'{"error":"json only"}')
                try:
                    body = self._body(1000)
                    sid, accept = int(body["id"]), body["accept"]
                    if not isinstance(accept, bool):
                        raise ValueError("accept: true or false")
                except (ValueError, TypeError, KeyError):
                    return self._send(400, b'{"error":"want {\\"id\\": N, \\"accept\\": true|false}"}')
                from . import memsuggest
                try:
                    with ui.lock:
                        out = memsuggest.decide(ui.p, sid, accept)
                except ValueError as e:
                    return self._send(409, json.dumps({"error": str(e)[:200]}).encode())
                return self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"))

            do_HEAD = do_GET

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]

    def find_button(self, want: dict) -> dict:
        """The button `want` names ({project, task, piece|null, btn: "a<i>" act / "c<i>" control}) in the data the
        page is shown now; LookupError when it is gone (the run moved on) or never offered a command to run."""
        with self.lock:
            data = collect(self.p, self.project, self.days, self.reader, quota_wait=False)
        pr = next((x for x in data["projects"] if x["id"] == want.get("project")), None)
        if want.get("task") == "_lead":              # U7: the project's switch-lead panel (its buttons are c<i>)
            tk = (pr or {}).get("lead_switch")
            want = {**want, "piece": None}
        else:
            tk = next((x for x in (pr or {}).get("tasks") or [] if x["id"] == want.get("task")), None)
        if tk is None:
            raise LookupError("that task is no longer on the page: reload")
        holder = tk
        if want.get("piece") is not None:
            holder = next((x for x in _walk(tk["pieces"]) if x["id"] == want.get("piece")), None)
            if holder is None:
                raise LookupError("that piece is no longer on the page: reload")
        m = re.fullmatch(r"([ac])(\d{1,2})", str(want.get("btn") or ""))
        if not m:
            raise ValueError("btn: a<i> or c<i>")
        group = ((holder.get("act") or {}).get("buttons") if m.group(1) == "a" else holder.get("ctl")) or []
        i = int(m.group(2))
        if i >= len(group) or not group[i].get("run"):
            raise LookupError("that button is no longer there, or only shows a command: reload")
        return group[i]

    def prepare(self, want: dict) -> dict:
        b = self.find_button(want)
        argv = fill(b["argv"], want.get("fill"))
        extra = {}
        if b.get("handoff"):                          # U7: from the current lead's session file when there is one
            argv, extra["transcript"] = handoff_argv(self.p, argv, b["handoff"]["by"])
        if argv[1:2] == ["undo"]:                     # the dry run's lists in the confirm box; refused when unsafe
            extra["undo"] = undo_preview(self.p, argv[2])
        if argv[1:3] == ["q", "accept"]:              # a refusal (protected branch, ...) said now, not in a log
            merge_preview(self.p, argv)
        cmd = " ".join(_q(x) for x in argv)
        if self.demo and b["spends"]:                 # U6: a demo hub never starts an agent; the command is shown
            return {"nonce": None, "cmd": cmd, "spends": True, "demo": True, "ttl_s": 0}
        nonce = secrets.token_urlsafe(18)
        now = time.time()
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if v["until"] > now}
            if len(self.pending) >= 20:
                raise LookupError("too many unconfirmed actions: wait a minute")
            self.pending[nonce] = {"argv": argv, "spends": b["spends"], "bg": bool(b.get("bg")),
                                   "until": now + ACT_TTL_S}
        return {"nonce": nonce, "cmd": cmd, "spends": b["spends"], "ttl_s": ACT_TTL_S, **extra}

    def run_prepared(self, nonce: str) -> dict:
        with self.lock:
            job = self.pending.pop(nonce, None)       # once: a second run of the same nonce finds nothing
        if not job or job["until"] < time.time():
            raise LookupError("this confirmation has expired or was used: press the button again")
        if self.demo and job["spends"]:
            raise LookupError("demo data: a command that starts an agent is shown, not run")
        if job["argv"][1:2] == ["undo"]:              # again: a resume may have started since it was prepared
            undo_preview(self.p, job["argv"][2])
        out = execute(self.p, job["argv"], background=job["spends"] or bool(job.get("bg")))
        if job["argv"][1:2] == ["handoff"] and out.get("ok"):
            out["handoff"] = handoff_result(job["argv"], out.get("out") or "")
        return {**out, "cmd": " ".join(_q(x) for x in job["argv"])}

    # ---------------------------------------------------------------- U2 / I1: the conversation and the reply
    def remember_boards(self, data: dict) -> None:
        self.boards = {c["id"]: (Path(c["path"]), c["name"]) for c in data.get("conversations") or []}

    def conv_root(self, pid: str) -> tuple[Path, str]:
        """The folder of a board the page shows (by project id): never a path the page sends."""
        if not _PID.fullmatch(pid or ""):
            raise ValueError("bad project id")
        if pid not in self.boards:
            with self.lock:
                self.remember_boards(collect(self.p, self.project, self.days, self.reader, quota_wait=False))
        if pid not in self.boards:
            raise FileNotFoundError("no conversation for that project")
        return self.boards[pid]

    def conversation(self, pid: str) -> dict:
        root, name = self.conv_root(pid)
        with self.lock:
            return conversation(self.reader, root, self.reader.cfg(), pid, name)

    def prepare_say(self, want: dict) -> dict:
        """The person's reply, first step: check it (a string, not empty, at most SAY_MAX characters: longer is
        refused, nothing is cut), find the thread and the message it answers (default: the thread's last), and
        answer what will be written, with a one-time nonce. Nothing is written yet."""
        text = want.get("text")
        if not isinstance(text, str):
            raise ValueError("text: a string")
        if not text.strip():
            raise ValueError("an empty message")
        if len(text) > SAY_MAX:
            raise ValueError(f"at most {SAY_MAX} characters, this has {len(text)}: nothing was sent or cut")
        root, _ = self.conv_root(str(want.get("project") or ""))
        thread = want.get("thread")
        if not isinstance(thread, str) or not thread:
            raise ValueError("thread: a name")
        msgs = [e for e in board.entries(root) if str(e.get("thread")) == thread]   # a fresh read, read only
        if not msgs:
            raise LookupError("that thread is not on the board: reload")
        rid = want.get("reply_to")
        if rid is None:
            parent = msgs[-1]
        else:
            if isinstance(rid, bool) or not isinstance(rid, int):
                raise ValueError("reply_to: a message id")
            parent = next((e for e in msgs if e.get("id") == rid), None)
            if parent is None:
                raise LookupError("that message is not in this thread: reload")
        to = board.norm(_reply_address(parent), allow_all=True)
        nonce = secrets.token_urlsafe(18)
        now = time.time()
        with self.lock:
            self.says = {k: v for k, v in self.says.items() if v["until"] > now}
            if len(self.says) >= 20:
                raise LookupError("too many unconfirmed replies: wait a minute")
            self.says[nonce] = {"root": root, "thread": thread, "reply_to": parent["id"], "to": to, "text": text,
                                "until": now + ACT_TTL_S}
        return {"nonce": nonce, "thread": thread, "reply_to": parent["id"], "to": to, "chars": len(text),
                "cmd": f"ccx reply {parent['id']}", "ttl_s": ACT_TTL_S}

    def run_say(self, nonce: str) -> dict:
        """Second step: write the prepared reply to the board once, as the person (from user, via ui), the way
        `ccx reply` does: board.post, one JSON line; the text is never run."""
        with self.lock:
            job = self.says.pop(nonce, None)          # once
        if not job or job["until"] < time.time():
            raise LookupError("this confirmation has expired or was used: press reply again")
        e = board.post(job["root"], "user", job["to"], job["text"], thread=job["thread"], reply_to=job["reply_to"],
                       via="ui", max_machine=_max_machine(self.reader.cfg()))
        log = self.p.state / "ui-actions.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "say": {"thread": e["thread"], "id": e["id"], "to": e["to"],
                                                            "reply_to": e["reply_to"], "chars": len(e["text"])},
                                 "via": "ui"}, ensure_ascii=False) + "\n")
        return {"ok": True, "posted": {k: e[k] for k in ("id", "thread", "to", "reply_to", "via")}}

    def _ledger_rows(self) -> list[dict]:
        """Every ledger row (read incrementally), dismissed runs marked as ledger.rows marks them."""
        from .ledger import _mark_dismissed
        with self.lock:
            got = self.reader.lines(self.p.ledger, _fold_rows, []) if self.p.ledger.exists() else []
            return _mark_dismissed([dict(r) for r in got])

    def token_flow(self, period: str = "7d", project: str | None = None, tests: bool = False) -> dict:
        """/api/tokens: the "Measured & where tokens go" page (B1). No `project`: the ui's own project when it was
        started with --project; `project=all`: every project, whatever the ui was started with."""
        if project == "all":
            project = None
        elif project is not None and not _PID.fullmatch(project):
            raise ValueError("bad project id")
        elif project is None and self.project:
            project = _pid(project_root(str(self.project)) or self.project)
        rows = self._ledger_rows()
        with self.flow_lock:
            return self.flow.tokens(rows, period, project, tests)

    def lead_cost(self, agent: str, session: str) -> dict:
        """/api/leadcost: one lead conversation's re-read parts and cache breaks (`ccx lead --breakdown` / `--cache`)."""
        rows = self._ledger_rows()
        with self.flow_lock:
            return self.flow.leadcost(rows, agent, session)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#k={self.token}"

    def judge(self, run_id: str) -> dict:
        """judge(), kept while the run's record is unchanged (the page asks again on every redraw of the card)."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id or ""):
            raise ValueError("bad run id")
        try:
            st = (self.p.runs / run_id / "run.json").stat()
        except OSError:
            raise FileNotFoundError(f"no ccx run {run_id!r}") from None
        key = [(st.st_mtime_ns, st.st_size)]
        for name in ("undo.json", "end.json"):        # end.json is written after the last run.json write
            try:
                sx = (self.p.runs / run_id / name).stat()
                key.append((sx.st_mtime_ns, sx.st_size))
            except OSError:
                key.append(None)
        key = tuple(key)
        hit = self.judged.get(run_id)
        if hit and hit[0] == key:
            return hit[1]
        out = judge(self.p, run_id)
        with self.lock:
            if len(self.judged) > 200:
                self.judged.clear()
            self.judged[run_id] = (key, out)
        return out

    def beat(self, now: float | None = None, hidden: bool = False) -> None:
        """The page says it is still open; `hidden` when its tab is in the background (U3)."""
        self.last_beat = now or time.time()
        self.hidden = bool(hidden)

    def idle_for(self, now: float | None = None) -> float:
        now = now or time.time()
        return now - (self.last_beat or self.started)

    def should_stop(self, now: float | None = None) -> bool:
        """60 s without a heartbeat and the server exits; a page whose last word was "hidden" gets HIDDEN_IDLE_S
        (browsers wake a background tab's timers about once a minute), so a closed tab still ends it, later."""
        if not self.last_beat:
            limit = max(self.idle_s, self.first_beat_s)
        else:
            limit = max(self.idle_s, self.hidden_idle_s) if self.hidden else self.idle_s
        return self.idle_for(now) > limit

    def _watch(self):
        while not self._done.wait(1.0):
            if self.should_stop():
                self.why_stopped = "page closed" if self.last_beat else "page never opened"
                self.httpd.shutdown()
                return

    def serve(self) -> str:
        self._done = threading.Event()
        threading.Thread(target=self._watch, daemon=True).start()
        try:
            self.httpd.serve_forever(poll_interval=0.5)
        finally:
            self._done.set()
            self.httpd.server_close()
        return self.why_stopped or "stopped"

    def stop(self):
        self.why_stopped = "stopped"
        self.httpd.shutdown()


def export(p: Paths, out: Path, project: Path | None = None, days: float = 7) -> Path:
    """A static snapshot: one HTML file with the page, its strings and the data; no server, no polling."""
    data = collect(p, project, days)
    page = _static("index.html").decode("utf-8")
    css = _static("app.css").decode("utf-8")
    js = _static("app.js").decode("utf-8")
    strings = _static("strings.json").decode("utf-8")

    def inline_json(obj_text: str) -> str:      # nothing in the data can close the script element
        return obj_text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = page.replace('<link rel="stylesheet" href="app.css">', f"<style>{css}</style>")
    page = page.replace('<script src="app.js"></script>',
                        f'<script type="application/json" id="ccx-strings">{inline_json(strings)}</script>'
                        f'<script type="application/json" id="ccx-snapshot">'
                        f'{inline_json(json.dumps(data, ensure_ascii=False, default=list))}</script>'
                        f"<script>{js}</script>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def waiting(p: Paths, days: float = 7) -> int:
    """How many recent runs wait for the person (for the session-start line), evaluation runs left out. Run records
    only: cheap."""
    now = time.time()
    rd = Reader(p)
    verdicts = rd.lines(p.ledger, _verdict_rows, {}) if p.ledger.exists() else {}
    scratch = scratch_roots(p)
    n = 0
    for f in (p.runs.glob("*/run.json") if p.runs.exists() else []):
        try:
            if f.stat().st_mtime < now - days * 86400:
                continue
        except OSError:
            continue
        rec = rd.json_file(f)
        if not isinstance(rec, dict) or rec.get("ephemeral") or str(rec.get("label") or "").startswith(INTERNAL):
            continue
        if is_test(rec, scratch):
            continue                                 # an evaluation, test or dismissed run: nobody waits on it
        if rec.get("state") == "running" or not rec.get("run_id"):
            continue
        if _act(rec, verdicts.get(rec["run_id"]), now, None):
            n += 1
    return n


def open_browser(url: str) -> bool:
    import webbrowser
    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001
        return False
