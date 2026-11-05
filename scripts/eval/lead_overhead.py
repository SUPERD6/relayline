"""Audit Stage 3 lead overhead from explicit result/stream paths; no CLI or model calls.

Usage: lead_overhead.py --results FILE --artifacts DIR [--out JSON]
Text estimates use UTF-8 text characters / 4, not a vendor tokenizer. Usage
counters are measured; estimated components and the residual are labelled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean, median

INPUT = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def messages(events):
    out = {}
    for e in events:
        if e.get("type") == "assistant" and not e.get("parent_tool_use_id"):
            m = e.get("message") or {}
            if m.get("id"):
                out[m["id"]] = m
    return list(out.values())


def tokens(m):
    return sum(int((m.get("usage") or {}).get(k) or 0) for k in (*INPUT, "output_tokens"))


def stream(row, root):
    s = row["streams"]
    path = (root / s["run"] / s["dir"] / s["path"] / "lead.jsonl").resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("stream path escapes artifact directory")
    raw = path.read_bytes()
    expected = next(f["sha256"] for f in s["files"] if f["file"] == "lead.jsonl")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("stream hash mismatch")
    return [json.loads(s) for s in raw.decode("utf-8").splitlines() if s.strip()]


def guidance_estimate(first_delta, self_requests, self_usd, ideal_ratio, small_fraction):
    import r5
    task = r5.tasks_fresh2.T[0]  # exercise formatting only; no solution or outcome
    texts = {a: r5.unit_how({"arm": a, "label": "L"}, task) for a in ("self", "ccx2cand", "ccx3cand")}
    sizes = {a: {"chars": len(s), "words": len(s.split()), "chars_div_4": len(s) / 4} for a, s in texts.items()}
    old_extra = len(texts["ccx2cand"]) - len(texts["self"])
    new_extra = len(texts["ccx3cand"]) - len(texts["self"])
    predicted_extra = first_delta * new_extra / old_extra
    ratios = {}
    for name, write_price in (("5_minute_write", 2.5), ("1_hour_write", 4.0)):
        cost = predicted_extra * (write_price + (self_requests - 1) * 0.2) / 1e6
        ratios[name] = ideal_ratio + small_fraction * cost / self_usd
    return {"text": sizes, "estimated_extra_context_per_self_request": predicted_extra,
            "illustrative_cost_ratio_to_self": ratios,
            "assumptions": "Scale observed first-context delta by guidance character-length ratio. "
                           "Small tasks otherwise exactly match self; 4 delegations unchanged. Added input written "
                           "once then cache-read at $0.20/M; writes $2.50/M or $4/M (r5 pricing assumptions). "
                           "No implementation, cache-placement, routing or quality changes. Not measured savings."}


def analyze(rows, artifacts):
    selected = [r for r in rows if r.get("arm") in ("self", "ccx2cand")]
    streams = {id(r): stream(r, artifacts) for r in selected}
    groups = {}
    for arm in ("self", "ccx2cand"):
        rs = [r for r in selected if r["arm"] == arm]
        groups[arm] = {"n": len(rs), **{k: {"mean": mean(r[k] for r in rs), "median": median(r[k] for r in rs)}
                                      for k in ("lead_requests", "lead_tokens", "usd")},
                       "stream_tokens": sum(sum(tokens(m) for m in messages(streams[id(r)])) for r in rs)}
    paired = []
    by_task = {(r["task"], r["arm"]): r for r in selected}
    for r in selected:
        if r["arm"] != "ccx2cand" or not r.get("small_self_run", {}).get("applied"):
            continue
        baseline = by_task[(r["task"], "self")]
        ev = streams[id(r)]
        ms, bs = messages(ev), messages(streams[id(baseline)])
        # The issuing request is observed. Its whole context is charged to the
        # avoidable decision call, so do not charge that prompt a second time.
        gate = [(i, m, c) for i, m in enumerate(ms) for c in m.get("content", [])
                if c.get("type") == "tool_use" and " run " in str(c.get("input"))]
        if len(gate) != 1:
            raise ValueError("expected one small_self decision call")
        i, m, c = gate[0]
        replies = [c2 for e in ev if e.get("type") == "user"
                   for c2 in ((e.get("message") or {}).get("content") or [])
                   if isinstance(c2, dict) and c2.get("tool_use_id") == c.get("id")]
        reply = "".join(str(x.get("content") or "") for x in replies)
        command = str((c.get("input") or {}).get("command") or "")
        remaining = len(ms) - i - 1
        first_delta = sum((ms[0].get("usage") or {}).get(k, 0) - (bs[0].get("usage") or {}).get(k, 0) for k in INPUT)
        replay = (len(command) + len(reply)) / 4 * remaining
        prompt = first_delta * (len(ms) - 1)
        delta = sum(map(tokens, ms)) - sum(map(tokens, bs))
        paired.append({"task": r["task"], "clean": r.get("env_clean") is True,
                       "delta_tokens": delta, "delta_requests": len(ms) - len(bs),
                       "decision_request_tokens_measured": tokens(m),
                       "first_request_context_delta_measured": first_delta,
                       "prompt_repeated_estimate": prompt,
                       "brief_command_chars": len(command), "decision_reply_chars": len(reply),
                       "brief_and_reply_repeated_estimate": replay,
                       "residual_tokens": delta - tokens(m) - prompt - replay})
    init = [e for ev in streams.values() for e in ev if e.get("type") == "system" and e.get("subtype") == "init"]
    small = {p["task"] for p in paired}
    ideal = sum(r["usd"] for r in selected if (r["task"] in small and r["arm"] == "self")
                or (r["task"] not in small and r["arm"] == "ccx2cand"))
    self_total = sum(r["usd"] for r in selected if r["arm"] == "self")
    clean = [p for p in paired if p["clean"]]
    isolated = all((r.get("fingerprint", {}).get("isolation") or {}).get("claude") == "flags" for r in selected)
    hooks_off = all((r.get("fingerprint", {}).get("isolation") or {}).get("hooks") == "disabled" for r in selected)
    return {"evidence": "measured historical streams; attribution estimates are not a causal A/B",
            "groups": groups, "small_pairs": len(paired),
            "small_mean": {k: mean(p[k] for p in paired) for k in paired[0] if k not in ("task", "clean")},
            "clean_small_pairs": len(clean),
            "clean_small_mean": {k: mean(p[k] for p in clean) for k in paired[0] if k not in ("task", "clean")}
                                if clean else None,
            "idealized_cost": {"usd": ideal, "ratio_to_self": ideal / self_total,
                               "assumption": "26 small tasks cost exactly their self pair; 4 delegations unchanged; "
                                             "no guidance cost or routing changes; not a bound or prediction"},
            "guidance_projection": guidance_estimate(mean(p["first_request_context_delta_measured"] for p in paired),
                groups["self"]["lead_requests"]["mean"], groups["self"]["usd"]["mean"], ideal / self_total,
                len(paired) / groups["ccx2cand"]["n"]),
            "zero_components": {"managed_blocks": "0: flags isolation disables managed CLAUDE.md" if isolated else "Unknown",
                                "hook_output": "0: recorded isolation hooks=disabled" if hooks_off else "Unknown",
                                "skill_list": "0" if init and all(e.get("skills") == [] for e in init) else "Unknown"},
            "init_n": len(init), "pairs": paired,
            "limits": "First-context delta includes prompt/framing differences; repeated prompt and chars/4 replay "
                      "are estimates. Residual retains implementation, output and tokenization differences. "
                      "Cache read/write mix affects dollars separately; token reduction is not a cost verdict."}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--artifacts", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    rows = [json.loads(s) for s in a.results.read_text(encoding="utf-8").splitlines() if s.strip()]
    result = analyze(rows, a.artifacts)
    body = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        with a.out.open("w", encoding="utf-8", newline="") as f:
            f.write(body)
    else:
        print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
