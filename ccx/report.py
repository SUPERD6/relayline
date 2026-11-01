"""Usage accounting and the static dashboard (`ccx stats --summary`, `ccx report`).

Numbers, and how each one is computed (kept simple so anyone can re-derive them):

  AE$ (API-equivalent USD)  tokens x list price from the task-routing price table, per bucket
                            (fresh, cache write [5m 1.25x / 1h 2x input], cache read, output).
                            Subscription plans don't bill per token, so AE$ is the common yardstick.
  Codex credits             AE$ x 25 (OpenAI credit conversion noted in docs/research, 2026-10-23).
  Cache-read share          cached / (fresh + cache write + cached) input tokens.
  Cost per success (CPS)    sub-agent AE$ / runs that ended done (verified when a verdict exists).
  Saving                    measured when a `ccx trial` has enough tasks in both halves (`saving_kind`
                            "measured"): the trial's saving per task (lead's own $ when it did the task minus
                            lead + sub-agent $ when it delegated) x delegated runs in the window.
                            Otherwise a MODEL (`saving_kind` "model"), kept in the data for scripts and never
                            shown on the page (P1-4: the page says "not measured yet"): per
                            delegated run, the task-sized part of the sub-agent's tokens (fresh input + output,
                            minus the sub-agent's cache reads and writes, ~93k tokens a run in round 2: the run's
                            whole input, mostly cache reads, its fixed prefix re-sent on each of ~5 requests;
                            and for Codex ~20k start-up tokens it reads fresh, STARTUP_FRESH) at the lead's
                            model price, minus what the sub-agent cost, minus the lead's brief+review overhead
                            (400 output + 1500+1000*b input tokens at the lead's price); 95% CI by bootstrap over
                            runs. `saving_old_model` keeps the old figure (all the sub-agent's tokens at the lead's
                            price, start-up included) for comparison; it bounds nothing that was measured. Measured totals so far (rounds 1-5,
                            docs/measured.md) were about even, so the model is never the headline. H11 (2026-10-24,
                            docs/research) measured something else: what the lead saves is the requests it
                            does not make x its own context per request — about one request per small task,
                            and only when the lead trusts ccx's check instead of re-running it.
"""
from __future__ import annotations

import html
import json
import random
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path

from . import accuracy, learn, ledger, usage
from .config import Paths, load_config

STREAMS = [("claude", "lead"), ("claude", "sub"), ("codex", "lead"), ("codex", "sub"), ("gemini", "sub"),
           ("claude", "builtin"), ("codex", "builtin"), ("deepseek", "sub"), ("other", "sub")]
STREAM_LABEL = {("claude", "lead"): "Claude · lead", ("claude", "sub"): "Claude · sub-agent",
                ("codex", "lead"): "Codex · lead", ("codex", "sub"): "Codex · sub-agent",
                ("gemini", "sub"): "Gemini · sub-agent",
                ("claude", "builtin"): "Claude · built-in sub-agent", ("codex", "builtin"): "Codex · built-in sub-agent",
                ("deepseek", "sub"): "DeepSeek · sub-agent (pay per token)",
                ("other", "sub"): "Other API providers · sub-agent (pay per token)"}
BASE_STREAMS = 4      # always shown; later ones only when they have data. Color = fixed slot per stream.
BUCKETS = [("input_tokens", "fresh input"), ("cache_write_tokens", "cache write"),
           ("cached_input_tokens", "cache read"), ("output_tokens", "output")]
CREDITS_PER_USD = 25


def _ae(p: Paths, agent: str, model: str, u: dict, ts: float | None = None) -> float:
    v = learn.price_usd(p, agent, model, u, ts=ts)
    return v or 0.0


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _soft_note(st: dict | None) -> str:
    """J7: how often a probable verdict was later judged the other way (all time, not only this window)."""
    if not st or not st.get("rechecked"):
        return ""
    note = f" · {st['overturned']}/{st['rechecked']} probable overturned later"
    return note + ("" if st["learn"] else " — too many: they no longer teach routing")


MEASURED_URL = "https://github.com/SUPERD6/relayline/blob/main/docs/measured.md"
MEASURED_NOTE = f"model estimate; measured totals so far about even (rounds 1-5): {MEASURED_URL}"


# Fresh (uncached) input a sub-agent reads at start-up before it touches the task. Claude reports its start-up as
# cache writes and reads, so none of it is in fresh input. Codex reports no cache-write bucket: a run that starts a
# session read 20.5-21.6k fresh tokens for a tiny piece (docs/research/2026-10-25-warm-lanes.md), so ~20k of its fresh
# input is start-up. Gemini is not measured; it is assumed to be like Codex (a lower estimate, not a higher one).
STARTUP_FRESH = {"claude": 0, "codex": 20000, "gemini": 20000}


def task_sized(u: dict, agent: str | None = None) -> dict:
    """The part of a sub-agent's usage the lead would also spend doing the task itself: fresh input and output,
    minus the agent's own start-up. Cache reads and cache writes are the sub-agent's start-up and its re-reading of it
    (~93k tokens a run in round 2: not a one-off start-up but the fixed prefix, Codex ~18-25k and Claude ~13-15k,
    re-sent on each of ~5 requests); Codex also reads ~20k start-up tokens fresh (STARTUP_FRESH). The lead, already
    running, would not pay for any of it again. Unknown agents are treated like Codex."""
    fresh = u.get("input_tokens", 0) or 0
    startup = STARTUP_FRESH.get(agent or "", STARTUP_FRESH["codex"]) if agent is not None else 0
    return {"input_tokens": max(0, fresh - startup), "output_tokens": u.get("output_tokens", 0) or 0}


