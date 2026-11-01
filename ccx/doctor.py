"""`ccx doctor`: say what works, what doesn't, and what is Unknown. No guessing."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from . import memory
from .config import Paths, claude_home, codex_home, load_config
from .runners import bin_argv, find_bin
from .sync import BEGIN, PLUGIN, codex_hook_needs_call_operator, plugin_tools


def _run(argv, timeout=20):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


HUB_FORMAT = 2   # bump when the hub's on-disk layout changes; `ccx init` migrates

# how to log in, per CLI (setup.py says the same); a doctor FAIL row and the summary name it
LOGIN_CMD = {"codex": "`codex login`", "claude": "`claude`, then /login", "gemini": "`gemini`, then sign in"}


def login_line(out: str) -> str:
    """The line of `<cli> login status` that says the state ("Not logged in" / "Logged in using ..."), not an
    unrelated first line: codex-cli 0.164 can print a PATH-alias warning first (2026-10-29 walkthrough, CODEX_HOME
    under a temp folder). Falls back to the first line."""
    lines = [x.strip() for x in (out or "").splitlines() if x.strip()]
    for x in lines:
        if "logged in" in x.lower() or "logged out" in x.lower():
            return x
    return lines[0] if lines else ""


def summary_lines(rows: list[tuple[str, str, str]]) -> list[str]:
    """What to do, blocking items first: a CLI that is not logged in (its login command), a hub that is not set up
    (`ccx init`), then the wiring `ccx sync` adds. A new user read only the last line, which named sync alone."""
    todo = []
    for name, state, _ in rows:
        if state == "FAIL" and name.endswith(" login"):
            agent = name.split()[0]
            todo.append(f"log in to {agent}: run {LOGIN_CMD.get(agent, agent)}")
    if any(state == "FAIL" and (name in ("hub", "memory snapshot")) for name, state, _ in rows):
        todo.append("set up the hub: run `ccx init` (or `ccx setup`)")
    if any(state == "missing" for _, state, _ in rows):
        todo.append("missing items: run `ccx sync` (dry run) then `ccx sync --apply`")
    if not todo:
        return []
    if len(todo) == 1 and todo[0].startswith("missing items"):
        return ["", todo[0] + "."]                 # the one line it always was
    return ["", "To do, in this order:"] + [f"  {i}. {t}" for i, t in enumerate(todo, 1)]

# what to add to ~/.codex/config.toml so a Codex lead can run `ccx run` (codex-cli 0.164 `exec --help`, 2026-10-24)
CODEX_LEAD_FIX = ('[sandbox_workspace_write]\nwritable_roots = ["{hub}"]\nnetwork_access = true\n'
                  '(or start Codex with --add-dir "{hub}")')
# on Windows that is not enough: workspace-write runs commands as a separate sandbox account (CodexSandboxOnline), and a
# Claude sub-agent started there refused every edit ("sensitive file") and saved no session, even with the hub and
# ~/.claude as writable roots and the network on (real runs, codex-cli 0.164 + Claude Code, 2026-10-24)
CODEX_LEAD_FIX_WIN = ('on Windows, give lead sessions full access, e.g. a profile:\n[profiles.lead]\n'
                      'sandbox_mode = "danger-full-access"\nthen start the lead with `codex -p lead`')


# Safer than full access, not yet checked on a real run: keep workspace-write and let only ccx's hand-out commands run
# outside the sandbox with a Codex rule (learn.chatgpt.com/docs/agent-configuration/rules, read 2026-10-25: "allow" =
# "Run the command outside the sandbox without prompting"; rules are experimental). The pattern is an exact argv prefix,
# so it names this copy of ccx exactly as the lead is told to call it (`codex execpolicy check` agrees, codex-cli 0.164).
LEAD_VERBS = ("run", "ask", "resume", "discuss")
FULL_ACCESS_NOTE = ("safety: in full access every command the lead runs has your rights, unsandboxed (files, network, "
                    "credentials). Safer, not yet checked on a real run: keep workspace-write and let only ccx out of "
                    "the sandbox with the rule `ccx doctor --codex-rule` prints")


def codex_lead_rule(argv: list[str] | None = None) -> str:
    """A ~/.codex/rules/ccx.rules entry that lets this copy of ccx hand work out from a sandboxed Codex lead."""
    from .config import ccx_argv
    pat = ", ".join(json.dumps(x) for x in (argv or ccx_argv())) + ", [" + ", ".join(json.dumps(v) for v in LEAD_VERBS) + "]"
    return ("prefix_rule(\n"
            f"    pattern = [{pat}],\n"
            '    decision = "allow",\n'
            '    justification = "ccx starts the sub-agent CLI as you, so it can edit files and keep its session",\n'
            ")\n")


def codex_rule_allows(rules_dir, argv: list[str] | None = None, check=None) -> bool:
    """Does a rule in ~/.codex/rules let `ccx run` out of the sandbox? Asked of Codex itself (`codex execpolicy
    check`), so the answer follows its own matching. `check(rules_file, argv) -> decision` for tests."""
    from pathlib import Path
    from .config import ccx_argv
    files = sorted(Path(rules_dir).glob("*.rules")) if Path(rules_dir).is_dir() else []
    if not files:
        return False
    cmd = [*(argv or ccx_argv()), "run", "--to", "claude", "x"]
    if check is None:
        def check(f, a):
            rc, out = _run([*bin_argv("codex"), "execpolicy", "check", "--rules", str(f), "--", *a])
            try:
                return json.loads(out).get("decision") if rc == 0 else None
            except ValueError:
                return None
    return any(check(f, cmd) == "allow" for f in files)


def codex_lead_sandbox(config_text: str, hub, windows: bool | None = None, rule: bool = False) -> tuple[str, str]:
    """Can a Codex lead run `ccx run`? ccx writes its run records into the hub, and the sub-agent CLI it starts needs
    the network. In Codex's workspace-write sandbox both are blocked unless configured: a real headless Codex lead
    got `[WinError 5] Access is denied` on the hub's runs folder (seven-cores check, 2026-10-24)."""
    import os
    import tomllib
    from pathlib import Path
    windows = os.name == "nt" if windows is None else windows
    try:
        cfg = tomllib.loads(config_text) if config_text else {}
    except tomllib.TOMLDecodeError as e:
        return "Unknown", f"config.toml does not parse: {e}"
    # not set: Codex picks read-only or workspace-write from the project's trust, so check as workspace-write
    mode = cfg.get("sandbox_mode") or "not set"
    if mode == "danger-full-access":
        return "ok", f"sandbox_mode = danger-full-access; {FULL_ACCESS_NOTE}"
    if rule and mode != "read-only":
        return "Unknown", (f"sandbox_mode = {mode} and a rule lets `ccx run` out of the sandbox: by Codex's docs that "
                           "should work, but it has not been checked on a real run (rules are experimental)")
    if windows:
        return "WARN", (f"sandbox_mode = {mode}: a Codex lead cannot hand work to Claude through `ccx run` in this "
                        f"sandbox on Windows (checked on real runs); {CODEX_LEAD_FIX_WIN}\nor, safer but not yet "
                        "checked on a real run: keep the sandbox and add the rule `ccx doctor --codex-rule` prints")
    fix = CODEX_LEAD_FIX.format(hub=Path(hub).as_posix())
    if mode == "read-only":
        return "WARN", f"sandbox_mode = read-only: a Codex lead cannot run `ccx run`; use workspace-write and add\n{fix}"
    ws = cfg.get("sandbox_workspace_write") or {}

    def norm(x) -> str:
        return str(Path(x).expanduser().resolve()).rstrip("\\/").lower()
    roots = {norm(r) for r in ws.get("writable_roots") or []}
    hub_ok = any(norm(hub) == r or norm(hub).startswith(r + ("\\" if "\\" in r else "/")) for r in roots)
    missing = [w for w, ok in (("the hub is not a writable root", hub_ok),
                               ("network_access is off", ws.get("network_access") is True)) if not ok]
    if not missing:
        return "ok", f"sandbox_mode = {mode}, hub writable, network on (not checked on a real run outside Windows)"
    return "WARN", (f"sandbox_mode = {mode} ({'; '.join(missing)}): a Codex lead's `ccx run` will fail. "
                    f"Add to config.toml (profiles may override it; not checked on a real run outside Windows):\n{fix}")


