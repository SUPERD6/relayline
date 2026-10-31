"""Helpers shared by the command modules (output, caller/lead detection, routing resolution)."""
from __future__ import annotations

import json
import os
import random
import sys
import time
import uuid

from pathlib import Path

from .. import learn, ledger, router
from ..config import AGENTS, DELEGATE_AGENTS
from ..runners import find_bin


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def human_tail(lines: list[str], stream=None) -> None:
    """A few plain lines after the JSON, only when stdout is a terminal: a person reads them. Leads and scripts read
    stdout through a pipe and get the JSON byte for byte as before."""
    stream = stream or sys.stdout
    try:
        tty = stream.isatty()
    except (AttributeError, ValueError, OSError):
        tty = False
    if tty and lines:
        print("\n" + "\n".join(lines), file=stream)


def hook_text(text: str, as_: str | None) -> str:
    """What a session hook prints. Codex (0.164) reads hook output that starts with '[' or '{' as JSON, and when it
    isn't, the hook counts as failed and nothing reaches the conversation (H7: every ccx line starts with '[ccx').
    A plain first line keeps it text."""
    if as_ == "codex" and text.lstrip()[:1] in ("[", "{"):
        return "From ccx (shared memory and delegated work):\n" + text
    return text


def _provider_lead(cli: str, env, cfg: dict | None = None) -> str | None:
    """The [providers] entry this Claude Code / Codex lead is pointed at, so a DeepSeek model behind Claude Code
    counts as DeepSeek. Claude Code: its ANTHROPIC_BASE_URL equals the provider's. Codex: config.toml's top-level
    model_provider is one a provider selects (`-c model_provider=...` given on Codex's own command line is not
    visible to the commands it runs; set CCX_LEAD then)."""
    from ..config import codex_home, load_config
    want = ""
    if cli == "claude":
        want = (env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
        if not want or "api.anthropic.com" in want:
            return None
    elif cli == "codex":
        import tomllib
        try:
            want = str(tomllib.loads((codex_home() / "config.toml").read_text(encoding="utf-8"))
                       .get("model_provider") or "")
        except (OSError, ValueError):
            return None
        if not want or want == "openai":
            return None
    try:
        provs = (cfg or load_config()).get("providers") or {}
    except Exception:  # noqa: BLE001
        return None
    for name, pv in provs.items():
        if (pv.get("agent") or "claude") != cli:
            continue
        if cli == "claude" and str((pv.get("env") or {}).get("ANTHROPIC_BASE_URL") or "").rstrip("/") == want:
            return name
        if cli == "codex" and f'model_provider="{want}"' in [str(x) for x in pv.get("args") or []]:
            return name
    return None


# What Codex sets for the commands it runs (codex-cli 0.164, checked on a real run 2026-10-25: also
# CODEX_VERSION and CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS). Not any CODEX_*: people set CODEX_HOME,
# CODEX_SQLITE_HOME or the installer's CODEX_INSTALL_DIR for good, and then a plain terminal looked like Codex.
CODEX_RUN_VARS = ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_TOOL_CALL_ID", "CODEX_CI", "CODEX_SANDBOX",
                  "CODEX_SANDBOX_NETWORK_DISABLED")


def lead_identity(env=None, cfg: dict | None = None) -> str:
    """Who is running this command, from the environment: a lead tool (claude, codex, dsh), the provider behind
    one (deepseek through Claude Code, deepseek-codex through Codex), or "user" at a plain terminal. CCX_LEAD
    names it outright. DeepSeek Harness gives the commands it runs DSH_SESSION_ID (0.2.1-rc.3, checked on a real
    run); it is checked first because a dsh started from another tool's terminal is the innermost one."""
    env = os.environ if env is None else env
    if env.get("CCX_LEAD"):
        return env["CCX_LEAD"]
    if env.get("DSH_SESSION_ID"):
        return "dsh"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return _provider_lead("claude", env, cfg) or "claude"
    if any(env.get(k) for k in CODEX_RUN_VARS):
        return _provider_lead("codex", env, cfg) or "codex"
    return "user"


