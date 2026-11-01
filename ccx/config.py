"""Paths and configuration for ccx.

Everything user-specific lives in the *hub*, a folder both Claude Code and Codex
read. The repo only holds generic code, defaults and templates — no personal
paths. Where the hub is comes from (first match wins):
  1. $CCX_HUB
  2. `hub = "..."` in ~/.ccx/config.toml   (written by `ccx init --hub PATH`)
  3. ~/.ccx-hub
"""
from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    raise SystemExit("ccx needs Python 3.11+ (for tomllib).")

REPO_ROOT = Path(__file__).resolve().parent.parent
# A clone (or editable install) has ccx.py next to the package; an installed wheel carries the same folders
# as package data (pyproject: config/ -> ccx/_config, skills/ -> ccx/_skills, hub-seed/ -> ccx/_hubseed).
FROM_SOURCE = (REPO_ROOT / "ccx.py").exists()
_PACKAGED = {"config": "_config", "skills": "_skills", "hub-seed": "_hubseed"}


def data_dir(name: str) -> Path:
    """config / skills / hub-seed, wherever this copy of ccx keeps them."""
    if FROM_SOURCE:
        return REPO_ROOT / name
    from importlib.resources import files
    return Path(str(files("ccx") / _PACKAGED[name]))


def ccx_argv() -> list[str]:
    """How to start this copy of ccx from another process (hooks, background runs)."""
    return [sys.executable, str(REPO_ROOT / "ccx.py")] if FROM_SOURCE else [sys.executable, "-m", "ccx"]


DEFAULT_TIERS = data_dir("config") / "tiers.toml"
RESULT_SCHEMA = data_dir("config") / "result.schema.json"
TIER_ORDER = ["T0", "T1", "T2", "T3", "T4"]
AGENTS = ("codex", "claude")                 # wired for shared memory / skills / MCP / hooks
DELEGATE_AGENTS = ("codex", "claude", "gemini", "dsh")   # can run headless sub-tasks (adapters in ccx/agents)
LEAD_ALIASES = {"deepseek": "dsh"}           # a lead named by its vendor: DeepSeek's own agent is dsh


def lead_name(value: str) -> str:
    """A lead tool's name as ccx keeps it: `deepseek` -> `dsh` (ccx handoff --to/--by). Not for `ccx run --to`,
    where `deepseek` is the deepseek provider (Claude Code on DeepSeek's API)."""
    v = str(value).strip()
    return LEAD_ALIASES.get(v.lower(), v)


def _default_providers() -> tuple[str, ...]:
    try:
        with open(DEFAULT_TIERS, "rb") as f:
            return tuple(tomllib.load(f).get("providers") or ())
    except (OSError, tomllib.TOMLDecodeError):
        return ("deepseek",)


PROVIDER_AGENTS = _default_providers()   # [providers.<name>] in config: an agent CLI pointed at another model API

def user_config_file() -> Path:
    env = os.environ.get("CCX_CONFIG")
    return Path(env).expanduser() if env else Path.home() / ".ccx" / "config.toml"


TOML_PATH_HINT = ("Windows paths: write them with / or in single quotes ('C:\\x\\y'); inside double quotes a "
                  "backslash starts an escape (\\n becomes a line break)")
_WARNED: set[str] = set()


def toml_problem(f: Path, e: tomllib.TOMLDecodeError) -> str:
    """One line for a TOML file that does not parse: the file, where (line and column are in the message), a hint."""
    return f"{f} is not valid TOML: {e}. {TOML_PATH_HINT}"


def _warn_once(text: str) -> None:
    if text not in _WARNED:
        _WARNED.add(text)
        print(f"ccx: {text}", file=sys.stderr)


def has_control_chars(value) -> bool:
    """A string (or one inside a list/dict) with a control character: usually "C:\\new" in double quotes."""
    if isinstance(value, str):
        return any(ord(c) < 32 for c in value)
    if isinstance(value, dict):
        return any(has_control_chars(v) for v in value.values())
    if isinstance(value, list):
        return any(has_control_chars(v) for v in value)
    return False


def hub_dir() -> Path:
    env = os.environ.get("CCX_HUB")
    if env:
        return Path(env).expanduser()
    f = user_config_file()
    if f.exists():
        try:
            hub = tomllib.loads(f.read_text(encoding="utf-8")).get("hub")
            if hub:
                return Path(hub).expanduser()
        except tomllib.TOMLDecodeError as e:
            # not silent: ccx would otherwise use the default hub and seem to have forgotten everything
            _warn_once(toml_problem(f, e) + f"; using {Path.home() / '.ccx-hub'} for now (`ccx doctor`, row "
                       "'ccx config')")
    return Path.home() / ".ccx-hub"


