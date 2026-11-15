"""E8: a real handover between leads, built by `ccx handoff --from-transcript` from the outgoing lead's session file.

  python scripts/eval/e8_handoff.py run --from claude --to codex
  python scripts/eval/e8_handoff.py run --from codex --to claude [--cut-after 25]
  python scripts/eval/e8_handoff.py ask --to codex --handoff FILE   # any existing handoff (e.g. a real session's)

`run`: in a scratch repo with four independent stub modules (tasks.PARALLEL_TASK), a real outgoing lead
(headless `claude -p` or `codex exec`, session kept on disk) plans the work and stops after part of it. Then
`ccx handoff --from-transcript <from> --no-model` builds the handoff from that session file, and a fresh agent of
the other kind gets only the handoff text, in an empty folder, through `ccx run --mode read`, and must say where
things stand and what comes next. The ground truth (which modules work, which test files exist) is read from the
repo. Judge the answer by hand and record it with `ccx verify <run_id> --ok 1|0 --note ...`.
Results go to .ccx/eval/e8/ (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, append_jsonl, ccx_rows, lead_env, make_repo, run_lead, run_tree  # noqa: E402
from tasks import PARALLEL_TASK  # noqa: E402

from ccx.runners import _codex_kept_settings, bin_argv  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "e8"
OUTGOING = (PARALLEL_TASK["brief"] + "\n\nFirst write your plan as a numbered list. Then work through it in order. "
            "You only have time for a.py and b.py (with tests/test_a.py and tests/test_b.py) in this session: "
            "after those two, stop and end with one line saying what is left. Do not commit.")
CUT = (PARALLEL_TASK["brief"] + "\n\nFirst write your plan as a numbered list. Then work through it in order, "
       "one module and its test at a time. Do not commit.")
ASK = ("You are taking over a coding task from another agent. You have NOT seen its conversation and cannot open its "
       "files: all you have is the handoff note below. From the note alone, answer in your summary:\n"
       "DONE: what has been finished (file by file)\nNEXT: the concrete next steps, in order\n"
       "MISSING: what the note does not tell you that you would need\n"
       "Do not look at any files; do not run commands.\n\n--- handoff note ---\n{note}\n--- end of note ---")


def ccx(*args: str, cwd: Path) -> dict:
    r = subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=lead_env())
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"rc": r.returncode, "stdout": r.stdout[-1500:], "stderr": r.stderr[-1500:]}


def codex_lead(prompt: str, repo: Path, model: str, effort: str, timeout: int = 900) -> dict:
    argv = [*bin_argv("codex"), "exec", "--json", "-m", model, "-c", f'model_reasoning_effort="{effort}"',
            "-c", 'sandbox_mode="workspace-write"', "--skip-git-repo-check", *_codex_kept_settings(), "-C", str(repo), "-"]
    t0 = time.time()
    try:
        r = run_tree(argv, input=prompt, cwd=repo, env=lead_env(), timeout=timeout)
        stdout, rc = r.stdout, r.returncode
    except subprocess.TimeoutExpired as e:      # --cut-after: the lead is stopped mid-work
        stdout = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        rc = -9
    sid, usage = None, {}
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "thread.started":
            sid = ev.get("thread_id")
        elif ev.get("type") == "turn.completed":
            usage = ev.get("usage") or usage
    return {"session": sid, "usage": usage, "rc": rc, "wall_s": round(time.time() - t0, 1)}


def ground_truth(repo: Path) -> dict:
    """Which stub modules now work (a quick call each) and which test files exist."""
    probes = {"a": "from a import is_palindrome as f; assert f('Aba') and not f('ab')",
              "b": "from b import chunks as f; assert f([1,2,3],2)==[[1,2],[3]]",
              "c": "from c import flatten as f; assert f([1,[2,[3]]])==[1,2,3]",
              "d": "from d import camel_to_snake as f; assert f('parseHTTPReply')=='parse_http_reply'"}
    done = {k: subprocess.run([sys.executable, "-c", code], cwd=repo, capture_output=True).returncode == 0
            for k, code in probes.items()}
    tests = sorted(p.name for p in (repo / "tests").glob("test_*.py"))
    return {"modules_working": done, "test_files": tests}


def ask(note: str, to: str, label: str, a, work: Path) -> dict:
    empty = work / "receiver"
    empty.mkdir(parents=True, exist_ok=True)
    brief = work / "ask.md"
    brief.write_text(ASK.format(note=note), encoding="utf-8")
    model = a.codex_model if to == "codex" else a.claude_model
    return ccx("run", "--to", to, "--model", model, "--effort", "low", "--mode", "read", "--new", "--no-ab",
               "--review", "off", "--label", label, "--cwd", str(empty), "--brief-file", str(brief), cwd=empty)


def cmd_run(a) -> int:
    work = Path(a.workdir or tempfile.mkdtemp(prefix=f"ccx-e8-{a.frm}-"))
    repo = make_repo(PARALLEL_TASK, work / "repo")
    prompt, limit = (OUTGOING, 900) if not a.cut_after else (CUT, a.cut_after)
    if a.frm == "claude":
        # session kept on disk (no --no-session-persistence) so --from-transcript can find it
        out = run_lead(prompt, repo, a.claude_model, "low", 0.15, timeout=limit, persist=True)
        lead = {k: out[k] for k in ("cost_usd", "requests", "context_tokens", "wall_s", "answer", "rc")}
        session = None
    else:
        lead = codex_lead(prompt, repo, a.codex_model, "low", timeout=limit)
        session = lead["session"]
    truth = ground_truth(repo)
    h = ccx("handoff", "--from-transcript", a.frm, "--to", a.to, "--no-model",
            *(["--session", session] if session else []), cwd=repo)
    note = Path(h["handoff"]).read_text(encoding="utf-8") if h.get("handoff") else ""
    label = f"eval-e8:{a.frm}-to-{a.to}:{time.strftime('%H%M%S')}"
    res = ask(note, a.to, label, a, work) if note else {}
    row = {"from": a.frm, "to": a.to, "cut_after": a.cut_after, "ts": time.time(), "work": str(work), "outgoing": lead, "truth": truth,
           "handoff_file": h.get("handoff"), "handoff_chars": len(note), "handoff": note,
           "receiver_run": res.get("run_id"), "receiver_summary": res.get("summary"),
           "receiver_next": res.get("next_step"), "receiver_ok": res.get("ok"), "receiver_ae_usd": sum(r.get("ae_usd") or 0 for r in ccx_rows(label))}
    append_jsonl(OUT / "results.jsonl", row)
    print(json.dumps({k: row[k] for k in ("from", "to", "truth", "handoff_file", "handoff_chars", "receiver_run",
                                          "receiver_summary", "receiver_ae_usd")}, ensure_ascii=False, indent=1))
    return 0


def cmd_ask(a) -> int:
    note = Path(a.handoff).read_text(encoding="utf-8")
    work = Path(a.workdir or tempfile.mkdtemp(prefix="ccx-e8-ask-"))
    label = f"eval-e8:file-to-{a.to}:{time.strftime('%H%M%S')}"
    res = ask(note, a.to, label, a, work)
    row = {"from": "file", "to": a.to, "ts": time.time(), "handoff_file": a.handoff, "handoff_chars": len(note),
           "receiver_run": res.get("run_id"), "receiver_summary": res.get("summary"),
           "receiver_next": res.get("next_step"), "receiver_ok": res.get("ok"),
           "receiver_ae_usd": sum(r.get("ae_usd") or 0 for r in ccx_rows(label))}
    append_jsonl(OUT / "results.jsonl", row)
    print(json.dumps(row, ensure_ascii=False, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codex-model", default="gpt-6-luna")
    ap.add_argument("--claude-model", default="haiku")
    ap.add_argument("--workdir", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--from", dest="frm", choices=["claude", "codex"], required=True)
    r.add_argument("--to", choices=["claude", "codex"], required=True)
    r.add_argument("--cut-after", type=int, default=0,
                   help="stop the outgoing lead after this many seconds, mid-work (a quota cut or a crash)")
    r.set_defaults(fn=cmd_run)
    k = sub.add_parser("ask")
    k.add_argument("--to", choices=["claude", "codex"], required=True)
    k.add_argument("--handoff", required=True)
    k.set_defaults(fn=cmd_ask)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
