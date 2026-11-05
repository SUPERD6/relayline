"""`ccx setup`: a guided first run — check, hub, init, sync (preview, then apply on a yes), doctor, notes from your
recent sessions (L6, each one only on a yes), selftest.

Every change is previewed and asked about first. Not on a terminal and no --yes (an agent running it, a pipe): it
shows the whole plan as the commands to run and changes nothing.
Goal: a new user delegates for the first time within five minutes."""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

from .config import hub_dir, paths, user_config_file
from .runners import bin_argv, find_bin

STEPS = 7
COLD_DAYS = 7          # L6: how far back the first run looks for preferences and pitfalls
COLD_FILES = 20        # newest session files read, at most
COLD_ASK = 10          # suggestions asked about one by one; the rest wait in `ccx mem suggestions`
LOGIN = {"codex": "codex login", "claude": "claude  (then /login)", "gemini": "gemini  (then sign in)"}
# The first delegation README, docs/install and setup all suggest: long enough to be delegated (a three-word summary
# scored T0 and was refused as do-it-yourself in the 2026-10-29 new-user walkthrough), a summary, so the cheapest
# rung; read-only.
FIRST_TASK = ("Summarise README.md in three lines for a new user: what this project does, how to install it, "
              "and the first command to try")


def first_command(to: str = "codex") -> str:
    return f'ccx run --to {to} --mode read "{FIRST_TASK}"'


class Wizard:
    def __init__(self, yes: bool, interactive: bool):
        self.yes, self.interactive = yes, interactive

    def say(self, text: str = "") -> None:
        print(text, flush=True)

    def step(self, n: int, title: str) -> None:
        self.say(f"\n[{n}/{STEPS}] {title}")

    def ask(self, question: str, default: bool = False) -> bool:
        if self.yes:
            self.say(f"  {question} yes (--yes)")
            return True
        if not self.interactive:
            self.say(f"  {question} (skipped: not on a terminal; run `ccx setup` yourself, or add --yes)")
            return False
        hint = "Y/n" if default else "y/N"
        try:
            ans = input(f"  {question} [{hint}] ").strip().lower()
        except EOFError:                     # input ended (e.g. Windows NUL looks like a terminal)
            self.interactive = False
            self.say("\n  (no answer: input ended) — treated as no")
            return False
        return default if not ans else ans in ("y", "yes", "是", "好")

    def text(self, question: str, default: str) -> str:
        if self.yes or not self.interactive:
            return default
        try:
            ans = input(f"  {question} [{default}] ").strip()
        except EOFError:
            self.interactive = False
            self.say("")
            return default
        return ans or default


def _login_ok(agent: str) -> bool | None:
    import subprocess
    cmd = {"codex": ["login", "status"], "claude": ["auth", "status"]}.get(agent)
    if not cmd:
        return None
    try:
        r = subprocess.run([*bin_argv(agent), *cmd], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "") + (r.stderr or "")
    try:
        return bool(json.loads(r.stdout).get("loggedIn"))
    except (json.JSONDecodeError, AttributeError):
        return r.returncode == 0 and "not logged in" not in out.lower()


def recent_sessions(days: float = COLD_DAYS, limit: int = COLD_FILES, now: float | None = None) -> list[tuple[str, Path]]:
    """The person's own recent Claude Code and Codex sessions (not ccx sub-runs, not sub-agents), newest first."""
    import time
    from .config import claude_home, codex_home
    from .usage import codex_parent
    since = (time.time() if now is None else now) - days * 86400
    found: list[tuple[float, str, Path]] = []
    root = claude_home() / "projects"
    for f in (root.glob("*/*.jsonl") if root.exists() else []):
        try:
            if (mt := f.stat().st_mtime) >= since:
                found.append((mt, "claude", f))
        except OSError:
            continue
    root = codex_home() / "sessions"
    from .usage import walk
    for f in walk(root, "rollout-*.jsonl"):
        try:
            if (mt := f.stat().st_mtime) < since:
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                meta = (json.loads(fh.readline() or "{}").get("payload") or {})
        except (OSError, ValueError):
            continue
        if meta.get("originator") == "codex_exec" or codex_parent(meta):
            continue
        found.append((mt, "codex", f))
    found.sort(key=lambda x: -x[0])
    return [(agent, f) for _, agent, f in found[:limit]]