def version_drift(version_out: str, tested: str, official: bool) -> tuple[str, str] | None:
    """(state, detail) when the installed CLI's major.minor differs from the version the adapter's flags were checked
    against (I8), None when they match. Patch releases are taken as compatible."""
    import re
    got = re.search(r"(\d+)\.(\d+)", version_out or "")
    want = re.search(r"(\d+)\.(\d+)", tested or "")
    if not got or not want:
        return "Unknown", f"could not read a version from {(version_out or '').strip()[:60]!r}"
    if got.groups() == want.groups():
        return None
    have = got.group(0)
    if official:
        return "WARN", (f"installed {have}, flags checked against {tested}: run the release check (H15: a real "
                        "read, write and resume run on this version) before relying on it")
    return "WARN", (f"installed {have}, adapter written for {tested}: not verified on this version (community "
                    "adapter; flags or output may have changed)")


# OpenAI's Claude Code plugin (github.com/openai/codex-plugin-cc v1.0.6, read 2026-10-25): marketplace "openai-codex",
# plugin "codex"; its hooks.json adds SessionStart, SessionEnd and an optional Stop review gate of its own.
CODEX_PLUGIN = "codex@openai-codex"


def codex_plugin(home) -> tuple[str, str] | None:
    """(state, detail) when the official codex-plugin-cc is installed or enabled in Claude Code (J8), else None.
    Its hooks run commands of its own, next to ccx's; what could go wrong is ccx's own hook being there twice."""
    from pathlib import Path
    home = Path(home)

    def js(f: Path) -> dict:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}
    installed = any(str(k).startswith(CODEX_PLUGIN) for k in (js(home / "plugins" / "installed_plugins.json")
                                                               .get("plugins") or {}))
    settings = js(home / "settings.json")
    enabled = (settings.get("enabledPlugins") or {}).get(CODEX_PLUGIN)
    if not installed and not enabled:
        return None
    ours = sum("mem delta" in json.dumps(g) for g in (settings.get("hooks") or {}).get("SessionStart") or [])
    state = "WARN" if ours > 1 else "info"
    return state, (f"OpenAI's codex-plugin-cc is {'enabled' if enabled else 'installed (not enabled)'}: its "
                   "SessionStart/SessionEnd/Stop hooks run beside ccx's, which is there "
                   f"{'once' if ours == 1 else f'{ours} times (run `ccx sync --apply`)' if ours else 'not at all'}. "
                   "Using both together is not tested yet; its Stop review gate, if you turn it on, reviews with "
                   "Codex at every stop on top of ccx's review")


