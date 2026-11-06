"""Bridge from ccx to the three standalone skills (task-routing, task-split, task-checkpoint).

The skills stay usable on their own (plain scripts, no ccx import). ccx loads them by path and:
  * asks task-routing which rung (agent:model:effort) to start on, and what to escalate to;
  * records every verified attempt back into task-routing (ability + cost) and task-split (horizon),
    so the estimates calibrate themselves from real runs instead of being tuned by hand;
  * writes the sub-agent's session id into a task-checkpoint step the moment it is known.

Learned state lives in the hub (CCX_HUB/ccx/routing-state.json, split-state.json), shared by both agents.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path

from .config import Paths, data_dir
from .runners import cli_version

REPO_SKILLS = data_dir("skills")
SCRIPTS = {
    "routing": ("task-routing", "task_routing.py"),
    "split": ("task-split", "split_plan.py"),
    "checkpoint": ("task-checkpoint", "checkpoint.py"),
}


def _skill_file(p: Paths | None, name: str) -> Path:
    folder, script = SCRIPTS[name]
    # prefer the copy the user actually has installed in the hub (that is what both agents run)
    for base in ([p.skills] if p else []) + [REPO_SKILLS]:
        f = base / folder / "scripts" / script
        if f.exists():
            return f
    raise FileNotFoundError(f"skill script {folder}/scripts/{script} not found")


@lru_cache(maxsize=None)
def _load(path: str, hub: str):
    os.environ.setdefault("CCX_HUB", hub)      # learned state goes to the hub, not the skill folder
    spec = importlib.util.spec_from_file_location(f"ccx_skill_{Path(path).stem}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def module(p: Paths, name: str):
    return _load(str(_skill_file(p, name)), str(p.hub))


# ------------------------------------------------------------------ routing
RUBRIC_KEYS = ("files", "coupling", "clarity", "risk", "novelty")


def difficulty(p: Paths, rubric: dict) -> int:
    tr = module(p, "routing")
    return tr.difficulty(int(rubric.get("files", 1)), rubric.get("coupling", "one"),
                         rubric.get("clarity", "spec"), rubric.get("risk", "low"),
                         rubric.get("novelty", "pattern"))


def combine_difficulty(p: Paths, b_rubric, minutes, lead: str | None) -> dict:
    """b from the rubric and/or human minutes plus the lead's learned bias (older skill copy: rubric only)."""
    tr = module(p, "routing")
    if not hasattr(tr, "combine_difficulty"):
        if b_rubric is None:
            raise ValueError("this task-routing copy needs the rubric (no --minutes support)")
        return {"b": float(b_rubric), "parts": {"rubric": float(b_rubric)}}
    return tr.combine_difficulty(b_rubric, minutes, tr.lead_bias(tr.load_state(), lead))


def model_tradeoff(tradeoff):
    """The whole-workflow tier "cheapest" picks models like save (an older skill copy knows no "cheapest")."""
    return "save" if tradeoff == "cheapest" else tradeoff


def tier_plan(p: Paths, tradeoff, brief: str = "", minutes: float | None = None, files: int = 0,
              lead_ctx: int = 0, policy: dict | None = None) -> dict | None:
    """task-routing's whole-workflow tier for one task (self | ccx2 | direct); None with an older skill copy."""
    tr = module(p, "routing")
    if not hasattr(tr, "tier_plan"):
        return None
    return tr.tier_plan(tradeoff, brief, minutes, files, lead_ctx, policy)


def pick(p: Paths, b: float, agents: list[str], tradeoff: str, verifiable: bool = True,
         max_escalations: int = 1, mode: str | None = None, kind: str | None = None, quota: dict | None = None,
         risk: str | None = None) -> dict:
    """-> {rung, agent, model, effort, ladder:[rung...], p, advice, b}"""
    tr = module(p, "routing")
    pri, st = tr.load_priors(), tr.load_state()
    kw = dict(tradeoff=model_tradeoff(tradeoff), verifiable=verifiable, max_escalations=max_escalations)
    try:
        res = tr.route(b, pri, st, agents, mode=mode, kind=kind or task_kind(mode), quota=known_quota(quota, p),
                       risk=risk or "low", **kw)
    except TypeError:                                   # an older installed skill copy: no mode / kind argument
        try:
            res = tr.route(b, pri, st, agents, mode=mode, **kw)
        except TypeError:
            res = tr.route(b, pri, st, agents, **kw)
    x = res["pick"]
    agent, model, effort = x["rung"].split(":", 2)
    return {"rung": x["rung"], "agent": agent, "model": model, "effort": effort,
            "ladder": x.get("escalates_to", []), "p": round(x["p"], 3),
            "chain_p": round(x.get("chain_success", x["p"]), 3), "advice": res.get("advice"),
            "stale": res.get("stale"), "b": b, "tradeoff": tradeoff,
            "expected_usd": None if x.get("expected_usd") is None else round(x["expected_usd"], 4)}


