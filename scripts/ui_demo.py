"""A throwaway hub with real ccx runs on the stand-in CLIs (tests/fakes), then `ccx ui` on it.

    python scripts/ui_demo.py [--dir FOLDER] [--export FILE] [--no-serve] [--lang zh|en] [--port N] [--plain]

For screenshots and for trying the page without spending tokens or showing anyone's real work. Every run below is
an ordinary `ccx run` / `ccx q run`; only the CLIs behind them are fakes. One Codex run hangs for a few minutes and
writes growing token counts to its session file, so the page has something live to show."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKES = ROOT / "tests" / "fakes"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="where to build it (default: a new temp folder, kept)")
    ap.add_argument("--export", help="also write a static snapshot here")
    ap.add_argument("--no-serve", action="store_true")
    ap.add_argument("--lang", choices=["zh", "en"])
    ap.add_argument("--port", help="serve on this port (default: a random free one)")
    ap.add_argument("--plain", action="store_true", help="no markup-in-a-title run (for README screenshots)")
    a = ap.parse_args()
    t = Path(a.dir or tempfile.mkdtemp(prefix="ccx-ui-demo-"))
    for sub in ("hub", "codex", "claude"):
        (t / sub).mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CCX_HUB": str(t / "hub"), "CODEX_HOME": str(t / "codex"), "CLAUDE_CONFIG_DIR": str(t / "claude"),
           "CCX_CONFIG": str(t / "cfg.toml"), "CCX_CODEX_BIN": str(FAKES / "fake_codex.py"),
           "CCX_CLAUDE_BIN": str(FAKES / "fake_claude.py"), "CCX_GEMINI_BIN": str(FAKES / "fake_gemini.py"),
           "CCX_AB_RATE": "0", "CCX_NO_BENCH_REFRESH": "1", "CCX_NO_QUOTA_PROBE": "1", "PYTHONUTF8": "1",
           "FAKE_LOG": str(t / "calls.jsonl")}
    for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CCX_DEPTH", "CCX_ROLE", "CCX_LEAD_SESSION"):
        env.pop(k, None)

    def repo(name: str) -> Path:
        d = t / name
        if not (d / ".git").exists():
            d.mkdir(exist_ok=True)
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            (d / "inventory.py").write_text("def restock(items, name, n):\n    pass\n", encoding="utf-8")
            g = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
            subprocess.run([*g, "add", "."], cwd=d, check=True)
            subprocess.run([*g, "commit", "-qm", "init"], cwd=d, check=True)
        return d

    def ccx(cwd: Path, *args: str, **extra) -> dict:
        r = subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args], cwd=cwd, env={**env, **extra},
                           capture_output=True, text=True, encoding="utf-8")
        try:
            return json.loads(r.stdout)
        except ValueError:
            return {"raw": r.stdout[-300:], "err": r.stderr[-300:]}

    shop = repo("shop-api")
    lead = "0d3c6a52-demo-lead-session"
    # the lead's own conversation, as Claude Code keeps it: its first message names the task, its model shows
    tr = t / "claude" / "projects" / "shop-api" / f"{lead}.jsonl"
    tr.parent.mkdir(parents=True, exist_ok=True)
    tr.write_text("\n".join(json.dumps(x) for x in [
        {"type": "user", "sessionId": lead, "message": {"role": "user", "content": "Refactor data loading and add tests"}},
        {"type": "assistant", "sessionId": lead, "cwd": str(shop), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "message": {"id": "m1", "model": "claude-opus-5-5", "usage": {"input_tokens": 10, "output_tokens": 20}}}]) + "\n",
                  encoding="utf-8")
    sub = tr.parent / lead / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "agent-a1b2c3d4.jsonl").write_text(json.dumps({"type": "assistant", "isSidechain": True, "message": {
        "id": "s1", "model": "claude-haiku-5-5", "usage": {"input_tokens": 5}}}) + "\n", encoding="utf-8")
    L = {"CCX_LEAD_SESSION": lead}
    w = ["run", "--from", "claude", "--mode", "write"]
    ccx(shop, *w, "--to", "codex", "--tier", "T1", "--review", "off", "--check", "exit 0", "--label", "restock",
        "In inventory.py add restock(items, name, n)", **L)
    ccx(shop, *w, "--to", "codex", "--tier", "T1", "--review", "on", "--label", "paginate",
        "Make paginate raise ValueError for a bad size", FAKE_REVIEW="issues,issues",
        FAKE_WRITE=f"{shop / 'inventory.py'}=def paginate(xs, size):\n    return [] if size < 1 else xs[:size]\n", **L)
    ccx(shop, "run", "--from", "claude", "--to", "claude", "--tier", "T1", "--mode", "read", "--label",
        "Check the README against the code", "Check whether the README is out of date",
        FAKE_STATUS="blocked", FAKE_SUMMARY="NEEDS_WRITE: README says load() but the code has load_config()", **L)
    done = ccx(shop, *w, "--to", "claude", "--tier", "T1", "--review", "off", "--label", "Config",
               "Move settings into config.py", **L)
    if done.get("run_id"):
        ccx(shop, "verify", done["run_id"], "--ok", "1")
    ccx(shop, *w, "--to", "gemini", "--tier", "T1", "--review", "off", "--label", "Docs",
        "Write docstrings for inventory.py", **L)
    ccx(shop, *w, "--to", "codex", "--tier", "T1", "--review", "off", "--label",
        "Logging" if a.plain else "<img src=x onerror=alert(1)> Logging",
        "Add logging (title with markup, to show it stays text)", **L)
    ccx(shop, *w, "--to", "codex", "--tier", "T1", "--review", "off", "--bg", "--label", "load_config",
        "Write load_config(path) that reads a JSON file", FAKE_STATUS="hang", FAKE_HANG_S="600", **L)

    # a second project with a work queue: one piece split again into its own pieces (a level deeper)
    data = repo("data-pipeline")
    plan = t / "plan.json"
    plan.write_text(json.dumps({"tasks": [
        {"id": "a", "title": "Migration plan", "brief": "Write the migration plan", "to": "codex"},
        {"id": "b", "title": "Port the API", "brief": "Port the API to v2 BIGPIECE", "to": "claude"},
        {"id": "c", "title": "Rollback tests", "brief": "Add rollback tests", "to": "codex", "mode": "write"}]}),
        encoding="utf-8")
    ccx(data, "q", "add", "--plan", str(plan))
    ccx(data, "q", "run", "--once", FAKE_SPLIT_IF="BIGPIECE", FAKE_NEXT_STEP=json.dumps([
        {"title": "GET endpoints", "brief": "Port the GET endpoints"},
        {"title": "POST endpoints", "brief": "Port the POST endpoints"},
        {"title": "API docs", "brief": "Update the API docs", "deps": [0, 1]}]))
    ccx(data, "q", "run", "--once")
    # stand-in quota readings (the fake CLIs report none), where ccx reads real ones: a Codex week running hot
    # (its session logs carry rate_limits) and a calm Claude week (<hub>/ccx/quota.jsonl)
    now = time.time()
    iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))  # noqa: E731
    roll = t / "codex" / "sessions" / time.strftime("%Y/%m/%d") / "rollout-demo-quota.jsonl"
    roll.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "session_meta", "payload": {"id": "demo-quota", "originator": "codex_exec"}}]
    for h, used in ((30, 20), (20, 31), (10, 42), (0.2, 52)):
        rows.append({"timestamp": iso(now - h * 3600), "type": "event_msg", "payload": {"type": "token_count",
                     "rate_limits": {"primary": {"used_percent": used, "window_minutes": 10080,
                                                 "resets_at": int(now + 100 * 3600)}}}})
    roll.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with open(t / "hub" / "ccx" / "quota.jsonl", "w", encoding="utf-8") as fh:
        for h, used in ((30, 0.05), (10, 0.08), (0.2, 0.11)):
            fh.write(json.dumps({"ts": now - h * 3600, "agent": "claude", "window": "seven_day", "used": used,
                                 "resets_at": now + 60 * 3600, "window_minutes": 10080}) + "\n")
    if a.lang:
        ccx(shop, "config", "set", "ui.lang", a.lang)
    # The same complete-run artifacts as the offline `ccx demo`, using this script's fake-CLI run ids.
    sys.path.insert(0, str(ROOT))
    from ccx.config import Paths
    from ccx.ui import seed_run_visibility
    p = Paths(t / "hub")
    seed_run_visibility(p, [f.parent.name for f in p.runs.glob("*/run.json")
                            if not json.loads(f.read_text(encoding="utf-8")).get("ephemeral")])
    print(f"demo hub: {t / 'hub'}", flush=True)
    if a.export:
        print(ccx(shop, "ui", "--export", a.export))
    if a.no_serve:
        return 0
    port = ["--port", a.port] if a.port else []
    return subprocess.call([sys.executable, str(ROOT / "ccx.py"), "ui", "--no-open", *port], cwd=shop, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