def plugin_ccx(tools: list[str], which=None) -> tuple[str, str]:
    """The relayline plugin carries its own copy of ccx: its hooks and Claude Code's Bash tool run that one. A
    terminal, Codex as the lead and `ccx setup` need ccx installed too; say so when it isn't (the copy the plugin
    puts on the Bash tool's PATH doesn't count)."""
    import shutil
    found = (which or shutil.which)("ccx")
    inside = found and any(os.path.normcase(str(h / "plugins")) in os.path.normcase(found)
                           for h in (claude_home(), codex_home()))
    where = "enabled in " + " and ".join(tools)
    if found and not inside:
        return "ok", f"{where}; ccx itself: {found}"
    return "WARN", (f"{where}, but ccx is not installed on its own: the plugin's hooks and skills run its bundled "
                    "copy inside the tool only. For your terminal and Codex: `pipx install "
                    "git+https://github.com/SUPERD6/relayline`, then `ccx init`")


def routing_prior(p: Paths) -> tuple[str, str]:
    """Where routing's starting point comes from: the hand-set priors and, for rungs this hub has not learned yet,
    the built-in A/B head start (task-routing [observed])."""
    try:
        from . import learn
        tr = learn.module(p, "routing")
        pri, st = tr.load_priors(), tr.load_state()
    except Exception as e:  # noqa: BLE001
        return "WARN", f"task-routing not readable: {e}"[:120]
    head = f"priors.toml {pri.get('as_of', '?')}"
    if not hasattr(tr, "observed_offsets"):
        return "ok", head + (" (the hub's task-routing predates the built-in A/B head start: update the checkout "
                             "it links to, or `ccx skills install`)")
    obs, learned = tr.observed_offsets(pri), st.get("offsets") or {}
    if not obs:
        return "ok", head
    parts = [f"{k} {v:+.2f}" + (" (learned here since)" if k in learned else "") for k, v in sorted(obs.items())]
    return "ok", (f"{head} + {pri['observed'].get('source', 'built-in outcomes')} at weight "
                  f"{pri['observed'].get('weight', 0.5)}: " + ", ".join(parts))