def detach(args: list[str], log: Path, env: dict):
    """Start `ccx <args>` detached (hidden console), its output into `log`: `ccx run --bg`, `ccx discuss --bg`.
    Returns the Popen, for a caller that waits on it in the same call (`ccx run --bg --wait N`)."""
    import subprocess
    from ..config import ccx_argv
    from ..winproc import BACKGROUND as kw   # hidden console: its git/codex/claude calls pop no windows
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w", encoding="utf-8") as lf:
        return subprocess.Popen([*ccx_argv(), *[x for x in args if x != "--bg"]], stdout=lf,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env={**os.environ, **env},
                                cwd=os.getcwd(), **kw)


def _caller(explicit: str | None) -> str:
    return explicit or lead_identity()


def _brief(args) -> str:
    if getattr(args, "brief_file", None):
        return Path(args.brief_file).read_text(encoding="utf-8")
    if args.brief and args.brief != ["-"]:
        return " ".join(args.brief)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("give the task as text, --brief-file FILE, or on stdin")


def _target(to: str, caller: str) -> str:
    if to != "auto":
        return to
    return "codex" if caller != "codex" else "claude"


def _tier(tier: str, text: str, files: int) -> tuple[str, dict | None]:
    if tier != "auto":
        return tier, None
    r = router.classify(text, files)
    return r.tier, r.as_dict()


def _agent_of_model(model: str) -> str | None:
    m = model.lower()
    if m.startswith(("gpt", "o3", "o4", "codex")):
        return "codex"
    if m.startswith(("claude", "haiku", "sonnet", "opus")):
        return "claude"
    if m.startswith(("gemini", "flash", "pro")) or m in ("flash-lite", "auto"):
        return "gemini"
    return None


LEAD_VARS = {"claude": ("CLAUDE_CODE_SESSION_ID",), "codex": ("CODEX_THREAD_ID", "CODEX_SESSION_ID"),
             "dsh": ("DSH_SESSION_ID",)}


def lead_session_id(caller: str | None = None) -> str | None:
    """The conversation the lead is in right now (set by Claude Code / Codex for the commands they run).
    The caller's own variable wins: a Codex started from inside Claude Code also inherits Claude's."""
    own = LEAD_VARS.get(caller or "", ())
    rest = tuple(k for ks in LEAD_VARS.values() for k in ks if k not in own)
    for k in ("CCX_LEAD_SESSION", *own, *rest):
        if os.environ.get(k):
            return os.environ[k]
    return None


CONTINUE_WINDOW_SEC = 3600      # the prompt cache lives 1 h: older sessions would be re-read at full price


CONTINUE_MAX_DEPTH = 5          # after 5 tasks in one sub-session, start fresh (its context keeps growing)


def _session_keeps_mode(agent: str) -> bool:
    """The agent's read-only / write is set when its session starts (dsh: an environment variable) and a resumed
    session keeps it: seen on a real dsh 0.2.1-rc.3 run, where a write task continued in a read-only session could
    not edit (2026-10-25). Claude and Codex take their permission flags on every call."""
    from ..agents import NAMES, get
    return agent in NAMES and get(agent).run_env is not None


def find_continuable(p, lead: str | None, cwd: Path, to: str, mode: str | None = None) -> str | None:
    """Same lead conversation + same folder + same agent + recent + ended cleanly -> its session can take the
    next task, so the sub-agent keeps what it already read instead of re-reading the repo. Not across read/write
    for an agent whose session keeps the permission it started with."""
    if not lead:
        return None
    from ..archive import archived_ids
    gone = archived_ids(p, after_run=False)     # archived right after its run: it comes back when continued
    here = str(cwd.resolve())
    for r in reversed(ledger.rows(p)):
        if r.get("type") or r.get("lead_session") != lead:
            continue
        if time.time() - (r.get("ts") or 0) > CONTINUE_WINDOW_SEC:
            return None
        if r.get("cwd") != here or r.get("to") != to or r.get("ephemeral"):
            continue
        # env: a session whose sub-agent could not start a process here is not continued (the next task would meet
        # the same wall in it); the new run starts fresh, and a resume of that run needs --env-fixed
        if r.get("kind") in ("quota", "auth", "timeout", "user_stopped", "interrupted", "env") or not r.get("session_id")                 or r["run_id"] in gone:
            return None
        if int(r.get("continue_depth") or 0) + 1 >= CONTINUE_MAX_DEPTH:
            return None
        if mode and r.get("mode") and r["mode"] != mode and _session_keeps_mode(to):
            return None
        return r["run_id"]
    return None


