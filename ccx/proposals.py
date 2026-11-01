"""The lead offers to delegate (proposal H12): before a large, checkable piece of work it asks `ccx propose` what
delegating would cost and how likely it is to work, offers it in one line when it pays, and delegates only on the
person's yes. Each step leaves a ledger row, so a week of real use shows the chain proposed -> agreed -> delegated
-> judged, and how many real (non-evaluation) runs got a verdict at all."""
from __future__ import annotations

import time
import uuid

from .config import Paths


def new(p: Paths, route: dict, text: str, lead_session: str | None) -> dict:
    from . import ledger
    c = route.get("choice") or {}
    sv = route.get("self_vs_delegate") or {}
    opt = {o["way"]: o for o in c.get("options", [])}
    row = {"type": "proposal", "proposal": time.strftime("p%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
           "ts": time.time(), "b": route.get("b"), "kind": route.get("kind"), "rung": route.get("rung"),
           "recommend": c.get("recommend") or sv.get("recommend"),
           "self_usd": (opt.get("self") or {}).get("usd", sv.get("self_usd")),
           "delegate_usd": (opt.get("delegate") or {}).get("usd", sv.get("delegate_usd")),
           "p": (opt.get("delegate") or {}).get("p", route.get("chain_p")),
           "lead_ctx_tokens": c.get("lead_ctx_tokens", sv.get("lead_ctx_tokens")),
           "lead_session": lead_session, "task": text[:200]}
    tp = route.get("policy") or {}
    if tp:                       # the whole-workflow tier: its size band, the estimate it used, the mode it planned
        row.update(policy_tier=tp.get("tier"), band=tp.get("band"), planned_mode=tp.get("mode"),
                   tier_explicit=bool(tp.get("explicit")), estimate_minutes=(tp.get("signals") or {}).get("minutes"),
                   estimate_files=(tp.get("signals") or {}).get("files"))
        # a tier the person picked decided this one: no offer, nobody is asked (left out of the H12 chain in stats)
        if tp.get("explicit") and tp.get("mode") in ("ccx2", "direct") and route.get("routing_mode") != "off":
            row["preauthorized"] = True
    if route.get("routing_mode") == "off":     # routing.mode=off said do it yourself: nothing was offered
        row["routing_mode"] = "off"
    ledger.append_event(p, row)
    return row


def get(p: Paths, proposal: str) -> dict | None:
    """The proposal row, or None."""
    from . import ledger
    return next((r for r in ledger.rows(p) if r.get("type") == "proposal" and r.get("proposal") == proposal), None)


_row = get


def answered(p: Paths, proposal: str) -> bool:
    """Has this proposal an answer yet (a yes or no, or the run of a pre-authorised one)?"""
    from . import ledger
    return any(r.get("type") == "proposal_answer" and r.get("proposal") == proposal for r in ledger.rows(p))


def _claim_file(p: Paths, proposal: str):
    return p.state / "proposals" / f"{proposal}.used"


def claimed(p: Paths, proposal: str) -> bool:
    """Has a run already taken this pre-authorised proposal (claim())?"""
    return _claim_file(p, proposal).exists()


def claim(p: Paths, proposal: str) -> bool:
    """Take a pre-authorised proposal for one run, atomically: True for the first caller only. An exclusive file
    create, so two runs started together (two `--bg` children, a `q run` refill and a manual run) cannot both pass
    a read-then-write check of the ledger."""
    import os
    f = _claim_file(p, proposal)
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"{time.time()} {os.getpid()}\n")
    return True


def preauthorized(p: Paths, proposal: str) -> dict | None:
    """The tier (as route["policy"]) when the person's picked tier pre-authorised this proposal, else None. Whether
    a run may still use it (once, at its size) is ccx run's check."""
    r = _row(p, proposal)
    if not r or not r.get("preauthorized"):
        return None
    return {"tier": r.get("policy_tier"), "band": r.get("band"), "mode": r.get("planned_mode"), "explicit": True,
            "signals": {"minutes": r.get("estimate_minutes"), "files": r.get("estimate_files")},
            "from_proposal": proposal}


