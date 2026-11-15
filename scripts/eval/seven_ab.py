"""Seven cores A/B: four paired comparisons on real CLIs, each pair the same task in the same round, the arms in a
random order fixed by --seed (docs/research/2026-10-24-seven-cores-ab.md, section 1).

  deleg   self -> delegate     a fresh headless Claude lead does the task itself, or hands it to Codex via `ccx run`
                               (h11_compare.run_arm); total = lead + sub-agent
  route   fixed -> routed      `ccx run --to auto --minutes M` (task-routing picks agent/model/effort, may escalate)
                               vs one fixed model (--fixed-to/--fixed-model/--fixed-effort, no escalation)
  review  noreview -> review   the same cheap sub-agent with `--review on` (another vendor reads the diff, one fix
                               round) vs `--review off`
  memory  nomem -> mem         the same sub-agent, the repo with or without a project-memory note (`ccx ctx add`) that
                               the brief leaves out and the hidden test checks
          nomem -> hubmem      the same note only in the shared hub journal (`ccx mem add`), nothing in the repo: does
                               it reach the sub-agent through its brief (I6)? Reported as `memory:hubmem`, outside the
                               Holm family of the four primary comparisons
Every memory unit runs in its own throwaway hub (CCX_HUB), so the person's hub is never read or written and no other
note can reach the brief.

Every comparison is arm B minus arm A, i.e. treatment minus control. A hidden acceptance test the agents never see decides right or wrong; it is recorded on the run with `ccx verify`.
Every unit is appended to .ccx/eval/seven/results.jsonl as soon as it ends, so `run` again resumes where it stopped.
Spend is summed before each unit and the batch stops at --budget.

  python scripts/eval/seven_ab.py plan --rounds 3 --seed 7
  python scripts/eval/seven_ab.py run --rounds 3 --seed 7 --budget 6 [--exps route,review] [--dry-run]
  python scripts/eval/seven_ab.py summary [--tag T] [--lead-context 351853]

Needs logged-in `claude` and `codex` CLIs; tests use fakes and never call this with real ones.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from math import comb, sqrt
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ROOT, append_jsonl, archive_hub, boot_ci, ccx_rows, ccx_verify, git, lead_env, make_repo,  # noqa: E402
                    read_jsonl, run_tree, score, sign_test)
from tasks import MEDIUM, MEMORY, by_id as _by_id  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "seven"
ACCEPT = "python -m pytest -q"
CORE = ["slugify", "duration", "intervals", "cli-json"] + [t["id"] for t in MEDIUM]
EXPS = {
    "deleg": {"arms": ("self", "delegate"), "tasks": CORE},
    "route": {"arms": ("fixed", "routed"), "tasks": CORE},
    "review": {"arms": ("noreview", "review"), "tasks": CORE},
    "memory": {"arms": ("nomem", "mem", "hubmem"), "tasks": [t["id"] for t in MEMORY]},   # arms[0] is the control
}
MINUTES = {**{t: 5 for t in CORE}, **{t["id"]: 15 for t in MEDIUM}}       # what --minutes routing is told


def by_id(task_id: str) -> dict:
    for t in MEMORY:
        if t["id"] == task_id:
            return t
    return _by_id(task_id)


def schedule(exps: list[str], rounds: int, seed: int) -> list[dict]:
    """Every (exp, round, task) as one unit per arm in a random arm order; the task order is shuffled per round.
    Rounds come first so a batch cut short still has every experiment's early rounds."""
    out = []
    for rd in range(1, rounds + 1):
        for exp in exps:
            rnd = random.Random(f"{seed}:{exp}:{rd}")
            tasks = list(EXPS[exp]["tasks"])
            rnd.shuffle(tasks)
            for t in tasks:
                arms = list(EXPS[exp]["arms"])
                rnd.shuffle(arms)
                for slot, arm in enumerate(arms):
                    out.append({"exp": exp, "round": rd, "task": t, "arm": arm, "slot": slot})
    return out


def unit_key(u: dict) -> str:
    return f"{u['tag']}:{u['exp']}:{u['round']}:{u['task']}:{u['arm']}"