def collect(p: Paths, days: int = 30, include_lead: bool = True) -> dict:
    since = time.time() - days * 86400
    cfg = load_config(p)
    billing = ledger.billing_config(cfg)
    rows = [r for r in ledger.rows(p) if (r.get("ts") or 0) >= since]
    runs = [r for r in rows if not r.get("type")]
    verdicts = {r["run_id"]: r["ok"] for r in rows if r.get("type") == "verify"}      # the last one wins
    soft = {r["run_id"]: bool(r.get("soft")) for r in rows if r.get("type") == "verify"}
    reasons: dict[str, int] = {}
    for r in rows:
        if r.get("type") == "verify" and not r.get("ok") and r.get("reason"):
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    selfruns = [r for r in rows if r.get("type") == "selfrun"]
    sub_sessions = {s for r in ledger.rows(p) if not r.get("type") for s in r.get("sessions", [])}
    lead_ev, quota = usage.lead_events(since, sub_sessions, cfg) if include_lead else ([], [])

    events, quota_events = [], []
    for r in runs:
        model = (r.get("rungs") or ["::"])[-1].split(":")[1] if r.get("rungs") else "?"
        u = r.get("usage4") or {"input_tokens": r["usage"].get("input", 0) - r["usage"].get("cache_write", 0),
                                "cache_write_tokens": r["usage"].get("cache_write", 0),
                                "cached_input_tokens": r["usage"].get("cached", 0),
                                "output_tokens": r["usage"].get("output", 0)}
        ae = r.get("ae_usd")
        if ae is None:
            ae = _ae(p, r["to"], model, u, ts=r.get("ts"))
        by = r.get("ae_by_agent") or {}
        qby = r.get("quota_by_agent") or {r["to"]: ledger.row_quota(r)}
        quota_events.extend({"ts": r["ts"], "agent": ag, "role": "sub", "quota_units": units}
                            for ag, units in qby.items())
        if len(by) > 1:     # each agent's dollar share; preserve the existing run/token accounting
            for ag, v in by.items():
                events.append({"ts": r["ts"], "agent": ag, "role": "sub", "model": model, "ae": v, "run": r,
                               "quota_units": qby.get(ag, 0),
                               "usage": u if ag == r["to"] else {}})
            continue
        events.append({"ts": r["ts"], "agent": r["to"], "role": "sub", "model": model, "usage": u, "ae": ae,
                       "quota_units": ledger.row_quota(r), "run": r})
    for e in lead_ev:
        e["ae"] = _ae(p, e["agent"], e["model"], e["usage"], ts=e.get("ts"))
        events.append(e)
        quota_events.append(e)
    return {"since": since, "days": days, "events": events, "quota_events": quota_events,
            "runs": runs, "verdicts": verdicts, "soft": soft,
            "soft_trust": ledger.soft_trust(ledger.rows(p)), "reasons": reasons,
            "selfruns": selfruns, "quota": quota, "lead_models": cfg.get("lead", {}),
            "lead_seen": include_lead, "billing": {"mode": billing["mode"]}}


def _trial(p: Paths) -> dict | None:
    from . import trial
    try:
        s = trial.summarize(p)
    except Exception:  # noqa: BLE001 — the dashboard must render without it
        return None
    return s if s.get("trial") else None


def _bootstrap(values: list[float], n: int = 1000, seed: int = 7) -> tuple[float, float] | None:
    if len(values) < 3:
        return None
    rnd = random.Random(seed)
    sums = sorted(sum(rnd.choice(values) for _ in values) for _ in range(n))
    return sums[int(0.025 * n)], sums[int(0.975 * n) - 1]


def _stream(e: dict, cfg: dict) -> tuple[str, str]:
    """A sub-agent run on DeepSeek by any route (Claude Code, Codex, dsh) counts as DeepSeek; other pay-per-token
    providers (Kimi, GLM, ...) share one stream."""
    s = (e["agent"], e["role"])
    if s in STREAM_LABEL or e["role"] != "sub":
        return s
    from .agents import vendor
    return ("deepseek", "sub") if vendor(e["agent"], cfg) == "deepseek" else ("other", "sub")