def known_quota(given: dict | None = None, p: Paths | None = None) -> dict:
    """Projected share of each subscription's tightest window by its reset (ccx/quota.py): what the caller gave,
    else read from the logs (Codex) and kept readings (Claude)."""
    from . import quota
    from .config import paths
    try:
        return quota.pressure(p or paths(), given)["quota"]
    except Exception:  # noqa: BLE001 — never break routing over a reading
        return dict(given or {})


def task_kind(mode: str | None, kind: str | None = None) -> str:
    """The kind of work decides which benchmarks count (task-routing merge): given, else read-only -> read."""
    return kind or ("read" if mode == "read" else "code")


def self_vs_delegate(p: Paths, b: float, lead: str, best_rung: str, ctx_tokens: int, remaining_turns: int,
                     tradeoff: str = "balanced", lead_ctx: int = 0) -> dict:
    """Section 4.4 of the plan: what doing it yourself costs (context you'd carry for the rest of the session)
    vs delegating (brief + sub cost + read-back/review). Uses the routing skill's estimates."""
    tr = module(p, "routing")
    pri, st = tr.load_priors(), tr.load_state()
    agent = best_rung.split(":", 1)[0]
    tradeoff = model_tradeoff(tradeoff)
    res = tr.route(b, pri, st, [agent], tradeoff=tradeoff, ctx_tokens=0)
    best = next((x for x in res["rows"] if x["rung"] == best_rung), res["pick"])
    try:
        return tr.self_vs_delegate(b, pri, st, lead, best, ctx_tokens, remaining_turns, lead_ctx)
    except TypeError:                                   # an older installed skill copy
        return tr.self_vs_delegate(b, pri, st, lead, best, ctx_tokens, remaining_turns)


def three_way(p: Paths, b: float, lead: str, delegate_agents: list[str], ctx_tokens: int, remaining_turns: int,
              tradeoff: str = "balanced", needs: tuple = (), quota: dict | None = None,
              kind: str = "code", risk: str = "low", lead_ctx: int = 0) -> dict | None:
    """Self / the lead's built-in sub-agent / ccx (task-routing's three_way). Codex's quota is read from its own
    session logs unless given; Claude Code's logs carry no quota %, so it comes only from --quota."""
    tr = module(p, "routing")
    if not hasattr(tr, "three_way"):
        return None                                      # an older installed skill copy
    q = known_quota(quota, p)
    tradeoff = model_tradeoff(tradeoff)
    pri, st = tr.load_priors(), tr.load_state()
    try:
        out = tr.three_way(b, pri, st, lead, delegate_agents, ctx_tokens, remaining_turns, tradeoff=tradeoff,
                           needs=tuple(needs), quota=q, kind=kind, risk=risk, lead_ctx=lead_ctx)
    except TypeError:                                   # skill copy without kinds
        out = tr.three_way(b, pri, st, lead, delegate_agents, ctx_tokens, remaining_turns, tradeoff=tradeoff,
                           needs=tuple(needs), quota=q)
    out["quota"] = q
    out["how"] = _how(out, b)
    return out


def _how(choice: dict, b: float) -> str:
    """What the lead does next for the recommended way (ccx cannot start a built-in sub-agent itself)."""
    rung = choice.get("rung", "")
    if choice.get("recommend") == "self":
        return "do it yourself"
    if choice.get("recommend") == "builtin":
        agent, model, _ = rung.split(":", 2)
        tool = (f"your Agent tool with model {model}" if agent.startswith("claude")
                else "your multi_agent tool (one sub-agent; it runs on your own model)")
        return (f"use {tool} and give it the brief; check its result, then: "
                f"ccx verify --builtin {rung} --b {b:g} --ok 1|0 --agent-id <its id>")
    agent, model, effort = rung.split(":", 2)
    return f'ccx run --to {agent} --model {model} --effort {effort} "<brief>"  (then ccx verify <run_id> --ok 1|0)'