def answer(p: Paths, proposal: str, yes: bool, source: str = "person") -> dict:
    """source: "person" (a yes or no to the offer), "tier" (the run of a proposal the picked tier pre-authorised,
    written when it starts) or "lead" (a proposal the picked tier planned self, sent out by the lead anyway)."""
    from . import ledger
    prop = _row(p, proposal)
    if not prop:
        raise ValueError(f"no proposal {proposal!r} (`ccx propose` prints its id)")
    # what actually happened: a no -> the lead does it itself; a yes -> ccx, unchecked when the tier planned direct
    row = {"type": "proposal_answer", "proposal": proposal, "yes": yes, "ts": time.time(),
           "actual_mode": ("direct" if prop.get("planned_mode") == "direct" else "ccx2") if yes else "self"}
    if source != "person":
        row["source"] = source
    ledger.append_event(p, row)
    return row


def tier_decided(r: dict) -> bool:
    """A proposal the person's picked tier decided (pre-authorised, or planned self): never offered to the person.
    A picked tier whose plan failed (no planned_mode) fell back to offer-first and stays an offer."""
    return bool(r.get("preauthorized") or (r.get("tier_explicit") and r.get("planned_mode") == "self"))


def stats(p: Paths, days: float = 7.0, now: float | None = None) -> dict:
    """Over the last `days`: the proposal chain, and the share of real runs that got a verdict (from the lead or
    the person; probable verdicts ccx gave by itself are counted apart)."""
    from . import ledger
    now = now or time.time()
    since = now - days * 86400
    rows = ledger.rows(p)
    runs_by = ledger.runs_by_id(rows)
    runs = [r for r in runs_by.values() if float(r.get("ts") or 0) >= since and not ledger.is_eval(r)]
    verdicts: dict[str, dict] = {}
    for r in rows:
        if r.get("type") == "verify" and r.get("run_id") in runs_by:
            verdicts[r["run_id"]] = r                                  # the last one wins
    # the H12 chain counts offers only: a proposal a picked tier decided (preauthorized, or tier_explicit and
    # planned self) was never put to the person
    in_window = [r for r in rows if r.get("type") == "proposal" and float(r.get("ts") or 0) >= since]
    props = {r["proposal"]: r for r in in_window if not tier_decided(r)}
    answers = {r["proposal"]: r["yes"] for r in rows if r.get("type") == "proposal_answer" and r["proposal"] in props
               and r.get("source", "person") == "person"}
    sent = [r for r in runs if r.get("proposal") in props]
    judged = [r for r in sent if r["run_id"] in verdicts and not verdicts[r["run_id"]].get("soft")]

    def share(a: int, b: int):
        return round(a / b, 3) if b else None
    by_lead = [r for r in runs if r["run_id"] in verdicts and not verdicts[r["run_id"]].get("soft")]
    soft = [r for r in runs if r["run_id"] in verdicts and verdicts[r["run_id"]].get("soft")]
    return {"days": days, "since": since,
            "proposals": {"proposed": len(props), "agreed": sum(v for v in answers.values()),
                          "declined": sum(not v for v in answers.values()),
                          "unanswered": len(props) - len(answers), "delegated": len({r["proposal"] for r in sent}),
                          "judged": len(judged), "held_up": sum(bool(verdicts[r["run_id"]].get("ok")) for r in judged),
                          "chain_complete_share": share(len({r["proposal"] for r in judged}), len(props)),
                          "tier_decided": len(in_window) - len(props)},
            "verdicts": {"real_runs": len(runs), "judged_by_lead_or_person": len(by_lead),
                         "probable_only": len(soft), "coverage": share(len(by_lead), len(runs)),
                         "coverage_incl_probable": share(len(by_lead) + len(soft), len(runs)),
                         "target": 0.6},
            "note": "real runs leave out evaluation runs (eval-* labels, --no-ab, probes: ledger.is_eval)"}