SEAT_WINDOW_SEC = 7 * 86400     # a named seat keeps its session a week (re-reading after the cache expires is
SEAT_MAX_DEPTH = 30             # still cheaper than starting over); after 30 tasks it starts fresh


def find_seat(p, seat: str, cwd: Path, to: str) -> str | None:
    """The last run of a named seat ("reviewer") in this folder on this agent: its session takes the next task."""
    from ..archive import archived_ids
    gone = archived_ids(p)
    here = str(cwd.resolve())
    for r in reversed(ledger.rows(p)):
        if r.get("type") or r.get("label") != f"seat:{seat}" or r.get("cwd") != here or r.get("to") != to:
            continue
        if time.time() - (r.get("ts") or 0) > SEAT_WINDOW_SEC or r["run_id"] in gone or not r.get("session_id"):
            return None
        if r.get("kind") in ("quota", "auth", "timeout", "user_stopped", "interrupted", "env") or                 int(r.get("continue_depth") or 0) + 1 >= SEAT_MAX_DEPTH:
            return None
        return r["run_id"]
    return None


def installed_agents() -> list[str]:
    """Routing only considers agents whose CLI is actually on this machine (auto-discovery)."""
    return [a for a in DELEGATE_AGENTS if find_bin(a)]


def parse_quota(items: list[str] | None) -> dict:
    """["claude=0.4", "codex=85"] -> {"claude": 0.4, "codex": 0.85} (a fraction or a percentage)."""
    out = {}
    for q in items or []:
        ag, _, v = q.partition("=")
        out[ag.strip()] = float(v) if float(v) <= 1 else float(v) / 100
    return out


def provider_agents(cfg: dict) -> list[str]:
    """Provider agents (e.g. deepseek) whose key is set and whose CLI is installed."""
    out = []
    for name, pv in (cfg.get("providers") or {}).items():
        keys = [str(v)[1:] for v in (pv.get("env") or {}).values() if str(v).startswith("$")]
        if find_bin(pv.get("agent", "claude")) and all(os.environ.get(k) for k in keys):
            out.append(name)
    return out


def cash_ready(p, cfg: dict, quota: dict) -> list[str]:
    """Pay-per-token agents that may take work now: key set and under today's cap. Whether they win is the total
    cost's call (their money against the subscriptions' quota at its shadow price), not a quota threshold."""
    try:
        cash = learn.module(p, "routing").load_priors().get("cash") or {}
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ag in provider_agents(cfg):
        cap = (cfg["providers"][ag] or {}).get("daily_usd")
        if ag in cash.get("agents", []) and (cap is None or ledger.spent_today(p, ag) < float(cap)):
            out.append(ag)
    return out


def _maybe_probe_claude(p, cfg: dict, agents: list[str], given: dict) -> None:
    """Claude's quota is only seen in a Claude run's events. When Claude is a candidate and the last reading is
    over an hour old, one tiny request refreshes it (off with [quota] probe_claude = false or CCX_NO_QUOTA_PROBE)."""
    if "claude" not in agents or "claude" in given or os.environ.get("CCX_NO_QUOTA_PROBE") == "1"             or not (cfg.get("quota") or {}).get("probe_claude", True) or not find_bin("claude"):
        return
    from .. import quota
    age = quota.claude_reading_age(p)
    if age is None or age > quota.PROBE_AFTER_S:
        try:
            quota.probe(p)
        except Exception:  # noqa: BLE001 — a failed probe just leaves the old reading
            pass


