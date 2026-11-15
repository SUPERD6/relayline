"""Release preflight (H15): one pass over the main flows on the real CLIs, with tiny tasks, before a version goes out.
Each step is judged by files, records and the ledger, not by what an agent says:

  delegate  a Claude-led task handed to a Codex sub-agent (write, --check); the hidden test passes
  followup  `ccx resume <run> "..."` continues the same sub-session
  stop      a background run stopped with `ccx stop`: state stopped, its tokens counted, one ledger row; then
            `ccx resume` continues the same session
  undo      `ccx undo <run> --apply` puts every file back
  handoff   `ccx handoff` writes its file under .ccx/handoffs/ (the path it prints); the receiving start hook (`ccx mem delta`) shows it, and a model
            given what that hook shows names the next task
  review    a write run with `--review on`: another vendor's model reviews the diff   (needs a 2nd vendor: --agents all)
  reverse   the other direction, Codex lead -> Claude sub-agent (haiku low)           (needs Claude: --agents all)

Everything runs in a throwaway hub (CCX_HUB) and under .ccx/eval/preflight/ in this checkout (git-ignored; a folder
the Codex sandbox can reach, unlike a temp folder in the user profile), with `eval-preflight:` labels and --no-ab.
The spend is read from that hub's ledger after every step; at `--cap` (default $0.50) the remaining steps are skipped.

  python scripts/eval/preflight_e2e.py                    # Codex only (gpt-6-luna low): delegate..handoff
  python scripts/eval/preflight_e2e.py --agents all       # also review and the Claude direction
  python scripts/eval/preflight_e2e.py --only stop        # one step

Rows go to .ccx/eval/preflight.jsonl. Tests use fakes and never call this with real CLIs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, append_jsonl, archive_hub, lead_env, make_repo, run_tree, score  # noqa: E402
from seven_func import last_json, tree_hash  # noqa: E402
from tasks import by_id  # noqa: E402

sys.path.insert(0, str(ROOT))
from ccx import ledger  # noqa: E402
from ccx.config import Paths  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "preflight.jsonl"
CCX = [sys.executable, str(ROOT / "ccx.py")]
CHEAP = ["--to", "codex", "--model", "gpt-6-luna", "--effort", "low"]
ACCEPT = "python -m pytest -q"
STEPS = ("delegate", "followup", "stop", "undo", "handoff", "review", "reverse")
NEEDS_ALL = ("review", "reverse")
# reading only: in a read-only sandbox `python -c "import m1"` would write __pycache__ and the run ends as needs_write
STOP_BRIEF = ("Read each m*.py file one at a time, with a separate command for each file, and explain in two sentences "
              "what its function does. End with a short summary.")


class Preflight:
    def __init__(self, work: Path, cap: float, review: str = "off"):
        # review: "off" keeps every model call on Codex (a write follow-up is reviewed by another vendor by default)
        self.work, self.cap, self.review = work, cap, review
        self.hub = work / "hub"
        self.hub.mkdir(parents=True, exist_ok=True)
        self.env = {**lead_env(), "CCX_HUB": str(self.hub), "CCX_AB_RATE": "0", "CCX_NO_BENCH_REFRESH": "1"}
        self.state: dict = {}

    def ccx(self, *args: str, cwd: Path, timeout: int = 900) -> tuple[int, dict, str]:
        try:
            r = run_tree([*CCX, *args], cwd=cwd, env=self.env, timeout=timeout)
        except subprocess.TimeoutExpired:
            return -9, {}, "timeout"
        return r.returncode, last_json(r.stdout), (r.stderr or "")[-400:]

    def record(self, run_id: str) -> dict:
        try:
            return ledger.load_run(Paths(self.hub), run_id)
        except (FileNotFoundError, ValueError):
            return {}

    def rows(self) -> list[dict]:
        return [r for r in ledger.rows(Paths(self.hub)) if not r.get("type")]

    def spent(self) -> float:
        return round(sum(r.get("ae_usd") or 0 for r in self.rows()), 4)

    # ------------------------------------------------------------------ steps
    def delegate(self) -> dict:
        task = by_id("slugify")
        repo = make_repo(task, self.work / "delegate")
        self.state.update(repo=repo, task=task, h0=tree_hash(repo))
        rc, res, err = self.ccx("run", "--from", "claude", *CHEAP, "--mode", "write", "--new", "--no-ab", "--force",
                                "--review", "off", "--label", "eval-preflight:delegate", "--check", ACCEPT,
                                task["brief"], cwd=repo)
        self.state["run"] = res.get("run_id")
        sc = score(repo, task)
        return {"ok": bool(res.get("ok")) and sc["ok"], "run_id": res.get("run_id"), "status": res.get("status"),
                "hidden_ok": sc["ok"], "pytest": sc["pytest"], "err": err if rc not in (0, 2) else ""}

    def followup(self) -> dict:
        rid, repo = self.state.get("run"), self.state.get("repo")
        if not rid:
            return {"ok": False, "skipped": "no delegate run"}
        rc, res, err = self.ccx("resume", rid, "Add a one-line docstring to slugify. Keep the tests passing.",
                                "--model", "gpt-6-luna", "--effort", "low", "--review", self.review, cwd=repo)
        first, again = self.record(rid), self.record(res.get("run_id") or "")
        same = bool(first.get("session_id")) and first.get("session_id") == again.get("session_id")
        return {"ok": bool(res.get("ok")) and same, "run_id": res.get("run_id"), "same_session": same,
                "status": res.get("status"), "err": err if rc not in (0, 2) else ""}

    def stop(self) -> dict:
        repo = self.work / "stop"
        repo.mkdir(parents=True, exist_ok=True)
        for i in range(1, 13):                           # long enough to be stopped part way
            (repo / f"m{i}.py").write_text(f"def f{i}(x):\n    return x * {i}\n", encoding="utf-8")
        rc, res, err = self.ccx("run", "--from", "claude", *CHEAP, "--mode", "read", "--new", "--no-ab", "--force",
                                "--label", "eval-preflight:stop", "--bg", STOP_BRIEF, cwd=repo)
        rid = res.get("run_id")
        if not rid:
            return {"ok": False, "err": err}
        end = time.time() + 120
        while time.time() < end and not (self.record(rid).get("session_id") and self.record(rid).get("pid")):
            time.sleep(0.5)
        time.sleep(1.5)                                  # stop it part way (a live run of 5 files was done in 6 s)
        _, out, _ = self.ccx("stop", rid, cwd=repo)
        rec = self.record(rid)
        rows = [r for r in self.rows() if r.get("run_id") == rid]
        tokens = sum(sum((r.get("usage4") or {}).values()) for r in rows)
        rc2, res2, err2 = self.ccx("resume", rid, "Continue where you stopped; answer in one short paragraph.",
                                   "--review", self.review, cwd=repo)
        again = self.record(res2.get("run_id") or "")
        same = bool(rec.get("session_id")) and again.get("session_id") == rec.get("session_id")
        ok = (rec.get("state"), rec.get("kind")) == ("stopped", "user_stopped") and len(rows) == 1 and same \
            and bool(res2.get("ok"))
        return {"ok": ok, "run_id": rid, "stop": out, "state": rec.get("state"), "kind": rec.get("kind"),
                "ledger_rows": len(rows), "tokens_counted": tokens, "ae_usd": rows[0].get("ae_usd") if rows else None,
                "resumed_run": res2.get("run_id"), "same_session": same, "resume_status": res2.get("status"),
                "err": err2 if rc2 not in (0, 2) else ""}

    def undo(self) -> dict:
        rid, repo = self.state.get("run"), self.state.get("repo")
        if not rid:
            return {"ok": False, "skipped": "no delegate run"}
        changed = sorted(k for k, v in tree_hash(repo).items() if self.state["h0"].get(k) != v)
        rc, res, err = self.ccx("undo", rid, "--apply", cwd=repo)
        back = tree_hash(repo) == self.state["h0"]
        return {"ok": bool(changed) and back, "changed_before": changed, "restored": back,
                "err": err if rc else ""}

    def handoff(self) -> dict:
        repo = self.state.get("repo") or make_repo(by_id("slugify"), self.work / "handoff")
        rc, out, err = self.ccx("handoff", "--by", "claude", "--to", "codex",
                              "Done: slugify works. Decided: keep it in textutil.py. "
                              "Next: write a test for strings that are only punctuation.", cwd=repo)
        # the handoff's own file under .ccx/handoffs/ (.ccx/handoff.md is only updated while it is ccx's copy)
        doc = Path(out["handoff"]) if out.get("handoff") else None
        written = bool(doc and doc.exists() and "punctuation" in doc.read_text(encoding="utf-8", errors="replace"))
        # what the receiving lead is shown: Codex's start hook runs `ccx mem delta --as codex` (ccx/sync.py)
        try:
            shown = subprocess.run([*CCX, "mem", "delta", "--as", "codex"], cwd=repo, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", env=self.env, timeout=60).stdout
        except subprocess.TimeoutExpired:
            shown = ""
        in_hook = "[ccx handoff to you from claude]" in shown and "punctuation" in shown
        # ... and whether a model taking over from that text knows what to do next (a first live run asked it to
        # read the file instead: gpt-6-luna low answered without opening it)
        rc2, res, err2 = self.ccx("run", "--from", "claude", *CHEAP, "--mode", "read", "--new", "--no-ab", "--force",
                                  "--label", "eval-preflight:handoff",
                                  "At the start of this session you were shown:\n\n" + shown[:1500] +
                                  "\n\nWhat is the next task? Put it in the summary, in one line.", cwd=repo)
        r = self.record(res.get("run_id") or "").get("result") or {}
        said = " ".join([r.get("summary") or "", r.get("next_step") or "", *map(str, r.get("open_questions") or [])])
        # the answer may come in the person's language (a live run answered in Chinese, from the user's Codex rules)
        named = any(w in said.lower() for w in ("punctuation", "标点"))
        return {"ok": written and in_hook and named, "written": written,
                "in_start_hook": in_hook, "said": said[:200], "run_id": res.get("run_id"),
                "err": (err or err2)[-300:] if rc or rc2 not in (0, 2) else ""}

    def review(self) -> dict:
        task = by_id("roman")
        repo = make_repo(task, self.work / "review")
        rc, res, err = self.ccx("run", "--from", "claude", *CHEAP, "--mode", "write", "--new", "--no-ab", "--force",
                                "--review", "on", "--label", "eval-preflight:review", "--check", ACCEPT,
                                task["brief"], cwd=repo)
        rv = res.get("review") or {}
        return {"ok": rv.get("verdict") in ("pass", "issues") and bool(rv.get("by")), "run_id": res.get("run_id"),
                "review": rv, "err": err if rc not in (0, 2) else ""}

    def reverse(self) -> dict:
        task = by_id("paginate")
        repo = make_repo(task, self.work / "reverse")
        rc, res, err = self.ccx("run", "--from", "codex", "--to", "claude", "--model", "haiku", "--effort", "low",
                                "--mode", "write", "--new", "--no-ab", "--force", "--review", "off",
                                "--label", "eval-preflight:reverse", "--check", ACCEPT, task["brief"], cwd=repo)
        sc = score(repo, task)
        return {"ok": bool(res.get("ok")) and sc["ok"], "run_id": res.get("run_id"), "agent": res.get("agent"),
                "hidden_ok": sc["ok"], "err": err if rc not in (0, 2) else ""}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agents", choices=["codex", "all"], default="codex",
                    help="codex: only Codex sub-agents (gpt-6-luna low); all: also review and the Claude direction")
    ap.add_argument("--only", default="", help="comma list of steps (default: every step the agents allow)")
    ap.add_argument("--cap", type=float, default=0.5, help="stop starting steps once the ledger says this much ($)")
    ap.add_argument("--work", default="", help="folder for the hub and the repos (default .ccx/eval/preflight/<ts>)")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")      # agents answer in the person's language; Windows pipes are not utf-8
    work = Path(a.work) if a.work else ROOT / ".ccx" / "eval" / "preflight" / time.strftime("%Y%m%d-%H%M%S")
    pf = Preflight(work, a.cap, review="auto" if a.agents == "all" else "off")
    steps = [s.strip() for s in a.only.split(",") if s.strip()] or list(STEPS)
    results = {}
    for s in steps:
        if s not in STEPS:
            raise SystemExit(f"unknown step {s!r}; steps: {', '.join(STEPS)}")
        if s in NEEDS_ALL and a.agents != "all":
            results[s] = {"ok": None, "skipped": "needs a second vendor: --agents all"}
            continue
        if pf.spent() >= a.cap:
            results[s] = {"ok": None, "skipped": f"spend cap ${a.cap} reached (${pf.spent()})"}
            continue
        t0 = time.time()
        try:
            results[s] = getattr(pf, s)()
        except Exception as e:  # noqa: BLE001 — one broken step must not hide the others
            results[s] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        results[s]["seconds"] = round(time.time() - t0, 1)
        results[s]["spent_so_far"] = pf.spent()
    ran = [r for r in results.values() if r.get("ok") is not None]
    row = {"ts": time.time(), "agents": a.agents, "ok": bool(ran) and all(r["ok"] for r in ran), "spent": pf.spent(),
           "cap": a.cap, "hub": str(pf.hub), "steps": results,
           "ledger": [{k: r.get(k) for k in ("run_id", "label", "kind", "state", "ae_usd", "usage4", "sessions")}
                      for r in pf.rows()]}
    row["archived_sessions"] = archive_hub(pf.hub)    # the throwaway hub's sessions leave the apps' lists
    append_jsonl(Path(a.out) if a.out else OUT, row)
    print(json.dumps(row, ensure_ascii=False, indent=1))
    return 0 if row["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