def toml_string(s: str) -> str:
    """A TOML literal string ('...': no escapes, so a Windows path stays as it is); a basic string only when the text
    holds a single quote or a control character, which a literal string cannot."""
    return f"'{s}'" if "'" not in s and not has_control_chars(s) else json.dumps(s)


def save_hub(path: Path) -> Path:
    """Remember the hub location for this machine (never inside the repo)."""
    f = user_config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f'# written by `ccx init --hub`\nhub = {toml_string(str(path))}\n', encoding="utf-8")
    return f


def codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    return Path(env).expanduser() if env else Path.home() / ".codex"


def claude_home() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


DEFAULT_LAYOUT = {
    # where the shared snapshot ("1") lives, relative to the hub
    "snapshot": "memory/MEMORY.md",
    # managed  = ccx wires the snapshot into each tool (CLAUDE.md import / AGENTS.md block)
    # external = the tools already load it some other way; ccx never writes into their instruction files
    "snapshot_mode": "managed",
    "skills": "skills",
    "mcp": "mcp/servers.json",
    "mcp_format": "auto",          # auto | ccx ({"servers": ...}) | mcpServers ({"mcpServers": ...})
    "external_sync": "",           # a command that already links skills/MCP into both tools; ccx then defers to it
    # every linked skill's description loads at every session start: link only what you use
    "skills_include": [],          # non-empty = link only these skill names
    "skills_exclude": [],          # never link these
}


def load_layout(hub: Path) -> dict:
    """Hub layout = defaults + <hub>/ccx/layout.toml. Lets ccx plug into an existing personal setup
    instead of creating a second one (that file is personal; the code stays generic)."""
    lay = dict(DEFAULT_LAYOUT)
    f = hub / "ccx" / "layout.toml"
    if f.exists():
        try:
            lay.update(tomllib.loads(f.read_text(encoding="utf-8")).get("layout", {}))
        except tomllib.TOMLDecodeError as e:
            _warn_once(toml_problem(f, e))      # stderr too: a caller that swallows the error still leaves a trace
            raise ValueError(toml_problem(f, e)) from e
    return lay


@dataclass(frozen=True)
class Paths:
    hub: Path

    @property
    def layout(self) -> dict:
        return load_layout(self.hub)

    @property
    def state(self) -> Path:          # ccx private state inside the hub
        return self.hub / "ccx"

    @property
    def runs(self) -> Path:
        return self.state / "runs"

    @property
    def ledger(self) -> Path:
        return self.state / "ledger.jsonl"

    @property
    def user_tiers(self) -> Path:
        return self.state / "tiers.toml"

    @property
    def settings(self) -> Path:       # written by `ccx config set` (no hand comments to lose)
        return self.state / "settings.toml"

    @property
    def memory(self) -> Path:
        return self.hub / "memory"

    @property
    def memory_index(self) -> Path:          # the shared snapshot ("1")
        return self.hub / self.layout["snapshot"]

    @property
    def snapshot_external(self) -> bool:
        return self.layout["snapshot_mode"] == "external"

    @property
    def skills(self) -> Path:
        return self.hub / self.layout["skills"]

    @property
    def mcp_registry(self) -> Path:
        return self.hub / self.layout["mcp"]


def paths() -> Paths:
    return Paths(hub_dir())


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(p: Paths | None = None) -> dict:
    p = p or paths()
    with open(DEFAULT_TIERS, "rb") as f:
        cfg = tomllib.load(f)
    for f in (p.user_tiers, p.settings):          # hand-edited overrides, then `ccx config set`
        if f.exists():
            with open(f, "rb") as fh:
                cfg = _deep_merge(cfg, tomllib.load(fh))
    return cfg


def worktree_location(cfg: dict) -> str:
    """Where new worktrees go; reject typos before creating a directory or a branch."""
    location = (cfg.get("worktree") or {}).get("location", "sibling")
    if location not in ("sibling", "inside"):
        raise ValueError("worktree.location must be sibling or inside")
    return location


# [subagent] (config/tiers.toml): experimental switches for what a sub-agent loads, each at today's behaviour until a
# before / after measurement passes (scripts/eval/r5.py, arms ccx2daily*). Not [subagents]: that one caps the
# sub-agent's own sub-agents.
SUBAGENT_SWITCHES = {"codex_memories": True, "clean": False, "codex_lean_tools": False}


def subagent_switches(cfg: dict) -> dict:
    """The [subagent] switches a run uses (a missing or non-boolean key: its default)."""
    c = cfg.get("subagent") or {}
    return {k: (c[k] if isinstance(c.get(k), bool) else d) for k, d in SUBAGENT_SWITCHES.items()}