def resolve(spec: dict, caller: str, p, cfg: dict) -> tuple[dict | None, dict]:
    """One task spec (CLI flags or a batch entry) -> (Request kwargs, routing info).
    kwargs is None when the answer is "don't delegate" (do it yourself / split first).

    Order: explicit --model/--effort  >  rubric (task-routing, learns from outcomes)  >  --tier  >
    keyword heuristic (fallback when no rubric is given)."""
    to = spec.get("to") or "auto"
    # the model pick: --tradeoff, else defaults.tradeoff, as before. A tier the person picked in their settings
    # (`ccx config set policy.picked <tier>`) is the whole-workflow tier when the lead names none (who does it, the
    # size band), but it does not change the models: the delegated part picks them like save (DECISIONS, tiers)
    tradeoff = spec.get("tradeoff") or cfg["defaults"].get("tradeoff", "save")
    policy_tier = spec.get("tradeoff") or picked_tier(cfg) or tradeoff
    route = {"tradeoff": tradeoff}
    if spec.get("no_ab"):                     # kept in the ledger: ledger.is_eval leaves such runs out
        route["no_ab"] = True
    if spec.get("minutes"):
        route["minutes"] = float(spec["minutes"])
    rubric = {k: spec[k] for k in learn.RUBRIC_KEYS[1:] if spec.get(k)}
    given_files = int(spec.get("files") or 0)      # the lead's own estimate (sizing a tier), before any guess below
    if spec.get("brief") and (rubric or spec.get("minutes")):
        from ..signals import measure        # what the brief and the folder show, the same for everyone
        obj = measure(spec["brief"], Path(spec.get("cwd") or os.getcwd()))
        if obj:
            route["objective"] = obj
            if not spec.get("files"):
                spec = {**spec, "files": obj["suggests"]["files"]}
            if rubric and "coupling" not in rubric:
                rubric["coupling"] = obj["suggests"]["coupling"]
    if spec.get("b") is not None:
        route["b"] = float(spec["b"])
    elif rubric or spec.get("minutes"):
        b_rub = None
        if rubric:
            rubric["files"] = int(spec.get("files") or 1)
            b_rub = learn.difficulty(p, rubric)
            route["rubric"] = rubric
        d = learn.combine_difficulty(p, b_rub, spec.get("minutes"), caller)
        route["b"], route["difficulty"] = d["b"], d["parts"]
    if "b" in route:
        tp = tier_policy(p, cfg, {**spec, "files": given_files}, policy_tier)
        if tp:
            route["policy"] = tp

    if spec.get("provider"):
        pv = (cfg.get("providers") or {}).get(spec["provider"])
        if not pv:
            raise ValueError(f"unknown provider {spec['provider']!r}")
        model = spec.get("model") or (pv.get("models") or [None])[-1]
        if not model:
            raise ValueError(f"provider {spec['provider']} needs --model")
        route["source"] = f"provider:{spec['provider']}"
        return {"to": spec["provider"], "model": model, "effort": spec.get("effort") or "low",
                "tier": "auto", "route": route, "provider": spec["provider"]}, route
    if spec.get("model"):
        agent = to if to != "auto" else (_agent_of_model(spec["model"]) or _target("auto", caller))
        route["source"] = "explicit"
        default_effort = "default" if agent == "gemini" else "medium"
        return {"to": agent, "model": spec["model"], "effort": spec.get("effort") or default_effort,
                "tier": "auto", "route": route}, route
    if "b" in route and spec.get("tier", "auto") == "auto":
        agents = ((installed_agents() or list(AGENTS)) + cash_ready(p, cfg, spec.get("quota") or {})
                  if to == "auto" else [to])
        _maybe_probe_claude(p, cfg, agents, spec.get("quota") or {})
        pk = learn.pick(p, route["b"], agents, tradeoff,
                        max_escalations=int(cfg["defaults"].get("max_escalations", 1)), mode=spec.get("mode"),
                        kind=spec.get("kind"), quota=spec.get("quota"), risk=spec.get("risk"))
        route["kind"] = learn.task_kind(spec.get("mode"), spec.get("kind"))
        route.update(source="task-routing", rung=pk["rung"], ladder=pk["ladder"], p=pk["p"],
                     chain_p=pk["chain_p"], expected_usd=pk.get("expected_usd"))
        if pk.get("stale"):
            route["stale"] = pk["stale"]
        if pk.get("advice") and not spec.get("force") and spec.get("person_to") \
                and pk["advice"].startswith("do-it-yourself"):
            route["cheaper_self"] = PERSON_TO_NOTE
        elif pk.get("advice") and not spec.get("force"):
            route["advice"] = pk["advice"]
            return None, route
        from .. import trial
        rate = float(os.environ.get("CCX_AB_RATE") or cfg["defaults"].get("ab_self_rate", 0) or 0)
        # only the run of a proposal the person's picked tier pre-authorised skips the random A/B self-run and the
        # trial (the tier decided who does it). A plain --tradeoff (project-manager passes --tradeoff save) is a
        # model pick and keeps A/B and the H11 trial exactly as before
        explicit = bool(spec.get("tier_preauth"))
        tr = (trial.active(p) if caller in AGENTS and not spec.get("force") and not spec.get("no_ab")
              and not explicit else None)
        if tr:                                # H11: a formal comparison is running: balanced halves
            route.update(trial=tr["id"], bucket=trial.bucket(route["kind"], route["b"]))
            self_run = trial.assign(p, tr, route["kind"], route["b"]) == "self"
        else:
            self_run = (rate > 0 and caller in AGENTS and not spec.get("force") and not spec.get("no_ab")
                        and not explicit and random.random() < rate)
        if self_run:
            route["ab"] = _ab_open(p, caller, route["b"], pk["rung"], spec.get("brief", ""),
                                   **({"trial": tr["id"], "bucket": route["bucket"], "kind": route["kind"],
                                       "lead_session": lead_session_id(caller)} if tr else {}))
            why = (f"the {tr['id']} comparison puts about {tr['rate']:.0%} of tasks on your side" if tr else
                   f"randomly chosen ~{rate:.0%} of tasks")
            route["advice"] = (f"ab-sample: do this one yourself ({why}, to measure what delegating saves), then "
                               f"run `ccx ab done {route['ab']} --ok 1|0`. Opt out: --no-ab")
            return None, route
        return {"to": pk["agent"], "model": pk["model"], "effort": pk["effort"], "tier": "auto",
                "route": route}, route
    tier, why = _tier(spec.get("tier", "auto"), spec.get("brief", ""), int(spec.get("files") or 0))
    route.update(source="tier" if spec.get("tier", "auto") != "auto" else "keywords", tier=tier)
    if why:
        route["why"] = why
    if tier == "T0" and not spec.get("force"):
        if spec.get("person_to"):
            route["cheaper_self"] = PERSON_TO_NOTE
        else:
            route["advice"] = "do-it-yourself: delegating costs more than the task"
            return None, route
    if tier == "T0":
        tier = "T1"
    return {"to": _target(to, caller), "tier": tier, "route": route}, route