def cold_start(w: Wizard, p) -> None:
    """L6: on a new hub, offer the preferences and pitfalls ccx's rules (memsuggest, no model) find in the last few
    days of sessions; each one goes to shared memory only on a yes, through `ccx mem accept`'s own path."""
    if w.yes or not w.interactive:
        w.say("  skipped (asks one by one, so only on a terminal); later: `ccx mem suggest --from-transcript "
              "claude|codex`, then `ccx mem suggestions`")
        return
    if not w.ask(f"Look through your Claude Code / Codex sessions of the last {COLD_DAYS} days for preferences and "
                 "pitfalls worth keeping? (read only; rules, no model)", default=True):
        return
    from . import memsuggest
    from .transcript import read_claude, read_codex
    added: list[dict] = []
    for agent, f in recent_sessions():
        try:
            d = (read_claude if agent == "claude" else read_codex)(f)
            added += memsuggest.add(p, memsuggest.gather(d, f))
        except Exception:  # noqa: BLE001 — one odd session file must not stop setup
            continue
    if not added:
        w.say("  nothing found — fine; ccx suggests notes again when work is handed over")
        return
    order = {"preference": 0, "decision": 1, "pitfall": 2}
    added.sort(key=lambda i: (i.get("by") != "user", order.get(i.get("kind"), 3)))
    w.say(f"  {len(added)} candidate(s); each is written to shared memory only if you say yes:")
    kept = 0
    for it in added[:COLD_ASK]:
        w.say(f"  #{it['id']} ({it['kind']}): {it['text']}")
        if w.ask("Keep it?"):
            memsuggest.decide(p, it["id"], True)
            kept += 1
        elif w.interactive:
            memsuggest.decide(p, it["id"], False)
        else:
            break                         # input ended: the rest stay waiting, not rejected
    rest = len(added) - min(len(added), COLD_ASK)
    w.say(f"  kept {kept}" + (f"; {rest} more wait in `ccx mem suggestions --all`" if rest else ""))


def run(yes: bool = False, hub: str | None = None) -> int:
    from .commands.install import init_hub
    from .sync import sync_all
    w = Wizard(yes, sys.stdin.isatty())
    w.say("ccx setup — every change is shown first and only made after you say yes.")

    w.step(1, "Check the tools")
    agents = [a for a in ("codex", "claude", "gemini") if find_bin(a)]
    logged_out: list[str] = []
    for a in ("codex", "claude", "gemini"):
        if a not in agents:
            w.say(f"  {a:7s} not installed" + ("" if a == "gemini" else "  ← needed for that direction"))
            continue
        ok = _login_ok(a)
        if ok is False:
            logged_out.append(a)
        w.say(f"  {a:7s} installed, " + {True: "logged in", False: f"NOT logged in → run: {LOGIN[a]}",
                                         None: "login unknown"}[ok])
    if not {"codex", "claude"} & set(agents):
        w.say("  Neither Codex nor Claude Code is installed. Install one or both, then run `ccx setup` again.")
        return 2

    w.step(2, "Your hub (personal folder for memory, skills, MCP and the ledger)")
    already = user_config_file().exists() and not hub
    where = Path(hub or (str(hub_dir()) if already else w.text("Where should it live?", str(hub_dir())))).expanduser()
    w.say(f"  hub: {where}" + ("  (already set; `ccx setup --hub <path>` to change)" if already else ""))
    if hub and _replaces(where):
        w.say(f"  this replaces the hub set before ({_replaces(where)}); nothing in it is moved or deleted")
    if not already:
        w.say("  Already have a shared AGENTS.md or your own sync script? Stop here and use "
              "`ccx init --hub … --snapshot … --external-sync …` instead.")

    if not w.yes and not w.interactive:
        return _plan_only(w, where, agents, logged_out)
    if w.yes and hub and _replaces(where):
        # --yes answers every question, so it would switch hubs unasked (as a walkthrough's temp hub once did)
        w.say(f'  Stopped: --yes does not switch hubs. To switch: ccx init --hub "{where}" --force, then ccx setup.')
        return 1

    w.step(3, "Create the hub skeleton (only adds files, never changes existing ones)")
    if not w.ask(f"Create/update ccx files in {where}?", default=True):
        w.say("  Stopped. Nothing was changed.")
        return 0
    with contextlib.redirect_stdout(io.StringIO()):
        info = init_hub(str(where), force=True)    # asked above (not --yes), the line before says what it replaces
    w.say(f"  done: hub {info['hub']}")

    w.step(4, "Wire both tools (session-start hook, skills, MCP)")
    p = paths()
    plan = sync_all(p, apply=False, parts=["skills", "memory", "hooks", "mcp"])
    if not plan.actions:
        w.say("  nothing to change — already wired")
    for x in plan.actions:
        w.say("  - " + x.replace("[dry-run] ", ""))
    for x in plan.warnings:
        w.say("  ! " + x)
    applied = False
    if plan.actions and w.ask("Make these changes? (each changed file is backed up first)"):
        with contextlib.redirect_stdout(io.StringIO()):
            sync_all(p, apply=True, parts=["skills", "memory", "hooks", "mcp"])
        applied = True
        w.say("  done")
    elif plan.actions:
        w.say("  skipped — run `ccx sync --apply` later (`ccx uninstall` removes it again)")

    w.step(5, "Health check")
    from .doctor import doctor
    doctor(p)
    if applied and "codex" in agents:
        w.say("  Codex: open Codex once and trust the hook in /hooks (\"ccx: shared memory delta\").")

    w.step(6, "Notes from your recent sessions (optional)")
    cold_start(w, p)

    w.step(7, "Try it")
    if logged_out:
        # it would only fail (and costs a little where it gets through): log in first, then `ccx selftest`
        w.say(f"  skipped: {', '.join(logged_out)} not logged in. Log in first, then run `ccx selftest`")
    elif w.ask("Run one tiny real task per installed agent (cheapest model, a few cents at most)?"):
        from types import SimpleNamespace
        from .commands.install import cmd_selftest
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_selftest(SimpleNamespace(agents=None, provider=None))
        try:
            for r in json.loads(buf.getvalue())["selftest"]:
                w.say(f"  {r['agent']:7s} {'ok' if r['ok'] else 'FAILED'}  {r.get('model') or r.get('error', '')}")
        except (json.JSONDecodeError, KeyError):
            w.say(buf.getvalue())
    _finish(w, agents, logged_out)
    return 0