def path_list(raw: str) -> list[str]:
    """`ccx config set` value for a list of folders: separated by ';' (a ':' is part of a Windows path)."""
    return [x.strip() for x in raw.replace("\n", ";").split(";") if x.strip()]


def _bool(raw: str) -> bool:
    """`ccx config set` value for an on/off setting."""
    v = raw.strip().lower()
    if v in ("true", "on", "yes", "1"):
        return True
    if v in ("false", "off", "no", "0"):
        return False
    raise ValueError(f"{raw!r} is not true or false")


_bool.__name__ = "true/false"


def _quota_minutes(raw: str) -> float | bool:
    return False if raw.strip().lower() == "false" else float(raw)


ROLE_DEFAULTS = {"mode": ("read", "write"), "review": ("auto", "on", "off"),
                 "worktree": bool, "check": str}  # roles.defaults.<name>; no implicit defaults


SETTINGS = {   # key -> (type, help). Only these can be set with `ccx config set`.
    # Arbitrary roles.<name> and roles.defaults.<name> mode/worktree/review/check use ccx.roles
    # (ccx roles set/unset), outside this scalar-key allowlist. Default role table: {}.
    "quota.auto_refresh_min": (_quota_minutes, "refresh existing readings older than N minutes (default 60); "
                                              "0/false disables"),
    "quota.avoid_above": (float, "used share above which quota routing prefers another subscription (default 0.8)"),
    "quota.routing": (str, "on | off: prefer subscriptions with available quota (default on)"),
    "billing.mode": (str, "api | subscription: API-equivalent USD first (default), or quota units first"),
    "defaults.tradeoff": (str, "tier: save | balanced | fast | cheapest, or a knob 0..1 (0 = cheapest, 1 = fastest)"),
    "policy.picked": (str, "save | balanced | fast | cheapest | none: the tier YOU pick for all work in this hub. It "
                           "pre-authorises what that tier delegates (`ccx propose` says authorized: true; project "
                           "autonomy L0/L1 still asks before edits). none (shipped) = offer first, as before"),
    "routing.mode": (str, "auto | off: auto (shipped) = ccx route / ccx run delegate as before; off = ccx "
                          "delegates no new work (route and propose say do it yourself; run, batch, q run / resume "
                          "and way refuse without --force); cross-vendor review and talk work as before: ccx ask, "
                          "ccx discuss, ccx run --mode read, mem, board"),
    "routing.small_self": (_bool, "true | false: `ccx route` / `ccx propose` advise doing a small task yourself "
                                  "instead of delegating it, sized by routing.small_self_by; `ccx run` still "
                                  "delegates (default false until a measured round backs it)"),
    "routing.small_self_files": (int, "routing.small_self: the most source files a task may touch to count as small"),
    "routing.small_self_by": (str, "files | cost: what routing.small_self sizes a task by: files (default) = at "
                                   "most routing.small_self_files source files by your --files; cost (experimental) "
                                   "= what doing it yourself costs (requests x your conversation's size, plus the "
                                   "files read) below routing.small_self_overhead_usd, scaled to your conversation"),
    "routing.small_self_overhead_usd": (float, "routing.small_self by cost: delegating's fixed cost on the lead's "
                                               "side (brief, wait, acceptance; default 0.035, the pg1 ledger median)"),
    "routing.small_self_quota": (float, "routing.small_self: from this share of your own quota used (0..1), small "
                                        "tasks are delegated as before"),
    "defaults.ab_self_rate": (float, "share of routed tasks the lead does itself to measure savings (0 = off)"),
    "defaults.max_escalations": (int, "stronger rungs to try after a verified failure"),
    "defaults.focused_retry": (_bool, "true | false: when ccx's --check fails after the sub-agent said done, the next "
                                      "attempt on the same agent continues its session with the failing command and "
                                      "~2000 characters of its output, told to fix only that (default false: the "
                                      "escalation note with 400 characters, as before)"),
    "escalate.on_self_checked": (str, "review | rung | off: when ccx's check passed only on tests the sub-agent "
                                      "wrote or changed in the run (kind ok_self_checked, always labelled): review = "
                                      "always reviewed against the task text (default); rung = one stronger rung "
                                      "redoes it first while one is left; off = the label only"),
    "defaults.max_parallel": (int, "parallel sub-agents in ccx batch"),
    "worktree.location": (str, "sibling | inside: new git worktrees beside the repository (default) or in "
                               "<repo>/.ccx/worktrees/<run_id> (ignore .ccx/ in .gitignore)"),
    "defaults.timeout_sec": (int, "per-attempt timeout"),
    "lanes.default": (int, "warm lanes for ccx batch / q run: small pieces for the same project and agent share at "
                           "most N sub-sessions, one after another (0 = off: every piece its own session)"),
    "lanes.max_tokens": (int, "a warm lane starts a new session after a piece that used this many tokens (the session has grown long)"),
    "lanes.max_blocks": (int, "a warm lane starts a new session after this many pieces"),
    "lead.claude": (str, "model the Claude lead runs on (for savings estimates; with lead.model_by_task also the "
                           "strong lead's name, which passes no --model), e.g. opus"),
    "lead.codex": (str, "model the Codex lead runs on, e.g. gpt-6.1-sol"),
    "prompt.slim": (_bool, "true | false: a run given --mode write and no --check is not told what to do when the "
                           "task only asks for an answer (that sentence is left out); false = the text as before "
                           "(default true)"),
    "run.max_usd": (float, "default --max-usd of ccx run / resume: stop the delegation (its attempts, review and fix "
                           "round together) once it has spent this many API-equivalent $ (0 = no limit, the default; "
                           "batch, q run, way and task resume do not read it)"),
    "wake.enabled": (_bool, "true | false: a --bg run that finishes sends the lead one line (Claude Code's inbox, "
                            "else the next turn's hook) instead of the lead polling (default true)"),
    "wake.trust_socket": (_bool, "true | false: a line delivered to Claude Code's inbox is not also left for the "
                                 "next turn's hook (default true; false: a held or expired line still arrives)"),
    "output.lead": (str, "line | full: what `ccx run` / `resume` / `show --wait` hand the lead when the check passed, "
                         "the review passed or none ran, and nothing needs a look: one JSON line (default) or the whole result as before "
                         "(`ccx show <id>` always gives the whole one)"),
    "lead.model_by_task": (_bool, "true | false: when ccx starts or recommends a NEW lead conversation (ccx fresh, "
                                  "ccx handoff, route/propose `new_lead`), pick its model from the task's difficulty: "
                                  "[lead_by_task] easy model up to easy_max_b, else the lead's own (default false; a "
                                  "running conversation never switches model)"),
    "sessions.archive": (str, "after_run | hours | off: archive a sub-agent session as soon as its result is "
                              "final (default), only after auto_archive_hours, or never by itself"),
    "sessions.auto_archive_hours": (float, "archive finished sub-agent sessions after N hours (0 = off)"),
    "report.publish_dir": (str, "local clone of your private usage repo; `ccx report --publish` commits there"),
    "board.github": (str, "owner/repo of a PRIVATE repository of yours: the board's fallback between computers "
                          "(empty = off, no network)"),
    "intake.github": (str, "owner/repo of a PRIVATE repository of yours whose labelled issues are tasks for "
                           "`ccx intake pull` (empty = off, no network)"),
    "intake.label": (str, "the label that makes an issue there a task (default ccx-task)"),
    "board.max_machine_turns": (int, "machine messages in a row in one board thread before a person must speak"),
    "projects.roots": (path_list, "folders `ccx projects scan` looks for your projects in, separated by ';' "
                                  "(the catalog stays in the hub, on this machine)"),
    "autonomy.level": (str, "L0 | L1 | L2: how much the project manager does without asking (default L1; "
                            "per project: `ccx autonomy set`)"),
    "memory.by_kind": (_bool, "true | false: kinds decide what a session start and a brief carry (preferences and "
                              "constraints at start, events by search only) and briefs pick notes by BM25 (default "
                              "false; to be decided by measurement, the confirmation run — the H11 trial was voided "
                              "on 2026-10-26)"),
    "memory.start_scene": (_bool, "true | false: a session start also carries this project's block from "
                                  "`ccx mem compact --by project` (default false)"),
    "hooks.timeout_s": (float, "seconds a session hook (ccx mem delta / turn) may run before it prints nothing and "
                               "exits 0; logged, shown by `ccx doctor` (0 = no limit)"),
    "ui.lang": (str, "zh | en: language of `ccx ui` and of the lines ccx writes into conversations (unset: the "
                     "page follows the browser, the lines stay English)"),
}


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def set_setting(p: Paths, key: str, raw: str) -> dict:
    if key not in SETTINGS:
        raise ValueError(f"unknown setting {key!r}; known: {', '.join(SETTINGS)}")
    typ = SETTINGS[key][0]
    if key == "billing.mode" and raw not in ("api", "subscription"):
        raise ValueError("billing.mode must be api or subscription")
    if key == "defaults.tradeoff" and raw not in ("save", "balanced", "fast", "cheapest"):
        k = float(raw)
        if not 0 <= k <= 1:
            raise ValueError("tradeoff knob must be between 0 and 1")
    if key == "policy.picked":
        if raw not in ("save", "balanced", "fast", "cheapest", "none", "off", ""):
            raise ValueError("policy.picked must be save, balanced, fast, cheapest or none")
        raw = "" if raw in ("none", "off") else raw
    if key == "sessions.archive" and raw not in ("after_run", "hours", "off"):
        raise ValueError("sessions.archive must be after_run, hours or off")
    if key == "worktree.location":
        worktree_location({"worktree": {"location": raw}})
    if key == "autonomy.level" and raw not in ("L0", "L1", "L2"):
        raise ValueError("autonomy.level must be L0, L1 or L2")
    if key == "output.lead" and raw not in ("line", "full"):
        raise ValueError("output.lead must be line or full")
    if key == "escalate.on_self_checked" and raw not in ("review", "rung", "off"):
        raise ValueError("escalate.on_self_checked must be review, rung or off")
    if key == "routing.mode" and raw not in ("auto", "off"):
        raise ValueError("routing.mode must be auto or off")
    if key == "quota.routing" and raw not in ("on", "off"):
        raise ValueError("quota.routing must be on or off")
    if key == "routing.small_self_by" and raw not in ("cost", "files"):
        raise ValueError("routing.small_self_by must be cost or files")
    if key == "run.max_usd" and not float(raw) >= 0:
        raise ValueError("run.max_usd must be 0 (no limit) or a positive amount")
    if key == "ui.lang" and raw not in ("zh", "en"):
        raise ValueError("ui.lang must be zh or en")
    try:
        val = typ(raw)
    except ValueError as e:
        raise ValueError(f"{key} needs a {typ.__name__}: {e}") from e
    cur = {}
    if p.settings.exists():
        cur = tomllib.loads(p.settings.read_text(encoding="utf-8"))
    sec, name = key.split(".", 1)
    cur.setdefault(sec, {})[name] = val
    lines = ["# written by `ccx config set`; edit with that command"]
    for s, vals in cur.items():
        lines.append(f"\n[{s}]")
        lines += [f"{k} = {_toml_value(v)}" for k, v in vals.items()]
    p.settings.parent.mkdir(parents=True, exist_ok=True)
    p.settings.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {key: val}