PERSON_TO_NOTE = ("small enough that doing it yourself would be cheaper; delegated anyway because you named --to "
                  "(a lead's call without --force is still refused)")


def person_named_to(caller: str, to: str | None, force: bool = False) -> bool:
    """Did a person at a plain terminal (no lead tool detected, or --from user) name the sub-agent themselves? Then a
    too-small task is still delegated, with one line saying it would be cheaper to do it yourself: the README's first
    command was refused as do-it-yourself in the 2026-10-29 new-user walkthrough. A lead's call keeps the refusal (the
    agent-delegate skill relies on it)."""
    return caller == "user" and bool(to) and to != "auto" and not force


def tier_policy(p, cfg: dict, spec: dict, tradeoff) -> dict | None:
    """The whole-workflow tier for this task (task-routing tier_plan, [policy.*] in config): who does it (self |
    ccx2 | direct), its size band, and whether the person picked the tier (explicit: this is the tier set in the
    person's settings, `policy.picked`; a --tradeoff the lead passes is only a model pick and authorises nothing).
    A bad [policy] entry does not stop routing: it comes back as {"error": ...} (no mode), and an explicit tier then
    falls back to offer-first; `ccx doctor` shows the same error."""
    picked = picked_tier(cfg)
    explicit = bool(picked) and str(tradeoff) == picked
    try:
        tp = learn.tier_plan(p, tradeoff, spec.get("brief", ""), spec.get("minutes"), int(spec.get("files") or 0),
                             int(spec.get("lead_ctx") or 0), cfg.get("policy"))
    except Exception as e:  # noqa: BLE001 — a bad [policy] entry must not stop routing
        return {"error": f"tier plan failed ({type(e).__name__}: {e}); check config [policy.*]",
                "tier": str(tradeoff), "explicit": explicit}
    if tp:
        tp["explicit"] = explicit
    return tp