def _login_todo(logged_out: list[str]) -> list[str]:
    return [f"log in to {a}: {LOGIN[a]}" for a in logged_out]


def _finish(w: Wizard, agents: list[str], logged_out: list[str]) -> None:
    """Blocking items first (a CLI not logged in: the first delegation would fail), then the first delegation."""
    todo = _login_todo(logged_out)
    if todo:
        w.say("\nBefore your first delegation:")
        for i, t in enumerate(todo, 1):
            w.say(f"  {i}. {t}")
    w.say("\nYour first delegation (from a project folder containing README.md, inside Claude Code or Codex, or a terminal):")
    w.say("  " + first_command("codex" if "codex" in agents else "claude"))
    w.say("Inspect it with ccx show <run_id>, then record your verdict: ccx verify <run_id> --ok 1 (correct) or --ok 0 (wrong)")


def _replaces(where: Path) -> str | None:
    """What `where` replaces in ~/.ccx/config.toml: the other hub it names, "a config.toml that does not parse", or
    None (nothing, or the same hub). `ccx init --hub` stops on either without --force."""
    from .commands.install import _saved_hub, _same
    try:
        old = _saved_hub()
    except ValueError:
        return "a config.toml that does not parse"
    return str(old) if old and not _same(old, where.expanduser().resolve()) else None


def _force(where: Path) -> str:
    """` --force` when `where` replaces something (_replaces): the printed `ccx init` step then works as printed."""
    return " --force" if _replaces(where) else ""


def _plan_only(w: Wizard, where: Path, agents: list[str], logged_out: list[str]) -> int:
    """Not on a terminal and no --yes (e.g. a Claude Code or Codex Bash tool): show every remaining step as the exact
    command, change nothing. Before, it stopped at step 3 and showed nothing of steps 4-7."""
    w.say("\n  Not on a terminal, so setup changes nothing here. The remaining steps as commands (run them yourself,")
    w.say("  or let your agent run them; `ccx setup` in a terminal of your own asks before each change instead):")
    steps = [*_login_todo(logged_out),
             f'create the hub skeleton (only adds files): ccx init --hub "{where}"' + _force(where),
             "preview the wiring (session-start hook, skills, MCP): ccx sync",
             "make those changes (each changed file is backed up; `ccx uninstall` removes them): ccx sync --apply",
             "health check: ccx doctor"]
    for i, t in enumerate(steps, 1):
        w.say(f"    {i}. {t}")
    w.say("  Then your first delegation:")
    w.say("    " + first_command("codex" if "codex" in agents else "claude"))
    w.say(f'  Or accept every step at once: ccx setup --yes --hub "{where}"')
    w.say("  Nothing was changed.")
    return 0