def provider_of(cfg: dict, agent: str) -> dict | None:
    """The [providers.<agent>] entry when this agent name is a provider (e.g. deepseek), else None."""
    return (cfg.get("providers") or {}).get(agent)


def daily_cap(cfg: dict, agent: str) -> float | None:
    """USD a pay-per-token agent may spend per day: [providers.<name>] daily_usd, or [pay_per_token.<agent>]
    daily_usd for an agent billed per token by itself (dsh). None = no cap (subscription agents)."""
    pv = provider_of(cfg, agent) or ((cfg.get("pay_per_token") or {}).get(agent)) or {}
    cap = pv.get("daily_usd")
    return None if cap is None else float(cap)


def provider_env(cfg: dict, name: str) -> tuple[str, dict]:
    """A provider = an agent CLI pointed at another model API (e.g. DeepSeek through Claude Code).
    Values like "$DEEPSEEK_API_KEY" are read from the environment at run time; keys are never stored."""
    pv = (cfg.get("providers") or {}).get(name)
    if not pv:
        raise ValueError(f"unknown provider {name!r}; configured: {', '.join(cfg.get('providers') or {}) or 'none'}")
    env = {}
    for k, v in (pv.get("env") or {}).items():
        v = str(v)
        if v.startswith("$"):
            val = os.environ.get(v[1:])
            if not val:
                raise ValueError(f"provider {name} needs the environment variable {v[1:]} (your API key)")
            v = val
        env[k] = v
    return pv.get("agent", "claude"), env


def tier_spec(cfg: dict, tier: str, agent: str) -> dict:
    t = cfg["tiers"].get(tier)
    if t is None:
        raise ValueError(f"unknown tier {tier!r}; use one of {TIER_ORDER}")
    if t.get("delegate") is False:
        raise ValueError(f"{tier} ({t.get('label')}) means: do it yourself, don't delegate.")
    spec = t.get(agent)
    if not spec:
        raise ValueError(f"tier {tier} has no model configured for {agent}")
    return spec


def next_tier(tier: str) -> str | None:
    i = TIER_ORDER.index(tier)
    return TIER_ORDER[i + 1] if i + 1 < len(TIER_ORDER) else None