def tier_policy_check(p: Paths, cfg: dict | None = None) -> tuple[str, str]:
    """Can every tier be planned with the [policy.*] config (a bad entry makes `ccx propose` fall back to
    offer-first), and which tier, if any, the person picked (policy.picked pre-authorises its delegation)."""
    try:
        from . import learn
        cfg = cfg if cfg is not None else load_config(p)
        pol = cfg.get("policy") or {}
        raw = str(pol.get("picked") or "").strip().lower()      # read as routing reads it (picked_tier)
        tiers = ("save", "balanced", "fast", "cheapest")
        if raw and raw not in tiers:
            return "WARN", f"policy.picked = {raw!r} is not a tier ({', '.join(tiers)}): no tier is picked"
        for tier in tiers:
            for brief, minutes, files, ctx in (("x", 5, 1, 0), ("x", 20, 2, 10 ** 9), ("x", 60, 4, 0),
                                               ("x", None, 0, 0), ("resume after a crash", 60, 4, 0)):
                if learn.tier_plan(p, tier, brief, minutes, files, ctx, pol) is None:
                    return "ok", "the hub's task-routing predates tiers (no tier plan): offer-first everywhere"
    except Exception as e:  # noqa: BLE001 — shown, not raised: routing itself goes on without a tier plan
        return "WARN", (f"[policy.*] cannot be planned ({type(e).__name__}: {e}); "
                        "ccx propose falls back to offer-first")[:200]
    return "ok", (f"picked tier: {raw} (pre-authorises what it delegates; L0/L1 still ask)" if raw else
                  "no tier picked: offer first (policy.picked)")


def config_row(p: Paths) -> tuple[str, str]:
    """~/.ccx/config.toml (where the hub is) and <hub>/ccx/layout.toml: FAIL when one does not parse (ccx then falls
    back to the default hub, or stops), WARN when a value holds a control character ("C:\\new" in double quotes)."""
    import tomllib
    from .config import has_control_chars, toml_problem, user_config_file
    files = [f for f in (user_config_file(), p.hub / "ccx" / "layout.toml") if f.exists()]
    warn = []
    for f in files:
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            return "FAIL", toml_problem(f, e)
        except OSError as e:
            return "FAIL", f"{f}: {e}"
        bad = sorted(k for k, v in data.items() if has_control_chars(v))
        if bad:
            warn.append(f"{f}: {', '.join(bad)} holds a control character (a backslash escape in double quotes?); "
                        "write Windows paths with / or in single quotes")
    if warn:
        return "WARN", "; ".join(warn)
    env = " (CCX_HUB is set)" if os.environ.get("CCX_HUB") else ""
    return "ok", f"hub {p.hub}{env}; " + (", ".join(str(f) for f in files) or "no config file (defaults)")


# Rows about ccx's own workings, not something a person acts on while they are fine: shown with --verbose, or when
# their state is not ok (then they say what to do). Walkthrough 2026-10-29: a new user asked what "routing prior"
# and "tier policy" meant and whether to do something about them.
INTERNAL_ROWS = ("python", "tiers.toml", "ccx config", "hub format", "hub layout", "routing prior", "tier policy",
                 "hook timeouts")


def shown_rows(rows: list[tuple[str, str, str]], verbose: bool) -> list[tuple[str, str, str]]:
    return [r for r in rows if verbose or r[0] not in INTERNAL_ROWS or not str(r[1]).startswith("ok")]


