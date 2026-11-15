"""F9: does a Codex sub-agent actually use its own built-in sub-agents, and what does that change?

  python scripts/eval/f9_subagents.py run --repeat 2 [--explicit 1]

The same splittable task (tasks.PARALLEL_TASK: four independent stub modules, each with its own test file) goes
through `ccx run --to codex` with built-in sub-agents on (the default) and off (`--no-subagents`), `--repeat` times
each, in fresh scratch repos. `--explicit N` adds N "on" runs whose brief also asks for sub-agents in so many words
(codex-cli 0.164 tells the model not to spawn any unless the user explicitly asks). For each run: spend, time,
the hidden acceptance test (recorded with `ccx verify`), and whether children really started — from ccx's own
count (ledger `codex_children`) and, independently, from the session files (child rollouts whose parent is the
run's session, and spawn_agent calls in the run's own rollout). Results go to .ccx/eval/f9/ (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, append_jsonl, ccx_rows, ccx_verify, lead_env, make_repo, read_jsonl, run_tree, score  # noqa: E402
from tasks import PARALLEL_TASK  # noqa: E402

from ccx.config import codex_home  # noqa: E402
from ccx.transcript import _codex_sessions  # noqa: E402
from ccx.usage import codex_children  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "f9"
ACCEPT = "python -m pytest -q"
EXPLICIT = ("\n\nUse your own sub-agents for this: spawn one sub-agent per module (a, b, c, d) to work in parallel, "
            "then check their work and run the tests.")


def spawn_calls(session: str) -> int:
    """spawn_agent calls in the run's own rollout file: a direct tool call, or (codex-cli 0.164 code mode) a
    `tools.spawn_agent(` inside an exec call. The tool's definition alone is in every rollout and does not count."""
    for f in _codex_sessions(codex_home())[:300]:
        if session not in f.name:
            continue
        n = 0
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                pl = json.loads(line).get("payload") or {}
            except ValueError:
                continue
            if pl.get("type") in ("function_call", "custom_tool_call"):
                body = str(pl.get("arguments") or "") + str(pl.get("input") or "")
                n += pl.get("name") == "spawn_agent" or body.count("spawn_agent(")
        return n
    return 0


def run_one(arm: str, i: int, a, work: Path) -> dict:
    repo = make_repo(PARALLEL_TASK, work / f"{arm}-{i}")
    label = f"eval-f9:{a.tag}:{arm}:{i}"
    brief = PARALLEL_TASK["brief"] + (EXPLICIT if arm == "explicit" else "")
    argv = [sys.executable, str(ROOT / "ccx.py"), "run", "--to", "codex", "--model", a.model, "--effort", a.effort,
            "--mode", "write", "--new", "--no-ab", "--review", "off", "--label", label, "--check", ACCEPT,
            "--cwd", str(repo), *(["--no-subagents"] if arm == "off" else []), brief]
    t0 = time.time()
    r = run_tree(argv, cwd=repo, env=lead_env(), timeout=1800)
    rows = ccx_rows(label)
    rec = rows[-1] if rows else {}
    sc = score(repo, PARALLEL_TASK)
    sid = rec.get("session_id") or ""
    kids_files = codex_children(sid, t0 - 5) if sid else {}
    row = {"tag": a.tag, "arm": arm, "i": i, "label": label, "run_id": rec.get("run_id"), "rc": r.returncode,
           "ok": sc["ok"], "pytest": sc["pytest"], "ccx_ok": rec.get("ok"), "ae_usd": rec.get("ae_usd"),
           "seconds": rec.get("seconds"), "usage": rec.get("usage"), "attempts": rec.get("attempts"),
           "children_ccx": len(rec.get("codex_children") or {}), "children_files": len(kids_files),
           "spawn_calls": spawn_calls(sid) if sid else 0, "wall_s": round(time.time() - t0, 1)}
    if rec.get("run_id"):
        row["verify"] = ccx_verify(rec["run_id"], sc["ok"], f"eval-f9 hidden acceptance: {sc['pytest']}")
    return row


def cmd_run(a) -> int:
    work = Path(a.workdir or tempfile.mkdtemp(prefix="ccx-f9-"))
    plan = [arm for _ in range(a.repeat) for arm in ("on", "off")] + ["explicit"] * a.explicit
    seen: dict[str, int] = {}
    for arm in plan:
        seen[arm] = seen.get(arm, 0) + 1
        row = run_one(arm, seen[arm], a, work)
        append_jsonl(OUT / "results.jsonl", row)
        print(json.dumps({k: row[k] for k in ("arm", "i", "ok", "ae_usd", "seconds", "children_ccx", "children_files",
                                              "spawn_calls", "run_id")}), flush=True)
    return 0


def cmd_summary(a) -> int:
    rows = [r for r in read_jsonl(OUT / "results.jsonl") if not a.tag or r["tag"] == a.tag]
    out = {}
    for arm in ("on", "off", "explicit"):
        rs = [r for r in rows if r["arm"] == arm]
        if rs:
            out[arm] = {"n": len(rs), "ok": sum(r["ok"] for r in rs),
                        "usd": [r["ae_usd"] for r in rs], "seconds": [r["seconds"] for r in rs],
                        "children_ccx": [r["children_ccx"] for r in rs],
                        "children_files": [r["children_files"] for r in rs],
                        "spawn_calls": [r["spawn_calls"] for r in rs]}
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--repeat", type=int, default=2)
    r.add_argument("--explicit", type=int, default=1)
    r.add_argument("--model", default="gpt-6-luna")
    r.add_argument("--effort", default="low")
    r.add_argument("--tag", default=time.strftime("%Y%m%d"))
    r.add_argument("--workdir", default="")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("summary")
    s.add_argument("--tag", default="")
    s.set_defaults(fn=cmd_summary)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
