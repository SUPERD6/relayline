"""Subscription quota by pace: how much of each window will be used by the time it resets.

Readings:
  Codex  — every token_count line of its own session logs carries rate_limits.{primary,secondary}: used_percent,
           window_minutes, resets_at (codex-cli 0.164). Whatever windows the plan has (weekly; Plus also 5 hours)
           are read as they come; the plan's name is never needed.
  Claude — its logs carry no quota. A Claude sub-agent's stream-json has rate_limit_event.rate_limit_info
           .unifiedWindows.{five_hour, seven_day}: utilization 0..1, resetsAt (Claude Code 2.1.309). ccx keeps each
           one in <hub>/ccx/quota.jsonl when it runs Claude; `probe` asks a tiny question just to get one.

Pace: within the current window (readings since its reset only — a drop in use or a later reset time means a new
window, e.g. after a plan change), the rate over the last 48 hours is projected to the reset. With less than six
hours of readings it is too early to project and the current share is used as it is."""
from __future__ import annotations

import json
import time
from pathlib import Path

WINDOW_MIN = {"five_hour": 300, "seven_day": 10080}
RATE_HOURS = 48
MIN_SPAN_HOURS = 6
PROBE_AFTER_S = 3600


def _file(p) -> Path:
    return p.state / "quota.jsonl"


def save_claude(p, events: list[dict]) -> int:
    """Keep the Claude windows from a run's stream events (rate_limit_event). Returns how many were kept."""
    out = []
    for ev in events:
        info = (ev.get("rate_limit_info") or {}) if ev.get("type") == "rate_limit_event" else {}
        for win, w in (info.get("unifiedWindows") or {}).items():
            if isinstance(w, dict) and w.get("utilization") is not None:
                out.append({"ts": time.time(), "agent": "claude", "window": win, "used": float(w["utilization"]),
                            "resets_at": w.get("resetsAt"), "window_minutes": WINDOW_MIN.get(win)})
    if out:
        f = _file(p)
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            for r in out:
                fh.write(json.dumps(r) + "\n")
    return len(out)


def claude_readings(p, days: float = 8) -> list[dict]:
    since = time.time() - days * 86400
    try:
        lines = _file(p).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if (r.get("ts") or 0) >= since:
            out.append(r)
    return out


TAIL_BYTES = 64 * 1024     # a session file's quota lines are near its end: read only this much of each
RECENT_FILES = 40          # session files changed within RATE_HOURS, newest first, at most this many ...
MORE_FILES = 5             # ... and when none of them has a quota line, up to this many older ones
SAMPLE_BYTES = 32 * 1024


def _tail_readings(f: Path) -> list[dict]:
    """Quota readings in the last TAIL_BYTES of one Codex session file, plus small pieces further back at twice the
    distance each time (128 KB, 256 KB, ... from the end, and the start): a session open for days keeps readings
    from every age, which the pace over RATE_HOURS needs. Only lines with rate_limits are parsed."""
    from .usage import _ts
    lines = []
    with open(f, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        spots = [(max(0, size - TAIL_BYTES), TAIL_BYTES)]
        back = 2 * TAIL_BYTES
        while back < size:
            spots.append((size - back, SAMPLE_BYTES))
            back *= 2
        if size > TAIL_BYTES:
            spots.append((0, SAMPLE_BYTES))
        for at, n in spots:
            fh.seek(at)
            part = fh.read(n).decode("utf-8", errors="replace").splitlines()
            lines += part[1:] if at else part        # a piece starts in the middle of a line
    out = []
    for line in lines:
        if '"rate_limits"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t = _ts(e.get("timestamp"))
        rl = (e.get("payload") or {}).get("rate_limits") or {}
        for win in ("primary", "secondary"):
            w = rl.get(win) or {}
            if t is not None and w.get("used_percent") is not None:
                out.append({"ts": t, "agent": "codex", "window": win, "used": w["used_percent"] / 100,
                            "resets_at": w.get("resets_at"), "window_minutes": w.get("window_minutes")})
    return out


def codex_readings(days: float = 8, p=None, home: Path | None = None, now: float | None = None) -> list[dict]:
    """Codex's quota readings, read only from the end of its newest session files (seconds -> milliseconds: a week
    of logs was read whole before, 9.65 of `ccx route`'s 10 s, PR #30). With a hub `p`, each file's readings are
    kept by (path, mtime, size) in <hub>/ccx/codex-quota-cache.json, so a later call re-reads only changed files."""
    from .config import codex_home
    now = now or time.time()
    root = (home or codex_home()) / "sessions"
    files = []
    from .usage import walk
    for f in walk(root, "rollout-*.jsonl"):
        try:
            st = f.stat()
        except OSError:
            continue
        if st.st_mtime >= now - days * 86400:
            files.append((st.st_mtime, st.st_size, f))
    files.sort(reverse=True)
    cf = p.state / "codex-quota-cache.json" if p is not None else None
    try:
        cache = json.loads(cf.read_text(encoding="utf-8")) if cf else {}
    except (OSError, ValueError):
        cache = {}
    new_cache, out, extra = {}, [], 0
    for k, (mtime, size, f) in enumerate(files):
        recent = mtime >= now - RATE_HOURS * 3600 and k < RECENT_FILES
        if not recent:
            if out or extra >= MORE_FILES:
                break
            extra += 1                     # nothing recent says anything: look a little further back
        hit = cache.get(str(f))
        if hit and hit[0] == mtime and hit[1] == size:
            rs = hit[2]
        else:
            try:
                rs = _tail_readings(f)
            except OSError:
                continue
        new_cache[str(f)] = [mtime, size, rs]
        out += rs
    if cf and new_cache != cache:
        try:
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps(new_cache), encoding="utf-8")
        except OSError:
            pass
    return [r for r in out if r["ts"] >= now - days * 86400]