def summarize(p: Paths, data: dict) -> dict:
    by_stream = {s: {"ae": 0.0, "quota_units": 0.0, "n": 0, **{k: 0 for k, _ in BUCKETS}} for s in STREAMS}
    by_day: dict[str, dict] = defaultdict(lambda: {s: 0.0 for s in STREAMS})
    quota_by_day: dict[str, dict] = defaultdict(lambda: {s: 0.0 for s in STREAMS})
    cfg = load_config(p)
    billing = ledger.billing_config(cfg)
    for e in data["events"]:
        s = _stream(e, cfg)
        if s not in by_stream:
            continue
        b = by_stream[s]
        b["ae"] += e["ae"]
        b["n"] += 1
        for k, _ in BUCKETS:
            b[k] += e["usage"].get(k, 0)
        by_day[_day(e["ts"])][s] += e["ae"]
    for e in data.get("quota_events", data["events"]):
        s = _stream(e, cfg)
        if s not in by_stream:
            continue
        units = e.get("quota_units")
        if units is None:
            units = ledger.quota_units(cfg, e["agent"], e.get("model") or "", e.get("usage") or {})
        by_stream[s]["quota_units"] += units
        quota_by_day[_day(e["ts"])][s] += units

    savings, uppers, run_rows = [], [], []
    done = verified_ok = 0
    for e in (x for x in data["events"] if x["role"] == "sub"):
        r = e["run"]
        verdict = data["verdicts"].get(r["run_id"])
        ok = verdict if verdict is not None else (r.get("status") == "done")
        done += bool(ok)
        verified_ok += bool(verdict)
        caller = r.get("caller")
        saving = None
        if caller in ("claude", "codex") and ok:      # a failed run saved nothing
            lead_model = data["lead_models"].get(caller, "")
            # the lead doing it itself pays for the task (what was read fresh and written), not for a second agent's
            # start-up and re-reading: pricing all of the sub-agent's tokens at the lead's price put the estimate at
            # several times the spend while measured totals were about even (PM review 2026-10-29)
            self_cost = learn.price_usd(p, caller, lead_model, task_sized(e["usage"], r["to"]))
            upper = learn.price_usd(p, caller, lead_model, e["usage"])
            bb = r.get("b") if r.get("b") is not None else 4
            overhead = learn.price_usd(p, caller, lead_model,
                                       {"input_tokens": 1500 + 1000 * bb, "output_tokens": 400}) or 0.0
            if self_cost is not None:
                saving = self_cost - e["ae"] - overhead
                savings.append(saving)
                uppers.append((upper or 0.0) - e["ae"] - overhead)
        run_rows.append({"run_id": r["run_id"], "day": _day(r["ts"]), "label": r.get("label") or "",
                         "task": r.get("task") or "", "caller": caller, "agent": r["to"],
                         "rungs": r.get("rungs") or [], "status": r.get("status"), "kind": r.get("kind"),
                         "verdict": verdict, "tokens": sum(e["usage"].values()), "ae": round(e["ae"], 5),
                         "quota_units": e.get("quota_units", ledger.row_quota(r)),
                         "saving": None if saving is None else round(saving, 5), "b": r.get("b")})

    tot_in = sum(by_stream[s][k] for s in STREAMS for k in ("input_tokens", "cache_write_tokens",
                                                             "cached_input_tokens"))
    cached = sum(by_stream[s]["cached_input_tokens"] for s in STREAMS)
    sub_ae = sum(by_stream[s]["ae"] for s in STREAMS if s[1] == "sub")
    lead_ae = sum(by_stream[s]["ae"] for s in STREAMS if s[1] == "lead")
    sub_units = sum(by_stream[s]["quota_units"] for s in STREAMS if s[1] == "sub")
    lead_units = sum(by_stream[s]["quota_units"] for s in STREAMS if s[1] == "lead")
    nsub = len(run_rows)
    # the lead's own turns (H10): every turn re-reads the whole conversation, so this is where most spend goes
    from .context import turn_tokens
    lead_turns = sorted((turn_tokens(e["usage"]), e["ae"]) for e in data["events"] if e["role"] == "lead")
    mid = lead_turns[len(lead_turns) // 2] if lead_turns else None
    # J5: what the same lead turns would have cost one model rung down (the switch itself is ignored here)
    from .leadcost import LADDER, _rung_of
    down_saving = 0.0
    for e in (x for x in data["events"] if x["role"] == "lead"):
        rung, ladder = _rung_of(e["agent"], e.get("model") or ""), LADDER.get(e["agent"], [])
        if rung and rung != ladder[-1]:
            lower = learn.price_usd(p, e["agent"], ladder[ladder.index(rung) + 1], e["usage"])
            if lower is not None:
                down_saving += e["ae"] - lower

    # A/B: measured self-runs vs delegated runs of similar difficulty
    ab = []
    buckets: dict[int, dict] = defaultdict(lambda: {"self": [], "delegated": []})
    for s in data["selfruns"]:
        if s.get("b") is not None:
            buckets[round(s["b"])]["self"].append(s.get("ae_usd") or 0.0)
    for rr in run_rows:
        if rr["b"] is not None:
            buckets[round(rr["b"])]["delegated"].append(rr["ae"])
    for b, v in sorted(buckets.items()):
        if v["self"]:
            ab.append({"b": b, "self_n": len(v["self"]), "delegated_n": len(v["delegated"]),
                       "self_mean": round(sum(v["self"]) / len(v["self"]), 5),
                       "delegated_mean": round(sum(v["delegated"]) / len(v["delegated"]), 5)
                       if v["delegated"] else None})

    # per-task cost: Claude Code's own sub-agents (one transcript = one task) vs ccx sub-agent runs
    per_task: dict[str, list[float]] = defaultdict(list)
    builtin: dict[tuple, float] = defaultdict(float)
    for e in data["events"]:
        if e["role"] == "builtin":
            builtin[(e["agent"], e["session"])] += e["ae"]
        elif e["role"] == "sub":
            per_task[f"ccx → {e['agent']}"].append(e["ae"])
    for (agent, _), v in builtin.items():
        per_task[f"{agent.capitalize()} built-in sub-agent"].append(v)
    compare = [{"kind": k, "tasks": len(v), "mean_ae": round(sum(v) / len(v), 5),
                "median_ae": round(sorted(v)[len(v) // 2], 5)} for k, v in sorted(per_task.items()) if v]

    quota = {}
    for q in sorted(data["quota"], key=lambda q: q["ts"]):
        quota[f"{q['agent']}:{q['window']}"] = q
    limit_hits = sum(1 for r in data["runs"] if r.get("kind") == "quota")
    tr = _trial(p)
    measured = tr and tr.get("enough") and tr.get("saving_per_task_usd") is not None
    # delegated runs that held up (a failed run saved nothing), the same rule as the model estimate above
    n_delegated = sum(1 for r in run_rows if (r["verdict"] if r["verdict"] is not None else r["status"] == "done"))

    return {
        "generated": time.strftime("%Y-%m-%d %H:%M"), "days": data["days"], "lead_seen": data["lead_seen"],
        "billing": {"mode": billing["mode"]},
        "totals": {"ae": round(sub_ae + lead_ae, 4), "sub_ae": round(sub_ae, 4), "lead_ae": round(lead_ae, 4),
                   "quota_units": round(sub_units + lead_units, 6),
                   "sub_quota_units": round(sub_units, 6), "lead_quota_units": round(lead_units, 6),
                   "quota_units_per_success": round(sub_units / done, 6) if done else None,
                   "codex_credits": round(sum(by_stream[s]["ae"] for s in STREAMS if s[0] == "codex")
                                          * CREDITS_PER_USD, 1),
                   "runs": nsub, "done_rate": round(done / nsub, 3) if nsub else None,
                   "verified": len([r for r in run_rows if r["verdict"] is not None
                                    and not data["soft"].get(r["run_id"])]),
                   "soft_verified": len([r for r in run_rows if data["soft"].get(r["run_id"])]),
                   "soft_trust": data.get("soft_trust"),
                   "reasons": data["reasons"],
                   "cps": round(sub_ae / done, 5) if done else None,
                   "cache_read_share": round(cached / tot_in, 3) if tot_in else None,
                   "saving": (round(tr["saving_per_task_usd"] * n_delegated, 4) if measured
                              else round(sum(savings), 4) if savings else None),
                   "saving_kind": "measured" if measured else "model",
                   "saving_ci95": ([round(x * n_delegated, 4) for x in tr["saving_ci95"]] if measured
                                   and tr.get("saving_ci95") else
                                   [round(x, 4) for x in (_bootstrap(savings) or ())] or None),
                   "saving_n": n_delegated if measured else len(savings),
                   # the old model (all sub-agent tokens at the lead's price), for comparison only: not a bound on a
                   # real saving, and left out when a trial measured one
                   "saving_old_model": round(sum(uppers), 4) if uppers and not measured else None,
                   "saving_note": None if measured else MEASURED_NOTE, "quota_stops": limit_hits,
                   "lead_turns": len(lead_turns), "lead_turn_tokens_median": mid[0] if mid else None,
                   "lead_turn_ae_median": round(mid[1], 4) if mid else None,
                   "lead_one_rung_down_saving": round(down_saving, 2) if lead_turns else None},
        "streams": [{"agent": s[0], "role": s[1], "label": STREAM_LABEL[s], "ae": round(v["ae"], 5),
                     "quota_units": round(v["quota_units"], 6),
                     "events": v["n"], **{k: v[k] for k, _ in BUCKETS}} for s, v in by_stream.items()],
        "days_series": [{"day": d, **{f"{a}:{r}": round(v[(a, r)], 5) for a, r in STREAMS}}
                        for d, v in sorted(by_day.items())],
        "quota_days_series": [{"day": d, **{f"{a}:{r}": round(v[(a, r)], 6) for a, r in STREAMS}}
                              for d, v in sorted(quota_by_day.items())],
        "runs": sorted(run_rows, key=lambda r: r["run_id"], reverse=True),
        "ab": ab, "trial": tr, "quota": list(quota.values()), "compare": compare,
        "accuracy": accuracy.summary(p, include_evals=bool(data.get("include_evals"))),
    }


# ------------------------------------------------------------------ HTML
CSS = """
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--good:#006300;--bad:#d03b3b;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#9a6a2f;--s9:#5f6b7a;--t1:#e87ba4;--t2:#008300;--t3:#6250d6;--t4:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
--surface-1:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink-2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--good:#0ca30c;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#c4955c;--s9:#98a2b0;
--t1:#d55181;--t2:#008300;--t3:#9085e9;--t4:#e66767}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-1:#1a1a19;--page:#0d0d0d;--ink:#f0efec;
--ink-2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--good:#0ca30c;--s1:#3987e5;
--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#c4955c;--s9:#98a2b0;--t1:#d55181;--t2:#008300;--t3:#9085e9;--t4:#e66767}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.viz-root{background:var(--page);color:var(--ink);min-height:100vh;padding:24px 16px 48px}
.chart{overflow-x:auto}.chart svg{min-width:620px}
.wrap{max-width:1080px;margin:0 auto}h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:0 0 12px}
.sub{color:var(--ink-2);margin:0 0 20px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
gap:12px;margin-bottom:16px}.tile,.card{background:var(--surface-1);border:1px solid var(--ring);border-radius:12px;padding:14px 16px}
.tile .k{color:var(--ink-2);font-size:12px}.tile .v{font-size:24px;font-weight:600;margin-top:2px}
.tile .n{color:var(--muted);font-size:12px;margin-top:2px}.card{margin-bottom:16px;overflow:hidden}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin:0 0 8px;color:var(--ink-2);font-size:12px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
svg{display:block;width:100%;height:auto}svg text{fill:var(--muted);font-size:11px}
.tbl{width:100%;border-collapse:collapse;font-size:12.5px}.tbl th{text-align:left;color:var(--ink-2);font-weight:500;
border-bottom:1px solid var(--grid);padding:6px 8px}.tbl td{border-bottom:1px solid var(--grid);padding:6px 8px;
font-variant-numeric:tabular-nums}.tbl td.r,.tbl th.r{text-align:right}.scroll{overflow-x:auto}
.good{color:var(--good)}.bad{color:var(--bad)}.note{color:var(--muted);font-size:12px;margin-top:8px}
#tip{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--ink);border:1px solid var(--ring);
border-radius:8px;padding:6px 8px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.12);display:none;z-index:9}
details summary{cursor:pointer;color:var(--ink-2);font-size:12px;margin-top:8px}
"""

JS = """
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{
 el.addEventListener('mousemove',e=>{tip.textContent=el.dataset.tip;tip.style.display='block';
  tip.style.left=Math.min(e.clientX+12,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=(e.clientY+12)+'px'});
 el.addEventListener('mouseleave',()=>tip.style.display='none');});
"""


def _usd(v) -> str:
    if v is None:
        return "–"
    if v == 0:
        return "$0"
    sign, v = ("-", -v) if v < 0 else ("", v)          # -$0.14, not $-0.14
    return sign + (f"${v:,.4f}" if v < 1 else f"${v:,.2f}")


def _num(v) -> str:
    return "–" if v is None else f"{v:,}"


def _esc(s) -> str:
    return html.escape(str(s))


def _shown(days: list[dict]) -> list[int]:
    return [i for i, (a, r) in enumerate(STREAMS)
            if i < BASE_STREAMS or any(d.get(f"{a}:{r}", 0) for d in days)]


def _daily_chart(days: list[dict], subscription: bool = False) -> str:
    if not days:
        return '<p class="note">No usage in this window yet.</p>'
    W, H, L, B, T = 960, 240, 56, 28, 10
    idx = _shown(days)
    keys = [f"{STREAMS[i][0]}:{STREAMS[i][1]}" for i in idx]
    colors = [f"var(--s{i + 1})" for i in idx]
    peak = max(sum(d[k] for k in keys) for d in days) or 1
    step = (W - L - 8) / len(days)
    bw = max(3, min(28, step * 0.62))
    fmt = _num if subscription else _usd
    label = "Quota units" if subscription else "API-equivalent dollars"
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{label} per day by stream">']
    for i in range(5):
        y = T + (H - T - B) * i / 4
        out.append(f'<line x1="{L}" x2="{W - 8}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
        out.append(f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end">{fmt(peak * (1 - i / 4))}</text>')
    out.append(f'<line x1="{L}" x2="{W - 8}" y1="{H - B}" y2="{H - B}" stroke="var(--axis)" stroke-width="1"/>')
    every = max(1, len(days) // 8)
    for i, d in enumerate(days):
        x = L + step * i + (step - bw) / 2
        y0 = H - B
        segs = [(k, c, d[k]) for k, c in zip(keys, colors) if d[k] > 0]
        for j, (k, c, v) in enumerate(segs):
            h = (H - T - B) * v / peak
            gap = 2 if j < len(segs) - 1 else 0
            top = j == len(segs) - 1
            a, r = k.split(":")
            label = STREAM_LABEL[(a, r)]
            path_h = max(h - gap, 0.5)
            if top and path_h > 4:
                rr = min(4, bw / 2)
                yt = y0 - h
                out.append(f'<path d="M{x:.1f},{y0 - gap:.1f} V{yt + rr:.1f} Q{x:.1f},{yt:.1f} {x + rr:.1f},{yt:.1f} '
                           f'H{x + bw - rr:.1f} Q{x + bw:.1f},{yt:.1f} {x + bw:.1f},{yt + rr:.1f} V{y0 - gap:.1f} Z" '
                           f'fill="{c}" data-tip="{d["day"]} · {label}: {fmt(v)}"/>')
            else:
                out.append(f'<rect x="{x:.1f}" y="{y0 - h:.1f}" width="{bw:.1f}" height="{path_h:.1f}" fill="{c}" '
                           f'data-tip="{d["day"]} · {label}: {fmt(v)}"/>')
            y0 -= h
        if i % every == 0:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{H - 8}" text-anchor="middle">{d["day"][5:]}</text>')
    out.append("</svg>")
    return "".join(out)


def _bucket_chart(streams: list[dict]) -> str:
    rows = [s for s in streams if any(s[k] for k, _ in BUCKETS)]
    if not rows:
        return '<p class="note">No tokens recorded yet.</p>'
    colors = ["var(--t1)", "var(--t2)", "var(--t3)", "var(--t4)"]
    W, rowh, L = 960, 34, 150
    H = rowh * len(rows) + 10
    peak = max(sum(s[k] for k, _ in BUCKETS) for s in rows) or 1
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Tokens by type for each stream">']
    for i, s in enumerate(rows):
        y = 6 + i * rowh
        out.append(f'<text x="{L - 10}" y="{y + 15}" text-anchor="end" style="fill:var(--ink-2)">{_esc(s["label"])}</text>')
        x = L
        segs = [(k, n, c) for (k, n), c in zip(BUCKETS, colors) if s[k] > 0]
        for j, (k, n, c) in enumerate(segs):
            w = (W - L - 70) * s[k] / peak
            gap = 2 if j < len(segs) - 1 else 0
            out.append(f'<rect x="{x:.1f}" y="{y + 4}" width="{max(w - gap, 0.5):.1f}" height="16" rx="{4 if j == len(segs) - 1 else 0}" '
                       f'fill="{c}" data-tip="{s["label"]} · {n}: {s[k]:,} tokens"/>')
            x += w
        out.append(f'<text x="{x + 6:.1f}" y="{y + 16}" style="fill:var(--ink-2)">{sum(s[k] for k, _ in BUCKETS):,}</text>')
    out.append("</svg>")
    return "".join(out)


def render_html(s: dict) -> str:
    t = s["totals"]
    subscription = (s.get("billing") or {}).get("mode") == "subscription"
    days = s["quota_days_series"] if subscription else s["days_series"]
    ci = t.get("saving_ci95")
    saving_note = (f"95% CI {_usd(ci[0])} … {_usd(ci[1])} · n={t['saving_n']}" if ci else
                   f"n={t['saving_n']} (CI needs ≥3 runs)")
    measured = t.get("saving_kind") == "measured"
    saving_note += (" · measured by ccx trial (per task × delegated runs)" if measured else
                    " · a model, not measured; measured totals so far about even (docs/measured.md). The model: the "
                    "task-sized part of the sub-agent's tokens (fresh input + output, minus its start-up) at the lead's price"
                    + (f"; the old model (all its tokens at the lead's price, start-up included) gave "
                       f"{_usd(t['saving_old_model'])}" if t.get("saving_old_model") is not None else "")
                    + ". Measured (H11): what the lead saves is the requests it doesn't make — about one per small "
                    "task, only when it trusts ccx's check. Measure yours with `ccx trial start`")
    tiles = [
        ("Total spend (AE$)", _usd(t["ae"]), f"last {s['days']} days · lead {_usd(t['lead_ae'])}"
         if s["lead_seen"] else f"last {s['days']} days · sub-agents only"),
        ("Sub-agent spend", _usd(t["sub_ae"]), f"{t['runs']} run{'' if t['runs'] == 1 else 's'} · cost/success {_usd(t['cps'])}"),
        ("Success rate", "–" if t["done_rate"] is None else f"{t['done_rate'] * 100:.0f}%",
         f"{t['verified']} judged by you or the lead · {t.get('soft_verified', 0)} probable (auto)"
         + _soft_note(t.get("soft_trust"))),
        ("Lead cost per turn", "–" if not t.get("lead_turn_tokens_median") else
         f"≈{t['lead_turn_tokens_median'] / 1000:,.0f}k tokens",
         f"median of {t.get('lead_turns', 0)} turns · ≈ {_usd(t.get('lead_turn_ae_median'))} a turn · shorter "
         f"conversations cost less (`ccx lead`)"
         + (f" · estimate: one model rung down would have cost {_usd(t['lead_one_rung_down_saving'])} less "
            f"(`ccx lead --suggest`)" if t.get("lead_one_rung_down_saving") else "")),
        ("Cache-read share", "–" if t["cache_read_share"] is None else f"{t['cache_read_share'] * 100:.0f}%",
         "of all input tokens"),
        ("Codex credits", f"{t['codex_credits']:,}", f"AE$ × {CREDITS_PER_USD} · quota stops {t['quota_stops']}"),
        # after what was spent: a saving only when `ccx trial` measured it. Until then no model figure is shown
        # (P1-4); `ccx stats --summary` still carries the labelled model for scripts.
        ("Saving (measured)", _usd(t["saving"]), saving_note) if measured else
        ("Saving", "not measured yet", "`ccx trial start` measures it (the lead does a share of the tasks itself); "
         "measured totals so far about even (docs/measured.md)"),
    ]
    if subscription:
        tiles[:2] = [
            ("Total usage (quota units)", _num(t["quota_units"]),
             f"last {s['days']} days · API-equivalent USD {_usd(t['ae'])}"),
            ("Sub-agent usage (quota units)", _num(t["sub_quota_units"]),
             f"{t['runs']} runs · units/success {_num(t['quota_units_per_success'])} · AE$ {_usd(t['sub_ae'])}"),
        ]
    tiles_html = "".join(f'<div class="tile"><div class="k">{_esc(k)}</div><div class="v">{_esc(v)}</div>'
                         f'<div class="n">{_esc(n)}</div></div>' for k, v, n in tiles)
    shown = _shown(days)
    legend1 = "".join(f'<span><i style="background:var(--s{i + 1})"></i>{_esc(STREAM_LABEL[STREAMS[i]])}</span>'
                      for i in shown)
    legend2 = "".join(f'<span><i style="background:var(--t{i + 1})"></i>{_esc(n)}</span>'
                      for i, (_, n) in enumerate(BUCKETS))
    day_rows = "".join(f"<tr><td>{d['day']}</td>" + "".join(
        f'<td class="r">{(_num if subscription else _usd)(d[f"{STREAMS[i][0]}:{STREAMS[i][1]}"])}</td>'
        for i in shown) + "</tr>" for d in days)
    quota_head = '<th class="r">quota units</th>' if subscription else ""
    stream_rows = "".join(
        f"<tr><td>{_esc(x['label'])}</td>" + "".join(f'<td class="r">{_num(x[k])}</td>' for k, _ in BUCKETS)
        + (f'<td class="r">{_num(x["quota_units"])}</td>' if subscription else "")
        + f'<td class="r">{_usd(x["ae"])}</td></tr>' for x in s["streams"] if x["events"])

    def verdict(r):
        if r["verdict"] is True:
            return '<span class="good">✓ verified</span>'
        if r["verdict"] is False:
            return '<span class="bad">✗ rejected</span>'
        return _esc(r["status"] or "")
    run_rows = "".join(
        f"<tr><td>{r['day']}</td><td>{_esc(r['label'] or r['task'] or r['run_id'])}</td><td>{_esc(r['caller'])} → "
        f"{_esc(r['agent'])}</td><td>{_esc(' → '.join(x.split(':', 1)[1] for x in r['rungs'] if x))}</td>"
        f"<td>{verdict(r)}{'' if r['kind'] in (None, 'ok') else ' · ' + _esc(r['kind'])}</td>"
        f'<td class="r">{_num(r["tokens"])}</td>'
        + (f'<td class="r">{_num(r["quota_units"])}</td>' if subscription else "")
        + f'<td class="r">{_usd(r["ae"])}</td></tr>' for r in s["runs"][:200])
    ab_html = ""
    if s["ab"]:
        ab_html = ('<div class="card"><h2>A/B check — lead did it itself vs delegated (same difficulty b)</h2>'
                   '<div class="scroll"><table class="tbl"><tr><th>b</th><th class="r">self-runs</th>'
                   '<th class="r">mean AE$ self</th><th class="r">delegated runs</th><th class="r">mean AE$ delegated</th></tr>'
                   + "".join(f'<tr><td>{a["b"]}</td><td class="r">{a["self_n"]}</td><td class="r">{_usd(a["self_mean"])}</td>'
                             f'<td class="r">{a["delegated_n"]}</td><td class="r">{_usd(a["delegated_mean"])}</td></tr>'
                             for a in s["ab"])
                   + '</table></div><p class="note">Measured samples from the runs the lead did itself (`ab_self_rate`); '
                     'a few runs per difficulty are noise, `ccx trial` is the measurement.</p></div>')
    tr = s.get("trial")
    if tr:
        a, d = tr["arms"]["self"], tr["arms"]["delegated"]
        rows_t = [("tasks", str(a["n"]), str(d["n"])),
                  ("lead tokens per task", _num(a["lead_tokens_mean"]), _num(d["lead_tokens_mean"])),
                  ("lead AE$ per task", _usd(a["lead_usd_mean"]), _usd(d["lead_usd_mean"])),
                  ("sub-agent AE$ per task", _usd(a["sub_usd_mean"]), _usd(d["sub_usd_mean"])),
                  ("total AE$ per task", _usd(a["total_usd_mean"]), _usd(d["total_usd_mean"])),
                  ("minutes per task", _esc(a["minutes_mean"]), _esc(d["minutes_mean"])),
                  ("held up", "–" if a["ok_rate"] is None else f'{a["ok_rate"]:.0%}',
                   "–" if d["ok_rate"] is None else f'{d["ok_rate"]:.0%}')]
        ab_html += (f'<div class="card"><h2>Formal comparison {_esc(tr["trial"]["id"])} — lead itself vs delegated'
                    f'{"" if not tr["running"] else " (running)"}{" (void)" if tr.get("void") else ""}</h2>'
                    '<div class="scroll"><table class="tbl"><tr><th></th>'
                    '<th class="r">lead did it itself</th><th class="r">delegated with ccx</th></tr>'
                    + "".join(f'<tr><td>{n}</td><td class="r">{x}</td><td class="r">{y}</td></tr>' for n, x, y in rows_t)
                    + f'</table></div><p class="note">{_esc(tr.get("note") or "")} Both halves measure the lead '
                      'conversation in the task window; delegated runs add the sub-agent and 10 minutes for checking '
                      'the result.</p></div>')
    cmp_html = ""
    if len(s.get("compare", [])) > 1:
        cmp_html = ('<div class="card"><h2>Cost per task: built-in sub-agents vs ccx sub-agents</h2>'
                    '<div class="scroll"><table class="tbl"><tr><th>who did the sub-task</th><th class="r">tasks</th>'
                    '<th class="r">mean AE$</th><th class="r">median AE$</th></tr>' + "".join(
                        f'<tr><td>{_esc(c["kind"])}</td><td class="r">{c["tasks"]}</td><td class="r">{_usd(c["mean_ae"])}</td>'
                        f'<td class="r">{_usd(c["median_ae"])}</td></tr>' for c in s["compare"])
                    + '</table></div><p class="note">Built-in sub-agents spend the lead\'s own quota; ccx sub-agents spend '
                      'the other tool\'s quota. Compare like with like: similar tasks, same period.</p></div>')
    quota_html = ""
    if s["quota"]:
        quota_html = ('<div class="card"><h2>Quota windows (latest reading)</h2><table class="tbl"><tr><th>agent</th>'
                      '<th>window</th><th class="r">used</th></tr>' + "".join(
                          f'<tr><td>{_esc(q["agent"])}</td><td>{_esc(q["window"])} ({_esc(q.get("window_minutes") or "?")} min)'
                          f'</td><td class="r">{q["used_percent"]:.0f}%</td></tr>' for q in s["quota"]) + "</table></div>")
    lead_note = ("" if s["lead_seen"] else
                 '<p class="note">Lead-side usage not read (run with transcripts available to include it).</p>')
    basis = ("quota units are a configured token proxy, not remaining subscription quota; secondary amounts are "
             "API-equivalent USD (AE$)" if subscription else
             "amounts are API-equivalent USD (AE$), not your subscription bill")
    day_title = "Quota units per day, by who spent them" if subscription else "Spend per day, by who spent it"
    empty_run = '<tr><td colspan="8">No runs yet.</td></tr>' if subscription else '<tr><td colspan="7">No runs yet.</td></tr>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ccx Usage Dashboard</title>
<style>{CSS}</style></head><body><div class="viz-root"><div class="wrap">
<h1>Token and quota usage</h1><p class="sub">Claude Code ⇄ Codex ⇄ DeepSeek via ccx · generated {s['generated']} ·
last {s['days']} days · {basis}</p>
<div class="tiles">{tiles_html}</div>
<div class="card"><h2>{day_title}</h2><div class="legend">{legend1}</div><div class="chart">{_daily_chart(days, subscription)}</div>
<details><summary>Table view</summary><div class="scroll"><table class="tbl"><tr><th>day</th>
{''.join(f'<th class="r">{_esc(STREAM_LABEL[STREAMS[i]])}</th>' for i in shown)}</tr>{day_rows}</table></div></details>{lead_note}</div>
<div class="card"><h2>Tokens by type</h2><div class="legend">{legend2}</div><div class="chart">{_bucket_chart(s['streams'])}</div>
<details open><summary>Table view</summary><div class="scroll"><table class="tbl"><tr><th>stream</th>
{''.join(f'<th class="r">{_esc(n)}</th>' for _, n in BUCKETS)}{quota_head}<th class="r">AE$</th></tr>{stream_rows}</table></div></details>
<p class="note">Cache reads bill at about 0.1× input; Claude's headless start-up is written to a 1-hour cache (2× input) on
first use, so delegations close together are cheaper.</p></div>
{ab_html}{cmp_html}{quota_html}{accuracy.card_html(s.get('accuracy'))}
<div class="card"><h2>Delegated runs</h2><div class="scroll"><table class="tbl"><tr><th>day</th><th>task</th><th>who</th>
<th>model → escalation</th><th>result</th><th class="r">tokens</th>{quota_head}<th class="r">AE$</th></tr>
{run_rows or empty_run}</table></div>
<p class="note">What each run cost. No per-run saving is shown: a saving is only reported once `ccx trial` has
measured one (measured totals so far were about even, docs/measured.md).</p></div>
</div></div><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>"""


def write(p: Paths, days: int = 30, out: Path | None = None, include_lead: bool = True,
          include_evals: bool = False) -> dict:
    s = summarize(p, {**collect(p, days, include_lead), "include_evals": include_evals})
    out = out or p.state / "report" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(s), encoding="utf-8")
    (out.parent / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"report": str(out), "summary": str(out.parent / "summary.json"), "totals": s["totals"],
            "billing": s["billing"]}


def publish(p: Paths, report_dir: Path) -> dict:
    """Copy the dashboard into the user's private usage repo (report.publish_dir) and commit + push.
    Only numbers, run ids and labels are published — never prompts or file contents."""
    cfg = load_config(p)
    target = (cfg.get("report") or {}).get("publish_dir") or ""
    if not target:
        raise ValueError("set the target first: ccx config set report.publish_dir <local clone of your private repo>")
    repo = Path(target).expanduser()
    if not (repo / ".git").exists():
        raise ValueError(f"{repo} is not a git clone")
    dest = repo / "usage"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "summary.json"):
        shutil.copy2(report_dir / name, dest / name)
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True,  # noqa: E731
                                    encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    git("add", "usage/index.html", "usage/summary.json")
    c = git("commit", "-m", f"usage report {time.strftime('%Y-%m-%d %H:%M')}")
    pushed = git("push").returncode == 0 if c.returncode == 0 else False
    return {"published": str(dest), "committed": c.returncode == 0, "pushed": pushed}