def ccx_argv(exp: str, arm: str, task: dict, label: str, a, ccx: list[str]) -> list[str]:
    """The `ccx run` command line of a direct (no lead) unit."""
    # --minutes on every arm: a run with an explicit model and no difficulty is not learned by routing (#33)
    base = [*ccx, "run", "--mode", "write", "--new", "--no-ab", "--force", "--label", label, "--check", ACCEPT,
            "--minutes", str(MINUTES.get(task["id"], 5))]
    cheap = ["--to", a.sub_to, "--model", a.sub_model, "--effort", a.sub_effort, "--no-escalate"]
    if exp == "route":
        pick = (["--to", "auto"] if arm == "routed" else
                ["--to", a.fixed_to, "--model", a.fixed_model, "--effort", a.fixed_effort, "--no-escalate"])
        return [*base, *pick, "--review", "off", task["brief"]]
    if exp == "review":
        return [*base, *cheap, "--review", "on" if arm == "review" else "off", task["brief"]]
    if exp == "memory":
        return [*base, *cheap, "--review", "off", task["brief"]]
    raise ValueError(exp)


def _last_json(text: str) -> dict:
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def _tokens(u: dict | None) -> int:
    u = u or {}
    return int(u.get("input", 0) or 0) + int(u.get("cached", 0) or 0) + int(u.get("output", 0) or 0)


def sub_cost(label: str, rows_for=ccx_rows) -> dict:
    """What the sub-agent side spent: the runs under this label plus their independent reviews (label review:<id>)."""
    runs = rows_for(label)
    revs = [r for rid in [x["run_id"] for x in runs] for r in rows_for(f"review:{rid}")]
    return {"run_ids": [r["run_id"] for r in runs], "rungs": [g for r in runs for g in (r.get("rungs") or [])],
            "sub_ae_usd": round(sum(r.get("ae_usd") or 0 for r in runs), 6),
            "review_ae_usd": round(sum(r.get("ae_usd") or 0 for r in revs), 6),
            "sub_tokens": sum(_tokens(r.get("usage")) for r in runs),
            "review_tokens": sum(_tokens(r.get("usage")) for r in revs),
            "sub_seconds": round(sum(r.get("seconds") or 0 for r in runs + revs), 1),
            "sub_ok": [r.get("ok") for r in runs], "kinds": [r.get("kind") for r in runs]}


