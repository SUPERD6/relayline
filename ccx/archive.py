"""Archive sub-agent sessions so they don't clutter Claude's / Codex's session history.

  Codex   official command: `codex archive <thread>` (and `codex unarchive`), reversible.
  Claude  no archive command: the session transcript (<claude home>/projects/<folder>/<id>.jsonl) is moved to
          <claude home>/ccx-archive/<folder>/ — nothing is deleted, `ccx archive --restore <run>` moves it back.
  dsh     no archive command (0.2.1-rc.3): the session id is added to the desktop app's archived list
          (<DSH_HOME>/storages/workspace.json, global.archivedSessionIds) and taken out again on restore.
  Gemini  no archive command yet: left alone (reported).

One-shot runs (`ccx ask`, `ccx selftest`) are never saved in the first place (--ephemeral /
--no-session-persistence). `sessions.archive` decides when the others go (the user's request, 2026-10-25):
  after_run (default)  as soon as a run's result is final: done and checked (its --check passed, or it checked
                       itself), or judged by `ccx verify`. Anything that may still be continued stays: a quota,
                       timeout, stop, kill, blocked or failed check; named seats; discussions and reviews. A session
                       archived this way is put back by itself when it is continued (`ccx resume`, the next task in
                       the auto-continue window): codex unarchive / the transcript moved back.
  hours                only `sessions.auto_archive_hours` after the run, at session start (the old behaviour)
  off                  never by itself
At session start, finished runs older than `sessions.auto_archive_hours` (default 2, 0 = off) are archived in both
after_run and hours modes; `ccx archive` does it on demand.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import ledger
from .config import Paths, claude_home, load_config
from .runners import bin_argv, find_bin


def _log(p: Paths) -> Path:
    return p.state / "archived.jsonl"


def _entries(p: Paths) -> list[dict]:
    f = _log(p)
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def archived_ids(p: Paths, after_run: bool = True) -> set[str]:
    """Runs whose sessions are archived now. after_run=False leaves out those archived by `after_run` (they come
    back by themselves when continued, so they still count as continuable)."""
    out, auto = set(), set()
    for e in _entries(p):
        if e.get("restored"):
            out.discard(e["run_id"])
            auto.discard(e["run_id"])
        else:
            out.add(e["run_id"])
            (auto.add if e.get("why") == "after_run" else auto.discard)(e["run_id"])
    return out if after_run else out - auto


def finished_runs(p: Paths, older_than_h: float = 0) -> list[str]:
    done = archived_ids(p)
    cutoff = time.time() - older_than_h * 3600
    return [r["run_id"] for r in ledger.rows(p)
            if not r.get("type") and r["run_id"] not in done
            and (not r.get("ephemeral") or str(r.get("label") or "").startswith("discuss:"))  # those keep a session
            and not str(r.get("label") or "").startswith("seat:")     # named seats keep their session
            and (r.get("ts") or 0) <= cutoff and (r.get("sessions") or r.get("session_id"))]


def _sessions(p: Paths, run_id: str) -> list[tuple[str, str]]:
    rec = ledger.load_run(p, run_id)
    seen, out = set(), []
    for a in rec.get("attempts", []):
        sid = a.get("session_id")
        if sid and sid not in seen:
            seen.add(sid)
            out.append((a.get("agent") or rec["to"], sid))
    return out


def _claude_transcript(sid: str) -> Path | None:
    from .transcript import claude_session_file
    return claude_session_file(sid, claude_home())


def _run(argv: list[str]) -> tuple[int, str]:
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout or r.stderr).strip()[-300:]


def dsh_desktop_open() -> bool:
    """Is the DeepSeek Harness desktop app running? (CCX_DSH_DESKTOP=open|closed overrides, for tests.)"""
    forced = os.environ.get("CCX_DSH_DESKTOP")
    if forced in ("open", "closed"):
        return forced == "open"
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq DeepSeek Harness.exe", "/NH"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=20)
            return "deepseek harness" in r.stdout.lower()
        r = subprocess.run(["pgrep", "-f", "DeepSeek Harness"], capture_output=True, stdin=subprocess.DEVNULL,
                           timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False                       # can't tell: write it (at worst the app writes its own copy back)


def _dsh_files() -> tuple[Path, Path]:
    from .agents.dsh import dsh_home
    f = dsh_home() / "storages" / "workspace.json"
    return f, f.with_name(f.name + ".ccx-pending.json")


def dsh_mark(sid: str, archived: bool) -> tuple[bool, str]:
    """DeepSeek Harness has no archive command (0.2.1-rc.3). Its desktop app keeps the archived list in
    <DSH_HOME>/storages/workspace.json, global.archivedSessionIds (what its own archiveSession / unarchiveSession
    change). Add or remove only this one session id: the file is backed up first (workspace.json.ccx-backup) and
    replaced atomically; nothing else in it is touched.
    While the desktop app is open it keeps that list in memory and writes it back on its next change, dropping
    what ccx wrote (checked 2026-10-25). So then the change is queued next to the file (workspace.json.ccx-pending.json,
    shared by every hub) and written by the first ccx call that finds the app closed (dsh_flush)."""
    f, pend = _dsh_files()
    if not f.exists():
        return False, "no desktop workspace file (the desktop app was never opened here)"
    if dsh_desktop_open():
        try:
            q = json.loads(pend.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            q = {"add": [], "remove": []}
        keep, drop = ("add", "remove") if archived else ("remove", "add")
        q[drop] = [x for x in q.get(drop, []) if x != sid]
        q[keep] = [*[x for x in q.get(keep, []) if x != sid], sid]
        try:
            pend.write_text(json.dumps(q, indent=1), encoding="utf-8")
        except OSError as e:
            return False, f"could not queue it in {pend}: {e}"
        # closing its window is not enough: it stays in the tray, still running (seen 2026-10-25)
        return True, ("queued: the desktop app is running; written once it is quit (closing its window leaves it "
                      "in the tray: quit it there)")
    dsh_flush()                            # anything still queued from when it was open goes in first
    return _dsh_write({sid} if archived else set(), set() if archived else {sid})


def dsh_flush() -> str:
    """Write what was queued while the desktop app was open, if it is closed now. Returns what happened."""
    f, pend = _dsh_files()
    if not pend.exists() or dsh_desktop_open():
        return ""
    try:
        q = json.loads(pend.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        q = {}
    ok, msg = _dsh_write(set(q.get("add") or []), set(q.get("remove") or []))
    if ok:
        pend.unlink(missing_ok=True)
    return msg


def _dsh_write(add: set[str], remove: set[str]) -> tuple[bool, str]:
    from .ledger import replace
    f, pend = _dsh_files()
    try:
        raw = f.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return False, "no desktop workspace file (the desktop app was never opened here)"
    ids = (data.get("global") or {}).get("archivedSessionIds")
    if not isinstance(ids, list):
        return False, "workspace file without global.archivedSessionIds (another dsh version?)"
    new = [x for x in ids if x not in remove] + sorted(x for x in add if x not in ids and x not in remove)
    if new == ids:
        return True, "already so"
    ids[:] = new
    try:
        f.with_name(f.name + ".ccx-backup").write_text(raw, encoding="utf-8")
        tmp = f.with_name(f.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")   # as dsh writes it
        replace(tmp, f)
    except OSError as e:
        return False, f"could not write {f}: {e}"
    return True, "ok"


def archive(p: Paths, run_ids: list[str], apply: bool = False, why: str = "") -> dict:
    rows, handled = [], {}            # (agent, session) -> first run that archived it in this call
    for run_id in run_ids:
        try:
            sessions = _sessions(p, run_id)
        except FileNotFoundError:
            continue
        done = []
        for agent, sid in sessions:
            if (agent, sid) in handled:       # auto-continued runs share a session: archive it once
                first, original = handled[(agent, sid)]
                if apply and original is not False:
                    done.append([agent, sid, original])
                rows.append({"run_id": run_id, "agent": agent, "session": sid,
                             "action": f"same session as {first}: handled there"})
                continue
            handled[(agent, sid)] = (run_id, False)
            if agent == "codex":
                action = f"codex archive {sid}"
                if apply:
                    if not find_bin("codex"):
                        action += " (skipped: codex CLI not found)"
                        rows.append({"run_id": run_id, "agent": agent, "session": sid, "action": action})
                        continue
                    rc, msg = _run([*bin_argv("codex"), "archive", sid])
                    action += " -> ok" if rc == 0 else f" -> failed: {msg}"
                    if rc == 0:
                        done.append([agent, sid, None])
                        handled[(agent, sid)] = (run_id, None)
            elif agent == "dsh":
                action = f"dsh desktop: add {sid} to archivedSessionIds"
                if apply:
                    ok, msg = dsh_mark(sid, archived=True)
                    action += (" -> " + ("ok" if msg in ("ok", "already so") else msg)) if ok else f" -> skipped: {msg}"
                    if ok:
                        done.append([agent, sid, "dsh-list"])
                        handled[(agent, sid)] = (run_id, "dsh-list")
            elif agent == "claude":
                src = _claude_transcript(sid)
                if not src:
                    rows.append({"run_id": run_id, "agent": agent, "session": sid, "action": "no transcript (not saved)"})
                    continue
                dst = claude_home() / "ccx-archive" / src.parent.name / src.name
                action = f"move {src} -> {dst}"
                if apply:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                    done.append([agent, sid, str(src)])
                    handled[(agent, sid)] = (run_id, str(src))
            else:
                action = f"{agent}: no archive command, left alone"
            rows.append({"run_id": run_id, "agent": agent, "session": sid, "action": action})
        if apply:
            _log(p).parent.mkdir(parents=True, exist_ok=True)
            with open(_log(p), "a", encoding="utf-8") as f:
                f.write(json.dumps({"run_id": run_id, "sessions": done, "ts": time.time(),
                                    **({"why": why} if why else {})}) + "\n")
    return {"applied": apply, "runs": len(run_ids), "sessions": rows,
            "note": "" if apply else "dry run: add --apply"}


def restore(p: Paths, run_id: str) -> dict:
    entries = _entries(p)
    last = next((e for e in reversed(entries) if e["run_id"] == run_id and not e.get("restored")), None)
    if not last:
        raise FileNotFoundError(f"run {run_id} is not archived")
    out = []
    for agent, sid, original in last["sessions"]:
        if agent == "codex":
            rc, msg = _run([*bin_argv("codex"), "unarchive", sid])
            out.append({"session": sid, "action": "codex unarchive -> " + ("ok" if rc == 0 else msg)})
        elif agent == "dsh":
            ok, msg = dsh_mark(sid, archived=False)
            out.append({"session": sid, "action": "dsh desktop: removed from archivedSessionIds"
                        if ok and msg in ("ok", "already so") else f"dsh desktop: {msg}"})
        elif agent == "claude" and original:
            src = claude_home() / "ccx-archive" / Path(original).parent.name / Path(original).name
            if src.exists():
                Path(original).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), original)
            out.append({"session": sid, "action": f"moved back to {original}"})
    with open(_log(p), "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_id": run_id, "restored": True, "ts": time.time()}) + "\n")
    return {"run_id": run_id, "restored": out}


def auto(p: Paths) -> int:
    """Quiet housekeeping at session start: archive finished runs older than sessions.auto_archive_hours."""
    try:
        dsh_flush()                        # what was queued while the dsh desktop app was open
    except Exception:  # noqa: BLE001 — never break session start
        pass
    hours = float((load_config(p).get("sessions") or {}).get("auto_archive_hours", 2) or 0)
    if hours <= 0 or mode(p) == "off":
        return 0
    ids = finished_runs(p, older_than_h=hours)
    if ids:
        archive(p, ids, apply=True)
    return len(ids)


KEEP_LABELS = ("discuss:", "review:", "seat:", "quota-probe", "selftest")   # their own lifetimes: left as they are


def mode(p: Paths) -> str:
    """sessions.archive: after_run (default) | hours | off."""
    return str((load_config(p).get("sessions") or {}).get("archive", "after_run") or "after_run")


def is_final(record: dict) -> bool:
    """Nothing more will be done in this run's session: judged by the lead, or done and checked."""
    v = record.get("verdict") or {}
    if v and not v.get("soft"):
        return True
    from .coverage import reviewed_ok
    if (record.get("state") != "finished" or not record.get("ok")
            or not (record.get("kind") == "ok" or (record.get("kind") == "ok_self_checked" and reviewed_ok(record)))):
        return False                       # quota, timeout, stop, kill, blocked, failed check, review issues ...
    res = record.get("result") or {}
    if res.get("status") != "done":
        return False
    if record.get("check"):
        return bool(record["check"].get("passed"))
    return res.get("verification", "not-run") not in ("", "not-run")


def after_run(p: Paths, record: dict) -> dict | None:
    """sessions.archive = after_run: archive a run's session the moment its result is final. Best effort."""
    if os.environ.get("CCX_NO_AUTO_ARCHIVE") == "1" or mode(p) != "after_run":
        return None
    if record.get("ephemeral") or str(record.get("label") or "").startswith(KEEP_LABELS) or not is_final(record):
        return None
    if record["run_id"] in archived_ids(p) or not record.get("session_id"):
        return None
    return archive(p, [record["run_id"]], apply=True, why="after_run")


def bring_back(p: Paths, session: str | None) -> dict | None:
    """Before a run continues `session`: if it is archived, put it back (codex unarchive / move the transcript)."""
    if not session:
        return None
    gone = archived_ids(p)
    for e in reversed(_entries(p)):
        if e["run_id"] in gone and any(s[1] == session for s in e.get("sessions") or []):
            return restore(p, e["run_id"])
    return None