def codex_quota(days: float = 7) -> float | None:
    """Latest share of Codex's primary (weekly) quota used, 0..1, from its session logs."""
    from .quota import codex_readings
    try:
        prim = [s for s in codex_readings(days) if s.get("window") == "primary"]
    except Exception:  # noqa: BLE001
        return None
    return round(max(prim, key=lambda s: s["ts"])["used"], 3) if prim else None


def refresh_benchmarks_later(p: Paths) -> bool:
    """At session start: if the public benchmark cache is a week old, refresh it in a detached process (a few
    seconds of downloads; the session never waits for it). Returns whether one was started."""
    import subprocess
    import sys
    try:
        tr = module(p, "routing")
        if not hasattr(tr, "bench") or not tr.bench().is_stale(tr.bench_path()):
            return False
        script = _skill_file(p, "routing")
    except Exception:  # noqa: BLE001 — older skill copy or no skill: nothing to do
        return False
    from .winproc import BACKGROUND as flags      # hidden console: no window for it or its children
    subprocess.Popen([sys.executable, str(script), "refresh", "--if-stale"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **flags)
    return True


def escalates_to(p: Paths, agent: str) -> str | None:
    """The agent whose stronger rungs follow this agent's own ladder ([escalate_to] in the priors)."""
    try:
        return (module(p, "routing").load_priors().get("escalate_to") or {}).get(agent)
    except Exception:  # noqa: BLE001
        return None


def ladder_after(p: Paths, rung: str, n: int) -> list[str]:
    """Next n stronger rungs of the same agent (escalation path for an explicit --model/--effort), then of the
    agent it escalates to."""
    tr = module(p, "routing")
    pri, st = tr.load_priors(), tr.load_state()
    agent = rung.split(":", 1)[0]
    th = lambda r: r["theta"] + st["offsets"].get(tr.rung_key(r), 0.0)   # noqa: E731
    rows = sorted((r for r in pri["rungs"] if r["agent"] == agent), key=th)
    nxt = (pri.get("escalate_to") or {}).get(agent)
    if nxt and rows:
        rows += sorted((r for r in pri["rungs"] if r["agent"] == nxt and th(r) > th(rows[-1])), key=th)
    keys = [tr.rung_key(r) for r in rows]
    if rung in keys:
        return keys[keys.index(rung) + 1: keys.index(rung) + 1 + n]
    return []


def _with_cli(fn, *args, cli: str):
    """Pass the CLI version to a skill function; an older installed skill copy doesn't take it."""
    try:
        return fn(*args, cli=cli)
    except TypeError:
        return fn(*args)


def mark_unavailable(p: Paths, agent: str, model: str) -> None:
    tr = module(p, "routing")
    with tr._Lock(tr.state_path()):
        st = tr.load_state()
        _with_cli(tr.mark_unavailable, st, agent, model, cli=cli_version(agent))
        tr.save_state(st)


def is_unavailable(p: Paths, agent: str, model: str) -> bool:
    """A mark made under another CLI version is dropped here, so routing stops skipping the model too."""
    try:
        tr = module(p, "routing")
        st, cli = tr.load_state(), cli_version(agent)
        key = f"{agent}:{model}"
        if key in (st.get("unavailable") or {}) and not _with_cli(tr.unavailable, st, agent, model, cli=cli):
            with tr._Lock(tr.state_path()):
                st = tr.load_state()
                st["unavailable"].pop(key, None)
                tr.save_state(st)
            return False
        return _with_cli(tr.unavailable, st, agent, model, cli=cli)
    except Exception:  # noqa: BLE001
        return False


def substitute(p: Paths, agent: str, model: str, effort: str) -> tuple[str, str] | None:
    """Cheapest rung of the same agent, at least as able as agent:model:effort, on a model this account can use."""
    tr = module(p, "routing")
    pri, st = tr.load_priors(), tr.load_state()
    rows = sorted((r for r in pri["rungs"] if r["agent"] == agent), key=lambda r: r["theta"])
    base = next((r["theta"] for r in rows if r["model"] == model and r["effort"] == effort),
                next((r["theta"] for r in rows if r["model"] == model), 0))
    for r in rows:
        if r["model"] != model and r["theta"] >= base and not tr.unavailable(st, agent, r["model"]):
            return r["model"], r["effort"]
    for r in reversed(rows):                       # nothing as able: the best one left
        if r["model"] != model and not tr.unavailable(st, agent, r["model"]):
            return r["model"], r["effort"]
    return None


def price_usd(p: Paths, agent: str, model: str, usage: dict, ts: float | None = None) -> float | None:
    """API-equivalent USD for one attempt from the routing price table (None if the model is unknown); `ts` (when
    it ran) applies an off-peak discount where the priors have one."""
    try:
        tr = module(p, "routing")
        pri = tr.load_priors()
    except Exception:  # noqa: BLE001
        return None
    mult = tr.price_mult(pri, agent, ts) if hasattr(tr, "price_mult") else 1.0
    rs = [r for r in pri["rungs"] if r["agent"] == agent]
    r = next((r for r in rs if r["model"] == model), None) or \
        next((r for r in rs if r["model"] in (model or "")), None)     # "claude-opus-5-5" -> opus
    key = r["price"] if r else (pri.get("model_prices") or {}).get(model or "")
    if key and key in pri["prices"]:
        pr = pri["prices"][key]
    else:                       # a provider can carry its own prices: [providers.<name>] prices."<model>"
        from .config import load_config
        pr = ((((load_config(p).get("providers") or {}).get(agent) or {}).get("prices") or {}).get(model or ""))
        if not pr:
            return None
    w = usage.get("cache_write_tokens", 0) or 0
    w1h = min(w, usage.get("cache_write_1h_tokens", 0) or 0)
    m5, m1h = pr.get("cache_write_5m_mult", 1.25), pr.get("cache_write_1h_mult", 2.0)
    return mult * ((usage.get("input_tokens", 0) or 0) * pr["input"]
            + ((w - w1h) * m5 + w1h * m1h) * pr["input"]
            + (usage.get("cached_input_tokens", 0) or 0) * pr["cached"]
            + (usage.get("output_tokens", 0) or 0) * pr["output"]) / 1e6


def record_outcomes(p: Paths, record: dict, final_ok: bool) -> list[dict]:
    """Feed every attempt of a run back into the skills. Failed earlier attempts count as failures of
    their rung; the last attempt counts as `final_ok`. Needs a difficulty b (from the rubric)."""
    route = record.get("route") or {}
    b = route.get("b")
    out = []
    if b is None:
        return out
    tr = module(p, "routing")
    pri, st = tr.load_priors(), tr.load_state()
    sp = None
    if route.get("minutes"):
        try:
            sp = module(p, "split")
        except FileNotFoundError:
            sp = None
    atts = record.get("attempts", [])
    first_p = None
    for i, a in enumerate(atts):
        if a.get("kind") in ("quota", "capacity", "auth", "timeout", "model", "policy", "needs_write", "split", "over_budget",
                             "user_stopped", "killed", "interrupted"):
            continue                      # not the model's fault: says nothing about ability
        rung = f"{a['agent']}:{a['model']}:{a['effort']}"
        ok = final_ok if i == len(atts) - 1 else False
        cost = a.get("cost_usd") if a.get("cost_usd") is not None else a.get("ae_usd")
        with tr._Lock(tr.state_path()):
            st = tr.load_state()
            try:
                r = tr.record(rung, float(b), ok, pri, st, cost_usd=cost, seconds=a.get("seconds"))
            except TypeError:                            # skill copy without time learning
                r = tr.record(rung, float(b), ok, pri, st, cost_usd=cost)
            tr.save_state(st)
        if first_p is None:
            first_p = r.get("predicted_p")
        out.append(r)
        if sp is not None:
            try:
                with tr._Lock(sp.state_path()):          # batch runs record from several threads
                    out.append({"split": sp.record(rung, float(route["minutes"]), ok)})
            except SystemExit:
                pass                      # rung without a horizon prior: skip
    if first_p is not None and record.get("caller") and hasattr(tr, "record_bias"):
        # the lead's estimate vs what happened: learns whether this lead tends to under- or over-estimate
        secs = sum(a.get("seconds") or 0 for a in atts)
        with tr._Lock(tr.state_path()):
            st = tr.load_state()
            tr.record_bias(st, record["caller"], final_ok, float(first_p), route.get("rubric"),
                           route.get("minutes"), secs)
            tr.save_state(st)
    return out


# ------------------------------------------------------------------ checkpoint
def checkpoint(p: Paths, cwd: Path, *args: str) -> None:
    """Best effort: run a task-checkpoint command in the project at cwd."""
    cp = module(p, "checkpoint")
    old = os.environ.get("CHECKPOINT_ROOT")
    try:
        if not old:
            os.environ["CHECKPOINT_ROOT"] = str(cp_root(cwd))
        cp.main(list(args))
    except SystemExit:
        pass
    finally:
        if old is None:
            os.environ.pop("CHECKPOINT_ROOT", None)


def cp_root(cwd: Path) -> Path:
    import subprocess
    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip()).parent
    return cwd