def run_direct(u: dict, a, work: Path, ccx: list[str], rows_for=ccx_rows, verify=ccx_verify) -> dict:
    task = by_id(u["task"])
    repo = make_repo(task, work / f"{u['exp']}-{u['round']}-{u['task']}-{u['arm']}")
    env, hub = lead_env(), None
    if u["exp"] == "memory":                   # a throwaway hub: the person's hub is never read or written
        hub = work / f"hub-{u['round']}-{u['task']}-{u['arm']}"
        if hub.exists():
            shutil.rmtree(hub)
        hub.mkdir(parents=True)
        env["CCX_HUB"] = str(hub)
        if rows_for is ccx_rows:
            rows_for = lambda lab: ccx_rows(lab, hub=hub)  # noqa: E731
        if verify is ccx_verify:
            verify = lambda rid, ok, note: ccx_verify(rid, ok, note, hub=hub)  # noqa: E731
    if u["exp"] == "memory" and u["arm"] == "hubmem":
        r = subprocess.run([*ccx, "mem", "add", "--by", "user", "--topic", "conventions", task["memory"]],
                           cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if r.returncode:
            raise RuntimeError(f"`ccx mem add` into the eval hub failed: {(r.stderr or r.stdout)[-300:]}")
    if u["exp"] == "memory" and u["arm"] == "mem":
        for step in (["init"], ["add", task["memory"]]):
            subprocess.run([*ccx, "ctx", "--cwd", str(repo), *step], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        ctx = repo / ".ccx" / "context.md"
        if task["memory"] not in (ctx.read_text(encoding="utf-8") if ctx.exists() else ""):
            raise RuntimeError(f"the project memory note did not reach {ctx}")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "project memory")
    label = u["label"]
    t0 = time.time()
    try:
        r = run_tree(ccx_argv(u["exp"], u["arm"], task, label, a, ccx), cwd=repo, env=env, timeout=a.timeout)
        out, rc = r.stdout, r.returncode
    except subprocess.TimeoutExpired:
        out, rc = "", -9
    res = _last_json(out)
    sc = score(repo, task)
    row = {**u, "ts": t0, "wall_s": round(time.time() - t0, 1), "rc": rc, "ok": sc["ok"], "pytest": sc["pytest"],
           "ccx_status": res.get("status"), "ccx_ok": res.get("ok"), "check": res.get("check"),
           "review": res.get("review"), "lead": None, **sub_cost(label, rows_for)}
    if hub and row["run_ids"]:                 # did the note travel in the sub-agent's first prompt?
        pr = hub / "ccx" / "runs" / row["run_ids"][0] / "prompt.md"
        row["note_in_prompt"] = pr.exists() and task["memory"] in pr.read_text(encoding="utf-8", errors="replace")
    if row["run_ids"]:
        row["verify"] = verify(row["run_ids"][-1], sc["ok"], f"eval-7c hidden acceptance: {sc['pytest']}")
    if hub:
        row["archived_sessions"] = archive_hub(hub)    # a throwaway hub: nothing continues its sessions
    return row


def run_deleg(u: dict, a, work: Path, rows_for=ccx_rows) -> dict:
    import h11_compare
    ns = SimpleNamespace(tag=a.tag, sub_model=a.sub_model, sub_effort=a.sub_effort, lead_model=a.lead_model,
                         lead_effort=a.lead_effort, lead_budget=a.lead_budget)
    sub = work / f"deleg-{u['round']}"
    sub.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    row = h11_compare.run_arm(by_id(u["task"]), u["arm"], u["label"], ns, sub)
    row.update(u)
    row["wall_s"] = row["lead"]["wall_s"]
    row["ts"] = t0
    row.update(sub_cost(u["label"], rows_for) if u["arm"] == "delegate" else
               {"run_ids": [], "sub_ae_usd": 0.0, "review_ae_usd": 0.0, "sub_tokens": 0, "review_tokens": 0})
    return row


def unit_usd(r: dict) -> float:
    return ((r.get("lead") or {}).get("cost_usd") or 0) + (r.get("sub_ae_usd") or 0) + (r.get("review_ae_usd") or 0)


def unit_tokens(r: dict) -> int:
    L = r.get("lead") or {}
    return (L.get("context_tokens") or 0) + (L.get("output_tokens") or 0) + (r.get("sub_tokens") or 0) + \
        (r.get("review_tokens") or 0)


def cmd_plan(a) -> int:
    for u in schedule(a.exps.split(","), a.rounds, a.seed):
        print(f"{u['exp']:7} r{u['round']} {u['task']:10} {u['slot']} {u['arm']}")
    return 0


def cmd_run(a, ccx: list[str] | None = None, runners=None) -> int:
    ccx = ccx or [sys.executable, str(ROOT / "ccx.py")]
    out = Path(a.out) if a.out else OUT / "results.jsonl"
    work = Path(a.workdir or tempfile.mkdtemp(prefix="ccx-7c-"))
    done = {unit_key(r) for r in read_jsonl(out)}
    runners = runners or {"direct": run_direct, "deleg": run_deleg}
    print(f"work dir: {work}  results: {out}", flush=True)
    for u in schedule(a.exps.split(","), a.rounds, a.seed):
        u = {**u, "tag": a.tag, "seed": a.seed}
        u["label"] = f"eval-7c:{a.tag}:{u['exp']}:{u['round']}:{u['task']}:{u['arm']}"
        if unit_key(u) in done or (getattr(a, "tasks", "") and u["task"] not in a.tasks.split(",")):
            continue
        total = sum(unit_usd(r) for r in read_jsonl(out))
        if total >= a.budget:
            print(f"budget ${a.budget} reached (${total:.3f}): stopping", flush=True)
            return 2
        if a.dry_run:
            print(f"[dry] {u['label']}")
            continue
        fn = runners["deleg"] if u["exp"] == "deleg" else runners["direct"]
        row = fn(u, a, work) if u["exp"] == "deleg" else fn(u, a, work, ccx)
        append_jsonl(out, row)
        print(f"{u['exp']:7} r{u['round']} {u['task']:10} {u['arm']:9} ok={row['ok']} ${unit_usd(row):.4f} "
              f"tok={unit_tokens(row)} {row['wall_s']}s rungs={row.get('rungs')}", flush=True)
    return 0


# ---------- statistics ----------

def mcnemar_p(b: int, c: int) -> float | None:
    """Exact two-sided McNemar test on the discordant pairs (b: only arm A right, c: only arm B right)."""
    n = b + c
    if not n:
        return None
    return min(1.0, 2 * sum(comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)


def holm(ps: dict[str, float | None]) -> dict[str, tuple[float | None, float | None]]:
    """Holm step-down adjusted p-values (a missing p stays missing and is not counted)."""
    have = sorted((p, k) for k, p in ps.items() if p is not None)
    out, run = {k: (None, None) for k, p in ps.items() if p is None}, 0.0
    for i, (p, k) in enumerate(have):
        run = max(run, min(1.0, (len(have) - i) * p))
        out[k] = (p, round(run, 6))
    return out


def pairs_of(rows: list[dict], exp: str, treat: str | None = None) -> list[tuple[dict, dict]]:
    """(control, treatment) units of the same tag, round and task; the treatment is arms[1] unless named."""
    arms = EXPS[exp]["arms"]
    t = treat or arms[1]
    by: dict = {}
    for r in rows:
        if r.get("exp") == exp:
            by.setdefault((r["tag"], r["round"], r["task"]), {})[r["arm"]] = r
    return [(d[arms[0]], d[t]) for k, d in sorted(by.items()) if arms[0] in d and t in d]


def _metrics(exp: str, lead_context: int) -> dict:
    m = {"total_usd": unit_usd, "total_tokens": unit_tokens, "wall_s": lambda r: r.get("wall_s") or 0}
    if exp == "deleg":
        m.update(lead_requests=lambda r: r["lead"]["requests"],
                 lead_tokens=lambda r: r["lead"]["context_tokens"] + (r["lead"]["output_tokens"] or 0),
                 lead_usd=lambda r: r["lead"]["cost_usd"] or 0,
                 # the same number of lead requests in a long real conversation (J0: median context per request)
                 lead_tokens_at_real_context=lambda r: r["lead"]["requests"] * lead_context)
    return m


def compare(pairs: list[tuple[dict, dict]], f) -> dict:
    """Arm B minus arm A, per pair and per task (the mean over its rounds: the conservative unit)."""
    diffs = [f(b) - f(a) for a, b in pairs]
    by_task: dict = {}
    for (a, b), d in zip(pairs, diffs):
        by_task.setdefault(a["task"], []).append(d)
    td = [statistics.fmean(v) for v in by_task.values()]
    A = [f(a) for a, _ in pairs]
    B = [f(b) for _, b in pairs]
    med = lambda xs: round(statistics.median(xs), 6) if xs else None  # noqa: E731
    ratio = [y / x for x, y in zip(A, B) if x]
    return {"n_pairs": len(diffs), "n_tasks": len(td), "A_median": med(A), "B_median": med(B),
            "diff_median": med(diffs), "diff_mean": round(statistics.fmean(diffs), 6) if diffs else None,
            "ratio_median": med(ratio), "pair_ci95": boot_ci(diffs), "pair_sign_p": sign_test(diffs),
            "task_diff_median": med(td), "task_ci95": boot_ci(td), "task_sign_p": sign_test(td)}


def summarize(rows: list[dict], lead_context: int = 351853) -> dict:
    res = {}
    for exp, spec, B in [(e, s, t) for e, s in EXPS.items() for t in s["arms"][1:]]:
        ps = pairs_of(rows, exp, B)
        if not ps:
            continue
        A = spec["arms"][0]
        key = exp if B == spec["arms"][1] else f"{exp}:{B}"
        ka, kb = sum(p[0]["ok"] for p in ps), sum(p[1]["ok"] for p in ps)
        b = sum(p[0]["ok"] and not p[1]["ok"] for p in ps)
        c = sum(p[1]["ok"] and not p[0]["ok"] for p in ps)
        e = {"arms": [A, B], "pairs": len(ps), "tasks": sorted({p[0]["task"] for p in ps}),
             "ok": {A: ka, B: kb}, "ok_wilson": {A: wilson(ka, len(ps)), B: wilson(kb, len(ps))},
             "ok_diff": round((kb - ka) / len(ps), 3), "discordant": {f"only_{A}": b, f"only_{B}": c},
             "mcnemar_p": mcnemar_p(b, c),
             "ccx_said_ok_but_hidden_failed": sum(bool(r.get("ccx_ok")) and not r["ok"] for p in ps for r in p),
             "metrics": {k: compare(ps, f) for k, f in _metrics(exp, lead_context).items()}}
        if any("note_in_prompt" in p[1] for p in ps):
            e["note_in_prompt"] = sum(bool(p[1].get("note_in_prompt")) for p in ps)
        if exp == "route":                       # p[1] is the treatment arm (routed)
            e["routed_rungs"] = sorted({g for p in ps for g in (p[1].get("rungs") or [])})
            e["escalated"] = sum(len(p[1].get("rungs") or []) > 1 for p in ps)
        if exp == "review":
            vs = [(p[1].get("review") or {}) for p in ps]
            e["review_verdicts"] = {v: sum((x.get("verdict") or "none") == v for x in vs)
                                    for v in sorted({x.get("verdict") or "none" for x in vs})}
            e["first_review_found_issues"] = sum("review_issues" in (p[1].get("kinds") or []) for p in ps)
            e["fix_round_turned_fail_into_pass"] = sum("review_issues" in (p[1].get("kinds") or []) and p[1]["ok"]
                                                       and not p[0]["ok"] for p in ps)
        if exp == "deleg":
            e["did_not_delegate"] = sum(not p[1].get("run_ids") for p in ps)
            e["lead_edited_after_delegating"] = sum((p[1].get("lead_edits") or 0) > 0 for p in ps)
        res[key] = e
    prim = {"deleg": ("total_usd", "task_sign_p"), "route": ("total_usd", "task_sign_p"),
            "review": ("ok", "mcnemar_p"), "memory": ("ok", "mcnemar_p")}
    ps = {e: (res[e]["metrics"][m][k] if m != "ok" else res[e][k]) for e, (m, k) in prim.items() if e in res}
    res["primary_holm"] = {e: {"metric": prim[e][0], "p": p, "p_holm": q} for e, (p, q) in holm(ps).items()}
    res["spend_usd"] = round(sum(unit_usd(r) for r in rows), 4)
    res["units"] = len(rows)
    return res


def cmd_summary(a) -> int:
    rows = read_jsonl(Path(a.file) if a.file else OUT / "results.jsonl")
    if a.tag:
        rows = [r for r in rows if r.get("tag") == a.tag]
    print(json.dumps(summarize(rows, a.lead_context), ensure_ascii=False, indent=1))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("run", cmd_run)):
        r = sub.add_parser(name)
        r.add_argument("--exps", default=",".join(EXPS))
        r.add_argument("--rounds", type=int, default=3)
        r.add_argument("--seed", type=int, default=7)
        r.set_defaults(fn=fn)
        if name == "run":
            r.add_argument("--tag", default="r1")
            r.add_argument("--tasks", default="", help="only these task ids (a pilot)")
            r.add_argument("--budget", type=float, default=6.0, help="stop before a new unit once results reach $")
            r.add_argument("--out", default="")
            r.add_argument("--workdir", default="")
            r.add_argument("--timeout", type=int, default=900)
            r.add_argument("--lead-model", default="sonnet")
            r.add_argument("--lead-effort", default="medium")
            r.add_argument("--lead-budget", type=float, default=0.4, help="claude --max-budget-usd per lead")
            r.add_argument("--sub-to", default="codex")
            r.add_argument("--sub-model", default="gpt-6-luna")
            r.add_argument("--sub-effort", default="low")
            r.add_argument("--fixed-to", default="claude")
            r.add_argument("--fixed-model", default="sonnet")
            r.add_argument("--fixed-effort", default="medium")
            r.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("summary")
    s.add_argument("--file", default="")
    s.add_argument("--tag", default="")
    s.add_argument("--lead-context", type=int, default=351853,
                   help="tokens one request of a real lead re-reads (J0 real --days 7: Claude median)")
    s.set_defaults(fn=cmd_summary)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