def picked_tier(cfg: dict) -> str:
    """The tier the person picked for all work (`ccx config set policy.picked balanced`; "" = none, shipped)."""
    v = str(((cfg.get("policy") or {}).get("picked")) or "").strip().lower()
    return v if v in ("save", "balanced", "fast", "cheapest") else ""


def _ab_open(p, caller: str, b: float, rung: str, brief: str, **extra) -> str:
    ab_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    d = p.state / "ab"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{ab_id}.json").write_text(json.dumps({"id": ab_id, "caller": caller, "b": b, "would_route": rung,
                                                 "brief_chars": len(brief), "ts": time.time(), **extra}),
                                     encoding="utf-8")
    return ab_id


def apply_mode(spec: dict) -> dict:
    """Fill spec["mode"] from the task text when no --mode was given (ccx/modes.py); keep how it was decided."""
    from ..modes import resolve_mode
    m = resolve_mode(spec.get("mode"), spec.get("brief", ""))
    spec.update(mode=m["mode"], mode_source=m["source"], mode_why=m["why"])
    return m


def _spec_from_args(a, text: str) -> dict:
    return {"no_ab": getattr(a, "no_ab", False), "to": a.to, "brief": text, "tier": a.tier, "files": a.files, "model": a.model,
            "effort": a.effort, "b": a.b, "coupling": a.coupling, "clarity": a.clarity, "risk": a.risk,
            "novelty": a.novelty, "minutes": a.minutes, "tradeoff": a.tradeoff, "force": a.force,
            "provider": getattr(a, "provider", None), "mode": getattr(a, "mode", None),
            "quota": parse_quota(getattr(a, "quota", None)), "kind": getattr(a, "kind", None),
            "cwd": getattr(a, "cwd", None)}


def _routing_args(ap, into=None) -> None:
    """The routing rubric options, in their own help group, or in `into` (run's "advanced" group; --tradeoff then
    stays with the main options)."""
    g = into if into is not None else ap.add_argument_group(
        "routing rubric (task-routing; any of these switches on the calibrated pick)")
    g.add_argument("--files", type=int, default=0, help="files touched")
    g.add_argument("--coupling", choices=["one", "cross", "system"])
    g.add_argument("--clarity", choices=["spec", "goal", "unknown"])
    g.add_argument("--risk", choices=["low", "visible", "critical"])
    g.add_argument("--novelty", choices=["pattern", "new"])
    g.add_argument("--b", type=float, help="difficulty 0-10 directly instead of the rubric")
    g.add_argument("--kind", choices=["code", "read", "research", "write"],
                   help="kind of work: decides which public benchmarks count (default: read-only -> read, else code)")
    (ap if into is not None else g).add_argument("--tradeoff", choices=["save", "balanced", "fast", "cheapest"],
                   help="tier: save | balanced | fast | cheapest (task-routing). Picks the models; `ccx propose` "
                        "also shows who would do the task (self, ccx, or ccx unchecked for cheapest). Passing it "
                        "authorises nothing. Default models: config defaults.tradeoff (shipped: save); default tier "
                        "plan: the tier the person picked (`ccx config set policy.picked`, which pre-authorises "
                        "what it delegates and does not change the models), else that default")
