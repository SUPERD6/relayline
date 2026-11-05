"""Reconcile explicit archived run records, ledger rows and CLI self reports offline."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ccx import runners as _runners  # initialize adapter imports in the CLI's normal order
from ccx.agents import NAMES, vendor
from result_rows import number, rows

BUCKETS = ("input_tokens", "cache_write_tokens", "cached_input_tokens", "output_tokens")


def compare(left, right, tolerance=0.00001):
    if left is None or right is None:
        return "Unknown"
    return "Pass" if abs(left - right) <= tolerance else "Fail"


def total(values):
    ns = [number(v) for v in values]
    return sum(ns) if ns and all(v is not None for v in ns) else None


def stream_reports(manifest, base):
    """Extract native event usage without the production adapter parser; read named log files only."""
    output = []
    for item in manifest:
        path = base / item["path"]
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        cli = item["cli"]
        usage, cost, name = {}, None, None
        if cli == "codex":
            native = [e["usage"] for e in events if e.get("type") == "turn.completed" and e.get("usage")]
            if native and item.get("usage_scope") == "attempt":
                # Native input includes cached input; the ccx fresh bucket does not.
                usage = {"input_tokens": sum(u.get("input_tokens", 0) - u.get("cached_input_tokens", 0) for u in native),
                         "cached_input_tokens": sum(u.get("cached_input_tokens", 0) for u in native),
                         "output_tokens": sum(u.get("output_tokens", 0) for u in native), "cache_write_tokens": 0}
        elif cli == "claude":
            finals = [e for e in events if e.get("type") == "result"]
            if finals:
                final = finals[-1]
                cost = final.get("total_cost_usd")
                models = final.get("modelUsage") or {}
                if models and item.get("usage_scope") == "attempt":
                    mapping = dict(zip(BUCKETS, ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens")))
                    usage = {k: sum(u.get(native, 0) for u in models.values()) for k, native in mapping.items()}
                    name = "+".join(sorted(models))
        elif cli == "dsh":
            native = [e["usage"] for e in events if e.get("type") == "status" and e.get("phase") == "step_end"
                      and e.get("usage")]
            if native and item.get("usage_scope") == "attempt":
                mapping = dict(zip(BUCKETS, ("inputTokens", "cacheWriteTokens", "cacheReadTokens", "outputTokens")))
                usage = {k: sum(u.get(native_key, 0) for u in native) for k, native_key in mapping.items()}
        else:
            raise ValueError("unsupported stream CLI")
        output.append({"run_id": item["run_id"], "attempt": item["attempt"], "usage": usage,
                       "cost_usd": cost, "model": name, "vendor": item.get("observed_vendor")})
    return output


def reconcile(records, ledger_rows, reports, cfg=None):
    """Reports are independently captured normalized CLI observations, keyed by run_id + attempt (0 based)."""
    cfg = cfg or {}
    ledger = {}
    for row in ledger_rows:
        if not row.get("type"):
            ledger.setdefault(row.get("run_id"), []).append(row)
    observed = {}
    for row in reports:
        observed.setdefault((row.get("run_id"), row.get("attempt")), []).append(row)
    output = []
    record_counts = Counter(r.get("run_id") for r in records)
    for record in records:
        rid = record["run_id"]
        matches = ledger.get(rid, [])
        entry = matches[0] if len(matches) == 1 else {}
        attempts = record.get("attempts") or []
        attempt_rows = []
        for i, attempt in enumerate(attempts):
            # Do not use record.to: escalation/fallback can change provider and model.
            agent = attempt.get("agent")
            rung = str(attempt.get("rung") or "").split(":")
            name = attempt.get("model") or (rung[1] if len(rung) > 1 else None)
            matches_cli = observed.get((rid, i), [])
            cli = matches_cli[0] if len(matches_cli) == 1 else {}
            maker = attempt.get("vendor") or (vendor(agent, cfg) if agent in NAMES or agent in cfg.get("providers", {}) else None)
            usage = attempt.get("usage") or {}
            other_usage = cli.get("usage") or {}
            attempt_rows.append({"attempt": i, "agent": agent or "Unknown", "model": name or "Unknown",
                                 "vendor": maker or "Unknown", "cli_vendor": cli.get("vendor", "Unknown"),
                                 "cli_model": cli.get("model", "Unknown"),
                                 "actual_model": cli.get("model") or "Unknown",
                                 "actual_vendor": cli.get("vendor") or "Unknown",
                                 "model_check": "Unknown" if not name or not cli.get("model") else
                                     "Unknown" if name in ("haiku", "sonnet", "opus") and name != cli["model"] else
                                     "Pass" if name == cli["model"] else "Fail",
                                 "vendor_check": "Unknown" if not maker or not cli.get("vendor") else
                                     "Pass" if maker == cli["vendor"] else "Fail",
                                 "cli_report_count": len(matches_cli),
                                 "usage": {k: compare(number(usage.get(k)), number(other_usage.get(k)), 0)
                                           for k in BUCKETS},
                                 "ccx_ae_usd": attempt.get("ae_usd"),
                                 "cli_cost_usd": cli.get("cost_usd"),
                                 # CLI invoice and API-equivalent prices are different rulers.
                                 "cli_cost_check": compare(number(attempt.get("cost_usd")), number(cli.get("cost_usd")))})
        sums = {key: total([a.get(key) for a in attempts]) for key in ("ae_usd", "cost_usd")}
        checks = {key: compare(number(entry.get(key)), sums[key]) for key in sums}
        usage_checks = {k: compare(number((entry.get("usage4") or {}).get(k)),
                                   total([(a.get("usage") or {}).get(k) for a in attempts]), 0) for k in BUCKETS}
        agents = {a.get("agent") for a in attempts if a.get("agent")}
        agent_cost_checks = {agent: compare(number((entry.get("ae_by_agent") or {}).get(agent)),
                                           total([a.get("ae_usd") for a in attempts if a.get("agent") == agent]))
                             for agent in sorted(agents)}
        all_checks = [*checks.values(), *usage_checks.values(), *agent_cost_checks.values()]
        for row in attempt_rows:
            all_checks += [row["model_check"], row["vendor_check"], row["cli_cost_check"], *row["usage"].values()]
            if row["cli_report_count"] > 1:
                all_checks.append("Fail")
        if len(matches) > 1 or record_counts[rid] > 1:
            all_checks.append("Fail")
        verdict = "Fail" if "Fail" in all_checks else "Unknown" if "Unknown" in all_checks or not attempts else "Pass"
        output.append({"run_id": rid, "ledger_row_count": len(matches), "attempts": attempt_rows,
                       "ledger_cost_checks": checks, "ledger_usage_checks": usage_checks,
                       "agent_cost_checks": agent_cost_checks, "verdict": verdict})
    counts = Counter(r["verdict"] for r in output)
    keys = {(r["run_id"], i) for r in records for i, _ in enumerate(r.get("attempts") or [])}
    return {"evidence": "engineering check", "runs": output,
            "counts": {k: counts[k] for k in ("Pass", "Fail", "Unknown")},
            "orphan_cli_reports": sum(len(v) for k, v in observed.items() if k not in keys),
            "limitations": ["Explicit archived files only; no scanning or model calls.",
                            "CLI cost is compared to cost_usd, never to API-equivalent ae_usd.",
                            "Missing CLI vendor/model, usage, costs or ledger rows remain Unknown.",
                            "Provider vendor mapping needs the archived providers config, not today's user config.",
                            "Claude requested aliases versus native model IDs are Unknown without an alias snapshot.",
                            "This checks arithmetic and captured observations, not vendor billing accuracy."]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", action="append", required=True, type=Path, help="one archived run.json; repeat for more")
    p.add_argument("--ledger", required=True, type=Path)
    evidence = p.add_mutually_exclusive_group(required=True)
    evidence.add_argument("--cli-reports", type=Path,
                   help="JSON(L): run_id, attempt, vendor, model, normalized usage, cost_usd")
    evidence.add_argument("--streams", type=Path, help="JSON(L) manifest: run_id, attempt, cli, path, usage_scope")
    p.add_argument("--providers", type=Path, help="archived JSON configuration with providers table (no secrets)")
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    records = [json.loads(path.read_text(encoding="utf-8")) for path in a.run]
    cfg = json.loads(a.providers.read_text(encoding="utf-8")) if a.providers else {}
    reports = rows(a.cli_reports) if a.cli_reports else stream_reports(rows(a.streams), a.streams.parent)
    report = reconcile(records, rows(a.ledger), reports, cfg)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8", newline="")
    else:
        print(text, end="")
    return 1 if report["counts"]["Fail"] or report["orphan_cli_reports"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