def pace(readings: list[dict], now: float | None = None) -> dict:
    """window -> {used, projected, resets_at, hours_left, per_day, note}."""
    now = now or time.time()
    out = {}
    for win in sorted({r["window"] for r in readings}):
        rs = sorted((r for r in readings if r["window"] == win), key=lambda r: r["ts"])
        last = rs[-1]
        reset = last.get("resets_at")
        freshness = round(max(0, now - last["ts"]) / 60, 1)
        if reset and reset <= now:
            # the window has reset since the last reading: what it says no longer applies
            out[win] = {"used": None, "projected": 0.0, "resets_at": reset, "hours_left": 0.0,
                        "freshness": freshness, "reading_age_min": round(freshness),
                        "note": "window has reset since the last reading"}
            continue
        # the current window: same reset time as the latest reading, and no drop in use since
        cur = [r for r in rs if r.get("resets_at") is None or reset is None or abs(r["resets_at"] - reset) < 120]
        for i in range(len(cur) - 1, 0, -1):
            if cur[i]["used"] + 0.02 < cur[i - 1]["used"]:
                cur = cur[i:]
                break
        hours_left = max(0.0, (reset - now) / 3600) if reset else None
        recent = [r for r in cur if r["ts"] >= last["ts"] - RATE_HOURS * 3600]
        span = (last["ts"] - recent[0]["ts"]) / 3600 if recent else 0
        row = {"used": round(last["used"], 3), "resets_at": reset,
               "hours_left": round(hours_left, 1) if hours_left is not None else None,
               "reading_age_min": round((now - last["ts"]) / 60),
               "freshness": freshness,
               "read_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(last["ts"]))}   # when the reading was taken
        if span >= MIN_SPAN_HOURS and hours_left is not None:
            per_h = max(0.0, (last["used"] - recent[0]["used"]) / span)
            row.update(per_day=round(per_h * 24, 3), projected=round(last["used"] + per_h * hours_left, 3))
        else:
            row.update(projected=round(last["used"], 3), note="too early to project (less than 6 h of readings)")
        out[win] = row
    for row in out.values():
        row["projected_at_reset"] = row["projected"]
    return out


def pressure(p, given: dict | None = None) -> dict:
    """agent -> projected share of its tightest window by its reset (what the total cost prices quota with).
    Explicit values (--quota claude=0.8) win; else Codex from its logs and Claude from kept readings."""
    q = dict(given or {})
    detail = {}
    for agent, readings in (("codex", codex_readings(p=p)), ("claude", claude_readings(p))):
        if not readings:
            continue
        pc = pace(readings)
        if pc:
            detail[agent] = pc
            if agent not in q and any(w.get("used") is not None for w in pc.values()):
                q[agent] = max(w["projected"] for w in pc.values())
    return {"quota": q, "pace": detail,
            "freshness": {ag: min((w["freshness"] for w in detail.get(ag, {}).values()), default=None)
                          for ag in ("claude", "codex")}}


def backfill(p) -> int:
    """Read the Claude windows out of past run logs (once, to start with some history)."""
    n = 0
    for f in sorted(p.runs.glob("*/events.*.log")) if p.runs.exists() else []:
        try:
            lines = [x for x in f.read_text(encoding="utf-8", errors="replace").splitlines()
                     if '"rate_limit_event"' in x]
        except OSError:
            continue
        evs = []
        for x in lines:
            try:
                evs.append(json.loads(x))
            except ValueError:
                pass
        if evs:
            ts = f.stat().st_mtime
            for ev in evs:
                for win, w in ((ev.get("rate_limit_info") or {}).get("unifiedWindows") or {}).items():
                    if isinstance(w, dict) and w.get("utilization") is not None:
                        with open(_file(p), "a", encoding="utf-8") as fh:
                            fh.write(json.dumps({"ts": ts, "agent": "claude", "window": win,
                                                 "used": float(w["utilization"]), "resets_at": w.get("resetsAt"),
                                                 "window_minutes": WINDOW_MIN.get(win)}) + "\n")
                        n += 1
    return n


def _stops_file(p) -> Path:
    return p.state / "quota-stops.jsonl"


def stop_evidence(cli: str, stdout: str, stderr: str, error: str | None) -> dict:
    """Why an attempt was taken for a quota stop (H2): Claude's rejected rate_limit_event as it came, else the hint
    in runners.QUOTA_HINTS that matched and the words around it. Kept so a wrong call ("quota" in a task's own
    text, a new wording of a real limit) can be found and the hints corrected, without spending quota to test."""
    from .runners import QUOTA_HINTS
    if cli == "claude":
        for line in stdout.splitlines():
            if '"rate_limit_event"' not in line:
                continue
            try:
                info = json.loads(line).get("rate_limit_info") or {}
            except ValueError:
                continue
            if str(info.get("status", "")).lower() in ("rejected", "exceeded", "blocked"):
                return {"by": "rate_limit_event", "event": {k: info.get(k) for k in (
                    "status", "rateLimitType", "resetsAt", "overageStatus", "isUsingOverage") if k in info}}
    text = " ".join(x for x in (error, stderr[-4000:], stdout[-4000:]) if x)
    low = text.lower()
    for h in QUOTA_HINTS:
        i = low.find(h)
        if i != -1:
            return {"by": "hint", "hint": h, "text": " ".join(text[max(0, i - 160): i + 160].split())}
    return {"by": "unknown"}


def log_stop(p, run_id: str, attempt: dict, evidence: dict) -> None:
    """One line per quota stop in <hub>/ccx/quota-stops.jsonl (shown by `ccx quota`)."""
    row = {"ts": time.time(), "run_id": run_id, "agent": attempt.get("agent"), "model": attempt.get("model"),
           "effort": attempt.get("effort"), "retry_after": attempt.get("retry_after"),
           "seconds": attempt.get("seconds"), **evidence}
    f = _stops_file(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def recent_stops(p, n: int = 5) -> list[dict]:
    try:
        lines = _stops_file(p).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def claude_reading_age(p) -> float | None:
    rs = claude_readings(p, days=8)
    return (time.time() - max(r["ts"] for r in rs)) if rs else None


def probe(p) -> int:
    """Legacy --probe: keep the option, using the same tiny Claude probe as --refresh."""
    return refresh(p, ["claude"])["claude"].get("readings", 0)


def _refresh_file(p) -> Path:
    return p.state / "quota-refresh.json"


def _refresh_state(p) -> dict:
    try:
        return json.loads(_refresh_file(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _probe_agent(p, agent: str) -> dict:
    """No project context or delegation; Claude has no tools, Codex is read-only.
    Flags checked: Claude 2.1.316 / Codex 0.164.0 --help.
    Cost is the CLI's reported cost or an API-equivalent estimate, never invented when unavailable."""
    import os
    import subprocess
    import tempfile
    from . import learn
    from .runners import bin_argv
    from .agents.claude import parse_claude
    from .agents.codex import parse_codex

    row = {"ts": time.time(), "agent": agent, "source": "probe", "readings": 0,
           "cost_usd": None, "ae_usd": None, "target_usd": 0.005}
    model = "haiku" if agent == "claude" else "gpt-6-luna"
    try:
        argv = bin_argv(agent)
        if agent == "claude":
            argv += ["-p", "--model", model, "--effort", "low", "--output-format", "stream-json", "--verbose",
                     "--system-prompt", "Reply OK.", "--tools", "", "--strict-mcp-config",
                     "--disable-slash-commands", "--setting-sources", "", "--no-session-persistence",
                     "--max-budget-usd", "0.005"]
        else:
            argv += ["exec", "--json", "-m", model, "-s", "read-only", "--skip-git-repo-check",
                     "--ignore-user-config", "-c", 'model_reasoning_effort="low"',
                     "-c", 'web_search="disabled"', "-c", "features.multi_agent=false",
                     "-c", "features.plugins=false", "-c", "features.apps=false", "-"]
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        # A lead using Claude Code against a third-party server is not the Claude subscription.
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(key, None)
        with tempfile.TemporaryDirectory(prefix="ccx-quota-") as tmp:
            r = subprocess.run(argv, input="Reply OK. Do not use tools.", cwd=tmp, env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        events = []
        for line in r.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        if agent == "claude":
            row["readings"] = save_claude(p, events)
            oc = parse_claude(r.stdout, r.stderr, r.returncode)
        else:
            row["readings"] = sum(r["ts"] >= row["ts"] for r in codex_readings(p=p))
            oc = parse_codex(r.stdout, r.stderr, r.returncode, None)
        row.update(exit_code=r.returncode, usage=oc.usage, cost_usd=oc.cost_usd,
                   ae_usd=learn.price_usd(p, agent, model, oc.usage) if oc.usage else None)
        if not row["readings"]:
            row["error"] = "probe returned no quota windows; reading remains Unknown/stale"
        if r.returncode:
            row["error"] = oc.error or oc.kind
    except (OSError, subprocess.SubprocessError) as e:
        row["error"] = f"{type(e).__name__}: {e}"
    return row


def refresh(p, agents: list[str] | None = None, *, max_age_min: float | None = None) -> dict:
    """Refresh each subscription once; Codex reuses current disk readings before spending a request.
    Attempts, including failures, are recorded so an unreadable quota cannot cause a probe on every command."""
    from .config import load_config
    if max_age_min is None:
        max_age_min = float((load_config(p).get("quota") or {}).get("auto_refresh_min", 60) or 60)
    if max_age_min <= 0:
        max_age_min = 60                       # explicit refresh still works with automatic refresh off
    state, out = _refresh_state(p), {}
    for agent in dict.fromkeys(agents if agents is not None else ("claude", "codex")):
        if agent not in ("claude", "codex"):
            continue
        rs = codex_readings(p=p) if agent == "codex" else []
        windows = pace(rs)
        current = bool(windows) and all(w.get("used") is not None and w["freshness"] <= max_age_min
                                        for w in windows.values())
        row = ({"ts": time.time(), "agent": agent, "source": "session_files", "readings": len(rs),
                "cost_usd": 0.0, "ae_usd": 0.0} if current else _probe_agent(p, agent))
        state[agent] = row
        out[agent] = row
        p.state.mkdir(parents=True, exist_ok=True)
        with open(p.state / "quota-refresh.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    f = _refresh_file(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return out


def maybe_refresh(p, cfg: dict, agents: list[str] | None = None, given: dict | None = None) -> dict:
    """Refresh only an existing reading older than the interval; unknown subscriptions need --refresh.
    0/false disables automatic refresh; explicit --refresh still works."""
    import os
    from .runners import find_bin
    minutes = (cfg.get("quota") or {}).get("auto_refresh_min", 60)
    if not minutes or float(minutes) <= 0 or os.environ.get("CCX_NO_QUOTA_PROBE") == "1":
        return {}
    pr, state, due = pressure(p), _refresh_state(p), []
    for ag in agents if agents is not None else ("claude", "codex"):
        if ag not in ("claude", "codex") or ag in (given or {}) or not find_bin(ag):
            continue
        if ag == "claude" and not (cfg.get("quota") or {}).get("probe_claude", True):
            continue                         # retain the existing opt-out
        age = pr["freshness"].get(ag)
        stale = age is not None and age > float(minutes)
        if stale and time.time() - (state.get(ag) or {}).get("ts", 0) >= float(minutes) * 60:
            due.append(ag)
    return refresh(p, due, max_age_min=float(minutes)) if due else {}


def at_start(p) -> dict:
    """Read the snapshot for run.json only; no probe, run directory or ledger row."""
    return pressure(p)


def summary(p) -> str:
    """Read-only doctor line: Unknown stays Unknown and expired windows never imply zero use."""
    pr = pressure(p)
    parts = []
    for ag in ("claude", "codex"):
        wins = pr["pace"].get(ag) or {}
        desc = ", ".join(f"{win} {w['used']:.0%}" if w.get("used") is not None else f"{win} Unknown"
                         for win, w in wins.items()) or "Unknown"
        age = pr["freshness"].get(ag)
        parts.append(f"{ag}: {desc}" + (f" ({age:g} min old)" if age is not None else ""))
    return "; ".join(parts)


def reset_text(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(ts)) if ts else "Unknown reset time"