def doctor(p: Paths, codex_lead: bool = False, verbose: bool = False) -> bool:
    """The table and what to do. codex_lead: the 'Codex as lead' row in full (else a WARN there is one info line).
    verbose: also the INTERNAL_ROWS that are ok."""
    rows: list[tuple[str, str, str]] = []

    def add(name, state, detail=""):
        rows.append((name, state, detail))

    add("python", "ok" if sys.version_info >= (3, 11) else "FAIL", sys.version.split()[0])
    try:
        load_config(p)
        add("tiers.toml", "ok")
    except Exception as e:  # noqa: BLE001
        add("tiers.toml", "FAIL", str(e))
    add("ccx config", *config_row(p))
    from . import quota
    add("subscription quota", "info", quota.summary(p))
    try:                                   # a broken layout.toml: keep the table, skip the rows that read it
        lay = p.layout
    except ValueError as e:
        lay = None
        add("hub layout", "FAIL", str(e))

    from .agents import all_adapters
    for ad in all_adapters():
        agent, official = ad.name, ad.support == "official"
        if not find_bin(agent):
            if official:                       # the two official agents are expected; the rest are optional
                add(f"{agent} CLI", "FAIL", "not on PATH")
            continue
        rc, out = _run([*bin_argv(agent), "--version"])
        ver = out.splitlines()[0] if out else ""
        can = ", ".join(k for k, v in ad.capabilities().items() if v)
        add(f"{agent} CLI" + ("" if official else " (optional)"), "ok" if rc == 0 else ("FAIL" if official else "WARN"),
            f"{ver} (flags checked against {ad.tested_version}; {ad.support}; {ad.vendor}; {can})")
        if rc == 0 and (drift := version_drift(ver, ad.tested_version, official)):
            add(f"{agent} version", *drift)
        if ad.locate and find_bin(agent) == ad.locate():        # not on PATH: say where ccx found it
            add(f"{agent} location", "ok", f"{find_bin(agent)} (found from the installed app, not on PATH)")
        if not ad.login_argv:
            add(f"{agent} login", "Unknown", "ccx can't check this tool's login; its first run will tell")
            continue
        rc, out = _run([*bin_argv(agent), *ad.login_argv])
        try:                                   # claude auth status prints JSON
            import json as _j
            js = _j.loads(out)
            if isinstance(js, dict) and "loggedIn" in js:
                ok_ = bool(js["loggedIn"])
                add(f"{agent} login", "ok" if ok_ else "FAIL",
                    (js.get("authMethod") or "") if ok_ else
                    f"not logged in -> run {LOGIN_CMD.get(agent, agent)}")
                continue
        except ValueError:
            pass
        line = login_line(out)
        low = line.lower()
        if rc == 0 and "not" not in low:
            state = "ok"
        elif rc != 0 or "not logged" in low or "logged out" in low:
            state = "FAIL"
        else:
            state = "Unknown"
        add(f"{agent} login", state, line[:90] + (f" -> run {LOGIN_CMD.get(agent, agent)}"
                                                    if state == "FAIL" else ""))

    add("hub", "ok" if p.hub.exists() else "FAIL", str(p.hub))
    vf = p.state / "version.json"
    if vf.exists():
        import json as _json
        hv = _json.loads(vf.read_text(encoding="utf-8")).get("hub_format")
        add("hub format", "ok" if hv == HUB_FORMAT else "WARN",
            f"{hv}" + ("" if hv == HUB_FORMAT else f" (this ccx writes {HUB_FORMAT}: run `ccx init` to migrate)"))
    if lay is None:
        pass                               # the snapshot's path is in the layout: its FAIL row says why
    elif p.memory_index.exists():
        size = p.memory_index.stat().st_size
        if p.snapshot_external:
            # the user's own shared rules file: its size is theirs to decide; ccx only folds its journal into it
            add("memory snapshot", "ok", f"{size} bytes (external: your own file; ccx only appends its section)")
        else:
            add("memory snapshot", "ok" if size < 6000 else "WARN",
                f"{size} bytes" + (" (big: run `ccx mem compact` and trim)" if size >= 6000 else ""))
        n = len(memory.entries(p))
        add("memory journal", "ok" if n < 40 else "WARN",
            f"{n} entries" + (" (run `ccx mem compact`)" if n >= 40 else ""))
    else:
        add("memory snapshot", "FAIL", "run `ccx init`")

    if lay is not None:
        add("hub layout", "ok", f"snapshot={lay['snapshot']} ({lay['snapshot_mode']})"
            + (f", external sync: {lay['external_sync']}" if lay.get("external_sync") else ""))
    add("routing prior", *routing_prior(p))
    add("tier policy", *tier_policy_check(p))
    if lay is None:
        pass
    elif lay["snapshot_mode"] == "external":
        add("snapshot wiring", "ok (external)", "the tools load the snapshot themselves; ccx writes no blocks")
    else:
        cm = claude_home() / "CLAUDE.md"
        am = codex_home() / "AGENTS.md"
        tag = BEGIN.format(id="memory")
        add("Claude memory block", "ok" if cm.exists() and tag in cm.read_text(encoding="utf-8") else "missing", str(cm))
        add("Codex memory block", "ok" if am.exists() and tag in am.read_text(encoding="utf-8") else "missing", str(am))

    sj = claude_home() / "settings.json"
    try:
        has = "mem delta" in json.dumps(json.loads(sj.read_text(encoding="utf-8"))["hooks"]["SessionStart"])
    except Exception:  # noqa: BLE001
        has = False
    plugged = plugin_tools()
    if "claude" in plugged:
        add("Claude SessionStart hook", "WARN" if has else "ok",
            "in settings.json AND in the relayline plugin, so it runs twice: `ccx sync --apply` takes ccx's copy out"
            if has else "from the relayline plugin")
    else:
        add("Claude SessionStart hook", "ok" if has else "missing", str(sj))
    if plugged:
        add("relayline plugin", *plugin_ccx(sorted(plugged)))
    if (cp := codex_plugin(claude_home())):
        add("codex-plugin-cc", *cp)
    ct = codex_home() / "config.toml"
    has = ct.exists() and "ccx:begin hooks" in ct.read_text(encoding="utf-8")
    if has and os.name == "nt" and codex_hook_needs_call_operator(ct.read_text(encoding="utf-8")):
        add("Codex SessionStart hook", "WARN", "written before the Windows fix: Codex runs hooks through PowerShell and "
            "this command starts with a quoted path, so it runs nothing. Run `ccx sync --apply`, then trust the hooks "
            f"again in Codex with /hooks ({ct})")
    else:
        add("Codex SessionStart hook", "ok (trust once via /hooks)" if has else "missing", str(ct))
    from . import hooktimeout
    add("hook timeouts", *hooktimeout.doctor_row(p))
    if find_bin("codex"):
        lead = codex_lead_row(p, ct)
        if lead[0] == "WARN" and not codex_lead:
            # only matters when Codex leads: one line here, the details (and the full-access advice) on request
            lead = ("info", "only matters if Codex leads (hands work to Claude): `ccx doctor --codex-lead` shows "
                    "whether its sandbox lets it and how to set it up")
        add("Codex as lead (sandbox)", *lead)

    skill = "agent-delegate"
    for tool, d in (("claude", claude_home() / "skills"), ("codex", codex_home() / "skills")):
        if tool in plugged:
            add(f"{tool} has {skill}", "ok", f"from the relayline plugin ({PLUGIN}:{skill})")
        else:
            add(f"{tool} has {skill}", "ok" if (d / skill / "SKILL.md").exists() else "missing", str(d))

    show = shown_rows(rows, verbose)
    w = max(len(r[0]) for r in show)
    for name, state, detail in show:
        print(f"{name.ljust(w)}  {state:<8} {detail}")
    if len(show) < len(rows):
        print(f"({len(rows) - len(show)} internal checks ok; `ccx doctor --verbose` shows them)")
    bad = [r for r in rows if r[1] in ("FAIL",)]
    for x in summary_lines(rows):
        print(x)
    return not bad


def codex_lead_row(p: Paths, ct=None) -> tuple[str, str]:
    """The full 'Codex as lead (sandbox)' verdict (`ccx doctor --codex-lead`)."""
    ct = ct or codex_home() / "config.toml"
    return codex_lead_sandbox(ct.read_text(encoding="utf-8") if ct.exists() else "", p.hub,
                              rule=codex_rule_allows(codex_home() / "rules"))
